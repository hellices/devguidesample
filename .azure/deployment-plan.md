# Azure Deployment Plan

> **Status:** Validated — base azd deployment only (provision, deploy, doctor, baseline, pre-acknowledgement safety gate, `azd down --purge`). The manual Agent connection in the portal and the live S1/S2/S3 run/capture/score sequence have not been run: the operator will run them one by one.

Updated: 2026-08-15 (run-attempt state gate; recovery failure propagation; plan reconciled with the live deployment that has run and the scenario sequence that has not)

## Goal

Validate the Azure SRE Agent event lab as a repeatable guided exercise:

1. deploy the disposable workload and monitoring stack with `azd up`;
2. connect Azure SRE Agent through consent-sensitive portal steps;
3. run S1/S2/S3 in order and capture explicit conclusions or missing states;
4. remove the environment with `azd down --purge`.

## Deployment Context

| Attribute | Value |
|---|---|
| Mode | Modify existing lab |
| Classification | Development / disposable incident lab |
| Scale | Small |
| Budget | Cost-optimized; delete immediately after validation |
| Subscription | Current authenticated subscription selected through `AZURE_SUBSCRIPTION_ID` |
| Location | `koreacentral` |
| Resource group | `rg-${AZURE_ENV_NAME}` unless explicitly overridden |
| Required tags | `purpose=sre-agent-event-lab`, `azd-env-name=${AZURE_ENV_NAME}`, one-day `expiresOn` |
| Agent autonomy | Review |

No subscription ID, resource group, global name suffix, or expiry date is fixed in source.

## Components

| Component | Azure service |
|---|---|
| Incident API | Azure Container Apps |
| Image build and storage | Azure Container Registry Basic, remote ACR build |
| Dependency failure target | Storage account with Blob private endpoint |
| Workload identity | User-assigned managed identity |
| Logs and traces | Log Analytics and workspace-based Application Insights |
| Incident detection | Three Sev2 scheduled-query alert rules |
| Incident analysis | Existing or disposable Azure SRE Agent in Review mode |

## Deployment Recipe

- Azure Developer CLI project: `monitor/sre-agent-event-lab/azure.yaml`
- Subscription-scope entry template: `monitor/sre-agent-event-lab/infra/main.bicep`
- Resource-group module: `monitor/sre-agent-event-lab/infra/lab.bicep`
- Parameters: `monitor/sre-agent-event-lab/infra/main.parameters.json`
- Preprovision: dependency/login/provider checks and non-secret defaults
- Postprovision (`scripts/azd-postprovision-local.sh`): local uv environment setup only; no Azure call, so `azd provision` ends with the public placeholder image still serving
- Postdeploy (`scripts/azd-deploy-app.sh`): wait for `AcrPull` propagation, then ACR remote build, registry/identity configuration, ingress move to 8000, Container App image update, revision and `/healthz` verification, and image persistence
- Predown: validate and delete only recorded external Monitoring Contributor role assignments
- Postdown: clear persisted image/tag environment values

The standard exercise uses the Azure Monitor incident platform and Review-mode response plans. The historical Logic App/HTTP Trigger bridge is not deployed.

## Two-Phase Container Apps + ACR Flow (deploy gate)

Discovered while preparing live validation: this lab is a Container Apps
workload pulling from ACR with a user-assigned managed identity, which
cannot be provisioned and deployed in one step.

- One ARM deployment creates the registry, the identity, the `AcrPull`
  assignment and the Container App, but the lab image does not exist yet
  (it is built *by* the registry), and a role assignment created moments
  earlier is not necessarily usable by a pull issued immediately after.
- Therefore provisioning deploys a **public placeholder image** (ingress
  80, no probes) and performs no image work at all, and the deploy phase
  performs every image action behind an explicit gate.

