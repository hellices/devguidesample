"""Behaviour tests for the azd lifecycle hook scripts.

The hooks run inside `azd provision` / `azd down`, where the Azure CLI's
active subscription is whatever the operator last selected -- not
necessarily the subscription azd is deploying into. Every Azure CLI
operation therefore has to be pinned to AZURE_SUBSCRIPTION_ID, and the
`predown` hook has to survive a lab that never configured the Agent.
"""

import os
import re
import stat
import subprocess
from pathlib import Path


from azd_fake import write_azd_stub

SCRIPTS_DIR = Path(__file__).parents[1]
LAB_ROOT = Path(__file__).parents[2]
AZD_CONFIGURE = SCRIPTS_DIR / "azd-configure.sh"
AZD_POSTPROVISION = SCRIPTS_DIR / "azd-postprovision.sh"
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


def test_azd_postprovision_runs_setup_venv_before_any_azure_cli_call():
    text = AZD_POSTPROVISION.read_text()

    assert "setup-venv.sh" in text
    setup_venv_at = text.index("setup-venv.sh")
    first_account_show_at = text.index("az account show")
    assert setup_venv_at < first_account_show_at, (
        "setup-venv.sh must run before the hook makes any Azure CLI call"
    )


def test_azd_postprovision_stops_before_any_azure_call_when_setup_venv_fails(tmp_path):
    """`app/.venv` setup is local and has nothing to do with the Azure CLI,
    but a broken corporate proxy or missing `uv` must still stop the hook
    before it spends a single Azure API call -- the cloud side is already
    provisioned by the time this hook runs, so failing fast here changes
    nothing about that, but a failure must never be masked by continuing
    on to the ACR build."""
    scripts_copy = tmp_path / "scripts"
    scripts_copy.mkdir()
    (scripts_copy / "azd-postprovision.sh").write_text(AZD_POSTPROVISION.read_text())
    (scripts_copy / "azd-postprovision.sh").chmod(0o755)
    fake_setup_venv = scripts_copy / "setup-venv.sh"
    fake_setup_venv.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'uv is required to set up app/.venv but was not found on PATH.' >&2\n"
        "echo 'azd hooks run postprovision' >&2\n"
        "exit 1\n"
    )
    fake_setup_venv.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az_log = tmp_path / "az-calls.log"
    _write_az_stub(bin_dir, az_log)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["AZURE_SUBSCRIPTION_ID"] = "11111111-2222-3333-4444-555555555555"
    env["AZURE_RESOURCE_GROUP"] = "rg-test"
    env["AZURE_ACR_NAME"] = "acrtest"
    env["AZURE_CONTAINER_APP_NAME"] = "ca-test"
    env["AZURE_CONTAINER_APP_FQDN"] = "ca-test.example.com"

    result = subprocess.run(
        [str(scripts_copy / "azd-postprovision.sh")],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert not az_log.exists() or az_log.read_text() == ""
    assert "uv" in result.stderr


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



def _run_azd_configure(tmp_path, azd_values, missing_key_mode="azd_1_29"):
    """Run the preprovision hook with a fake `az` and a realistic fake `azd`.

    The fake `azd` reproduces azd 1.29.0: it reports a value it does not
    have with `ERROR: ...` on **stdout** and exit 1, and resolves the
    project from `--cwd` (else the process working directory). The hook is
    started from a scratch directory that holds no `azure.yaml`.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    az_log = tmp_path / "az-calls.log"
    azd_log = tmp_path / "azd-calls.log"
    _write_az_stub(bin_dir, az_log)
    write_azd_stub(bin_dir, azd_values, missing_key_mode, azd_log)

    workdir = tmp_path / "elsewhere"
    workdir.mkdir(exist_ok=True)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["AZURE_SUBSCRIPTION_ID"] = "11111111-2222-3333-4444-555555555555"

    result = subprocess.run(
        [str(AZD_CONFIGURE)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(workdir),
    )
    return result, (azd_log.read_text() if azd_log.exists() else "")


def test_azd_configure_defaults_the_resource_group_when_azd_has_no_value(tmp_path):
    """A key azd does not have must read as absent, not as azd's error text.

    azd 1.29 prints `ERROR: ...` on stdout while exiting non-zero, so a
    lookup that keeps stdout regardless sees a non-empty "value" and skips
    the default the hook is there to write.
    """
    result, azd_calls = _run_azd_configure(
        tmp_path, {"AZURE_ENV_NAME": "sre-lab-hooktest"}
    )

    assert result.returncode == 0, result.stderr
    assert "env set AZURE_RESOURCE_GROUP rg-sre-lab-hooktest" in azd_calls, (
        f"the hook did not derive the resource group: {azd_calls!r}"
    )
    assert "env set SRE_LAB_EXPIRES_ON" in azd_calls
    assert "ERROR" not in azd_calls, (
        f"azd's error output leaked into a stored value: {azd_calls!r}"
    )


def test_azd_configure_keeps_values_the_azd_environment_already_has(tmp_path):
    result, azd_calls = _run_azd_configure(
        tmp_path,
        {
            "AZURE_ENV_NAME": "sre-lab-hooktest",
            "AZURE_RESOURCE_GROUP": "rg-chosen-by-the-operator",
            "SRE_LAB_EXPIRES_ON": "2026-08-15",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "env set AZURE_RESOURCE_GROUP" not in azd_calls, (
        f"the hook overwrote an existing resource group: {azd_calls!r}"
    )
    assert "env set SRE_LAB_EXPIRES_ON" not in azd_calls


def test_azd_configure_pins_every_azd_lookup_to_the_lab_project(tmp_path):
    """azd hooks are also run by hand while debugging a lab, so the hook
    must not depend on the working directory it inherits."""
    result, azd_calls = _run_azd_configure(
        tmp_path, {"AZURE_ENV_NAME": "sre-lab-hooktest"}
    )

    assert result.returncode == 0, result.stderr
    assert f"cwd={LAB_ROOT}" in azd_calls, (
        f"azd was not pinned to the lab project root: {azd_calls!r}"
    )
    assert "no project exists" not in azd_calls


def test_azd_configure_refuses_to_derive_a_resource_group_without_an_environment(tmp_path):
    """Deriving `rg-` from an unavailable environment name would create a
    resource group nobody can identify; the hook must stop instead."""
    result, azd_calls = _run_azd_configure(tmp_path, {})

    assert result.returncode != 0
    assert "azd env new" in result.stderr
    assert "env set AZURE_RESOURCE_GROUP" not in azd_calls, (
        f"the hook must not store a half-derived resource group: {azd_calls!r}"
    )
