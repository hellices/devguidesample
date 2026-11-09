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
    text = (LAB_ROOT / "azure.yaml").read_text()

    assert "services:" not in text
    for hook, script in {
        "preprovision": "./scripts/azd-configure.sh",
        "postprovision": "./scripts/azd-postprovision.sh",
        "postdeploy": "./scripts/azd-deploy.sh",
        "predown": "./scripts/cleanup-external.sh --yes",
    }.items():
        assert re.search(
            rf"^  {hook}:.*?^    run: {re.escape(script)}$",
            text,
            re.MULTILINE | re.DOTALL,
        )


def test_main_bicep_never_creates_a_dedicated_cluster():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()

    assert "targetScope = 'subscription'" in text
    assert "param existingDedicatedClusterResourceId string = ''" in text
    assert "Microsoft.EventHub/clusters@" not in text


def test_main_bicep_exports_hook_contract():
    text = (LAB_ROOT / "infra" / "main.bicep").read_text()
    names = (
        "AZURE_RESOURCE_GROUP",
        "AKS_CLUSTER_NAME",
        "ACR_NAME",
        "ACR_LOGIN_SERVER",
        "GATEWAY_VM_NAME",
        "GATEWAY_PUBLIC_IP",
        "GATEWAY_PRIVATE_IP",
        "GATEWAY_CLIENT_ID",
        "PREMIUM_NAMESPACE_NAME",
        "WORKLOAD_EVENTHUB_NAME",
        "WORKLOAD_CONSUMER_GROUP",
        "TELEMETRY_NAMESPACE_NAME",
        "TELEMETRY_EVENTHUB_NAME",
        "CHECKPOINT_ACCOUNT_NAME",
        "KEY_VAULT_NAME",
        "PRODUCER_CLIENT_ID",
        "CONSUMER_CLIENT_ID",
        "VMSINGLE_PRIVATE_IP",
    )

    for name in names:
        assert f"output {name} " in text


def test_main_parameters_map_azd_environment_values():
    parameters = (LAB_ROOT / "infra" / "main.parameters.json").read_text()

    for variable in (
        "AZURE_ENV_NAME",
        "AZURE_LOCATION",
        "OPERATOR_EGRESS_CIDR",
        "GRAFANA_ADMIN_PASSWORD",
        "GATEWAY_ADMIN_SSH_PUBLIC_KEY",
        "EXISTING_DEDICATED_CLUSTER_RESOURCE_ID=",
    ):
        assert "${" + variable + "}" in parameters
