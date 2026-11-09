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
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(bin_dir.parent),
        "AZURE_ENV_NAME": "unit",
        "LAB_STATE_ROOT": str(bin_dir.parent / "state"),
    }
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
        'if [[ "$1 $2" == "env get-value" && "${@: -1}" == "AZURE_SUBSCRIPTION_ID" ]]; then '
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
        'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
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


def test_hooks_pin_azd_env_to_the_running_environment():
    for path in SCRIPTS.glob("*.sh"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith(("azd env set", "azd env get-value")) or "$(azd env get-value" in stripped:
                raise AssertionError(f"{path.name}: use azd_env so -e <env> is honored: {stripped}")


def test_preprovision_writes_to_the_requested_environment(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'case "$1 $2" in "account show") '
          'if [[ "$*" == *user.type* ]]; then echo user; else echo 00000000-0000-0000-0000-000000000000; fi;; '
          '"provider show") echo Registered;; "ad signed-in-user") echo 33333333-3333-3333-3333-333333333333;; esac')
    write("azd", 'if [[ "$1 $2" == "env get-value" && "${@: -1}" == "AZURE_SUBSCRIPTION_ID" ]]; then '
          "echo 00000000-0000-0000-0000-000000000000; exit 0; fi; "
          'if [[ "$1 $2" == "env get-value" ]]; then exit 1; fi; exit 0')
    write("curl", "echo 203.0.113.10")
    write("python3", "exit 0")
    write("ssh-keygen", 'for a; do last="$a"; done; echo "ssh-ed25519 AAAA test" > "$last.pub"; touch "$last"')

    result = _run("azd-configure.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    sets = [line for line in log.read_text().splitlines() if line.startswith("azd env set")]
    assert sets and all(line.startswith("azd env set -e unit ") for line in sets)
    assert "azd env set -e unit OPERATOR_EGRESS_CIDR 203.0.113.10/32" in log.read_text()


def test_postdown_verifies_the_group_recorded_by_predown(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write(
        "azd",
        'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
        "AZURE_RESOURCE_GROUP) echo rg-example;; *) exit 1;; esac",
    )
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0

    # azd down has cleared provision outputs by the time postdown runs.
    write(
        "azd",
        'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; *) exit 1;; esac',
    )
    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    assert "group exists --subscription 00000000-0000-0000-0000-000000000000 -n rg-example" in log.read_text()


def test_postdeploy_never_scales_the_running_consumer(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "account show" ]]; then echo 00000000-0000-0000-0000-000000000000; fi')
    write("azd", 'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
                 '*) echo value;; esac')
    write("kubectl", 'if [[ "$*" == *" apply "* ]]; then cat >/dev/null; fi')

    result = _run("azd-deploy.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    assert "scale deploy/eventhubs-slow-consumer" not in log.read_text()
    manifest = (LAB_ROOT / "k8s" / "workloads.yaml").read_text().split("---")
    consumer = next(doc for doc in manifest if "name: eventhubs-slow-consumer\n  namespace" in doc and "kind: Deployment" in doc)
    producer = next(doc for doc in manifest if "name: eventhubs-producer\n  namespace" in doc and "kind: Deployment" in doc)
    assert "replicas:" not in consumer
    assert "replicas: 0" in producer
