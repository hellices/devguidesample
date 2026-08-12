# Azure SRE Agent Event Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy an isolated Azure Container Apps workload, trigger three real Azure Monitor incidents, measure Azure SRE Agent's event-driven investigations, and publish an evidence-based results report.

**Architecture:** A Python HTTP service runs on Azure Container Apps and sends request, exception, and Blob dependency telemetry to workspace-based Application Insights. Azure Monitor scheduled-query alerts turn deterministic HTTP 500, latency, and Storage RBAC failures into incidents; Azure SRE Agent receives them through its Azure Monitor incident platform and investigates in Review mode using the test resource group, observability connector, repository, and runbook.

**Tech Stack:** Python 3.12, FastAPI, Azure Monitor OpenTelemetry, Azure Identity, Azure Blob Storage, pytest, Docker/ACR Tasks, Bicep, Azure CLI, Azure Container Apps, Log Analytics, Application Insights, Azure Monitor, Azure SRE Agent.

## Global Constraints

- Use subscription `ME-MngEnvMCAP310512-inhwanhwang-3` and region `koreacentral`.
- Create only resources in `rg-sre-agent-event-lab-krc`, except the Azure SRE Agent managed identity's required subscription-scope `Monitoring Contributor` role assignment.
- Apply `purpose=sre-agent-event-lab` and `expiresOn=2026-08-13` tags to created resources.
- Configure every incident response plan in `Review` mode.
- Do not grant the Agent Contributor access to the workload.
- Disable or delete the default `quickstart_handler` response plan before enabling custom plans.
- Run only one failure scenario at a time and verify recovery before starting the next.
- Never delete or change role assignments outside the test Storage container and the Agent's explicitly recorded role assignments.
- Record all test timestamps in UTC.
- Do not modify or commit unrelated existing worktree changes.

---

## File Map

| File | Responsibility |
|---|---|
| `monitor/sre-agent-event-lab/app/main.py` | FastAPI endpoints, deterministic failure modes, structured logs, Blob dependency call |
| `monitor/sre-agent-event-lab/app/telemetry.py` | Azure Monitor OpenTelemetry initialization |
| `monitor/sre-agent-event-lab/app/requirements.txt` | Runtime dependencies pinned to compatible major/minor versions |
| `monitor/sre-agent-event-lab/app/requirements-dev.txt` | pytest and HTTP test dependencies |
| `monitor/sre-agent-event-lab/app/tests/test_main.py` | Unit tests for normal, HTTP 500, latency, and dependency failure behavior |
| `monitor/sre-agent-event-lab/app/Dockerfile` | Reproducible Python 3.12 container |
| `monitor/sre-agent-event-lab/infra/main.bicep` | Resource group deployment entry point and outputs |
| `monitor/sre-agent-event-lab/infra/observability.bicep` | Log Analytics and Application Insights |
| `monitor/sre-agent-event-lab/infra/workload.bicep` | ACR, Storage, Container Apps environment/app, managed identity, Blob role assignment |
| `monitor/sre-agent-event-lab/infra/alerts.bicep` | Three scheduled-query alert rules scoped to the deployed application telemetry |
| `monitor/sre-agent-event-lab/infra/main.bicepparam` | Stable Korea Central deployment parameters |
| `monitor/sre-agent-event-lab/scripts/common.sh` | Subscription, names, outputs, precondition checks, evidence directory helpers |
| `monitor/sre-agent-event-lab/scripts/deploy.sh` | RG creation, Bicep deployment, ACR build, final app deployment |
| `monitor/sre-agent-event-lab/scripts/loadgen.py` | Bounded concurrent HTTP traffic generator with JSON summary |
| `monitor/sre-agent-event-lab/scripts/run-scenario.sh` | Inject, observe, and recover exactly one named scenario |
| `monitor/sre-agent-event-lab/scripts/query-evidence.sh` | Export Azure Monitor alert, App Insights, activity, and Container Apps evidence |
| `monitor/sre-agent-event-lab/scripts/cleanup.sh` | Remove recorded Agent role assignment and test RG safely |
| `monitor/sre-agent-event-lab/runbooks/incident-response.md` | Ground-truth-free investigation order and safe mitigations for the Agent |
| `monitor/sre-agent-event-lab/README.md` | Operator guide and test prerequisites |
| `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md` | Living measured-results report |

