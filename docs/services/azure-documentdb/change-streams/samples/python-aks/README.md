# Change stream to Parquet with Airflow on AKS

This runnable sample checks whether an Airflow DAG on AKS can export Azure
DocumentDB change stream events to Parquet files in ADLS Gen2 without losing
or duplicating events. A long-running PyMongo consumer is included as a
baseline. The cluster has public network access disabled. Pods on AKS reach it
through a private endpoint.

| Path | Purpose |
| --- | --- |
| `azure.yaml` | azd project. azd provisions the Azure resources only |
| `infra/main.bicep` | azd entry point. Creates the resource group, deploys the two modules below and outputs the values the Kubernetes steps need |
| `infra/cluster.bicep` | VNet, DocumentDB cluster (M30, one shard), private endpoint and DNS zone, ACR, AKS with OIDC issuer and workload identity |
| `infra/lake.bicep` | ADLS Gen2 account with public access and shared keys disabled, blob and dfs private endpoints, a managed identity federated to the `cs-lake` service account |
| `app/probe.py` | Checks which change stream options and event fields the cluster returns |
| `app/consumer.py` | Long-running consumer. Writes events to a sink collection and keeps the resume token in a checkpoint collection |
| `app/generator.py` | Deterministic insert, update, replace and delete workload |
| `app/verify.py` | Compares the generator's expected events with a sink collection |
| `app/lake_export.py` | One export run: resumes from the checkpoint in the lake, writes the closed 10-minute windows as Parquet chunks of at most 80 MB of row data and exits |
| `app/verify_lake.py` | Compares the generator's expected events with the Parquet files |
| `app/test_*.py` | Local regression tests for event identity/order and atomic checkpoint replacement |
| `app/stale_writer_test.py` | Test only. Stops one export run before its first upload, lets a second run write the same file and checks that the first run cannot overwrite it |
| `airflow/` | DAG that runs `lake_export.py` with `KubernetesPodOperator`, the Airflow image and chart values |
| `k8s/` | Consumer Deployment, generic Job, toolbox pod, lake Job, RBAC for the Airflow scheduler |

Azure resources are provisioned with azd. Images, pods and Airflow are
deployed by hand with `az acr build`, `kubectl` and `helm` so each step can be
inspected. Run every command from this directory.

## Prerequisites

- Azure Developer CLI 1.29 or later and Azure CLI
- `kubectl`, Helm 3.19.0 or later (Airflow chart 1.22.0 requires it) and
  `envsubst` (gettext)
- Permission to create a resource group and role assignments in the
  subscription

## 1. Provision Azure resources with azd

```bash
azd auth login
azd env new docdb-changestream
azd env set AZURE_LOCATION eastus2
export DOCDB_ADMIN_PASSWORD="Cs$(openssl rand -hex 12)Aa9"
azd provision --preview
azd provision
```

`infra/main.parameters.json` maps `adminPassword` to `DOCDB_ADMIN_PASSWORD`.
Export it in the shell instead of storing it with `azd env set`, because azd
environment values are kept in a plain-text `.env` file. azd stops with
`missing required inputs` when the variable is not set. Keep the value
somewhere safe: every later `azd provision` needs the same password, and a
different one changes the administrator password.

`azd provision` creates `rg-<environment name>` and deploys `cluster.bicep`
and `lake.bicep` into it. The lake module receives the AKS OIDC issuer from
the cluster module, so one run sets up the workload identity federation too.

The deployment outputs are saved as azd environment values:

| Value | Used for |
| --- | --- |
| `AZURE_RESOURCE_GROUP`, `AZURE_AKS_CLUSTER_NAME` | `az aks get-credentials` |
| `AZURE_CONTAINER_REGISTRY_NAME`, `AZURE_CONTAINER_REGISTRY_ENDPOINT` | Image builds and image names |
| `DOCDB_CONNECTION_STRING`, `DOCDB_ADMIN_USER` | `MONGO_URI` with the exported password. The connection string keeps the `<user>` and `<password>` placeholders |
| `LAKE_URL` | `k8s/lake.yaml` and `airflow/values.yaml` |
| `LAKE_CLIENT_ID` | Annotation on the `cs-lake` service account |

`.azure/` holds the environment values and is ignored by Git. Do not commit
it.

Load the values into the shell. Later steps read them as variables.

```bash
set -a; eval "$(azd env get-values)"; set +a
```

