"""Entra ID v2 delegated-token verification for the MCP resource server.

Implements the SDK's `TokenVerifier` protocol against one fixed tenant and
one fixed application (audience). App-only tokens can carry a service
principal `oid`; the required delegated scope is enforced separately at
the HTTP boundary. Rejections log reason labels, not tokens or claim values.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

import anyio
import jwt

from mcp.server.auth.provider import AccessToken, TokenVerifier

from .config import Config, REQUIRED_SCOPE

logger = logging.getLogger(__name__)

#: Entra v2 access tokens for this lab are always RS256; anything else
#: (including "none" or an HMAC algorithm run against the RSA public key,
#: the classic verification-downgrade attack) is rejected before the key
#: resolver or `jwt.decode` ever sees the token.
_ALGORITHM = "RS256"


class SigningKeyResolver(Protocol):
    """Resolves a JWT `kid` to the public key material `jwt.decode` verifies against."""

    def resolve(self, kid: str | None) -> Any: ...  # pragma: no cover - protocol


class EntraJwksResolver:
    """Production resolver: fetches and caches signing keys from the tenant's JWKS endpoint."""

    def __init__(self, jwks_uri: str) -> None:
        self._client = jwt.PyJWKClient(jwks_uri, lifespan=300)

    def resolve(self, kid: str | None) -> Any:
        if not kid:
            raise jwt.InvalidTokenError("token header is missing 'kid'")
        return self._client.get_signing_key(kid).key


class EntraTokenVerifier(TokenVerifier):
    """Verifies bearer tokens issued by one fixed Entra tenant for one fixed application."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._key_resolver: SigningKeyResolver = EntraJwksResolver(config.jwks_uri)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            logger.info("rejected bearer token: unparseable header")
            return None

        if header.get("alg") != _ALGORITHM:
            logger.info("rejected bearer token: unsupported algorithm")
            return None

        try:
            signing_key = await anyio.to_thread.run_sync(
                self._key_resolver.resolve, header.get("kid")
            )
        except jwt.PyJWKClientConnectionError:
            # The JWKS endpoint is unreachable: our backend is broken, the
            # presented token was never actually evaluated. Surface this as a
            # server error rather than reporting it as an invalid token.
            raise
        except jwt.PyJWTError:
            logger.info("rejected bearer token: signing key not resolvable")
            return None

        try:
            claims = jwt.decode(
                token,
                key=signing_key,
                algorithms=[_ALGORITHM],
                audience=self._config.api_client_id,
                issuer=self._config.issuer,
                options={"require": ["exp", "nbf"]},
            )
        except jwt.PyJWTError as exc:
            logger.info("rejected bearer token: %s", type(exc).__name__)
            return None

        if claims.get("tid") != self._config.tenant_id:
            logger.info("rejected bearer token: tid mismatch")
            return None

        oid = claims.get("oid")
        if not oid:
            logger.info("rejected bearer token: missing oid (not a delegated user token)")
            return None

        raw_scopes = claims.get("scp", "")
        # Entra emits bare scp values; OAuth metadata advertises qualified scopes.
        scopes = (
            [self._config.scope_prefix + value for value in raw_scopes.split()]
            if isinstance(raw_scopes, str) else []
        )
        # Deliberately not rejected here even if `REQUIRED_SCOPE` is absent:
        # a structurally valid delegated token with the wrong scope must
        # still become an `AccessToken` (with its real, possibly-insufficient
        # scopes) so the SDK's own scope check reports 403, not 401. Rejecting
        # it here instead would report every wrong-scope token as "no token".

        azp = claims.get("azp")
        if not isinstance(azp, str) or azp.lower() not in self._config.allowed_client_ids:
            logger.info("rejected bearer token: azp not allowlisted")
            return None

        return AccessToken(
            token=token,
            client_id=azp,
            scopes=scopes,
            expires_at=claims.get("exp"),
            # Only set once aud has been validated above: this reflects the
            # canonical MCP endpoint, never the raw `aud` claim value.
            resource=self._config.resource_url,
            subject=oid,
            claims=claims,
        )
