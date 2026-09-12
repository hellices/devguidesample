"""Behaviour tests for `setup-venv.sh`, the idempotent preparer of
`app/.venv` and the entire job of the `postprovision` azd hook
(`scripts/azd-postprovision-local.sh`).

Every test drives the real script's *logic* against a fake `uv` on PATH
(never a real network install) -- but never the real script *file in
place*. `setup-venv.sh` resolves `SCRIPT_DIR`/`LAB_ROOT`/`VENV_DIR` from its
own `${BASH_SOURCE[0]}`, never from the caller's cwd, so running the real,
in-place script (as this suite once did, pointing only `cwd` at a scratch
`tmp_path`) still always operates on the real `app/.venv` -- and a fake `uv`
that *creates* `${target}/bin/python` (as every success-path test here
needs) then either overwrites the real `app/.venv/bin/python` outright or,
because it is a symlink `uv` manages, writes straight through it into the
real interpreter binary it points at. Every test below therefore runs a
throwaway *copy* of `setup-venv.sh` plus the real `app/requirements.txt` /
`app/requirements-dev.txt`, laid out under `tmp_path` exactly as the real
lab lays them out, so the copy's own path resolution lands entirely inside
`tmp_path`. `real_lab_venv_is_never_touched` is the regression tripwire that
proves it: it fingerprints the real `app/.venv/bin/python` before and after
every test in this file and fails loudly on any drift.
"""
import hashlib
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "setup-venv.sh"
LAB_ROOT = Path(__file__).parents[2]
REQUIREMENTS = LAB_ROOT / "app" / "requirements.txt"
REQUIREMENTS_DEV = LAB_ROOT / "app" / "requirements-dev.txt"
REAL_VENV_PYTHON = LAB_ROOT / "app" / ".venv" / "bin" / "python"


def _fingerprint(path: Path):
    """(is_symlink, symlink target, sha256 of the resolved file's content).

    Sensitive to a swapped-in regular file, a retargeted symlink, or edited
    content -- any of which is exactly what a fake `uv` run against the real
    `app/.venv` in place would do. `(None, None, None)` means the path is
    simply absent (also a legitimate, distinct fingerprint).
    """
    if not path.exists() and not path.is_symlink():
        return (None, None, None)
    is_link = path.is_symlink()
    target = os.readlink(path) if is_link else None
    resolved = path.resolve()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest() if resolved.is_file() else None
    return (is_link, target, digest)


@pytest.fixture(autouse=True)
def real_lab_venv_is_never_touched():
    """Regression tripwire for the vulnerability every fixture below fixes.

    Fingerprints the real, developer-machine `app/.venv/bin/python` before
    and after each test and fails loudly if it ever changes -- type
    (symlink vs. regular file), symlink target, or content hash. This must
    never fire; if it does, a test in this file stopped running against a
    `lab_copy` and started running the real script in place again.
    """
    before = _fingerprint(REAL_VENV_PYTHON)
    yield
    after = _fingerprint(REAL_VENV_PYTHON)
    assert after == before, (
        "a test in this file mutated the REAL app/.venv/bin/python "
        f"(before={before!r} after={after!r}); every test must run a "
        "lab_copy of setup-venv.sh under tmp_path, never the real script "
        "in place"
    )


