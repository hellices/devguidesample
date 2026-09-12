"""Verify real private MCP authorization, OBO and APIM REST-tool invocation."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from auth_probe import api_token, verified_claims
from cloud_lab import load_state, private_path
from cloud_stage import ApplicationStage
from probe_utils import ProbeFailure, Results, all_tools, azure_resource_count, json_result


def inventory_matches(payload: object, probe_id: str) -> bool:
    if not isinstance(payload, dict):
        return False
    widgets = payload.get("widgets")
    invocation = payload.get("invocation_id")
    return (
        payload.get("source") == "inventory-rest"
        and isinstance(invocation, str)
        and re.fullmatch(r"[a-f0-9]{32}", invocation) is not None
        and payload.get("probe_id") == probe_id
        and payload.get("authorization_present") is False
        and isinstance(widgets, list)
        and all(isinstance(widget, dict) for widget in widgets)
        and [widget.get("sku") for widget in widgets] == ["WID-100", "WID-200", "WID-300"]
    )


def advertised_scope(identity: dict, scopes: list[str]) -> str:
    accepted = {
        identity["identifier_uri"] + "/" + identity["scope_name"],
        identity["client_id"] + "/" + identity["scope_name"],
    }
    for scope in scopes:
        if scope in accepted:
            return scope
    raise ProbeFailure("metadata did not advertise a scope for the intended API")


def control_plane(results: Results, stage: ApplicationStage) -> None:
    service_id = (
        stage.group_id + "/providers/Microsoft.ApiManagement/service/apim-mcplab-"
        + stage.state["suffix"]
    )

    def get(path: str):
        return stage.azure([
            "rest", "--method", "get",
            "--url", "https://management.azure.com" + service_id + path
            + "?api-version=2025-09-01-preview",
            "--headers", "Accept=application/json",
        ])["properties"]

    native = get("/apis/rest-tools")
    tool = get("/apis/rest-tools/tools/getInventory")
    operation = tool["operationId"]
    if operation.startswith("/apis/"):
        operation = service_id + operation
    expected = service_id + "/apis/lab-rest/operations/get-inventory"
    results.add(
        "apim-native-rest-mapping",
        native["type"] == "mcp" and operation.casefold() == expected.casefold(),
        result_count=1,
    )
    proxy = get("/apis/learn-mcp")
    endpoint = proxy["mcpProperties"]["endpoints"]["message"]["uriTemplate"]
    results.add(
        "apim-native-proxy-binding",
        proxy["type"] == "mcp" and proxy["backendId"] == "learn-backend" and endpoint == "/mcp",
        result_count=1,
    )
    for api_id, label in (("learn-mcp", "learn"), ("lab-rest", "rest")):
        policy = ElementTree.fromstring(get(f"/apis/{api_id}/policies/policy")["value"])
        removes_header = any(
            item.attrib.get("name", "").lower() == "authorization"
            and item.attrib.get("exists-action") == "delete"
            for item in policy.findall("./inbound/set-header")
        )
        results.add(f"apim-{label}-header-removal-policy", removes_header, header_removed=removes_header)


async def run(state_path: Path, output: Path) -> None:
    results = Results(output)
    stage = ApplicationStage(state_path)
    state = stage.state
    root = state_path.parent
    apps = load_state(root / "mcp-apps.json")
    apim = load_state(root / "mcp-apim.json")
    network = load_state(root / "network.json")
    identities = stage.identities
    control_plane(results, stage)
    results.add("vnet-private-dns", network["private_dns"] is True, private_dns=network["private_dns"])

    custom_token = api_token(state_path, "custom_api")
    native_token = api_token(state_path, "azure_api")
    arm_token = stage.azure([
        "account", "get-access-token", "--tenant", state["tenant_id"],
        "--resource", "https://management.azure.com/",
    ])["accessToken"]
    origin = urlsplit(apim["nativeMcpUrl"])
    gateway = origin.scheme + "://" + origin.netloc
    targets = [
        ("python", apps["pythonUrl"] + "/mcp", custom_token, identities["custom_api"],
         apps["pythonUrl"] + "/.well-known/oauth-protected-resource/mcp", "lab_inventory"),
        ("azure", apps["azureUrl"] + "/", native_token, identities["azure_api"],
         apps["azureUrl"] + "/.well-known/oauth-protected-resource", "group_resource_list"),
        ("apim-rest", apim["nativeMcpUrl"], custom_token, identities["custom_api"],
         gateway + "/oauth-metadata/rest-tools/mcp", "getInventory"),
        ("apim-learn", apim["learnMcpUrl"], custom_token, identities["custom_api"],
         gateway + "/oauth-metadata/learn/mcp", "microsoft_docs_search"),
    ]
    advertised_tokens: dict[str, str] = {}
    scope_tokens: dict[str, str] = {}
    async with httpx2.AsyncClient(
        proxy=network["proxy_url"], timeout=httpx2.Timeout(30, read=120),
    ) as http:
        for label, url, _, identity, metadata_url, tool_name in targets:
            methods = [
                ("initialize", {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "mcp-entra-lab-probe", "version": "1.0.0"},
                }),
                ("tools/list", {}),
                ("tools/call", {"name": tool_name, "arguments": {}}),
            ]
            for method, params in methods:
                response = await http.post(
                    url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers={"Accept": "application/json, text/event-stream"},
                )
                results.add(
                    label + "-anonymous-" + method.replace("/", "-"),
                    response.status_code == 401, http_status=response.status_code, tls_verified=True,
                )
            response = await http.post(
                url,
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer " + arm_token,
                },
            )
            results.add(label + "-wrong-audience", response.status_code == 401, http_status=response.status_code)
            metadata = await http.get(metadata_url)
            body = metadata.json()
            scope = advertised_scope(identity, body["scopes_supported"])
            matched = (
                metadata.status_code == 200
                and body["resource"].rstrip("/") == url.rstrip("/")
                and f"https://login.microsoftonline.com/{state['tenant_id']}/v2.0"
                in body["authorization_servers"]
            )
            results.add(
                label + "-protected-resource-metadata", matched,
                http_status=metadata.status_code, metadata_matched=matched,
            )
            if scope not in scope_tokens:
                scope_tokens[scope] = stage.azure([
                    "account", "get-access-token", "--tenant", state["tenant_id"],
                    "--scope", scope,
                ])["accessToken"]
            advertised_tokens[label] = scope_tokens[scope]
            claims = verified_claims(
                scope_tokens[scope], state["tenant_id"], identity["client_id"]
            )
            scope_matched = identity["scope_name"] in claims["scp"].split()
            results.add(
                label + "-advertised-scope-token", scope_matched,
                audience_matched=True, scope_matched=scope_matched,
            )
        rest_unauthorized = await http.get(apim["restUrl"])
        results.add("apim-rest-direct-anonymous", rest_unauthorized.status_code == 401, http_status=rest_unauthorized.status_code)
        delegated_unauthorized = await http.get(apps["pythonUrl"] + "/delegated-resource-group")
        results.add(
            "python-delegated-rest-anonymous", delegated_unauthorized.status_code == 401,
            http_status=delegated_unauthorized.status_code,
        )
        forbidden_bearer = await http.get(
            apps["pythonUrl"] + "/inventory",
            headers={"Authorization": "Bearer " + custom_token},
        )
        results.add(
            "rest-fixture-rejects-bearer", forbidden_bearer.status_code == 400,
            http_status=forbidden_bearer.status_code,
        )
        baseline_nonce = secrets.token_hex(8)
        rest = await http.get(apim["restUrl"], headers={
            "Authorization": "Bearer " + custom_token, "x-lab-probe-id": baseline_nonce,
        })
        baseline = rest.json()
        matched = rest.status_code == 200 and inventory_matches(baseline, baseline_nonce)
        results.add(
            "apim-real-rest-baseline", matched, http_status=rest.status_code,
            backend_invoked=matched, correlation_matched=matched, header_removed=matched,
        )

    for label, url, token, _, _, _ in targets:
        nonce = secrets.token_hex(8)
        async with httpx2.AsyncClient(
            proxy=network["proxy_url"],
            headers={"Authorization": "Bearer " + advertised_tokens[label], "x-lab-probe-id": nonce},
            timeout=httpx2.Timeout(30, read=120),
        ) as http:
            async with Client(
                streamable_http_client(url, http_client=http), read_timeout_seconds=120,
            ) as client:
                tools = await all_tools(client)
                names = {tool.name for tool in tools}
                results.add(
                    label + "-authenticated-discovery", bool(tools),
                    tool_count=len(tools), protocol_version=client.protocol_version,
                )
                if label == "python":
                    results.add("python-bounded-tool-surface", names == {
                        "lab_inventory", "read_lab_resource_group", "learn_search"
                    }, tool_count=len(names))
                    response = await client.call_tool("read_lab_resource_group", {})
                    body = json_result(response)
                    matched = body["exists"] is True and body["provisioning_succeeded"] is True
                    results.add(
                        "python-hosted-obo", matched, obo=True,
                        downstream_authorized=matched, tool_error=response.is_error,
                    )
                    response = await client.call_tool("learn_search", {"topic": "azure-api-management"})
                    entries = json_result(response)["results"]
                    results.add("python-hosted-learn", len(entries) > 0, result_count=len(entries), tool_error=response.is_error)
                elif label == "azure":
                    response = await client.call_tool("group_resource_list", {
                        "subscription": state["subscription_id"],
                        "resource-group": state["resource_group"],
                    })
                    count = azure_resource_count(response, stage.group_id)
                    results.add(
                        "native-azure-hosted-obo", count > 0, resource_count=count,
                        obo=True, downstream_authorized=True, tool_error=response.is_error,
                    )
                elif label == "apim-rest":
                    results.add("apim-selected-rest-tool", names == {"getInventory"}, tool_count=len(names))
                    response = await client.call_tool("getInventory", {})
                    body = json_result(response)
                    matched = (
                        inventory_matches(body, nonce)
                        and body["invocation_id"] != baseline["invocation_id"]
                    )
                    results.add(
                        "apim-native-rest-tool-invocation", matched,
                        backend_invoked=matched, correlation_matched=matched,
                        header_removed=matched, tool_error=response.is_error,
                    )
                else:
                    response = await client.call_tool(
                        "microsoft_docs_search", {"query": "Azure API Management MCP"}
                    )
                    entries = json_result(response)["results"]
                    results.add(
                        "apim-learn-proxy-invocation", len(entries) > 0,
                        result_count=len(entries), tool_error=response.is_error,
                    )
    results.complete("cloud-suite-complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(private_path(args.state), args.output))


if __name__ == "__main__":
    main()
