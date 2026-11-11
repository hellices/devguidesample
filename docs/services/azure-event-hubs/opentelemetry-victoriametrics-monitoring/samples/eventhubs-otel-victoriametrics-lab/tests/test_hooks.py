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
    for name in (*HOOKS, "run-scenario.sh", "vm-query.sh", "managed-grafana.sh"):
        path = SCRIPTS / name
        assert path.is_file(), name
        assert os.access(path, os.X_OK), name


AZ_CALL = re.compile(r"(?:^|\$\(|[\s;|&(])az\s+([a-z-]+(?:\s+[a-z-]+)?)")
# A lone "&" (background) ends a command too; "&&", "2>&1" and "&>" are not lone ampersands.
COMMAND_END = re.compile(r"\)|;|&&|\||(?<![&>])&(?![&>])")


def _strip_comment(line: str) -> str:
    """The line without a shell comment: an unquoted # at the start of a word ends the command."""
    quote, escaped = None, False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            return line[:index]
    return line


def _az_calls(line: str) -> list[tuple[str, str]]:
    """Each az invocation on a line with the text up to its own command boundary."""
    line = _strip_comment(line)
    calls = []
    for match in AZ_CALL.finditer(line):
        rest = line[match.end():]
        end = COMMAND_END.search(rest)
        calls.append((match.group(1), match.group(0) + (rest[: end.start()] if end else rest)))
    return calls


def test_az_call_segments_do_not_borrow_options_from_the_next_command():
    for separator in (";", " &", " &&", " |"):
        calls = _az_calls(f'az group delete -n "$rg"{separator} az group show -n "$rg" --subscription "$sub"')
        assert [("--subscription" in segment) for _, segment in calls] == [False, True], separator
    # Redirections keep the rest of the command in the same segment.
    [(_, segment)] = _az_calls('az group show -n "$rg" 2>&1 --subscription "$sub"')
    assert "--subscription" in segment
    # A commented-out option is not passed to az; a quoted or ${#...} hash is not a comment.
    [(_, segment)] = _az_calls('az group delete -n "$rg" # --subscription "$sub"')
    assert "--subscription" not in segment
    [(_, segment)] = _az_calls('az group show -n "a#b" --query "x" --subscription "${#sub}"')
    assert "--subscription" in segment
    [(_, segment)] = _az_calls('az group show -n "a\\" #b" --subscription "$sub"')
    assert "--subscription" in segment


def test_azure_cli_calls_pin_the_subscription():
    for path in SCRIPTS.glob("*.sh"):
        for line in _joined_commands(path.read_text()):
            if line.lstrip().startswith(("#", "require_commands")):
                continue
            for command, segment in _az_calls(line):
                if command.startswith("extension ") and "--subscription" not in segment:
                    continue  # installs a local CLI extension; no Azure resource is touched
                if command.startswith(("ad ", "account ")) and "--subscription" not in segment:
                    # Entra ID lookups, the active-subscription guard and token reads are tenant scoped.
                    assert command.startswith(
                        ("ad signed-in-user", "account show", "account get-access-token")
                    ), line
                    continue
                if 'az vm run-command invoke "${args[@]}"' in segment:
                    # The array is expanded at run time; test_gateway_run_pins_the_subscription executes it.
                    continue
                assert "--subscription" in segment, f"{path.name}: {segment.strip()}"


def test_no_script_creates_a_dedicated_cluster():
    for path in LAB_ROOT.rglob("*.sh"):
        for line in _joined_commands(path.read_text()):
            normalized = " ".join(line.split())
            assert "eventhubs cluster create" not in normalized, f"{path.name}: {line.strip()}"
            assert "Microsoft.EventHub/clusters" not in normalized, f"{path.name}: {line.strip()}"


def test_kubectl_uses_lab_kubeconfig_only():
    # Every kubectl invocation, including inside $(...) and pipelines, must pin the lab kubeconfig.
    for path in SCRIPTS.glob("*.sh"):
        for line in _joined_commands(path.read_text()):
            if line.lstrip().startswith(("#", "require_commands")):
                continue
            for match in re.finditer(r"(?:^|[\s;|&(])kubectl\s([^;|&)]*)", _strip_comment(line)):
                assert "--kubeconfig" in match.group(1), f"{path.name}: {line.strip()}"


def test_kubectl_check_ignores_a_commented_out_kubeconfig():
    line = _strip_comment('kubectl get pods # --kubeconfig "$cfg"')
    [args] = re.findall(r"(?:^|[\s;|&(])kubectl\s([^;|&)]*)", line)
    assert "--kubeconfig" not in args


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
    # Only the read-only active-subscription lookup may run before the mismatch check.
    write("az", 'if [[ "$1 $2" == "account show" ]]; then echo 99999999-0000-0000-0000-000000000000; exit 0; fi; exit 97')
    write(
        "azd",
        'if [[ "$1 $2" == "env get-value" && "${@: -1}" == "AZURE_SUBSCRIPTION_ID" ]]; then '
        "echo 00000000-0000-0000-0000-000000000000; exit 0; fi; exit 1",
    )
    write("python3", "exit 0")

    result = _run("azd-configure.sh", bin_dir)

    assert result.returncode != 0
    assert "does not match" in result.stderr
    calls = log.read_text().splitlines()
    assert "azd env set" not in "\n".join(calls)
    assert [c for c in calls if c.startswith("az ")] == ["az account show --query id -o tsv"]


def test_cleanup_is_idempotent_when_resource_group_is_absent(fake_bin, tmp_path):
    bin_dir, log, write = fake_bin
    # Only the existence lookup is allowed; any other az call (including deletes) fails the run.
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; exit 0; fi; '
                'echo "unexpected az call: $*" >&2; exit 97')
    write(
        "azd",
        'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
        "AZURE_RESOURCE_GROUP) echo rg-example;; *) exit 1;; esac",
    )

    first = _run("cleanup-external.sh", bin_dir, "--yes")
    second = _run("cleanup-external.sh", bin_dir, "--yes")

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    az_calls = [c for c in log.read_text().splitlines() if c.startswith("az ")]
    assert az_calls == ["az group exists --subscription 00000000-0000-0000-0000-000000000000 -n rg-example -o tsv"] * 2


