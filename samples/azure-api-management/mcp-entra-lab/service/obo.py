"""On-behalf-of exchange of the inbound delegated token for an ARM token.

Uses MSAL's confidential-client OBO grant. The inbound MCP caller's own
token is used only as the `user_assertion`; it is never itself forwarded to
a downstream API. A failed exchange (including consent-required) never
raises the identity provider's free-text `error_description`: only a numeric
AADSTS code (or, failing that, a fixed safe label) crosses this boundary.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

import anyio
import msal

from .config import Config

logger = logging.getLogger(__name__)

#: The one downstream scope this lab exchanges for: Azure Resource Manager,
#: default-scoped. Never caller-configurable.
ARM_SCOPE = "https://management.azure.com/.default"

_AADSTS_RE = re.compile(r"\bAADSTS\d{5,9}\b")
_OAUTH_ERRORS = {
    "invalid_grant", "invalid_client", "server_error", "temporarily_unavailable",
    "interaction_required", "consent_required", "invalid_scope",
    "unauthorized_client", "invalid_request",
}


class OboError(Exception):
    """The on-behalf-of exchange did not produce an access token.

    `safe_code` is the only detail meant to reach a tool caller: an AADSTS
    code when the identity provider's response carried one, else a short
    fixed label. The provider's `error_description` text is discarded.
    """

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


def extract_aadsts_code(error_description: str | None) -> str | None:
    """Pull a bare `AADSTSxxxxx` code out of an AAD error description, if present."""
    if not isinstance(error_description, str):
        return None
    match = _AADSTS_RE.search(error_description)
    return match.group(0) if match else None


def _safe_failure_code(result: dict[str, Any]) -> str:
    codes = result.get("error_codes")
    if isinstance(codes, list):
        for code in codes:
            if type(code) is int and 10000 <= code <= 999999999:
                return f"AADSTS{code}"
    extracted = extract_aadsts_code(result.get("error_description"))
    if extracted:
        return extracted
    error = result.get("error")
    if isinstance(error, str) and error in _OAUTH_ERRORS:
        return error
    return "AuthorizationFailed"


class OnBehalfOfExchanger(Protocol):
    """Exchanges an inbound delegated assertion for a token in another resource's scope."""

    async def acquire_token(self, user_assertion: str, scopes: list[str]) -> str: ...  # pragma: no cover


class MsalOnBehalfOfExchanger:
    """Production exchanger backed by a real `msal.ConfidentialClientApplication`.

    The client is built lazily, on first use. `ConfidentialClientApplication.__init__`
    performs a blocking OIDC discovery call against the tenant; that does not
    belong on the path that builds the ASGI app (`create_app()`, called once
    by the ASGI server's factory, with no event loop guaranteed running yet).
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._app: msal.ConfidentialClientApplication | None = None
        self._build_lock = anyio.Lock()

    async def acquire_token(self, user_assertion: str, scopes: list[str]) -> str:
        app = await self._get_app()
        # MSAL performs blocking network I/O; keep it off the event loop.
        result = await anyio.to_thread.run_sync(self._acquire, app, user_assertion, scopes)
        if "access_token" in result:
            return result["access_token"]
        code = _safe_failure_code(result)
        logger.info("on-behalf-of exchange failed: %s", code)
        raise OboError(code)

    async def _get_app(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            async with self._build_lock:
                if self._app is None:
                    self._app = await anyio.to_thread.run_sync(self._build_app)
        return self._app

    def _build_app(self) -> msal.ConfidentialClientApplication:
        return msal.ConfidentialClientApplication(
            client_id=self._config.api_client_id,
            client_credential=self._config.api_client_secret,
            authority=f"https://login.microsoftonline.com/{self._config.tenant_id}",
            enable_pii_log=False,
        )

    @staticmethod
    def _acquire(
        app: msal.ConfidentialClientApplication, user_assertion: str, scopes: list[str]
    ) -> dict[str, Any]:
        return app.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=scopes)