## 2. Build the images

```bash
export ACR=$AZURE_CONTAINER_REGISTRY_ENDPOINT
export IMAGE=$ACR/cslab:v1
az acr build -r $AZURE_CONTAINER_REGISTRY_NAME -t cslab:v1 app/
az acr build -r $AZURE_CONTAINER_REGISTRY_NAME -t cslab-airflow:v1 airflow/
```

The AKS kubelet identity has `AcrPull` on the registry, so the pods need no
pull secret.

## 3. Connect to AKS and store the connection string

```bash
az aks get-credentials -g $AZURE_RESOURCE_GROUP -n $AZURE_AKS_CLUSTER_NAME
kubectl create namespace cslab

MONGO_URI="${DOCDB_CONNECTION_STRING/<user>:<password>/$DOCDB_ADMIN_USER:$DOCDB_ADMIN_PASSWORD}"
kubectl -n cslab create secret generic docdb --from-literal=uri="$MONGO_URI"
```

The connection string uses `mongodb+srv://`. The cluster host name resolves to
the private endpoint address inside the VNet, so it works only from AKS.

### Use a secondary user for CDC

The commands above use the built-in administrator to keep the lab short. For
a long-running deployment, create a secondary user with the least privilege
needed by each workload. Azure DocumentDB documents two secondary-user role
sets:

- A read-only CDC that stores checkpoints outside DocumentDB can use
  `readAnyDatabase`.
- A consumer that writes its checkpoint or sink back to DocumentDB needs
  `readWriteAnyDatabase` and `clusterAdmin`.

In the service behavior measured on 2026-10-08, a user with only the two
read-write roles could open a plain stream and use `resumeAfter`, but
`startAtOperationTime` returned code 13. Granting `readAnyDatabase` after
creation enabled the same request. Creating the user with all three roles at
once returned code 31, and changing roles through `updateUser` returned code
2. Create the read-write user first, then grant the additional read role.

```javascript
use admin

db.runCommand({
  createUser: "cdc_writer",
  pwd: "<strong-password>",
  roles: [
    { role: "readWriteAnyDatabase", db: "admin" },
    { role: "clusterAdmin", db: "admin" }
  ]
})

db.runCommand({
  grantRolesToUser: "cdc_writer",
  roles: [
    { role: "readAnyDatabase", db: "admin" }
  ]
})
```

Verify the stored roles with `usersInfo`, not `connectionStatus`.
`connectionStatus.authenticatedUserRoles` did not display the granted
`readAnyDatabase` role in this test even though a new connection could use
`startAtOperationTime`.

```javascript
db.runCommand({ usersInfo: "cdc_writer" })
```

Close existing MongoClient pools after the grant and reconnect. To roll back
the added role:

```javascript
db.runCommand({
  revokeRolesFromUser: "cdc_writer",
  roles: [
    { role: "readAnyDatabase", db: "admin" }
  ]
})
```

