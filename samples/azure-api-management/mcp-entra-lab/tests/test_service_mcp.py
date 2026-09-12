import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

from service.app import create_app
from service.arm import ArmError, ResourceGroupStatus
from service.auth import StaticSigningKeyResolver
from service.learn import LearnConnector, LearnTopic
from service.obo import ARM_SCOPE, OboError
from test_service_fakes import FakeArmReader, FakeOboExchanger, build_fake_learn_asgi_app
from test_service_helpers import (
    OMIT,
    build_test_config,
    generate_rsa_keypair,
    make_token,
    run_async,
    running_lifespan,
)

PRIVATE_KEY, PUBLIC_KEY = generate_rsa_keypair()
CONFIG = build_test_config()
BASE_URL = "https://mcp-lab.internal.example"
KEY_RESOLVER = StaticSigningKeyResolver(public_key=PUBLIC_KEY)


def _build_app(**kwargs):
    return create_app(CONFIG, key_resolver=KEY_RESOLVER, **kwargs)


def _auth_header(token: str | None) -> dict[str, str]:
    return {} if token is None else {"Authorization": "Bearer " + token}


async def _post_mcp(
    app, *, token: str | None = None, raw_header: str | None = None, extra_headers: dict[str, str] | None = None
):
    # No `mcp-protocol-version` header is sent by default, which the SDK's
    # server-side routing (mcp/server/streamable_http_manager.py) treats as
    # the legacy (pre-2026-07-28) dispatch path -- see
    # `test_missing_authorization_is_401_regardless_of_protocol_version_header`
    # below for proof the auth gate rejects identically on the modern path.
    # That's fine here either way: `RequireAuthMiddleware` wraps the whole
    # streamable-http app and runs before any legacy/modern branching, so
    # every denial-mode test in this section is a pure HTTP-boundary check,
    # independent of protocol era or JSON-RPC method name.
    headers = {"Accept": "application/json, text/event-stream"}
    if raw_header is not None:
        headers["Authorization"] = raw_header
    else:
        headers.update(_auth_header(token))
    if extra_headers:
        headers.update(extra_headers)
    async with running_lifespan(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http_client:
            return await http_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                headers=headers,
            )


async def _get(app, path: str, *, token: str | None = None):
    async with running_lifespan(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http_client:
            return await http_client.get(path, headers=_auth_header(token))


@asynccontextmanager
async def connected_mcp_client(app, token: str, *, mode: str = "auto"):
    async with running_lifespan(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url=BASE_URL, headers=_auth_header(token)
        ) as http_client:
            transport = streamable_http_client(BASE_URL + "/mcp", http_client=http_client)
            async with Client(transport, mode=mode) as client:
                yield client


# ---------------------------------------------------------------------------
# Public discovery: reachable with no token at all.
# ---------------------------------------------------------------------------


def test_protected_resource_metadata_requires_no_auth_and_matches_config():
    response = run_async(lambda: _get(_build_app(), "/.well-known/oauth-protected-resource/mcp"))
    assert response.status_code == 200
    body = response.json()
    assert body["resource"] == CONFIG.resource_url
    assert body["authorization_servers"] == [CONFIG.issuer]
    assert body["scopes_supported"] == [f"api://{CONFIG.api_client_id}/Mcp.Access"]


# ---------------------------------------------------------------------------
# /mcp denial modes: every case must be refused at the HTTP boundary.
# ---------------------------------------------------------------------------


def test_missing_authorization_is_401_with_resource_metadata_pointer():
    response = run_async(lambda: _post_mcp(_build_app()))
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]


def test_missing_authorization_is_401_regardless_of_protocol_version_header():
    # Same denial with the modern per-request header present (routes through
    # mcp/server/_streamable_http_modern.py on the server side instead of the
    # legacy dispatch the header-less requests above take): proves the auth
    # gate is identical on both eras, empirically, not just by code reading.
    response = run_async(
        lambda: _post_mcp(_build_app(), extra_headers={"mcp-protocol-version": "2026-07-28"})
    )
    assert response.status_code == 401


def test_garbage_bearer_token_is_401():
    response = run_async(lambda: _post_mcp(_build_app(), raw_header="Bearer not-a-jwt"))
    assert response.status_code == 401


def test_non_bearer_authorization_scheme_is_401():
    response = run_async(lambda: _post_mcp(_build_app(), raw_header="Basic dXNlcjpwYXNz"))
    assert response.status_code == 401


