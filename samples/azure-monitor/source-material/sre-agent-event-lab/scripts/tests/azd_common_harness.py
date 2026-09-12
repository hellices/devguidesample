"""Shared test harness for exercising `common.sh` against a fake `azd`/`az`.

Not a test module itself (no `test_` prefix) -- imported by test_common.py and
test_azd_env.py so both suites drive `common.sh` through the same fake-CLI
harness instead of duplicating it. The fake `azd` reproduces azd 1.29.0's
real contract (see `azd_fake.py`): `ERROR:` text on **stdout**, failure only
in the exit status, and project discovery from `--cwd` or the process
working directory.
"""
import os
import shutil
import subprocess
from pathlib import Path

from azd_fake import write_azd_stub, write_executable


COMMON_SH = Path(__file__).parents[1] / "common.sh"
LAB_ROOT = Path(__file__).parents[2]
BASH = shutil.which("bash") or "/bin/bash"
# Sourcing common.sh needs `dirname`; every other command it runs at source
# time is a Bash builtin. Restricted-PATH runs symlink just this one binary
# so a "required command" test controls exactly which CLIs are reachable.
SOURCE_TIME_BINARIES = ("dirname",)
REQUIRED_COMMANDS = ("az", "azd", "jq", "curl", "python3")


def _write_az_stub(bin_dir, az_script=None):
    """A fake `az` used only so `require_commands`/`command -v az` succeed.

    `az_script` lets a test override behaviour (e.g. `az account show`,
    `az group show`) by supplying the body of the stub script.
    """
    body = az_script if az_script is not None else "exit 0\n"
    write_executable(bin_dir / "az", "#!/usr/bin/env bash\n" + body)


def _write_trivial_stub(bin_dir, name):
    write_executable(bin_dir / name, "#!/usr/bin/env bash\nexit 0\n")


def run_common(
    tmp_path,
    env,
    azd_values,
    command,
    az_script=None,
    cwd=None,
    missing_key_mode="azd_1_29",
    available_commands=None,
    azd_log=None,
):
    """Source common.sh in a throwaway bash process and run `command`.

    `env` is the *only* process environment passed through (plus PATH),
    so tests control explicit-environment precedence precisely. `azd_values`
    populates the fake `azd env get-value` responses. `cwd` runs the shell
    from another directory (the default, `tmp_path`, deliberately holds no
    `azure.yaml`, so a lookup that does not pin the lab's project root
    fails exactly as the real azd would). `available_commands`, when given,
    restricts PATH to those fakes so a preflight test can drop one CLI.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)

    if available_commands is None:
        selected = REQUIRED_COMMANDS
        path_value = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    else:
        selected = tuple(available_commands)
        for binary in SOURCE_TIME_BINARIES:
            resolved = shutil.which(binary)
            link = bin_dir / binary
            if resolved and not link.exists():
                os.symlink(resolved, link)
        path_value = str(bin_dir)

    for name in selected:
        if name == "azd":
            write_azd_stub(bin_dir, azd_values, missing_key_mode, azd_log)
        elif name == "az":
            _write_az_stub(bin_dir, az_script)
        else:
            _write_trivial_stub(bin_dir, name)

    full_env = {
        "PATH": path_value,
        "HOME": os.environ.get("HOME", str(tmp_path)),
    }
    full_env.update(env)

    harness = f'source "{COMMON_SH}"\n{command}\n'
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        env=full_env,
        cwd=str(cwd) if cwd is not None else str(tmp_path),
    )
