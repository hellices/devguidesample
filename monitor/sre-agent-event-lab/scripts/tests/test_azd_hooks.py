"""Behaviour tests for the azd lifecycle hook scripts.

The hooks run inside `azd provision` / `azd down`, where the Azure CLI's
active subscription is whatever the operator last selected -- not
necessarily the subscription azd is deploying into. Every Azure CLI
operation therefore has to be pinned to AZURE_SUBSCRIPTION_ID, and the
`predown` hook has to survive a lab that never configured the Agent.

The `postprovision` hook is deliberately *local only*: it prepares
`app/.venv` and nothing else. Building the lab image and moving the
Container App onto it belongs to the deploy phase
(`scripts/azd-deploy-app.sh`, tested in `test_azd_deploy_app.py`), because
the workload identity's `AcrPull` grant is not necessarily usable the
moment provisioning returns.

Every test that *executes* a hook script runs it from a `lab_copy` --
never the real, in-place `azd-configure.sh` /
`azd-postprovision-local.sh` / `setup-venv.sh`.
`azd-postprovision-local.sh` calls `setup-venv.sh`, and `setup-venv.sh`
resolves its own `SCRIPT_DIR`/`LAB_ROOT`/`VENV_DIR` from
its own `${BASH_SOURCE[0]}`, never from the caller's cwd -- so running the
real, in-place hook (as this file once did, pointing
only the *subprocess's* cwd or `AZURE_*` environment at a scratch
`tmp_path`) still always resolves `VENV_DIR` to the real, developer-machine
`app/.venv`, and setup-venv.sh's `uv venv --allow-existing` / `uv pip
install` would then run for real against it -- a real filesystem mutation
and a real network/package-index call, entirely unrelated to what the test
claims to be checking. `lab_copy`
copies the whole `scripts/`+`app/` layout the scripts depend on into
`tmp_path`, so every script's own path resolution lands entirely inside
`tmp_path`; `real_lab_venv_tree_is_never_touched` (autouse, this whole
file) is the regression tripwire proving it -- it fingerprints the real
`app/.venv` tree before and after every test here and fails loudly on any
drift; `test_no_execution_helper_runs_a_real_in_place_hook_script` is a
second, purely static tripwire (a source-text scan of this very file, no
subprocess involved) that keeps the same vulnerability from silently
coming back.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from azd_fake import write_azd_stub

SCRIPTS_DIR = Path(__file__).parents[1]
LAB_ROOT = Path(__file__).parents[2]
AZD_CONFIGURE = SCRIPTS_DIR / "azd-configure.sh"
AZD_POSTPROVISION = SCRIPTS_DIR / "azd-postprovision-local.sh"
AZD_DEPLOY_APP = SCRIPTS_DIR / "azd-deploy-app.sh"
SETUP_VENV = SCRIPTS_DIR / "setup-venv.sh"
REQUIREMENTS = LAB_ROOT / "app" / "requirements.txt"
REQUIREMENTS_DEV = LAB_ROOT / "app" / "requirements-dev.txt"
REAL_VENV_DIR = LAB_ROOT / "app" / ".venv"
SUBSCRIPTION_PIN = '--subscription "${AZURE_SUBSCRIPTION_ID}"'
# The one deliberately unpinned call: it reads whichever account is active
# so the hook can report a mismatch.
ACTIVE_ACCOUNT_PROBE = "az account show --query id"
# Everything that changes the deployed application. The provision phase
# must contain none of it.
DEPLOY_ACTIONS = (
    "az acr build",
    "az containerapp update",
    "az containerapp ingress update",
    "az containerapp registry set",
)


# --- Regression tripwire: the real app/.venv must never move ---------------
#
# Two independent guards, deliberately redundant:
#   1. `real_lab_venv_tree_is_never_touched` (below) is an *execution-time*
#      safety net: it fingerprints the real tree and fails if any test in
#      this file ever changes it, no matter how that test is written.
#   2. `test_no_execution_helper_runs_a_real_in_place_hook_script` (further
#      down) is a *static* safety net: it scans this file's own source for
#      the exact patterns that caused the original vulnerability, and never
#      executes anything -- so it is always safe to run, including on a
#      version of this file that would otherwise mutate the real venv.


def _venv_tree_fingerprint(root: Path):
    """A manifest-style fingerprint of the whole real `app/.venv` tree.

    For every entry under `root`, records its path relative to `root`,
    whether it is a directory/file/symlink, its symlink target (if any),
    its size, and its mtime for every entry -- then hashes the whole sorted
    manifest into one digest, plus a byte-content sha256 of `bin/python`'s
    *resolved* target (uv manages `bin/python` as a symlink to a real
    interpreter binary that can live entirely outside `root`, e.g. under
    `~/.local/share/uv/python/...`; `path.resolve()` follows it there).
    This is deliberately a *tree* fingerprint, not a single file's: `uv
    venv --allow-existing` / `uv pip install` mutate site-packages by
    adding, removing, resizing, and retargeting many files and symlinks at
    once, so a single canary file (or a bare directory mtime) could miss a
    change a broader manifest catches. mtime is included as one signal
    among several, deliberately not the only one -- comparing mtime alone
    would be brittle (some legitimate changes leave mtime untouched at
    second resolution; some incidental system activity touches mtime
    without any content change) -- so a real regression must additionally
    show up as a manifest entry that is new, missing, resized, retargeted,
    or reclassified (file/dir/symlink), or as a changed interpreter content
    hash, to be caught; mtime differences alone are deliberately not enough
    for the assertion below to fire a false positive.
    """
    if not root.exists():
        return ("absent", None, None, None)
    entries = []
    for path in sorted(root.rglob("*")):
        try:
            st = path.lstat()
        except OSError:
            continue
        is_link = path.is_symlink()
        kind = "symlink" if is_link else ("dir" if path.is_dir() else "file")
        target = os.readlink(path) if is_link else None
        entries.append(
            (str(path.relative_to(root)), kind, target, st.st_size, st.st_mtime_ns)
        )
    manifest = repr(entries).encode()

    venv_python = root / "bin" / "python"
    interpreter_digest = None
    if venv_python.exists() or venv_python.is_symlink():
        resolved = venv_python.resolve()
        if resolved.is_file():
            interpreter_digest = hashlib.sha256(resolved.read_bytes()).hexdigest()

    return (
        "present",
        len(entries),
        hashlib.sha256(manifest).hexdigest(),
        interpreter_digest,
    )


@pytest.fixture(autouse=True)
def real_lab_venv_tree_is_never_touched():
    """Module-wide tripwire: fingerprints the real, developer-machine
    `app/.venv` tree before and after every test in this file and fails
    loudly if it ever changes. This must never fire; if it does, a test in
    this file stopped running against a `lab_copy` and started running a
    real hook script in place again -- exactly the vulnerability this
    whole file's redesign fixes.
    """
    before = _venv_tree_fingerprint(REAL_VENV_DIR)
    yield
    after = _venv_tree_fingerprint(REAL_VENV_DIR)
    assert after == before, (
        "a test in this file mutated the REAL app/.venv tree "
        f"(before={before!r} after={after!r}); every test that executes a "
        "hook script must run it from a `lab_copy`, never the real script "
        "in place"
    )


@pytest.fixture
def lab_copy(tmp_path):
    """A throwaway copy of exactly the layout the hook scripts depend on:
    `azd-configure.sh`, `azd-postprovision-local.sh`, and the *real*
    `setup-venv.sh` under `scripts/`, the real `app/requirements.txt` and
    `app/requirements-dev.txt` under `app/` (setup-venv.sh's own
    `REQUIREMENTS_FILE`), and a placeholder `azure.yaml` at the copied lab
    root (azd-configure.sh's fake-`azd` stub requires one to exist at
    whatever `--cwd` it is given, matching the real lab layout). Every
    script's own `SCRIPT_DIR`/`LAB_ROOT`/`APP_DIR`/`VENV_DIR` resolution
    (from its own `${BASH_SOURCE[0]}`) therefore lands entirely inside
    `tmp_path`, never inside the real lab tree. `app/.venv` is deliberately
    never created here -- a script under test creates it fresh, against
    whatever fake `uv` a given test puts on `PATH`.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for source, name in (
        (AZD_CONFIGURE, "azd-configure.sh"),
        (AZD_POSTPROVISION, "azd-postprovision-local.sh"),
        (SETUP_VENV, "setup-venv.sh"),
    ):
        copy = scripts_dir / name
        shutil.copy2(source, copy)
        copy.chmod(copy.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shutil.copy2(REQUIREMENTS, app_dir / "requirements.txt")
    shutil.copy2(REQUIREMENTS_DEV, app_dir / "requirements-dev.txt")

    (tmp_path / "azure.yaml").write_text("name: sre-lab-hooktest\n")

    return SimpleNamespace(
        root=tmp_path,
        configure=scripts_dir / "azd-configure.sh",
        postprovision=scripts_dir / "azd-postprovision-local.sh",
        setup_venv=scripts_dir / "setup-venv.sh",
        app_dir=app_dir,
    )


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


def _write_fake_uv(directory, log_path):
    """A fake `uv` that logs every invocation, creates a runnable stub
    interpreter under whatever target directory `uv venv` is given, and
    always succeeds. This lets a *real*, copied `setup-venv.sh` run its
    genuine `uv venv` / `uv pip install` / Pillow-import logic end to end
    without ever reaching the real `uv` binary, a real virtual environment,
    or a real package index -- `log_path` is what each test's assertion
    inspects to prove the fake, not the real, `uv` ran.
    """
    stub = directory / "uv"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "%s\\n" "$*" >> "{log_path}"\n'
        'case "$1" in\n'
        "  venv)\n"
        '    target="${@: -1}"\n'
        '    mkdir -p "${target}/bin"\n'
        "    cat > \"${target}/bin/python\" <<'PYEOF'\n"
        "#!/usr/bin/env bash\n"
        'exit 0\n'
        "PYEOF\n"
        '    chmod +x "${target}/bin/python"\n'
        "    ;;\n"
        "  pip)\n"
        "    exit 0\n"
        "    ;;\n"
        "  *)\n"
        "    exit 0\n"
        "    ;;\n"
        "esac\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def _run_hook_script(script_path, tmp_path, az_stub_factory, environment=None):
    """Execute a *copied* azd hook script with a controllable fake `az` on
    PATH. `script_path` must come from a `lab_copy` -- see this module's
    top-of-file docstring and `test_no_execution_helper_runs_a_real_in_place_hook_script`
    for why the real, in-place script must never be passed here.
    """
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


def test_no_execution_helper_runs_a_real_in_place_hook_script():
    """Regression tripwire for the vulnerability every `lab_copy`-based test
    below fixes: executing the real, in-place `AZD_CONFIGURE` /
    `AZD_POSTPROVISION` / `SETUP_VENV` path constants (as this file once
    did) always resolves those scripts' own `SCRIPT_DIR`/`LAB_ROOT`/
    `VENV_DIR` to the real, developer-machine `app/.venv`, regardless of
    what `tmp_path`, `cwd`, or `AZURE_*` environment a test additionally
    sets up -- only copying the whole `scripts/`+`app/` tree elsewhere
    (`lab_copy`) actually moves that resolution. This is a pure
    source-text scan of this file itself: it runs no subprocess and
    touches no filesystem outside its own `__file__`, so it is always safe
    to run -- unlike the execution pattern it guards against. Confirmed in
    session: run against the pre-fix version of this file (the
    git-committed HEAD revision before this test existed), every one of
    `_run_hook_script`'s two direct hook-script call sites and
    `_run_azd_configure`'s own subprocess call site matched, because that
    revision passed the real, in-place path constants straight to a
    subprocess line-wrapped across multiple lines. Patterns below are
    regexes, not bare substrings, specifically so a call site line-wrapped
    that way cannot dodge the scan by reformatting.
    """
    source = Path(__file__).read_text()
    forbidden_execution_patterns = (
        r"_run_hook_script\(\s*AZD_CONFIGURE\b",
        r"_run_hook_script\(\s*AZD_POSTPROVISION\b",
        r"_run_hook_script\(\s*SETUP_VENV\b",
        r"\[\s*str\(\s*AZD_CONFIGURE\s*\)\s*\]",
        r"\[\s*str\(\s*AZD_POSTPROVISION\s*\)\s*\]",
        r"\[\s*str\(\s*SETUP_VENV\s*\)\s*\]",
    )
    for pattern in forbidden_execution_patterns:
        assert not re.search(pattern, source), (
            f"found a real, in-place hook script execution pattern {pattern!r} "
            "in this test file; every executed hook script must come from "
            "the `lab_copy` fixture instead"
        )


def test_azd_configure_pins_every_azure_cli_call_to_the_target_subscription():
    for command in _az_invocations(AZD_CONFIGURE.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"azd-configure.sh runs an unpinned Azure CLI command: {command}"
        )


def test_azd_postprovision_pins_every_azure_cli_call_to_the_target_subscription():
    """Vacuously true today -- the provision-phase hook makes no Azure CLI
    call at all -- but kept so that any Azure call added back to it has to
    carry the same subscription pin as every other lab entry point."""
    for command in _az_invocations(AZD_POSTPROVISION.read_text()):
        if command.startswith(ACTIVE_ACCOUNT_PROBE):
            continue
        assert SUBSCRIPTION_PIN in command, (
            f"azd-postprovision-local.sh runs an unpinned Azure CLI command: {command}"
        )


def test_azd_configure_requires_the_target_subscription_and_verifies_the_active_account():
    text = AZD_CONFIGURE.read_text()
    assert "AZURE_SUBSCRIPTION_ID:?" in text, (
        "azd-configure.sh must fail fast when azd did not provide a subscription"
    )
    assert ACTIVE_ACCOUNT_PROBE in text, (
        "azd-configure.sh must verify which subscription the Azure CLI is signed in to"
    )


def test_postprovision_never_builds_or_updates_the_container_app():
    """The provision phase must leave the public placeholder image running.

    Bicep creates the registry, the workload identity, its `AcrPull`
    assignment and a placeholder-image Container App in one deployment.
    Building and switching the image straight afterwards -- what this hook
    used to do -- starts an ACR pull with a role assignment that has just
    been created, with no check that it is usable yet. Those steps belong
    to `azd-deploy-app.sh`, behind the AcrPull poll.
    """
    text = AZD_POSTPROVISION.read_text()

    for action in DEPLOY_ACTIONS:
        assert action not in text, (
            f"the provision-phase hook still runs `{action}`"
        )
    assert "SRE_CONTAINER_IMAGE" not in text, (
        "recording a built image is part of the deploy phase"
    )
    assert "/healthz" not in text, (
        "the placeholder image serves no /healthz; verifying it belongs to "
        "the deploy phase"
    )


def test_postprovision_only_prepares_the_local_python_environment(tmp_path, lab_copy):
    """Executed, not read: the hook runs `setup-venv.sh` (against a fake
    `uv`) and spends no Azure API call at all -- not even the login probe,
    which has nothing to check when nothing is deployed."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az_log = tmp_path / "az-calls.log"
    uv_log = tmp_path / "uv-calls.log"
    azd_log = tmp_path / "azd-calls.log"
    _write_az_stub(bin_dir, az_log)
    _write_fake_uv(bin_dir, uv_log)
    write_azd_stub(bin_dir, {}, "azd_1_29", azd_log)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["AZURE_SUBSCRIPTION_ID"] = "11111111-2222-3333-4444-555555555555"

    result = subprocess.run(
        [str(lab_copy.postprovision)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not az_log.exists() or az_log.read_text().strip() == "", (
        f"the provision-phase hook made an Azure CLI call: {az_log.read_text()!r}"
    )
    uv_calls = uv_log.read_text() if uv_log.exists() else ""
    assert "venv" in uv_calls and "pip install" in uv_calls, (
        f"the hook did not prepare the local environment: {uv_calls!r}"
    )
    created_python = lab_copy.app_dir / ".venv" / "bin" / "python"
    assert created_python.is_file()
    assert not str(created_python).startswith(str(LAB_ROOT))


def test_postprovision_says_where_the_application_deployment_happens(tmp_path, lab_copy):
    """`azd provision` on its own leaves the placeholder image running, so
    the hook that ends the provision phase has to say what still has to
    happen -- otherwise a successful `azd provision` looks like a finished
    lab."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_uv(bin_dir, tmp_path / "uv-calls.log")

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(lab_copy.postprovision)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "azd deploy" in result.stdout + result.stderr


def test_postprovision_fails_when_the_local_environment_cannot_be_prepared(
    tmp_path, lab_copy
):
    """A broken corporate proxy or a missing `uv` must fail the hook rather
    than let `azd provision` report success over a half-prepared lab."""
    lab_copy.setup_venv.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'uv is required to set up app/.venv but was not found on PATH.' >&2\n"
        "exit 1\n"
    )
    lab_copy.setup_venv.chmod(0o755)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az_log = tmp_path / "az-calls.log"
    _write_az_stub(bin_dir, az_log)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [str(lab_copy.postprovision)],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert not az_log.exists() or az_log.read_text() == ""
    assert "uv" in result.stderr


def test_azd_configure_reports_a_clear_error_when_the_azure_cli_is_not_logged_in(tmp_path, lab_copy):
    """`az account show` fails with a generic Azure CLI error when signed
    out. Guard it so the hook fails fast with one unambiguous message
    instead of raw CLI stderr or an unexplained `set -e` abort.
    """
    result, calls = _run_hook_script(
        lab_copy.configure, tmp_path, _write_login_failing_az_stub
    )

    assert result.returncode != 0
    assert "az login" in result.stderr
    assert "Please run 'az login' to setup account." not in result.stderr
    assert calls.strip() == "account show --query id -o tsv", (
        "the hook must exit immediately after the failed login check, "
        f"before any other az call: {calls!r}"
    )


def test_deploy_actions_live_only_in_the_deploy_phase_hook():
    """One place, and only one place, changes the running application."""
    deploy_text = AZD_DEPLOY_APP.read_text()
    for action in DEPLOY_ACTIONS:
        assert action in deploy_text, (
            f"`{action}` must live in the deploy-phase hook"
        )
        for script in (AZD_CONFIGURE, AZD_POSTPROVISION):
            assert action not in script.read_text(), (
                f"`{action}` must not run in the provision phase ({script.name})"
            )


def _run_azd_configure(tmp_path, lab_copy, azd_values, missing_key_mode="azd_1_29"):
    """Run the preprovision hook (a `lab_copy` copy) with a fake `az` and a
    realistic fake `azd`.

    The fake `azd` reproduces azd 1.29.0: it reports a value it does not
    have with `ERROR: ...` on **stdout** and exit 1, and resolves the
    project from `--cwd` (else the process working directory). The hook is
    started from a scratch directory that holds no `azure.yaml` -- distinct
    from `lab_copy.root`, which does (matching the real lab layout), so
    that `--cwd "${LAB_ROOT}"` inside the copied script is what makes the
    lookups succeed, not the process's own cwd.
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
        [str(lab_copy.configure)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(workdir),
    )
    return result, (azd_log.read_text() if azd_log.exists() else "")


def test_azd_configure_defaults_the_resource_group_when_azd_has_no_value(tmp_path, lab_copy):
    """A key azd does not have must read as absent, not as azd's error text.

    azd 1.29 prints `ERROR: ...` on stdout while exiting non-zero, so a
    lookup that keeps stdout regardless sees a non-empty "value" and skips
    the default the hook is there to write.
    """
    result, azd_calls = _run_azd_configure(
        tmp_path, lab_copy, {"AZURE_ENV_NAME": "sre-lab-hooktest"}
    )

    assert result.returncode == 0, result.stderr
    assert "env set AZURE_RESOURCE_GROUP rg-sre-lab-hooktest" in azd_calls, (
        f"the hook did not derive the resource group: {azd_calls!r}"
    )
    assert "env set SRE_LAB_EXPIRES_ON" in azd_calls
    assert "ERROR" not in azd_calls, (
        f"azd's error output leaked into a stored value: {azd_calls!r}"
    )


def test_azd_configure_keeps_values_the_azd_environment_already_has(tmp_path, lab_copy):
    result, azd_calls = _run_azd_configure(
        tmp_path,
        lab_copy,
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


def test_azd_configure_pins_every_azd_lookup_to_the_lab_project(tmp_path, lab_copy):
    """azd hooks are also run by hand while debugging a lab, so the hook
    must not depend on the working directory it inherits."""
    result, azd_calls = _run_azd_configure(
        tmp_path, lab_copy, {"AZURE_ENV_NAME": "sre-lab-hooktest"}
    )

    assert result.returncode == 0, result.stderr
    assert f"cwd={lab_copy.root}" in azd_calls, (
        f"azd was not pinned to the copied lab project root: {azd_calls!r}"
    )
    assert "no project exists" not in azd_calls


def test_azd_configure_refuses_to_derive_a_resource_group_without_an_environment(tmp_path, lab_copy):
    """Deriving `rg-` from an unavailable environment name would create a
    resource group nobody can identify; the hook must stop instead."""
    result, azd_calls = _run_azd_configure(tmp_path, lab_copy, {})

    assert result.returncode != 0
    assert "azd env new" in result.stderr
    assert "env set AZURE_RESOURCE_GROUP" not in azd_calls, (
        f"the hook must not store a half-derived resource group: {azd_calls!r}"
    )