AZD_CLEANUP_ENV = (
    'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
    "AZURE_RESOURCE_GROUP) echo rg-example;; PRODUCER_CLIENT_ID) echo client-producer;; "
    "CONSUMER_CLIENT_ID) echo client-consumer;; *) exit 1;; esac"
)
# Exactly the lookups and deletes cleanup may make; anything else (for example deleting an
# identity, or touching an unrelated identity) is rejected with exit 97.
AZ_CLEANUP = (
    'args="$*"; SUB=00000000-0000-0000-0000-000000000000\n'
    'case "$args" in\n'
    # Every allowed call is matched in full, including the exact subscription and resource group.
    '  "group exists --subscription $SUB -n rg-example -o tsv") echo true;;\n'
    '  "identity list --subscription $SUB -g rg-example --query [?clientId==\'client-producer\'].name | [0] -o tsv") echo id-producer;;\n'
    '  "identity list --subscription $SUB -g rg-example --query [?clientId==\'client-consumer\'].name | [0] -o tsv") echo id-consumer;;\n'
    '  "identity federated-credential list --subscription $SUB -g rg-example --identity-name id-producer --query [?name==\'aks-eventhubs-producer\'].name -o tsv") echo aks-eventhubs-producer;;\n'
    '  "identity federated-credential list --subscription $SUB -g rg-example --identity-name id-consumer --query [?name==\'aks-eventhubs-slow-consumer\'].name -o tsv") echo aks-eventhubs-slow-consumer;;\n'
    '  "identity federated-credential delete --subscription $SUB -g rg-example --identity-name id-producer --name aks-eventhubs-producer --yes --output none") ;;\n'
    '  "identity federated-credential delete --subscription $SUB -g rg-example --identity-name id-consumer --name aks-eventhubs-slow-consumer --yes --output none") ;;\n'
    '  *) echo "unexpected az call: $args" >&2; exit 97;;\n'
    'esac'
)


@pytest.mark.parametrize("failing", ["group exists", "identity list", "identity federated-credential list"])
def test_cleanup_fails_when_an_azure_lookup_fails(fake_bin, failing):
    bin_dir, log, write = fake_bin
    write("az", f'if [[ "$*" == "{failing}"* ]]; then echo "auth expired" >&2; exit 1; fi\n' + AZ_CLEANUP)
    write("azd", AZD_CLEANUP_ENV)

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode != 0
    assert "external state removed" not in result.stderr + result.stdout


