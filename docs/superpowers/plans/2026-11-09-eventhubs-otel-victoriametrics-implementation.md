# Event Hubs OpenTelemetry·VictoriaMetrics Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Premium Event Hubs platform metrics와 consumer lag를 OTel Collector Contrib에서 수집해 AKS VictoriaMetrics에 scrape와 remote write로 저장하고, agent가 검증한 Grafana dashboard와 실제 캡처를 포함한 재현 가능한 `azd` 실습을 만든다.

**Architecture:** Korea Central의 임시 RG에 Premium Event Hubs, telemetry용 Standard Event Hubs, checkpoint Storage, ACR, AKS, Gateway VM을 Bicep으로 만든다. VM의 Collector는 `azuremonitorreceiver`, `azureeventhubreceiver`, Prometheus lag receiver를 source별로 fan-out하고 AKS의 VMAgent scrape와 VMSingle remote write를 동시에 검증한다. Dedicated는 생성하지 않고 기존 cluster resource ID가 명시된 경우에만 config를 렌더링하는 runtime 미검증 profile로 둔다.

**Tech Stack:** Azure Developer CLI, Bicep, Azure CLI, AKS 1.36, Python 3.12, Azure Event Hubs SDK, Azure Blob checkpoint store, OpenTelemetry Collector Contrib 0.165.0, VictoriaMetrics Operator 0.75.2, VictoriaMetrics 1.155.0, Grafana OSS 13.3.0, Docker Compose, pytest, Playwright.

## Global Constraints

- 기본 배포 리전은 `koreacentral`, Event Hubs는 Premium 1 PU다.
- Dedicated cluster를 생성하는 Bicep·hook·script를 작성하지 않는다.
- `existingDedicatedClusterResourceId`는 기존 Dedicated read-only 수집 profile만 활성화한다.
- Premium의 `NamespaceCpuUsage`/`NamespaceMemoryUsage`와 Dedicated의 `CPU`/`AvailableMemory`를 같은 의미로 합치지 않는다.
- `OutgoingRequests`는 지원 지표로 만들거나 추정하지 않는다.
- OTel Collector, VictoriaMetrics, Grafana, fallback exporter image는 tag와 digest를 모두 기록한다.
- Azure workload 인증은 Managed Identity 또는 AKS Workload Identity만 사용한다.
- connection string, SAS key, Grafana password, subscription/resource ID, 실제 IP·hostname을 공개 artifact에 커밋하지 않는다.
- raw series에는 `source_path`와 `delivery_path`가 항상 존재해야 한다.
- 누락 series를 0으로 치환하지 않고 0행과 실제 0값을 구분한다.
- 최종 dashboard 캡처는 실제 배포 화면이어야 하며 mockup으로 대체하지 않는다.
- 실제 배포·query·capture·cleanup이 모두 확인되기 전 `verification_status: verified`를 사용하지 않는다.

## File Map

```text
docs-taxonomy.yml
docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/
├── index.md
├── images/
│   ├── architecture.png
│   └── grafana-dashboard.png
├── lab/index.md
└── samples/eventhubs-otel-victoriametrics-lab/
    ├── sample.yml
    ├── README.md
    ├── azure.yaml
    ├── infra/
    │   ├── main.bicep
    │   ├── main.parameters.json
    │   └── modules/
    │       ├── foundation.bicep
    │       ├── messaging.bicep
    │       └── compute.bicep
    ├── gateway/
    │   ├── compose.yaml
    │   ├── collector.base.yaml
    │   ├── grafana/provisioning/datasources/victoriametrics.yaml
    │   └── render_collector.py
    ├── workloads/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   ├── producer.py
    │   ├── consumer.py
    │   ├── lag_exporter.py
    │   └── lag.py
    ├── k8s/
    │   ├── namespace.yaml
    │   ├── victoria-values.yaml
    │   ├── victoria.yaml
    │   ├── scrape.yaml
    │   └── workloads.yaml
    ├── agent/
    │   ├── probe.py
    │   ├── build_dashboard.py
    │   ├── verify_panels.py
    │   └── capture.mjs
    ├── scripts/
    │   ├── azd-configure.sh
    │   ├── azd-postprovision.sh
    │   ├── azd-deploy.sh
    │   ├── run-scenario.sh
    │   ├── collect-evidence.sh
    │   └── cleanup-external.sh
    └── tests/
        ├── test_azd_project.py
        ├── test_bicep_contract.py
        ├── test_collector_config.py
        ├── test_lag.py
        ├── test_dashboard.py
        └── test_hooks.py
```

---

### Task 1: Topic package metadata and repository contract

**Files:**
- Modify: `docs-taxonomy.yml:27-82`
- Create initially as `needs-review`: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/index.md`
- Create initially as `needs-review`: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/lab/index.md`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/sample.yml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/README.md`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py`

**Interfaces:**
- Consumes: repository public-document and sample contracts from `AGENTS.md`.
- Produces: canonical service/technology slugs and the sample root path used by every later task.

- [ ] **Step 1: Write the failing repository-contract test**

```python
from pathlib import Path
import yaml

LAB_ROOT = Path(__file__).parents[1]
REPO_ROOT = Path(__file__).parents[7]
TAXONOMY = REPO_ROOT / "docs-taxonomy.yml"


def test_taxonomy_declares_event_hubs_and_victoriametrics():
    data = yaml.safe_load(TAXONOMY.read_text())
    assert data["services"]["azure-event-hubs"] == "Azure Event Hubs"
    assert data["technologies"]["victoriametrics"] == "VictoriaMetrics"


def test_sample_manifest_is_runnable_and_referenced_by_both_pages():
    manifest = yaml.safe_load((LAB_ROOT / "sample.yml").read_text())
    assert manifest == {
        "title": "Event Hubs OpenTelemetry VictoriaMetrics lab",
        "description": "Deploys and verifies Event Hubs metrics, consumer lag, dual VictoriaMetrics ingestion paths, and an agent-built Grafana dashboard.",
        "kind": "runnable",
        "used_by": ["index", "lab"],
    }
```

- [ ] **Step 2: Run the test and confirm RED**

Run:

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
```

Expected: FAIL because taxonomy keys and `sample.yml` do not exist.

- [ ] **Step 3: Add the taxonomy entries and sample manifest**

Add under `services:`:

```yaml
  azure-event-hubs: Azure Event Hubs
```

Add under `technologies:`:

```yaml
  victoriametrics: VictoriaMetrics
```

Create `sample.yml`:

```yaml
title: Event Hubs OpenTelemetry VictoriaMetrics lab
description: Deploys and verifies Event Hubs metrics, consumer lag, dual VictoriaMetrics ingestion paths, and an agent-built Grafana dashboard.
kind: runnable
used_by:
  - index
  - lab
```

Create the parent guide, lab entry, and sample README in `needs-review` state with the official sources, SKU scope, cost, cleanup requirement, and explicit statement that runtime evidence does not exist yet. The repository metadata validator requires both `used_by` slugs and the sample README to exist as soon as the sample manifest is added.

- [ ] **Step 4: Run the focused and metadata tests**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_metadata.py
```