@pytest.fixture
def lab_copy(tmp_path):
    """A throwaway copy of exactly the layout `setup-venv.sh` depends on:
    itself under `scripts/`, plus `app/requirements.txt` and
    `app/requirements-dev.txt` under `app/`. `app/.venv` is deliberately
    never copied -- the script creates it fresh -- so nothing here ever
    reads or writes the real one. Returns the path to the copied script.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script_copy = scripts_dir / "setup-venv.sh"
    shutil.copy2(SCRIPT, script_copy)
    script_copy.chmod(script_copy.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    shutil.copy2(REQUIREMENTS, app_dir / "requirements.txt")
    shutil.copy2(REQUIREMENTS_DEV, app_dir / "requirements-dev.txt")

    return script_copy


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_fake_uv(bin_dir: Path, log_path: Path, venv_exit: int = 0, pip_exit: int = 0, pillow_importable: bool = True):
    """A fake `uv` that logs every invocation and creates just enough of a
    venv (`bin/python` as a real, runnable interpreter) that the script's
    own Pillow-import check can run against it. Only ever pointed at a
    `lab_copy`'s `tmp_path`-scoped `app/.venv`, never the real one."""
    real_python = os.environ.get("SETUP_VENV_TEST_PYTHON", "python3")
    stub = bin_dir / "uv"
    _write_executable(
        stub,
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
case "$1" in
  venv)
    if [[ {venv_exit} -ne 0 ]]; then
      exit {venv_exit}
    fi
    target="${{@: -1}}"
    mkdir -p "${{target}}/bin"
    cat > "${{target}}/bin/python" <<'PYEOF'
#!/usr/bin/env bash
if [[ "$1" == "-c" ]]; then
  case "$2" in
    *PIL*)
      exit_code=$([[ "{str(pillow_importable).lower()}" == "true" ]] && echo 0 || echo 1)
      exit "${{exit_code}}"
      ;;
  esac
fi
exec {real_python} "$@"
PYEOF
    chmod +x "${{target}}/bin/python"
    ;;
  pip)
    exit {pip_exit}
    ;;
  *)
    exit 0
    ;;
esac
""",
    )


def _write_fake_uv_no_matching_python(bin_dir: Path, log_path: Path):
    """A fake `uv` reproducing its real message when no installed Python
    clears the requested floor (verified against real `uv 0.10.9`): `uv
    venv` fails with `error: No interpreter found for Python >=X ...` on
    stderr, before ever reaching `uv pip install`."""
    stub = bin_dir / "uv"
    _write_executable(
        stub,
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log_path}"
case "$1" in
  venv)
    echo "error: No interpreter found for Python >=3.10 in managed installations or search path" >&2
    exit 1
    ;;
  *)
    exit 0
    ;;
esac
""",
    )


def _run(script: Path, bin_dir: Path, workdir: Path, extra_path: bool = True):
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    else:
        # Simulate `uv` genuinely absent: a PATH with no bin_dir at all,
        # not just an empty one, so no fake (or real, developer-machine)
        # `uv` is reachable.
        env["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        [str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(workdir),
    )


def test_fails_actionably_with_no_pip_fallback_when_uv_is_missing(tmp_path, lab_copy):
    result = _run(lab_copy, tmp_path / "bin-unused", tmp_path, extra_path=False)

    assert result.returncode != 0
    assert "uv" in result.stderr
    assert "install uv" in result.stderr.lower() or "uv is required" in result.stderr
    _assert_hint_explains_the_deploy_phase(result.stderr)


