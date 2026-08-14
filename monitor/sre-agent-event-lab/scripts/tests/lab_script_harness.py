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
import sys
from pathlib import Path

from azd_fake import write_azd_stub, write_executable


SCRIPTS_DIR = Path(__file__).parents[1]
BASH = shutil.which("bash") or "/bin/bash"
# `lab_state.py`/`score.py` are part of the behaviour under test, so the fake
# interpreters below only fake the scripts that would reach Azure or render
# images (`loadgen.py`, `capture_agent.py`, `render_capture.py`) and hand
# every other script to the real interpreter running the suite.
REAL_PYTHON = sys.executable

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


def _alert(scenario, alert_uuid):
    """One entry of the Alerts Management list response.

    All three lab rules are listed, because `run-scenario.sh` picks the
    alert whose rule matches the scenario it just ran: a list containing
    only S1's alert would let an S2 run pass on S1's evidence.
    """
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/providers"
            f"/Microsoft.AlertsManagement/alerts/{alert_uuid}"
        ),
        "properties": {
            "essentials": {
                "alertRule": (
                    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}"
                    f"/providers/microsoft.insights/metricAlerts/{scenario}"
                ),
                "startDateTime": "2026-08-14T00:05:00Z",
                "monitorCondition": "Fired",
            }
        },
    }


ALERTS_JSON = json.dumps(
    {
        "value": [
            _alert("alert-sre-lab-s1-http500", "aaaa0000-1111-2222-3333-444455556666"),
            _alert("alert-sre-lab-s2-latency", "bbbb0000-1111-2222-3333-444455556666"),
            _alert("alert-sre-lab-s3-storage-rbac", "cccc0000-1111-2222-3333-444455556666"),
        ]
    }
)

# The normalized capture a healthy run produces: a real conclusion, which is
# the only outcome `lab_state.py` treats as a successful capture.
CONCLUSION_TIMELINE = json.dumps(
    [
        {"state": "alert-fired"},
        {"state": "thread-created"},
        {"state": "investigating"},
        {"state": "conclusion"},
    ]
)
# What the Agent leaves behind when it never concluded: the explicit marker
# `capture_model.normalize_capture` appends, never a success.
MISSING_CONCLUSION_TIMELINE = json.dumps(
    [
        {"state": "alert-fired"},
        {"state": "thread-created"},
        {"state": "investigating"},
        {"state": "conclusion-missing"},
    ]
)


