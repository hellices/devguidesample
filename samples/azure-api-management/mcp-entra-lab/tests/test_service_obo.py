import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from service.obo import ARM_SCOPE, MsalOnBehalfOfExchanger, OboError, extract_aadsts_code
from test_service_helpers import build_test_config, run_async


def test_extract_aadsts_code_finds_a_code_in_free_text():
    description = "AADSTS65001: Due to a configuration change made by your administrator..."
    assert extract_aadsts_code(description) == "AADSTS65001"


def test_extract_aadsts_code_returns_none_when_absent():
    assert extract_aadsts_code("some unrelated failure text") is None
    assert extract_aadsts_code(None) is None


def test_constructing_the_exchanger_does_not_perform_network_io():
    # Regression test: `msal.ConfidentialClientApplication.__init__` performs
    # blocking OIDC discovery; the real MSAL client must be built lazily, not
    # at `create_app()` time, or building the ASGI app requires live network.
    config = build_test_config(tenant_id="00000000-0000-0000-0000-000000000000")
    start = time.monotonic()
    exchanger = MsalOnBehalfOfExchanger(config)
    elapsed = time.monotonic() - start

    assert exchanger._app is None
    assert elapsed < 1.0


class _StubMsalApp:
    def __init__(self, result: dict):
        self.calls: list[tuple[str, list[str]]] = []
        self._result = result

    def acquire_token_on_behalf_of(self, user_assertion, scopes):
        self.calls.append((user_assertion, list(scopes)))
        return self._result


def _exchanger_with_stub(result: dict) -> tuple[MsalOnBehalfOfExchanger, _StubMsalApp]:
    exchanger = MsalOnBehalfOfExchanger(build_test_config())
    stub = _StubMsalApp(result)
    exchanger._app = stub  # pre-seed: skip the lazy real-MSAL build entirely
    return exchanger, stub


def test_successful_exchange_returns_the_access_token_and_uses_the_arm_scope():
    exchanger, stub = _exchanger_with_stub({"access_token": "new-arm-token"})

    token = run_async(lambda: exchanger.acquire_token("inbound-user-token", [ARM_SCOPE]))

    assert token == "new-arm-token"
    assert stub.calls == [("inbound-user-token", [ARM_SCOPE])]


def test_consent_required_failure_surfaces_only_the_aadsts_code():
    exchanger, _ = _exchanger_with_stub(
        {
            "error": "invalid_grant",
            "error_description": "AADSTS65001: The user or administrator has not consented...",
            "error_codes": [65001],
        }
    )

    with pytest.raises(OboError) as exc_info:
        run_async(lambda: exchanger.acquire_token("inbound-user-token", [ARM_SCOPE]))

    assert exc_info.value.safe_code == "AADSTS65001"
    assert "consent" not in str(exc_info.value).lower()


def test_failure_without_error_codes_falls_back_to_description_regex():
    exchanger, _ = _exchanger_with_stub(
        {"error": "invalid_grant", "error_description": "AADSTS70011: blah blah"}
    )

    with pytest.raises(OboError) as exc_info:
        run_async(lambda: exchanger.acquire_token("t", [ARM_SCOPE]))

    assert exc_info.value.safe_code == "AADSTS70011"


def test_failure_with_no_recognizable_code_falls_back_to_a_fixed_label():
    exchanger, _ = _exchanger_with_stub({"error": "server_error"})

    with pytest.raises(OboError) as exc_info:
        run_async(lambda: exchanger.acquire_token("t", [ARM_SCOPE]))

    assert exc_info.value.safe_code == "server_error"


def test_no_fabricated_success_when_access_token_absent_and_no_error_either():
    # A malformed/unexpected MSAL result must never be treated as success.
    exchanger, _ = _exchanger_with_stub({})

    with pytest.raises(OboError) as exc_info:
        run_async(lambda: exchanger.acquire_token("t", [ARM_SCOPE]))

    assert exc_info.value.safe_code == "AuthorizationFailed"