def test_succeeds_and_calls_uv_venv_then_uv_pip_install_with_requirements_dev(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = log_path.read_text()
    assert "venv --python" in calls
    assert "--allow-existing" in calls
    assert ".venv" in calls
    assert "pip install --python" in calls
    assert "requirements-dev.txt" in calls

    # The venv setup-venv.sh created must live under the throwaway copy,
    # never under the real lab tree.
    created_python = lab_copy.parents[1] / "app" / ".venv" / "bin" / "python"
    assert created_python.is_file(), "the fake venv was not created under lab_copy's tmp_path"
    assert str(created_python).startswith(str(tmp_path))
    assert not str(created_python).startswith(str(LAB_ROOT))


def test_never_falls_back_to_a_bare_pip_binary(tmp_path, lab_copy):
    """Even when a bare `pip` is reachable on PATH, the script must drive
    installation only through `uv pip install`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path)
    bare_pip_log = tmp_path / "bare-pip-calls.log"
    _write_executable(
        bin_dir / "pip",
        f"#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"{bare_pip_log}\"\nexit 0\n",
    )

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not bare_pip_log.exists(), "setup-venv.sh must never invoke a bare pip"


def test_is_idempotent_across_repeated_runs(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path)

    first = _run(lab_copy, bin_dir, tmp_path)
    second = _run(lab_copy, bin_dir, tmp_path)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr


def test_fails_actionably_when_uv_venv_creation_fails(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, venv_exit=1)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)
    assert "pip install" not in log_path.read_text()


def test_fails_actionably_when_uv_pip_install_fails(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pip_exit=1)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)
    assert "proxy" in result.stderr


def test_fails_actionably_when_pillow_is_still_not_importable(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pillow_importable=False)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    assert "Pillow" in result.stderr
    _assert_hint_explains_the_deploy_phase(result.stderr)


def test_installs_the_labs_real_requirements_dev_file():
    assert REQUIREMENTS_DEV.is_file()
    assert "Pillow" in REQUIREMENTS_DEV.read_text()


def test_script_never_executes_a_bare_pip_or_pip3_command():
    """Every executable (non-comment, non-message) shell command line that
    starts with `pip`/`pip3` would be a fallback outside `uv`; only lines
    that start with `uv` are allowed to reach a `pip` subcommand."""
    for line in SCRIPT.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "echo")):
            continue
        if re.match(r"^(if\s+!\s+)?pip3?\b", stripped):
            raise AssertionError(("bare pip invocation found", stripped))


# --- The provision/deploy split: what a failure here does and does not mean

#
# `setup-venv.sh` is the whole job of the `postprovision` hook now: the
# Container App image build and the image switch moved to the deploy phase
# (`scripts/azd-deploy-app.sh`, run by `azd deploy` / `azd up`'s deploy
# phase behind the AcrPull gate). So a failure here no longer sits in the
# middle of a half-finished cloud deployment -- re-running just this script
# is a complete fix for the local part, and every failure message must say
# what still has to happen afterwards (`azd deploy`) instead of claiming the
# app deployment is about to run inside this same hook.


def _assert_hint_explains_the_deploy_phase(stderr: str):
    assert "./scripts/setup-venv.sh" in stderr, (
        "the local environment is the only thing this hook prepares, so "
        "re-running this script directly is now a complete recovery"
    )
    assert "azd deploy" in stderr, (
        "the application deployment is a separate phase the operator still "
        "has to run; the hint must name it"
    )
    lowered = stderr.lower()
    assert "run *after* this step" not in lowered, (
        "the ACR build no longer runs later inside this same hook"
    )
    assert "this hook's container app image build" not in lowered


def test_missing_uv_hint_explains_the_separate_deploy_phase(tmp_path, lab_copy):
    result = _run(lab_copy, tmp_path / "bin-unused", tmp_path, extra_path=False)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)


def test_venv_creation_failure_hint_explains_the_separate_deploy_phase(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, venv_exit=1)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)


def test_pip_install_failure_hint_explains_the_separate_deploy_phase(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pip_exit=1)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)


def test_pillow_failure_hint_explains_the_separate_deploy_phase(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pillow_importable=False)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    _assert_hint_explains_the_deploy_phase(result.stderr)


# --- Finding #3: actionable "no matching Python" guidance ------------------


def test_fails_actionably_with_uv_python_install_guidance_when_no_matching_python_is_found(tmp_path, lab_copy):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv_no_matching_python(bin_dir, log_path)

    result = _run(lab_copy, bin_dir, tmp_path)

    assert result.returncode != 0
    assert "No interpreter found" in result.stderr
    assert "uv python install 3.12" in result.stderr
    assert "proxy" in result.stderr.lower() or "mirror" in result.stderr.lower()
    assert "pip install" not in log_path.read_text(), (
        "a missing interpreter must never fall through to uv pip install"
    )
    assert "pypi.org" not in result.stderr.lower()
    assert not re.search(r"(?<!uv )pip install", result.stderr), (
        "the guidance must recommend 'uv python install', never a bare pip install"
    )
