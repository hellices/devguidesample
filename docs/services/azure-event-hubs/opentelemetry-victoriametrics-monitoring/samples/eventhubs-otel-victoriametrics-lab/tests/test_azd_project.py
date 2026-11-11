import json
from pathlib import Path
import re

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
        "description": (
            "Deploys and verifies Event Hubs metrics, consumer lag, dual "
            "VictoriaMetrics ingestion paths, and an agent-built Grafana dashboard."
        ),
        "kind": "runnable",
        "used_by": ["index", "lab"],
    }
    # used_by is a claim about the pages; each page must actually point at this sample.
    sample_url = ("https://github.com/hellices/devguidesample/tree/main/docs/services/azure-event-hubs/"
                  "opentelemetry-victoriametrics-monitoring/samples/eventhubs-otel-victoriametrics-lab")
    topic = LAB_ROOT.parents[1]
    for page in (topic / "index.md", topic / "lab" / "index.md"):
        assert f"]({sample_url})" in page.read_text(), page


def test_azure_yaml_declares_lifecycle_hooks_without_local_docker_service():
    project = yaml.safe_load((LAB_ROOT / "azure.yaml").read_text())

    assert "services" not in project
    expected = {
        "preprovision": "./scripts/azd-configure.sh",
        "postprovision": "./scripts/azd-postprovision.sh",
        "postdeploy": "./scripts/azd-deploy.sh",
        "predown": "./scripts/cleanup-external.sh --yes",
        "postdown": "./scripts/verify-cleanup.sh",
    }
    assert {hook: spec["run"] for hook, spec in project["hooks"].items()} == expected
    assert all(spec["continueOnError"] is False for spec in project["hooks"].values())


