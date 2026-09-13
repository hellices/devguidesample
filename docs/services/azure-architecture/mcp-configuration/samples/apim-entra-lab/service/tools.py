"""Registers the lab's three read-only MCP tools onto an `MCPServer`.

Wiring only: each tool delegates to `obo.py` / `arm.py` / `learn.py` /
`inventory.py`. `read_lab_resource_group` is the one place that ties the
verified caller identity (`get_access_token()`) to a downstream call, and it
never has another way to get an identity: no managed-identity or
client-credential fallback if the on-behalf-of exchange fails.
"""

from __future__ import annotations

import logging

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from .arm import ArmError, ArmResourceGroupReader, ResourceGroupStatus
from .config import Config
from .inventory import FIXED_INVENTORY, LabWidget
from .learn import LearnConnector, LearnSearchError, LearnSearchResult, LearnTopic
from .obo import ARM_SCOPE, OboError, OnBehalfOfExchanger

logger = logging.getLogger(__name__)

_READ_ONLY_LOCAL = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)
_READ_ONLY_EXTERNAL = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True)


def register_tools(
    server: MCPServer,
    *,
    config: Config,
    obo_exchanger: OnBehalfOfExchanger,
    arm_reader: ArmResourceGroupReader,
    learn_connector: LearnConnector,
) -> None:
    """Add `lab_inventory`, `read_lab_resource_group` and `learn_search` to `server`."""

    def lab_inventory() -> list[LabWidget]:
        """Return a fixed, fictitious widget inventory. No live data, no identities."""
        return list(FIXED_INVENTORY)

    server.add_tool(
        lab_inventory,
        name="lab_inventory",
        description=lab_inventory.__doc__,
        annotations=_READ_ONLY_LOCAL,
    )

    async def read_lab_resource_group() -> ResourceGroupStatus:
        """Read this lab's fixed Azure resource group, via delegated on-behalf-of.

        Exchanges the caller's own MCP access token for an Azure Resource
        Manager token (the ARM_SCOPE default scope) using this server's
        confidential client, then reads one fixed resource group at
        ARM_API_VERSION. The ARM call always carries the exchanged token,
        never the caller's inbound token. Only sanitized status crosses back:
        no resource IDs or names.
        """
        access_token = get_access_token()
        if access_token is None:
            # Reachable only if this tool is ever invoked outside an
            # authenticated HTTP request (e.g. in-process); there is no
            # fallback identity to use instead.
            raise ToolError("AuthenticationFailed: no verified caller identity")

        try:
            arm_token = await obo_exchanger.acquire_token(access_token.token, [ARM_SCOPE])
        except OboError as exc:
            raise ToolError(f"ConsentRequired: {exc.safe_code}") from exc

        try:
            return await arm_reader.read(
                subscription_id=config.subscription_id,
                resource_group=config.resource_group,
                bearer_token=arm_token,
            )
        except ArmError as exc:
            detail = exc.safe_code if exc.http_status is None else f"{exc.safe_code}: {exc.http_status}"
            raise ToolError(detail) from exc

    server.add_tool(
        read_lab_resource_group,
        name="read_lab_resource_group",
        description=read_lab_resource_group.__doc__,
        annotations=_READ_ONLY_EXTERNAL,
    )

    async def learn_search(topic: LearnTopic) -> LearnSearchResult:
        """Search public Microsoft Learn documentation for one fixed topic.

        Connects to the public Learn MCP server anonymously -- this server's
        own bearer token is never attached to that outbound connection. The
        query text is one of a small set of fixed, public strings selected by
        `topic`; there is no free-text query parameter.
        """
        try:
            return await learn_connector.search(topic)
        except LearnSearchError as exc:
            raise ToolError(exc.safe_code) from exc

    server.add_tool(
        learn_search,
        name="learn_search",
        description=learn_search.__doc__,
        annotations=_READ_ONLY_EXTERNAL,
    )
