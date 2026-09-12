"""Run real read-only MCP calls; credentials and raw responses stay unpublished."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import shlex
import subprocess

import httpx2
from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from cloud_lab import SAMPLE_ROOT, load_state, private_path, write_private
from probe_utils import Results, all_tools, azure_resource_count, json_result, text_result


TARGETS = ("github", "learn", "azure", "aks")


def aks_azure_command(state: dict) -> str:
    return shlex.join([
        "az", "aks", "show", "--subscription", state["subscription_id"],
        "--resource-group", state["resource_group"],
        "--name", state["foundation_outputs"]["aksName"],
        "--query", "{id:id,provisioningState:provisioningState}", "-o", "json",
    ])


def aks_cluster_matches(state: dict, payload: object) -> bool:
    expected = (
        f"/subscriptions/{state['subscription_id']}/resourceGroups/{state['resource_group']}"
        f"/providers/Microsoft.ContainerService/managedClusters/{state['foundation_outputs']['aksName']}"
    )
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("id"), str)
        and payload["id"].casefold() == expected.casefold()
        and payload.get("provisioningState") == "Succeeded"
    )


@asynccontextmanager
async def http_client(url: str, headers: dict[str, str] | None = None):
    async with httpx2.AsyncClient(
        headers=headers, timeout=httpx2.Timeout(30, read=120),
    ) as transport:
        async with Client(
            streamable_http_client(url, http_client=transport), read_timeout_seconds=120
        ) as client:
            yield client


@asynccontextmanager
async def stdio_client_for(
    command: Path, arguments: list[str], environment: dict[str, str], log_path: Path
):
    if not command.is_file():
        raise FileNotFoundError("install the pinned MCP runtime before this probe")
    if "AZURE_CONFIG_DIR" in os.environ:
        environment = {**environment, "AZURE_CONFIG_DIR": os.environ["AZURE_CONFIG_DIR"]}
    write_private(log_path, "")
    with log_path.open("a", encoding="utf-8") as log:
        params = StdioServerParameters(
            command=str(command), args=arguments, env=environment,
        )
        async with Client(
            stdio_client(params, errlog=log), read_timeout_seconds=120
        ) as client:
            yield client


async def github(results: Results) -> None:
    credential = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=30
    ).stdout.strip()
    async with http_client("https://api.githubcopilot.com/mcp/", {
        "Authorization": "Bearer " + credential,
        "X-MCP-Readonly": "true",
        "X-MCP-Tools": "search_repositories",
    }) as client:
        tools = await all_tools(client)
        results.add(
            "github-readonly-discovery", {tool.name for tool in tools} == {"search_repositories"},
            tool_count=len(tools), protocol_version=client.protocol_version,
        )
        response = await client.call_tool(
            "search_repositories", {"query": "repo:hellices/devguidesample"}
        )
        payload = json_result(response)
        items = payload["items"]
        matched = [
            item for item in items
            if item.get("full_name") == "hellices/devguidesample"
        ]
        results.add(
            "github-public-repository-search", payload["total_count"] == 1 and len(matched) == 1,
            result_count=len(matched), tool_error=response.is_error,
        )


async def learn(results: Results) -> None:
    async with http_client("https://learn.microsoft.com/api/mcp") as client:
        tools = await all_tools(client)
        required = {"microsoft_docs_search", "microsoft_docs_fetch", "microsoft_code_sample_search"}
        results.add(
            "learn-anonymous-discovery", required.issubset({tool.name for tool in tools}),
            tool_count=len(tools), protocol_version=client.protocol_version,
        )
        response = await client.call_tool(
            "microsoft_docs_search", {"query": "Azure API Management MCP"}
        )
        entries = json_result(response)["results"]
        results.add("learn-search", len(entries) > 0, result_count=len(entries), tool_error=response.is_error)
        fetched = await client.call_tool("microsoft_docs_fetch", {
            "url": "https://learn.microsoft.com/azure/api-management/export-rest-mcp-server"
        })
        article = text_result(fetched)
        results.add(
            "learn-full-article-fetch",
            len(article) > 1000 and "API Management" in article and "MCP" in article,
            result_count=1, tool_error=fetched.is_error,
        )


async def azure(results: Results, state_path: Path) -> None:
    state = load_state(state_path)
    async with stdio_client_for(
        SAMPLE_ROOT / "node_modules" / ".bin" / "azmcp",
        [
            "server", "start", "--mode", "all", "--read-only", "--namespace", "group",
            "--outgoing-auth-strategy", "UseHostingEnvironmentIdentity",
        ],
        {"AZURE_MCP_COLLECT_TELEMETRY": "false", "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential"},
        state_path.with_name("azure-stdio-probe.log"),
    ) as client:
        tools = await all_tools(client)
        results.add(
            "azure-stdio-discovery", "group_resource_list" in {tool.name for tool in tools},
            tool_count=len(tools), protocol_version=client.protocol_version,
        )
        response = await client.call_tool("group_resource_list", {
            "subscription": state["subscription_id"],
            "resource-group": state["resource_group"],
            "retry-max-retries": 1,
            "retry-network-timeout": 30,
        })
        group_id = f"/subscriptions/{state['subscription_id']}/resourceGroups/{state['resource_group']}"
        count = azure_resource_count(response, group_id)
        results.add("azure-stdio-lab-resources", count > 0, resource_count=count, tool_error=response.is_error)


async def aks(results: Results, state_path: Path, binary: Path) -> None:
    state = load_state(state_path)
    kubeconfig = state_path.with_name("kubeconfig")
    if not kubeconfig.is_file():
        raise FileNotFoundError("prepare the lab-only kubeconfig before running AKS MCP")
    async with stdio_client_for(
        binary,
        [
            "--access-level", "readonly", "--enabled-components", "az_cli,kubectl",
            "--allow-namespaces", "mcp-lab", "--timeout", "90",
        ],
        {"KUBECONFIG": str(kubeconfig)},
        state_path.with_name("aks-stdio-probe.log"),
    ) as client:
        tools = await all_tools(client)
        results.add(
            "aks-stdio-discovery", {"call_az", "call_kubectl"}.issubset({tool.name for tool in tools}),
            tool_count=len(tools), protocol_version=client.protocol_version,
        )
        response = await client.call_tool("call_az", {
            "cli_command": aks_azure_command(state)
        })
        results.add("aks-azure-read", aks_cluster_matches(state, json_result(response)), tool_error=response.is_error)
        response = await client.call_tool("call_kubectl", {
            "command": "kubectl get pods -n mcp-lab -o json"
        })
        pods = json_result(response)["items"]
        in_scope = bool(pods) and all(pod["metadata"]["namespace"] == "mcp-lab" for pod in pods)
        results.add("aks-kubernetes-read", in_scope, result_count=len(pods), tool_error=response.is_error)


async def run(state_path: Path, output: Path, selected: str | None, binary: Path) -> None:
    results = Results(output)
    for target in (selected,) if selected else TARGETS:
        if target == "github":
            await github(results)
        elif target == "learn":
            await learn(results)
        elif target == "azure":
            await azure(results, state_path)
        else:
            await aks(results, state_path, binary)
        print(target + ": live checks completed.")
    results.complete(f"upstreams-{selected}-complete" if selected else "upstreams-suite-complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only", choices=TARGETS)
    parser.add_argument("--aks-binary", type=Path)
    args = parser.parse_args()
    state_path = private_path(args.state)
    binary = args.aks_binary or state_path.parent.parent / "mcp-tools" / "aks-mcp"
    asyncio.run(run(state_path, args.output, args.only, binary))


if __name__ == "__main__":
    main()