def test_cleanup_deletes_only_the_lab_credentials(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", AZ_CLEANUP)
    write("azd", AZD_CLEANUP_ENV)

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode == 0, result.stderr
    mutations = [c for c in log.read_text().splitlines()
                 if c.startswith("az ") and not any(k in c for k in (" exists ", " list "))]
    assert len(mutations) == 2, mutations
    pairs = sorted((c.split("--identity-name ", 1)[1].split()[0], c.split("--name ", 1)[1].split()[0])
                   for c in mutations)
    assert pairs == [("id-consumer", "aks-eventhubs-slow-consumer"), ("id-producer", "aks-eventhubs-producer")]


def test_cleanup_requires_confirmation(fake_bin):
    bin_dir, log, write = fake_bin
    # The environment is fully available, so only the missing --yes can stop the run.
    write("az", AZ_CLEANUP)
    write("azd", AZD_CLEANUP_ENV)

    result = _run("cleanup-external.sh", bin_dir)

    assert result.returncode != 0
    assert "pass --yes to confirm cleanup" in result.stderr
    calls = log.read_text().splitlines() if log.exists() else []
    assert not [c for c in calls if c.startswith("az ")]


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
    write("openssl", 'if [[ "$1" == rand ]]; then echo "R3ZhbGlkUGFzc3dvcmRGb3JUZXN0c09ubHk="; fi')
    write("ssh-keygen", 'for a; do last="$a"; done; echo "ssh-ed25519 AAAA test" > "$last.pub"; touch "$last"')

    result = _run("azd-configure.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    sets = [line for line in log.read_text().splitlines() if line.startswith("azd env set")]
    assert sets and all(line.startswith("azd env set -e unit ") for line in sets)
    assert "azd env set -e unit OPERATOR_EGRESS_CIDR 203.0.113.10/32" in log.read_text()
    assert "azd env set -e unit GATEWAY_ADMIN_SSH_PUBLIC_KEY ssh-ed25519 AAAA test" in log.read_text()
    password = [l for l in sets if " GRAFANA_ADMIN_PASSWORD " in l]
    assert len(password) == 1 and len(password[0].rsplit(" ", 1)[1]) >= 16


@pytest.mark.parametrize("broken", ["password", "ssh_key"])
def test_preprovision_never_writes_an_empty_hook_value(fake_bin, broken):
    bin_dir, log, write = fake_bin
    write("az", 'case "$1 $2" in "account show") '
          'if [[ "$*" == *user.type* ]]; then echo user; else echo 00000000-0000-0000-0000-000000000000; fi;; '
          '"provider show") echo Registered;; "ad signed-in-user") echo 33333333-3333-3333-3333-333333333333;; esac')
    write("azd", 'if [[ "$1 $2" == "env get-value" && "${@: -1}" == "AZURE_SUBSCRIPTION_ID" ]]; then '
          "echo 00000000-0000-0000-0000-000000000000; exit 0; fi; "
          'if [[ "$1 $2" == "env get-value" ]]; then exit 1; fi; exit 0')
    write("curl", "echo 203.0.113.10")
    write("python3", "exit 0")
    # Tools that "succeed" but produce nothing usable.
    write("openssl", "exit 0" if broken == "password" else 'echo "R3ZhbGlkUGFzc3dvcmRGb3JUZXN0c09ubHk="')
    write("ssh-keygen", 'for a; do last="$a"; done; '
          + (': > "$last.pub"' if broken == "ssh_key" else 'echo "ssh-ed25519 AAAA test" > "$last.pub"')
          + '; touch "$last"')

    result = _run("azd-configure.sh", bin_dir)

    assert result.returncode != 0
    name = "GRAFANA_ADMIN_PASSWORD" if broken == "password" else "GATEWAY_ADMIN_SSH_PUBLIC_KEY"
    assert f" {name} " not in log.read_text()


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


def test_postdown_rejects_a_group_other_than_the_recorded_one(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write("azd", AZD_CLEANUP_ENV)
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0

    write("azd", AZD_CLEANUP_ENV.replace("rg-example", "rg-other"))
    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode != 0
    assert "predown recorded rg-example" in result.stderr
    assert "-n rg-other" not in log.read_text()


def test_postdeploy_never_scales_the_running_consumer(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "account show" ]]; then echo 00000000-0000-0000-0000-000000000000; fi')
    write("azd", 'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
                 '*) echo value;; esac')
    # Only the two expected kubectl calls succeed; scale, patch or anything else fails the run.
    write("kubectl", (
        'args="$*"\n'
        'case "${args#--kubeconfig * }" in\n'
        '  "apply -f -") cat >/dev/null;;\n'
        '  "rollout status deploy/eventhubs-slow-consumer -n eventhubs-observability --timeout 300s") ;;\n'
        '  *) echo "unexpected kubectl call: $*" >&2; exit 97;;\n'
        'esac'
    ))

    result = _run("azd-deploy.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    kubectl = [c.split(" ", 3)[3] for c in log.read_text().splitlines() if c.startswith("kubectl ")]
    assert kubectl == [
        "apply -f -",
        "rollout status deploy/eventhubs-slow-consumer -n eventhubs-observability --timeout 300s",
    ]
    manifest = (LAB_ROOT / "k8s" / "workloads.yaml").read_text().split("---")
    consumer = next(doc for doc in manifest if "name: eventhubs-slow-consumer\n  namespace" in doc and "kind: Deployment" in doc)
    producer = next(doc for doc in manifest if "name: eventhubs-producer\n  namespace" in doc and "kind: Deployment" in doc)
    assert "replicas:" not in consumer
    assert "replicas: 0" in producer


def test_vm_query_refuses_a_port_served_for_another_environment(fake_bin, tmp_path):
    import http.server
    import threading

    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bin_dir, log, write = fake_bin
    write("azd", "exit 1")
    write("curl", 'exec /usr/bin/curl "$@"')
    try:
        env_port = str(server.server_address[1])
        result = subprocess.run(
            ["bash", str(SCRIPTS / "vm-query.sh"), "start"],
            cwd=tmp_path,
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "AZURE_ENV_NAME": "unit",
                 "LAB_STATE_ROOT": str(tmp_path / "state"), "VM_LOCAL_PORT": env_port},
            capture_output=True, text=True, timeout=30,
        )
    finally:
        server.shutdown()

    assert result.returncode != 0
    assert "already serves another VictoriaMetrics" in result.stderr
    assert "port-forward" not in log.read_text()


def test_each_environment_gets_its_own_default_port(fake_bin):
    bin_dir, _, write = fake_bin
    write("azd", "exit 1")
    ports = set()
    for env_name in ("ehotel-lab1", "ehotel-lab2", "ehotel-lab3"):
        result = subprocess.run(
            ["bash", str(SCRIPTS / "vm-query.sh"), "port"],
            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(bin_dir.parent), "AZURE_ENV_NAME": env_name,
                 "LAB_STATE_ROOT": str(bin_dir.parent / "state")},
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        ports.add(int(result.stdout.strip()))
    assert len(ports) == 3
    assert all(18428 <= port < 18928 for port in ports)


def _free_ports(count: int) -> list[int]:
    import contextlib
    import socket

    with contextlib.ExitStack() as stack:
        # Hold every socket until all are bound so the ports are distinct.
        probes = [stack.enter_context(socket.socket()) for _ in range(count)]
        for probe in probes:
            probe.bind(("127.0.0.1", 0))
        return [probe.getsockname()[1] for probe in probes]


def _port_closed(port: int) -> bool:
    import socket
    import time

    time.sleep(1)
    with socket.socket() as again:
        # A surviving forward would still accept connections on the port.
        return again.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture
def fake_forward(fake_bin, tmp_path):
    bin_dir, _, write = fake_bin
    write("azd", "exit 1")
    write("curl", 'exec /usr/bin/curl "$@"')
    # The fake kubectl stays alive as "kubectl ... port-forward ... <port>:8428" (like the real
    # binary) and serves /health on the forwarded port until it is terminated.
    server = (
        "import http.server as h,sys\n"
        "class H(h.BaseHTTPRequestHandler):\n"
        " def do_GET(s): s.send_response(200); s.end_headers()\n"
        " def log_message(s,*a): pass\n"
        "h.HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()"
    )
    (tmp_path / "server.py").write_text(server)
    write("kubectl", (
        'for a; do case "$a" in *:8428) p="${a%%:*}";; esac; done; '
        f'/usr/bin/python3 {tmp_path / "server.py"} "$p" & child=$!; '
        "trap 'kill $child' TERM; wait $child"
    ))

    def run(action: str, port: int) -> subprocess.CompletedProcess:
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "AZURE_ENV_NAME": "unit",
               "LAB_STATE_ROOT": str(tmp_path / "state"), "VM_LOCAL_PORT": str(port)}
        return subprocess.run(["bash", str(SCRIPTS / "vm-query.sh"), action], env=env,
                              capture_output=True, text=True, timeout=60)

    return run


def test_vm_query_stop_terminates_the_forward_it_started(fake_forward):
    [port] = _free_ports(1)

    assert fake_forward("start", port).returncode == 0
    assert fake_forward("start", port).returncode == 0  # reuses its own healthy forward
    assert fake_forward("stop", port).returncode == 0
    assert _port_closed(port)


def test_vm_query_cleans_up_a_forward_started_on_a_previous_port(fake_forward):
    old, new = _free_ports(2)

    assert fake_forward("start", old).returncode == 0
    assert fake_forward("start", new).returncode == 0
    assert _port_closed(old)
    assert fake_forward("stop", old).returncode == 0  # stop uses the recorded port, not the current one
    assert _port_closed(new)


def test_evidence_is_kept_per_environment():
    text = (SCRIPTS / "lib.sh").read_text()
    assert 'local dir="$LAB_ROOT/evidence/$(env_value AZURE_ENV_NAME)"' in text


def _gateway_bundle(profile="default"):
    import io
    import tarfile

    files = {
        "./.env": ("GATEWAY_CLIENT_ID=c\nKEY_VAULT_NAME=kv\nACR_NAME=acr\n"
                   f"GATEWAY_PUBLIC_IP=1.2.3.4\nCOMPOSE_PROFILE={profile}\n"),
        "./compose.yaml": "services: {}\n",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            bundle.addfile(info, io.BytesIO(data))
    return buffer


def _bootstrap_tools(write, docker="exit 0"):
    for name in ("cloud-init", "chown", "curl", "sleep"):
        write(name, "exit 0")
    write("docker", docker)
    write("az", 'if [[ "$1 $2" == "keyvault secret" ]]; then echo pw; fi')
    write("openssl", (
        'case "$*" in\n'
        '  req*) echo "cert 1.2.3.4 pub=k1" >tls/grafana.crt; echo k1 >tls/grafana.key;;\n'
        '  "x509 -in tls/grafana.crt -noout -pubkey") grep -o "pub=[a-z0-9]*" tls/grafana.crt | cut -d= -f2;;\n'
        '  "pkey -in tls/grafana.key -pubout") [ -s tls/grafana.key ] && cat tls/grafana.key || exit 1;;\n'
        '  *-checkend*) exit 0;;\n'
        '  *subjectAltName*) printf "X509v3 Subject Alternative Name: \\n    IP Address:1.2.3.4\\n";;\n'
        'esac'
    ))


BUNDLE_MARKER = ".eventhubs-observability-bundle"


def _previous_bundle(app):
    """An APP_DIR that an earlier bootstrap installed (it always leaves the bundle marker)."""
    app.mkdir(parents=True, exist_ok=True)
    (app / BUNDLE_MARKER).touch()
    return app


def _run_bootstrap(bin_dir, tmp_path, app, profile="default"):
    import base64

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "APP_DIR": str(app),
           "BUNDLE_B64": base64.b64encode(_gateway_bundle(profile).getvalue()).decode()}
    return subprocess.run(["bash", str(LAB_ROOT / "gateway" / "bootstrap.sh")], env=env,
                          capture_output=True, text=True, timeout=60)


def test_gateway_bundle_replaces_stale_files_but_keeps_runtime_state(fake_bin, tmp_path):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    app = _previous_bundle(tmp_path / "app")
    (app / "grafana" / "provisioning").mkdir(parents=True)
    (app / "grafana" / "provisioning" / "removed.yaml").write_text("old")
    (app / "old-compose.override.yaml").write_text("old")
    (app / "tls").mkdir()
    (app / "tls" / "grafana.crt").write_text("cert 1.2.3.4 pub=k1")
    (app / "tls" / "grafana.key").write_text("k1")

    result = _run_bootstrap(bin_dir, tmp_path, app)

    assert result.returncode == 0, result.stderr
    assert not (app / "old-compose.override.yaml").exists()
    assert not (app / "grafana").exists()
    assert (app / "compose.yaml").exists() and (app / ".env").exists()
    assert (app / "tls" / "grafana.key").read_text() == "k1"  # reused, not regenerated


def test_gateway_bundle_restores_the_previous_bundle_when_the_copy_fails(fake_bin, tmp_path):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    write("cp", "exit 1")  # e.g. the disk filled up while copying the new bundle
    app = _previous_bundle(tmp_path / "app")
    (app / "tls").mkdir()
    (app / "compose.yaml").write_text("previous")
    (app / ".env").write_text("previous")

    result = _run_bootstrap(bin_dir, tmp_path, app)

    assert result.returncode != 0
    assert "previous bundle restored" in result.stderr
    assert (app / "compose.yaml").read_text() == "previous" and (app / ".env").read_text() == "previous"
    assert (app / "tls").is_dir()
    assert not list(tmp_path.glob("app.previous.*"))


def test_gateway_bundle_restores_the_previous_bundle_when_an_entry_cannot_be_moved(fake_bin, tmp_path):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    app = _previous_bundle(tmp_path / "app")
    (app / "compose.yaml").write_text("previous")
    (app / "stale.yaml").write_text("old")
    # e.g. an immutable entry or a mount point: only this move fails.
    write("mv", f'case "$1" in {app}/stale.yaml) exit 1;; esac; exec /bin/mv "$@"')

    result = _run_bootstrap(bin_dir, tmp_path, app)

    assert result.returncode != 0
    assert "could not move" in result.stderr and "previous bundle restored" in result.stderr
    assert (app / "compose.yaml").read_text() == "previous" and (app / "stale.yaml").read_text() == "old"
    assert not list(tmp_path.glob("app.previous.*"))


def test_gateway_keeps_the_grafana_secret_when_key_vault_fails(fake_bin, tmp_path):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    write("az", 'if [[ "$1 $2" == "keyvault secret" ]]; then echo "throttled" >&2; exit 1; fi')
    app = _previous_bundle(tmp_path / "app")
    (app / "secrets").mkdir()
    (app / "secrets" / "grafana_admin_password").write_text("current")
    (app / "compose.yaml").write_text("previous")

    result = _run_bootstrap(bin_dir, tmp_path, app)

    assert result.returncode != 0
    assert "not a gateway bundle directory" not in result.stderr  # failed at Key Vault, not the guard
    assert (app / "secrets" / "grafana_admin_password").read_text() == "current"
    assert not list((app / "secrets").glob(".grafana_admin_password.*"))


def test_gateway_bootstrap_sets_home_for_run_command():
    text = (LAB_ROOT / "gateway" / "bootstrap.sh").read_text()
    # Without HOME, az writes .cache under a literal "None" directory in the bundle directory.
    assert text.index('export HOME="${HOME:-/root}"') < text.index("az login")


@pytest.mark.parametrize("app_dir", ["/", "/opt", "unrelated", "unrelated-with-tls"])
def test_gateway_bundle_refuses_a_directory_it_does_not_own(fake_bin, tmp_path, app_dir):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    if app_dir.startswith("unrelated"):
        app = tmp_path / "other-app"
        app.mkdir()
        (app / "data.db").write_text("keep")
        # Common runtime directory names alone do not prove the directory is this bundle's.
        if app_dir == "unrelated-with-tls":
            (app / "tls").mkdir()
            (app / "secrets").mkdir()
            (app / "compose.yaml").write_text("other")
        app_dir = str(app)

    result = _run_bootstrap(bin_dir, tmp_path, app_dir)

    assert result.returncode != 0
    assert "GATEWAY_STEP_FAILED" in result.stderr
    if app_dir.endswith("other-app"):
        assert (tmp_path / "other-app" / "data.db").read_text() == "keep"


@pytest.mark.parametrize("profile, pull", [
    ("default", "compose pull --quiet"),
    ("fallback", "compose --profile fallback pull --quiet"),
])
def test_gateway_pulls_the_fallback_image_only_for_the_fallback_profile(fake_bin, tmp_path, profile, pull):
    bin_dir, log, write = fake_bin
    _bootstrap_tools(write, docker=(
        'if [[ "$*" == *"ps --status running --services"* ]]; then '
        'printf "otel-collector\\ngrafana\\nazure-metrics-exporter\\n"; fi'
    ))

    result = _run_bootstrap(bin_dir, tmp_path, tmp_path / "app", profile=profile)

    assert result.returncode == 0, result.stderr
    pulls = [line for line in log.read_text().splitlines() if line.startswith("docker") and " pull " in f"{line} "]
    assert pulls == [f"docker {pull}"]


@pytest.mark.parametrize("running, ready", [
    ("otel-collector\ngrafana\nazure-metrics-exporter", True),
    ("otel-collector\ngrafana", False),  # the exporter exited right after `up -d`
])
def test_fallback_gateway_waits_for_the_exporter_container(fake_bin, tmp_path, running, ready):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write, docker=(
        f'if [[ "$*" == *"ps --status running --services"* ]]; then printf "{running}\\n"; fi'
    ))

    result = _run_bootstrap(bin_dir, tmp_path, tmp_path / "app", profile="fallback")

    assert ("GATEWAY_READY" in result.stdout) is ready
    assert (result.returncode == 0) is ready


