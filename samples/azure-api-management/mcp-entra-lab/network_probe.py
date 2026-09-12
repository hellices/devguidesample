"""Use a new lab cluster as a private-network probe, not as a corporate VPN."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
from urllib.parse import urlsplit

from cloud_lab import SAMPLE_ROOT, load_state, private_path, save_state, write_private
from cloud_stage import ApplicationStage


NAMESPACE = "mcp-lab"
DEPLOYMENT = "mcp-transport-probe"
PYTHON_IMAGE = "python@sha256:7415fbc3c9e4979cc717d92377ab2bc7b2b4a2af1ac03cc52b5f3f88efedaf3a"


def target_hosts(urls: list[str]) -> list[str]:
    hosts = set()
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("probe endpoints must use default-port HTTPS")
        host = parsed.hostname or ""
        if (
            parsed.username or parsed.password or parsed.query or parsed.fragment
            or not host.endswith((".azure-api.net", ".azurecontainerapps.io"))
        ):
            raise ValueError("probe endpoint is not an approved Azure lab hostname")
        hosts.add(host)
    return sorted(hosts)


def proxy_manifest(hosts: list[str], proxy_code: str) -> dict:
    labels = {"app": DEPLOYMENT, "purpose": "mcp-entra-validation"}
    return {
        "apiVersion": "v1",
        "kind": "List",
        "items": [
            {
                "apiVersion": "v1", "kind": "Namespace",
                "metadata": {"name": NAMESPACE, "labels": labels},
            },
            {
                "apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {"name": DEPLOYMENT, "namespace": NAMESPACE, "labels": labels},
                "data": {"transport_proxy.py": proxy_code},
            },
            {
                "apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": {"name": DEPLOYMENT, "namespace": NAMESPACE, "labels": labels},
                "spec": {
                    "replicas": 1,
                    "selector": {"matchLabels": {"app": DEPLOYMENT}},
                    "template": {
                        "metadata": {
                            "labels": labels,
                            "annotations": {
                                "mcp-lab/code-sha256": hashlib.sha256(proxy_code.encode()).hexdigest()
                            },
                        },
                        "spec": {
                            "automountServiceAccountToken": False,
                            "containers": [{
                                "name": "connect-proxy",
                                "image": PYTHON_IMAGE,
                                "command": ["python", "-B", "/app/transport_proxy.py"],
                                "args": [
                                    argument for host in hosts
                                    for argument in ("--allow-host", host)
                                ],
                                "ports": [{"containerPort": 8080}],
                                "securityContext": {
                                    "runAsNonRoot": True,
                                    "runAsUser": 65532,
                                    "allowPrivilegeEscalation": False,
                                    "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]},
                                    "seccompProfile": {"type": "RuntimeDefault"},
                                },
                                "resources": {
                                    "requests": {"cpu": "20m", "memory": "24Mi"},
                                    "limits": {"cpu": "150m", "memory": "64Mi"},
                                },
                                "readinessProbe": {
                                    "tcpSocket": {"port": 8080}, "periodSeconds": 5,
                                },
                                "volumeMounts": [{"name": "code", "mountPath": "/app", "readOnly": True}],
                            }],
                            "volumes": [{
                                "name": "code", "configMap": {"name": DEPLOYMENT},
                            }],
                        },
                    },
                },
            },
        ],
    }


def forwarded_port(line: str) -> int | None:
    match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+) -> 8080", line)
    return int(match.group(1)) if match else None


def wait_with_output(process: subprocess.Popen[str], log_path: Path) -> int:
    if process.stdout is None:
        raise ValueError("the tunnel process must expose its output pipe")
    write_private(log_path, "")
    with log_path.open("a", encoding="utf-8") as log:
        for line in process.stdout:
            log.write(line)
    return process.wait()


class NetworkProbe:
    def __init__(self, state_path: Path):
        self.path = private_path(state_path)
        self.stage = ApplicationStage(self.path)
        self.kubeconfig = self.path.with_name("kubeconfig")

    def command(self, arguments: list[str], timeout: int = 300) -> str:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            write_private(self.path.with_name("last-kubernetes-error.txt"), result.stderr)
            raise RuntimeError(
                f"{arguments[0]} failed with exit {result.returncode}; "
                "inspect last-kubernetes-error.txt in the private state directory"
            )
        return result.stdout

    def kubectl(self, arguments: list[str]) -> list[str]:
        return ["kubectl", "--kubeconfig", str(self.kubeconfig), *arguments]

    def prepare(self) -> None:
        state = self.stage.state
        cluster = self.stage.azure([
            "aks", "show", "--name", "aks-mcplab-" + state["suffix"], *self.stage.common,
        ])
        if (
            cluster["provisioningState"] != "Succeeded"
            or cluster["disableLocalAccounts"] is not True
            or cluster["aadProfile"]["managed"] is not True
        ):
            raise ValueError("the Entra-enabled lab cluster is not ready")
        self.stage.azure([
            "aks", "get-credentials", "--name", cluster["name"], *self.stage.common,
            "--file", str(self.kubeconfig), "--overwrite-existing", "--format", "exec",
        ])
        self.kubeconfig.chmod(0o600)
        self.command([
            "kubelogin", "convert-kubeconfig", "--login", "azurecli",
            "--kubeconfig", str(self.kubeconfig),
        ])
        apps = load_state(self.path.with_name("mcp-apps.json"))
        hosts = target_hosts([
            apps["pythonUrl"], apps["azureUrl"],
            "https://apim-mcplab-" + state["suffix"] + ".azure-api.net",
        ])
        manifest = proxy_manifest(
            hosts, (SAMPLE_ROOT / "transport_proxy.py").read_text(encoding="utf-8")
        )
        manifest_path = self.path.with_name("proxy-manifest.json")
        save_state(manifest_path, manifest)
        self.command(self.kubectl(["apply", "-f", str(manifest_path)]))
        self.command(self.kubectl([
            "-n", NAMESPACE, "rollout", "status", "deployment/" + DEPLOYMENT,
            "--timeout=240s",
        ]))
        output = self.command(self.kubectl([
            "-n", NAMESPACE, "exec", "deployment/" + DEPLOYMENT, "--",
            "python", "-c",
            "import ipaddress,json,socket,sys;"
            "print(json.dumps({'host_count':len(sys.argv)-1,"
            "'private_dns':all(ipaddress.ip_address(socket.gethostbyname(h)).is_private "
            "for h in sys.argv[1:])}))",
            *hosts,
        ]))
        result = json.loads(output)
        if not result["private_dns"]:
            raise RuntimeError("at least one MCP endpoint does not resolve privately in the VNet")
        save_state(self.path.with_name("network-ready.json"), {
            "private_dns": True, "host_count": result["host_count"],
            "kubeconfig": str(self.kubeconfig),
        })
        print("Probe ready: three approved MCP hosts resolve privately inside the new VNet.")

    def forward(self) -> None:
        ready = load_state(self.path.with_name("network-ready.json"))
        if not ready["private_dns"] or ready["kubeconfig"] != str(self.kubeconfig):
            raise ValueError("prepare and validate this private probe first")
        process = subprocess.Popen(
            self.kubectl([
                "-n", NAMESPACE, "port-forward", "--address", "127.0.0.1",
                "deployment/" + DEPLOYMENT, ":8080",
            ]),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        lines = []
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                deadline = time.monotonic() + 60
                port = None
                while time.monotonic() < deadline and process.poll() is None:
                    if selector.select(timeout=2):
                        line = process.stdout.readline()
                        lines.append(line)
                        port = forwarded_port(line)
                        if port:
                            break
                if port is None:
                    write_private(self.path.with_name("port-forward-error.txt"), "".join(lines))
                    raise RuntimeError("kubectl did not bind the loopback tunnel within 60 seconds")
            save_state(self.path.with_name("network.json"), {
                "proxy_url": f"http://127.0.0.1:{port}",
                "pid": os.getpid(),
                "forwarder_pid": process.pid,
                "private_dns": True,
            })
            print("Authenticated loopback tunnel is listening.", flush=True)
            returncode = wait_with_output(process, self.path.with_name("port-forward.log"))
            if returncode:
                raise RuntimeError(f"kubectl tunnel exited with status {returncode}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("command", choices=["prepare", "forward"])
    args = parser.parse_args()
    probe = NetworkProbe(args.state)
    if args.command == "prepare":
        probe.prepare()
    else:
        probe.forward()


if __name__ == "__main__":
    main()
