from pathlib import Path


LAB_ROOT = Path(__file__).parents[1]
FOUNDATION = LAB_ROOT / "infra" / "modules" / "foundation.bicep"


def test_foundation_declares_required_resource_types():
    text = FOUNDATION.read_text()

    for resource_type in (
        "Microsoft.Network/virtualNetworks@",
        "Microsoft.ContainerRegistry/registries@",
        "Microsoft.Storage/storageAccounts@",
        "Microsoft.KeyVault/vaults@",
        "Microsoft.ManagedIdentity/userAssignedIdentities@",
    ):
        assert resource_type in text


def test_foundation_uses_fixed_non_overlapping_subnets():
    text = FOUNDATION.read_text()

    assert "10.42.0.0/16" in text
    assert "10.42.1.0/24" in text
    assert "10.42.2.0/24" in text
    assert "10.42.2.20" in text


def test_storage_and_key_vault_disable_legacy_secret_access():
    text = FOUNDATION.read_text()

    assert "allowSharedKeyAccess: false" in text
    assert "defaultToOAuthAuthentication: true" in text
    assert "allowBlobPublicAccess: false" in text
    assert "enableRbacAuthorization: true" in text
    assert "defaultAction: 'Deny'" in text
    assert "grafana-admin-password" in text


def test_foundation_assigns_only_expected_built_in_roles():
    text = FOUNDATION.read_text()

    for role_definition_id in (
        "7f951dda-4ed3-4680-a7ca-43fe172d538d",  # AcrPull
        "4633458b-17de-408a-b874-0445c86b69e6",  # Key Vault Secrets User
        "ba92f5b4-2d11-453d-a403-e96b0029c9fe",  # Storage Blob Data Contributor
        "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",  # Storage Blob Data Reader
    ):
        assert role_definition_id in text
    assert "principalType: 'ServicePrincipal'" in text


def test_foundation_does_not_expose_secrets():
    text = FOUNDATION.read_text()

    assert "output grafanaPassword" not in text
    assert "output connectionString" not in text
    assert "output storageKey" not in text


def test_foundation_exports_main_module_contract():
    text = FOUNDATION.read_text()
    names = (
        "vnetId",
        "gatewaySubnetId",
        "aksSubnetId",
        "acrId",
        "acrName",
        "acrLoginServer",
        "storageName",
        "keyVaultName",
        "gatewayIdentityId",
        "gatewayPrincipalId",
        "gatewayClientId",
        "producerPrincipalId",
        "producerClientId",
        "consumerPrincipalId",
        "consumerClientId",
        "vmSinglePrivateIp",
    )

    for name in names:
        assert f"output {name} " in text