---

### Task 1: Build the instrumented failure-injection service

**Files:**
- Create: `monitor/sre-agent-event-lab/app/main.py`
- Create: `monitor/sre-agent-event-lab/app/telemetry.py`
- Create: `monitor/sre-agent-event-lab/app/requirements.txt`
- Create: `monitor/sre-agent-event-lab/app/requirements-dev.txt`
- Create: `monitor/sre-agent-event-lab/app/tests/test_main.py`
- Create: `monitor/sre-agent-event-lab/app/Dockerfile`

**Interfaces:**
- Consumes: `FAILURE_MODE`, `ORDER_DELAY_MS`, `AZURE_STORAGE_ACCOUNT_URL`, and `APPLICATIONINSIGHTS_CONNECTION_STRING` environment variables.
- Produces: `GET /healthz`, `GET /api/orders`, and `GET /api/documents`; structured JSON log fields `scenario`, `operation`, `status`, `elapsed_ms`, and `correlation_id`.

- [ ] **Step 1: Write failing endpoint tests**

Create tests using `pytest`, `fastapi.testclient.TestClient`, and `monkeypatch`. Define a `FakeBlobService` whose `get_container_client("documents").list_blobs()` returns one item, then assert:

```python
def test_orders_normal(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "none")
    monkeypatch.setenv("ORDER_DELAY_MS", "0")
    response = client.get("/api/orders")
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"

def test_orders_http500(client, monkeypatch):
    monkeypatch.setenv("FAILURE_MODE", "http500")
    response = client.get("/api/orders")
    assert response.status_code == 500
    assert response.json()["detail"] == "Injected order processing failure"

def test_orders_delay(client, monkeypatch):
    monkeypatch.setenv("ORDER_DELAY_MS", "50")
    started = time.perf_counter()
    response = client.get("/api/orders")
    assert response.status_code == 200
    assert time.perf_counter() - started >= 0.045

def test_documents_maps_authorization_failure_to_503(client, monkeypatch):
    def denied_service():
        raise HttpResponseError(message="AuthorizationPermissionMismatch", response=None)

    monkeypatch.setattr(main, "list_documents", denied_service)
    response = client.get("/api/documents")
    assert response.status_code == 503
    assert response.json()["detail"] == "Blob dependency unavailable"
```

- [ ] **Step 2: Run tests and confirm the RED state**

Run:

```bash
cd monitor/sre-agent-event-lab/app
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Expected: collection fails because `main.py` and its endpoints do not exist.

- [ ] **Step 3: Implement telemetry initialization**

In `telemetry.py`, export:

```python
def configure_telemetry() -> None:
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if connection_string:
        configure_azure_monitor(connection_string=connection_string)
```

Do not catch initialization errors. A malformed connection string must fail startup rather than silently disabling telemetry.

- [ ] **Step 4: Implement the FastAPI service**

In `main.py`:

- Call `configure_telemetry()` before constructing `FastAPI`.
- Read failure configuration per request so unit tests and new revisions are deterministic.
- Raise `HTTPException(500, "Injected order processing failure")` when `FAILURE_MODE=http500`.
- Sleep `ORDER_DELAY_MS / 1000` seconds when the value is a non-negative integer; raise a clear `ValueError` for invalid values instead of silently defaulting.
- Use `DefaultAzureCredential()` and `BlobServiceClient(account_url=..., credential=...)` for `/api/documents`.
- Convert only `azure.core.exceptions.HttpResponseError` from Blob access to HTTP 503; do not broadly catch unrelated exceptions.
- Emit one JSON log record per request outcome.

- [ ] **Step 5: Pin dependencies and build the container**

Use:

```text
fastapi~=0.116
uvicorn[standard]~=0.35
azure-monitor-opentelemetry~=1.8
azure-identity~=1.24
azure-storage-blob~=12.26
```

Development requirements add:

```text
-r requirements.txt
pytest~=8.4
httpx~=0.28
```

The Dockerfile must use `python:3.12-slim`, install `requirements.txt`, copy only application files, run as a non-root user, expose port 8000, and start `uvicorn main:app --host 0.0.0.0 --port 8000`.

- [ ] **Step 6: Run tests and local process validation**

Run:

```bash
.venv/bin/pytest -q
FAILURE_MODE=none ORDER_DELAY_MS=0 \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 18000 \
  >/tmp/sre-event-lab-uvicorn.log 2>&1 &