def _az_stub_source(log_path, state_dir):
    """A fake `az` that answers every call the lab scripts make.

    Revision names advance on `containerapp update` so
    `wait_for_new_revision_ready` observes a genuinely new revision instead
    of spinning on its ten-minute timeout.

    The fired alert has a lifecycle: a single-alert read answers with the
    condition recorded in `${state}/alert_condition`, and a *recovering*
    call (clearing the failure mode/delay, or restoring the blob role)
    flips it to `Resolved` -- unless `${state}/alert_stays_fired` exists,
    which reproduces an alert that never closes. That is the only way to
    exercise the recovery gate honestly: `run-scenario.sh` must not record
    a recovery Azure Monitor never confirmed.

    Recovery itself can fail, which is the other half of that gate. Three
    markers reproduce the ways Azure refuses to restore the workload:
    `${state}/recovery_update_fails` (the `az containerapp update` that
    clears the injected setting exits non-zero),
    `${state}/recovery_revision_stalls` (the update is accepted but no new
    revision ever appears, so the wait times out) and
    `${state}/role_create_fails` (S3's blob role cannot be re-created).
    Only the *recovering* call is affected in each case: injection still
    has to succeed, otherwise there would be nothing to recover from.

    The mirror image is `${state}/injection_update_fails`: the *injecting*
    `az containerapp update` is rejected, which aborts a run before it can
    record any outcome of its own. Every marker is read from disk on each
    call, so a test can start a healthy run and break a later one.
    """
    return f"""#!/usr/bin/env bash
printf '%s\\t%s\\n' "$*" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "{log_path}"
state="{state_dir}"
resolve_alert() {{
  if [[ ! -f "${{state}}/alert_stays_fired" ]]; then
    printf 'Resolved\\n' > "${{state}}/alert_condition"
  fi
}}
next_revision() {{
  printf '%s\\n' "$(( $(cat "${{state}}/revision") + 1 ))" > "${{state}}/revision"
}}
# Real azure-cli global flags (`--only-show-errors`, etc.) can land before
# or between an az command's own arguments, shifting whatever the
# positional `$1 $2` dispatch below expects. `az rest` is the one call
# `cleanup-external.sh` adds such a flag to, so its dispatch key is derived
# from the presence of `--method` in "$@" rather than its position.
dispatch_key="${{1:-}} ${{2:-}}"
case " $* " in
  *" --method "*) dispatch_key="rest --method" ;;
esac
case "${{dispatch_key}}" in
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
    if [[ "$*" == *"FAILURE_MODE=none"* || "$*" == *"ORDER_DELAY_MS=0"* ]]; then
      if [[ -f "${{state}}/recovery_update_fails" ]]; then
        printf 'ERROR: (ContainerAppOperationError) the update was rejected.\\n' >&2
        exit 1
      fi
      if [[ ! -f "${{state}}/recovery_revision_stalls" ]]; then
        next_revision
      fi
      resolve_alert
    else
      if [[ -f "${{state}}/injection_update_fails" ]]; then
        printf 'ERROR: (ContainerAppOperationError) the update was rejected.\\n' >&2
        exit 1
      fi
      next_revision
    fi ;;
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
    if [[ "${{3:-}}" == "create" ]]; then
      if [[ -f "${{state}}/role_create_fails" ]]; then
        printf 'ERROR: (RoleAssignmentUpdateNotPermitted) the assignment was refused.\\n' >&2
        exit 1
      fi
      resolve_alert
    elif [[ "${{3:-}}" == "list" && "$*" != *"-o tsv"* ]]; then
      printf '[]\\n'
    fi ;;
  "rest --method")
    if [[ "$*" == *"/roleAssignments/"* ]]; then
      assignment_id="${{*##*--url }}"
      assignment_id="${{assignment_id%%\\?*}}"
      principal_id="${{assignment_id##*/}}"
      printf '{{"properties": {{"principalId": "%s", "roleDefinitionId": "/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.Authorization/roleDefinitions/{MONITORING_CONTRIBUTOR_ROLE_ID}", "scope": "/subscriptions/{SUBSCRIPTION_ID}"}}}}\\n' \\
        "${{principal_id}}"
    elif [[ "$*" == *"monitorCondition=Fired"* ]]; then
      if [[ -f "${{state}}/alert_never_fires" ]]; then
        printf '{{"value": []}}\\n'
      else
        printf '%s\\n' '{ALERTS_JSON}'
      fi
    elif [[ "$*" == *"/Microsoft.AlertsManagement/alerts/"* ]]; then
      printf '{{"properties": {{"essentials": {{"monitorCondition": "%s", "startDateTime": "2026-08-14T00:05:00Z"}}}}}}\\n' \\
        "$(cat "${{state}}/alert_condition")"
    else
      printf '%s\\n' '{ALERTS_JSON}'
    fi ;;
  *)
    : ;;
esac
exit 0
"""


def _lab_python_stub_source(log_path, capture_timeline, pillow_importable=True):
    """A fake `${LAB_ROOT}/app/.venv/bin/python`.

    Only the two scripts that would reach the SRE Agent data plane or write
    images are faked; every other script (notably `lab_state.py` and
    `score.py`, which are the behaviour under test) runs under the real
    interpreter.

    Also answers the `-c "import PIL"` probe `capture-scenario.sh` and
    doctor's "Python environment" check use to verify Pillow is importable,
    per `pillow_importable` -- explicitly, rather than delegating to
    whichever real interpreter happens to run the test suite, so this fake
    behaves the same regardless of that interpreter's own installed
    packages.
    """
    pil_exit = 0 if pillow_importable else 1
    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
if [[ "${{1:-}}" == "-c" && "${{2:-}}" == *PIL* ]]; then
  exit {pil_exit}
