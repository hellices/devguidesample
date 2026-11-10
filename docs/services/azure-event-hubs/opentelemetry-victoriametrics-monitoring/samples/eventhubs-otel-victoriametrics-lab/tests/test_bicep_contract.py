import re
from pathlib import Path

import pytest


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


def _assigned_role_guids(text: str) -> set[str]:
    """GUIDs actually used by roleAssignments, resolved through their var declarations.

    Every roleAssignments resource and every roleDefinitionId must use the one supported form,
    so an assignment written differently (for example a literal GUID) fails instead of hiding.
    """
    variables = dict(re.findall(r"^var (\w+) = '([0-9a-f-]{36})'", text, re.MULTILINE))
    assignments = re.findall(r"'Microsoft\.Authorization/roleAssignments@", text)
    definitions = re.findall(r"roleDefinitionId:\s*(.+)", text)
    supported = re.compile(r"subscriptionResourceId\('Microsoft\.Authorization/roleDefinitions', (\w+)\)")
    used = []
    for definition in definitions:
        match = supported.fullmatch(definition.strip())
        assert match, f"unsupported roleDefinitionId expression: {definition.strip()}"
        used.append(match.group(1))
    assert used, "no role assignments found"
    assert len(used) == len(assignments), "every roleAssignments resource must declare one roleDefinitionId"
    return {variables[name] for name in used}


def test_role_parser_rejects_other_role_definition_forms():
    owner = (
        "var acr = '7f951dda-4ed3-4680-a7ca-43fe172d538d'\n"
        "resource a 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acr)\n}\n"
        "resource b 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', "
        "'8e3af657-a8ff-443c-a75c-2fe8c4bcb635')\n}\n"
    )
    with pytest.raises(AssertionError, match="unsupported roleDefinitionId"):
        _assigned_role_guids(owner)


def test_foundation_assigns_only_expected_built_in_roles():
    assert _assigned_role_guids(FOUNDATION.read_text()) == {
        "7f951dda-4ed3-4680-a7ca-43fe172d538d",  # AcrPull
        "4633458b-17de-408a-b874-0445c86b69e6",  # Key Vault Secrets User
        "ba92f5b4-2d11-453d-a403-e96b0029c9fe",  # Storage Blob Data Contributor
        "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",  # Storage Blob Data Reader
    }
    assert "principalType: 'ServicePrincipal'" in FOUNDATION.read_text()


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


MESSAGING = LAB_ROOT / "infra" / "modules" / "messaging.bicep"


def test_messaging_creates_premium_and_standard_but_no_dedicated_cluster():
    text = MESSAGING.read_text()

    assert "name: 'Premium'" in text
    assert "tier: 'Premium'" in text
    assert "capacity: 1" in text
    assert "name: 'Standard'" in text
    assert "Microsoft.EventHub/clusters@" not in text
    assert "Microsoft.Insights/diagnosticSettings@2021-05-01-preview" in text


def test_messaging_keeps_workload_local_auth_disabled():
    text = MESSAGING.read_text()

    assert "disableLocalAuth: true" in text
    assert "eventHubAuthorizationRuleId: telemetryDiagnosticRule.id" in text
    assert "output connectionString" not in text
    assert "listKeys(" not in text


def test_messaging_roles_are_resource_scoped():
    text = MESSAGING.read_text()

    assert "scope: premiumNamespace" in text
    assert "scope: workloadHub" in text
    assert "scope: telemetryHub" in text
    for role_definition_id in (
        "43d0d8ad-25c7-4714-9337-8ba259a9fe05",  # Monitoring Reader
        "2b629674-e913-4c01-ae53-ef4638d8f975",  # Event Hubs Data Sender
        "a638d3c7-ab3a-418d-83e6-5f17a39d4fde",  # Event Hubs Data Receiver
    ):
        assert role_definition_id in text


def test_messaging_exports_main_module_contract():
    text = MESSAGING.read_text()

    for name in (
        "premiumNamespaceName",
        "premiumNamespaceId",
        "workloadEventHubName",
        "workloadConsumerGroup",
        "telemetryNamespaceName",
        "telemetryEventHubName",
    ):
        assert re.search(rf"^output {name} ", text, re.MULTILINE), name


COMPUTE = LAB_ROOT / "infra" / "modules" / "compute.bicep"


def test_compute_enables_workload_identity_and_restricts_public_ports():
    text = COMPUTE.read_text()

    assert "oidcIssuerProfile: { enabled: true }" in text
    assert "workloadIdentity: { enabled: true }" in text
    rules = text[text.index("securityRules: ["):text.index("resource gatewayNic")]
    # Rules declared as separate child resources would sit outside this inline list.
    for module in (LAB_ROOT / "infra").rglob("*.bicep"):
        assert "networkSecurityGroups/securityRules" not in module.read_text(), module.name
    # Plural forms could open more ports or sources without matching the singular checks below.
    for plural in ("destinationPortRanges", "sourceAddressPrefixes"):
        assert plural not in rules, plural
    assert rules.count("access: 'Allow'") == 1
    allow = re.findall(r"access: 'Allow'.*?destinationPortRange: '(\w+)'", rules, re.DOTALL)
    assert allow == ["3000"]
    assert re.findall(r"sourceAddressPrefix: (\S+)", rules) == ["operatorEgressCidr"]
    assert "destinationPortRange: '22'" not in text