This role-specific behavior is an observed Azure DocumentDB compatibility
detail, not a behavior described in the
[secondary-user documentation](https://learn.microsoft.com/azure/documentdb/secondary-users).
Recheck it after service upgrades. Do not put real credentials in this
repository or in `azd` environment files.

## 4. Run the consumer

The watched collection must exist before the consumer starts. The cluster
under test returned `NamespaceNotFound` (code 26) for a missing collection.

```bash
envsubst < k8s/toolbox.yaml | kubectl apply -f -
kubectl -n cslab wait --for=condition=Ready pod/cs-toolbox --timeout=5m
kubectl -n cslab exec cs-toolbox -- python -c \
  "from common import *; get_database(get_client('setup')).create_collection('orders')"

envsubst < k8s/consumer.yaml | kubectl apply -f -
kubectl -n cslab rollout status deployment/cs-consumer

JOB_NAME=gen-r1 SCRIPT=generator.py RUN_ID=r1 DOCS=10000 WORKERS=16 RATE=0 \
  envsubst < k8s/job.yaml | kubectl apply -f -
# After the generator finishes and the consumer catches up:
JOB_NAME=verify-r1 SCRIPT=verify.py RUN_ID=r1 DOCS=0 WORKERS=0 RATE=0 \
  envsubst < k8s/job.yaml | kubectl apply -f -
kubectl -n cslab logs job/verify-r1
```

Run `probe.py` the same way with `SCRIPT=probe.py`.

## Consumer behavior

- The sink write is an upsert keyed by the resume token `_data`. A replayed
  event increments `deliveries` on the existing row instead of adding a row.
- On its first start the consumer saves the current time as its start position
  before it reads. A retry before the first checkpoint opens the stream at that
  time with `startAtOperationTime` and reads the same events again.
- The consumer does not set `maxAwaitTimeMS` by default. Microsoft's driver
  compatibility verifier uses one second only to check that a cursor opens.
  MongoDB drivers send this option as `getMore.maxTimeMS`; on DocumentDB a
  historical scan that needs longer can return code 50 instead of an empty
  batch. Set `MAX_AWAIT_MS` only after testing the largest expected backlog.
- The checkpoint is saved after each sink batch. When the stream is idle, the
  consumer saves the post-batch resume token instead.
- Delivery is at-least-once. `FAULT_EXIT_AFTER_WRITE=<events>` makes the
  process exit between the sink write and the checkpoint so you can see the
  replay. Use it only in tests.
- On SIGTERM the consumer writes the pending batch and its checkpoint before
  exiting.
- Deleting a pod makes the ReplicaSet start a replacement while the old pod is
  still terminating. The `Recreate` strategy covers rollouts only, so for a
  short time two consumers can run. The upsert keeps the sink correct.

## 5. Export to Parquet with Airflow

The storage account, its private endpoints and the federated identity already
exist from step 1. Create the `cs-lake` service account that the identity is
federated to. The export pods use it to get a workload identity token.

```bash
kubectl -n cslab create serviceaccount cs-lake
kubectl -n cslab annotate serviceaccount cs-lake \
  azure.workload.identity/client-id="$LAKE_CLIENT_ID"
```

Install Airflow with the DAG baked into the image. The values use
`LocalExecutor`, so tasks run in the scheduler pod. `k8s/airflow-rbac.yaml`
lets the scheduler's service account create the export pods in `cslab`.

```bash
kubectl apply -f k8s/airflow-rbac.yaml
helm repo add apache-airflow https://airflow.apache.org
AIRFLOW_IMAGE_TAG=v1 envsubst < airflow/values.yaml | \
  helm install airflow apache-airflow/airflow --version 1.22.0 \
    -n airflow --create-namespace -f - --wait --timeout 10m
```

With chart defaults the database migration job is a post-install hook, so
`--wait` never sees it run and the Airflow pods wait for the migration forever.
`values.yaml` sets `useHelmHooks` and `applyCustomEnv` to `false` for
`migrateDatabaseJob` and `createUserJob`, as the
[chart documentation](https://airflow.apache.org/docs/helm-chart/stable/index.html)
advises for `--wait`.

The DAG is paused when Airflow first loads it. Unpause it to start the
schedule. Runs start at minute 2, 12, 22 and so on (UTC), two minutes after
each 10-minute window closes.

```bash
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags unpause change_stream_to_parquet
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags list-runs change_stream_to_parquet
```

The first run has no checkpoint, so it saves the current time as its start
position and reads from there. Write events after that run and compare them with the
Parquet files once a later run has exported them. An event is exported by the
first run after its window closes.

```bash
JOB_NAME=gen-af1 SCRIPT=generator.py RUN_ID=af1 DOCS=100000 WORKERS=16 RATE=0 \
  envsubst < k8s/job.yaml | kubectl apply -f -
# After the generator finishes, wait until its last event's window closes and
# the DAG run that starts after that boundary completes successfully:
JOB_NAME=verify-lake-af1 SCRIPT=verify_lake.py LAKE_PREFIX=orders RUN_ID=af1 MAX_EVENTS=0 \
  FAULT_EXIT_AFTER_UPLOAD=0 envsubst < k8s/lake.yaml | kubectl apply -f -
kubectl -n cslab logs job/verify-lake-af1
```

Export behavior:

- Events are grouped by `wallTime` into UTC windows of `WINDOW_MINUTES`
  (10). A run reads only the windows that closed before it started. It stops
  at the first event of the open window without writing it, or when the
  stream has nothing to return. Under steady writes `try_next()` rarely
  returns `None`, so the window boundary is what ends the run.
- A chunk holds events of one window. It ends at the window boundary or
  before its rows pass `CHUNK_BYTES` (80,000,000). The size is the
  plain-encoded row size before compression, so the Parquet file is smaller
  than the limit. A window that gets more data than the limit is split into
  several files. In the test, files cut at the limit were 43.7–46.7 MB with
  1 KB random padding and 13.3–13.4 MB with unpadded documents. The file is a
  fixed share of the limit that depends on how well the data compresses, so
  data that hardly compresses gets files close to 80 MB. Set `CS_CHUNK_BYTES` to 50,000,000 if files must stay under 50 MB.
- An event is written about 2 to 12 minutes after it happens, plus the run
  time: it waits for its window to close and for the offset. The test measured
  p50 454 seconds and a maximum of 731 seconds.
- Rows are moved into Arrow record batches every 10,000 rows, so a chunk is
  not held as Python objects and an Arrow copy at the same time. Peak RSS was
  336 MiB with 80 MB chunks of 1 KB padded documents, 390 MiB at 100 MB and
  620 MiB at 200 MB. These runs used `k8s/lake.yaml` pods, which request
  512Mi and are limited to 4Gi. The pod the DAG starts requests 512Mi and is
  limited to 1Gi. Raise its memory in the DAG when you raise the limit.
- A run with no checkpoint saves the current time as the start position before
  it reads. Its retry starts at the same time.
- Each chunk is written to
  `dt=<date>/hour=<hour>/part-<window start>-<hash>.parquet`. The hash comes
  from the resume token before its first event. A retry reads the same events
  from the same checkpoint and overwrites the same file. A chunk whose events
  have no `wallTime` goes to `dt=unknown`.
- The checkpoint is `_checkpoints/<stream>.json` in the same file system. It is
  replaced with one conditional `Put Blob` after each chunk upload. The small
  JSON write is atomic, so an interrupted replacement leaves the previous
  checkpoint readable.
- A run holds a 20-second lease on `_checkpoints/<stream>.lock` and renews it
  in the background. A second run waits up to 90 seconds for the lease and
  then fails, so two runs do not write chunks at the same time. A lease that
  expires instead of being released can take up to a minute to become
  available again.
- A run can lose the stream lease while it serializes or uploads a chunk. The
  next run then starts from the same checkpoint and may write a shorter chunk
  to the same file. The ETag condition only protects the checkpoint, so a
  chunk is written in three steps:
  1. The run saves the checkpoint again at the same position with the chunk
     path in `writing`, under the ETag condition. This fails if another run
     moved the checkpoint or recorded its own chunk.
  2. It creates the chunk file empty if it is missing and acquires a
     60-second lease on it. A lease left by an older run is broken. It then
     checks that the checkpoint ETag is still the one it saved.
  3. It uploads with the lease ID and saves the checkpoint.

  A later run that writes the same file saves its own record before it breaks
  the lease. So an older run either fails the check in step 2 or gets 412 from
  storage on the upload instead of overwriting the file. One chunk upload has
  to finish within the 60 seconds. A lease proposed when the file is created
  could not be released through the Blob endpoint in the test
  (`LeaseIdMismatchWithLeaseOperation`), so the run creates the file first
  and leases it after.
- Trigger the DAG with `{"fault_after_chunks": 1}` to make the first try exit
  after one upload and before the checkpoint. The retry finishes the run.
- `max_await_time_ms` is not set unless `MAX_AWAIT_MS` is non-zero. The test
  cluster applied it as a limit on the whole `getMore`. With 1000 ms, resuming
  a backlog larger than the active change log failed with code 50
  (`ExceededTimeLimit`) at the same event on every retry. An idle `getMore`
  without it still returns after about one second.
- To change the window, set `CS_WINDOW_MINUTES` in `airflow/values.yaml`. The
  DAG passes it to the pod and builds its schedule from it, so the two stay
  equal. `CS_EXPORT_OFFSET_MIN` (2) delays the run after the window closes.
  `CS_CHUNK_BYTES` sets the file limit.
- `consumer.py` and `lake_export.py` omit `MAX_AWAIT_MS` by default. A short
  value becomes `getMore.maxTimeMS` and can abort historical catch-up.

## 6. Measured scenarios

The published results come from these runs. Each one uses the commands from
steps 4 and 5 with the parameters below. Verify every run with `verify.py`
(consumer) or `verify_lake.py` (Parquet) and the same `RUN_ID`. Both exit with
code 1 on a missing, unexpected or out-of-order event. The generator records a
run as `failed` and exits with code 1 if any write fails, and the verifiers
refuse such a run.

The runs used the sample before these changes: the first-run start position,
the stream lease, the `dt=unknown` partition and the stricter exit codes.
They change only failure paths that the runs did not hit. The changed sample
was then deployed again on Azure with the defaults in this README. r1, the
first DAG run without a checkpoint, a 100,000-document Airflow run and the
Airflow retry passed again. A second export started while another pod held the
stream lease waited about 90 seconds and failed with `LeaseAlreadyPresent`
before it opened the change stream. The `dt=unknown` partition and the
out-of-order failure were not hit there and were checked with local fakes only.

The Airflow rows were run once more on a new deployment after the export
switched to 10-minute windows and 50 MB chunks. The published latency results
come from those runs. The next day the export started to move rows into Arrow
batches and the default limit became 80 MB. The chunk limit comparison, the
Airflow 80 MB backlog and the Airflow retry were run on the same deployment
with that sample. The published file size, memory and 80 MB retry results come
from them. The backlog row was not repeated. The stale writer row was run
with the current sample and, for comparison, with the sample before the chunk
file lease.

| Run | Generator parameters | Extra steps |
| --- | --- | --- |
| r1 | `DOCS=10000 RATE=0` | None |
| r2 | `DOCS=100000 RATE=0` | While the generator runs, delete the consumer pod repeatedly with `kubectl -n cslab delete pod -l app=cs-consumer --wait=false` |
| r3 | `DOCS=100000 RATE=0` | Before the generator, run `kubectl -n cslab set env deployment/cs-consumer FAULT_EXIT_AFTER_WRITE=200`. The container exits after each 200-event write and restarts. Remove it with `FAULT_EXIT_AFTER_WRITE-` after the number of faults you want |
| r4 | `DOCS=130000 RATE=1000` | None |
| Airflow latency | `DOCS=780000 RATE=1000 PAD_BYTES=1000` | DAG unpaused for the whole run |
| Airflow retry | `DOCS=300000 RATE=0 PAD_BYTES=1000` (`DOCS=100000` with 50 MB chunks) | Keep the DAG unpaused. Start the generator right after a window opens so its events fall in that window. After the window closes and before the next scheduled run, in the first two minutes of the next window, run `airflow dags trigger change_stream_to_parquet -c '{"fault_after_chunks": 1}'` in the scheduler container. Do not pause the DAG for this run. Unpausing creates the missed scheduled run at once, and that run can read the events before the triggered run |
| Export memory | `DOCS=100000 RATE=0`, once with `PAD_BYTES=1000` and once with `PAD_BYTES=0` | Pause the DAG. After the window closes, run `lake_export.py` with `k8s/lake.yaml` and wrap it to print `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` at exit |
| Chunk limit comparison | `DOCS=200000 RATE=0 PAD_BYTES=1000`, then `DOCS=450000 RATE=0 PAD_BYTES=0` in the next window | Pause the DAG. Before the generator, run `lake_export.py` once per limit with its own `LAKE_PREFIX`, which is also the stream ID, so each saves its own start position. After each window closes, run the exports again with `CHUNK_BYTES` added to the Job env (50000000, 100000000 or 200000000) and wrapped as in Export memory. Verify each prefix with `verify_lake.py`. The 80 MB memory was measured the same way on the third run of the next row |
| Airflow 80 MB backlog | The two runs above, then `DOCS=300000 RATE=0 PAD_BYTES=1000` in another window | Keep the DAG paused while the three runs write, then unpause it. One scheduled run reads the three windows |
| Airflow backlog | `DOCS=600000 RATE=0 PAD_BYTES=4000` | Pause the DAG, run the generator, then unpause it |
| Stale writer | `DOCS=20000 RATE=0 PAD_BYTES=1000` | Pause the DAG. Before the generator, run `lake_export.py` once per case with its own `LAKE_PREFIX`. After the window closes, run `stale_writer_test.py` with `k8s/lake.yaml` (`SCRIPT=stale_writer_test.py`), once as is and once with `STALL_AT=lease` added to the Job env. It exits with code 1 when the older run overwrote the newer chunk. Then run `lake_export.py` again on each prefix and verify it with `verify_lake.py` |

All runs use `WORKERS=16`. Pause the DAG with `airflow dags pause
change_stream_to_parquet` in the scheduler container.

## Clean up

```bash
azd down
kubectl config delete-context $AZURE_AKS_CLUSTER_NAME
```

`azd down` deletes the resource group and everything in it.