fi
case "${{1:-}}" in
  *capture_agent.py)
    shift
    output_dir=""
    while [[ "$#" -gt 0 ]]; do
      case "$1" in
        --output-dir) output_dir="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    printf '%s\\n' '{capture_timeline}' > "${{output_dir}}/normalized-timeline.json"
    ;;
  *render_capture.py)
    shift
    normalized="${{1:-}}"
    asset_dir="${{2:-}}"
    [[ -f "${{normalized}}" ]] || exit 1
    mkdir -p "${{asset_dir}}"
    printf 'GIF89a' > "${{asset_dir}}/investigation.gif"
    printf 'timeline\\n' > "${{asset_dir}}/timeline.mmd"
    ;;
  *loadgen.py)
    ;;
  *)
    exec "{REAL_PYTHON}" "$@"
    ;;
esac
exit 0
"""


def _python3_stub_source(log_path):
    """A fake `python3`: `loadgen.py` is faked, everything else is real."""
    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
case "${{1:-}}" in
  *loadgen.py) exit 0 ;;
  *) exec "{REAL_PYTHON}" "$@" ;;
esac
"""


def make_lab(
    tmp_path,
    azd_values=None,
    missing_key_mode="azd_1_29",
    alert_resolves=True,
    alert_fires=True,
    capture_timeline=CONCLUSION_TIMELINE,
    venv_present=True,
    pillow_importable=True,
    recovery_update_fails=False,
    recovery_revision_stalls=False,
    role_create_fails=False,
    injection_update_fails=False,
):
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
    (state_dir / "alert_condition").write_text("Fired\n")
    if not alert_resolves:
        (state_dir / "alert_stays_fired").write_text("1\n")
    if not alert_fires:
        (state_dir / "alert_never_fires").write_text("1\n")
    if recovery_update_fails:
        (state_dir / "recovery_update_fails").write_text("1\n")
    if recovery_revision_stalls:
        (state_dir / "recovery_revision_stalls").write_text("1\n")
    if role_create_fails:
        (state_dir / "role_create_fails").write_text("1\n")
    if injection_update_fails:
        (state_dir / "injection_update_fails").write_text("1\n")

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
    write_executable(bin_dir / "python3", _python3_stub_source(python_log))

    venv_bin = lab / "app" / ".venv" / "bin"
    if venv_present:
        venv_bin.mkdir(parents=True)
        write_executable(
            venv_bin / "python",
            _lab_python_stub_source(lab_python_log, capture_timeline, pillow_importable),
        )

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()

    return LabRun(lab, bin_dir, workdir, az_log, azd_log, lab_python_log, state_dir)


class LabRun:
    def __init__(self, lab, bin_dir, workdir, az_log, azd_log, lab_python_log, state_dir):
        self.lab = lab
        self.bin_dir = bin_dir
        self.workdir = workdir
        self.az_log = az_log
        self.azd_log = azd_log
        self.lab_python_log = lab_python_log
        self.state_dir = state_dir

    def break_injection(self):
        """Make the *next* injecting `az containerapp update` fail.

        Set after a healthy run so one lab can execute a successful
        scenario and then a re-run that dies before recording anything.
        """
        (self.state_dir / "injection_update_fails").write_text("1\n")

    def break_recovery(self):
        """Make the *next* recovering `az containerapp update` fail."""
        (self.state_dir / "recovery_update_fails").write_text("1\n")

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

    @property
    def state_path(self):
        return self.lab / "evidence" / "state.json"

    def seed_state(
        self,
        stages=("baseline_passed", "agent_setup_acknowledged"),
        scenarios=None,
        environment=ENV_NAME,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
    ):
        """Pre-record the ordered state a test starts from.

        Written directly rather than through `lab_state.py` so a test states
        the precondition it wants (including impossible ones, e.g. a state
        file bound to another environment) without depending on the code
        under test to produce it.
        """
        state = {
            "environment": environment,
            "subscription_id": subscription_id,
            "resource_group": resource_group,
            "stages": {stage: {"at": "2026-08-14T00:00:00Z"} for stage in stages},
            "scenarios": scenarios or {},
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
        return self.state_path

    def state(self):
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text())

    def scenario_state(self, scenario):
        return self.state().get("scenarios", {}).get(scenario, {})
