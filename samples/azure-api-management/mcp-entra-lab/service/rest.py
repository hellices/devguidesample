"""Custom HTTP routes alongside the MCP endpoint.

`MCPServer.custom_route()` registrations are never authenticated by the SDK
(routes added this way bypass `RequireAuthMiddleware` entirely) -- that is
correct for `/healthz` and `/inventory`, which are meant to be reachable with
no token. `/delegated-resource-group` is the one route here that carries
protected data, so it enforces its own auth explicitly, reusing the same
`TokenVerifier`-backed identity (`get_access_token()`) the `/mcp` route uses,
and answering with the same 401/403 shape.
"""

from __future__ import annotations

import re
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token

from .arm import ArmError, ArmResourceGroupReader
from .auth import REQUIRED_SCOPE
from .config import Config
from .inventory import lab_inventory_as_dicts
from .obo import ARM_SCOPE, OboError, OnBehalfOfExchanger

_WWW_AUTHENTICATE_INVALID_TOKEN = "Bearer error=\"invalid_token\""


def _unauthorized() -> Response:
    return JSONResponse(
        {"error": "invalid_token", "error_description": "Authentication required"},
        status_code=401,
        headers={"WWW-Authenticate": _WWW_AUTHENTICATE_INVALID_TOKEN},
    )


def _forbidden() -> Response:
    return JSONResponse(
        {"error": "insufficient_scope", "error_description": "Required scope: " + REQUIRED_SCOPE},
        status_code=403,
    )


def register_rest_routes(
    server: MCPServer,
    *,
    config: Config,
    obo_exchanger: OnBehalfOfExchanger,
    arm_reader: ArmResourceGroupReader,
) -> None:
    """Add `/healthz`, `/inventory` and `/delegated-resource-group` to `server`."""

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(request: Request) -> Response:
        """Public liveness probe. No sensitive data, no auth."""
        return JSONResponse({"status": "ok"})

    @server.custom_route("/inventory", methods=["GET"])
    async def inventory(request: Request) -> Response:
        """Harmless fixture backend for APIM REST wrapping.

        Fixed, fictitious data -- not a live read of anything -- and
        deliberately unauthenticated at this layer. Any access control for a
        real deployment is APIM/network policy in front of this container,
        which is outside this component's scope.
        """
        if "authorization" in request.headers:
            return JSONResponse({"error": "unexpected_authorization_header"}, status_code=400)
        probe_id = request.headers.get("x-lab-probe-id")
        if probe_id is not None and not re.fullmatch(r"[a-f0-9]{16}", probe_id):
            return JSONResponse({"error": "invalid_probe_id"}, status_code=400)
        body = {
            "source": "inventory-rest",
            "widgets": lab_inventory_as_dicts(),
            "invocation_id": secrets.token_hex(16),
            "authorization_present": False,
        }
        if probe_id is not None:
            body["probe_id"] = probe_id
        return JSONResponse(body)

    @server.custom_route("/delegated-resource-group", methods=["GET"])
    async def delegated_resource_group(request: Request) -> Response:
        """Protected REST counterpart of the `read_lab_resource_group` MCP tool."""
        access_token = get_access_token()
        if access_token is None:
            return _unauthorized()
        if config.scope_uri not in access_token.scopes:
            return _forbidden()

        try:
            arm_token = await obo_exchanger.acquire_token(access_token.token, [ARM_SCOPE])
        except OboError as exc:
            return JSONResponse(
                {"error": "ConsentRequired", "error_code": exc.safe_code}, status_code=502
            )

        try:
            status = await arm_reader.read(
                subscription_id=config.subscription_id,
                resource_group=config.resource_group,
                bearer_token=arm_token,
            )
        except ArmError as exc:
            return JSONResponse({"error": exc.safe_code}, status_code=502)

        return JSONResponse(status.model_dump())
