"""Public health and fictitious REST inventory; delegated operations use MCP."""

from __future__ import annotations

import re
import secrets

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from mcp.server import MCPServer
from .inventory import lab_inventory_as_dicts


def register_rest_routes(server: MCPServer) -> None:

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
