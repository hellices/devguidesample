"""Harness that runs `cleanup-external.sh` as a program.

The script is the `predown`/`postdown` hook of `azd down`, so it is
exercised the way azd runs it: as an executable, from a working directory
that is not the lab, with fake `az`/`azd` binaries on PATH and nothing but
PATH/HOME inherited from the developer's shell. That is the only way to
prove what reading the text cannot -- that it deletes exactly the recorded
role assignments it verified, and nothing else.

The fake `az` answers the three calls the script makes:

* `az account show --query id -o tsv` -- the active subscription, or the
  signed-out failure the real CLI produces.
* `az rest --method get --url .../roleAssignments/<name>?...` -- the stored
  assignment document, or, when no such assignment was staged, the failure
  the real CLI produces (recorded from azure-cli against a live
  subscription on 2026-08-14):

  ```
  rc=1, stderr='ERROR: Not Found({"error":{"code":"RoleAssignmentNotFound",
  "message":"The role assignment \'...\' is not found."}})'
  ```

  A document stored as `@error:<text>` fails with that text instead, which
  is how an unreadable assignment (no permission, throttling) is staged.
* `az role assignment delete ...` -- success, or a staged failure.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

from azd_fake import write_azd_stub, write_executable


SCRIPTS_DIR = Path(__file__).parents[1]
LAB_ROOT = Path(__file__).parents[2]
CLEANUP_EXTERNAL = SCRIPTS_DIR / "cleanup-external.sh"
BASH = shutil.which("bash") or "/bin/bash"

SUBSCRIPTION_ID = "11111111-2222-3333-4444-555555555555"
OTHER_SUBSCRIPTION_ID = "99999999-9999-9999-9999-999999999999"
MONITORING_CONTRIBUTOR_ROLE_ID = "749f88d5-cbae-40b8-bcfc-e573ddc772fa"
READER_ROLE_ID = "acdd72a7-3385-48ef-bd42-f606fba81ae7"

AGENT_PRINCIPAL_ID = "aaaaaaaa-0000-4000-8000-aaaaaaaaaaaa"
AGENT_UAMI_PRINCIPAL_ID = "bbbbbbbb-0000-4000-8000-bbbbbbbbbbbb"
AGENT_ASSIGNMENT_NAME = "cccccccc-1111-2222-3333-cccccccccccc"
UAMI_ASSIGNMENT_NAME = "dddddddd-1111-2222-3333-dddddddddddd"

# Not staged in the fake tenant: reads back as an assignment that no longer
# exists, which is the "someone already deleted it" case.
ABSENT_ASSIGNMENT_NAME = "eeeeeeee-1111-2222-3333-eeeeeeeeeeee"


def assignment_id(name, subscription_id=SUBSCRIPTION_ID):
    return (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        f"/roleAssignments/{name}"
    )


def assignment_document(
    principal_id,
    subscription_id=SUBSCRIPTION_ID,
    role_definition_id=None,
    scope=None,
):
    """The ARM document `az rest` returns for one role assignment."""
    if role_definition_id is None:
        role_definition_id = (
            f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
            f"/roleDefinitions/{MONITORING_CONTRIBUTOR_ROLE_ID}"
        )
    return {
        "properties": {
            "principalId": principal_id,
            "roleDefinitionId": role_definition_id,
            "scope": scope if scope is not None else f"/subscriptions/{subscription_id}",
        }
    }


def agent_setup(
    monitoring_assignment_id=None,
    agent_principal_id=AGENT_PRINCIPAL_ID,
    uami_assignment_id=None,
    uami_principal_id=AGENT_UAMI_PRINCIPAL_ID,
):
    """The evidence file `lab.sh acknowledge agent-setup` leaves behind."""
    if monitoring_assignment_id is None:
        monitoring_assignment_id = assignment_id(AGENT_ASSIGNMENT_NAME)
    if uami_assignment_id is None:
        uami_assignment_id = assignment_id(UAMI_ASSIGNMENT_NAME)
    return {
        "agent_endpoint": "https://sre-agent.example.com/api/incidents",
        "monitoring_contributor_assignment_id": monitoring_assignment_id,
        "agent_principal_id": agent_principal_id,
        "uami_monitoring_contributor_assignment_id": uami_assignment_id,
        "agent_user_assigned_principal_id": uami_principal_id,
    }


def staged_assignments():
    """The two assignments a healthy lab recorded, as the tenant holds them."""
    return {
        AGENT_ASSIGNMENT_NAME: assignment_document(AGENT_PRINCIPAL_ID),
        UAMI_ASSIGNMENT_NAME: assignment_document(AGENT_UAMI_PRINCIPAL_ID),
    }


def _az_stub_source(log_path, state_dir):
    return f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
state="{state_dir}"
case "${{1:-}} ${{2:-}}" in
  "account show")
    if [[ -f "${{state}}/signed_out" ]]; then
      echo "ERROR: Please run 'az login' to setup account." >&2
      exit 1
    fi
    cat "${{state}}/active_subscription"
    ;;
  "rest --method")
    url=""
    while [[ "$#" -gt 0 ]]; do
      if [[ "$1" == "--url" ]]; then
        url="$2"
        shift 2
        continue
      fi
      shift
    done
    name="${{url%%\\?*}}"
    name="${{name##*/}}"
    document="${{state}}/assignments/${{name}}.json"
    if [[ ! -f "${{document}}" ]]; then
      printf 'ERROR: Not Found({{"error":{{"code":"RoleAssignmentNotFound","message":"The role assignment %s is not found."}}}})\\n' "${{name}}" >&2
      exit 1
    fi
    if [[ "$(head -c 7 "${{document}}")" == "@error:" ]]; then
      tail -c +8 "${{document}}" >&2
      exit 1
    fi
    cat "${{document}}"
    ;;
  "role assignment")
    if [[ -f "${{state}}/delete_fails" ]]; then
      echo "ERROR: AuthorizationFailed" >&2
      exit 1
    fi
    ;;
esac
exit 0
"""