Expected: focused test PASS; metadata validator remains green for existing public documents.

- [ ] **Step 5: Commit**

```bash
git add docs-taxonomy.yml docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring
git commit -m "test(eventhubs): establish observability lab contract"
```

---

### Task 2: azd project and subscription-scoped Bicep interface

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/azure.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/main.bicep`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/main.parameters.json`
- Extend: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py`

**Interfaces:**
- Consumes: `environmentName`, `location`, `operatorEgressCidr`, secure `grafanaAdminPassword`, `gatewayAdminSshPublicKey`, optional `existingDedicatedClusterResourceId`.
- Produces: stable azd outputs consumed by hooks: `AZURE_RESOURCE_GROUP`, `AKS_CLUSTER_NAME`, `ACR_NAME`, `ACR_LOGIN_SERVER`, `GATEWAY_VM_NAME`, `GATEWAY_PUBLIC_IP`, `GATEWAY_PRIVATE_IP`, `PREMIUM_NAMESPACE_NAME`, `WORKLOAD_EVENTHUB_NAME`, `WORKLOAD_CONSUMER_GROUP`, `TELEMETRY_NAMESPACE_NAME`, `TELEMETRY_EVENTHUB_NAME`, `CHECKPOINT_ACCOUNT_NAME`, `KEY_VAULT_NAME`, `PRODUCER_CLIENT_ID`, `CONSUMER_CLIENT_ID`, `VMSINGLE_PRIVATE_IP`.

- [ ] **Step 1: Add failing azd/Bicep contract tests**

```python
import re


def test_azure_yaml_declares_lifecycle_hooks_without_local_docker_service():
    text = (LAB_ROOT / "azure.yaml").read_text()
    assert "services:" not in text
    for hook, script in {
        "preprovision": "./scripts/azd-configure.sh",
        "postprovision": "./scripts/azd-postprovision.sh",
        "postdeploy": "./scripts/azd-deploy.sh",
        "predown": "./scripts/cleanup-external.sh",
    }.items():
        assert re.search(rf"^  {hook}:.*?run: {re.escape(script)}$", text, re.M | re.S)


def test_main_bicep_never_creates_a_dedicated_cluster():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()
    assert "targetScope = 'subscription'" in text
    assert "param existingDedicatedClusterResourceId string = ''" in text
    assert "Microsoft.EventHub/clusters@" not in text


def test_main_bicep_exports_hook_contract():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()
    names = (
        "AZURE_RESOURCE_GROUP", "AKS_CLUSTER_NAME", "ACR_NAME",
        "ACR_LOGIN_SERVER", "GATEWAY_VM_NAME", "GATEWAY_PUBLIC_IP",
        "GATEWAY_PRIVATE_IP", "PREMIUM_NAMESPACE_NAME",
        "WORKLOAD_EVENTHUB_NAME", "WORKLOAD_CONSUMER_GROUP",
        "TELEMETRY_NAMESPACE_NAME", "TELEMETRY_EVENTHUB_NAME",
        "CHECKPOINT_ACCOUNT_NAME", "KEY_VAULT_NAME",
        "PRODUCER_CLIENT_ID", "CONSUMER_CLIENT_ID", "VMSINGLE_PRIVATE_IP",
    )
    for name in names:
        assert f"output {name} " in text
```

- [ ] **Step 2: Run the tests and confirm RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
```

Expected: FAIL because `azure.yaml` and Bicep files do not exist.

- [ ] **Step 3: Create `azure.yaml`**

```yaml
# yaml-language-server: $schema=https://raw.githubusercontent.com/Azure/azure-dev/main/schemas/v1.0/azure.yaml.json
name: eventhubs-otel-victoriametrics-lab
infra:
  provider: bicep
  path: infra
  module: main
hooks:
  preprovision:
    shell: sh
    run: ./scripts/azd-configure.sh
    interactive: true
    continueOnError: false
  postprovision:
    shell: sh
    run: ./scripts/azd-postprovision.sh
    interactive: true
    continueOnError: false
  postdeploy:
    shell: sh
    run: ./scripts/azd-deploy.sh
    interactive: true
    continueOnError: false
  predown:
    shell: sh
    run: ./scripts/cleanup-external.sh --yes
    interactive: true
    continueOnError: false
```

- [ ] **Step 4: Create the subscription template and parameter mapping**

`main.bicep` must use this interface and module graph:

```bicep
targetScope = 'subscription'

param environmentName string
param location string = 'koreacentral'
param operatorEgressCidr string
param kubernetesVersion string = '1.36'
param existingDedicatedClusterResourceId string = ''
@secure()
param grafanaAdminPassword string
param gatewayAdminSshPublicKey string

var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName, 'lab': 'eventhubs-otel-victoriametrics' }
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module foundation 'modules/foundation.bicep' = {
  name: 'foundation'
  scope: rg
  params: { location: location, token: token, tags: tags, operatorEgressCidr: operatorEgressCidr, grafanaAdminPassword: grafanaAdminPassword }
}
module messaging 'modules/messaging.bicep' = {
  name: 'messaging'
  scope: rg
  params: { location: location, token: token, tags: tags, gatewayPrincipalId: foundation.outputs.gatewayPrincipalId, producerPrincipalId: foundation.outputs.producerPrincipalId, consumerPrincipalId: foundation.outputs.consumerPrincipalId }
}
module compute 'modules/compute.bicep' = {
  name: 'compute'
  scope: rg
  params: { location: location, token: token, tags: tags, kubernetesVersion: kubernetesVersion, operatorEgressCidr: operatorEgressCidr, gatewayAdminSshPublicKey: gatewayAdminSshPublicKey, vnetId: foundation.outputs.vnetId, aksSubnetId: foundation.outputs.aksSubnetId, gatewaySubnetId: foundation.outputs.gatewaySubnetId, gatewayIdentityId: foundation.outputs.gatewayIdentityId, gatewayClientId: foundation.outputs.gatewayClientId, acrId: foundation.outputs.acrId, keyVaultName: foundation.outputs.keyVaultName }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AKS_CLUSTER_NAME string = compute.outputs.aksName
output ACR_NAME string = foundation.outputs.acrName
output ACR_LOGIN_SERVER string = foundation.outputs.acrLoginServer
output GATEWAY_VM_NAME string = compute.outputs.gatewayVmName
output GATEWAY_PUBLIC_IP string = compute.outputs.gatewayPublicIp
output GATEWAY_PRIVATE_IP string = compute.outputs.gatewayPrivateIp
output PREMIUM_NAMESPACE_NAME string = messaging.outputs.premiumNamespaceName
output WORKLOAD_EVENTHUB_NAME string = messaging.outputs.workloadEventHubName
output WORKLOAD_CONSUMER_GROUP string = messaging.outputs.workloadConsumerGroup
output TELEMETRY_NAMESPACE_NAME string = messaging.outputs.telemetryNamespaceName
output TELEMETRY_EVENTHUB_NAME string = messaging.outputs.telemetryEventHubName
output CHECKPOINT_ACCOUNT_NAME string = foundation.outputs.storageName
output KEY_VAULT_NAME string = foundation.outputs.keyVaultName
output PRODUCER_CLIENT_ID string = foundation.outputs.producerClientId
output CONSUMER_CLIENT_ID string = foundation.outputs.consumerClientId
output VMSINGLE_PRIVATE_IP string = foundation.outputs.vmSinglePrivateIp
output EXISTING_DEDICATED_CLUSTER_RESOURCE_ID string = existingDedicatedClusterResourceId
```

