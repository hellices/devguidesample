import pytest


def test_only_known_azure_https_hosts_can_enter_the_proxy_allowlist():
    from network_probe import target_hosts

    assert target_hosts([
        "https://gateway.example.azure-api.net/rest-tools/mcp",
        "https://mcp.example.azurecontainerapps.io/mcp",
    ]) == ["gateway.example.azure-api.net", "mcp.example.azurecontainerapps.io"]
    with pytest.raises(ValueError, match="approved"):
        target_hosts(["https://unrelated.example.test"])
    with pytest.raises(ValueError, match="HTTPS"):
        target_hosts(["http://gateway.example.azure-api.net"])


def test_proxy_has_no_public_service_and_no_service_account_token():
    from network_probe import proxy_manifest

    resources = proxy_manifest(["gateway.example.azure-api.net"], "print('fixture')")
    assert {item["kind"] for item in resources["items"]} == {
        "Namespace", "ConfigMap", "Deployment"
    }
    deployment = next(item for item in resources["items"] if item["kind"] == "Deployment")
    pod = deployment["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["containers"][0]["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False
    assert "hostNetwork" not in pod
    assert "hostPort" not in pod["containers"][0]["ports"][0]


def test_tunnel_port_parser_does_not_accept_non_loopback_binding():
    from network_probe import forwarded_port

    assert forwarded_port("Forwarding from 127.0.0.1:43210 -> 8080") == 43210
    assert forwarded_port("Forwarding from 0.0.0.0:43210 -> 8080") is None


def test_proxy_code_change_changes_the_pod_template():
    from network_probe import proxy_manifest

    def template(code):
        resources = proxy_manifest(["gateway.example.azure-api.net"], code)
        return next(r for r in resources["items"] if r["kind"] == "Deployment")["spec"]["template"]

    assert template("first") != template("second")


def test_tunnel_drains_output_before_waiting_for_process_exit(tmp_path):
    from io import StringIO
    from network_probe import wait_with_output

    output = "Handling connection for 8080\n" * 5000

    class Process:
        stdout = StringIO(output)

        def wait(self):
            assert self.stdout.tell() == len(output)
            return 0

    assert wait_with_output(Process(), tmp_path / "tunnel.log") == 0
    assert (tmp_path / "tunnel.log").read_text() == output
