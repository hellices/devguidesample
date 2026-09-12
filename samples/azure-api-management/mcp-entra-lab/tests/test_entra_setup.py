import pytest


def test_api_uses_v2_delegated_scope_and_exact_cli_preauthorization():
    from entra_setup import api_manifest, AZURE_CLI_CLIENT_ID

    result = api_manifest("lab-api", "scope-example", "Mcp.Access", "client-example", "arm-scope")
    assert result["api"]["requestedAccessTokenVersion"] == 2
    assert result["api"]["oauth2PermissionScopes"][0]["value"] == "Mcp.Access"
    allowed = result["api"]["preAuthorizedApplications"]
    assert {item["appId"] for item in allowed} == {AZURE_CLI_CLIENT_ID, "client-example"}
    assert all(item["delegatedPermissionIds"] == ["scope-example"] for item in allowed)
    assert result["requiredResourceAccess"][0]["resourceAccess"] == [
        {"id": "arm-scope", "type": "Scope"}
    ]


def test_public_client_never_has_a_secret_or_implicit_flow():
    from entra_setup import public_client_manifest

    result = public_client_manifest("lab-client")
    assert result["publicClient"]["redirectUris"] == ["http://localhost"]
    assert result["isFallbackPublicClient"] is True
    assert "passwordCredentials" not in result
    assert "web" not in result
    assert result["signInAudience"] == "AzureADMyOrg"


def test_downstream_grant_is_only_for_the_lab_operator():
    from entra_setup import delegated_grant

    result = delegated_grant("middle-sp", "arm-sp", "operator-example")
    assert result["consentType"] == "Principal"
    assert result["principalId"] == "operator-example"
    assert result["scope"] == "user_impersonation"


def test_identity_binding_refuses_another_tenant():
    from entra_setup import verify_binding

    state = {"tenant_id": "tenant-a", "subscription_id": "sub-a", "resource_group": "rg-a"}
    identities = {"context": {**state, "tenant_id": "tenant-b"}}
    with pytest.raises(ValueError, match="different lab"):
        verify_binding(identities, state)


def test_existing_identity_binding_matches_exact_context():
    from entra_setup import verify_binding

    state = {"tenant_id": "tenant-a", "subscription_id": "sub-a", "resource_group": "rg-a"}
    verify_binding({"context": state.copy()}, state)
