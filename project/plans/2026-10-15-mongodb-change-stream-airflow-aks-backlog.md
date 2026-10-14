# MongoDB Change Stream Airflow on AKS Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the existing Azure DocumentDB change-stream sample in the authenticated Azure subscription, measure an Airflow-on-AKS backlog drain, publish the sanitized architecture and result, and open a pull request.

**Architecture:** Keep one ordered catch-up lane per resume-token chain. An Airflow `KubernetesPodOperator` pod resumes from an ADLS Gen2 checkpoint, writes deterministic Parquet chunks, and advances the checkpoint under leases and ETag conditions; independent stream IDs are the only horizontal-scaling boundary. If measured drain capacity cannot fit inside the remaining change-stream history, the public guidance escalates to a durable Event Hubs or raw-ADLS ingestion buffer instead of adding concurrent readers to one stream.

**Tech Stack:** Azure Developer CLI, Azure CLI, Bicep, Azure DocumentDB, AKS, ACR, ADLS Gen2, Apache Airflow 3.2.2, Helm chart 1.22.0, Kubernetes, Python 3, PyMongo, PyArrow, MkDocs

## Global Constraints

- Treat Azure DocumentDB's MongoDB-compatible endpoint as the source for this repository-owned experiment.
- Use a disposable single-shard, non-HA DocumentDB test cluster and the existing sample's four-node AKS default, then delete the resource group after evidence collection.
- Never publish subscription, tenant, resource-group, host, credential, kubeconfig, or user identifiers.
- Keep one writer per `STREAM_ID`; scale only across independent stream IDs, collections, or tenant partitions.
- Preserve the existing checkpoint, lease, deterministic chunk, and retry protocol.
- Do not commit `.azure/`, kubeconfig, `evidence/`, generated `site/`, or raw command logs.
- Verify every Microsoft and Azure product claim with the repository `verify-with-microsoft-learn` skill before publication.
- Run the complete documentation validation contract before the implementation commit.
- Include `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` in every implementation commit.

## File Structure

- Create `docs/services/azure-documentdb/change-streams/backlog-architecture/index.md`: focused architecture decision, capacity model, operational thresholds, escalation path, and dated live result.
- Modify `docs/services/azure-documentdb/change-streams/index.md`: point readers from the topic entry to the backlog-specific child.
- Modify `docs/services/azure-documentdb/change-streams/samples/python-aks/sample.yml`: expose the existing runnable sample on the new child page.
- Modify `docs/services/azure-documentdb/change-streams/samples/python-aks/README.md`: add only the reproducible 2026-10-15 backlog scenario and sanitized result if the live run succeeds.
- Store raw and sanitized experiment evidence under `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/`; none of it is committed.

---

### Task 1: Verify sources and the existing sample baseline

**Files:**
- Read: `docs/services/azure-documentdb/change-streams/index.md`
- Read: `docs/services/azure-documentdb/change-streams/measurements/index.md`
- Read: `docs/services/azure-documentdb/change-streams/samples/python-aks/README.md`
- Read: `docs/services/azure-documentdb/change-streams/samples/python-aks/app/test_lake_export.py`
- Read: `docs/services/azure-documentdb/change-streams/samples/python-aks/app/test_verification.py`

**Interfaces:**
- Consumes: the existing `python-aks` sample and its public source list.
- Produces: verified source notes and a passing local baseline before Azure resources are created.

- [ ] **Step 1: Load the required official-source workflow**

Invoke the repository `verify-with-microsoft-learn` skill. Search Microsoft
Learn for Azure DocumentDB change streams, AKS workload identity, AKS cluster
autoscaler behavior, and Airflow-on-AKS operational dependencies. Fetch the
full selected pages and compare their scope with the claims planned for the
new page.

Expected: every Azure claim used by the new page is either supported by a
fetched official page or explicitly labeled as an experiment observation.

- [ ] **Step 2: Verify upstream semantics outside Microsoft's authority**

Fetch the MongoDB change-stream specification and the Apache Airflow
documentation for `catchup`, `max_active_runs`, and
`KubernetesPodOperator`.

Expected: the design distinguishes Airflow scheduler catch-up from
resume-token data catch-up and does not claim that Kubernetes can parallelize
one ordered checkpoint.