| Phase | Command | What runs | What it must not do |
|---|---|---|---|
| Provision | `azd provision` | Bicep (infra + placeholder app) → `postprovision` = `scripts/setup-venv.sh` only | No `az acr build`, no `az containerapp update`/`ingress update`/`registry set`, no image env values |
| Deploy | `azd deploy` | `postdeploy` = poll exact `AcrPull` (principal + role definition `7f951dda-4ed3-4680-a7ca-43fe172d538d` + registry scope) up to 300s, then ACR build → `registry set --identity` → `ingress update --target-port 8000` → `update --image` → new healthy revision → `/healthz` → `azd env set SRE_IMAGE_TAG`/`SRE_CONTAINER_IMAGE` | Nothing may run before the grant is observed; nothing is persisted unless `/healthz` returned 200 |

`azd up` runs both phases in order, so the user-facing command stays a
single command and still passes through the same gate.

Deploy-phase outputs consumed from the azd environment:
`AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `AZURE_ACR_NAME`,
`AZURE_ACR_LOGIN_SERVER`, `AZURE_CONTAINER_APP_NAME`,
`AZURE_CONTAINER_APP_FQDN`, `AZURE_CONTAINER_APP_PRINCIPAL_ID`,
`AZURE_WORKLOAD_IDENTITY_RESOURCE_ID`.

Behaviour verified against the installed azd (1.29.0), because the project
declares no services:

- `azd deploy --no-prompt` on a project with this exact `azure.yaml` shape
  (bicep `infra:`, five hooks, no `services:`) runs the `postdeploy` hook,
  and a non-zero hook exit fails the command
  (`ERROR: failed running post hooks: 'postdeploy' hook failed with exit
  code: '7'`).
- `azd deploy` before any provision fails fast with
  `ERROR: infrastructure has not been provisioned` — the guard is a plain
  environment check (`env.GetSubscriptionId() == ""` in
  `cli/azd/internal/cmd/deploy.go`), so the deploy phase is reachable
  exactly when provisioning has run.
- `azd up` uses the same project hooks: `cli/azd/internal/cmd/up_graph.go`
  adds `cmdhook-predeploy`/`cmdhook-postdeploy` unconditionally and keeps
  the deploy events for "Zero-service projects".

No `services:` entry is declared: the only service host that would apply
here (`containerapp` + `docker`) makes `azd deploy`/`azd up` require a
local Docker build, which this lab deliberately avoids.

### ACR gate review fixes (2026-08-14)

A follow-up review of the AcrPull poll (`acr_pull_is_visible` in
`scripts/azd-deploy-app.sh`) found it calling `az role assignment list`
with `--assignee-principal-type ServicePrincipal`, an option that does not
exist for `list` (only for `role assignment create`). Verified against the
installed Azure CLI (2.89.1): passing it fails with `ERROR: unrecognized
arguments: --assignee-principal-type ServicePrincipal`, exit 2, which
would have made every poll fail and the deploy phase never build the
image. Fixed by removing that flag and adding `--fill-principal-name
false --fill-role-definition-name false` (both real, supported flags),
so the poll never depends on Microsoft Graph reachability -- `--assignee-
object-id` already bypasses Graph for the filter, but the two `--fill-*`
flags default to `true` and would each still query Graph to populate
fields this poll never reads. `scripts/tests/deploy_app_harness.py`'s fake
`az` was hardened to reject any `role assignment list` flag the real
parser does not recognise, so a regression back to the unsupported flag
fails the test suite instead of silently passing against a permissive
fake. Confirmed RED (11 tests failing with `ERROR: unrecognized
arguments`) before the fix and GREEN (30/30 in
`test_azd_deploy_app.py`) after.

Also fixed while reviewing the two-phase gate: `doctor.sh`'s `/healthz`
check previously reported the same generic "Investigate: curl -v" FAIL
whether `azd deploy` had simply not run yet (the documented, expected
placeholder state -- port 80, no `/healthz`) or the lab image was
genuinely unhealthy after deployment. It now checks the azd environment's
`SRE_CONTAINER_IMAGE` (set only once the deploy phase succeeds): when it
is empty, the failure explicitly names the state and the remedy (`Run:
azd deploy --no-prompt`) instead of the generic message; once it is set,
a `/healthz` failure is reported as a real regression as before. Stale
`main.bicep` comments attributing this image build/switch to
`postprovision` (moved to the `postdeploy` hook in the two-phase refactor
above) were also corrected.

### Live deployment failure: alert query schema, not cadence (2026-08-14)

A live `azd provision` attempt failed for all three
`Microsoft.Insights/scheduledQueryRules@2023-12-01` alert rules
(`alert-sre-lab-s1-http500`, `-s2-latency`, `-s3-storage-rbac`) with:

```
QueryNotContainKnownTable: One-minute frequency is not supported for
this query. Either switch to five-minute frequency or adapt the query.
```

The first fix read that message literally and moved every rule to
`evaluationFrequency: 'PT5M'`. That was the wrong root cause, and it has
been reverted.

Real root cause: `infra/alerts.bicep` scoped the rules to the Application
Insights **component** and queried the legacy resource-centric schema
(`requests`, `dependencies`, `timestamp`, `cloud_RoleName`, `duration`).
In a workspace-based Application Insights resource those legacy names are
not tables -- they are functions over the workspace tables. The official
one-minute-frequency limitations list ("the query calls a function that
calls other tables", plus `search`/`union`/`take`, `ingestion_time()` and
the `adx` pattern) is exactly what `QueryNotContainKnownTable` reports:
the query contains no *known table*, so the one-minute optimization
cannot be applied. Source: [Create a log search alert
rule](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-log-alert-rule#configure-alert-rule-conditions)
(reached from `aka.ms/lsa_1m_limits`, the link the troubleshooting page
gives for this error).

Final fix (strict TDD, RED first): `infra/alerts.bicep` now takes a
`workspaceResourceId`, queries the workspace schema known tables
`AppRequests`/`AppDependencies` with the exact column casing already used
by `scripts/query-evidence.sh` (`TimeGenerated`, `AppRoleName`, `Name`,
`ResultCode`, `DurationMs`, `Target`; `percentile(DurationMs, 95)` needs
no timespan conversion), scopes each rule to the Log Analytics workspace,
declares `targetResourceTypes: ['Microsoft.OperationalInsights/workspaces']`,
and restores `evaluationFrequency: 'PT1M'` with `windowSize: 'PT5M'`.
`lab.bicep` passes `observability.outputs.workspaceId` into the alerts
module; the `workspaceId` output chain (observability -> lab -> main ->
`AZURE_WORKSPACE_ID`) is unchanged. `appInsightsResourceId` (observability
-> lab -> main.bicep) remains an output too, kept only for backward
compatibility -- no module and no lab script reads it anymore. The alerts
module takes `workspaceResourceId`, not `appInsightsResourceId`, and every
lab script that queries telemetry (`query-evidence.sh`, `run-scenario.sh`,
`doctor.sh`, `baseline.sh`, all via `scripts/common.sh`'s
`deployment_output`/`load_lab_config`) reads `workspaceCustomerId`, which
is unrelated to `appInsightsResourceId`. Per-rule thresholds and the
default fire/resolve timeouts (`LAB_ALERT_FIRE_TIMEOUT_SECONDS=720`,
`LAB_ALERT_RESOLVE_TIMEOUT_SECONDS=900`) are unchanged: the one-minute
cadence they were sized for is back.

Consequence for the recorded results: the S1/S2/S3 run in
`monitor/sre-agent-event-lab/validation-results.md` -- an earlier execution
of this lab, not the deployment recorded below -- was executed at a
one-minute cadence and stays plausible, because the failure above was the
legacy schema on the component scope, not the cadence. Both that report
and `dynamic-thresholds.md` now carry that annotation, and `README.md`'s
cost callout is back to "1분 주기 로그 검색 경고 규칙 3개".

#### Alert template preflight, before the live deployment (2026-08-14)

Run against the partially provisioned lab resource group (only the
observability resources existed in it at that point), with placeholders for
the real subscription ID and resource group:

```
az deployment group validate \
  --resource-group <lab-rg> \
  --name sre-lab-alerts-validate-workspace \
  --template-file infra/alerts.bicep \
  --parameters location=koreacentral \
               workspaceResourceId=/subscriptions/<sub>/resourceGroups/<lab-rg>/providers/Microsoft.OperationalInsights/workspaces/law-sre-event-lab-<suffix> \
               serviceName=sre-event-lab-<suffix> \
               tags='{"purpose":"sre-agent-event-lab"}'