@pytest.mark.parametrize("existing, key, renewed", [
    (None, None, True),                 # first bootstrap
    ("1.2.3.4", "k1", False),           # valid certificate and matching key are reused
    ("1.2.3.40", "k1", True),           # "1.2.3.4" must not match a SAN for 1.2.3.40
    ("expiring", "k1", True),           # expires within a day
    ("1.2.3.4", None, True),            # key file missing
    ("1.2.3.4", "k2", True),            # key belongs to another certificate
])
def test_gateway_restarts_grafana_only_after_renewing_its_certificate(fake_bin, tmp_path, existing, key, renewed):
    import base64
    import io
    import tarfile

    bin_dir, log, write = fake_bin
    app = tmp_path / "app"
    for name in ("cloud-init", "docker", "chown", "curl"):
        write(name, "exit 0")
    write("az", 'if [[ "$1 $2" == "keyvault secret" ]]; then echo pw; fi')
    # Fake openssl: SAN, expiry and public key answers come from marker content in the files;
    # a certificate carries "pub=<key>" and matches the key file holding that same name.
    write("openssl", (
        'case "$*" in\n'
        '  req*) echo "cert 1.2.3.4 pub=k1" >tls/grafana.crt; echo k1 >tls/grafana.key;;\n'
        '  "x509 -in tls/grafana.crt -noout -pubkey") grep -o "pub=[a-z0-9]*" tls/grafana.crt | cut -d= -f2;;\n'
        '  "pkey -in tls/grafana.key -pubout") [ -s tls/grafana.key ] && cat tls/grafana.key || exit 1;;\n'
        '  *-checkend*) grep -q expiring tls/grafana.crt && exit 1; exit 0;;\n'
        '  *subjectAltName*) printf "X509v3 Subject Alternative Name: \\n    IP Address:%s\\n" '
        '"$(grep -o "[0-9][0-9.]*" tls/grafana.crt | head -1)";;\n'
        'esac'
    ))
    buffer = _gateway_bundle()
    if existing:
        (_previous_bundle(app) / "tls").mkdir()
        ip = "1.2.3.4 expiring" if existing == "expiring" else existing
        (app / "tls" / "grafana.crt").write_text(f"cert {ip} pub=k1")
        if key:
            (app / "tls" / "grafana.key").write_text(key)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "APP_DIR": str(app),
           "BUNDLE_B64": base64.b64encode(buffer.getvalue()).decode()}

    result = subprocess.run(["bash", str(LAB_ROOT / "gateway" / "bootstrap.sh")], env=env,
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stderr
    assert "GATEWAY_READY" in result.stdout
    calls = log.read_text().splitlines()
    assert any(c.startswith("openssl req") for c in calls) is renewed
    restarts = [i for i, c in enumerate(calls) if c == "docker compose restart grafana"]
    assert bool(restarts) is renewed
    if renewed:
        # Restart only after the new certificate exists and the containers are up.
        renewal = next(i for i, c in enumerate(calls) if c.startswith("openssl req"))
        assert renewal < restarts[0]
        assert restarts[0] > calls.index("docker compose up -d --remove-orphans")


def test_postprovision_rebuilds_a_venv_whose_install_failed(fake_bin, tmp_path):
    bin_dir, log, write = fake_bin
    fail = tmp_path / "pip-fails"
    fail.touch()
    # Fake `python3 -m venv DIR`: creates DIR/bin/python and a pip that fails while the flag exists.
    write("python3", (
        'if [[ "$1 $2" == "-m venv" ]]; then mkdir -p "$3/bin"; printf "#!/bin/sh\\n" >"$3/bin/python"; '
        f'printf "#!/bin/sh\\n[ -e {fail} ] && exit 1\\nexit 0\\n" >"$3/bin/pip"; chmod +x "$3/bin/"*; fi'
    ))
    state = tmp_path / "state"
    state.mkdir()
    text = (SCRIPTS / "azd-postprovision.sh").read_text()
    start = text.index("python_env() {")
    function = tmp_path / "python_env.sh"
    function.write_text(text[start:text.index("\n}\n", start) + 3])
    harness = f'source "{SCRIPTS / "lib.sh"}"; STATE="{state}"; source "{function}"; PY="$(python_env)"; echo "PY=$PY"'
    run = lambda: subprocess.run(["bash", "-c", harness], env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
                                 capture_output=True, text=True, timeout=60)

    first = run()
    assert first.returncode != 0
    assert "could not install" in first.stderr

    fail.unlink()
    second = run()
    assert second.returncode == 0, second.stderr
    assert (state / "venv" / ".lab-requirements.txt").read_text() == (LAB_ROOT / "agent" / "requirements.txt").read_text()
    venv_creations = log.read_text().count("python3 -m venv")

    assert run().returncode == 0
    assert log.read_text().count("python3 -m venv") == venv_creations  # a completed install is reused


@pytest.mark.parametrize("recorded_port, started", [
    ("234", "same"),          # "234:8428" must not match the argument "1234:8428"
    ("1234", "Mon Jan  1 00:00:00 2001"),  # same command, but a different process generation
])
def test_vm_query_never_signals_a_process_it_did_not_start(fake_bin, tmp_path, recorded_port, started):
    bin_dir, _, write = fake_bin
    write("azd", "exit 1")
    other = tmp_path / "kubectl"
    # No exec: the bash process keeps the kubectl-like command line that vm-query.sh inspects.
    other.write_text("#!/usr/bin/env bash\nsleep 30 & child=$!\ntrap 'kill $child; exit 0' TERM\nwait $child\n")
    other.chmod(0o755)
    process = subprocess.Popen(["bash", str(other), "--kubeconfig", "k", "port-forward", "svc/x", "1234:8428"])
    try:
        state = tmp_path / "state" / "unit"
        state.mkdir(parents=True)
        lstart = subprocess.run(["ps", "-p", str(process.pid), "-o", "lstart="],
                                capture_output=True, text=True).stdout
        (state / "port-forward.pid").write_text(f"{process.pid}\n")
        (state / "port-forward.port").write_text(f"{recorded_port}\n")
        (state / "port-forward.started").write_text(lstart if started == "same" else started + "\n")
        env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "AZURE_ENV_NAME": "unit",
               "LAB_STATE_ROOT": str(tmp_path / "state"), "VM_LOCAL_PORT": recorded_port}

        result = subprocess.run(["bash", str(SCRIPTS / "vm-query.sh"), "stop"], env=env,
                                capture_output=True, text=True, timeout=60)

        assert result.returncode == 0, result.stderr
        assert process.poll() is None, "an unrelated process was signalled"
        assert not (state / "port-forward.pid").exists()
    finally:
        process.terminate()
        process.wait()


