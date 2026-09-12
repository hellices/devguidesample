def test_obo_error_is_numeric_and_excludes_provider_description():
    from auth_probe import safe_obo_error

    assert safe_obo_error({
        "error_codes": [65001],
        "error_description": "private-user and private-tenant must not be published",
    }) == "AADSTS65001"


def test_unknown_obo_error_is_an_explicit_failure_code():
    from auth_probe import safe_obo_error

    assert safe_obo_error({"error": "invalid_grant"}) == "AuthenticationFailed"


def test_obo_error_does_not_echo_untrusted_strings():
    from auth_probe import safe_obo_error

    assert safe_obo_error({"error_codes": ["private-token"]}) == "AuthenticationFailed"


def test_token_command_selects_tenant_without_mutually_exclusive_subscription(monkeypatch, tmp_path):
    from auth_probe import api_token

    state = {
        "tenant_id": "tenant-example",
        "subscription_id": "subscription-example",
        "resource_group": "rg-example",
    }
    identities = {
        "context": state.copy(),
        "custom_api": {"identifier_uri": "api://example", "scope_name": "Mcp.Access"},
    }
    monkeypatch.setattr(
        "auth_probe.load_state",
        lambda path: identities if path.name == "identities.json" else state,
    )
    captured = []

    def azure(arguments, path):
        captured.extend(arguments)
        return {"accessToken": "example-token"}

    monkeypatch.setattr("auth_probe.az_json", azure)
    assert api_token(tmp_path / "state.json", "custom_api") == "example-token"
    assert "--tenant" in captured
    assert "--subscription" not in captured


def test_auth_rerun_clears_old_success_before_loading_state(monkeypatch, tmp_path):
    import json
    import pytest
    from auth_probe import run

    output = tmp_path / "evidence.json"
    output.write_text('{"checks":[{"status":"passed"}]}')

    def fail(path):
        raise RuntimeError("state unavailable")

    monkeypatch.setattr("auth_probe.load_state", fail)
    with pytest.raises(RuntimeError, match="state unavailable"):
        run(tmp_path / "state.json", output)
    assert json.loads(output.read_text())["checks"] == []


def test_auth_completion_is_written_after_all_four_checks(monkeypatch, tmp_path):
    import json
    from contextlib import nullcontext
    from types import SimpleNamespace
    from auth_probe import run

    state = {
        "tenant_id": "tenant", "subscription_id": "subscription",
        "resource_group": "group", "suffix": "example",
    }
    app = {"client_id": "client", "scope_name": "Mcp.Access", "client_secret": "example"}
    identities = {
        "context": {key: state[key] for key in ("tenant_id", "subscription_id", "resource_group")},
        "custom_api": app, "azure_api": app,
    }
    monkeypatch.setattr("auth_probe.load_state", lambda p: identities if p.name == "identities.json" else state)
    monkeypatch.setattr("auth_probe.api_token", lambda *args: "mcp-token")
    monkeypatch.setattr("auth_probe.verified_claims", lambda *args: {"scp": "Mcp.Access", "tid": "tenant"})
    monkeypatch.setattr(
        "auth_probe.msal.ConfidentialClientApplication",
        lambda *args, **kwargs: SimpleNamespace(
            acquire_token_on_behalf_of=lambda **kwargs: {"access_token": "arm-token"}
        ),
    )

    class Http:
        def get(self, url, *, headers):
            authorized = headers["Authorization"].endswith("arm-token")
            return SimpleNamespace(
                status_code=200 if authorized else 401,
                json=lambda: {"tags": {"labId": "example"}},
            )

    monkeypatch.setattr("auth_probe.httpx.Client", lambda **kwargs: nullcontext(Http()))
    output = tmp_path / "results.json"
    assert run(tmp_path / "state.json", output) == 0
    checks = json.loads(output.read_text())["checks"]
    assert len(checks) == 5
    assert checks[-1]["id"] == "auth-suite-complete"
    assert checks[-1]["observed"]["result_count"] == 4