```

Result: `"provisioningState": "Succeeded"`, `"error": null`, and
`validatedResources` listing exactly the three
`Microsoft.Insights/scheduledQueryRules` IDs
(`alert-sre-lab-s1-http500`, `alert-sre-lab-s2-latency`,
`alert-sre-lab-s3-storage-rbac`) -- i.e. the workspace-scoped,
`AppRequests`/`AppDependencies`, PT1M/PT5M template is accepted.

Honest limit of that proof, measured on the same resource group: ARM
preflight does **not** run the scheduled-query-rule query validation. The
pre-fix template (component scope, `requests`/`dependencies`, PT1M) was
re-validated on purpose and *also* returned `provisioningState:
Succeeded`, even though the same template failed the real deployment with
`QueryNotContainKnownTable`. So `az deployment group validate` proves the
template shape, parameters and RBAC are deployable, not that the query is
accepted at PUT time.

The query side was therefore proven directly against the live workspace
with `az monitor log-analytics query`:

- `AppRequests | where TimeGenerated > ago(5m) | where AppRoleName == "<service>" | where Name has "/api/orders" | where ResultCode == "500" | summarize Failures=count()` returns `Failures = 0` (no traffic yet -- the Container App still runs the placeholder image), so the table and every column name/casing resolve.
- The S2 (`percentile(DurationMs, 95)`) and S3 (`AppDependencies` ... `Target`, `ResultCode`) queries resolve the same way.
- The legacy name fails in workspace scope: `requests | take 1` returns `SEM0100: 'take' operator: Failed to resolve table or column expression named 'requests'`, confirming it is not a known table there.

Definitive confirmation came from the live `azd up` recorded under **Live
Deployment Proof** below: the three PT1M workspace-scoped rules deployed
and were enabled, which ARM preflight alone could not have shown. Nothing
was deployed, modified or deleted *while diagnosing and fixing this*; the
live deployment came afterwards, from the fixed template.

### State gate: a re-run retires the previous attempt (2026-08-15)

Review finding (Important): `run-scenario.sh` recorded a scenario's
outcome only at the end, through `mark-recovered`/`mark-failed`. Every
exit path *before* that -- a rejected injecting `az containerapp update`,
a recovery the EXIT trap could not complete, an operator's Ctrl-C -- left
the previous attempt's `run_status: recovered` and
`capture_status: conclusion` untouched. Re-running an already-captured S1
and breaking early therefore left the state file describing a run that no
longer existed, and `lab.sh run s2` was admitted on it: two overlapping
incidents in one workload, with neither capture readable.

Reproduced first (RED), as the finding describes: S1 recovered and
captured a real conclusion, S1 re-run, the re-run's injection rejected ->
the scenario entry still read `recovered` + `conclusion` and S2 injected
`ORDER_DELAY_MS=4000`.

Fix (strict TDD): `LabState.begin_run(scenario, evidence_dir=None)` and
the `begin-run` CLI command start an attempt atomically -- they re-check
the same prerequisites `require_run` enforces (and the same environment
binding every command checks), clear the whole scenario entry (previous
`run_status`, `capture_status`, `failure_reason`, `alert_resolved_at`,
evidence directory and any terminal capture metadata a later version
records) and write `run_status: running` plus `started_at` and the new
evidence directory. `run-scenario.sh` calls it after `require-run` and
before the first destructive Azure call. `running` satisfies no gate:
`has('sX_recovered')` accepts only `recovered`, `has('sX_captured')` only
a recorded `conclusion`, so an attempt that dies early keeps the next
scenario blocked and scores as "no capture recorded" until a run really
recovers and a capture really lands. `mark_recovered`/`mark_failed`
complete a started attempt unchanged, and still clear a stale
`capture_status` themselves for state written without a recorded start.

Confirmed RED (17 state/CLI/doc tests plus 3 end-to-end script tests
failing, including the exact old-success -> broken re-run -> S2 admitted
sequence) and GREEN afterwards, with the full suite and all five Bicep
templates rebuilt.

Documentation fixed in the same pass: `validation-results.md` now opens by
dating itself to the pre-azd, hand-built lab (its subscription, resource
group and Logic App bridge are not what `azd up` creates);
`dynamic-thresholds.md` labels the Action Group -> Logic App -> HTTP
Trigger event path as the legacy bridge and names the Azure Monitor
incident platform path as the default; and both Learn screenshots that
show `Autonomous` now carry a caption warning that this lab must choose
`Review` (the pictures themselves are unchanged). The scenario guides
state that re-running a scenario clears its previous
`sX_recovered`/`sX_captured` record before the fault is injected.

## Security and Safety

- Container Apps reach Blob Storage through private networking.
- Managed identities and Azure RBAC are used; no credentials are stored in the repository or azd environment examples.
- Every destructive script verifies the current subscription, `purpose`, and `azd-env-name` tags.
- S3 removes only the recorded Blob Data Reader assignment and restores it through an exit trap.
- Scenario progression is bound to the current azd environment and requires workload recovery, alert resolution, and an explicit capture status.
- Cleanup validates recorded assignment subscription, principal, role definition, and scope before any deletion.

## Role Assignment Verification

- Status: Verified
- Identity checked: Container App user-assigned managed identity
- ACR access: `AcrPull` (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) scoped to the lab registry
- Blob access: `Storage Blob Data Reader` (`2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`) scoped to the single documents container
- Local developer data access: not required; baseline and scenarios call the public lab API rather than Blob data plane directly
- Issues: none

## Validation Plan

### Preflight checks (re-run after the two-phase refactor)

- [x] 1. AZD Installation — azd 1.29.0
- [x] 2. Schema Validation — official azd v1.0 schema; hooks include `postdeploy`, no `services`
- [x] 3. Environment Setup — the live run used the azd environment `sre-lab-08141227`, provisioned from the corrected template and purged afterwards
- [x] 4. Authentication Check — Azure CLI and azd authenticated
- [x] 5. Subscription/Location Check — current authenticated subscription, Korea Central
- [x] 6. Aspire Pre-Provisioning Checks — not applicable
- [x] 7. Provision Preview — superseded: no separate `--preview` pass was run; the live `azd provision` below deployed the real plan and is recorded in full
- [x] 8. Build Verification — 505 tests and five Bicep builds passed
- [x] 9. Docker Build Context Validation — Dockerfile and requirements present; the image is built by ACR from `app/`, never locally
- [x] 10. Package Validation — `azd package --all --no-prompt` passed
- [x] 11. Azure Policy Validation — three assigned Defender policies are unrelated to planned resources
- [x] 12. Aspire Post-Provisioning Checks — not applicable
- [x] 13. Deploy-Hook Reachability — `postdeploy` runs for this service-less project shape on azd 1.29.0, and its failure fails the command

1. Run the complete pytest suite, Bash syntax checks, Python 3.9 imports, Bicep compilation, and azure.yaml schema validation. **Done.**
2. Create a unique azd environment in Korea Central. **Done.**
3. Run infrastructure preview and inspect the resource plan. **Superseded by the live provision in step 4.**
4. Run `azd up` (provision phase leaves the placeholder image; deploy phase waits for `AcrPull`, builds and switches the image), then `lab.sh doctor` and `lab.sh baseline`. **Done.**
5. Complete the portal Agent setup guide and acknowledge it explicitly. **Not run** — consent-sensitive portal steps the operator performs by hand; only the refusal *before* the acknowledgement was exercised.
6. Run and capture S1, S2, and S3 sequentially; generate the scorecard. **Not run** — the operator runs these one by one after connecting the Agent.
7. Run `azd down --purge`. **Done.**
8. Verify the resource group and recorded external assignments are absent. **Done.**

## Expected Cost

Container Apps, ACR, Log Analytics/Application Insights, Storage, and Azure SRE Agent can incur charges. Use a uniquely named disposable environment and remove it immediately after validation.

## Section 7: Validation Proof

Re-run after the two-phase ACR gate and workspace-schema alert corrections:

| Check | Command | Result |
|---|---|---|
| Unit/integration tests | `app/.venv/bin/python -m pytest app/tests infra/tests scripts/tests` | 505 passed (RED first for the workspace-schema alert fix, the swallowed scenario-recovery failures, and the re-run state gate) |
| Shell syntax | `bash -n scripts/*.sh` | Passed (all scripts, including the two new hooks) |
| Python modules | `python3 -c "import lab_state, score"` | Passed on Python 3.9.6 |
| Bicep build | `az bicep build --file infra/{main,lab,workload,observability,alerts}.bicep --stdout` | Passed (five templates; `alerts.bicep` emits `evaluationFrequency: PT1M`, `windowSize: PT5M`, workspace scope and `targetResourceTypes: Microsoft.OperationalInsights/workspaces`) |
| AZD schema | `azure.yaml` validated against `schemas/v1.0/azure.yaml.json` from Azure/azure-dev | Passed; hooks = preprovision, postprovision, postdeploy, predown, postdown; no `services` |
| AZD package | `azd package --all --no-prompt` | Passed |
| Zero-service deploy hook | `azd deploy --no-prompt` against a marker-hook copy of this `azure.yaml` | `postdeploy` ran; hook exit 7 failed the command |
| Authentication | `az account show`; `azd auth login --check-status --output json` | Authenticated |
| Alert template preflight | `az deployment group validate --template-file infra/alerts.bicep ...` against the live lab resource group | `provisioningState: Succeeded`, `error: null`, three `scheduledQueryRules` validated (see the proof note above for what preflight does and does not cover) |
| Alert queries | `az monitor log-analytics query` for the three rule queries against the live workspace | All three resolve (`Failures=0`, `P95DurationMs=None`, `DependencyFailures=0` with no traffic yet); legacy `requests` fails with `SEM0100` |

## Live Deployment Proof

Validation environment: `sre-lab-08141227`

What this table proves is the base azd deployment path. The incident
exercise itself -- connecting Azure SRE Agent and running the three
scenarios -- is deliberately not part of it (last row).

| Check | Result |
|---|---|
| Alert correction | Workspace-scoped `AppRequests`/`AppDependencies` replaced the rejected legacy component queries; all three PT1M rules deployed and enabled |
| Two-phase deployment | `azd provision` completed with the public placeholder, live `AcrPull` was confirmed, then `azd deploy` built in ACR and switched the app |
| Main user command | `azd up --no-prompt` completed end to end in 4 minutes 39 seconds |
| Health | `/healthz` returned HTTP 200 and the active revision was Healthy |
| Doctor | Workload, telemetry, alert rules, login, tags, and the local Python environment passed; Agent settings remained explicit FAIL/MANUAL because the user will configure them later |
| Baseline | `/api/orders` and `/api/documents` baseline plus Log Analytics telemetry verification passed |
| Safety gate | `lab.sh run s1` was rejected before `acknowledge agent-setup`; `FAILURE_MODE` remained `none` |
| Cleanup | `azd down --purge --force --no-prompt` completed in 21 minutes 40 seconds |
| Cleanup proof | Resource group absent; `SRE_CONTAINER_IMAGE` and `SRE_IMAGE_TAG` cleared; no external Agent setup record or role assignment existed |
| Manual scenario sequence | Pending — the operator connects the Agent in the portal, then runs S1 → capture → S2 → capture → S3 → capture → score one by one. Only the pre-acknowledgement refusal above was exercised: no fault was ever injected, no capture was taken and no scorecard was produced against a live Agent. Scenario behaviour is covered by the test suite (fake `az`/`azd`), not by this deployment. |