APP_PID=$!
trap 'kill "$APP_PID" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do
  curl --fail --silent http://127.0.0.1:18000/healthz && break
  sleep 1
done
curl --fail http://127.0.0.1:18000/healthz
curl --fail http://127.0.0.1:18000/api/orders
kill "$APP_PID"
wait "$APP_PID" || true
trap - EXIT
```

Expected: all tests pass; both requests return HTTP 200; uvicorn exits after the PID-specific `kill`. The Dockerfile is validated later by the remote `az acr build`, so local Docker is not required.

- [ ] **Step 7: Commit**

```bash
git add monitor/sre-agent-event-lab/app
git commit -m "feat(monitor): add SRE Agent failure lab app" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Define isolated Azure infrastructure

**Files:**
- Create: `monitor/sre-agent-event-lab/infra/main.bicep`
- Create: `monitor/sre-agent-event-lab/infra/observability.bicep`
- Create: `monitor/sre-agent-event-lab/infra/workload.bicep`
- Create: `monitor/sre-agent-event-lab/infra/alerts.bicep`
- Create: `monitor/sre-agent-event-lab/infra/main.bicepparam`

**Interfaces:**
- Consumes: `location`, `suffix`, `containerImage`, `deployContainerApp`, and `tags`.
- Produces: `acrName`, `acrLoginServer`, `containerAppName`, `containerAppFqdn`, `containerAppPrincipalId`, `storageContainerScope`, `blobRoleAssignmentName`, `workspaceId`, `appInsightsName`, and alert rule names.

- [ ] **Step 1: Write the deployment entry point**

`main.bicep` must call focused `observability`, `workload`, and `alerts` modules. Pass the Application Insights connection string from observability to workload. Deploy the `alerts` module only when `deployContainerApp=true`, after the workload module, so there is no circular dependency.

- [ ] **Step 2: Define observability resources and exact alert queries**

Create one workspace-based Application Insights component in `observability.bicep`. Create three `Microsoft.Insights/scheduledQueryRules@2023-12-01` resources in `alerts.bicep` with 5-minute windows and 1-minute evaluation:

```kusto
AppRequests
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where ResultCode startswith "5"
| summarize Failures=count()
```

Fire S1 when `Failures > 10`.

```kusto
AppRequests
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where Name has "/api/orders"
| summarize P95DurationMs=percentile(DurationMs, 95)
```

Fire S2 when `P95DurationMs > 2000`.

```kusto
AppDependencies
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where Target has "blob.core.windows.net"
| where Success == false
| summarize DependencyFailures=count()
```

Fire S3 when `DependencyFailures > 5`.

Use Sev2, auto-mitigation, enabled rules, and titles prefixed exactly with `[SRE-LAB-S1]`, `[SRE-LAB-S2]`, and `[SRE-LAB-S3]`.

- [ ] **Step 3: Define workload resources**

Create:

- Basic ACR with admin disabled.
- Standard_LRS Storage account with public blob access disabled.
- Private `documents` blob container.
- Container Apps managed environment connected to the Log Analytics workspace.
- Consumption Container App with external ingress on port 8000, one active revision, min replicas 1, max replicas 2, 0.5 CPU, 1 GiB memory.
- System-assigned identity with `AcrPull` on ACR and `Storage Blob Data Reader` on the `documents` container.
- Environment variables: `FAILURE_MODE=none`, `ORDER_DELAY_MS=0`, `AZURE_STORAGE_ACCOUNT_URL`, `APPLICATIONINSIGHTS_CONNECTION_STRING`, `OTEL_SERVICE_NAME=sre-event-lab`.

Use deterministic role assignment GUIDs based on scope, principal ID, and role definition ID. Export the role assignment name and container scope for safe S3 recovery.

- [ ] **Step 4: Add stable parameters**

Set `location = 'koreacentral'`, derive resource names from `suffix = '95933ae5'`, and define:

```bicep
param tags = {
  purpose: 'sre-agent-event-lab'
  expiresOn: '2026-08-13'
}
```

