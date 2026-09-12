"""Read native caller restrictions; optionally exercise a reversible lab-only denial."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import time

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from auth_probe import api_token
from cloud_lab import load_state, private_path
from cloud_stage import ApplicationStage
from entra_setup import AZURE_CLI_CLIENT_ID
from probe_utils import Results, all_tools


def denial_clients(clients: list[str], denied: str) -> list[str]:
    if denied not in clients:
        raise ValueError("the test client is not in the original allowlist")
    reduced = [client for client in clients if client != denied]
    if not reduced:
        raise ValueError("the denial exercise must keep a nonempty allowlist")
    return reduced


async def discovery(url: str, proxy: str, token: str) -> tuple[str, int]:
    async with httpx2.AsyncClient(
        proxy=proxy, headers={"Authorization": "Bearer " + token},
        timeout=httpx2.Timeout(30, read=120),
    ) as http:
        async with Client(
            streamable_http_client(url, http_client=http), read_timeout_seconds=120,
        ) as client:
            return client.protocol_version, len(await all_tools(client))


async def wait_for_status(url: str, proxy: str, token: str, expected: int) -> int:
    deadline = time.monotonic() + 180
    async with httpx2.AsyncClient(proxy=proxy, timeout=30) as client:
        while True:
            response = await client.post(
                url,
                headers={
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json, text/event-stream",
                },
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25", "capabilities": {},
                        "clientInfo": {"name": "caller-gate-probe", "version": "1.0.0"},
                    },
                },
            )
            if response.status_code == expected or time.monotonic() >= deadline:
                return response.status_code
            await asyncio.sleep(3)


async def run(state_path: Path, output: Path, exercise: bool) -> None:
    results = Results(output)
    stage = ApplicationStage(state_path)
    apps = load_state(state_path.with_name("mcp-apps.json"))
    proxy = load_state(state_path.with_name("network.json"))["proxy_url"]
    app_id = stage.group_id + "/providers/Microsoft.App/containerApps/" + apps["azureAppName"]
    config = stage.azure([
        "rest", "--method", "get",
        "--url", "https://management.azure.com" + app_id + "/authConfigs/current?api-version=2025-01-01",
        "--headers", "Accept=application/json",
    ])["properties"]
    provider = config["identityProviders"]["azureActiveDirectory"]
    allowed = provider["validation"]["defaultAuthorizationPolicy"]["allowedApplications"]
    native = stage.identities["azure_api"]
    matched = (
        config["platform"]["enabled"] is True
        and config["globalValidation"]["unauthenticatedClientAction"] == "Return401"
        and provider["registration"]["clientId"] == native["client_id"]
        and AZURE_CLI_CLIENT_ID in allowed
    )
    results.add("native-client-policy-readback", matched, result_count=len(allowed))
    token = api_token(state_path, "azure_api")
    url = apps["azureUrl"] + "/"
    version, count = await discovery(url, proxy, token)
    results.add("native-client-allowed-before", count == 2, protocol_version=version, tool_count=count)
    if exercise:
        parameters = {
            "appName": apps["azureAppName"],
            "tenantId": stage.state["tenant_id"],
            "apiClientId": native["client_id"],
            "allowedClientIds": allowed,
        }
        blocked_status = None
        try:
            stage.deploy("native-auth.bicep", "mcp-native-auth-denial", {
                **parameters,
                "allowedClientIds": denial_clients(allowed, AZURE_CLI_CLIENT_ID),
            })
            blocked_status = await wait_for_status(url, proxy, token, 403)
        finally:
            stage.deploy("native-auth.bicep", "mcp-native-auth-restore", parameters)
            restored_status = await wait_for_status(url, proxy, token, 200)
            if restored_status != 200:
                raise RuntimeError("native client allowlist restoration did not become effective")
        results.add(
            "native-valid-token-client-denied", blocked_status == 403,
            http_status=blocked_status,
        )
        version, count = await discovery(url, proxy, token)
        results.add("native-client-allowed-restored", count == 2, protocol_version=version, tool_count=count)
    results.complete("native-client-gate-complete" if exercise else "native-client-gate-readonly-complete")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exercise-denial", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(private_path(args.state), args.output, args.exercise_denial))


if __name__ == "__main__":
    main()
