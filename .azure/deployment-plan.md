# Azure Deployment Plan

> **Status:** Deployed

Generated: 2026-08-12T03:35:07Z

---

## 1. Project Overview

**Goal:** Deploy an isolated Azure Container Apps incident lab, connect Azure Monitor alerts to Azure SRE Agent, execute three deterministic failures, and publish an evidence-based analysis report.

**Path:** Add Components

**Design:** `monitor/sre-agent-event-lab/README.md`

**Execution plan:** `monitor/sre-agent-event-lab/README.md`

---

## 2. Requirements

| Attribute | Value |
|---|---|
| Classification | Development / disposable incident lab |
| Scale | Small |
| Budget | Cost-Optimized |
| Subscription | `95933ae5-0201-4a21-a1fc-8051a7437982` |
| Location | `koreacentral` |
| Resource group | `rg-sre-agent-event-lab-krc` |
| Required tags | `purpose=sre-agent-event-lab`, `expiresOn=2026-08-13` |
| Agent autonomy | Review |

The current Azure CLI context matches the recorded subscription. Korea Central supports Azure SRE Agent and the selected workload services.

---

## 3. Components Detected

| Component | Type | Technology | Path |
|---|---|---|---|
| Incident lab API | API | Python 3.12, FastAPI, Azure Monitor OpenTelemetry | `monitor/sre-agent-event-lab/app/` |
| Azure infrastructure | IaC | Bicep | `monitor/sre-agent-event-lab/infra/` |
| Deployment and incident tooling | Operations | Azure CLI, Bash, Python | `monitor/sre-agent-event-lab/scripts/` |
| Agent knowledge | Runbook | Markdown | `monitor/sre-agent-event-lab/runbooks/` |
| Results | Report | Markdown | `monitor/sre-agent-event-lab/validation-results.md` |

---

## 4. Recipe Selection

**Selected:** Bicep + AZCLI

**Rationale:**

- The repository already uses direct Bicep and Azure CLI patterns.
- The deployment requires a two-phase flow: base resources, ACR cloud build, then Container App and alert rules.
- The incident runner needs explicit control over revision configuration, RBAC removal/recovery, alert polling, evidence export, and cleanup.
- Local Docker is not required; `az acr build` performs the image build.

---

## 5. Architecture

**Stack:** Containers

### Service Mapping

| Component | Azure Service | SKU |
|---|---|---|
| FastAPI incident API | Azure Container Apps | Consumption, 0.5 CPU / 1 GiB, min 1, max 2 |
| Container image | Azure Container Registry | Basic |
| Blob dependency | Azure Storage | Standard_LRS StorageV2 |
| Central logs | Log Analytics | PerGB2018, 30-day retention |
| APM | Workspace-based Application Insights | Web |
| Incident detection | Azure Monitor scheduled-query rules | 3 Sev2 rules |
| Workload authentication | User-assigned managed identity | No SKU |
| Incident analysis | Azure SRE Agent | Korea Central, Review response plans |

### Data and Incident Flow

1. Public HTTPS requests reach the Container App.
2. OpenTelemetry exports request, exception, and Blob dependency telemetry to Application Insights.
3. Scheduled-query rules evaluate every minute over a five-minute window.
4. Azure SRE Agent's Azure Monitor scanner receives matching Sev2 incidents.
5. Response plans investigate with repository, runbook, resource, Activity Log, and observability context.
6. The operator records and scores the analysis, then verifies scenario recovery.

### Security Controls

- ACR admin access and anonymous pull are disabled.
- Container App pulls with a user-assigned managed identity and `AcrPull`.
- Blob access uses the same managed identity and `Storage Blob Data Reader` scoped to the `documents` container.
- Storage shared-key authentication and public blob access are disabled.
- Application Insights connection string is a Container Apps secret.
- Agent workload access is Reader; remediation remains in Review mode.
- Scenario and cleanup scripts refuse untagged or wrong-subscription targets.

---

## 6. Provisioning Limit Checklist

Quota CLI was used first for Microsoft.App and Microsoft.Storage. Azure Resource Graph plus official service-limit documentation was used where quota CLI is unsupported or no adjustable count quota exists.

| Resource Type | Number to Deploy | Current in Korea Central | Total After Deployment | Limit/Quota | Source and result |
|---|---:|---:|---:|---:|---|
| `Microsoft.App/managedEnvironments` | 1 | 0 | 1 | 50 | `azure-quotas`, `ManagedEnvironmentCount`: sufficient |
| `Microsoft.Storage/storageAccounts` | 1 | 0 | 1 | 250 | `azure-quotas`, `StorageAccounts`: sufficient |
| `Microsoft.ContainerRegistry/registries` | 1 | 1 | 2 | 100 per subscription per region | quota CLI returned `BadRequest`; Azure Resource Graph + official limits: sufficient |
| `Microsoft.App/containerApps` | 1 | 0 | 1 | governed by Container Apps environment/consumption quotas | Azure Resource Graph + deployment validation: sufficient |
| `Microsoft.OperationalInsights/workspaces` | 1 | 1 | 2 | no adjustable regional creation quota exposed | Azure Resource Graph + deployment validation |
| `Microsoft.Insights/components` | 1 | 1 | 2 | no adjustable regional creation quota exposed | Azure Resource Graph + deployment validation |
| `Microsoft.Insights/scheduledQueryRules` | 3 | 0 | 3 | within Azure Monitor alert-rule limits | Azure Resource Graph + deployment validation |
| `Microsoft.ManagedIdentity/userAssignedIdentities` | 1 | 5 | 6 | no adjustable regional creation quota exposed | Azure Resource Graph + deployment validation |