def _bicep_code(text):
    """Bicep source without block or line comments, so commented-out declarations never count."""
    return re.sub(r"(?m)//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL))


def test_only_the_messaging_module_creates_a_dedicated_cluster():
    text = _bicep_code((LAB_ROOT / "infra" / "main.bicep").read_text())

    assert "targetScope = 'subscription'" in text
    assert re.search(r"(?m)^param existingDedicatedClusterResourceId string = ''$", text)
    assert re.search(r"(?m)^param eventHubsSku string = 'Dedicated'$", text)
    # main.bicep deploys local modules, so every Bicep file is checked, case-insensitively.
    # An `existing` reference only reads a cluster; any other declaration creates one.
    declaration = re.compile(r"'microsoft\.eventhub/clusters@[^']*'\s*(existing\b)?")
    creators = [path.name for path in (LAB_ROOT / "infra").rglob("*.bicep")
                if any(not existing for existing in declaration.findall(_bicep_code(path.read_text()).lower()))]
    assert creators == ["messaging.bicep"]


def test_a_premium_lab_grants_the_gateway_read_access_to_an_existing_cluster():
    text = _bicep_code((LAB_ROOT / "infra" / "main.bicep").read_text())
    module = _bicep_code((LAB_ROOT / "infra" / "modules" / "cluster-reader.bicep").read_text())

    assert "var observeExistingCluster = eventHubsSku != 'Dedicated' && !empty(existingDedicatedClusterResourceId)" in text
    assert re.search(r"module existingClusterReader 'modules/cluster-reader\.bicep' = if \(observeExistingCluster\)", text)
    assert "scope: resourceGroup(existingClusterIdParts[2], existingClusterIdParts[4])" in text
    assert "gatewayPrincipalId: foundation.outputs.gatewayPrincipalId" in text
    assert "'Microsoft.EventHub/clusters@2024-01-01' existing" in module
    assert "var monitoringReaderRoleDefinitionId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'" in module
    # Scope, role and principal must belong to the same (only) role assignment block.
    [block] = re.findall(r"(?ms)^resource \w+ 'Microsoft\.Authorization/roleAssignments@[^']+' = \{.*?^\}", module)
    assert re.search(r"^\s*scope: cluster\s*$", block, re.MULTILINE)
    assert re.search(r"^\s*principalId: gatewayPrincipalId\s*$", block, re.MULTILINE)
    assert "roleDefinitions', monitoringReaderRoleDefinitionId)" in block


def test_main_bicep_exports_hook_contract():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()
    # Each hook input must come from the right resource, not merely be declared.
    expected = {
        "AZURE_RESOURCE_GROUP": "rg.name",
        "AKS_CLUSTER_NAME": "compute.outputs.aksName",
        "ACR_NAME": "foundation.outputs.acrName",
        "ACR_LOGIN_SERVER": "foundation.outputs.acrLoginServer",
        "GATEWAY_VM_NAME": "compute.outputs.gatewayVmName",
        "GATEWAY_PUBLIC_IP": "compute.outputs.gatewayPublicIp",
        "GATEWAY_PRIVATE_IP": "compute.outputs.gatewayPrivateIp",
        "GATEWAY_CLIENT_ID": "foundation.outputs.gatewayClientId",
        "EVENTHUBS_LOCATION": "messagingLocation",
        "PREMIUM_NAMESPACE_NAME": "messaging.outputs.premiumNamespaceName",
        "WORKLOAD_EVENTHUB_NAME": "messaging.outputs.workloadEventHubName",
        "WORKLOAD_CONSUMER_GROUP": "messaging.outputs.workloadConsumerGroup",
        "TELEMETRY_NAMESPACE_NAME": "messaging.outputs.telemetryNamespaceName",
        "TELEMETRY_EVENTHUB_NAME": "messaging.outputs.telemetryEventHubName",
        "CHECKPOINT_ACCOUNT_NAME": "foundation.outputs.storageName",
        "KEY_VAULT_NAME": "foundation.outputs.keyVaultName",
        "PRODUCER_CLIENT_ID": "foundation.outputs.producerClientId",
        "CONSUMER_CLIENT_ID": "foundation.outputs.consumerClientId",
        "AKS_OIDC_ISSUER": "compute.outputs.aksOidcIssuer",
        "CHECKPOINT_ACCOUNT_URL": "foundation.outputs.storageBlobEndpoint",
        "VMSINGLE_PRIVATE_IP": "foundation.outputs.vmSinglePrivateIp",
        "EXISTING_DEDICATED_CLUSTER_RESOURCE_ID": "existingDedicatedClusterResourceId",
        "EXISTING_CLUSTER_READER_ASSIGNMENT_ID": "existingClusterReader.?outputs.roleAssignmentId ?? ''",
        "EVENTHUBS_SKU": "eventHubsSku",
        "DEDICATED_CLUSTER_RESOURCE_ID": "messaging.outputs.dedicatedClusterId",
        "TELEMETRY_LOGS_EVENTHUB_NAME": "messaging.outputs.telemetryLogsEventHubName",
        "MANAGED_GRAFANA_NAME": "grafana.?outputs.name ?? ''",
        "MANAGED_GRAFANA_ENDPOINT": "grafana.?outputs.endpoint ?? ''",
    }

    assert _declared_outputs(text) == expected


def _declared_outputs(text):
    return dict(re.findall(r"^output (\w+) string = (.+?)\s*$", _bicep_code(text), re.MULTILINE))


def test_commented_outputs_are_not_declared():
    assert _declared_outputs("/*\noutput A string = x\n*/\n// output B string = y\noutput C string = z\n") == {"C": "z"}


def test_main_parameters_map_azd_environment_values():
    document = json.loads((LAB_ROOT / "infra" / "main.parameters.json").read_text())
    values = {name: entry["value"] for name, entry in document["parameters"].items()}

    # azd up validates required inputs before preprovision runs, so hook-filled values need
    # an empty default. Bicep refuses @minLength with that default (BCP333) and ARM preflight
    # accepts '', so azd-configure.sh is the guard (see test_preprovision_* in test_hooks.py).
    assert values == {
        "environmentName": "${AZURE_ENV_NAME}",
        "location": "${AZURE_LOCATION}",
        "eventHubsLocation": "${EVENTHUBS_LOCATION=}",
        "operatorEgressCidr": "${OPERATOR_EGRESS_CIDR=}",
        "grafanaAdminPassword": "${GRAFANA_ADMIN_PASSWORD=}",
        "gatewayAdminSshPublicKey": "${GATEWAY_ADMIN_SSH_PUBLIC_KEY=}",
        "deployerPrincipalId": "${AZURE_PRINCIPAL_ID=}",
        "deployerPrincipalType": "${AZURE_PRINCIPAL_TYPE=User}",
        "existingDedicatedClusterResourceId": "${EXISTING_DEDICATED_CLUSTER_RESOURCE_ID=}",
        "eventHubsSku": "${EVENTHUBS_SKU=Dedicated}",
        "eventHubsLogs": "${EVENTHUBS_LOGS=Enabled}",
        "eventHubsDiagnosticMetrics": "${EVENTHUBS_DIAGNOSTIC_METRICS=Disabled}",
        "managedGrafana": "${MANAGED_GRAFANA=Disabled}",
    }

    main = (LAB_ROOT / "infra" / "main.bicep").read_text()
    for parameter in ("operatorEgressCidr", "grafanaAdminPassword", "gatewayAdminSshPublicKey"):
        assert re.search(rf"(?m)^param {parameter} string = ''$", _bicep_code(main)), parameter


def test_managed_grafana_is_optional_standard_and_reachable_only_privately():
    main = _bicep_code((LAB_ROOT / "infra" / "main.bicep").read_text())
    module = _bicep_code((LAB_ROOT / "infra" / "modules" / "grafana.bicep").read_text())
    foundation = _bicep_code((LAB_ROOT / "infra" / "modules" / "foundation.bicep").read_text())

    assert "param managedGrafana string = 'Disabled'" in main
    assert "module grafana 'modules/grafana.bicep' = if (managedGrafana == 'Enabled')" in main
    # Managed private endpoints need Standard; API keys stay off.
    assert re.search(r"sku: \{\s*name: 'Standard'\s*\}", module)
    assert "apiKey: 'Disabled'" in module
    # Creating the workspace already grants the caller Grafana Admin; a Bicep duplicate fails, so the
    # hook grants it only when missing.
    assert "roleAssignments" not in module
    hook = (LAB_ROOT / "scripts" / "managed-grafana.sh").read_text()
    # The grant is the create call inside the "not assigned yet" branch, and there is no other grant.
    branch = re.search(r'if \[\[ "\$assigned" == "0" \]\]; then\n(.*?)\nfi\n', hook, re.DOTALL)
    assert branch, "missing Grafana Admin branch"
    assert re.search(r'az role assignment create .*--assignee-object-id "\$DEPLOYER_ID".*--role "Grafana Admin" '
                     r'--scope "\$GRAFANA_ID"', branch.group(1).replace("\\\n", " "), re.DOTALL)
    assert hook.count("az role assignment create") == 1
    # The Private Link Service on the AKS internal load balancer needs this subnet policy off.
    assert "privateLinkServiceNetworkPolicies: 'Disabled'" in foundation
    pls = (LAB_ROOT / "k8s" / "vmsingle-pls.yaml").read_text()
    assert 'service.beta.kubernetes.io/azure-load-balancer-internal: "true"' in pls
    assert 'service.beta.kubernetes.io/azure-pls-create: "true"' in pls