def test_verify_cleanup_fails_fast_when_the_lookup_fails(fake_bin):
    bin_dir, _, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write("azd", AZD_CLEANUP_ENV)
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0
    write("az", 'echo "AADSTS700082: token expired" >&2; exit 1')

    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode != 0
    assert "could not query resource group" in result.stderr


def test_verify_cleanup_requires_what_predown_recorded(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write("azd", AZD_CLEANUP_ENV)

    # Without predown the current environment values must not be verified in its place.
    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode != 0
    assert "predown did not record" in result.stderr
    assert "group exists" not in log.read_text()


def test_vm_query_start_fails_when_its_forward_exits_while_another_listener_answers(fake_bin, tmp_path):
    [port] = _free_ports(1)
    bin_dir, _, write = fake_bin
    write("azd", "exit 1")
    write("curl", 'exec /usr/bin/curl "$@"')
    server = tmp_path / "other.py"
    server.write_text(
        "import http.server as h,sys\n"
        "class H(h.BaseHTTPRequestHandler):\n"
        " def do_GET(s): s.send_response(200); s.end_headers()\n"
        " def log_message(s,*a): pass\n"
        "h.HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()"
    )
    pid_file = tmp_path / "other.pid"
    # The fake kubectl loses the race: another environment's listener takes the port, and the
    # forward itself exits (as kubectl does when it cannot bind).
    write("kubectl", f'/usr/bin/python3 {server} {port} & echo $! > {pid_file}; exit 1')
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "AZURE_ENV_NAME": "unit",
           "LAB_STATE_ROOT": str(tmp_path / "state"), "VM_LOCAL_PORT": str(port)}
    try:
        result = subprocess.run(["bash", str(SCRIPTS / "vm-query.sh"), "start"], env=env,
                                capture_output=True, text=True, timeout=60)
    finally:
        if pid_file.exists():
            subprocess.run(["kill", pid_file.read_text().strip()])

    assert result.returncode != 0
    assert "exited before becoming ready" in result.stderr