- [ ] **Step 3: Run the sample regression tests**

Run from
`docs/services/azure-documentdb/change-streams/samples/python-aks`:

```bash
python -m unittest discover -s app -p 'test_*.py' -v
```

Expected: all tests pass. If imports are missing, install only
`app/requirements.txt` into an isolated virtual environment under the session
folder and rerun the same command.

- [ ] **Step 4: Compile every Bicep entry point**

```bash
az bicep build --file infra/main.bicep --stdout >/dev/null
az bicep build --file infra/cluster.bicep --stdout >/dev/null
az bicep build --file infra/lake.bicep --stdout >/dev/null
```

Expected: each command exits 0 with no Bicep error.

---

### Task 2: Provision the disposable Azure environment

**Files:**
- Use: `docs/services/azure-documentdb/change-streams/samples/python-aks/azure.yaml`
- Use: `docs/services/azure-documentdb/change-streams/samples/python-aks/infra/main.bicep`
- Use: `docs/services/azure-documentdb/change-streams/samples/python-aks/airflow/values.yaml`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/kubeconfig`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/setup.log`

**Interfaces:**
- Consumes: authenticated `az` and `azd`, compiled Bicep, and the existing sample manifests.
- Produces: an AKS cluster with Airflow, a private Azure DocumentDB endpoint, ACR images, ADLS Gen2, and an initialized change-stream checkpoint.

Run every step in this task from
`docs/services/azure-documentdb/change-streams/samples/python-aks`.

- [ ] **Step 1: Confirm authentication without printing identifiers**

```bash
az account show --query state -o tsv
az provider show --namespace Microsoft.DocumentDB --query registrationState -o tsv
az provider show --namespace Microsoft.ContainerService --query registrationState -o tsv
az provider show --namespace Microsoft.Storage --query registrationState -o tsv
```

Expected: `Enabled` followed by three `Registered` values.

- [ ] **Step 2: Create one isolated azd environment and preview it**

Run the preview and provisioning in the same shell so the generated
administrator password is never persisted:

```bash
set -euo pipefail
EVIDENCE=/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15
ENV_NAME="cs-backlog-20261015-$(openssl rand -hex 3)"
mkdir -p "$EVIDENCE"
azd env new "$ENV_NAME"
azd env set AZURE_LOCATION eastus2
export DOCDB_ADMIN_PASSWORD="Cs$(openssl rand -hex 12)Aa9"
azd provision --preview
azd provision
```

Expected: the preview reports no validation error and provisioning outputs
the AKS, ACR, DocumentDB, storage, and workload-identity values.

- [ ] **Step 3: Build both container images**

In the same shell, load azd outputs and build versioned images:

```bash
set -a
eval "$(azd env get-values)"
set +a
export ACR="$AZURE_CONTAINER_REGISTRY_ENDPOINT"
export IMAGE="$ACR/cslab:backlog-20261015"
az acr build -r "$AZURE_CONTAINER_REGISTRY_NAME" -t cslab:backlog-20261015 app/
az acr build -r "$AZURE_CONTAINER_REGISTRY_NAME" -t cslab-airflow:backlog-20261015 airflow/
```

Expected: both ACR builds finish with `Run ID` status `Succeeded`.

- [ ] **Step 4: Configure the isolated kubeconfig and Kubernetes secrets**

Still in the shell that owns `DOCDB_ADMIN_PASSWORD`:

```bash
export KUBECONFIG="$EVIDENCE/kubeconfig"
az aks get-credentials \
  -g "$AZURE_RESOURCE_GROUP" \
  -n "$AZURE_AKS_CLUSTER_NAME" \
  --file "$KUBECONFIG"
kubectl create namespace cslab
MONGO_URI="${DOCDB_CONNECTION_STRING/<user>:<password>/$DOCDB_ADMIN_USER:$DOCDB_ADMIN_PASSWORD}"
kubectl -n cslab create secret generic docdb --from-literal=uri="$MONGO_URI"
unset MONGO_URI DOCDB_ADMIN_PASSWORD
```

Expected: `kubectl get nodes` shows two `Ready` nodes and the `docdb` secret
exists without its value being printed.

- [ ] **Step 5: Create the source collection and workload identity**

