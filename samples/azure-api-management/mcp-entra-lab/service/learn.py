"""Read-only connector to the public Microsoft Learn MCP server.

Always connects anonymously: this server's own inbound bearer token is never
attached to this outbound connection, regardless of who called `learn_search`
or what auth this server enforces on `/mcp`. The caller picks a topic from a
fixed enum; the actual query text sent upstream is one of a small set of
fixed, public strings, never caller-supplied free text.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any

import httpx2
from pydantic import BaseModel

from mcp import Client
from mcp.shared.exceptions import MCPError

logger = logging.getLogger(__name__)

LEARN_MCP_URL = "https://learn.microsoft.com/api/mcp"

# The documented, stable tool name (per current Microsoft Learn MCP docs).
_KNOWN_SEARCH_TOOL_NAME = "microsoft_docs_search"
# Fallback discovery if the stable name ever changes: match by shape instead.
_SEARCH_NAME_HINTS = ("search",)
_SEARCH_DESC_HINTS = ("microsoft", "docs", "documentation", "learn")

_MAX_RESULTS = 5
_SNIPPET_LENGTH = 500


class LearnTopic(str, Enum):
    """A fixed, safe set of public topics. There is no free-text query input."""

    AZURE_API_MANAGEMENT = "azure-api-management"
    AZURE_CONTAINER_APPS = "azure-container-apps"
    ENTRA_ID = "entra-id"
    MODEL_CONTEXT_PROTOCOL = "model-context-protocol"


_TOPIC_QUERIES: dict[LearnTopic, str] = {
    LearnTopic.AZURE_API_MANAGEMENT: "Azure API Management overview",
    LearnTopic.AZURE_CONTAINER_APPS: "Azure Container Apps overview",
    LearnTopic.ENTRA_ID: "Microsoft Entra ID overview",
    LearnTopic.MODEL_CONTEXT_PROTOCOL: "Model Context Protocol overview",
}


class LearnSearchError(Exception):
    """A Learn search failed. `safe_code` is the only detail meant to reach a caller."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class LearnResultItem(BaseModel):
    title: str
    snippet: str


class LearnSearchResult(BaseModel):
    topic: LearnTopic
    tool_used: str
    results: list[LearnResultItem]


def _looks_like_search_tool(tool: Any) -> bool:
    name = (tool.name or "").lower()
    if name == _KNOWN_SEARCH_TOOL_NAME:
        return True
    description = (tool.description or "").lower()
    return any(hint in name for hint in _SEARCH_NAME_HINTS) and any(
        hint in description for hint in _SEARCH_DESC_HINTS
    )


def _pick_query_parameter(tool: Any) -> str:
    schema = tool.input_schema or {}
    properties = schema.get("properties") or {}
    if "query" in properties:
        return "query"
    for name in schema.get("required") or []:
        if properties.get(name, {}).get("type") == "string":
            return name
    for name, spec in properties.items():
        if isinstance(spec, dict) and spec.get("type") == "string":
            return name
    raise LearnSearchError("Unsupported")


def _parse_results(raw_text: str) -> list[LearnResultItem]:
    try:
        payload = json.loads(raw_text)
        raw_results = payload["results"]
        if not isinstance(raw_results, list):
            raise TypeError("results is not a list")
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("learn search returned an unsupported result structure")
        raise LearnSearchError("Unsupported") from exc

    items: list[LearnResultItem] = []
    for entry in raw_results[:_MAX_RESULTS]:
        if not isinstance(entry, dict):
            logger.warning("learn search returned an invalid result entry")
            raise LearnSearchError("Unsupported")
        title = str(entry.get("title") or "untitled")
        snippet = str(entry.get("content") or entry.get("snippet") or "")[:_SNIPPET_LENGTH]
        items.append(LearnResultItem(title=title, snippet=snippet))
    return items


class LearnConnector:
    """Anonymous Learn connection; the SDK negotiates the upstream revision."""

    async def search(self, topic: LearnTopic) -> LearnSearchResult:
        try:
            return await self._search(topic)
        except* (MCPError, httpx2.HTTPError):
            logger.warning("learn connection, discovery or call failed")
            raise LearnSearchError("McpError") from None

    async def _search(self, topic: LearnTopic) -> LearnSearchResult:
        query = _TOPIC_QUERIES[topic]

        async with Client(LEARN_MCP_URL) as client:
            listing = await client.list_tools()
            tool = next(
                (t for t in listing.tools if t.name == _KNOWN_SEARCH_TOOL_NAME), None
            )
            if tool is None:
                candidates = [t for t in listing.tools if _looks_like_search_tool(t)]
                tool = candidates[0] if len(candidates) == 1 else None
            if tool is None:
                logger.info("learn search failed: no recognizable search tool advertised")
                raise LearnSearchError("Unsupported")

            param_name = _pick_query_parameter(tool)
            result = await client.call_tool(tool.name, {param_name: query})

            if result.is_error:
                logger.info("learn search failed: tool reported is_error")
                raise LearnSearchError("McpError")

            text_items = [c.text for c in result.content if getattr(c, "type", None) == "text"]
            if not text_items:
                raise LearnSearchError("Unsupported")

            return LearnSearchResult(
                topic=topic,
                tool_used=tool.name,
                results=_parse_results(text_items[0]),
            )
