"""Behaviour tests for `setup-venv.sh`, the idempotent preparer of
`app/.venv` invoked from the `postprovision` azd hook.

Every test drives the real script against a fake `uv` on PATH (never a real
network install), so these prove the script's actual call contract: it
requires `uv` with no pip fallback, it fails fast and actionably at each
step, and re-running it is safe.
"""
import os
import stat
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "setup-venv.sh"
LAB_ROOT = Path(__file__).parents[2]
REQUIREMENTS_DEV = LAB_ROOT / "app" / "requirements-dev.txt"


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_fake_uv(bin_dir: Path, log_path: Path, venv_exit: int = 0, pip_exit: int = 0, pillow_importable: bool = True):
    """A fake `uv` that logs every invocation and creates just enough of a
    venv (`bin/python` as a real, runnable interpreter) that the script's
    own Pillow-import check can run against it."""
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


def _run(bin_dir: Path, workdir: Path, extra_path: bool = True):
    env = dict(os.environ)
    if extra_path:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    else:
        # Simulate `uv` genuinely absent: a PATH with no bin_dir at all,
        # not just an empty one, so no fake (or real, developer-machine)
        # `uv` is reachable.
        env["PATH"] = "/usr/bin:/bin"
    return subprocess.run(
        [str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(workdir),
    )


def test_fails_actionably_with_no_pip_fallback_when_uv_is_missing(tmp_path):
    result = _run(tmp_path / "bin-unused", tmp_path, extra_path=False)

    assert result.returncode != 0
    assert "uv" in result.stderr
    assert "install uv" in result.stderr.lower() or "uv is required" in result.stderr
    assert "azd hooks run postprovision" in result.stderr
    assert "already deployed" in result.stderr


def test_succeeds_and_calls_uv_venv_then_uv_pip_install_with_requirements_dev(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path)

    result = _run(bin_dir, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = log_path.read_text()
    assert "venv --python" in calls
    assert "--allow-existing" in calls
    assert ".venv" in calls
    assert "pip install --python" in calls
    assert "requirements-dev.txt" in calls


def test_never_falls_back_to_a_bare_pip_binary(tmp_path):
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

    result = _run(bin_dir, tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not bare_pip_log.exists(), "setup-venv.sh must never invoke a bare pip"


def test_is_idempotent_across_repeated_runs(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path)

    first = _run(bin_dir, tmp_path)
    second = _run(bin_dir, tmp_path)

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr


def test_fails_actionably_when_uv_venv_creation_fails(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, venv_exit=1)

    result = _run(bin_dir, tmp_path)

    assert result.returncode != 0
    assert "azd hooks run postprovision" in result.stderr
    assert "already deployed" in result.stderr
    assert "pip install" not in log_path.read_text()


def test_fails_actionably_when_uv_pip_install_fails(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pip_exit=1)

    result = _run(bin_dir, tmp_path)

    assert result.returncode != 0
    assert "azd hooks run postprovision" in result.stderr
    assert "already deployed" in result.stderr
    assert "proxy" in result.stderr


def test_fails_actionably_when_pillow_is_still_not_importable(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv-calls.log"
    _write_fake_uv(bin_dir, log_path, pillow_importable=False)

    result = _run(bin_dir, tmp_path)

    assert result.returncode != 0
    assert "Pillow" in result.stderr
    assert "azd hooks run postprovision" in result.stderr


def test_installs_the_labs_real_requirements_dev_file():
    assert REQUIREMENTS_DEV.is_file()
    assert "Pillow" in REQUIREMENTS_DEV.read_text()


def test_script_never_executes_a_bare_pip_or_pip3_command():
    """Every executable (non-comment, non-message) shell command line that
    starts with `pip`/`pip3` would be a fallback outside `uv`; only lines
    that start with `uv` are allowed to reach a `pip` subcommand."""
    import re

    for line in SCRIPT.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "echo")):
            continue
        if re.match(r"^(if\s+!\s+)?pip3?\b", stripped):
            raise AssertionError(("bare pip invocation found", stripped))
