"""Entra-protected MCP server with inventory, ARM OBO and Learn tools."""

import os
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from .arm import HttpArmResourceGroupReader
from .auth import EntraTokenVerifier
from .config import load_config
from .learn import LearnConnector
from .obo import MsalOnBehalfOfExchanger
from .rest import register_rest_routes
from .tools import register_tools


def create_app() -> Starlette:
    config = load_config(os.environ)
    hostname = urlsplit(config.resource_url).hostname
    server = MCPServer(
        "azure-mcp-entra-lab",
        version="0.2.0",
        token_verifier=EntraTokenVerifier(config),
        auth=AuthSettings(
            issuer_url=config.issuer,
            resource_server_url=config.resource_url,
            required_scopes=[config.scope_uri],
            validate_token_resource=True,
        ),
    )
    register_tools(
        server,
        config=config,
        obo_exchanger=MsalOnBehalfOfExchanger(config),
        arm_reader=HttpArmResourceGroupReader(),
        learn_connector=LearnConnector(),
    )
    register_rest_routes(server)
    return server.streamable_http_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[hostname, f"{hostname}:443"],
            allowed_origins=[f"https://{hostname}", f"https://{hostname}:443"],
        )
    )
