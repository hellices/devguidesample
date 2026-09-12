"""Fake dependency implementations for `create_app`'s test-only seams.

Not a test module itself (no `test_*` functions). Each fake records what it
was called with, so a test can assert exactly what crossed the boundary
(which token, which scope) instead of only that a call happened.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from service.arm import ArmError, ResourceGroupStatus
from service.obo import OboError


class FakeOboExchanger:
    """Records every `acquire_token` call; returns a fixed token or raises a fixed error."""

    def __init__(self, *, token: str = "fake-arm-token", error: OboError | None = None) -> None:
        self.calls: list[tuple[str, list[str]]] = []
        self._token = token
        self._error = error

    async def acquire_token(self, user_assertion: str, scopes: list[str]) -> str:
        self.calls.append((user_assertion, list(scopes)))
        if self._error is not None:
            raise self._error
        return self._token


class FakeArmReader:
    """Records every `read` call; returns a fixed status or raises a fixed error."""

    def __init__(
        self, *, status: ResourceGroupStatus | None = None, error: ArmError | None = None
    ) -> None:
        self.calls: list[dict[str, str]] = []
        self._status = status or ResourceGroupStatus(
            exists=True, region="eastus", provisioning_succeeded=True
        )
        self._error = error

    async def read(
        self, *, subscription_id: str, resource_group: str, bearer_token: str
    ) -> ResourceGroupStatus:
        self.calls.append(
            {
                "subscription_id": subscription_id,
                "resource_group": resource_group,
                "bearer_token": bearer_token,
            }
        )
        if self._error is not None:
            raise self._error
        return self._status


def build_fake_learn_asgi_app(*, captured_requests: list[dict[str, str]]):
    """An in-process fake of the public Learn MCP server.

    Registers a real `microsoft_docs_search`-shaped tool on a real
    `MCPServer`, and wraps its ASGI app to record the headers of every HTTP
    request it receives -- so a test can assert the real `LearnConnector`
    never attaches this server's own inbound bearer token to it.
    """
    fake_learn = MCPServer("fake-learn")

    def microsoft_docs_search(query: str) -> str:
        """Search official Microsoft/Azure documentation (fake, in-process)."""
        payload = {"results": [{"title": "Result for " + query, "content": "fake snippet content"}]}
        return json.dumps(payload)

    fake_learn.add_tool(microsoft_docs_search, name="microsoft_docs_search")
    # This fake is reached as "https://learn.fake.test", not localhost; the
    # SDK's default DNS-rebinding allowlist would 421 every request behind a
    # hostname it does not recognize (see docs/run/deploy.md). Turning the
    # check off is correct for this in-process double, same as the docs'
    # guidance for a reverse proxy that already controls Host.
    inner_app = fake_learn.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    async def capturing_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            captured_requests.append(headers)
        await inner_app(scope, receive, send)

    return capturing_app