```bash
set -a
eval "$(azd env get-values)"
set +a
export KUBECONFIG="$EVIDENCE/kubeconfig"
export ACR="$AZURE_CONTAINER_REGISTRY_ENDPOINT"
export IMAGE="$ACR/cslab:backlog-20261015"
export RUN_ID=setup DOCS=0 WORKERS=1 RATE=0 SINK= PAD_BYTES=0
envsubst < k8s/toolbox.yaml | kubectl apply -f -
kubectl -n cslab wait --for=condition=Ready pod/cs-toolbox --timeout=5m
kubectl -n cslab exec cs-toolbox -- python -c \
  "from common import *; get_database(get_client('setup')).create_collection('orders')"
kubectl -n cslab create serviceaccount cs-lake
kubectl -n cslab annotate serviceaccount cs-lake \
  azure.workload.identity/client-id="$LAKE_CLIENT_ID"
kubectl apply -f k8s/airflow-rbac.yaml
```

Expected: the collection command exits 0 and the `cs-lake` service account has
the workload-identity client annotation.

- [ ] **Step 6: Install Airflow and initialize the checkpoint**

```bash
set -a
eval "$(azd env get-values)"
set +a
export KUBECONFIG="$EVIDENCE/kubeconfig"
export ACR="$AZURE_CONTAINER_REGISTRY_ENDPOINT"
export IMAGE="$ACR/cslab:backlog-20261015"
helm repo add apache-airflow https://airflow.apache.org
helm repo update
AIRFLOW_IMAGE_TAG=backlog-20261015 envsubst < airflow/values.yaml | \
  helm install airflow apache-airflow/airflow --version 1.22.0 \
    -n airflow --create-namespace -f - --wait --timeout 15m
kubectl -n airflow rollout status statefulset/airflow-scheduler --timeout=10m
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags list | grep change_stream_to_parquet
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags trigger change_stream_to_parquet -r checkpoint-init-20261015
```

Poll `airflow dags list-runs change_stream_to_parquet --output json` until the
`checkpoint-init-20261015` run is `success`.

Expected: the DAG is loaded, the manual run succeeds while the DAG remains
paused, and the first checkpoint is created before test data is written.

---

### Task 3: Measure backlog drain and remove Azure resources

**Files:**
- Use: `docs/services/azure-documentdb/change-streams/samples/python-aks/k8s/job.yaml`
- Use: `docs/services/azure-documentdb/change-streams/samples/python-aks/k8s/lake.yaml`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/generator.log`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/export.log`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/verify.json`
- Create locally only: `/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/summary.json`

**Interfaces:**
- Consumes: the initialized DAG and Kubernetes secret from Task 2.
- Produces: a sanitized evidence summary containing only workload counts,
  timings, rates, file statistics, and correctness counters.

Run every step in this task from
`docs/services/azure-documentdb/change-streams/samples/python-aks`.

- [ ] **Step 1: Generate a rate-limited backlog while the DAG stays paused**

```bash
set -a
eval "$(azd env get-values)"
set +a
EVIDENCE=/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15
export KUBECONFIG="$EVIDENCE/kubeconfig"
export ACR="$AZURE_CONTAINER_REGISTRY_ENDPOINT"
export IMAGE="$ACR/cslab:backlog-20261015"
export JOB_NAME=gen-backlog-20261015 SCRIPT=generator.py RUN_ID=backlog-20261015
export DOCS=100000 WORKERS=16 RATE=1000 SINK= PAD_BYTES=1000
envsubst < k8s/job.yaml | kubectl apply -f -
kubectl -n cslab wait --for=condition=complete job/gen-backlog-20261015 --timeout=15m
kubectl -n cslab logs job/gen-backlog-20261015 | tee "$EVIDENCE/generator.log"
```

Expected: `generator_done` reports 100,000 documents, 230,000 expected change
events, no worker errors, and an observed generation rate close to 1,000
operations per second.

- [ ] **Step 2: Wait until every generated event belongs to a closed window**

```bash
WAIT_SECONDS=$((600 - $(date -u +%s) % 600 + 5))
sleep "$WAIT_SECONDS"
```

Expected: current UTC time is at least five seconds after the next 10-minute
boundary following generator completion.

- [ ] **Step 3: Trigger exactly one Airflow catch-up run**

```bash
EVIDENCE=/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15
export KUBECONFIG="$EVIDENCE/kubeconfig"
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  airflow dags trigger change_stream_to_parquet -r backlog-drain-20261015
```

Poll `airflow dags list-runs change_stream_to_parquet --output json` until the
named run reaches a terminal state.

Expected: `backlog-drain-20261015` is `success`; no second active run exists
for the DAG.

- [ ] **Step 4: Capture the Airflow task's structured completion event**

Locate the task log under the scheduler's `/opt/airflow/logs` tree and copy
only lines containing `export_start`, `chunk`, or `export_done`:

```bash
kubectl -n airflow exec airflow-scheduler-0 -c scheduler -- \
  sh -c "grep -R -E 'export_start|\"event\": \"chunk\"|export_done' \
  /opt/airflow/logs/dag_id=change_stream_to_parquet 2>/dev/null" \
  > "$EVIDENCE/export.log"
