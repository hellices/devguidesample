from pathlib import Path
import re
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parent))

import anyio
import httpx2
import pytest

from service.app import create_app
from service.auth import EntraTokenVerifier, StaticSigningKeyResolver
from service.config import ConfigError, load_config
from service.learn import LearnSearchError, _parse_results
from service.obo import _safe_failure_code
from test_service_config import VALID_ENV
from test_service_helpers import (
    OMIT, build_test_config, generate_rsa_keypair, make_token, run_async, running_lifespan,
)


PRIVATE_KEY, PUBLIC_KEY = generate_rsa_keypair()
CONFIG = build_test_config()


def app():
    return create_app(CONFIG, key_resolver=StaticSigningKeyResolver(PUBLIC_KEY))


def test_inventory_has_fresh_safe_correlation_for_real_rest_invocations():
    async def scenario():
        server = app()
        async with running_lifespan(server):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(server), base_url="https://mcp-lab.internal.example"
            ) as client:
                first = await client.get("/inventory", headers={"x-lab-probe-id": "a1b2c3d4e5f60708"})
                second = await client.get("/inventory")
                return first.json(), second.json()

    first, second = run_async(scenario)
    assert first["source"] == "inventory-rest"
    assert first["probe_id"] == "a1b2c3d4e5f60708"
    assert re.fullmatch(r"[a-f0-9]{32}", first["invocation_id"])
    assert first["invocation_id"] != second["invocation_id"]
    assert "probe_id" not in second
    assert first["widgets"] == second["widgets"]


def test_inventory_does_not_echo_arbitrary_header_content():
    async def scenario():
        server = app()
        async with running_lifespan(server):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(server), base_url="https://mcp-lab.internal.example"
            ) as client:
                return await client.get("/inventory", headers={"x-lab-probe-id": "private-value"})

    response = run_async(scenario)
    assert response.status_code == 400
    assert "private-value" not in response.text


@pytest.mark.parametrize("text", ["not-json", '{"results":{}}', '{"results":[null]}'])
def test_malformed_learn_results_are_not_success_shaped(text):
    with pytest.raises(LearnSearchError):
        _parse_results(text)


@pytest.mark.parametrize(
    "result", [{"error_codes": ["private-value"]}, {"error": "private-value"}]
)
def test_obo_failure_never_reflects_unapproved_error_text(result):
    code = _safe_failure_code(result)
    assert "private-value" not in code
    assert code == "AuthorizationFailed"


@pytest.mark.parametrize(
    "url", [
        "https://user:password@mcp-lab.internal.example/mcp",
        "https://mcp-lab.internal.example/mcp?secret=example",
        "https://mcp-lab.internal.example/mcp#fragment",
        "https://mcp-lab.internal.example/wrong-path",
    ],
)
def test_resource_metadata_url_cannot_expose_credentials_or_wrong_route(url):
    with pytest.raises(ConfigError):
        load_config({**VALID_ENV, "MCP_RESOURCE_URL": url})


def test_sdk_rejects_a_verified_token_for_a_different_resource(monkeypatch):
    original = EntraTokenVerifier.verify_token

    async def wrong_resource(self, token):
        verified = await original(self, token)
        assert verified is not None
        return verified.model_copy(update={"resource": "https://different.internal.example/mcp"})

    monkeypatch.setattr(EntraTokenVerifier, "verify_token", wrong_resource)

    async def scenario():
        server = app()
        async with running_lifespan(server):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(server), base_url="https://mcp-lab.internal.example"
            ) as client:
                return await client.post(
                    "/mcp",
                    headers={
                        "Authorization": "Bearer " + make_token(PRIVATE_KEY, CONFIG),
                        "Accept": "application/json, text/event-stream",
                    },
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                )

    assert run_async(scenario).status_code in (401, 403)


def test_app_only_token_with_service_principal_oid_is_still_denied():
    async def scenario():
        server = app()
        token = make_token(PRIVATE_KEY, CONFIG, scp=OMIT, idtyp="app")
        async with running_lifespan(server):
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(server), base_url="https://mcp-lab.internal.example"
            ) as client:
                return await client.post(
                    "/mcp", headers={"Authorization": "Bearer " + token},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                )

    assert run_async(scenario).status_code in (401, 403)


def test_jwks_network_lookup_does_not_block_the_event_loop():
    started, release = Event(), Event()
    completed_without_blocking = []

    class Resolver:
        def resolve(self, kid):
            started.set()
            completed_without_blocking.append(release.wait(timeout=2))
            return PUBLIC_KEY

    async def scenario():
        verifier = EntraTokenVerifier(CONFIG, key_resolver=Resolver())
        async with anyio.create_task_group() as group:
            group.start_soon(verifier.verify_token, make_token(PRIVATE_KEY, CONFIG))
            await anyio.to_thread.run_sync(started.wait)
            release.set()

    run_async(scenario)
    assert completed_without_blocking == [True]
