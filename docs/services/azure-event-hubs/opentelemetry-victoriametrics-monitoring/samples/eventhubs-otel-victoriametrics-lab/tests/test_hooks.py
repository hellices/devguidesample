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


AZ_CALL = re.compile(r"(?:^|\$\(|[\s;|&(])az\s+([a-z-]+(?:\s+[a-z-]+)?)")
COMMAND_END = re.compile(r"\)|;|&&|\|")


def _az_calls(line: str) -> list[tuple[str, str]]:
    """Each az invocation on a line with the text up to its own command boundary."""
    calls = []
    for match in AZ_CALL.finditer(line):
        rest = line[match.end():]
        end = COMMAND_END.search(rest)
        calls.append((match.group(1), match.group(0) + (rest[: end.start()] if end else rest)))
    return calls


def test_az_call_segments_do_not_borrow_options_from_the_next_command():
    calls = _az_calls('az group delete -n "$rg"; az group show -n "$rg" --subscription "$sub"')
    assert [("--subscription" in segment) for _, segment in calls] == [False, True]


def test_azure_cli_calls_pin_the_subscription():
    for path in SCRIPTS.glob("*.sh"):
        for line in _joined_commands(path.read_text()):
            if line.lstrip().startswith(("#", "require_commands")):
                continue
            for command, segment in _az_calls(line):
                if command.startswith(("ad ", "account ")) and "--subscription" not in segment:
                    # Entra ID lookups, the active-subscription guard and token reads are tenant scoped.
                    assert command.startswith(
                        ("ad signed-in-user", "account show", "account get-access-token")
                    ), line
                    continue
                if 'az vm run-command invoke "${args[@]}"' in segment:
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
            for match in re.finditer(r"(?:^|[\s;|&(])kubectl\s([^;|&)]*)", line):
                assert "--kubeconfig" in match.group(1), f"{path.name}: {line.strip()}"


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


AZD_CLEANUP_ENV = (
    'case "${@: -1}" in AZURE_SUBSCRIPTION_ID) echo 00000000-0000-0000-0000-000000000000;; '
    "AZURE_RESOURCE_GROUP) echo rg-example;; PRODUCER_CLIENT_ID) echo client-producer;; "
    "CONSUMER_CLIENT_ID) echo client-consumer;; *) exit 1;; esac"
)
# Exactly the lookups and deletes cleanup may make; anything else (for example deleting an
# identity, or touching an unrelated identity) is rejected with exit 97.
AZ_CLEANUP = (
    'args="$*"\n'
    'case "$args" in\n'
    '  "group exists --subscription "*" -n rg-example") echo true;;\n'
    '  "identity list "*"clientId==\'client-producer\'"*) echo id-producer;;\n'
    '  "identity list "*"clientId==\'client-consumer\'"*) echo id-consumer;;\n'
    '  "identity federated-credential list "*"--identity-name id-producer "*) echo aks-eventhubs-producer;;\n'
    '  "identity federated-credential list "*"--identity-name id-consumer "*) echo aks-eventhubs-slow-consumer;;\n'
    '  "identity federated-credential delete "*"--identity-name id-producer --name aks-eventhubs-producer --yes"*) ;;\n'
    '  "identity federated-credential delete "*"--identity-name id-consumer --name aks-eventhubs-slow-consumer --yes"*) ;;\n'
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
    env_file = ("GATEWAY_CLIENT_ID=c\nKEY_VAULT_NAME=kv\nACR_NAME=acr\n"
                "GATEWAY_PUBLIC_IP=1.2.3.4\nCOMPOSE_PROFILE=default\n").encode()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        info = tarfile.TarInfo("./.env")
        info.size = len(env_file)
        bundle.addfile(info, io.BytesIO(env_file))
    if existing:
        (app / "tls").mkdir(parents=True)
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
    write("az", 'echo "AADSTS700082: token expired" >&2; exit 1')
    write("azd", AZD_CLEANUP_ENV)

    result = _run("verify-cleanup.sh", bin_dir)

    assert result.returncode != 0
    assert "could not query resource group" in result.stderr


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