def test_compute_uses_overlay_network_without_vnet_overlap():
    text = COMPUTE.read_text()

    assert "networkPlugin: 'azure'" in text
    assert "networkPluginMode: 'overlay'" in text
    assert "podCidr: '10.244.0.0/16'" in text
    assert "serviceCidr: '10.0.0.0/16'" in text
    assert "dnsServiceIP: '10.0.0.10'" in text
    assert "vnetSubnetID: aksSubnetId" in text


def test_gateway_uses_managed_identity_and_no_embedded_secret():
    text = COMPUTE.read_text()

    assert "type: 'UserAssigned'" in text
    assert "gatewayIdentityId" in text
    assert "adminPassword" not in text
    assert "disablePasswordAuthentication: true" in text
    assert "grafana-admin-password" not in text


def test_compute_assigns_kubelet_acr_pull():
    text = COMPUTE.read_text()

    assert "aks.properties.identityProfile.kubeletidentity.objectId" in text
    assert "7f951dda-4ed3-4680-a7ca-43fe172d538d" in text
    assert "scope: acr" in text


def test_compute_bootstraps_gateway_without_starting_application():
    text = COMPUTE.read_text()

    assert "docker.io" in text
    assert "docker-compose-v2" in text
    assert "InstallAzureCLIDeb" in text
    assert "/opt/eventhubs-observability" in text
    assert "docker compose up" not in text


def test_compute_exports_main_module_contract():
    text = COMPUTE.read_text()

    for name in (
        "aksName",
        "aksOidcIssuer",
        "gatewayVmName",
        "gatewayPublicIp",
        "gatewayPrivateIp",
    ):
        assert f"output {name} " in text


MESSAGING = LAB_ROOT / "infra" / "modules" / "messaging.bicep"
COMPUTE = LAB_ROOT / "infra" / "modules" / "compute.bicep"
MAIN = LAB_ROOT / "infra" / "main.bicep"


def test_key_vault_never_sets_purge_protection_false():
    # ARM rejects enablePurgeProtection=false; omit it to leave purge protection off.
    assert "enablePurgeProtection: false" not in FOUNDATION.read_text()