def test_wrong_audience_is_401():
    token = make_token(PRIVATE_KEY, CONFIG, aud="99999999-9999-9999-9999-999999999999")
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 401


def test_wrong_issuer_is_401():
    token = make_token(PRIVATE_KEY, CONFIG, iss="https://login.microsoftonline.com/other/v2.0")
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 401


def test_expired_token_is_401():
    token = make_token(PRIVATE_KEY, CONFIG, exp=1)
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 401


def test_app_only_style_token_without_oid_is_401():
    token = make_token(PRIVATE_KEY, CONFIG, oid=OMIT, scp=OMIT)
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 401


def test_valid_token_with_wrong_scope_is_403():
    token = make_token(PRIVATE_KEY, CONFIG, scp="SomeOther.Scope")
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 403


def test_azp_not_allowlisted_is_401_when_allowlist_configured():
    config = build_test_config(allowed_client_ids=frozenset({"77777777-7777-7777-7777-777777777777"}))
    app = create_app(config, key_resolver=KEY_RESOLVER)
    token = make_token(PRIVATE_KEY, config)  # azp defaults to a value not on the list
    response = run_async(lambda: _post_mcp(app, token=token))
    assert response.status_code == 401


def test_fully_valid_token_is_accepted_at_the_http_boundary():
    # No `mcp-protocol-version` header -> legacy dispatch (server-side); this
    # is the legacy `initialize` handshake accepted at the HTTP boundary.
    token = make_token(PRIVATE_KEY, CONFIG)
    response = run_async(lambda: _post_mcp(_build_app(), token=token))
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Full protocol: initialize -> tools/list -> tools/call, over the real ASGI
# transport and lifespan, with a fully valid token.
# ---------------------------------------------------------------------------


def test_tools_list_shows_exactly_the_three_lab_tools():
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(_build_app(), token) as client:
            listing = await client.list_tools()
            return sorted(t.name for t in listing.tools)

    assert run_async(scenario) == ["lab_inventory", "learn_search", "read_lab_resource_group"]


@pytest.mark.parametrize(
    ("mode", "expect_handshake_version"),
    [
        ("2026-07-28", False),  # stable stateless per-request protocol (server/discover)
        ("legacy", True),  # pre-2026-07-28 initialize handshake, forced explicitly
    ],
)
def test_tool_call_works_over_both_the_modern_and_legacy_wire_protocol(mode, expect_handshake_version):
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(_build_app(), token, mode=mode) as client:
            result = await client.call_tool("lab_inventory", {})
            return client.protocol_version, result

    negotiated_version, result = run_async(scenario)
    if expect_handshake_version:
        assert negotiated_version in HANDSHAKE_PROTOCOL_VERSIONS
    else:
        assert negotiated_version in MODERN_PROTOCOL_VERSIONS
    assert result.is_error is False
    assert result.structured_content["result"][0]["sku"] == "WID-100"


def test_lab_inventory_tool_call_returns_the_fixed_inventory():
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(_build_app(), token) as client:
            return await client.call_tool("lab_inventory", {})

    result = run_async(scenario)
    assert result.is_error is False
    skus = [item["sku"] for item in result.structured_content["result"]]
    assert skus == ["WID-100", "WID-200", "WID-300"]


def test_read_lab_resource_group_uses_the_exchanged_token_never_the_inbound_one():
    fake_obo = FakeOboExchanger(token="downstream-arm-token")
    fake_arm = FakeArmReader(
        status=ResourceGroupStatus(exists=True, region="eastus", provisioning_succeeded=True)
    )
    app = _build_app(obo_exchanger=fake_obo, arm_reader=fake_arm)
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(app, token) as client:
            return await client.call_tool("read_lab_resource_group", {})

    result = run_async(scenario)

    assert result.is_error is False
    assert result.structured_content["exists"] is True
    assert result.structured_content["region"] == "eastus"
    assert result.structured_content["provisioning_succeeded"] is True
    # no resource id or name in the tool result at all
    assert "id" not in result.structured_content
    assert "name" not in result.structured_content

    [obo_call] = fake_obo.calls
    assert obo_call == (token, [ARM_SCOPE])  # exact downstream scope ("aud"), and the inbound token as assertion

    [arm_call] = fake_arm.calls
    assert arm_call["bearer_token"] == "downstream-arm-token"
    assert arm_call["bearer_token"] != token  # ARM never sees the inbound MCP token
    assert arm_call["subscription_id"] == CONFIG.subscription_id
    assert arm_call["resource_group"] == CONFIG.resource_group


