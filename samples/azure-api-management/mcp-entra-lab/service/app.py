"""ASGI application factory: `service.app:create_app`.

Wires config, the Entra token verifier, and the three read-only tools onto
one `MCPServer`, then returns its Streamable HTTP ASGI app. Called with no
arguments this is the real production wiring (`uvicorn service.app:create_app
--factory`); the keyword-only parameters exist so tests can substitute
ephemeral keys and fake network-facing dependencies without touching this
module's default behavior.
"""

from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit

from starlette.applications import Starlette

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings

from .arm import ArmResourceGroupReader, HttpArmResourceGroupReader
from .auth import EntraTokenVerifier, SigningKeyResolver
from .config import Config, load_config
from .learn import LearnConnector
from .obo import MsalOnBehalfOfExchanger, OnBehalfOfExchanger
from .rest import register_rest_routes
from .tools import register_tools

SERVER_NAME = "azure-mcp-entra-lab"
SERVER_VERSION = "0.1.0"
SERVER_INSTRUCTIONS = (
    "Read-only Azure MCP + Entra delegated-OBO lab: a fixed fictitious "
    "inventory, one on-behalf-of Azure Resource Manager resource-group "
    "read, and public Microsoft Learn documentation search."
)


def _transport_security_for(resource_url: str) -> TransportSecuritySettings:
    """Allowlist exactly the hostname clients use to reach this server.

    Derived from `MCP_RESOURCE_URL` so there is no separate hostname setting
    to keep in sync, and so DNS-rebinding protection stays on (unlike
    disabling it outright) even though this server's real hostname is not
    known until deploy time.
    """
    hostname = urlsplit(resource_url).hostname
    if not hostname:
        raise ValueError(f"resource_url has no hostname: {resource_url!r}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[hostname, f"{hostname}:*"],
        allowed_origins=[f"https://{hostname}", f"https://{hostname}:*"],
    )


def create_app(
    config: Config | None = None,
    *,
    key_resolver: SigningKeyResolver | None = None,
    obo_exchanger: OnBehalfOfExchanger | None = None,
    arm_reader: ArmResourceGroupReader | None = None,
    learn_connector: LearnConnector | None = None,
    env: Mapping[str, str] | None = None,
) -> Starlette:
    """Build the ASGI app. Raises `ConfigError` if the environment is invalid.

    `config` and the four dependency keywords are test-only seams; production
    use (`create_app()` with no arguments) loads `Config` from the real
    process environment and talks to real Entra, ARM and Learn endpoints.
    """
    cfg = config or load_config(env if env is not None else os.environ)

    verifier = EntraTokenVerifier(cfg, key_resolver=key_resolver)
    auth_settings = AuthSettings(
        issuer_url=cfg.issuer,
        resource_server_url=cfg.resource_url,
        required_scopes=[cfg.scope_uri],
        validate_token_resource=True,
    )

    server: MCPServer = MCPServer(
        SERVER_NAME,
        version=SERVER_VERSION,
        instructions=SERVER_INSTRUCTIONS,
        token_verifier=verifier,
        auth=auth_settings,
    )

    resolved_obo = obo_exchanger or MsalOnBehalfOfExchanger(cfg)
    resolved_arm = arm_reader or HttpArmResourceGroupReader()
    resolved_learn = learn_connector or LearnConnector()

    register_tools(
        server,
        config=cfg,
        obo_exchanger=resolved_obo,
        arm_reader=resolved_arm,
        learn_connector=resolved_learn,
    )
    register_rest_routes(
        server,
        config=cfg,
        obo_exchanger=resolved_obo,
        arm_reader=resolved_arm,
    )

    return server.streamable_http_app(transport_security=_transport_security_for(cfg.resource_url))
