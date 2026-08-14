"""Behaviour tests for the azd lifecycle hook scripts.

The hooks run inside `azd provision` / `azd down`, where the Azure CLI's
active subscription is whatever the operator last selected -- not
necessarily the subscription azd is deploying into. Every Azure CLI
operation therefore has to be pinned to AZURE_SUBSCRIPTION_ID, and the
`predown` hook has to survive a lab that never configured the Agent.
"""

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


SCRIPTS_DIR = Path(__file__).parents[1]
AZD_CONFIGURE = SCRIPTS_DIR / "azd-configure.sh"
AZD_POSTPROVISION = SCRIPTS_DIR / "azd-postprovision.sh"
CLEANUP_EXTERNAL = SCRIPTS_DIR / "cleanup-external.sh"
SUBSCRIPTION_PIN = '--subscription "${AZURE_SUBSCRIPTION_ID}"'
# The one deliberately unpinned call: it reads whichever account is active
# so the hook can report a mismatch.
ACTIVE_ACCOUNT_PROBE = "az account show --query id"


def _az_invocations(script_text):
    """Every `az ...` command in a script, with line continuations joined."""
    joined = re.sub(r"\\\n\s*", " ", script_text)
    commands = []
    for line in joined.splitlines():
        if line.strip().startswith("#"):
            continue
        for segment in re.split(r"\$\(|\|\||&&|\||;|`", line):
            stripped = re.sub(
                r"^(?:if\s+|until\s+|while\s+|then\s+|else\s+|do\s+|!\s*)+",
                "",
                segment.strip(),
            )
            if re.match(r"^az\s", stripped):
                commands.append(re.sub(r"\s+", " ", stripped).strip())
    return commands


