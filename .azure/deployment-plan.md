# Azure Deployment Plan

> **Status:** Ready for Validation

Updated: 2026-08-14 (alert evaluation frequency fix)

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

### Live deployment failure: alert evaluation frequency (2026-08-14)

A live `azd provision` attempt failed ARM validation for all three
`Microsoft.Insights/scheduledQueryRules@2023-12-01` alert rules
(`alert-sre-lab-s1-http500`, `-s2-latency`, `-s3-storage-rbac`) with:

```
QueryNotContainKnownTable: One-minute frequency is not supported for
this query. Either switch to five-minute frequency or adapt the query.
```

Root cause: `infra/alerts.bicep` set `evaluationFrequency: 'PT1M'` for
all three rules while their `requests`/`dependencies` Application
Insights queries only support a five-minute (or coarser) evaluation
cadence -- the one-minute cadence was never deployable, only ever
validated by `az bicep build`, which does not call ARM and cannot catch
this. Fixed with strict TDD: added
`test_evaluation_frequency_is_five_minutes_not_one_minute` to
`infra/tests/test_alerts_bicep.py` (RED against the unmodified
template), then changed `evaluationFrequency` to `'PT5M'` for all three
rules (GREEN). `windowSize` stays `'PT5M'` and per-rule thresholds are
unchanged, since nothing about the failure implicated them. Two
user-facing docs asserted the now-incorrect one-minute cadence and were
corrected under the same RED/GREEN discipline (new tests in
`scripts/tests/test_lab_guides.py`): `README.md`'s cost callout ("1분
주기 로그 검색 경고 규칙 3개" → "5분 주기 로그 검색 경고 규칙 3개") and
`dynamic-thresholds.md`'s Static Threshold section ("evaluation: 1분" →
"evaluation: 5분"); the unrelated, still-true statement that Log Search
*dynamic* thresholds do not support one-minute evaluation was left
as-is. No Azure resources were deployed or deleted while diagnosing or
fixing this.

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
- [ ] 3. Environment Setup — a fresh environment is needed for the live run (`sre-lab-08141227` predates this change)
- [x] 4. Authentication Check — Azure CLI and azd authenticated
- [x] 5. Subscription/Location Check — current authenticated subscription, Korea Central
- [x] 6. Aspire Pre-Provisioning Checks — not applicable
- [ ] 7. Provision Preview — to re-run against the updated template outputs
- [x] 8. Build Verification — 460 tests and three Bicep builds passed
- [x] 9. Docker Build Context Validation — Dockerfile and requirements present; the image is built by ACR from `app/`, never locally
- [x] 10. Package Validation — `azd package --all --no-prompt` passed
- [x] 11. Azure Policy Validation — three assigned Defender policies are unrelated to planned resources
- [x] 12. Aspire Post-Provisioning Checks — not applicable
- [x] 13. Deploy-Hook Reachability — `postdeploy` runs for this service-less project shape on azd 1.29.0, and its failure fails the command

1. Run the complete pytest suite, Bash syntax checks, Python 3.9 imports, Bicep compilation, and azure.yaml schema validation.
2. Create a unique azd environment in Korea Central.
3. Run infrastructure preview and inspect the resource plan.
4. Run `azd up` (provision phase leaves the placeholder image; deploy phase waits for `AcrPull`, builds and switches the image), then `lab.sh doctor` and `lab.sh baseline`.
5. Complete the portal Agent setup guide and acknowledge it explicitly.
6. Run and capture S1, S2, and S3 sequentially; generate the scorecard.
7. Run `azd down --purge`.
8. Verify the resource group and recorded external assignments are absent.

## Expected Cost

Container Apps, ACR, Log Analytics/Application Insights, Storage, and Azure SRE Agent can incur charges. Use a uniquely named disposable environment and remove it immediately after validation.

## Section 7: Validation Proof

Re-run after the two-phase refactor (the previous run predates it, so the
earlier "Validated" status no longer applies):

| Check | Command | Result |
|---|---|---|
| Unit/integration tests | `app/.venv/bin/python -m pytest app/tests infra/tests scripts/tests` | 463 passed (added 3 for the PT5M alert-frequency fix) |
| Shell syntax | `bash -n scripts/*.sh` | Passed (all scripts, including the two new hooks) |
| Python modules | `python3 -c "import lab_state, score"` | Passed on Python 3.9.6 |
| Bicep build | `az bicep build --file infra/{main,lab,workload,alerts}.bicep --stdout` | Passed (four templates; `alerts.bicep` now emits `evaluationFrequency: PT5M`) |
| AZD schema | `azure.yaml` validated against `schemas/v1.0/azure.yaml.json` from Azure/azure-dev | Passed; hooks = preprovision, postprovision, postdeploy, predown, postdown; no `services` |
| AZD package | `azd package --all --no-prompt` | Passed |
| Zero-service deploy hook | `azd deploy --no-prompt` against a marker-hook copy of this `azure.yaml` | `postdeploy` ran; hook exit 7 failed the command |
| Authentication | `az account show`; `azd auth login --check-status --output json` | Authenticated |

Pending live validation (no resources were deployed by this change):

| Check | Command | Status |
|---|---|---|
| Environment | `azd env new <unique> --location koreacentral` | To re-create for the live run |
| Provision preview | `azd provision --preview --no-prompt` | To re-run |
| Provision phase | `azd provision --no-prompt` leaves the placeholder image serving and `app/.venv` ready | Failed live at ARM validation for the three `scheduledQueryRules` alert rules (`QueryNotContainKnownTable`, PT1M unsupported) before this fix; to re-verify live now that `alerts.bicep` uses PT5M |
| Deploy phase | `azd deploy --no-prompt` waits for `AcrPull`, builds in ACR, switches the image, `/healthz` returns 200 | To verify live |
| Policy assignments | `az policy assignment list --scope <subscription> --disable-scope-strict-match` | Unchanged from the previous run; re-check at validation time |
| Static RBAC | reviewed all `Microsoft.Authorization/roleAssignments` in `workload.bicep` | Unchanged: least-privilege AcrPull and container-scoped Blob Data Reader |
