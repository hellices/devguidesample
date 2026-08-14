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


def _write_azd_stub(directory, log_path):
    """A fake `azd` on PATH that records its arguments.

    Without this, `command -v azd` on a developer machine finds the real
    `azd` binary, which would then try to mutate an environment that does
    not exist in the test's tmp_path and fail for unrelated reasons.

    Uses `%q` (not `$*`) so an empty-string argument -- e.g. clearing an
    azd environment value with `azd env set KEY ""` -- is visible in the
    log as `''` instead of silently vanishing.
    """
    stub = directory / "azd"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%q " "$@" >> "{log_path}"\n'
        f'printf "\\n" >> "{log_path}"\n'
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _write_login_failing_az_stub(directory, log_path):
    """A fake `az` that fails only the login-check probe, like a signed-out
    Azure CLI, while logging every invocation it receives.
    """
    stub = directory / "az"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log_path}"\n'
        'if [[ "$1 $2" == "account show" && "$*" == *"--query id"* ]]; then\n'
        "  echo \"ERROR: Please run 'az login' to setup account.\" >&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _run_cleanup_external(tmp_path, args, evidence=None, environment=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_path = tmp_path / "az-calls.log"
    azd_log_path = tmp_path / "azd-calls.log"
    _write_az_stub(bin_dir, log_path)
    _write_azd_stub(bin_dir, azd_log_path)

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
    azd_calls = azd_log_path.read_text() if azd_log_path.exists() else ""
    return result, calls, azd_calls


def _run_hook_script(script_path, tmp_path, az_stub_factory, environment=None):
    """Execute an azd hook script with a controllable fake `az` on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log_path = tmp_path / "az-calls.log"
    az_stub_factory(bin_dir, log_path)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env.setdefault("AZURE_SUBSCRIPTION_ID", "11111111-2222-3333-4444-555555555555")
    if environment:
        env.update(environment)

    result = subprocess.run(
        [str(script_path)],
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
    result, calls, _ = _run_cleanup_external(tmp_path, ["--yes"])

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
    result, calls, _ = _run_cleanup_external(
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
    result, calls, _ = _run_cleanup_external(
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
    result, calls, _ = _run_cleanup_external(
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

    result, _, _ = _run_cleanup_external(tmp_path, ["--yes"])

    assert result.returncode == 0, (
        f"cleanup-external.sh must run on bash {version}: {result.stderr}"
    )
    assert "unbound variable" not in result.stderr


def test_cleanup_external_clears_hook_set_image_env_vars_alongside_role_cleanup(tmp_path):
    """`azd down` may delete the resource group (and its ACR) that
    `azd-postprovision.sh` recorded in SRE_CONTAINER_IMAGE/SRE_IMAGE_TAG. If
    those values survive in the azd environment, reusing it later would make
    `azd provision` try to redeploy an image tag that no longer exists
    instead of falling back to the placeholder. `predown` always runs this
    hook with --yes (see azure.yaml), so clearing here is safe.
    """
    subscription_id = "11111111-2222-3333-4444-555555555555"
    recorded = (
        f"/subscriptions/{subscription_id}/providers/Microsoft.Authorization"
        "/roleAssignments/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    result, calls, azd_calls = _run_cleanup_external(
        tmp_path,
        ["--yes"],
        evidence={
            "monitoring_contributor_assignment_id": recorded,
            "agent_principal_id": "principal-a",
            "uami_monitoring_contributor_assignment_id": recorded,
            "agent_user_assigned_principal_id": "principal-b",
        },
        environment={"AZURE_SUBSCRIPTION_ID": subscription_id},
    )

    assert result.returncode == 0, result.stderr
    assert f"role assignment delete --ids {recorded}" in calls
    assert "env set SRE_CONTAINER_IMAGE ''" in azd_calls
    assert "env set SRE_IMAGE_TAG ''" in azd_calls
    assert "group delete" not in calls
    assert "resource delete" not in calls


def test_cleanup_external_clears_image_env_vars_even_without_agent_evidence(tmp_path):
    """A lab that never configured the SRE Agent takes the early-exit path
    (no evidence file); the hook-set image values must still be cleared on
    that path, since it has nothing to do with the Agent.
    """
    result, calls, azd_calls = _run_cleanup_external(tmp_path, ["--yes"])

    assert result.returncode == 0, result.stderr
    assert calls == "", f"nothing external exists, but the hook called: {calls}"
    assert "env set SRE_CONTAINER_IMAGE ''" in azd_calls
    assert "env set SRE_IMAGE_TAG ''" in azd_calls


def test_cleanup_external_does_not_clear_image_env_vars_during_a_dry_run(tmp_path):
    """Without --yes, the hook only plans actions; it must not mutate the
    azd environment either.
    """
    result, _, azd_calls = _run_cleanup_external(tmp_path, [])

    assert result.returncode == 0, result.stderr
    assert azd_calls == "", (
        f"a dry run (no --yes) must not mutate the azd environment: {azd_calls}"
    )


def test_azd_configure_reports_a_clear_error_when_the_azure_cli_is_not_logged_in(tmp_path):
    """`az account show` fails with a generic Azure CLI error when signed
    out. Guard it so the hook fails fast with one unambiguous message
    instead of raw CLI stderr or an unexplained `set -e` abort.
    """
    result, calls = _run_hook_script(
        AZD_CONFIGURE, tmp_path, _write_login_failing_az_stub
    )

    assert result.returncode != 0
    assert "az login" in result.stderr
    assert "Please run 'az login' to setup account." not in result.stderr
    assert calls.strip() == "account show --query id -o tsv", (
        "the hook must exit immediately after the failed login check, "
        f"before any other az call: {calls!r}"
    )


def test_azd_postprovision_reports_a_clear_error_when_the_azure_cli_is_not_logged_in(tmp_path):
    environment = {
        "AZURE_RESOURCE_GROUP": "rg-test",
        "AZURE_ACR_NAME": "acrtest",
        "AZURE_CONTAINER_APP_NAME": "ca-test",
        "AZURE_CONTAINER_APP_FQDN": "ca-test.example.com",
    }
    result, calls = _run_hook_script(
        AZD_POSTPROVISION, tmp_path, _write_login_failing_az_stub, environment
    )

    assert result.returncode != 0
    assert "az login" in result.stderr
    assert "Please run 'az login' to setup account." not in result.stderr
    assert calls.strip() == "account show --query id -o tsv", (
        "the hook must exit immediately after the failed login check, "
        f"before any other az call: {calls!r}"
    )