def test_cleanup_skips_an_identity_whose_client_id_is_unknown(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", AZ_CLEANUP)
    # The producer client ID is missing; cleanup must not look up "eventhubs-producer" as a client ID.
    write("azd", AZD_CLEANUP_ENV.replace("PRODUCER_CLIENT_ID) echo client-producer;; ", ""))

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode == 0, result.stderr
    deletes = [c for c in log.read_text().splitlines() if "federated-credential delete" in c]
    assert len(deletes) == 1 and "--identity-name id-consumer" in deletes[0]


def test_postdown_checks_the_subscription_predown_recorded(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write("azd", AZD_CLEANUP_ENV)
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0

    write("azd", AZD_CLEANUP_ENV.replace("00000000-0000-0000-0000-000000000000", "11111111-1111-1111-1111-111111111111"))
    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode != 0
    assert "predown recorded subscription 00000000-0000-0000-0000-000000000000" in result.stderr
    assert "--subscription 11111111" not in log.read_text()


def test_scenario_counts_only_fresh_lag_samples():
    text = (SCRIPTS / "run-scenario.sh").read_text()
    # A stopped exporter leaves its last value queryable; only samples newer than 120 s count.
    assert 'FRESH_LAG="($LAG_SERIES and (time() - timestamp($LAG_SERIES)) < 120)"' in text
    # A partition whose lag series disappeared must not let the others report a recovery.
    assert '"max($FRESH_LAG) and on() (count($FRESH_LAG) == count($FRESH_PARTITIONS))"' in text
    final = text.index('FINAL_LAG="$(max_lag)"')
    assert final < text.index('SCENARIO_END="$(now)"', final)
    assert '[[ "$FINAL_LAG" -ge 0 ]] || die' in text


def test_scenario_completes_only_when_the_final_lag_is_still_recovered():
    text = (SCRIPTS / "run-scenario.sh").read_text()

    # A dip below the target that rose again by the end is not a recovery.
    check = '[[ "$FINAL_LAG" -le "$TARGET" ]] || die'
    assert check in text
    assert text.index('FINAL_LAG="$(max_lag)"') < text.index(check) < text.index('log "scenario completed"')


def test_scenario_load_window_and_peak_cover_the_running_producer():
    text = (SCRIPTS / "run-scenario.sh").read_text()

    rollout = text.index("kube rollout status -n \"$NS\" deploy/eventhubs-producer")
    assert rollout < text.index('LOAD_START="$(now)"') < text.index("sleep $((LOAD_MINUTES * 60))")
    # The peak is the maximum since the producer was requested, read after the producer stopped.
    assert text.index('LOAD_REQUESTED_EPOCH="$(date +%s)"') < text.index("kube scale -n \"$NS\" deploy/eventhubs-producer --replicas 1")
    stop = text.index("stop_producer\nPRODUCER_STOP=")
    assert stop < text.index('PEAK_LAG="$(peak_lag)"')
    assert "max(max_over_time($LAG_SERIES[$(( $(date +%s) - LOAD_REQUESTED_EPOCH ))s]))" in text


def test_gateway_only_requires_a_completed_full_postprovision():
    text = (SCRIPTS / "azd-postprovision.sh").read_text()

    full = text.index('if [[ "${GATEWAY_ONLY:-false}" != "true" ]]; then')
    # A new full run invalidates the stamp first and writes it only after the last health check.
    assert text.index('rm -f "$COMPLETED_STAMP"', full) < text.index('log "1/6', full)
    health = text.index('log "6/6 operator-facing health checks"')
    # The stamp follows the health check command itself (and its failure branch), not just its log line.
    check = text.index('"https://$GATEWAY_PUBLIC_IP:3000/api/health"', health)
    failure = text.index('|| die "Grafana is not reachable', check)
    assert text.index('touch "$COMPLETED_STAMP"') > failure
    assert text.count('touch "$COMPLETED_STAMP"') == 1
    # The only write is skipped for GATEWAY_ONLY, so a gateway-only run can never create the stamp.
    assert '[[ "${GATEWAY_ONLY:-false}" == "true" ]] || touch "$COMPLETED_STAMP"\n' in text
    assert '[[ -f "$COMPLETED_STAMP" && -n "$WORKLOAD_IMAGE" ]] || die' in text


def test_predown_never_leaves_an_earlier_target_for_postdown(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
    write("azd", AZD_CLEANUP_ENV)
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0

    # A later run on an environment with no provisioned group replaces the old target with "none".
    write("azd", "exit 1")
    assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0
    log.write_text("")
    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode == 0, result.stderr
    assert "nothing to verify" in result.stderr
    assert "group exists" not in log.read_text()


def test_predown_derives_the_group_when_provision_failed_before_writing_outputs(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$*" == "group exists --subscription 00000000-0000-0000-0000-000000000000 -n rg-unit -o tsv" ]]; '
                'then echo true; exit 0; fi; if [[ "$1 $2" == "identity list" ]]; then exit 0; fi; '
                'echo "unexpected az call: $*" >&2; exit 97')
    # Only the subscription is recorded: the outputs (including AZURE_RESOURCE_GROUP) were never saved.
    write("azd", 'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; *) exit 1;; esac')

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode == 0, result.stderr
    state = bin_dir.parent / "state" / "unit"
    assert (state / "down-resource-group").read_text() == "rg-unit\n"
    assert (state / "down-subscription").read_text() == "00000000-0000-0000-0000-000000000000\n"


READER_ID = ("/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/rg-existing/providers/"
             "Microsoft.EventHub/clusters/ehc-existing/providers/Microsoft.Authorization/roleAssignments/"
             "33333333-3333-3333-3333-333333333333")


# ARM may return the provider segments in lower case; the scope must still be the cluster.
READER_ID_LOWER = READER_ID.replace("/providers/Microsoft.EventHub/", "/providers/microsoft.eventhub/").replace(
    "/providers/Microsoft.Authorization/roleAssignments/", "/providers/microsoft.authorization/roleassignments/")


@pytest.mark.parametrize("present, reader_id", [(True, READER_ID), (False, READER_ID), (True, READER_ID_LOWER)])
def test_predown_removes_only_the_lab_reader_assignment_on_an_existing_cluster(fake_bin, present, reader_id):
    bin_dir, log, write = fake_bin
    scope = re.split(r"(?i)/providers/microsoft\.authorization/", reader_id)[0]
    assert scope.lower().endswith("/clusters/ehc-existing")
    write("az", (
        'args="$*"\n'
        'case "$args" in\n'
        '  "group exists "*) echo false;;\n'
        f'  "role assignment list --subscription 22222222-2222-2222-2222-222222222222 --scope {scope} '
        f'--query [?name==\'33333333-3333-3333-3333-333333333333\'] | length(@) -o tsv") echo {1 if present else 0};;\n'
        f'  "role assignment delete --subscription 22222222-2222-2222-2222-222222222222 --ids {reader_id} --output none") ;;\n'
        '  *) echo "unexpected az call: $args" >&2; exit 97;;\n'
        'esac'
    ))
    write("azd", AZD_CLEANUP_ENV.replace("*) exit 1;;", f"EXISTING_CLUSTER_READER_ASSIGNMENT_ID) echo {reader_id};; *) exit 1;;"))

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode == 0, result.stderr
    deletes = [c for c in log.read_text().splitlines() if "role assignment delete" in c]
    assert deletes == ([f"az role assignment delete --subscription 22222222-2222-2222-2222-222222222222 --ids {reader_id} --output none"]
                       if present else [])


def test_predown_refuses_a_reader_assignment_id_of_another_shape(fake_bin):
    bin_dir, log, write = fake_bin
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; exit 0; fi; exit 97')
    other = "/subscriptions/2/resourceGroups/rg/providers/Microsoft.Authorization/roleAssignments/33333333-3333-3333-3333-333333333333"
    write("azd", AZD_CLEANUP_ENV.replace("*) exit 1;;", f"EXISTING_CLUSTER_READER_ASSIGNMENT_ID) echo {other};; *) exit 1;;"))

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode != 0
    assert "unexpected EXISTING_CLUSTER_READER_ASSIGNMENT_ID" in result.stderr
    assert "role assignment delete" not in log.read_text()


def test_predown_refuses_a_half_known_target(fake_bin):
    bin_dir, _, write = fake_bin
    write("az", "exit 0")
    write("azd", 'case "${@: -1}" in AZURE_RESOURCE_GROUP) echo rg-example;; *) exit 1;; esac')

    result = _run("cleanup-external.sh", bin_dir, "--yes")

    assert result.returncode != 0
    assert "only one of AZURE_RESOURCE_GROUP and AZURE_SUBSCRIPTION_ID" in result.stderr


@pytest.mark.parametrize("script, args", [("verify-cleanup.sh", ()), ("cleanup-external.sh", ("--yes",))])
def test_group_lookup_rejects_an_unexpected_answer(fake_bin, script, args):
    bin_dir, _, write = fake_bin
    write("azd", AZD_CLEANUP_ENV)
    if script == "verify-cleanup.sh":
        write("az", 'if [[ "$1 $2" == "group exists" ]]; then echo false; fi')
        assert _run("cleanup-external.sh", bin_dir, "--yes").returncode == 0
    # A table-formatted answer would never equal "false" and must not loop until "still exists".
    write("az", 'if [[ "$1 $2" == "group exists" ]]; then printf "Result\\n--------\\nFalse\\n"; fi')

    result = _run(script, bin_dir, *args)

    assert result.returncode != 0
    assert "unexpected answer to the resource group existence check" in result.stderr


def test_gateway_run_pins_the_subscription(fake_bin, tmp_path):
    bin_dir, log, write = fake_bin
    write("az", "exit 0")
    script = tmp_path / "step.sh"
    script.write_text("echo hi\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "AZURE_ENV_NAME": "unit",
           "LAB_STATE_ROOT": str(tmp_path / "state"), "AZURE_SUBSCRIPTION_ID": "00000000-0000-0000-0000-000000000000",
           "AZURE_RESOURCE_GROUP": "rg-example", "GATEWAY_VM_NAME": "vm-example"}
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPTS / "lib.sh"}"; gateway_run "{script}" BUNDLE_B64=abc'],
        env=env, capture_output=True, text=True, timeout=30,
    )

    assert result.returncode == 0, result.stderr
    [call] = [line for line in log.read_text().splitlines() if line.startswith("az vm run-command invoke")]
    assert " --subscription 00000000-0000-0000-0000-000000000000 " in f"{call} "
    assert " --resource-group rg-example " in call and " --parameters BUNDLE_B64=abc" in call


@pytest.mark.parametrize("vault, code", [("pw", "0"), (None, "1")])
def test_gateway_bootstrap_ends_with_its_exit_code(fake_bin, tmp_path, vault, code):
    bin_dir, _, write = fake_bin
    _bootstrap_tools(write)
    if vault is None:
        write("az", 'if [[ "$1 $2" == "keyvault secret" ]]; then exit 1; fi')

    result = _run_bootstrap(bin_dir, tmp_path, tmp_path / "app")

    # Run Command returns output only, so postprovision trusts this line, not the transport status.
    assert result.stdout.rstrip().splitlines()[-1] == f"GATEWAY_EXIT_CODE={code}"
    text = (SCRIPTS / "azd-postprovision.sh").read_text()
    assert 'grep -qx "GATEWAY_EXIT_CODE=0" "$STATE/gateway-bootstrap.log"' in text


def test_managed_grafana_is_wired_only_when_enabled_and_approves_only_its_own_connection():
    post = (SCRIPTS / "azd-postprovision.sh").read_text()
    text = (SCRIPTS / "managed-grafana.sh").read_text()

    assert 'if [[ -n "$(env_value MANAGED_GRAFANA_NAME)" ]]; then\n  "$LAB_ROOT/scripts/managed-grafana.sh"' in post
    # The Private Link Service is open to every subscription, so only this request may be approved.
    assert "privateLinkServiceConnectionState.status=='Pending' && privateLinkServiceConnectionState.description=='$REQUEST_MESSAGE'" in text
    assert '--request-message "$REQUEST_MESSAGE"' in text
    # A requester picks its own message, so the message carries a secret per-environment nonce that is
    # generated once, kept only in the local azd environment, and reused on reruns.
    assert 'REQUEST_MESSAGE="eventhubs-lab ${AZURE_ENV_NAME} managed grafana ${REQUEST_NONCE}"' in text
    assert 'REQUEST_NONCE="$(env_value MANAGED_GRAFANA_REQUEST_NONCE)"' in text
    assert 'REQUEST_NONCE="$(openssl rand -hex 16)"' in text
    assert 'azd_env set MANAGED_GRAFANA_REQUEST_NONCE "$REQUEST_NONCE"' in text
    assert text.index('REQUEST_MESSAGE=') < text.index("az grafana managed-private-endpoint create")
    # The data source keeps the Gateway Grafana uid so the agent dashboard works unchanged.
    assert '"uid": "victoriametrics"' in text and 'http://{sys.argv[1]}:8428' in text
    assert 'die "managed private endpoint $MPE_NAME was not approved' in text


def test_platform_metrics_azure_monitor_keeps_only_the_event_hub_receiver():
    post = (SCRIPTS / "azd-postprovision.sh").read_text()
    collect = (SCRIPTS / "collect-evidence.sh").read_text()
    managed = (SCRIPTS / "managed-grafana.sh").read_text()
    compose = (LAB_ROOT / "gateway" / "compose.yaml").read_text()

    assert 'PLATFORM_METRICS="${PLATFORM_METRICS:-Collector}"' in post
    assert 'die "PLATFORM_METRICS must be Collector or AzureMonitor' in post
    mode = post[post.index('if [[ "$PLATFORM_METRICS" == "AzureMonitor" ]]; then'):]
    mode = mode[:mode.index("\nfi\n")]
    # Lag comes from the ConsumerLag resource log, so the logs hub is mandatory in this mode.
    assert '[[ -n "$(env_value TELEMETRY_LOGS_EVENTHUB_NAME)" ]]' in mode
    assert "ENABLE_API_RECEIVER=false" in mode and "ENABLE_LAG_RECEIVER=false" in mode
    assert "LAG_EXPORTER_SCALE=0" in mode
    assert "ENABLE_LAG_RECEIVER=$ENABLE_LAG_RECEIVER" in post and "LAG_EXPORTER_SCALE=$LAG_EXPORTER_SCALE" in post
    assert "scale: ${LAG_EXPORTER_SCALE:-1}" in compose
    # Nothing outside the Collector reads the exporter any more.
    assert "lag-scrape" not in post and not (LAB_ROOT / "k8s" / "lag-scrape.yaml").exists()
    # No other platform metrics copy may run in this mode.
    assert 'die "PLATFORM_METRICS=AzureMonitor does not collect platform metrics; unset ENABLE_FALLBACK_EXPORTER"' in mode
    assert 'METRICS_HUB=""' in mode and "TELEMETRY_EVENTHUB_NAME=$METRICS_HUB" in post
    # A managed report from an earlier run is not compared unless this run produced it.
    assert '[[ -n "$MANAGED_ENDPOINT" ]] && reports+=(panel-verification-managed)' in collect
    assert '--cluster-resource-group "$CLUSTER_RG"' in collect
    assert "GF_AZURE_MANAGED_IDENTITY_CLIENT_ID: ${GATEWAY_CLIENT_ID" in compose
    assert "build_direct_dashboard.py" in collect and "compare_grafana_azure_monitor.py" in collect
    assert '"/d/$DASHBOARD_UID"' in collect
    assert "--data-source azure-monitor-oob" in managed and '"azureAuthType": "msi"' in managed


def test_scenario_reads_consumer_lag_logs_in_azure_monitor_mode():
    text = (SCRIPTS / "run-scenario.sh").read_text()
    branch = text[text.index('if [[ "$(env_value PLATFORM_METRICS)" == "AzureMonitor" ]]; then'):]
    branch = branch[:branch.index("\nfi\n")]
    assert 'eventhubs_log_consumer_lag{source_path="diagnostic_logs",delivery_path="remote_write"}' in branch
    assert "SETTLE_SECONDS=180" in branch and "LOG_LAG=true" in branch
    # An absent record reads as 0 only while other resource logs still arrive; otherwise it is unknown.
    assert 'vm_scalar "${1:-30}" "max($FRESH_LAG) or (vector(0) and on() (sum(increase($LOG_RECORDS[3m])) > 0))"' in text
    assert "&& consumer_progressed; then" in text
    assert '"$processed" -gt "$CONSUMER_PROCESSED_AT_LOAD_END"' in text
    assert 'sleep "$SETTLE_SECONDS"' in text