class CleanupRun:
    def __init__(self, result, az_log, azd_log):
        self.result = result
        self._az_log = az_log
        self._azd_log = azd_log

    @property
    def returncode(self):
        return self.result.returncode

    @property
    def stdout(self):
        return self.result.stdout

    @property
    def stderr(self):
        return self.result.stderr

    @property
    def az_calls(self):
        return self._az_log.read_text() if self._az_log.exists() else ""

    @property
    def azd_calls(self):
        return self._azd_log.read_text() if self._azd_log.exists() else ""


def run_cleanup(
    tmp_path,
    args=(),
    evidence=None,
    raw_evidence=None,
    assignments=None,
    subscription_id=SUBSCRIPTION_ID,
    active_subscription_id=None,
    azd_values=None,
    signed_out=False,
    delete_fails=False,
    env=None,
    script=CLEANUP_EXTERNAL,
):
    """Run `cleanup-external.sh` against a staged fake subscription."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    state_dir = tmp_path / "state"
    (state_dir / "assignments").mkdir(parents=True, exist_ok=True)
    (state_dir / "active_subscription").write_text(
        f"{active_subscription_id or subscription_id}\n"
    )
    if signed_out:
        (state_dir / "signed_out").write_text("1\n")
    if delete_fails:
        (state_dir / "delete_fails").write_text("1\n")
    for name, document in (
        staged_assignments() if assignments is None else assignments
    ).items():
        path = state_dir / "assignments" / f"{name}.json"
        path.write_text(
            document if isinstance(document, str) else json.dumps(document)
        )

    az_log = tmp_path / "az-calls.log"
    azd_log = tmp_path / "azd-calls.log"
    write_executable(bin_dir / "az", _az_stub_source(az_log, state_dir))
    write_azd_stub(
        bin_dir,
        {"AZURE_SUBSCRIPTION_ID": subscription_id}
        if azd_values is None
        else azd_values,
        "azd_1_29",
        azd_log,
    )

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    if raw_evidence is not None:
        (evidence_root / "agent-setup.json").write_text(raw_evidence)
    elif evidence is not None:
        (evidence_root / "agent-setup.json").write_text(json.dumps(evidence))

    workdir = tmp_path / "elsewhere"
    workdir.mkdir(parents=True, exist_ok=True)

    process_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "SRE_LAB_EVIDENCE_ROOT": str(evidence_root),
    }
    process_env.update(env or {})

    result = subprocess.run(
        [BASH, str(script), *args],
        capture_output=True,
        text=True,
        env=process_env,
        cwd=str(workdir),
    )
    return CleanupRun(result, az_log, azd_log)