def test_read_lab_resource_group_obo_consent_failure_is_a_safe_tool_error():
    fake_obo = FakeOboExchanger(error=OboError("AADSTS65001"))
    app = _build_app(obo_exchanger=fake_obo, arm_reader=FakeArmReader())
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(app, token) as client:
            return await client.call_tool("read_lab_resource_group", {})

    result = run_async(scenario)

    assert result.is_error is True
    assert result.structured_content is None  # no fabricated successful result
    text = result.content[0].text
    assert "AADSTS65001" in text


def test_read_lab_resource_group_arm_error_is_a_safe_tool_error_not_a_crash():
    fake_obo = FakeOboExchanger(token="downstream-arm-token")
    fake_arm = FakeArmReader(error=ArmError("AuthorizationFailed", 403))
    app = _build_app(obo_exchanger=fake_obo, arm_reader=fake_arm)
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(app, token) as client:
            return await client.call_tool("read_lab_resource_group", {})

    result = run_async(scenario)
    assert result.is_error is True
    assert "AuthorizationFailed" in result.content[0].text


def test_learn_search_discovers_and_calls_the_fake_search_tool_anonymously():
    captured_requests: list[dict[str, str]] = []
    fake_learn_app = build_fake_learn_asgi_app(captured_requests=captured_requests)

    def transport_factory():
        fake_http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=fake_learn_app), base_url="https://learn.fake.test"
        )
        return streamable_http_client("https://learn.fake.test/mcp", http_client=fake_http_client)

    learn_connector = LearnConnector(transport_factory=transport_factory)
    app = _build_app(learn_connector=learn_connector)
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with running_lifespan(fake_learn_app):
            async with connected_mcp_client(app, token) as client:
                return await client.call_tool(
                    "learn_search", {"topic": LearnTopic.AZURE_API_MANAGEMENT.value}
                )

    result = run_async(scenario)

    assert result.is_error is False
    assert result.structured_content["tool_used"] == "microsoft_docs_search"
    assert "Azure API Management overview" in result.structured_content["results"][0]["title"]

    # The fake Learn server must never see this server's own inbound bearer token.
    assert len(captured_requests) > 0
    assert all("authorization" not in headers for headers in captured_requests)


def test_learn_search_works_when_forced_over_the_legacy_wire_protocol():
    # The real public Learn MCP server currently speaks only the legacy
    # (pre-2026-07-28) initialize handshake; LearnConnector's default `mode`
    # ("auto") is what actually downgrades to it in production. This proves
    # the connector's *own* logic (discovery-by-name, parameter-picking,
    # result-parsing) is correct over that wire protocol specifically, not
    # merely that the SDK negotiates it -- forcing `mode="legacy"` here
    # rather than relying on the fake (modern-capable) server picking legacy
    # on its own.
    captured_requests: list[dict[str, str]] = []
    fake_learn_app = build_fake_learn_asgi_app(captured_requests=captured_requests)

    def transport_factory():
        fake_http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=fake_learn_app), base_url="https://learn.fake.test"
        )
        return streamable_http_client("https://learn.fake.test/mcp", http_client=fake_http_client)

    learn_connector = LearnConnector(transport_factory=transport_factory, mode="legacy")
    app = _build_app(learn_connector=learn_connector)
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with running_lifespan(fake_learn_app):
            async with connected_mcp_client(app, token) as client:
                return await client.call_tool(
                    "learn_search", {"topic": LearnTopic.ENTRA_ID.value}
                )

    result = run_async(scenario)

    assert result.is_error is False
    assert result.structured_content["tool_used"] == "microsoft_docs_search"
    assert "Microsoft Entra ID overview" in result.structured_content["results"][0]["title"]
    assert all("authorization" not in headers for headers in captured_requests)


def test_learn_search_topic_is_a_closed_enum_not_free_text():
    token = make_token(PRIVATE_KEY, CONFIG)

    async def scenario():
        async with connected_mcp_client(_build_app(), token) as client:
            listing = await client.list_tools()
            tool = next(t for t in listing.tools if t.name == "learn_search")
            return tool.input_schema

    schema = run_async(scenario)
    topic_schema = schema["properties"]["topic"]
    # A pydantic enum parameter is a `$ref` to a `$defs` entry carrying the
    # closed `enum` list -- not a free-text string field.
    ref = topic_schema["$ref"].removeprefix("#/$defs/")
    resolved = schema["$defs"][ref]
    assert resolved["type"] == "string"
    assert set(resolved["enum"]) == {t.value for t in LearnTopic}
