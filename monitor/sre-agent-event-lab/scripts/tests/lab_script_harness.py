"""Harness that runs the lab's shell entry points end to end.

The scenario/query/capture/cleanup scripts are the only place where
`common.sh`'s configuration contract, its `readonly` declarations and each
script's own variables meet, so they are exercised as *programs* here: a
throwaway copy of the lab (its own `azure.yaml`, `evidence/`, `assets/`)
plus fake `az`, `azd` and `python` executables on PATH. Every run starts
from a scratch working directory that is not the lab, which is how the
scripts are invoked in practice (from the repository root or anywhere else).
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from azd_fake import write_azd_stub, write_executable


SCRIPTS_DIR = Path(__file__).parents[1]
BASH = shutil.which("bash") or "/bin/bash"

SUBSCRIPTION_ID = "11111111-2222-3333-4444-555555555555"
RESOURCE_GROUP = "rg-sre-lab-exec"
ENV_NAME = "sre-lab-exec"
MONITORING_CONTRIBUTOR_ROLE_ID = "749f88d5-cbae-40b8-bcfc-e573ddc772fa"

AZD_VALUES = {
    "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION_ID,
    "AZURE_RESOURCE_GROUP": RESOURCE_GROUP,
    "AZURE_ENV_NAME": ENV_NAME,
    "AZURE_LOCATION": "koreacentral",
    "AZURE_CONTAINER_APP_NAME": "ca-sre-lab",
    "AZURE_CONTAINER_APP_FQDN": "ca-sre-lab.example.azurecontainerapps.io",
    "AZURE_STORAGE_CONTAINER_SCOPE": (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
        "/providers/Microsoft.Storage/storageAccounts/stsrelab/blobServices/default"
        "/containers/documents"
    ),
    "AZURE_BLOB_ROLE_ASSIGNMENT_NAME": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    "AZURE_WORKSPACE_ID": (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
        "/providers/Microsoft.OperationalInsights/workspaces/log-sre-lab"
    ),
    "AZURE_APP_INSIGHTS_NAME": "appi-sre-lab",
    "AZURE_TELEMETRY_SERVICE_NAME": "sre-lab-order-api",
    "containerAppPrincipalId": "8c8a4f0e-0000-4000-8000-2b1f9a0c1234",
    "workspaceCustomerId": "9d1a0b2c-3d4e-5f60-7182-93a4b5c6d7e8",
}

ALERTS_JSON = json.dumps(
    {
        "value": [
            {
                "id": (
                    f"/subscriptions/{SUBSCRIPTION_ID}/providers"
                    "/Microsoft.AlertsManagement/alerts/aaaa0000-1111-2222-3333-444455556666"
                ),
                "properties": {
                    "essentials": {
                        "alertRule": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
                            "/providers/microsoft.insights/metricAlerts/"
                            "alert-sre-lab-s1-http500"
                        ),
                        "startDateTime": "2026-08-14T00:05:00Z",
                        "monitorCondition": "Fired",
                    }
                },
            }
        ]
    }
)


def _az_stub_source(log_path, state_dir):
    """A fake `az` that answers every call the lab scripts make.

    Revision names advance on `containerapp update` so
    `wait_for_new_revision_ready` observes a genuinely new revision instead
    of spinning on its ten-minute timeout.
    """
    return f"""#!/usr/bin/env bash
printf '%s\\t%s\\n' "$*" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "{log_path}"
state="{state_dir}"
case "${{1:-}} ${{2:-}}" in
  "account show")
    printf '%s\\n' "{SUBSCRIPTION_ID}" ;;
  "group exists")
    printf 'true\\n' ;;
  "group show")
    if [[ "$*" == *"azd-env-name"* ]]; then
      printf '%s\\n' "{ENV_NAME}"
    else
      printf 'sre-agent-event-lab\\n'
    fi ;;
  "group delete")
    : ;;
  "containerapp show")
    printf 'rev-%s\\n' "$(cat "${{state}}/revision")" ;;
  "containerapp update")
    printf '%s\\n' "$(( $(cat "${{state}}/revision") + 1 ))" > "${{state}}/revision" ;;
  "containerapp revision")
    if [[ "$*" == *"healthState"* ]]; then
      printf 'Healthy\\n'
    elif [[ "$*" == *".active"* ]]; then
      printf 'true\\n'
    else
      printf '[]\\n'
    fi ;;
  "monitor log-analytics")
    # The `log-analytics` extension flattens the REST `{{"tables": [...]}}`
    # envelope into one JSON array of row objects, so "no rows" is `[]`.
    printf '[]\\n' ;;
  "monitor activity-log")
    printf '[]\\n' ;;
  "role assignment")
    if [[ "${{3:-}}" == "list" && "$*" != *"-o tsv"* ]]; then
      printf '[]\\n'
    fi ;;
  "rest --method")
    if [[ "$*" == *"/roleAssignments/"* ]]; then
      assignment_id="${{*##*--url }}"
      assignment_id="${{assignment_id%%\\?*}}"
      principal_id="${{assignment_id##*/}}"
      printf '{{"properties": {{"principalId": "%s", "roleDefinitionId": "/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleDefinitions/{MONITORING_CONTRIBUTOR_ROLE_ID}", "scope": "/subscriptions/{SUBSCRIPTION_ID}"}}}}\\n' \\
        "${{principal_id}}"
    else
      printf '%s\\n' '{ALERTS_JSON}'
    fi ;;
  *)
    : ;;
