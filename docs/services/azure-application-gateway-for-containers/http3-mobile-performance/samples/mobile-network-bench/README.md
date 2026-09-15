# HTTP/2 and HTTP/3 mobile-network control

This sample compares strict HTTP/2 and HTTP/3 against the same local server.
It is **not** an AKS, Application Gateway for Containers (AGFC), mobile-device,
browser, or mobile-carrier benchmark. It does not deploy any Azure resources.

The [owning research page](../../index.md) explains why an AGFC HTTP/3 result
cannot be inferred from this control experiment.

## Requirements

- Docker with Linux containers and permission to add `NET_ADMIN` to the two
  isolated test containers.
- Go 1.26 for running the native sample tests (the container builder uses 1.26.5).
- Bash.

## Run

```bash
go test -race ./...
bash run.sh
```

Use `DOCKER_CONTEXT` to select a dedicated runtime without changing the global
Docker context. For example, with an already-running dedicated context:

```bash
DOCKER_CONTEXT=my-test-context SAMPLES=1 bash run.sh
DOCKER_CONTEXT=my-test-context SAMPLES=30 bash run.sh
```

`SAMPLES` is the number of pairs **per workload and network profile**, not the
number of HTTP requests. The default produces 360 measured trials and 3,060
measured requests. An additional 180 requests prewarm connections, and the
initial protocol preflight is excluded from the dataset.

The script bounds `SAMPLES` to 1-100. The client has a 20-second per-request
timeout. No other workload is run concurrently by the script. A failed trial
is preserved in the output, remaining trials are collected, and the command
exits 1. Setup, malformed evidence, and incomplete output are fatal. Do not
treat a nonzero exit as a successful benchmark.

## Topology and network model

```text
strict H2/H3 client -- isolated network -- Linux forwarding router
                                            |
                                      isolated network
                                            |
                              same H2/H3 TLS endpoint and handler
```

There are three containers and two internal Docker networks, with no
published host ports. Both protocols use the same hostname, destination port
8443, route, certificate, TLS 1.3 policy, and response bytes. Static host
resolution avoids external DNS traffic.

| Profile | Router delay per direction | Rate per direction | Random packet loss per direction |
|---|---:|---:|---:|
| `unshaped` | none added | no configured limit | none added |
| `mobile-clean` | 40 ms | 10 Mbit/s | 0% |
| `mobile-loss` | 40 ms | 10 Mbit/s | 1% |

The two shaped profiles target **80 ms additional round-trip delay**, not
40 ms RTT. The loss setting is 1% independently in **each direction**, not
a 1% HTTP failure rate or a 1% round-trip loss setting. Loss seeds are
20260915 and 20260916 on the router's two interfaces.

Impairment is applied on the forwarding router rather than the application
sender's qdisc. TSO, GSO, GRO, and UDP segmentation offload are disabled on
the test interfaces. The script records applied qdiscs, cumulative counters
before/after each profile, offload settings, and ICMP RTT checks. Counter
differences, not the absolute cumulative values, describe a profile.

Linux scheduling and timer granularity still affect the realized delay and
rate. This is a simple packet-level model, not a radio-access-network model:
there is no cellular scheduler, radio power state, signal attenuation,
carrier congestion, burst-loss model, deliberate jitter, or network handover.

## What is measured

- `cold`: a new transport and a new TLS connection for one 1 KiB response.
- `warm`: a new transport, one **unmeasured 1 KiB warmup**, then sixteen
  concurrent 16 KiB responses on that same connection (256 KiB in total).
  This is a pre-established connection, not a long-running steady-state
  congestion-window benchmark.
- HTTP/2-first and HTTP/3-first order alternates between pairs. Each trial
  has its own transport; connection state is not shared across trials.
- Session tickets, TLS session resumption, HTTP compression, and server-side
  0-RTT acceptance are disabled. The forced HTTP/3 client does not pay an
  Alt-Svc discovery request, so `cold` does not model a browser's first visit.
- Every successful response must have the requested wire HTTP version,
  matching ALPN, TLS 1.3, HTTP 200, exact content, and one server connection
  identifier. Warm trials must reuse the warmup's identifier.

`elapsed_ms` runs from releasing the request batch to completion of all body
reads and verification. `headers_ms` is recorded only for the single-request
workload: it measures response-header completion, **not exact first-byte
arrival**. Neither measurement includes rendering, JavaScript execution,
mobile CPU cost, battery usage, or application database time.

The connection identifier comes from this directly connected TLS endpoint.
It cannot prove frontend connection reuse through a reverse proxy. Do not
repurpose the identifier as AGFC frontend-connection evidence.

## Evidence and summaries

Runtime output goes to a unique ignored `evidence/<run-id>/` directory:

- `all.jsonl` and per-profile JSONL: every trial, including failures, payload
  bytes, negotiated protocols, connection identifiers, and elapsed time.
- `summary.json`: success/failure counts and nearest-rank p50/p95 over
  **successful trials only**. Failed-only groups have `null`, not zero,
  latency. `incomplete_requests` includes requests not sent after a failed
  warmup; `warmup_failures` identifies these trials.
- qdisc, ping, offload, environment, and package-version files: verify the
  configured model and the actual runtime. A nonempty qdisc backlog can
  include connection-close packets after response measurement.
- `preflight.jsonl` and `server.log`: diagnostics, not performance samples.

To recompute a summary without Docker:

```bash
go run . summarize < evidence/<run-id>/all.jsonl
```

The reader rejects truncated JSON and success records without matching
protocol, payload, connection, and timing evidence. The runner also checks
the expected number of records for each profile. A summary alone is not
proof that an arbitrary manually supplied file contains a complete run.

The container base images are digest-pinned; Go dependencies are locked by
the module files. Alpine package repositories can change, so the run also
records installed package versions. Identical seeds do not guarantee
identical wall-clock measurements or identical packet schedules.

### Recorded run

The reviewed [2026-09-15 dataset](results/2026-09-15/) contains:

- `trials.jsonl`: 360 measured trials, copied without altering their values.
- `summary.json`: the exact runner output, independently recomputed.
- `environment.json`: scope, versions, method, counts, and SHA-256 checksums.
- `network.json`: original qdisc snapshots plus address-free RTT aggregates
  and the relevant observed offload settings.

```bash
go run . summarize < results/2026-09-15/trials.jsonl
shasum -a 256 results/2026-09-15/trials.jsonl results/2026-09-15/summary.json
```

The dataset includes the unshaped results where HTTP/3 was slower, and the
lossy cold-connection p95 regression. It is not an AGFC benchmark and does
not establish a production p95 or a universal HTTP/3 improvement percentage.

## Cleanup and safety

The script removes only its uniquely named containers, networks, certificate
volume, and run image, including on normal failure, SIGINT, or SIGTERM.
Downloaded base images and build cache can remain. SIGKILL or host failure
cannot execute shell cleanup; inspect and remove only that run's named
resources in that case. Do not use a global Docker prune on a shared host.

Certificates are generated solely for the experiment, trusted explicitly by
the client, and deleted with the temporary volume. Containers receive only
`NET_ADMIN`, not host networking or privileged mode. No Azure/Kubernetes
credentials, cloud deployment, or changes to the host's interfaces and
default Docker/Kubernetes contexts are required.

Review any runtime logs before publishing. The recorded public dataset must
exclude certificates, actual target addresses, resource identifiers, and
machine-specific paths. Keep unreviewed runtime evidence under `evidence/`.
