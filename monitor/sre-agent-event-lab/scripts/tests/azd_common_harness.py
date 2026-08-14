"""Shared test harness for exercising `common.sh` against a fake `azd`/`az`.

Not a test module itself (no `test_` prefix) -- imported by test_common.py and
test_azd_env.py so both suites drive `common.sh` through the same fake-CLI
harness instead of duplicating it.
"""
import os
import shutil
import stat
import subprocess
from pathlib import Path


COMMON_SH = Path(__file__).parents[1] / "common.sh"
BASH = shutil.which("bash") or "/bin/bash"


def _make_executable(path, content):
    path.write_text(content)
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_azd_stub(bin_dir, azd_values):
    """A fake `azd` that only understands `env get-value NAME`.

    Returns the mapped value for a known name with exit 0, and -- matching
    the real `azd`'s behaviour for a value that was never set -- prints
    nothing and exits non-zero for an unknown name.
    """
    lines = [
        "#!/usr/bin/env bash",
        'if [[ "${1:-}" == "env" && "${2:-}" == "get-value" ]]; then',
        '  case "${3:-}" in',
    ]
    for name, value in azd_values.items():
        escaped = value.replace("'", "'\\''")
        lines.append(f"    {name}) printf '%s' '{escaped}'; exit 0 ;;")
    lines.append('    *) exit 1 ;;')
    lines.append("  esac")
    lines.append("fi")
    lines.append('echo "azd stub: unsupported invocation: $*" >&2')
    lines.append("exit 1")
    _make_executable(bin_dir / "azd", "\n".join(lines) + "\n")


def _write_az_stub(bin_dir, az_script=None):
    """A fake `az` used only so `require_commands`/`command -v az` succeed.

    `az_script` lets a test override behaviour (e.g. `az account show`,
    `az group show`) by supplying the body of the stub script.
    """
    body = az_script if az_script is not None else "exit 0\n"
    _make_executable(bin_dir / "az", "#!/usr/bin/env bash\n" + body)


def run_common(tmp_path, env, azd_values, command, az_script=None):
    """Source common.sh in a throwaway bash process and run `command`.

    `env` is the *only* process environment passed through (plus PATH),
    so tests control explicit-environment precedence precisely. `azd_values`
    populates the fake `azd env get-value` responses.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _write_azd_stub(bin_dir, azd_values)
    _write_az_stub(bin_dir, az_script)

    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": os.environ.get("HOME", str(tmp_path)),
    }
    full_env.update(env)

    harness = f'source "{COMMON_SH}"\n{command}\n'
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=full_env,
    )