def _code(text: str) -> str:
    """Bicep source without block or line comments."""
    return re.sub(r"(?m)//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL))


def _resource_block(text: str, symbol: str) -> str:
    start = re.search(rf"(?m)^resource {symbol} '", text)
    assert start, symbol
    end = re.search(r"(?m)^}", text[start.start():])
    return text[start.start():start.start() + end.end()]


def test_data_plane_uses_private_endpoints_only():
    text = _code(FOUNDATION.read_text())

    # Each data-plane resource is private on its own, not just "two Disabled somewhere".
    for symbol in ("storage", "keyVault"):
        block = _resource_block(text, symbol)
        assert re.findall(r"publicNetworkAccess:\s*'(\w+)'", block) == ["Disabled"], symbol
    assert "virtualNetworkRules" not in text

    # One endpoint per service: exact target, group and DNS zone, all driven by the same list.
    links = re.findall(
        r"\{\s*name: '(\w+)'\s*zone: '([^']+)'\s*groupId: '(\w+)'\s*targetId: (\w+)\.id\s*\}",
        text[text.index("var privateLinks = ["):text.index("]", text.index("var privateLinks = ["))],
    )
    assert links == [
        ("vault", "privatelink.vaultcore.azure.net", "vault", "keyVault"),
        ("blob", "privatelink.blob.${environment().suffixes.storage}", "blob", "storage"),
    ]
    endpoints = _resource_block(text, "privateEndpoints")
    assert "[for link in privateLinks:" in endpoints
    assert "privateLinkServiceId: link.targetId" in endpoints
    assert re.search(r"groupIds: \[\s*link\.groupId\s*\]", endpoints)
    assert "[for (link, i) in privateLinks:" in _resource_block(text, "privateDnsGroups")
    assert "[for link in privateLinks:" in _resource_block(text, "privateDnsZones")


def test_private_endpoint_check_sees_a_commented_out_setting():
    text = "resource storage 'x' = {\n  publicNetworkAccess: 'Enabled' // publicNetworkAccess: 'Disabled'\n}\n"
    assert re.findall(r"publicNetworkAccess:\s*'(\w+)'", _resource_block(_code(text), "storage")) == ["Enabled"]


def _role_assignments(text: str) -> list[tuple[str, str, str]]:
    """(scope, role variable, principal) of every roleAssignments resource block."""
    blocks = re.split(r"(?m)^resource \w+ 'Microsoft\.Authorization/roleAssignments@", text)[1:]
    assignments = []
    for block in blocks:
        block = block.split("\n}\n", 1)[0]
        scope = re.search(r"^\s*scope:\s*(\w+)\s*$", block, re.MULTILINE)
        role = re.search(r"roleDefinitions', (\w+)\)", block)
        principal = re.search(r"^\s*principalId:\s*(\S+)\s*$", block, re.MULTILINE)
        # An assignment without an explicit scope would land on the whole resource group.
        assert scope and role and principal, block
        assignments.append((scope.group(1), role.group(1), principal.group(1)))
    return assignments


def test_foundation_role_assignments_are_exact():
    # Exact (scope, role, principal) list: a duplicate GUID at a wider scope cannot hide in a set.
    gateway, consumer = "gatewayIdentity.properties.principalId", "consumerIdentity.properties.principalId"
    assert sorted(_role_assignments(FOUNDATION.read_text())) == sorted([
        ("acr", "acrPullRoleDefinitionId", gateway),
        ("keyVault", "keyVaultSecretsUserRoleDefinitionId", gateway),
        ("workloadCheckpoints", "storageBlobDataContributorRoleDefinitionId", consumer),
        ("workloadCheckpoints", "storageBlobDataReaderRoleDefinitionId", gateway),
        ("collectorCheckpoints", "storageBlobDataContributorRoleDefinitionId", gateway),
    ])


def test_messaging_and_compute_role_assignments_are_exact():
    assert sorted(_role_assignments(MESSAGING.read_text())) == sorted([
        ("premiumNamespace", "monitoringReaderRoleDefinitionId", "gatewayPrincipalId"),
        ("workloadHub", "eventHubsDataSenderRoleDefinitionId", "producerPrincipalId"),
        ("workloadHub", "eventHubsDataReceiverRoleDefinitionId", "consumerPrincipalId"),
        ("workloadHub", "eventHubsDataReceiverRoleDefinitionId", "gatewayPrincipalId"),
        ("telemetryHub", "eventHubsDataReceiverRoleDefinitionId", "gatewayPrincipalId"),
    ])
    assert sorted(_role_assignments(COMPUTE.read_text())) == sorted([
        ("acr", "acrPullRoleDefinitionId", "aks.properties.identityProfile.kubeletidentity.objectId"),
        ("aksSubnet", "networkContributorRoleDefinitionId", "aks.identity.principalId"),
        ("aks", "aksRbacClusterAdminRoleDefinitionId", "deployerPrincipalId"),
    ])


def test_role_assignment_parser_rejects_a_missing_scope():
    unscoped = (
        "resource x 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "  properties: {\n"
        "    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)\n"
        "    principalId: p\n  }\n}\n"
    )
    with pytest.raises(AssertionError):
        _role_assignments(unscoped)


def test_checkpoint_roles_are_container_scoped():
    scopes = {scope for scope, role, _ in _role_assignments(FOUNDATION.read_text()) if "storageBlob" in role}
    assert scopes == {"workloadCheckpoints", "collectorCheckpoints"}


def test_role_assignment_parser_sees_a_widened_scope():
    widened = (
        "resource x 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "  scope: storage   \n"
        "  properties: {\n"
        "    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)\n"
        "    principalId: gatewayIdentity.properties.principalId\n  }\n}\n"
    )
    assert _role_assignments(widened) == [("storage", "r", "gatewayIdentity.properties.principalId")]


def test_event_hubs_region_is_separable_and_zone_redundancy_is_platform_default():
    main = MAIN.read_text()

    assert "param eventHubsLocation string = ''" in main
    assert "location: messagingLocation" in main
    assert "zoneRedundant" not in MESSAGING.read_text()


def test_premium_namespace_is_tagged_for_receiver_filter():
    assert "'otel-metrics-source': 'premium'" in MESSAGING.read_text()


def test_aks_can_manage_internal_lb_and_deployer_gets_cluster_admin():
    text = COMPUTE.read_text()

    assert "4d97b98b-1d4f-4787-a291-c67834d212e7" in text  # Network Contributor
    assert "scope: aksSubnet" in text
    assert "b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b" in text  # AKS RBAC Cluster Admin


def test_modules_assign_only_expected_roles():
    assert _assigned_role_guids(MESSAGING.read_text()) == {
        "43d0d8ad-25c7-4714-9337-8ba259a9fe05",  # Monitoring Reader
        "2b629674-e913-4c01-ae53-ef4638d8f975",  # Azure Event Hubs Data Sender
        "a638d3c7-ab3a-418d-83e6-5f17a39d4fde",  # Azure Event Hubs Data Receiver
    }
    assert _assigned_role_guids(COMPUTE.read_text()) == {
        "7f951dda-4ed3-4680-a7ca-43fe172d538d",  # AcrPull (kubelet)
        "4d97b98b-1d4f-4787-a291-c67834d212e7",  # Network Contributor (AKS subnet)
        "b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b",  # Azure Kubernetes Service RBAC Cluster Admin
    }
