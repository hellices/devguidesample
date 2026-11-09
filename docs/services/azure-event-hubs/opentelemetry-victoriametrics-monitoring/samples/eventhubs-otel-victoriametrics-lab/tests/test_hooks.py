import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).parents[1]
SCRIPTS = LAB_ROOT / "scripts"
HOOKS = (
    "azd-configure.sh",
    "azd-postprovision.sh",
    "azd-deploy.sh",
    "cleanup-external.sh",
    "verify-cleanup.sh",
)


def _joined_commands(text: str) -> list[str]:
    """Join backslash-continued shell lines so multi-line az calls are checked as one command."""
    return re.sub(r"\\\n\s*", " ", text).splitlines()


def test_hooks_exist_and_are_executable():
    for name in (*HOOKS, "run-scenario.sh", "vm-query.sh"):
        path = SCRIPTS / name
        assert path.is_file(), name
        assert os.access(path, os.X_OK), name


def test_azure_cli_calls_pin_the_subscription():
    for path in SCRIPTS.glob("*.sh"):
        for line in _joined_commands(path.read_text()):
            match = re.search(r"(?:^|\$\(|\s)az\s+([a-z-]+(?:\s+[a-z-]+)?)", line)
            if not match or line.lstrip().startswith(("#", "require_commands")):
                continue
            command = match.group(1)
            if command.startswith(("ad ", "account show")) and "--subscription" not in line:
                # Entra ID lookups and the active-subscription guard are tenant scoped.
                assert command.startswith(("ad signed-in-user", "ad sp", "account show")), line
                continue
            if 'az vm run-command invoke "${args[@]}"' in line:
                continue
            assert "--subscription" in line, f"{path.name}: {line.strip()}"


def test_no_script_creates_a_dedicated_cluster():
    text = "\n".join(p.read_text() for p in LAB_ROOT.rglob("*.sh"))
    assert "eventhubs cluster create" not in text
    assert "Microsoft.EventHub/clusters" not in text


def test_kubectl_uses_lab_kubeconfig_only():
    for path in SCRIPTS.glob("*.sh"):
        for line in path.read_text().splitlines():
            if re.match(r"\s*kubectl\s", line):
                assert "--kubeconfig" in line, f"{path.name}: {line.strip()}"


@pytest.fixture
def fake_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"

    def write(name: str, body: str) -> None:
        path = bin_dir / name
        path.write_text(f"#!/usr/bin/env bash\necho \"{name} $*\" >> {log}\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    for name in ("curl", "openssl", "ssh-keygen", "kubectl", "kubelogin", "helm"):
        write(name, "exit 0")
    return bin_dir, log, write


def _run(script: str, bin_dir: Path, *args: str) -> subprocess.CompletedProcess:
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(bin_dir.parent), "AZURE_ENV_NAME": "unit"}
    return subprocess.run(
        ["bash", str(SCRIPTS / script), *args],
        cwd=bin_dir.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_preprovision_stops_before_mutation_on_subscription_mismatch(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "account show" ]]; then echo 99999999-0000-0000-0000-000000000000; fi')
    write(
        "azd",
        'if [[ "$1 $2" == "env get-value" && "$3" == "AZURE_SUBSCRIPTION_ID" ]]; then '
        "echo 00000000-0000-0000-0000-000000000000; exit 0; fi; exit 1",
    )
    write("python3", "exit 0")

    result = _run("azd-configure.sh", bin_dir)

    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert "azd env set" not in log.read_text()


def test_cleanup_is_idempotent_when_resource_group_is_absent(fake_bin, tmp_path):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write(
        "azd",
        'case "$3" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
        "AZURE_RESOURCE_GROUP) echo rg-example;; *) exit 1;; esac",
    )

    first = _run("cleanup-external.sh", bin_dir, "--yes")
    second = _run("cleanup-external.sh", bin_dir, "--yes")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "federated-credential delete" not in log.read_text()


def test_cleanup_requires_confirmation(fake_bin):
    bin_dir, _, write = fake_bin
    write("az", "exit 0")
    write("azd", "exit 1")

    assert _run("cleanup-external.sh", bin_dir).returncode != 0
