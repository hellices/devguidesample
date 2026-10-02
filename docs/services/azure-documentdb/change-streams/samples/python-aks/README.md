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
| `app/lake_export.py` | One export run: resumes from the checkpoint in the lake, writes Parquet chunks and exits |
| `app/verify_lake.py` | Compares the generator's expected events with the Parquet files |
| `airflow/` | DAG that runs `lake_export.py` with `KubernetesPodOperator`, the Airflow image and chart values |
| `k8s/` | Consumer Deployment, generic Job, toolbox pod, lake Job, RBAC for the Airflow scheduler |

Azure resources are provisioned with azd. Images, pods and Airflow are
deployed by hand with `az acr build`, `kubectl` and `helm` so each step can be
inspected. Run every command from this directory.

## Prerequisites

- Azure Developer CLI 1.29 or later and Azure CLI
- `kubectl`, `helm` and `envsubst` (gettext)
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
5-minute schedule.

```bash
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags unpause change_stream_to_parquet
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags list-runs change_stream_to_parquet
```

The first run has no checkpoint, so it starts at the current position of the
stream and saves it. Write events after that run and compare them with the
Parquet files once a later run has exported them.

```bash
JOB_NAME=gen-af1 SCRIPT=generator.py RUN_ID=af1 DOCS=100000 WORKERS=16 RATE=0 \
  envsubst < k8s/job.yaml | kubectl apply -f -
# After the next DAG run finishes:
JOB_NAME=verify-lake-af1 SCRIPT=verify_lake.py LAKE_PREFIX=orders RUN_ID=af1 MAX_EVENTS=0 \
  FAULT_EXIT_AFTER_UPLOAD=0 envsubst < k8s/lake.yaml | kubectl apply -f -
kubectl -n cslab logs job/verify-lake-af1
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

## 6. Measured scenarios

The published results come from these runs. Each one uses the commands from
steps 4 and 5 with the parameters below. Verify every run with `verify.py`
(consumer) or `verify_lake.py` (Parquet) and the same `RUN_ID`.

| Run | Generator parameters | Extra steps |
| --- | --- | --- |
| r1 | `DOCS=100000 RATE=0` | None |
| r2 | `DOCS=100000 RATE=0` | While the generator runs, delete the consumer pod repeatedly with `kubectl -n cslab delete pod -l app=cs-consumer --wait=false` |
| r3 | `DOCS=100000 RATE=0` | Before the generator, run `kubectl -n cslab set env deployment/cs-consumer FAULT_EXIT_AFTER_WRITE=200`. The container exits after each 200-event write and restarts. Remove it with `FAULT_EXIT_AFTER_WRITE-` after the number of faults you want |
| r4 | `DOCS=300000 RATE=1000` | None |
| Airflow latency | `DOCS=780000 RATE=1000 PAD_BYTES=1000` | DAG unpaused for the whole run |
| Airflow retry | `DOCS=100000 RATE=0 PAD_BYTES=1000` | Pause the DAG, run the generator, then `airflow dags trigger change_stream_to_parquet -c '{"fault_after_chunks": 1}'` in the scheduler container |
| Airflow backlog | `DOCS=600000 RATE=0 PAD_BYTES=4000` | Pause the DAG, run the generator, then unpause it |

All runs use `WORKERS=16`. Pause the DAG with `airflow dags pause
change_stream_to_parquet` in the scheduler container.

## Clean up

```bash
azd down
kubectl config delete-context $AZURE_AKS_CLUSTER_NAME
```

`azd down` deletes the resource group and everything in it.
