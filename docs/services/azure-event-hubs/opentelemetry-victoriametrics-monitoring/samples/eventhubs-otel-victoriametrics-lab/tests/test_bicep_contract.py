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
        assert f"output {name} " in text


COMPUTE = LAB_ROOT / "infra" / "modules" / "compute.bicep"


def test_compute_enables_workload_identity_and_restricts_public_ports():
    text = COMPUTE.read_text()

    assert "oidcIssuerProfile: { enabled: true }" in text
    assert "workloadIdentity: { enabled: true }" in text
    assert "destinationPortRange: '3000'" in text
    assert "sourceAddressPrefix: operatorEgressCidr" in text
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


def test_data_plane_uses_private_endpoints_only():
    text = FOUNDATION.read_text()

    assert text.count("publicNetworkAccess: 'Disabled'") == 2
    assert "privatelink.vaultcore.azure.net" in text
    assert "privatelink.blob." in text
    assert "Microsoft.Network/privateEndpoints@" in text
    assert "virtualNetworkRules" not in text


def test_checkpoint_roles_are_container_scoped():
    text = FOUNDATION.read_text()

    assert "scope: workloadCheckpoints" in text
    assert "scope: collectorCheckpoints" in text
    assert "scope: storage\n" not in text


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
