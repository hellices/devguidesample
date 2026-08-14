import json
import os
import re
from pathlib import Path


LAB_ROOT = Path(__file__).parents[2]
PLACEHOLDER_IMAGE = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"


def _hook_commands():
    """Every `run:` command declared in azure.yaml, hook name unknown."""
    config = (LAB_ROOT / "azure.yaml").read_text()
    return re.findall(r"^\s*run:\s*(\S+)", config, flags=re.MULTILINE)


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


def test_every_azure_yaml_hook_references_an_existing_executable_script():
    """azd aborts the whole command when a hook script cannot be executed.

    `predown` pointed at scripts/cleanup-external.sh, which did not exist,
    so `azd down` failed before it could delete anything.
    """
    commands = _hook_commands()

    assert commands, "azure.yaml must declare at least one hook command"
    for command in commands:
        script = LAB_ROOT / command
        assert script.is_file(), f"azure.yaml hook references a missing script: {command}"
        assert os.access(script, os.X_OK), (
            f"azure.yaml hook script is not executable: {command}"
        )


def test_workload_binds_ingress_port_and_probes_to_parameters():
    """The initial provision runs the public placeholder image, which
    listens on port 80 and serves no /healthz. Hardcoding targetPort 8000
    with /healthz probes makes that first Bicep deployment fail, so both
    must be parameterized and always agree with each other.
    """
    template = (LAB_ROOT / "infra" / "workload.bicep").read_text()

    assert "param containerTargetPort int" in template
    assert "param enableHealthProbes bool" in template
    assert "targetPort: containerTargetPort" in template
    assert "port: containerTargetPort" in template
    assert "enableHealthProbes ?" in template
    assert "targetPort: 8000" not in template
    assert "port: 8000" not in template


def test_lab_bicep_forwards_container_port_and_probe_switches():
    template = (LAB_ROOT / "infra" / "lab.bicep").read_text()

    assert "param containerTargetPort int" in template
    assert "param enableHealthProbes bool" in template
    assert "containerTargetPort: containerTargetPort" in template
    assert "enableHealthProbes: enableHealthProbes" in template


def test_main_bicep_keeps_placeholder_port_and_probes_consistent():
    template = (LAB_ROOT / "infra" / "main.bicep").read_text()

    assert PLACEHOLDER_IMAGE in template
    assert re.search(r"containerTargetPort:\s*\S+\s*\?\s*80\s*:\s*8000", template), (
        "main.bicep must expose the placeholder on port 80 and the lab image on 8000"
    )
    assert re.search(r"enableHealthProbes:\s*!\S+", template), (
        "main.bicep must disable /healthz probes while the placeholder image runs"
    )


def test_main_bicep_restores_outputs_consumed_by_lab_scripts():
    template = (LAB_ROOT / "infra" / "main.bicep").read_text()

    for name in (
        "containerAppName",
        "containerAppFqdn",
        "containerAppPrincipalId",
        "workspaceCustomerId",
        "acrLoginServer",
        "appInsightsResourceId",
        "alertRuleNames",
        "storageContainerScope",
        "blobRoleAssignmentName",
        "telemetryServiceName",
    ):
        assert f"output {name} " in template, (
            f"scripts/common.sh consumers still read the {name} deployment output"
        )


def test_main_parameters_map_action_group_and_deployed_image():
    parameters = json.loads((LAB_ROOT / "infra" / "main.parameters.json").read_text())["parameters"]

    assert parameters["actionGroupResourceId"]["value"] == "${ACTION_GROUP_RESOURCE_ID}"
    assert parameters["containerImage"]["value"] == "${SRE_CONTAINER_IMAGE}"


def test_hardcoded_lab_bicepparam_is_deleted():
    """lab.bicepparam pinned a dead suffix (95933ae5) and an expiry date;
    azd owns those values now, so the file must not linger.
    """
    assert not (LAB_ROOT / "infra" / "lab.bicepparam").exists()
    assert not (LAB_ROOT / "infra" / "main.bicepparam").exists()


def test_lab_ignores_local_azd_environment_directory():
    ignore_file = LAB_ROOT / ".gitignore"

    assert ignore_file.is_file(), "the lab must ignore its own .azure/ azd state directory"
    assert ".azure/" in ignore_file.read_text()


def test_azd_onboarding_docs_and_config_do_not_hardcode_a_subscription_id():
    """README's `azd env new` command hardcoded the one subscription ID used
    for the original real validation run. Anyone following the README for a
    *different* subscription would silently target someone else's
    subscription, so no file that documents or drives the current `azd`
    onboarding path may hardcode it.

    `scripts/common.sh` (the pre-azd legacy flow, still intentionally pinned
    per `test_common_does_not_expose_personal_subscription_display_name`) and
    `validation-results.md` (the historical record of that specific real run)
    are deliberately out of scope here.
    """
    fixed_subscription_id = "95933ae5-0201-4a21-a1fc-8051a7437982"
    onboarding_paths = [
        LAB_ROOT / "README.md",
        LAB_ROOT / "azure.yaml",
        LAB_ROOT / "infra" / "main.bicep",
        LAB_ROOT / "infra" / "lab.bicep",
        LAB_ROOT / "infra" / "workload.bicep",
        LAB_ROOT / "infra" / "main.parameters.json",
        LAB_ROOT / "scripts" / "azd-configure.sh",
        LAB_ROOT / "scripts" / "azd-postprovision.sh",
        LAB_ROOT / "scripts" / "cleanup-external.sh",
        LAB_ROOT / "scripts" / "deploy.sh",
    ]

    offenders = [
        str(path.relative_to(LAB_ROOT))
        for path in onboarding_paths
        if path.is_file() and fixed_subscription_id in path.read_text()
    ]

    assert offenders == [], (
        "azd onboarding docs/config still hardcode the original validation "
        f"subscription ID: {offenders}"
    )


def test_main_bicep_tolerates_an_empty_resource_group_parameter():
    """azd substitutes an unset ${AZURE_RESOURCE_GROUP} with "" and, because
    the Bicep default is a non-empty expression, passes that empty string
    through (armParameterFileValue in azure-dev's bicep_provider.go). The
    template must fall back on its own instead of creating a resource group
    with an empty name.
    """
    template = (LAB_ROOT / "infra" / "main.bicep").read_text()

    assert "param resourceGroupName string = 'rg-${environmentName}'" in template
    assert re.search(
        r"var effectiveResourceGroupName = empty\(resourceGroupName\)", template
    )
    assert "name: effectiveResourceGroupName" in template