`main.parameters.json`:

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "environmentName": { "value": "${AZURE_ENV_NAME}" },
    "location": { "value": "${AZURE_LOCATION}" },
    "operatorEgressCidr": { "value": "${OPERATOR_EGRESS_CIDR}" },
    "grafanaAdminPassword": { "value": "${GRAFANA_ADMIN_PASSWORD}" },
    "gatewayAdminSshPublicKey": { "value": "${GATEWAY_ADMIN_SSH_PUBLIC_KEY}" },
    "existingDedicatedClusterResourceId": { "value": "${EXISTING_DEDICATED_CLUSTER_RESOURCE_ID=}" }
  }
}
```

- [ ] **Step 5: Verify the azd contract before resource modules are implemented**

Run the contract test now; defer `az bicep build` until Tasks 3–5 have implemented all three modules.

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
```

Expected: tests PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/azure.yaml docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py
git commit -m "feat(eventhubs): define azd deployment contract"
```

---

### Task 3: Foundation resources, identities, and least-privilege boundaries

**Files:**
- Replace: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/foundation.bicep`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py`

**Interfaces:**
- Produces VNet/subnets, ACR, Storage containers, Key Vault secret, Gateway user-assigned identity, producer/consumer identities, and reserved VMSingle private IP `10.42.2.20`.
- Later tasks consume output IDs and principal/client IDs only; no secret output is allowed.

- [ ] **Step 1: Write failing foundation tests**

```python
from pathlib import Path

LAB_ROOT = Path(__file__).parents[1]
FOUNDATION = LAB_ROOT / "infra" / "modules" / "foundation.bicep"


def test_foundation_has_no_secret_outputs_and_declares_required_resources():
    text = FOUNDATION.read_text()
    for resource_type in (
        "Microsoft.Network/virtualNetworks@",
        "Microsoft.ContainerRegistry/registries@",
        "Microsoft.Storage/storageAccounts@",
        "Microsoft.KeyVault/vaults@",
        "Microsoft.ManagedIdentity/userAssignedIdentities@",
    ):
        assert resource_type in text
    assert "output grafanaPassword" not in text
    assert "output connectionString" not in text


def test_foundation_uses_fixed_non_overlapping_subnets():
    text = FOUNDATION.read_text()
    assert "10.42.0.0/16" in text
    assert "10.42.1.0/24" in text
    assert "10.42.2.0/24" in text
    assert "10.42.2.20" in text
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

Expected: FAIL because the foundation module is missing or does not yet declare the required resources.

- [ ] **Step 3: Implement foundation module**

The module must create:

```bicep
param location string
param token string
param tags object
param operatorEgressCidr string
@secure()
param grafanaAdminPassword string

var gatewaySubnetPrefix = '10.42.1.0/24'
var aksSubnetPrefix = '10.42.2.0/24'
var vmSinglePrivateIp = '10.42.2.20'
```

Required resources and settings:

- VNet `10.42.0.0/16`; subnets `gateway` and `aks`; AKS subnet private endpoint policies disabled only if required by actual service behavior.
- ACR Basic with admin disabled.
- Storage Standard_LRS, shared key access disabled, default OAuth authentication enabled, containers `workload-checkpoints` and `collector-checkpoints`.
- Key Vault RBAC authorization enabled, public network access allowed only for deployment bootstrap, purge protection disabled because the whole lab must be removable.
- A Key Vault secret named `grafana-admin-password` stores the secure `grafanaAdminPassword` parameter. No output may expose its value.
- User-assigned identities: `gateway`, `producer`, `consumer`.
- Built-in role assignments available at this stage: Gateway `AcrPull`, Gateway `Key Vault Secrets User`, Consumer `Storage Blob Data Contributor`, and Gateway `Storage Blob Data Reader`. Task 5 assigns `AcrPull` to the AKS kubelet identity after AKS creates it.

The output contract is:

```bicep
output vnetId string = vnet.id
output gatewaySubnetId string = vnet.properties.subnets[0].id
output aksSubnetId string = vnet.properties.subnets[1].id
output acrId string = acr.id
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output storageName string = storage.name
output keyVaultName string = keyVault.name
output gatewayIdentityId string = gatewayIdentity.id
output gatewayPrincipalId string = gatewayIdentity.properties.principalId
output gatewayClientId string = gatewayIdentity.properties.clientId
output producerPrincipalId string = producerIdentity.properties.principalId
output producerClientId string = producerIdentity.properties.clientId
output consumerPrincipalId string = consumerIdentity.properties.principalId
output consumerClientId string = consumerIdentity.properties.clientId
output vmSinglePrivateIp string = vmSinglePrivateIp
```

- [ ] **Step 4: Build and test GREEN**

```bash
az bicep build --file docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/main.bicep
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

Expected: exit 0 and all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/foundation.bicep docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py
git commit -m "feat(eventhubs): add secure lab foundation"
```

---

### Task 4: Event Hubs resources, Diagnostic Settings, and messaging RBAC

**Files:**
- Replace: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/messaging.bicep`
- Extend: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py`

**Interfaces:**
- Consumes Gateway, producer, consumer principal IDs.
- Produces Premium workload namespace/event hub/consumer group, Standard telemetry namespace/event hub/consumer group, diagnostic setting, and scoped role assignments.

- [ ] **Step 1: Add failing messaging assertions**