esac
exit 0
"""


def _lab_python_stub_source(log_path):
    """A fake `${LAB_ROOT}/app/.venv/bin/python` for capture-scenario.sh."""
    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
script="${{1:-}}"
shift || true
output_dir=""
asset_dir=""
normalized=""
case "${{script}}" in
  *capture_agent.py)
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --output-dir) output_dir="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    printf '%s\\n' '[{{"state": "detected"}}, {{"state": "diagnosing"}}, {{"state": "root-caused"}}, {{"state": "resolved"}}]' \\
      > "${{output_dir}}/normalized-timeline.json"
    ;;
  *render_capture.py)
    normalized="${{1:-}}"
    asset_dir="${{2:-}}"
    [[ -f "${{normalized}}" ]] || exit 1
    mkdir -p "${{asset_dir}}"
    printf 'GIF89a' > "${{asset_dir}}/investigation.gif"
    printf 'timeline\\n' > "${{asset_dir}}/timeline.mmd"
    ;;
esac
exit 0
"""


def make_lab(tmp_path, azd_values=None, missing_key_mode="azd_1_29"):
    """A throwaway copy of the lab plus fake CLIs; returns a run context."""
    lab = tmp_path / "lab"
    shutil.copytree(
        SCRIPTS_DIR,
        lab / "scripts",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    (lab / "azure.yaml").write_text("name: sre-agent-event-lab\n")
    (lab / "evidence").mkdir()

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "revision").write_text("1\n")

    az_log = tmp_path / "az-calls.log"
    azd_log = tmp_path / "azd-calls.log"
    python_log = tmp_path / "python-calls.log"
    lab_python_log = tmp_path / "lab-python-calls.log"

    write_executable(bin_dir / "az", _az_stub_source(az_log, state_dir))
    write_azd_stub(
        bin_dir,
        AZD_VALUES if azd_values is None else azd_values,
        missing_key_mode,
        azd_log,
    )
    write_executable(
        bin_dir / "python3",
        f'#!/usr/bin/env bash\nprintf \'%s\\n\' "$*" >> "{python_log}"\nexit 0\n',
    )

    venv_bin = lab / "app" / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    write_executable(venv_bin / "python", _lab_python_stub_source(lab_python_log))

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()

    return LabRun(lab, bin_dir, workdir, az_log, azd_log, lab_python_log)


class LabRun:
    def __init__(self, lab, bin_dir, workdir, az_log, azd_log, lab_python_log):
        self.lab = lab
        self.bin_dir = bin_dir
        self.workdir = workdir
        self.az_log = az_log
        self.azd_log = azd_log
        self.lab_python_log = lab_python_log

    def run(self, script_name, args=(), env=None):
        process_env = {
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "HOME": os.environ.get("HOME", str(self.lab)),
        }
        process_env.update(env or {})
        return subprocess.run(
            [BASH, str(self.lab / "scripts" / script_name), *args],
            capture_output=True,
            text=True,
            env=process_env,
            cwd=str(self.workdir),
        )

    def az_calls(self):
        return self.az_log.read_text() if self.az_log.exists() else ""

    def azd_calls(self):
        return self.azd_log.read_text() if self.azd_log.exists() else ""

    def write_agent_setup(self, principal_ids=("principal-one", "principal-two")):
        assignment_ids = [
            f"/subscriptions/{SUBSCRIPTION_ID}/providers"
            f"/Microsoft.Authorization/roleAssignments/{principal_id}"
            for principal_id in principal_ids
        ]
        setup = {
            "agent_endpoint": "https://sre-agent.example.com/api/incidents",
            "monitoring_contributor_assignment_id": assignment_ids[0],
            "agent_principal_id": principal_ids[0],
            "uami_monitoring_contributor_assignment_id": assignment_ids[1],
            "agent_user_assigned_principal_id": principal_ids[1],
        }
        path = self.lab / "evidence" / "agent-setup.json"
        path.write_text(json.dumps(setup))
        return path