grep export_done "$EVIDENCE/export.log"
```

Expected: one completion event reports `events=230000`, `caught_up=true`, a
positive elapsed time, and one or more chunks.

- [ ] **Step 5: Verify the complete Parquet result**

```bash
set -a
eval "$(azd env get-values)"
set +a
EVIDENCE=/Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15
export KUBECONFIG="$EVIDENCE/kubeconfig"
export ACR="$AZURE_CONTAINER_REGISTRY_ENDPOINT"
export IMAGE="$ACR/cslab:backlog-20261015"
export JOB_NAME=verify-backlog-20261015 SCRIPT=verify_lake.py
export LAKE_PREFIX=orders RUN_ID=backlog-20261015 MAX_EVENTS=0 FAULT_EXIT_AFTER_UPLOAD=0
envsubst < k8s/lake.yaml | kubectl apply -f -
kubectl -n cslab wait --for=condition=complete job/verify-backlog-20261015 --timeout=15m
kubectl -n cslab logs job/verify-backlog-20261015 | tee "$EVIDENCE/verify.json"
```

Expected:

```text
expected_events = received_events = 230000
duplicate_rows = 0
missing = 0
unexpected = 0
per_doc_out_of_order = 0
files_with_mixed_windows = 0
files_over_chunk_bytes = 0
```

- [ ] **Step 6: Create a sanitized summary**

Parse the generator, export, and verifier logs into `summary.json` with these
keys only:

```json
{
  "observed_at": "2026-10-15",
  "documents": 100000,
  "expected_events": 230000,
  "received_events": 230000,
  "duplicates": 0,
  "missing": 0,
  "unexpected": 0,
  "out_of_order": 0,
  "generator_ops_per_s": 0,
  "export_elapsed_s": 0,
  "export_events_per_s": 0,
  "files": 0,
  "file_bytes_total": 0,
  "read_lag_p50_ms": 0,
  "read_lag_p99_ms": 0,
  "commit_lag_p99_s": 0
}
```

Replace each numeric zero that represents a measured rate, duration, size, or
lag with the parsed value by running:

```bash
python - "$EVIDENCE" <<'PY'
import json
from pathlib import Path
import sys

evidence = Path(sys.argv[1])


def logged_event(path: Path, name: str) -> dict:
    for line in path.read_text(encoding="utf-8").splitlines():
        start = line.find("{")
        if start < 0:
            continue
        try:
            value = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if value.get("event") == name:
            return value
    raise SystemExit(f"{name} was not found in {path.name}")


generator = logged_event(evidence / "generator.log", "generator_done")
export = logged_event(evidence / "export.log", "export_done")
verify_text = (evidence / "verify.json").read_text(encoding="utf-8")
verify = json.loads(verify_text[verify_text.find("{"):])
elapsed = float(export["elapsed_s"])
summary = {
    "observed_at": "2026-10-15",
    "documents": int(verify["docs"]),
    "expected_events": int(verify["expected_events"]),
    "received_events": int(verify["received_events"]),
    "duplicates": int(verify["duplicate_rows"]),
    "missing": int(verify["missing"]),
    "unexpected": int(verify["unexpected"]),
    "out_of_order": int(verify["per_doc_out_of_order"]),
    "generator_ops_per_s": float(generator["ops_per_s"]),
    "export_elapsed_s": elapsed,
    "export_events_per_s": round(int(export["events"]) / elapsed, 1),
    "files": int(verify["files"]),
    "file_bytes_total": int(verify["file_bytes"]["total"]),
    "read_lag_p50_ms": float(verify["read_lag_ms"]["p50"]),
    "read_lag_p99_ms": float(verify["read_lag_ms"]["p99"]),
    "commit_lag_p99_s": float(verify["commit_lag_s"]["p99"]),
}
if summary["expected_events"] != summary["received_events"]:
    raise SystemExit("event counts differ")
