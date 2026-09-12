import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx
import pytest

from service.arm import ARM_API_VERSION, ArmError, HttpArmResourceGroupReader
from test_service_helpers import run_async


def _reader_with(handler) -> HttpArmResourceGroupReader:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpArmResourceGroupReader(client=client)


def test_sends_the_exchanged_bearer_token_not_something_else():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"location": "eastus", "properties": {"provisioningState": "Succeeded"}})

    reader = _reader_with(handler)
    run_async(
        lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="obo-token-xyz")
    )

    assert seen["authorization"] == "Bearer obo-token-xyz"


def test_requests_the_fixed_api_version_and_url_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"location": "eastus", "properties": {}})

    reader = _reader_with(handler)
    run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert seen["url"] == (
        f"https://management.azure.com/subscriptions/sub-1/resourceGroups/rg-1?api-version={ARM_API_VERSION}"
    )


def test_sanitizes_a_successful_response_to_booleans_and_region():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "/subscriptions/sub-1/resourceGroups/rg-1",
                "name": "rg-1",
                "location": "westeurope",
                "properties": {"provisioningState": "Succeeded"},
                "tags": {"owner": "someone@example.com"},
            },
        )

    reader = _reader_with(handler)
    status = run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert status.exists is True
    assert status.region == "westeurope"
    assert status.provisioning_succeeded is True
    dumped = status.model_dump()
    assert set(dumped) == {"exists", "region", "provisioning_succeeded"}


def test_404_is_reported_as_not_existing_not_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "ResourceGroupNotFound"}})

    reader = _reader_with(handler)
    status = run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert status.exists is False
    assert status.region is None


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_failures_are_reported_as_authorization_failed(status_code):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"error": {"code": "Forbidden"}})

    reader = _reader_with(handler)
    with pytest.raises(ArmError) as exc_info:
        run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert exc_info.value.safe_code == "AuthorizationFailed"
    assert exc_info.value.http_status == status_code


def test_other_http_errors_are_reported_generically():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"code": "InternalServerError"}})

    reader = _reader_with(handler)
    with pytest.raises(ArmError) as exc_info:
        run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert exc_info.value.safe_code == "HttpError"
    assert exc_info.value.http_status == 500


def test_timeout_is_reported_as_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    reader = _reader_with(handler)
    with pytest.raises(ArmError) as exc_info:
        run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert exc_info.value.safe_code == "Timeout"


def test_connection_failure_is_reported_as_network_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    reader = _reader_with(handler)
    with pytest.raises(ArmError) as exc_info:
        run_async(lambda: reader.read(subscription_id="sub-1", resource_group="rg-1", bearer_token="t"))

    assert exc_info.value.safe_code == "NetworkUnavailable"
