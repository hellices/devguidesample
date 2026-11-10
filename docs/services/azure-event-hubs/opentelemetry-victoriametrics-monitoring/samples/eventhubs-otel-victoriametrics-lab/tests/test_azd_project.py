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


def test_main_bicep_never_creates_a_dedicated_cluster():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()

    assert "targetScope = 'subscription'" in text
    assert "param existingDedicatedClusterResourceId string = ''" in text
    assert "Microsoft.EventHub/clusters@" not in text


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
    }

    assert _declared_outputs(text) == expected


def _declared_outputs(text):
    # Drop block and line comments first, so commented-out outputs never count as declared.
    code = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    code = re.sub(r"(?m)//.*$", "", code)
    return dict(re.findall(r"^output (\w+) string = (.+?)\s*$", code, re.MULTILINE))


def test_commented_outputs_are_not_declared():
    assert _declared_outputs("/*\noutput A string = x\n*/\n// output B string = y\noutput C string = z\n") == {"C": "z"}


def test_main_parameters_map_azd_environment_values():
    document = json.loads((LAB_ROOT / "infra" / "main.parameters.json").read_text())
    values = {name: entry["value"] for name, entry in document["parameters"].items()}

    # azd up validates required inputs before preprovision runs, so hook-filled values need
    # an empty default; main.bicep enforces minimum lengths instead.
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
    }

    main = (LAB_ROOT / "infra" / "main.bicep").read_text()
    for parameter in ("operatorEgressCidr", "grafanaAdminPassword", "gatewayAdminSshPublicKey"):
        assert f"param {parameter} string = ''" in main