def _write_az_stub(directory, log_path):
    """A fake `az` on PATH that records its arguments."""
    stub = directory / "az"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log_path}"\n'
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _run_cleanup_external(tmp_path, args, evidence=None, environment=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_path = tmp_path / "az-calls.log"
    _write_az_stub(bin_dir, log_path)

    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir(exist_ok=True)
    if evidence is not None:
        (evidence_root / "agent-setup.json").write_text(json.dumps(evidence))

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["SRE_LAB_EVIDENCE_ROOT"] = str(evidence_root)
    env.setdefault("AZURE_SUBSCRIPTION_ID", "11111111-2222-3333-4444-555555555555")
    if environment:
        env.update(environment)

    result = subprocess.run(
        [str(CLEANUP_EXTERNAL), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    calls = log_path.read_text() if log_path.exists() else ""
    return result, calls


def test_azd_configure_pins_every_azure_cli_call_to_the_target_subscription():
    for command in _az_invocations(AZD_CONFIGURE.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"azd-configure.sh runs an unpinned Azure CLI command: {command}"
        )


def test_azd_postprovision_pins_every_azure_cli_call_to_the_target_subscription():
    for command in _az_invocations(AZD_POSTPROVISION.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"azd-postprovision.sh runs an unpinned Azure CLI command: {command}"
        )


def test_azd_hooks_require_the_target_subscription_and_verify_the_active_account():
    for script in (AZD_CONFIGURE, AZD_POSTPROVISION):
        text = script.read_text()
        assert "AZURE_SUBSCRIPTION_ID:?" in text, (
            f"{script.name} must fail fast when azd did not provide a subscription"
        )
        assert ACTIVE_ACCOUNT_PROBE in text, (
            f"{script.name} must verify which subscription the Azure CLI is signed in to"
        )


def test_azd_postprovision_targets_only_current_azd_values():
    text = AZD_POSTPROVISION.read_text()

    assert "rg-sre-agent-event-lab-krc" not in text
    assert "95933ae5-0201-4a21-a1fc-8051a7437982" not in text
    assert "common.sh" not in text
    for value in (
        "AZURE_RESOURCE_GROUP:?",
        "AZURE_ACR_NAME:?",
        "AZURE_CONTAINER_APP_NAME:?",
        "AZURE_CONTAINER_APP_FQDN:?",
    ):
        assert value in text


def test_azd_postprovision_moves_ingress_to_the_app_port_and_records_the_image():
    """The provisioned placeholder listens on port 80; the lab image listens
    on 8000. postprovision must move ingress before verifying /healthz, and
    persist the built image so a later `azd provision` does not revert the
    Container App to the placeholder.
    """
    text = AZD_POSTPROVISION.read_text()

    assert "az containerapp ingress update" in text
    assert "--target-port" in text
    assert "8000" in text
    assert "azd env set SRE_CONTAINER_IMAGE" in text
    assert "/healthz" in text

    ingress_at = text.index("az containerapp ingress update")
    healthz_at = text.index("/healthz")
    assert ingress_at < healthz_at


def test_cleanup_external_exists_and_is_executable():
    assert CLEANUP_EXTERNAL.is_file()
    assert os.access(CLEANUP_EXTERNAL, os.X_OK)


def test_cleanup_external_never_deletes_broad_scopes():
    text = CLEANUP_EXTERNAL.read_text()

    assert "az group delete" not in text
    assert "az resource delete" not in text
    assert "--all" not in text
    assert "az role assignment delete" in text


def test_cleanup_external_succeeds_when_agent_evidence_is_absent(tmp_path):
    """`azd down` runs this hook with continueOnError: false, so a lab that
    never configured the SRE Agent must still tear down cleanly.
    """
    result, calls = _run_cleanup_external(tmp_path, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert calls == "", f"nothing external exists, but the hook called: {calls}"


def test_cleanup_external_deletes_only_recorded_subscription_assignments(tmp_path):
    subscription_id = "11111111-2222-3333-4444-555555555555"
    recorded = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        "/roleAssignments/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    uami_recorded = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        "/roleAssignments/ffffffff-1111-2222-3333-444444444444"
    )
    result, calls = _run_cleanup_external(
        tmp_path,
        ["--yes"],
        evidence={
            "monitoring_contributor_assignment_id": recorded,
            "agent_principal_id": "principal-a",
            "uami_monitoring_contributor_assignment_id": uami_recorded,
            "agent_user_assigned_principal_id": "principal-b",
        },
        environment={"AZURE_SUBSCRIPTION_ID": subscription_id},
    )

    assert result.returncode == 0, result.stderr
    assert f"role assignment delete --ids {recorded}" in calls
    assert f"role assignment delete --ids {uami_recorded}" in calls
    assert f"--subscription {subscription_id}" in calls
    assert "group delete" not in calls


def test_cleanup_external_refuses_assignments_outside_the_target_subscription(tmp_path):
    subscription_id = "11111111-2222-3333-4444-555555555555"
    foreign = (
        "/subscriptions/99999999-9999-9999-9999-999999999999/providers"
        "/Microsoft.Authorization/roleAssignments/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    result, calls = _run_cleanup_external(
        tmp_path,
        ["--yes"],
        evidence={
            "monitoring_contributor_assignment_id": foreign,
            "agent_principal_id": "principal-a",
            "uami_monitoring_contributor_assignment_id": foreign,
            "agent_user_assigned_principal_id": "principal-b",
        },
        environment={"AZURE_SUBSCRIPTION_ID": subscription_id},
    )

    assert result.returncode != 0
    assert "role assignment delete" not in calls


def test_cleanup_external_is_a_dry_run_without_yes(tmp_path):
    subscription_id = "11111111-2222-3333-4444-555555555555"
    recorded = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        "/roleAssignments/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    result, calls = _run_cleanup_external(
        tmp_path,
        [],
        evidence={
            "monitoring_contributor_assignment_id": recorded,
            "agent_principal_id": "principal-a",
            "uami_monitoring_contributor_assignment_id": recorded,
            "agent_user_assigned_principal_id": "principal-b",
        },
        environment={"AZURE_SUBSCRIPTION_ID": subscription_id},
    )

    assert result.returncode == 0, result.stderr
    assert "delete" not in calls


def test_cleanup_external_runs_under_bash_32(tmp_path):
    """macOS ships Bash 3.2, where `${ARRAY[@]}` on an empty array aborts
    under `set -u`.
    """
    bash_path = shutil.which("bash") or "/bin/bash"
    version = subprocess.run(
        [bash_path, "-c", "echo ${BASH_VERSINFO[0]}"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    result, _ = _run_cleanup_external(tmp_path, ["--yes"])

    assert result.returncode == 0, (
        f"cleanup-external.sh must run on bash {version}: {result.stderr}"
    )
    assert "unbound variable" not in result.stderr