The initial deployment uses `deployContainerApp = false` and `containerImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'`; the image is not referenced while the app condition is false.

- [ ] **Step 5: Validate Bicep**

Run:

```bash
az bicep build --file monitor/sre-agent-event-lab/infra/main.bicep
az bicep build --file monitor/sre-agent-event-lab/infra/main.bicep --stdout >/dev/null
```

Expected: exit code 0 and no errors. Remove generated `main.json` from the first command after validation.

- [ ] **Step 6: Commit**

```bash
git add monitor/sre-agent-event-lab/infra
git commit -m "feat(monitor): define SRE Agent lab infrastructure" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add bounded scenario and evidence tooling

**Files:**
- Create: `monitor/sre-agent-event-lab/scripts/common.sh`
- Create: `monitor/sre-agent-event-lab/scripts/deploy.sh`
- Create: `monitor/sre-agent-event-lab/scripts/loadgen.py`
- Create: `monitor/sre-agent-event-lab/scripts/run-scenario.sh`
- Create: `monitor/sre-agent-event-lab/scripts/query-evidence.sh`
- Create: `monitor/sre-agent-event-lab/scripts/cleanup.sh`
- Create: `monitor/sre-agent-event-lab/scripts/tests/test_loadgen.py`

**Interfaces:**
- `loadgen.py URL --requests N --concurrency N --expect-status CODE --output FILE` returns nonzero when observed status codes differ from the expectation and writes a JSON summary.
- `run-scenario.sh s1|s2|s3` creates `evidence/<scenario>-<UTC timestamp>/`.
- `query-evidence.sh SCENARIO EVIDENCE_DIR START_UTC END_UTC` writes JSON/TSV evidence without changing Azure resources.

- [ ] **Step 1: Test the bounded load generator**

Use a local `ThreadingHTTPServer` fixture and assert that 20 requests with concurrency 4 produce:

```json
{
  "total": 20,
  "status_counts": {"200": 20},
  "errors": 0
}
```

Also assert that `--expect-status 500` returns exit code 2 when the server returns 200.

- [ ] **Step 2: Implement `loadgen.py`**

Use only the Python standard library. Bound `requests` to 1-10,000 and `concurrency` to 1-50. Record UTC start/end, request count, status counts, transport errors, average milliseconds, and p95 milliseconds. Write atomically by creating `<output>.tmp` and replacing the output path.

- [ ] **Step 3: Implement shared safety checks**

`common.sh` must:

- require `az`, `jq`, `curl`, and `python3`;
- verify the current subscription ID equals `95933ae5-0201-4a21-a1fc-8051a7437982`;
- set `RESOURCE_GROUP=rg-sre-agent-event-lab-krc`;
- refuse scenario or cleanup operations if the RG lacks tag `purpose=sre-agent-event-lab`;
- load deployment outputs with `az deployment group show`;
- create evidence directories under `monitor/sre-agent-event-lab/evidence/`, with that directory added to `.gitignore`.

- [ ] **Step 4: Implement two-phase deployment**

`deploy.sh` must:

1. Create or validate the tagged RG.
2. Run subscription and group deployment validation.
3. Deploy `deployContainerApp=false`.
4. Read ACR name from outputs.
5. Build `sre-event-lab:20260812.1` with `az acr build`.
6. Deploy `deployContainerApp=true` with the resulting image.
7. Poll `/healthz` until HTTP 200 with a maximum 10-minute deadline.
8. Print all final outputs as JSON.

- [ ] **Step 5: Implement scenario injection and unconditional recovery**

`run-scenario.sh` must install a shell `trap` that runs the matching recovery action on `EXIT`, then:

- S1: set `FAILURE_MODE=http500`, wait for the new revision to become ready, run 120 requests at concurrency 4 expecting 500, and recover to `FAILURE_MODE=none`.
- S2: set `ORDER_DELAY_MS=4000`, wait for readiness, run 90 requests at concurrency 8 expecting 200, and recover to `ORDER_DELAY_MS=0`.
- S3: delete only the output `blobRoleAssignmentName` at `storageContainerScope`, run 60 `/api/documents` requests at concurrency 4 expecting 503, and recreate `Storage Blob Data Reader` on exactly that scope in the trap.

After traffic generation, keep the failure active for up to 12 minutes while polling Azure Monitor for the matching fired alert. Record the alert ID and firing time before recovery. Never use a fixed blind sleep when readiness or alert state can be polled.

- [ ] **Step 6: Implement evidence export**

Export:

- Container App revisions and environment variable names, redacting secret values.
- AppRequests/AppDependencies/AppExceptions query results for the scenario interval.
- relevant Azure Activity Log entries.
- fired and resolved Azure Monitor alert instances.
- role assignments only for the test app principal and test container scope.

Do not export access tokens, connection strings, or unrelated subscription resources.

- [ ] **Step 7: Implement safe cleanup**

`cleanup.sh` must require the exact RG name and tag, accept `--yes`, remove only the recorded Agent `Monitoring Contributor` assignment if its principal ID and assignment ID were saved by setup, then delete the test RG with `az group delete --no-wait`. Without `--yes`, print the planned actions and exit without changes.

- [ ] **Step 8: Run tests and static checks**

Run:

```bash
python3 -m pytest monitor/sre-agent-event-lab/scripts/tests/test_loadgen.py -q
bash -n monitor/sre-agent-event-lab/scripts/*.sh
```

Expected: pytest passes and every shell script parses successfully.

- [ ] **Step 9: Commit**

```bash
git add .gitignore monitor/sre-agent-event-lab/scripts
git commit -m "feat(monitor): add safe SRE lab scenario tooling" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Add Agent runbook and operator documentation

**Files:**
- Create: `monitor/sre-agent-event-lab/runbooks/incident-response.md`
- Create: `monitor/sre-agent-event-lab/README.md`
- Create: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

**Interfaces:**
- The runbook gives investigation order and allowed mitigations but does not reveal scenario ground truth.
- The report uses one row per scenario with detection latency, pickup latency, completion latency, RCA score, and verdict.

- [ ] **Step 1: Write the ground-truth-free runbook**

The runbook must tell the Agent to:

1. identify the affected resource and exact UTC onset;
2. separate availability, latency, and dependency symptoms;
3. inspect requests, exceptions, dependencies, revisions, configuration changes, Activity Log, and RBAC changes;
4. cite concrete query results before concluding;
5. propose the smallest reversible mitigation;
6. avoid changing anything outside `rg-sre-agent-event-lab-krc`;
7. wait for approval before remediation.

Do not include strings such as `FAILURE_MODE=http500`, `ORDER_DELAY_MS=4000`, or “role assignment was removed,” because those are the answers being tested.

- [ ] **Step 2: Write the operator guide**

Document prerequisites, exact deploy/test/query/cleanup commands, SRE Agent portal checkpoints, expected maximum duration, estimated low-cost footprint, safety boundaries, and troubleshooting order.

- [ ] **Step 3: Create the living report**

Add:

- execution metadata;
- “한눈에 보기” table for S1-S3;
- Agent and observability configuration;
- one section per scenario with ground truth, timeline, evidence, Agent findings, scoring rubric, recovery;
- cross-scenario conclusions;
- cost and cleanup status.

Mark unexecuted measured fields as `⏳ 미실행` rather than inventing values.

- [ ] **Step 4: Validate documentation**

Run:

```bash
rg -n 'PENDING_VALUE|FIXME|REPLACE_ME' \
  monitor/sre-agent-event-lab/README.md \
  monitor/sre-agent-event-lab/runbooks/incident-response.md \
  docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git diff --check
```

Expected: no placeholder matches and no whitespace errors.

- [ ] **Step 5: Commit**

```bash
git add monitor/sre-agent-event-lab/README.md \
  monitor/sre-agent-event-lab/runbooks/incident-response.md \
  docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git commit -m "docs(monitor): add SRE Agent lab runbook and report" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Deploy and validate the Azure workload

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

**Interfaces:**
- Consumes: Tasks 1-4 commits.
- Produces: healthy public test endpoint, populated observability tables, enabled alert rules, deployment evidence.

- [ ] **Step 1: Verify Azure context and providers**

Run:

```bash
az account set --subscription 95933ae5-0201-4a21-a1fc-8051a7437982
az account show --query '{name:name,id:id,state:state}' -o table
for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
  Microsoft.Storage Microsoft.ContainerRegistry; do
  az provider register --namespace "$provider" --wait
done
```

Expected: the named development subscription is enabled and every provider becomes `Registered`.

- [ ] **Step 2: Validate and deploy**

Run:

```bash
bash monitor/sre-agent-event-lab/scripts/deploy.sh \
  2>&1 | tee monitor/sre-agent-event-lab/evidence/deploy.log
```

Expected: deployment succeeds, ACR build succeeds, `/healthz` returns 200.

- [ ] **Step 3: Verify baseline telemetry**

Send 30 normal `/api/orders` requests and 10 successful `/api/documents` requests. Query `AppRequests` and `AppDependencies` until both contain current records. Confirm all three alert queries are below threshold.

- [ ] **Step 4: Record deployment facts**

Write resource names, deployment IDs, baseline query counts, exact UTC times, and observed cost meter start into the report. Do not store connection strings or tokens.

- [ ] **Step 5: Commit measured deployment metadata**

```bash
git add docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git commit -m "docs(monitor): record SRE lab deployment" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 6: Create and connect Azure SRE Agent

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`
- Create in evidence directory: `agent-setup.json`

**Interfaces:**
- Produces: Agent in Korea Central, GitHub and observability context, Azure Monitor incident platform, three Review-mode response plans, recorded managed identity and role assignment IDs.

- [ ] **Step 1: Create the Agent through `https://sre.azure.com`**

Use:

- subscription: `ME-MngEnvMCAP310512-inhwanhwang-3`;
- resource group: `rg-sre-agent-event-lab-krc`;
- agent name: `sre-devguidesample-95933ae5`;
- region: Korea Central;
- Application Insights: use the lab instance when selectable, otherwise allow the wizard-created instance and record it.

Checkpoint: deployment status is `Succeeded`.

- [ ] **Step 2: Connect context**

Connect:

- GitHub repository `hellices/devguidesample`;
- Azure resource group `rg-sre-agent-event-lab-krc` with Reader access;
- the lab Log Analytics/Application Insights connector;
- `monitor/sre-agent-event-lab/runbooks/incident-response.md` as knowledge.

Checkpoint: each card shows connected/healthy.

- [ ] **Step 3: Connect Azure Monitor incident platform**

Open **Builder → Incident platform**, choose Azure Monitor, turn off Quickstart response plan, and save. If a `quickstart_handler` exists, delete it before continuing.

- [ ] **Step 4: Create response plans**

Create exactly:

| Name | Severity | Title filter | Mode |
|---|---|---|---|
| `sre-lab-s1-http500` | Sev2 | `[SRE-LAB-S1]` | Review |
| `sre-lab-s2-latency` | Sev2 | `[SRE-LAB-S2]` | Review |
| `sre-lab-s3-storage-rbac` | Sev2 | `[SRE-LAB-S3]` | Review |

Checkpoint: all plans are On and show Review.

- [ ] **Step 5: Verify and record permissions**

Confirm the Agent managed identity has:

- Reader on the test RG;
- Monitoring Contributor on the test subscription as required by the Azure Monitor scanner;
- no Contributor or Owner role.

Save only principal ID, role assignment IDs, scopes, and timestamps to `agent-setup.json`. Never save credentials.

- [ ] **Step 6: Record setup in the report**

Record Agent region, model provider, connectors, response plans, role scopes, and setup checkpoints.

---

### Task 7: Execute S1 and score the HTTP 500 investigation

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

- [ ] **Step 1: Establish a clean baseline**

Verify `/healthz` and `/api/orders` return 200, S1 alert is resolved, and no prior active S1 thread exists.

- [ ] **Step 2: Run S1**

```bash
bash monitor/sre-agent-event-lab/scripts/run-scenario.sh s1
```

Expected: HTTP 500 traffic, S1 alert fired, SRE Agent thread created, recovery trap restores HTTP 200.

- [ ] **Step 3: Wait on observable conditions**

Poll until the Agent thread has a structured conclusion or 15 minutes elapse. Do not prompt the Agent manually; the event-driven path is under test.

- [ ] **Step 4: Export evidence and score**

Run `query-evidence.sh`, compare Agent statements to the recorded configuration change, and score impact 0-2, cause 0-3, evidence 0-2, mitigation 0-2, uncertainty 0-1.

- [ ] **Step 5: Update and commit the report**

Record exact timeline, Agent output summary, cited evidence, unsupported claims, score, verdict, and recovery.

---

### Task 8: Execute S2 and score the latency investigation

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

- [ ] **Step 1: Establish a clean baseline**

Verify `ORDER_DELAY_MS=0`, request p95 is below 2 seconds, S2 alert is resolved, and the app is healthy.

- [ ] **Step 2: Run S2**

```bash
bash monitor/sre-agent-event-lab/scripts/run-scenario.sh s2
```

Expected: 2xx responses with approximately 4-second latency, S2 alert fired, event-driven Agent thread, recovery to baseline latency.

- [ ] **Step 3: Export evidence and score**

Confirm the Agent distinguishes latency from availability, identifies the affected revision/configuration timing, and does not claim a dependency outage without evidence.

- [ ] **Step 4: Update the report**

Use the same timeline and 10-point scoring format as S1.

---

### Task 9: Execute S3 and score the Storage RBAC investigation

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

- [ ] **Step 1: Establish a clean baseline**

Verify `/api/documents` returns 200, the exact Blob Data Reader assignment exists on the test container, and S3 alert is resolved.

- [ ] **Step 2: Run S3**

```bash
bash monitor/sre-agent-event-lab/scripts/run-scenario.sh s3
```

Expected: Blob authorization failures surface as HTTP 503, S3 alert fires, Agent thread starts, and the trap restores only the deleted role assignment.

- [ ] **Step 3: Verify recovery before analysis**

Poll until `/api/documents` returns 200 and the role assignment ID/scope match the intended test container.

- [ ] **Step 4: Export evidence and score**

Confirm the Agent connects 503 symptoms to Blob 403 dependency evidence and the recent role assignment deletion. Penalize generic “network issue” conclusions unsupported by evidence.

- [ ] **Step 5: Update the report**

Use the same timeline and 10-point scoring format as S1 and S2.

---

### Task 10: Complete the report, verify the lab, and clean up

**Files:**
- Modify: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`
- Modify: `monitor/sre-agent-event-lab/README.md` only if measured behavior changes an operator instruction

- [ ] **Step 1: Calculate cross-scenario results**

Calculate detection, pickup, and completion latency from UTC timestamps. Apply:

- Pass: score 8-10
- Partial: score 5-7
- Fail: score 0-4

Overall success requires every scenario Partial or better, at least two Pass results, and zero unauthorized autonomous actions.

- [ ] **Step 2: Add operational conclusions**

Document which evidence sources the Agent used well, missed correlations, false claims, response-plan tuning, RBAC implications, scanner behavior, and whether the Agent is suitable for this repository's future incident labs.

- [ ] **Step 3: Capture cost**

Query Cost Management for the tagged RG when data is available. If cost ingestion is delayed, record the Azure retail estimate separately from observed cost and label it clearly.

- [ ] **Step 4: Run final code and IaC verification**

```bash
monitor/sre-agent-event-lab/app/.venv/bin/pytest \
  monitor/sre-agent-event-lab/app/tests \
  monitor/sre-agent-event-lab/scripts/tests -q
bash -n monitor/sre-agent-event-lab/scripts/*.sh
az bicep build --file monitor/sre-agent-event-lab/infra/main.bicep --stdout >/dev/null
git diff --check
```

Expected: tests pass, scripts parse, Bicep compiles, and no whitespace errors remain.

- [ ] **Step 5: Clean up safely**

After preserving evidence and report facts:

```bash
bash monitor/sre-agent-event-lab/scripts/cleanup.sh
bash monitor/sre-agent-event-lab/scripts/cleanup.sh --yes
```

Expected: first command is dry-run only; second removes the recorded subscription role assignment and starts deletion of only `rg-sre-agent-event-lab-krc`.

- [ ] **Step 6: Verify cleanup**

Poll until the test RG no longer exists. Query role assignments for the Agent principal and confirm the recorded subscription-scope Monitoring Contributor assignment is absent. Record whether the Agent resource was deleted with the RG.

- [ ] **Step 7: Final commit**

```bash
git add monitor/sre-agent-event-lab \
  docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
git commit -m "docs(monitor): publish Azure SRE Agent event test results" \
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