```python
MESSAGING = LAB_ROOT / "infra" / "modules" / "messaging.bicep"


def test_messaging_creates_premium_and_standard_but_no_dedicated_cluster():
    text = MESSAGING.read_text()
    assert "name: 'Premium'" in text
    assert "capacity: 1" in text
    assert "name: 'Standard'" in text
    assert "Microsoft.EventHub/clusters@" not in text
    assert "Microsoft.Insights/diagnosticSettings@2021-05-01-preview" in text


def test_messaging_roles_are_resource_scoped():
    text = MESSAGING.read_text()
    assert "scope: workloadHub" in text
    assert "scope: telemetryHub" in text
    assert "Monitoring Reader" in text or "43d0d8ad-25c7-4714-9337-8ba259a9fe05" in text
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

- [ ] **Step 3: Implement messaging resources**

Use these stable names and settings:

```bicep
var premiumNamespaceName = 'ehp-${token}'
var telemetryNamespaceName = 'eht-${token}'
var workloadEventHubName = 'workload'
var workloadConsumerGroup = 'slow-consumer'
var telemetryEventHubName = 'platform-metrics'
var telemetryConsumerGroup = 'otel-collector'
```

- Premium namespace: `sku.name = 'Premium'`, `tier = 'Premium'`, `capacity = 1`, zone redundancy according to regional support returned by deployment.
- Workload Event Hub: 4 partitions, 1-day retention.
- Standard telemetry namespace and Event Hub: 2 partitions, 1-day retention.
- Diagnostic authorization rule is used only by the Azure service and never emitted as output.
- Diagnostic setting selects `AllMetrics` and points to the telemetry Event Hub.
- Gateway: Monitoring Reader on Premium namespace, Data Receiver on workload and telemetry hubs.
- Producer: Data Sender on workload hub.
- Consumer: Data Receiver on workload hub.

Outputs:

```bicep
output premiumNamespaceName string = premiumNamespace.name
output premiumNamespaceId string = premiumNamespace.id
output workloadEventHubName string = workloadHub.name
output workloadConsumerGroup string = workloadConsumerGroup
output telemetryNamespaceName string = telemetryNamespace.name
output telemetryEventHubName string = telemetryHub.name
```

- [ ] **Step 4: Verify Bicep and contracts**

```bash
az bicep build --file docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/main.bicep
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/messaging.bicep docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py
git commit -m "feat(eventhubs): provision monitored messaging path"
```

---

### Task 5: AKS and Gateway VM compute layer

**Files:**
- Replace: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/compute.bicep`
- Extend: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py`

**Interfaces:**
- Consumes foundation network, identity, ACR, Key Vault outputs.
- Produces AKS with OIDC/Workload Identity and Gateway VM with public Grafana access restricted to `operatorEgressCidr`.

- [ ] **Step 1: Add failing compute tests**

```python
COMPUTE = LAB_ROOT / "infra" / "modules" / "compute.bicep"


def test_compute_enables_workload_identity_and_restricts_public_ports():
    text = COMPUTE.read_text()
    assert "enableOIDCIssuer: true" in text
    assert "enableWorkloadIdentity: true" in text
    assert "destinationPortRange: '3000'" in text
    assert "sourceAddressPrefix: operatorEgressCidr" in text
    assert "destinationPortRange: '22'" not in text


def test_gateway_uses_managed_identity_and_no_embedded_secret():
    text = COMPUTE.read_text()
    assert "type: 'UserAssigned'" in text
    assert "adminPassword" not in text
    assert "disablePasswordAuthentication: true" in text
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

- [ ] **Step 3: Implement compute resources**

AKS requirements:

```bicep
properties: {
  kubernetesVersion: kubernetesVersion
  dnsPrefix: 'aks-${token}'
  enableRBAC: true
  oidcIssuerProfile: { enabled: true }
  securityProfile: { workloadIdentity: { enabled: true } }
  apiServerAccessProfile: { authorizedIPRanges: [operatorEgressCidr] }
  agentPoolProfiles: [{
    name: 'system'
    count: 1
    vmSize: 'Standard_D4as_v5'
    mode: 'System'
    osType: 'Linux'
    vnetSubnetID: aksSubnetId
  }]
  networkProfile: { networkPlugin: 'azure', networkPluginMode: 'overlay', podCidr: '10.244.0.0/16', serviceCidr: '10.0.0.0/16', dnsServiceIP: '10.0.0.10', loadBalancerSku: 'standard' }
}
```

After the managed cluster creates its kubelet identity, assign `AcrPull` on `acrId` to `aks.properties.identityProfile.kubeletidentity.objectId` in this module.

Gateway requirements:

- Ubuntu 24.04 LTS Gen2, `Standard_D2as_v5`, user-assigned Gateway identity.
- Public IP Standard static; NSG allows TCP 3000 only from `operatorEgressCidr`.
- No SSH rule; password auth disabled. `gatewayAdminSshPublicKey` comes from a local key pair under ignored `.azure/${AZURE_ENV_NAME}/`; the private key never enters Bicep, azd output, VM Run Command, or Git.
- Private IP on Gateway subnet.
- cloud-init installs Docker Engine, Compose plugin, Azure CLI, jq, and creates `/opt/eventhubs-observability` owned by root.
- cloud-init does not start Collector until postprovision has written runtime environment and compose files.

Outputs:

```bicep
output aksName string = aks.name
output aksOidcIssuer string = aks.properties.oidcIssuerProfile.issuerURL
output gatewayVmName string = vm.name
output gatewayPublicIp string = publicIp.properties.ipAddress
output gatewayPrivateIp string = nic.properties.ipConfigurations[0].properties.privateIPAddress
```

- [ ] **Step 4: Verify**

```bash
az bicep build --file docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/main.bicep
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/infra/modules/compute.bicep docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_bicep_contract.py
git commit -m "feat(eventhubs): add AKS and collector gateway"
```

---

### Task 6: Producer, slow consumer, and lag calculation

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/requirements.txt`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/lag.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/producer.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/consumer.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/lag_exporter.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/Dockerfile`
- Create from registry inspection: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/images.lock`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_lag.py`

**Interfaces:**
- `compute_lag(last_enqueued_sequence_number: int | None, checkpoint_sequence_number: int | None) -> LagResult`.
- Producer and consumer authenticate with `DefaultAzureCredential(managed_identity_client_id=AZURE_CLIENT_ID)`.
- Exporter exposes `eventhubs_consumer_lag_messages`, `eventhubs_checkpoint_present`, and `eventhubs_last_checkpoint_unixtime` on port 9464.

- [ ] **Step 1: Write lag unit tests**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1] / "workloads"))
from lag import LagResult, compute_lag


def test_lag_is_sequence_difference():
    assert compute_lag(120, 99) == LagResult(messages=21, checkpoint_present=True, partition_empty=False)


def test_missing_checkpoint_is_reported_not_coerced_to_zero():
    assert compute_lag(120, None) == LagResult(messages=None, checkpoint_present=False, partition_empty=False)


def test_empty_partition_has_zero_lag():
    assert compute_lag(None, None) == LagResult(messages=0, checkpoint_present=False, partition_empty=True)


def test_checkpoint_ahead_is_clamped_and_marked_invalid():
    result = compute_lag(10, 11)
    assert result.messages == 0
    assert result.invalid_order is True
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_lag.py -q
```

- [ ] **Step 3: Implement the pure lag model**

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class LagResult:
    messages: int | None
    checkpoint_present: bool
    partition_empty: bool
    invalid_order: bool = False


def compute_lag(last_enqueued_sequence_number, checkpoint_sequence_number):
    if last_enqueued_sequence_number is None:
        return LagResult(0, checkpoint_sequence_number is not None, True)
    if checkpoint_sequence_number is None:
        return LagResult(None, False, False)
    if checkpoint_sequence_number > last_enqueued_sequence_number:
        return LagResult(0, True, False, True)
    return LagResult(last_enqueued_sequence_number - checkpoint_sequence_number, True, False)
```

- [ ] **Step 4: Implement executable workloads**

`requirements.txt` pins:

```text
azure-eventhub==5.15.0
azure-eventhub-checkpointstoreblob-aio==1.2.0
azure-identity==1.25.1
azure-storage-blob==12.27.1
prometheus-client==0.23.1
```

Producer behavior:

- sends JSON containing `sequence`, `sent_at`, and a 1 KiB payload;
- records actual accepted event count to stdout every 10 seconds;
- environment: `EVENTHUB_FULLY_QUALIFIED_NAMESPACE`, `EVENTHUB_NAME`, `AZURE_CLIENT_ID`, `PRODUCER_EVENTS_PER_SECOND`.

Consumer behavior:

- uses `BlobCheckpointStore` and the configured consumer group;
- sleeps `CONSUMER_PROCESSING_DELAY_MS` after each event;
- checkpoints every `CHECKPOINT_EVERY_EVENTS` events;
- logs actual processed count and latest sequence by partition.

Lag exporter behavior:

- reads partition IDs and `get_partition_properties()` from Event Hubs;
- calls checkpoint store `list_checkpoints()`;
- invokes `compute_lag()` for every partition;
- does not emit a lag sample when `messages is None`; emits checkpoint-presence state instead;
- updates metrics every `LAG_POLL_SECONDS=15`.

`Dockerfile`:

```dockerfile
ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lag.py producer.py consumer.py lag_exporter.py ./
USER 65532:65532
ENTRYPOINT ["python"]
```

Resolve the multi-architecture manifest digest with:

```bash
docker buildx imagetools inspect python:3.12.8-slim --format '{{json .Manifest.Digest}}'
```

Write `images.lock` as one exact line by concatenating `PYTHON_IMAGE=python:3.12.8-slim@` with the returned `sha256:` digest. The ACR build hook reads the complete locked value and passes it through `--build-arg PYTHON_IMAGE`; tests reject an unpinned value or a digest that is not 64 lowercase hex characters.

