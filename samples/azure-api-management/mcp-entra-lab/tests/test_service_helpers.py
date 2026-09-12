"""Shared test helpers: ephemeral keys, token minting, and an ASGI lifespan runner.

Not a test module itself (no `test_*` functions); imported directly by the
other `test_service_*` files, which is why it still matches that glob.
Everything here is local/in-process: no real network, no real Azure calls,
no pytest plugins -- just plain asyncio primitives driving the real ASGI
lifespan protocol against the real app object.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, Callable

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from service.config import Config

TEST_KID = "test-signing-key-1"


def generate_rsa_keypair():
    """A fresh ephemeral RSA keypair, private key first."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def build_test_config(**overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "api_client_id": "22222222-2222-2222-2222-222222222222",
        "api_client_secret": "lab-secret-value",
        "resource_url": "https://mcp-lab.internal.example/mcp",
        "subscription_id": "33333333-3333-3333-3333-333333333333",
        "resource_group": "rg-mcp-lab",
        "allowed_client_ids": frozenset({"11111111-aaaa-bbbb-cccc-222222222222"}),
    }
    defaults.update(overrides)
    return Config(**defaults)


def make_claims(config: Config, **overrides: Any) -> dict[str, Any]:
    """A full set of valid Entra v2 delegated-token claims for `config`, overridable per-field."""
    now = int(time.time())
    claims = {
        "iss": config.issuer,
        "aud": config.api_client_id,
        "tid": config.tenant_id,
        "exp": now + 3600,
        "nbf": now - 10,
        "iat": now - 10,
        "oid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "scp": "Mcp.Access",
        "azp": "11111111-aaaa-bbbb-cccc-222222222222",
    }
    for key, value in overrides.items():
        if value is _OMIT:
            claims.pop(key, None)
        else:
            claims[key] = value
    return claims


class _Omit:
    def __repr__(self) -> str:
        return "OMIT"


#: Sentinel passed as a claim override in `make_claims`/`make_token` to drop that claim entirely.
OMIT = _Omit()
_OMIT = OMIT


def make_token(
    private_key,
    config: Config,
    *,
    kid: str | None = TEST_KID,
    alg: str = "RS256",
    **claim_overrides: Any,
) -> str:
    claims = make_claims(config, **claim_overrides)
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, private_key, algorithm=alg, headers=headers)


def make_hs256_confusion_token(public_key, config: Config) -> str:
    """A token claiming RS256's `kid` but signed HS256 with the RSA public key bytes as secret.

    PyJWT's own `encode()` refuses to build this (it detects the asymmetric
    key and raises), so this constructs the JWS by hand with stdlib `hmac`
    to exercise the server's algorithm allowlist against a real classic
    verification-downgrade token, not merely a call it would refuse to make.
    """
    import base64
    import hashlib
    import hmac
    import json

    from cryptography.hazmat.primitives import serialization

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    header = {"alg": "HS256", "typ": "JWT", "kid": TEST_KID}
    claims = make_claims(config)
    signing_input = (
        b64url(json.dumps(header, separators=(",", ":")).encode()) + "." + b64url(json.dumps(claims).encode())
    )
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signature = hmac.new(public_pem, signing_input.encode("ascii"), hashlib.sha256).digest()
    return signing_input + "." + b64url(signature)


@asynccontextmanager
async def running_lifespan(app: Any):
    """Drive the real ASGI lifespan protocol for `app`.

    `httpx`-style ASGI transports only forward `http` scope traffic; nothing
    starts `session_manager.run()` (the SDK's own background task group)
    unless something sends it real `lifespan.*` messages. This does exactly
    that, against the app object itself -- no shortcuts, no mocked manager.
    """
    to_app: asyncio.Queue = asyncio.Queue()
    from_app: asyncio.Queue = asyncio.Queue()

    async def receive() -> dict[str, Any]:
        return await to_app.get()

    async def send(message: dict[str, Any]) -> None:
        await from_app.put(message)

    task = asyncio.create_task(app({"type": "lifespan"}, receive, send))
    await to_app.put({"type": "lifespan.startup"})
    started = await from_app.get()
    if started["type"] != "lifespan.startup.complete":
        raise RuntimeError(f"ASGI lifespan startup failed: {started}")
    try:
        yield
    finally:
        await to_app.put({"type": "lifespan.shutdown"})
        stopped = await from_app.get()
        await task
        if stopped["type"] != "lifespan.shutdown.complete":
            raise RuntimeError(f"ASGI lifespan shutdown failed: {stopped}")


def run_async(coro_fn: Callable[[], Any]) -> Any:
    """Run one async test body. Plain `asyncio.run`; no pytest-asyncio plugin installed."""
    return asyncio.run(coro_fn())
