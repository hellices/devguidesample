# Python change stream consumer on AKS

This runnable sample tests MongoDB change streams on Azure DocumentDB with
PyMongo. The cluster has public network access disabled. Pods on AKS reach it
through a private endpoint.

| Path | Purpose |
| --- | --- |
| `infra/main.bicep` | VNet, DocumentDB cluster (M30, one shard), private endpoint and DNS zone, ACR, AKS |
| `app/probe.py` | Checks which change stream options and event fields the cluster returns |
| `app/consumer.py` | Long-running consumer. Writes events to a sink collection and keeps the resume token in a checkpoint collection |
| `app/generator.py` | Deterministic insert, update, replace and delete workload |
| `app/verify.py` | Compares the generator's expected events with a sink collection |
| `infra/lake.bicep` | ADLS Gen2 account with public access and shared keys disabled, blob and dfs private endpoints, a managed identity federated to the `cs-lake` service account |
| `app/lake_export.py` | One export run: resumes from the checkpoint in the lake, writes Parquet chunks and exits |
| `app/verify_lake.py` | Compares the generator's expected events with the Parquet files |
| `airflow/` | DAG that runs `lake_export.py` with `KubernetesPodOperator`, the Airflow image and chart values |
| `k8s/` | Consumer Deployment, generic Job, toolbox pod, lake Job and service account, RBAC for the Airflow scheduler |

## Run

The commands use fictitious names. Replace them with your own values.

```bash
RG=rg-docdb-changestream
az group create -n $RG -l eastus2
az deployment group create -g $RG -f infra/main.bicep \
  -p adminPassword="$ADMIN_PASSWORD"

ACR=docdbcsacrexample
az acr build -r $ACR -t cslab:v1 app/
az aks get-credentials -g $RG -n aks-docdbcs

kubectl create namespace cslab
kubectl -n cslab create secret generic docdb --from-literal=uri="$MONGO_URI"
```

`MONGO_URI` uses the cluster's `mongodb+srv://` connection string. The cluster
host name resolves to the private endpoint address inside the VNet.

The watched collection must exist before the consumer starts. The cluster
under test returned `NamespaceNotFound` (code 26) for a missing collection.

```bash
export IMAGE=docdbcsacrexample.azurecr.io/cslab:v1
envsubst < k8s/toolbox.yaml | kubectl apply -f -
kubectl -n cslab exec cs-toolbox -- python -c \
  "from common import *; get_database(get_client('setup')).create_collection('orders')"

envsubst < k8s/consumer.yaml | kubectl apply -f -

JOB_NAME=gen-r1 SCRIPT=generator.py RUN_ID=r1 DOCS=100000 WORKERS=16 RATE=0 \
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

## Airflow to Parquet

AKS needs the OIDC issuer and workload identity. `infra/main.bicep` enables
both. Deploy the lake next to the cluster.

```bash
ISSUER=$(az aks show -g $RG -n aks-docdbcs --query oidcIssuerProfile.issuerUrl -o tsv)
az deployment group create -g $RG -f infra/lake.bicep -p oidcIssuerUrl="$ISSUER"
export LAKE_CLIENT_ID=<identityClientId output>
export LAKE_URL=https://docdbcslakeexample.dfs.core.windows.net/
```

Install Airflow with the DAG baked into the image. The values use
`LocalExecutor`, so tasks run in the scheduler pod and its service account
launches the export pods in `cslab`.

```bash
az acr build -r $ACR -t cslab-airflow:v1 airflow/
kubectl apply -f k8s/airflow-rbac.yaml
ACR=docdbcsacrexample.azurecr.io AIRFLOW_IMAGE_TAG=v1 envsubst < airflow/values.yaml > values.rendered.yaml
helm repo add apache-airflow https://airflow.apache.org
helm install airflow apache-airflow/airflow --version 1.22.0 -n airflow --create-namespace \
  -f values.rendered.yaml --wait --timeout 10m
```

With chart defaults the database migration job is a post-install hook, so
`--wait` never sees it run and the Airflow pods wait for the migration forever.
`values.yaml` sets `useHelmHooks` and `applyCustomEnv` to `false` for
`migrateDatabaseJob` and `createUserJob`, as the
[chart documentation](https://airflow.apache.org/docs/helm-chart/stable/index.html)
advises for `--wait`.

`lake.yaml` creates the `cs-lake` service account. Apply it once before the
first DAG run, for example with the verifier job.

```bash
JOB_NAME=verify-lake-r1 SCRIPT=verify_lake.py LAKE_PREFIX=orders RUN_ID=r1 MAX_EVENTS=0 \
  FAULT_EXIT_AFTER_UPLOAD=0 envsubst < k8s/lake.yaml | kubectl apply -f -
```

Export behavior:

- A run stops at the first event written after the run started, or when the
  stream has nothing to return. Under steady writes `try_next()` rarely
  returns `None`, so the time boundary is what ends the run.
- A run with no checkpoint starts at the current position of the stream.
- Each chunk is named after the resume token before its first event. A retry
  reads the same events from the same checkpoint and overwrites the same file.
- The checkpoint is `_checkpoints/<stream>.json` in the same file system. It is
  written with an ETag condition after each chunk upload.
- Trigger the DAG with `{"fault_after_chunks": 1}` to make the first try exit
  after one upload and before the checkpoint. The retry finishes the run.
- `max_await_time_ms` is not set unless `MAX_AWAIT_MS` is non-zero. The test
  cluster applied it as a limit on the whole `getMore`. With 1000 ms, resuming
  a backlog larger than the active change log failed with code 50
  (`ExceededTimeLimit`) at the same event on every retry. An idle `getMore`
  without it still returns after about one second.
- With 4 KB documents a 100,000-event chunk is about 374 MB and the export pod
  used up to about 1.9 GiB. For large documents lower `CS_CHUNK_EVENTS` in the
  Airflow scheduler environment. The DAG passes it to the pod as `CHUNK_EVENTS`.
- `consumer.py` always passes `MAX_AWAIT_MS`, 1000 by default. Raise it before
  the consumer resumes a large backlog.

## Clean up

```bash
az group delete -n $RG
```