- [ ] **Step 5: Run tests and container import checks**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_lag.py -q
python -m py_compile docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads/*.py
```

Expected: PASS and no syntax errors.

- [ ] **Step 6: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/workloads docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_lag.py
git commit -m "feat(eventhubs): add lag-producing workloads"
```

---

### Task 7: Collector, fallback, Grafana, and Dedicated config renderer

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/collector.base.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/render_collector.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/compose.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/grafana/provisioning/datasources/victoriametrics.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_collector_config.py`

**Interfaces:**
- `render_config(env: Mapping[str, str]) -> dict` produces one complete Collector config.
- Premium is always enabled; Dedicated is enabled only when `EXISTING_DEDICATED_CLUSTER_RESOURCE_ID` is nonempty.
- Prometheus exporter port 8889 is scrape-only; remote write target is `http://10.42.2.20:8428/api/v1/write`.

- [ ] **Step 1: Write failing renderer tests**

```python
import sys
from pathlib import Path
import yaml
sys.path.insert(0, str(Path(__file__).parents[1] / "gateway"))
from render_collector import render_config

BASE_ENV = {
    "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
    "AZURE_RESOURCE_GROUP": "rg-test",
    "PREMIUM_NAMESPACE_NAME": "ehp-test",
    "TELEMETRY_NAMESPACE": "eht-test.servicebus.windows.net",
    "TELEMETRY_EVENTHUB_NAME": "platform-metrics",
    "CHECKPOINT_ACCOUNT_URL": "https://sttest.blob.core.windows.net",
    "GATEWAY_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
}


def test_premium_config_has_both_receivers_and_delivery_paths():
    config = render_config(BASE_ENV)
    assert "azuremonitor" in config["receivers"]
    assert "azureeventhub" in config["receivers"]
    assert config["exporters"]["prometheus"]["endpoint"] == "0.0.0.0:8889"
    assert config["exporters"]["prometheusremotewrite"]["endpoint"].endswith("/api/v1/write")
    assert "metrics/api-scrape" in config["service"]["pipelines"]
    assert "metrics/api-push" in config["service"]["pipelines"]


def test_dedicated_profile_is_absent_by_default():
    config = render_config(BASE_ENV)
    serialized = yaml.safe_dump(config)
    assert "microsoft.eventhub/clusters" not in serialized
    assert "ClusterUtilization" not in serialized


def test_dedicated_profile_requires_existing_resource_id():
    env = BASE_ENV | {"EXISTING_DEDICATED_CLUSTER_RESOURCE_ID": "/subscriptions/example/resourceGroups/rg-existing/providers/Microsoft.EventHub/clusters/ehd-existing"}
    serialized = yaml.safe_dump(render_config(env))
    assert "microsoft.eventhub/clusters" in serialized
    assert "AvailableMemory" in serialized
    assert "ClusterUtilization" in serialized
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_collector_config.py -q
```

- [ ] **Step 3: Implement renderer and Collector semantics**

`azuremonitor` receiver configuration must include:

```yaml
subscription_ids: ["${AZURE_SUBSCRIPTION_ID}"]
resource_groups: ["${AZURE_RESOURCE_GROUP}"]
services: ["Microsoft.EventHub/namespaces"]
collection_interval: 60s
initial_delay: 5s
use_batch_api: true
auth:
  authenticator: azureauth
metrics:
  microsoft.eventhub/namespaces:
    NamespaceCpuUsage: [Average, Maximum]
    NamespaceMemoryUsage: [Average, Maximum]
    IncomingRequests: [Total]
    SuccessfulRequests: [Total]
    ThrottledRequests: [Total]
    IncomingMessages: [Total]
    OutgoingMessages: [Total]
    IncomingBytes: [Total]
    OutgoingBytes: [Total]
```

The renderer must create distinct resource processors that add exact labels:

```yaml
attributes:
  - key: source_path
    action: upsert
    value: azure_monitor_api
  - key: delivery_path
    action: upsert
    value: scrape
```

Repeat with `remote_write`, and for diagnostic Event Hub and lag exporter sources. Do not share a processor instance between scrape and push if it would overwrite labels.

Both Prometheus exporters must enable resource-to-telemetry conversion so VictoriaMetrics stores those resource attributes as queryable labels:

```yaml
prometheus:
  endpoint: 0.0.0.0:8889
  resource_to_telemetry_conversion:
    enabled: true
prometheusremotewrite:
  endpoint: http://10.42.2.20:8428/api/v1/write
  resource_to_telemetry_conversion:
    enabled: true
```

`compose.yaml` must pin:

- `otel/opentelemetry-collector-contrib:0.165.0` by verified digest;
- `grafana/grafana:13.3.0` by verified digest;
- `webdevops/azure-metrics-exporter:26.10.0` under Compose profile `fallback`;
- custom lag image from ACR.

Grafana datasource:

```yaml
apiVersion: 1
datasources:
  - name: VictoriaMetrics
    uid: victoriametrics
    type: prometheus
    access: proxy
    url: http://10.42.2.20:8428
    isDefault: true
    jsonData:
      httpMethod: POST
```

- [ ] **Step 4: Verify renderer and Compose schema**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_collector_config.py -q
python docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/render_collector.py --env-file docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/test.env --output /tmp/collector.yaml
docker compose -f docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway/compose.yaml config --quiet
```

Expected: tests PASS, valid YAML, Compose exit 0. `test.env` contains only synthetic identifiers and is removed before commit or stored under `tests/fixtures/`.

- [ ] **Step 5: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/gateway docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_collector_config.py
git commit -m "feat(eventhubs): add dual-path collector gateway"
```

---

### Task 8: VictoriaMetrics and workload Kubernetes resources

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/namespace.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/victoria-values.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/victoria.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/scrape.yaml`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/workloads.yaml`
- Extend: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py`

**Interfaces:**
- VMSingle is reachable at static internal IP `10.42.2.20:8428`.
- VMAgent scrapes `GATEWAY_PRIVATE_IP:8889` through `VMStaticScrape`.
- Producer and consumer service accounts use federated identities supplied by postprovision.

- [ ] **Step 1: Add failing Kubernetes contract test**

```python

def test_kubernetes_manifests_keep_observability_private():
    root = LAB_ROOT / "k8s"
    victoria = (root / "victoria.yaml").read_text()
    scrape = (root / "scrape.yaml").read_text()
    workloads = (root / "workloads.yaml").read_text()
    assert "loadBalancerIP: 10.42.2.20" in victoria
    assert "service.beta.kubernetes.io/azure-load-balancer-internal: \"true\"" in victoria
    assert "kind: VMStaticScrape" in scrape
    assert "__GATEWAY_PRIVATE_IP__:8889" in scrape
    assert "azure.workload.identity/use: \"true\"" in workloads
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
```

- [ ] **Step 3: Create Kubernetes resources**

- Namespace `eventhubs-observability`.
- Operator Helm version `0.75.2` and chart values pin admission webhook and operator image digest.
- `VMSingle` version `v1.155.0`, 10 Gi managed-premium PVC, 7-day retention, internal LoadBalancer `10.42.2.20`.
- `VMAgent` selects all `VMStaticScrape` resources in the namespace and remote-writes to VMSingle.
- `VMStaticScrape` targets `__GATEWAY_PRIVATE_IP__:8889`, interval 30s, timeout 10s.
- Producer Deployment replicas 1 and consumer Deployment replicas 1, each with a dedicated Workload Identity service account.
- Lag exporter remains on Gateway VM, not in AKS, to exercise Collector Prometheus receiver locally.

- [ ] **Step 4: Validate client-side schemas**

```bash
kubectl apply --dry-run=client -f docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/namespace.yaml
kubectl apply --dry-run=client -f docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s/workloads.yaml
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py -q
```

- [ ] **Step 5: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/k8s docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_azd_project.py
git commit -m "feat(eventhubs): add VictoriaMetrics and lag workload manifests"
```

---

### Task 9: Safe azd lifecycle hooks

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/azd-configure.sh`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/azd-postprovision.sh`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/azd-deploy.sh`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/cleanup-external.sh`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_hooks.py`

**Interfaces:**
- Every Azure CLI call includes `--subscription "${AZURE_SUBSCRIPTION_ID}"` where supported.
- Hooks fail nonzero on missing tools, wrong subscription, unresolved role assignments, unhealthy rollout, empty required metrics, or failed cleanup.
- No hook creates Dedicated resources.

- [ ] **Step 1: Write failing static hook tests**

```python
from pathlib import Path
import os
import re

LAB_ROOT = Path(__file__).parents[1]


def test_all_hooks_exist_and_are_executable():
    for name in ("azd-configure.sh", "azd-postprovision.sh", "azd-deploy.sh", "cleanup-external.sh"):
        path = LAB_ROOT / "scripts" / name
        assert path.is_file()
        assert os.access(path, os.X_OK)


def test_hooks_pin_subscription_and_never_create_dedicated():
    text = "\n".join(path.read_text() for path in (LAB_ROOT / "scripts").glob("*.sh"))
    assert "az eventhubs cluster create" not in text
    assert "Microsoft.EventHub/clusters" not in text
    for match in re.findall(r"^\s*az\s+.*$", text, re.M):
        if "account show" not in match and "login" not in match:
            assert "--subscription" in match or "azd env" in match
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_hooks.py -q
```

- [ ] **Step 3: Implement hook behavior**

`azd-configure.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
for command in az azd curl openssl; do command -v "$command" >/dev/null || { echo "missing command: $command" >&2; exit 1; }; done
ACTIVE_SUB="$(az account show --query id -o tsv)"
AZURE_SUBSCRIPTION_ID="$(azd env get-value AZURE_SUBSCRIPTION_ID)"
[[ "$ACTIVE_SUB" == "$AZURE_SUBSCRIPTION_ID" ]] || { echo "active subscription mismatch" >&2; exit 1; }
EGRESS_IP="$(curl --fail --silent https://ifconfig.me/ip)"
azd env set OPERATOR_EGRESS_CIDR "${EGRESS_IP}/32"
azd env set AZURE_LOCATION koreacentral
if ! azd env get-value GRAFANA_ADMIN_PASSWORD >/dev/null 2>&1; then
  azd env set GRAFANA_ADMIN_PASSWORD "$(openssl rand -base64 32)"
fi
KEY_DIR=".azure/$(azd env get-value AZURE_ENV_NAME)"
mkdir -p "$KEY_DIR"
chmod 700 "$KEY_DIR"
if [[ ! -f "$KEY_DIR/gateway_ed25519" ]]; then
  ssh-keygen -q -t ed25519 -N '' -f "$KEY_DIR/gateway_ed25519"
fi
azd env set GATEWAY_ADMIN_SSH_PUBLIC_KEY "$(<"$KEY_DIR/gateway_ed25519.pub")"
```

`azd-postprovision.sh` performs, in order:

1. `az aks get-credentials` into `.azure/${AZURE_ENV_NAME}/kubeconfig`, never default kubeconfig.
2. create federated identity credentials for producer and consumer identities using the live AKS OIDC issuer.
3. build the workload image in ACR and resolve its digest.
4. install VictoriaMetrics Operator 0.75.2 and wait for CRDs/controller.
5. substitute only approved manifest tokens, apply VMSingle/VMAgent, wait for availability and internal IP.
6. upload compose/config files to Gateway with VM Run Command; retrieve Grafana secret from Key Vault inside the VM; start Compose.
7. test Collector `/` health and Grafana `/api/health` through the public endpoint.

`azd-deploy.sh` applies Workload Identity service accounts and workload Deployment, then calls `run-scenario.sh`, `collect-evidence.sh`, dashboard build/verify/capture.

`cleanup-external.sh` deletes federated credentials and local kubeconfig/evidence files that Bicep does not own; it must be idempotent and return 0 when resources never existed.

- [ ] **Step 4: Add fake-command execution tests**

Use temporary `az`, `azd`, `kubectl`, and `helm` executables on `PATH` that log arguments. Assert:

- wrong active subscription fails before mutation;
- preprovision stores `/32` egress CIDR;
- postprovision uses dedicated kubeconfig;
- cleanup is idempotent;
- no fake invocation contains Dedicated cluster creation.

- [ ] **Step 5: Run GREEN**

```bash
chmod +x docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/*.sh
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_hooks.py -q
shellcheck docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/*.sh
```

- [ ] **Step 6: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_hooks.py
git commit -m "feat(eventhubs): automate safe azd lifecycle"
```

---

### Task 10: Probe, dashboard generator, panel verification, and capture

**Files:**
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent/probe.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent/build_dashboard.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent/verify_panels.py`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent/capture.mjs`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_dashboard.py`

**Interfaces:**
- `probe.py` emits `evidence/probe.json` containing only metric names, safe labels, units, sample counts, freshness, and redacted resource names.
- `build_dashboard.py --probe evidence/probe.json --output evidence/dashboard.json` creates UID `eventhubs-otel-victoriametrics`.
- `verify_panels.py` exits nonzero for query error, 0 rows on required panels, NaN/Inf, or missing `source_path`/`delivery_path`.
- `capture.mjs` captures one complete dashboard PNG and never writes credentials.

- [ ] **Step 1: Write failing dashboard tests**

```python
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parents[1] / "agent"))
from build_dashboard import build_dashboard


def test_dashboard_contains_required_questions_and_unsupported_request_notice():
    dashboard = build_dashboard({"processing_units": 1, "dedicated_enabled": False})
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Premium CPU" in titles
    assert "Premium Memory" in titles
    assert "Consumer lag by partition" in titles
    assert "Receiver and delivery path comparison" in titles
    assert "Outgoing Requests support boundary" in titles


def test_dashboard_does_not_create_dedicated_panels_without_profile():
    dashboard = build_dashboard({"processing_units": 1, "dedicated_enabled": False})
    assert all("Dedicated" not in panel["title"] for panel in dashboard["panels"])


def test_committable_dashboard_has_no_environment_identifiers():
    dashboard = build_dashboard({"processing_units": 1, "dedicated_enabled": False})
    text = json.dumps(dashboard)
    assert "/subscriptions/" not in text
    assert "10.42." not in text
```

- [ ] **Step 2: Run RED**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_dashboard.py -q
```

- [ ] **Step 3: Implement probe and dashboard contracts**

Required panel groups:

1. Premium CPU gauge and Replica time series.
2. Premium memory gauge and Replica time series.
3. Incoming/successful/throttled request stats and bars.
4. Unsupported Outgoing Requests text panel with Microsoft Learn link.
5. Incoming/outgoing messages per PU.
6. Incoming/outgoing bytes per PU.
7. Max lag stat, per-partition bar gauge, lag time series, checkpoint presence table.
8. `source_path × delivery_path` sample count/freshness table.
9. API polling vs Diagnostic Event Hub metrics available-set comparison.
10. Collector receiver/exporter failures.

Required query rules:

- do not use `or vector(0)` for required data;
- exclude the currently filling 1-minute bin from comparison panels;
- use absolute from/to timestamps during screenshot verification;
- Dedicated panels exist only when probe says `dedicated_enabled=true`, and `AvailableMemory` remains “available memory”.

- [ ] **Step 4: Implement verifier and browser capture**

Verifier posts every panel query to Grafana `/api/ds/query`, records HTTP status, frame row count, finite-value count, and newest timestamp. It exits 1 if any required panel fails.

Capture script:

- reads `GRAFANA_URL`, `GRAFANA_USER`, `GRAFANA_PASSWORD` from process environment;
- logs in through the UI;
- navigates to the dashboard with absolute `from`/`to` and kiosk mode;
- waits until every panel leaves loading state;
- expands viewport to the internal scroll container height;
- writes only the PNG path supplied as argv[2].

- [ ] **Step 5: Run unit tests**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_dashboard.py -q
node --check docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent/capture.mjs
```

- [ ] **Step 6: Commit**

```bash
git add docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/agent docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests/test_dashboard.py
git commit -m "feat(eventhubs): add agent dashboard workflow"
```

---

### Task 11: Actual Azure deployment and evidence collection

**Files:**
- Create locally only: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/evidence/` (gitignored)
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/run-scenario.sh`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/scripts/collect-evidence.sh`
- Modify: sample `.gitignore` or repository `.gitignore` only to ignore the sample `evidence/` and `.azure/` state.

**Interfaces:**
- Consumes all prior artifacts and the authenticated VM managed identity.
- Produces real query results, sanitized metrics summaries, dashboard JSON, and PNG; only sanitized publishable outputs move into `images/` and docs.

- [ ] **Step 1: Verify deployment prerequisites without mutation**

Run:

```bash
az account show --query '{id:id,name:name,user:user}' -o json
az provider show --namespace Microsoft.EventHub --query registrationState -o tsv
az provider show --namespace Microsoft.ContainerService --query registrationState -o tsv
az provider show --namespace Microsoft.Compute --query registrationState -o tsv
az provider show --namespace Microsoft.Insights --query registrationState -o tsv
az deployment sub validate --location koreacentral --template-file infra/main.bicep --parameters infra/main.parameters.json
```

Expected: correct subscription; providers Registered; validation succeeds. If authorization fails, report the exact denied action/scope and stop without claiming deployment.

- [ ] **Step 2: Deploy with azd**

```bash
azd auth login --managed-identity
azd env new eventhubs-otel-vm --subscription "$AZURE_SUBSCRIPTION_ID" --location koreacentral
azd up --no-prompt
```

Expected: Bicep provision and all hooks exit 0. No Dedicated cluster appears in the RG.

- [ ] **Step 3: Verify component health independently**

Run the exact checks emitted by the hook environment:

```bash
kubectl --kubeconfig .azure/eventhubs-otel-vm/kubeconfig get pods -n eventhubs-observability
kubectl --kubeconfig .azure/eventhubs-otel-vm/kubeconfig get vmsingle,vmagent,vmstaticscrape -n eventhubs-observability
curl --fail "http://${GATEWAY_PUBLIC_IP}:3000/api/health"
az vm run-command invoke --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$GATEWAY_VM_NAME" --command-id RunShellScript --scripts 'docker compose -f /opt/eventhubs-observability/compose.yaml ps --format json'
```

Expected: all pods Ready, VMSingle/VMAgent reconciled, Grafana database `ok`, Collector/Grafana/lag containers running.

- [ ] **Step 4: Run lag rise and recovery scenario**

`run-scenario.sh` must:

1. record baseline for 5 minutes;
2. set producer to 200 events/s and consumer delay to 50 ms for 10 minutes;
3. verify producer accepted count and lag increase on at least one partition;
4. scale producer to zero;
5. wait up to 15 minutes for maximum lag to decline by at least 80%;
6. record exact UTC boundaries and actual sent/processed counts.

Expected: non-synthetic lag increase and recovery evidence. If 80% recovery is not reached, report observed values and fail the scenario.

- [ ] **Step 5: Verify both receiver and both delivery paths**

`collect-evidence.sh` queries VictoriaMetrics for:

```promql
count by (source_path, delivery_path) ({__name__=~"azure_.*eventhub.*"})
max by (partition) (eventhubs_consumer_lag_messages)
count_over_time({source_path="azure_monitor_api",delivery_path="scrape"}[30m])
count_over_time({source_path="azure_monitor_api",delivery_path="remote_write"}[30m])
```

It also directly queries Azure Monitor metric definitions and metrics for the Premium namespace to prove source availability. Expected source/delivery combinations are present; diagnostic path is judged only for DS Export-supported metrics.

- [ ] **Step 6: Exercise fallback separately**

Stop only the `azuremonitorreceiver` API pipelines, enable Compose `fallback` profile, wait one collection interval, and verify `source_path=fallback_exporter`. Restore the primary receiver and stop fallback before final dashboard capture. Preserve failure/success boundaries in evidence.

- [ ] **Step 7: Build, verify, and capture Grafana**

```bash
python agent/probe.py --output evidence/probe.json
python agent/build_dashboard.py --probe evidence/probe.json --output evidence/dashboard.json
python agent/verify_panels.py evidence/dashboard.json --output evidence/panel-verification.json
node agent/capture.mjs "/d/eventhubs-otel-victoriametrics/event-hubs-observability" evidence/grafana-dashboard.png
```

Expected: every required query PASS, PNG contains complete dashboard, and visual inspection finds no secrets/identifiers, empty required panels, warning-color misuse, or incomplete-bin distortion.

- [ ] **Step 8: Commit only implementation fixes discovered by deployment**

Run all focused tests after each fix and commit by concern; never commit `evidence/`, live dashboard JSON, kubeconfig, `.azure/`, or secrets.

---

### Task 12: Public guide, lab, real screenshot, and cleanup proof

**Files:**
- Modify: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/index.md`
- Modify: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/lab/index.md`
- Create: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/images/architecture.png`
- Create from sanitized real evidence: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/images/grafana-dashboard.png`
- Modify: `docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/README.md`

**Interfaces:**
- Public guide leads with the real screenshot and conclusions.
- Lab contains exact deployment, verification, cost, failure, and cleanup steps.
- README is the runnable sample entry point.

- [ ] **Step 1: Draft front matter with `needs-review` during writing**

`index.md`:

```yaml
---
title: "Event Hubs metrics·consumer lag의 OpenTelemetry 수집과 VictoriaMetrics 대시보드"
description: Event Hubs Premium 지표와 checkpoint 기반 consumer lag를 OTel Collector Contrib로 수집해 VictoriaMetrics에 scrape·remote write하고 agent가 Grafana dashboard를 검증한 결과입니다.
document_type: guide
services: [azure-event-hubs, azure-monitor]
technologies: [open-telemetry, victoriametrics, grafana, kubernetes, python, bicep]
tags: [deploy, operate, evaluate]
status: needs-review
verification_status: needs-review
sources_checked_at: 2026-11-09
last_verified: 2026-11-09
review_cycle_days: 60
applies_to:
  - Azure Event Hubs Premium namespace
  - Existing Event Hubs Dedicated cluster의 문서 기반 비생성 profile
  - OpenTelemetry Collector Contrib 0.165.0
---
```

`lab/index.md` additionally declares:

```yaml
document_type: lab
topic_order: 1
status: needs-review
verification_status: needs-review
estimated_time: 2h
cost: paid
cleanup_required: true
```

- [ ] **Step 2: Write the guide around verified claims**

Required noun-phrase sections:

1. `Premium 실측 수집 경로와 최종 dashboard`
2. `Azure Monitor API와 Diagnostic Event Hub의 지원 범위`
3. `scrape·remote write의 데이터 형태와 도착 차이`
4. `checkpoint 기반 consumer lag 상승·회복`
5. `Premium PU와 Dedicated CU의 지표 의미 차이`
6. `agent dashboard의 probe·build·verify·look`
7. `공식 참고 자료`

The first section includes `images/grafana-dashboard.png` and the actual absolute UTC observation window. Dedicated text must state “문서 기반 profile, 이 실습에서 runtime 미검증”.

- [ ] **Step 3: Write the executable lab and README**

Lab sections cover prerequisites, exact roles, cost warning, `azd up`, component health, scenario, query verification, fallback, capture, errors, and `azd down --purge`. README lists every file responsibility and the one-command path.

- [ ] **Step 4: Sanitize and publish images**

Copy the real screenshot only after checking OCR/text and pixels for subscription IDs, resource IDs, IPs, hostnames, usernames, and secrets. Architecture image must match the final implementation, including both receivers and the non-created Dedicated profile.

- [ ] **Step 5: Prove cleanup**

```bash
azd down --purge --force --no-prompt
az group show --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP"
```

Expected: `azd down` exits 0 and `az group show` returns ResourceGroupNotFound. Also query `az eventhubs cluster list` for the RG and confirm no Dedicated cluster was ever created.

- [ ] **Step 6: Promote verification status only after evidence exists**

Change both public documents to `verification_status: verified` and their lifecycle statuses to `current`/`verified` only when deployment, queries, capture, and cleanup all passed. If any gate failed, preserve `needs-review` and document the blocker.

- [ ] **Step 7: Run complete verification suite**

```bash
/tmp/devguidesample-docs-venv/bin/python -m pytest docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab/tests -q
/tmp/devguidesample-docs-venv/bin/python -m pytest tests/docs -q
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_metadata.py
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_sources.py
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_links.py
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_public_safety.py
/tmp/devguidesample-docs-venv/bin/mkdocs build --strict
/tmp/devguidesample-docs-venv/bin/python scripts/docs/validate_search_index.py
git diff --check
```

Expected: every command exits 0. Remove generated `site/` and confirm it is not staged.

- [ ] **Step 8: Commit final public artifacts**

```bash
git add docs-taxonomy.yml docs/services/azure-event-hubs/opentelemetry-victoriametrics-monitoring
git commit -m "docs(eventhubs): publish OTel VictoriaMetrics monitoring lab"
```

---

## Plan Self-Review Results

- **Spec coverage:** Tasks 1–12 cover taxonomy/topic package, azd/Bicep, identities, both Collector receivers, scrape and remote write, fallback, lag generation/calculation, agent dashboard workflow, actual Premium deployment, Dedicated non-creation profile, real screenshot, cleanup, and repository validation.
- **Placeholders:** Commands use environment variables or fixed synthetic fixture values; no implementation placeholder remains in the plan.
- **Interface consistency:** `existingDedicatedClusterResourceId` maps to `EXISTING_DEDICATED_CLUSTER_RESOURCE_ID`; `source_path` and `delivery_path` labels are consistent from renderer through probe/dashboard; VMSingle private IP is consistently `10.42.2.20`; workload identities use the client IDs exported by Bicep.
- **Scope:** Dedicated runtime deployment is explicitly excluded. Premium runtime verification and Dedicated config-render contract are separate gates.
