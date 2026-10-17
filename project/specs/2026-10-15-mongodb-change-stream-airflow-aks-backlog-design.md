# MongoDB Change Stream Airflow on AKS Backlog Design

## Goal

Extend the existing Azure DocumentDB change-stream sample with an
evidence-backed architecture for draining a backlog through an Apache Airflow
DAG on AKS. Provision the sample in the authenticated Azure subscription,
create a controlled backlog, verify the drain, remove the resources, publish
the sanitized results, and open a pull request.

## Assumptions

- "MongoDB" means Azure DocumentDB's MongoDB-compatible endpoint because the
  repository already owns a runnable Azure DocumentDB sample and the requested
  deployment target is an Azure subscription.
- The experiment is disposable. It uses a single-shard, non-HA test cluster
  and the existing sample's four-node AKS default, then deletes the resource
  group after evidence is collected.
- A source collection has one resume-token chain that this sample consumes
  serially. Parallel workers may process independent stream IDs, collections,
  or tenant partitions, but must not advance one checkpoint concurrently. The
  current verifier checks each document's lifecycle order; it does not claim
  or verify global ordering across different documents.
- The public result contains no subscription, tenant, resource-group, host,
  credential, or user identifiers.

## Architecture Options

### 1. One serial catch-up lane per stream

Airflow starts one `KubernetesPodOperator` task for a stream. The task resumes
from an ADLS Gen2 checkpoint, reads every closed event-time window, writes
deterministically named Parquet chunks, and checkpoints after each chunk.
`max_active_runs=1`, an ADLS lease, and conditional checkpoint writes enforce
one writer.

This is the selected implementation. It reuses the tested sample, preserves
serial checkpoint progression and the per-document ordering checked by the
verifier, and adds no service merely to handle a bounded operational backlog.

### 2. Durable ingestion buffer before Airflow

A continuously running change-stream capture service writes raw events to
Event Hubs or an append-only ADLS landing zone. Airflow consumes independent
buffer partitions and performs batch transformations.

This is the production escalation path when direct drain time approaches the
available change-stream history, ingestion must remain available while
Airflow is down, or transformation throughput needs independent horizontal
scaling. It is not provisioned in this experiment because it adds a service
and changes the data path beyond the requested Airflow-on-AKS validation.

### 3. Multiple readers sharing one checkpoint

Several Airflow tasks read the same stream and race to advance one resume
token. This is rejected. It can reorder events, overwrite chunks after a
lease loss, and produce a checkpoint that does not describe the published
data. More pods do not make one ordered token chain safely parallel.

## Selected Design

### Control plane

- Airflow runs on AKS and creates a short-lived export pod for each DAG run.
- The DAG uses `catchup=False` so Airflow does not synthesize historical
  scheduler intervals. The export task owns data catch-up by reading from the
  external checkpoint to the first event in the current open window.
- `max_active_runs=1` prevents expected overlap. The storage lease and ETag
  checks remain the correctness boundary when retries or delayed pods overlap.
- Production guidance separates scheduler capacity from export capacity:
  external PostgreSQL for Airflow metadata, a protected system node pool for
  Airflow, and a workload node pool for export pods.

### Data plane

1. The export pod acquires the stream lock and loads the resume token from
   ADLS Gen2.
2. It reads only closed UTC windows from Azure DocumentDB. A short
   `maxAwaitTimeMS` is not set because it can terminate historical `getMore`
   calls.
3. It bounds memory with deterministic, event-derived Parquet chunks.
4. Before upload it records the target path conditionally, leases the chunk,
   verifies that its checkpoint claim is still current, uploads, and advances
   the checkpoint.
5. A retry resumes at the previous committed chunk and overwrites the same
   deterministic path, yielding at-least-once processing with idempotent
   output.

### Backlog policy

For backlog `B`, arrival rate `lambda`, and measured drain rate `mu`, the
estimated drain time is:

```text
drain_time = B / (mu - lambda), when mu > lambda
```

The direct architecture is acceptable only when the estimate plus a recovery
margin is less than the remaining change-stream history. If `mu <= lambda`,
or the estimate crosses the history headroom, operators must increase
capacity across independent stream partitions or switch to the durable-buffer
architecture. Increasing readers on one stream is not an approved response.

Required operational signals are checkpoint age, oldest processed event age,
events and bytes per second, task and pod start delay, estimated drain time,
history headroom, retry count, lease/ETag conflicts, and history-lost or query
timeout errors.

## Azure Experiment

Use the existing `python-aks` sample in a new, uniquely named azd environment:

1. Provision Azure DocumentDB, private networking, ACR, AKS, and ADLS Gen2.
2. Build the application and Airflow images in ACR.
3. Deploy the namespace, workload identity, Airflow, and an initial no-data
   DAG run to create the checkpoint.
4. Pause the DAG and generate a controlled backlog in a closed 10-minute
   window.
5. Resume or manually trigger one DAG run, capture its `export_done` event,
   and run `verify_lake.py`.
6. Record expected and received event counts, duplicate and missing counts,
   per-document order violations, file count, elapsed time, and drain
   throughput.
7. Delete the experiment resource group and confirm removal.

Success requires:

- expected events equal received events;
- zero missing, unexpected, duplicate, and per-document out-of-order events;
- all files stay within one event-time window and the configured chunk bound;
- the run reports `caught_up=true`;
- measured drain throughput exceeds the workload's generation rate;
- no Azure identifiers or secrets appear in committed evidence.

Global ordering across different documents is outside this experiment's
success criteria and must not be inferred from the per-document check.

If regional capacity, quota, or a service deployment blocks the preferred
shape, use the smallest compatible SKU or another supported region and record
the deviation. Do not convert a failed deployment into a claimed measurement.

## Documentation Changes

- Add `backlog-architecture/index.md` as the second child of the existing
  Azure DocumentDB change-stream topic.
- Explain the selected topology, capacity equation, alert thresholds,
  partitioning boundary, escalation path, and the new subscription result.
- Update the topic entry to link the focused backlog guidance.
- Add the new child slug to the existing sample's `used_by` list.
- Update the sample README only where a reproducible backlog procedure or the
  newly observed result differs from the existing instructions.
- Reuse the existing architecture asset; do not add generated Azure evidence
  or local deployment state.

The public page is a `research` document because it compares architecture
choices and preserves a dated measurement. Current operational advice is
clearly separated from the experiment's observed values.

## Error Handling and Safety

- Provisioning, image build, Helm, workload, verifier, and cleanup failures are
  surfaced with their failing command and sanitized diagnostics.
- The checkpoint and deterministic output protocol are unchanged by the
  documentation work.
- Cleanup is attempted after both successful and failed experiments. Local
  `.azure/`, kubeconfig state, generated `site/`, and evidence files are not
  committed.
- The PR body reports every validation command and its result and follows the
  repository pull-request template.

## Validation

- Run the sample's focused Python tests.
- Run Bicep build or azd preview before provisioning.
- Complete the live Azure scenario and verifier.
- Run the full repository documentation validation contract.
- Review the branch diff for identifiers, generated artifacts, and unrelated
  changes before committing and opening the PR.

## Non-goals

- Production HA or failover testing for Azure DocumentDB.
- Multi-shard preview behavior.
- Building the Event Hubs buffer architecture in this change.
- Treating Kubernetes pod autoscaling as a way to parallelize one resume-token
  chain.
- Proving global event order across different documents.
