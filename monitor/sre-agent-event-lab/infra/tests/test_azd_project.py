from pathlib import Path


LAB_ROOT = Path(__file__).parents[2]


def test_azure_yaml_runs_remote_build_after_provision():
    config = (LAB_ROOT / "azure.yaml").read_text()
    assert "postprovision" in config
    assert "./scripts/azd-postprovision.sh" in config
    assert "predown" in config
    assert "./scripts/cleanup-external.sh" in config


def test_subscription_template_uses_azd_environment_parameters():
    template = (LAB_ROOT / "infra" / "main.bicep").read_text()
    assert "targetScope = 'subscription'" in template
    assert "param environmentName string" in template
    assert "param resourceGroupName string = 'rg-${environmentName}'" in template
    assert "95933ae5-0201-4a21-a1fc-8051a7437982" not in template
    assert "2026-08-13" not in template


def test_azd_outputs_have_stable_names():
    template = (LAB_ROOT / "infra" / "main.bicep").read_text()
    for name in (
        "AZURE_RESOURCE_GROUP",
        "AZURE_ACR_NAME",
        "AZURE_CONTAINER_APP_NAME",
        "AZURE_CONTAINER_APP_FQDN",
        "AZURE_WORKSPACE_ID",
        "AZURE_APP_INSIGHTS_NAME",
        "AZURE_STORAGE_CONTAINER_SCOPE",
        "AZURE_BLOB_ROLE_ASSIGNMENT_NAME",
        "AZURE_TELEMETRY_SERVICE_NAME",
    ):
        assert f"output {name} " in template