if any(summary[key] for key in ("duplicates", "missing", "unexpected", "out_of_order")):
    raise SystemExit("correctness counters are non-zero")
(evidence / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
PY
```

Confirm `summary.json` contains only the fixed keys above and numeric or date
values, so no Azure resource names, IDs, endpoints, or credentials can be
copied into the public page.

- [ ] **Step 7: Delete the Azure deployment and confirm removal**

```bash
set -a
eval "$(azd env get-values)"
set +a
RESOURCE_GROUP="$AZURE_RESOURCE_GROUP"
azd down --force --purge
az group exists --name "$RESOURCE_GROUP"
```

Expected: `azd down` succeeds and `az group exists` prints `false`. Remove the
local kubeconfig after the confirmation:

```bash
rm -f /Users/hwang-inhwan/.copilot/session-state/1266790b-0c91-48ae-9910-085e05b9d78d/files/backlog-run-2026-10-15/kubeconfig
```

---

### Task 4: Publish the architecture and observed result

**Files:**
- Create: `docs/services/azure-documentdb/change-streams/backlog-architecture/index.md`
- Modify: `docs/services/azure-documentdb/change-streams/index.md`
- Modify: `docs/services/azure-documentdb/change-streams/samples/python-aks/sample.yml`
- Modify: `docs/services/azure-documentdb/change-streams/samples/python-aks/README.md`

**Interfaces:**
- Consumes: verified sources from Task 1 and sanitized `summary.json` from Task 3.
- Produces: one new `research` child page and links from the existing topic and runnable sample.

- [ ] **Step 1: Create the child page with valid metadata**

Use this front matter:

```yaml
---
title: Airflow on AKS에서 change stream 백로그 따라잡기
description: Azure DocumentDB change stream을 Airflow DAG로 읽을 때 밀린 이벤트를 보존 기간 안에 안전하게 따라잡기 위한 단일 writer, checkpoint, 처리율 산정, 확장 경계를 실제 AKS 배포 결과와 함께 정리합니다.
document_type: research
services: [azure-documentdb, azure-kubernetes-service, azure-storage]
technologies: [mongodb, airflow, kubernetes, python]
tags: [design, evaluate, operate]
status: current
verification_status: verified
sources_checked_at: 2026-10-15
published_at: 2026-10-15
topic_order: 2
official_sources:
  - title: Change streams in Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/change-streams
  - title: Deploy and configure Azure Workload Identity on an AKS cluster
    url: https://learn.microsoft.com/azure/aks/workload-identity-deploy-cluster
  - title: Use the cluster autoscaler in Azure Kubernetes Service
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - title: MongoDB Change Streams Specification
    url: https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.md
---
```

Write sections for:

1. decision summary;
2. one-writer-per-stream diagram explanation using
   `../images/architecture.svg`;
3. normal and backlog data flow;
4. `B / (mu - lambda)` drain-time calculation and the `mu > lambda` gate;
5. AKS/Airflow resource isolation and independent-stream scaling;
6. lease, ETag, deterministic file, retry, and history-loss failure handling;
7. alert signals and action thresholds;
8. the exact sanitized values from `summary.json`;
9. limits of the single-shard, non-HA experiment;
10. criteria for switching to Event Hubs or raw ADLS buffering.

Do not imply that the AKS cluster autoscaler increases throughput for one
ordered stream. Describe it only as supplying nodes for multiple independent
export pods.

- [ ] **Step 2: Link the new child from the topic entry**

Add a short paragraph in
`docs/services/azure-documentdb/change-streams/index.md` after the result
table. Link to `backlog-architecture/index.md` and state that the child page
contains the capacity equation, safe scaling boundary, and the 2026-10-15
subscription rerun.

- [ ] **Step 3: Attach the runnable sample to the child**

Change `sample.yml` to:

```yaml
title: Change stream to Parquet with Airflow on AKS
description: Runnable Airflow DAG that exports Azure DocumentDB change stream events to Parquet in ADLS Gen2, with a PyMongo baseline consumer, probe, load generator and verifiers behind private endpoints.
kind: runnable
used_by:
- index
- measurements
- backlog-architecture
```

- [ ] **Step 4: Add the reproducible run to the sample README**

Under `Measured scenarios`, add a dated paragraph and row that use the exact
generator parameters from Task 3. Record only values present in
`summary.json`, identify the deployment as disposable single-shard/non-HA,
and state that resource deletion was confirmed. Do not include Azure resource
names or IDs.

- [ ] **Step 5: Run focused metadata, source, link, and safety checks**

```bash
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
```

Expected: all four commands exit 0.

---

### Task 5: Validate and review the completed branch

**Files:**
- Review: `project/specs/2026-10-15-mongodb-change-stream-airflow-aks-backlog-design.md`
- Review: `project/plans/2026-10-15-mongodb-change-stream-airflow-aks-backlog.md`
- Review: every file changed in Task 4

**Interfaces:**
- Consumes: the complete documentation change and successful Azure evidence.
- Produces: a validated implementation commit ready for pull-request review.

- [ ] **Step 1: Run the sample regression suite again**

```bash
cd docs/services/azure-documentdb/change-streams/samples/python-aks
python -m unittest discover -s app -p 'test_*.py' -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the complete repository documentation contract**

From the repository root:

```bash
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
python scripts/docs/audit_pre_pages.py
```

Expected: every command exits 0.

- [ ] **Step 3: Check the diff and repository hygiene**

```bash
git diff --check
git status --short
git diff --stat origin/main...HEAD
git ls-files | grep -E '(^|/)(\.azure|evidence|site)(/|$)' && exit 1 || true
```

Expected: no whitespace error, only planned files are changed, and no local
state or generated site output is tracked.

- [ ] **Step 4: Invoke the code-review workflow**

Invoke `requesting-code-review` and address only high-confidence issues tied
to this change. Re-run the smallest affected validator after each correction.

- [ ] **Step 5: Commit the implementation**

```bash
git add \
  docs/services/azure-documentdb/change-streams/index.md \
  docs/services/azure-documentdb/change-streams/backlog-architecture/index.md \
  docs/services/azure-documentdb/change-streams/samples/python-aks/README.md \
  docs/services/azure-documentdb/change-streams/samples/python-aks/sample.yml \
  project/plans/2026-10-15-mongodb-change-stream-airflow-aks-backlog.md
git commit -m "docs(azure-documentdb): 백로그 추격 아키텍처 검증" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

Expected: one implementation commit containing only the planned public
documentation, sample metadata, and implementation plan.

---

### Task 6: Push the branch and open the pull request

**Files:**
- Read: `.github/pull_request_template.md`

**Interfaces:**
- Consumes: the validated branch and repository pull-request template.
- Produces: a GitHub pull request against `main`.

- [ ] **Step 1: Inspect and preserve the pull-request template**

Read `.github/pull_request_template.md`. Preserve every heading, comment,
checklist item, and ordering in the final body. Fill validation sections with
each exact command from Task 5 and its `passed` result.

- [ ] **Step 2: Push without force**

```bash
git push --set-upstream origin agents/mongodb-change-stream-airflow-aks-architecture
```

Expected: the branch is published and tracks its origin counterpart.

- [ ] **Step 3: Invoke the pull-request workflow**

Invoke the repository `create-pull-request` skill. Create a non-draft PR to
`main` with a Korean title describing the backlog catch-up architecture.
Summarize the live deployment, sanitized measurement, architecture decision,
cleanup confirmation, and all validation results in the preserved template.

- [ ] **Step 4: Verify the created PR**

```bash
gh pr view --json number,url,state,isDraft,baseRefName,headRefName,title
gh pr checks --watch
```

Expected: the PR is open, not a draft, targets `main`, uses the current branch,
and all available checks finish successfully. If checks fail, invoke the
`fix-ci` workflow and do not report completion until the branch is green or a
specific external blocker is documented.