**Status:** All quota-metered resources are within limits. Resource names `acrsrelab95933ae5` and `stsrelab95933ae5` are globally available. The target resource group does not exist.

---

## 7. Deployment Sequence

1. Register `Microsoft.App`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.Storage`, `Microsoft.ContainerRegistry`, `Microsoft.ManagedIdentity`, and `Microsoft.AlertsManagement`.
2. Run local tests, shell parse checks, Bicep compilation, group validation, and deployment what-if.
3. Create the tagged resource group.
4. Deploy observability, ACR, Storage, managed identity, RBAC, and Container Apps environment with `deployContainerApp=false`.
5. Build `sre-event-lab:20260812.4` with ACR Tasks.
6. Deploy the Container App and three scheduled-query alert rules with `deployContainerApp=true`.
7. Poll revision health and `/healthz`.
8. Generate normal baseline request and dependency telemetry.
9. Create and configure Azure SRE Agent through `https://sre.azure.com`.
10. Execute S1, S2, and S3 sequentially with recovery gates.
11. Complete the report, remove the recorded Agent subscription role assignment, and delete the tagged resource group.

---

## 8. Validation Criteria

- Python tests pass with no failures.
- Shell scripts pass `bash -n`.
- Bicep compiles without warnings or errors.
- ARM validation and what-if succeed before resource creation.
- ACR cloud build succeeds.
- Container App revision is Healthy and `/healthz` returns HTTP 200.
- Normal AppRequests and AppDependencies telemetry arrives before incident injection.
- Each scenario produces the intended alert and returns to healthy state.
- Cleanup removes only the recorded role assignment and tagged lab resource group.

---

## 9. Execution Checklist

### Phase 1: Planning

- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location
- [x] Prepare resource inventory
- [x] Fetch quotas and validate capacity
- [x] Scan codebase
- [x] Select recipe
- [x] Plan architecture
- [x] User approved the design; unavailable review gates selected the recommended option under autopilot instructions

### Phase 2: Preparation

- [x] Install and update official `microsoft/azure-skills` globally
- [x] Research Azure SRE Agent, Container Apps, Application Insights, Azure Monitor alerts, Storage, and managed identity requirements
- [x] Generate application and tests
- [x] Generate Bicep infrastructure
- [x] Generate deployment, scenario, evidence, and cleanup tooling
- [x] Apply managed identity and least-privilege RBAC
- [x] Add runbook, operator guide, and results report
- [x] Set status to `Ready for Validation`

### Phase 3: Validation and Deployment

- [x] All validation checks pass
  - [x] Core Validation (CLI, auth, build, validate, what-if) using the official `validate-deployment.sh`
  - [x] Bicep compilation/lint validation
  - [x] Azure Policy validation
- [ ] Fix all validation blockers and repeat the validation workflow
- [x] Invoke `azure-deploy`
- [x] Verify baseline telemetry
- [x] Configure Azure SRE Agent
- [x] Execute and score S1-S3
- [x] Publish results and evidence captures
- [ ] Cleanup pending explicit confirmation; lab retained with `expiresOn=2026-08-13`

---

## 10. Validation Proof

Validated: 2026-08-12T03:40:00Z

| Check | Result | Evidence |
|---|---|---|
| Azure CLI | PASS | CLI installed and current account authenticated |
| Subscription | PASS | `95933ae5-0201-4a21-a1fc-8051a7437982` |
| Bicep build/lint | PASS | `subscription.bicep` compiled with no warnings |
| ARM validation | PASS | subscription-scope deployment validation succeeded in `koreacentral` |
| What-if | PASS | Create 12, Modify 0, Delete 0 |
| Azure Policy | PASS | 3 assignments inspected; all target SQL/Data Protection and do not conflict with this deployment |
| Name availability | PASS | `acrsrelab95933ae5`, `stsrelab95933ae5` available |
| Quota | PASS | Container Apps environments 0/50; Storage accounts 0/250 |

Commands:

```bash
bash ~/.agents/skills/azure-validate/references/recipes/scripts/validate-deployment.sh \
  --scope sub \
  --location koreacentral \
  --template monitor/sre-agent-event-lab/infra/subscription.bicep \
  --parameters monitor/sre-agent-event-lab/infra/subscription.bicepparam \
  --subscription 95933ae5-0201-4a21-a1fc-8051a7437982

monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/app/tests \
  monitor/sre-agent-event-lab/scripts/tests -q

bash -n monitor/sre-agent-event-lab/scripts/*.sh
az bicep build \
  --file monitor/sre-agent-event-lab/infra/subscription.bicep \
  --stdout >/dev/null

az policy assignment list \
  --scope /subscriptions/95933ae5-0201-4a21-a1fc-8051a7437982 \
  --disable-scope-strict-match -o json
```

Results:

```text
Official deployment validator: OVERALL PASS
What-if: Create 12, Modify 0, Delete 0
Tests: 11 passed, 0 warnings
Shell parse: PASS
Bicep build/lint: PASS, 0 warnings
Azure Policy: PASS, no assignment conflicts
Static RBAC review: PASS
```

---

## 11. Role Assignment Verification

- Status: Verified
- Identity checked: `id-sre-event-lab-95933ae5` user-assigned managed identity
- `AcrPull` (`7f951dda-4ed3-4680-a7ca-43fe172d538d`): registry scope, required for Container App image pulls
- `Storage Blob Data Reader` (`2a2b9908-6ea1-4ae2-8e65-a410df84e7d1`): `documents` container scope, matches the application's read-only `list_blobs` operation
- Assignment names: deterministic GUIDs derived from scope, identity, and role definition
- Principal type: `ServicePrincipal`
- Local user data-plane role: not required because Blob functional validation runs through the deployed managed identity
- Issues: none
