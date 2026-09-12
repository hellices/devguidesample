"""Strict result checks shared by the live MCP probes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.types import CallToolResult, Tool

from evidence import check, write_results


class ProbeFailure(RuntimeError):
    pass


async def all_tools(client: Client) -> list[Tool]:
    tools = []
    cursor = None
    seen = set()
    while True:
        page = await client.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return tools
        if cursor in seen:
            raise ProbeFailure("server repeated its tool pagination cursor")
        seen.add(cursor)


def text_result(result: CallToolResult) -> str:
    if result.is_error:
        raise ProbeFailure("MCP tool returned is_error")
    texts = [item.text for item in result.content if item.type == "text"]
    if not texts or not all(isinstance(text, str) and text.strip() for text in texts):
        raise ProbeFailure("MCP tool did not return non-empty text")
    return "\n".join(texts)


def json_result(result: CallToolResult) -> Any:
    if result.is_error:
        raise ProbeFailure("MCP tool returned is_error")
    if result.structured_content is not None:
        return result.structured_content
    try:
        return json.loads(text_result(result))
    except json.JSONDecodeError as error:
        raise ProbeFailure("MCP tool did not return the expected JSON") from error


def azure_resource_count(result: CallToolResult, group_id: str) -> int:
    payload = json_result(result)
    if not isinstance(payload, dict) or payload.get("status") != 200:
        raise ProbeFailure("Azure MCP's command wrapper did not report success")
    results = payload.get("results")
    resources = results.get("resources") if isinstance(results, dict) else None
    if not isinstance(resources, list) or not resources:
        raise ProbeFailure("Azure MCP did not return this populated lab's resources")
    prefix = group_id.casefold() + "/"
    if any(
        not isinstance(resource, dict)
        or not isinstance(resource.get("id"), str)
        or not resource["id"].casefold().startswith(prefix)
        for resource in resources
    ):
        raise ProbeFailure("Azure MCP returned a resource outside the requested lab group")
    return len(resources)


class Results:
    def __init__(self, output: Path):
        self.output = output
        self.checks: list[dict] = []
        write_results(self.output, self.checks)

    def add(self, identifier: str, passed: bool, **observed: str | int | bool) -> None:
        self.checks.append(check(
            identifier, "live", "passed" if passed else "failed", **observed
        ))
        write_results(self.output, self.checks)
        if not passed:
            raise ProbeFailure(identifier + " failed its measured condition")

    def complete(self, identifier: str) -> None:
        self.add(identifier, True, result_count=len(self.checks))
        print(f"{identifier}: {len(self.checks)} checks passed.")
