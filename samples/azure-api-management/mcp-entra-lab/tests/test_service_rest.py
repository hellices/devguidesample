import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx2

from service.app import create_app
from service.arm import ArmError, ResourceGroupStatus
from service.auth import StaticSigningKeyResolver
from service.obo import ARM_SCOPE, OboError
from test_service_fakes import FakeArmReader, FakeOboExchanger
from test_service_helpers import (
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


async def _get(app, path: str, *, token: str | None = None):
    headers = {} if token is None else {"Authorization": "Bearer " + token}
    async with running_lifespan(app):
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as http_client:
            return await http_client.get(path, headers=headers)


# ---------------------------------------------------------------------------
# /healthz: public liveness probe.
# ---------------------------------------------------------------------------


def test_healthz_requires_no_auth_and_reports_ok():
    response = run_async(lambda: _get(_build_app(), "/healthz"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# /inventory: harmless fixture backend, deliberately unauthenticated here.
# ---------------------------------------------------------------------------


def test_inventory_requires_no_auth_and_returns_the_fixed_fixture():
    response = run_async(lambda: _get(_build_app(), "/inventory"))
    assert response.status_code == 200
    widgets = response.json()["widgets"]
    assert [w["sku"] for w in widgets] == ["WID-100", "WID-200", "WID-300"]
    # fixture only: no identity-shaped fields
    assert all(set(w) == {"sku", "name", "quantity", "unit"} for w in widgets)
    assert response.json()["authorization_present"] is False


def test_inventory_rejects_forwarded_bearer_without_exposing_its_value():
    token = make_token(PRIVATE_KEY, CONFIG)
    response = run_async(lambda: _get(_build_app(), "/inventory", token=token))
    assert response.status_code == 400
    assert response.json()["error"] == "unexpected_authorization_header"
    assert token not in response.text


# ---------------------------------------------------------------------------
# /delegated-resource-group: protected REST counterpart of the MCP tool.
# `custom_route` does not enforce auth by itself, so this route must.
# ---------------------------------------------------------------------------


def test_delegated_resource_group_without_a_token_is_401():
    response = run_async(lambda: _get(_build_app(), "/delegated-resource-group"))
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")


def test_delegated_resource_group_with_wrong_scope_is_403():
    token = make_token(PRIVATE_KEY, CONFIG, scp="SomeOther.Scope")
    response = run_async(lambda: _get(_build_app(), "/delegated-resource-group", token=token))
    assert response.status_code == 403


def test_delegated_resource_group_with_expired_token_is_401():
    token = make_token(PRIVATE_KEY, CONFIG, exp=1)
    response = run_async(lambda: _get(_build_app(), "/delegated-resource-group", token=token))
    assert response.status_code == 401


def test_delegated_resource_group_success_matches_the_mcp_tool_shape():
    fake_obo = FakeOboExchanger(token="downstream-arm-token")
    fake_arm = FakeArmReader(
        status=ResourceGroupStatus(exists=True, region="westus2", provisioning_succeeded=True)
    )
    app = _build_app(obo_exchanger=fake_obo, arm_reader=fake_arm)
    token = make_token(PRIVATE_KEY, CONFIG)

    response = run_async(lambda: _get(app, "/delegated-resource-group", token=token))

    assert response.status_code == 200
    assert response.json() == {"exists": True, "region": "westus2", "provisioning_succeeded": True}
    [obo_call] = fake_obo.calls
    assert obo_call == (token, [ARM_SCOPE])
    [arm_call] = fake_arm.calls
    assert arm_call["bearer_token"] == "downstream-arm-token"


def test_delegated_resource_group_obo_failure_returns_a_safe_error_body():
    fake_obo = FakeOboExchanger(error=OboError("AADSTS65001"))
    app = _build_app(obo_exchanger=fake_obo, arm_reader=FakeArmReader())
    token = make_token(PRIVATE_KEY, CONFIG)

    response = run_async(lambda: _get(app, "/delegated-resource-group", token=token))

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "AADSTS65001"


def test_delegated_resource_group_arm_failure_returns_a_safe_error_body():
    fake_obo = FakeOboExchanger(token="downstream-arm-token")
    fake_arm = FakeArmReader(error=ArmError("AuthorizationFailed", 403))
    app = _build_app(obo_exchanger=fake_obo, arm_reader=fake_arm)
    token = make_token(PRIVATE_KEY, CONFIG)

    response = run_async(lambda: _get(app, "/delegated-resource-group", token=token))

    assert response.status_code == 502
    assert response.json()["error"] == "AuthorizationFailed"
