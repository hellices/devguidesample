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
    import ipaddress

    text = _code(FOUNDATION.read_text())
    prefixes = dict(re.findall(r"^var (\w+SubnetPrefix) = '([\d./]+)'$", text, re.MULTILINE))
    assert prefixes == {"gatewaySubnetPrefix": "10.42.1.0/24", "aksSubnetPrefix": "10.42.2.0/24",
                        "endpointsSubnetPrefix": "10.42.3.0/24"}
    # Each subnet uses its own prefix variable (swapping them would move the AKS load balancer IP).
    for subnet, var in (("gatewaySubnet", "gatewaySubnetPrefix"), ("aksSubnet", "aksSubnetPrefix"),
                        ("endpointsSubnet", "endpointsSubnetPrefix")):
        assert re.findall(r"addressPrefix: (\w+)", _resource_block(text, subnet)) == [var], subnet
    vnet = ipaddress.ip_network(re.search(r"addressPrefixes: \[\s*'([\d./]+)'\s*\]", text).group(1))
    nets = [ipaddress.ip_network(v) for v in prefixes.values()]
    assert vnet == ipaddress.ip_network("10.42.0.0/16") and all(n.subnet_of(vnet) for n in nets)
    assert not any(a.overlaps(b) for i, a in enumerate(nets) for b in nets[i + 1:])
    vmsingle = ipaddress.ip_address(re.search(r"^var vmSinglePrivateIp = '([\d.]+)'$", text, re.MULTILINE).group(1))
    assert vmsingle == ipaddress.ip_address("10.42.2.250") and vmsingle in ipaddress.ip_network("10.42.2.0/24")


def test_storage_and_key_vault_disable_legacy_secret_access():
    text = _code(FOUNDATION.read_text())

    # Each property is declared exactly once, with the value, inside its own resource block;
    # a commented-out line or a value set elsewhere does not count.
    expected = {
        "storage": {"allowSharedKeyAccess": "false", "defaultToOAuthAuthentication": "true",
                    "allowBlobPublicAccess": "false", "defaultAction": "'Deny'"},
        "keyVault": {"enableRbacAuthorization": "true", "defaultAction": "'Deny'"},
    }
    for symbol, properties in expected.items():
        block = _resource_block(text, symbol)
        for name, value in properties.items():
            assert re.findall(rf"^\s*{name}:\s*(\S+)\s*$", block, re.MULTILINE) == [value], (symbol, name)
    assert "grafana-admin-password" in text


def test_security_property_check_ignores_commented_out_lines():
    block = _resource_block(_code(
        "resource storage 'x' = {\n  properties: {\n    // allowSharedKeyAccess: false\n  }\n}\n"), "storage")
    assert re.findall(r"^\s*allowSharedKeyAccess:\s*(\S+)\s*$", block, re.MULTILINE) == []


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
    text = _code(FOUNDATION.read_text())

    # An exact allowlist: a renamed secret output cannot slip in under a new name.
    outputs = dict(re.findall(r"^output (\w+) \w+ = (.+)$", text, re.MULTILINE))
    assert set(outputs) == {
        "vnetId", "vnetName", "gatewaySubnetId", "gatewayNsgId", "aksSubnetId", "acrId", "acrName",
        "acrLoginServer", "storageName", "storageBlobEndpoint", "keyVaultName", "gatewayIdentityId",
        "gatewayPrincipalId", "gatewayClientId", "producerPrincipalId", "producerClientId",
        "consumerPrincipalId", "consumerClientId", "vmSinglePrivateIp",
    }
    for name, expr in outputs.items():
        assert not re.search(r"(?i)listKeys|listSecrets|getSecret|password|connectionString|primaryKey", expr), name


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


def test_messaging_creates_the_cluster_only_for_the_dedicated_tier():
    text = _code(MESSAGING.read_text())

    # Exactly one cluster resource, guarded by the tier, 1 CU.
    assert len(re.findall(r"'Microsoft\.EventHub/clusters@", text)) == 1
    cluster = _resource_block(text, "dedicatedCluster")
    assert "= if (dedicated) {" in cluster
    assert re.search(r"sku: \{\s*name: 'Dedicated'\s*capacity: 1\s*\}", cluster)
    assert "var dedicated = eventHubsSku == 'Dedicated'" in text
    # The workload namespace joins the cluster only for Dedicated; otherwise it is Premium 1 PU.
    namespace = _resource_block(text, "premiumNamespace")
    assert "dedicated ? {\n    clusterArmId: dedicatedCluster.id\n  } : {}" in namespace
    assert re.search(r"name: 'Premium'\s*tier: 'Premium'\s*capacity: 1", namespace)
    assert "Microsoft.Insights/diagnosticSettings@2021-05-01-preview" in text
    # Everything scoped to the cluster exists only when the cluster does.
    reader = _resource_block(text, "gatewayClusterMonitoringReader")
    assert "= if (dedicated) {" in reader and "scope: dedicatedCluster" in reader
    cluster_ds = _resource_block(text, "clusterMetricsToTelemetryHub")
    assert "= if (dedicated && diagnosticMetricsEnabled) {" in cluster_ds and "scope: dedicatedCluster" in cluster_ds


# Built-in role definition IDs (Azure built-in roles reference); a swapped GUID grants the wrong role.
ROLE_GUIDS = {
    "acrPullRoleDefinitionId": "7f951dda-4ed3-4680-a7ca-43fe172d538d",
    "keyVaultSecretsUserRoleDefinitionId": "4633458b-17de-408a-b874-0445c86b69e6",
    "storageBlobDataContributorRoleDefinitionId": "ba92f5b4-2d11-453d-a403-e96b0029c9fe",
    "storageBlobDataReaderRoleDefinitionId": "2a2b9908-6ea1-4ae2-8e65-a410df84e7d1",
    "monitoringReaderRoleDefinitionId": "43d0d8ad-25c7-4714-9337-8ba259a9fe05",
    "eventHubsDataSenderRoleDefinitionId": "2b629674-e913-4c01-ae53-ef4638d8f975",
    "eventHubsDataReceiverRoleDefinitionId": "a638d3c7-ab3a-418d-83e6-5f17a39d4fde",
    "networkContributorRoleDefinitionId": "4d97b98b-1d4f-4787-a291-c67834d212e7",
    "aksRbacClusterAdminRoleDefinitionId": "b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b",
    "grafanaAdminRoleDefinitionId": "22926164-76b3-42b3-bc55-97df8dab3e41",
}


def test_every_role_variable_holds_the_guid_its_name_promises():
    for path in (LAB_ROOT / "infra").rglob("*.bicep"):
        declared = dict(re.findall(r"^var (\w+RoleDefinitionId) = '([0-9a-f-]{36})'", _code(path.read_text()), re.MULTILINE))
        for name, guid in declared.items():
            assert ROLE_GUIDS.get(name) == guid, (path.name, name, guid)


def test_cluster_streams_its_metrics_to_the_same_telemetry_hub_only_for_dedicated():
    text = _code(MESSAGING.read_text())

    cluster_ds = _resource_block(text, "clusterMetricsToTelemetryHub")
    assert "= if (dedicated && diagnosticMetricsEnabled) {" in cluster_ds
    assert "scope: dedicatedCluster" in cluster_ds
    assert "eventHubName: telemetryHub.name" in cluster_ds
    assert "category: 'AllMetrics'" in cluster_ds


def test_metric_diagnostic_settings_are_opt_in_and_the_sink_exists_only_when_used():
    text = _code(MESSAGING.read_text())

    # The Metrics API already returns every AllMetrics value sooner and with dimensions.
    assert "param eventHubsDiagnosticMetrics string = 'Disabled'" in text
    assert "var telemetryEnabled = logsEnabled || diagnosticMetricsEnabled" in text
    for symbol in ("telemetryHub", "telemetryCollectorConsumer", "premiumMetricsToTelemetryHub",
                   "gatewayTelemetryReceiver"):
        assert "= if (diagnosticMetricsEnabled) {" in _resource_block(text, symbol), symbol
    for symbol in ("telemetryNamespace", "telemetryDiagnosticRule"):
        assert "= if (telemetryEnabled) {" in _resource_block(text, symbol), symbol
    assert "output telemetryNamespaceName string = telemetryEnabled ? telemetryNamespace.name : ''" in text
    assert "output telemetryEventHubName string = diagnosticMetricsEnabled ? telemetryHub.name : ''" in text
    main = _code(MAIN.read_text())
    assert "param eventHubsDiagnosticMetrics string = 'Disabled'" in main
    assert "eventHubsDiagnosticMetrics: eventHubsDiagnosticMetrics" in main


def test_messaging_keeps_workload_local_auth_disabled():
    text = MESSAGING.read_text()

    # Declared once, active (not commented out), on the workload namespace itself.
    namespace = _resource_block(_code(text), "premiumNamespace")
    assert re.findall(r"^\s*disableLocalAuth:\s*(\S+)\s*$", namespace, re.MULTILINE) == ["true"]
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
    foundation = (LAB_ROOT / "infra" / "modules" / "foundation.bicep").read_text()

    assert "oidcIssuerProfile: { enabled: true }" in text
    assert "workloadIdentity: { enabled: true }" in text
    # The gateway NSG lives with the subnets and is bound to both the gateway subnet and NIC.
    assert "resource gatewayNsg 'Microsoft.Network/networkSecurityGroups" not in text
    assert re.search(r"networkSecurityGroup: \{\s*id: gatewayNsgId\s*\}", text)
    rules = foundation[foundation.index("resource gatewayNsg"):foundation.index("resource aksNsg")]
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
    # The single allow rule as one unit: inbound TCP 3000 from the operator /32 only.
    [rule] = re.findall(r"properties: \{(.*?)\n\s*\}", rules, re.DOTALL)
    fields = dict(re.findall(r"^\s*(\w+): (\S+)\s*$", rule, re.MULTILINE))
    assert {k: fields.get(k) for k in ("access", "direction", "protocol", "sourceAddressPrefix",
                                       "destinationPortRange")} == {
        "access": "'Allow'", "direction": "'Inbound'", "protocol": "'Tcp'",
        "sourceAddressPrefix": "operatorEgressCidr", "destinationPortRange": "'3000'"}
    assert "destinationPortRange: '22'" not in text
    assert "destinationPortRange: '22'" not in foundation


def test_every_subnet_carries_a_template_owned_nsg():
    foundation = _code((LAB_ROOT / "infra" / "modules" / "foundation.bicep").read_text())

    # Governance automation attaches an empty deny-all NSG to subnets without one, which cut the
    # operator path to Grafana in a real run; owning the NSGs also survives a re-provision.
    for subnet, nsg in (("gatewaySubnet", "gatewayNsg"), ("aksSubnet", "aksNsg"), ("endpointsSubnet", "endpointsNsg")):
        assert re.search(rf"networkSecurityGroup: \{{\s*id: {nsg}\.id\s*\}}", _resource_block(foundation, subnet)), subnet
    for nsg in ("aksNsg", "endpointsNsg"):
        assert re.search(r"securityRules: \[\]", _resource_block(foundation, nsg)), nsg


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
    # Any whitespace between the words runs the same command.
    assert not re.search(r"\bdocker\s+compose\s+up\b", text)


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
    assert not re.search(r"\benablePurgeProtection\s*:\s*false\b", _code(FOUNDATION.read_text()))


def _code(text: str) -> str:
    """Bicep source without block or line comments."""
    return re.sub(r"(?m)//.*$", "", re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL))


def _resource_block(text: str, symbol: str) -> str:
    """One top-level resource, from its declaration to the bracket that closes its body.

    Counts {} and [] depth outside strings, so a `[for ...: { ... }]` collection ends at its own `}]`
    rather than at a later resource's closing brace.
    """
    start = re.search(rf"(?m)^resource {symbol} '", text)
    assert start, symbol
    body = text.index("=", start.end()) + 1
    depth, quoted, opened = 0, False, False
    for i in range(body, len(text)):
        ch = text[i]
        if ch == "'" and text[i - 1] != "\\":
            quoted = not quoted
        elif not quoted and ch in "{[":
            depth, opened = depth + 1, True
        elif not quoted and ch in "}]":
            depth -= 1
            if opened and depth == 0:
                return text[start.start():i + 1]
    raise AssertionError(f"unterminated resource {symbol}")


def test_resource_block_stops_at_the_end_of_a_collection_resource():
    text = ("resource a 'x' = [for i in list: {\n  name: i\n}]\n"
            "resource b 'y' = {\n  groupIds: [ 'blob' ]\n}\n")
    assert _resource_block(text, "a") == "resource a 'x' = [for i in list: {\n  name: i\n}]"
    assert "groupIds" not in _resource_block(text, "a")


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
    # Commented-out assignments are not deployed, so only code counts.
    text = _code(text)
    # Indented declarations are still declarations; every occurrence of the type must be parsed.
    blocks = re.split(r"(?m)^\s*resource \w+ 'Microsoft\.Authorization/roleAssignments@", text)[1:]
    assert len(blocks) == text.count("'Microsoft.Authorization/roleAssignments@"), "unparsed roleAssignments"
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
        ("dedicatedCluster", "monitoringReaderRoleDefinitionId", "gatewayPrincipalId"),
        ("telemetryLogsHub", "eventHubsDataReceiverRoleDefinitionId", "gatewayPrincipalId"),
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


def test_role_assignment_parser_sees_indented_declarations():
    text = (
        "resource a 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "  scope: hub\n  properties: {\n"
        "    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)\n"
        "    principalId: gatewayPrincipalId\n  }\n}\n"
        "  resource b 'Microsoft.Authorization/roleAssignments@2022-04-01' = {\n"
        "    scope: resourceGroupScope\n    properties: {\n"
        "      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', readerRole)\n"
        "      principalId: gatewayPrincipalId\n    }\n  }\n"
    )
    assert [scope for scope, _, _ in _role_assignments(text)] == ["hub", "resourceGroupScope"]


def test_resource_logs_go_to_their_own_hub_only_when_enabled():
    text = _code(MESSAGING.read_text())

    assert "var logsEnabled = eventHubsLogs == 'Enabled'" in text
    for symbol in ("telemetryLogsHub", "telemetryLogsCollectorConsumer", "premiumLogsToTelemetryHub",
                   "gatewayTelemetryLogsReceiver"):
        assert "= if (logsEnabled) {" in _resource_block(text, symbol), symbol
    logs_ds = _resource_block(text, "premiumLogsToTelemetryHub")
    # A separate hub: the metrics receiver must never see log records.
    assert "eventHubName: telemetryLogsHub.name" in logs_ds and "scope: premiumNamespace" in logs_ds
    assert re.findall(r"category: '(\w+)'", logs_ds) == ["ApplicationMetricsLogs", "RuntimeAuditLogs"]
    assert "telemetryLogsHub" not in _resource_block(text, "premiumMetricsToTelemetryHub")


GRAFANA = LAB_ROOT / "infra" / "modules" / "grafana.bicep"
GRAFANA_READER = LAB_ROOT / "infra" / "modules" / "grafana-reader.bicep"


def test_managed_grafana_identity_reads_only_the_charted_resources():
    # The Azure Monitor data source runs as the workspace identity; Bicep (unlike portal creation)
    # grants nothing at subscription scope, so the lab assigns Monitoring Reader per resource.
    assert sorted(_role_assignments(GRAFANA_READER.read_text())) == sorted([
        ("namespace", "monitoringReaderRoleDefinitionId", "grafanaPrincipalId"),
        ("cluster", "monitoringReaderRoleDefinitionId", "grafanaPrincipalId"),
    ])
    # Declarations are read from code only, so a commented-out copy cannot stand in for the real value.
    reader = _code(GRAFANA_READER.read_text())
    assert re.findall(r"^var monitoringReaderRoleDefinitionId = '([0-9a-f-]+)'$", reader, re.MULTILINE) == [
        "43d0d8ad-25c7-4714-9337-8ba259a9fe05"]
    assert re.findall(r"^output principalId string = (.+)$", _code(GRAFANA.read_text()), re.MULTILINE) == [
        "grafana.identity.principalId"]
    main = _code(MAIN.read_text())
    block = main[main.index("module grafanaReader"):]
    block = block[:block.index("\n}\n")]
    assert "if (managedGrafana == 'Enabled')" in block
    assert "grafanaPrincipalId: grafana.?outputs.principalId" in block
    assert "namespaceName: messaging.outputs.premiumNamespaceName" in block
    # The cluster role must land on the cluster the dashboard charts: the one this lab created.
    assert ("clusterName: empty(messaging.outputs.dedicatedClusterId) ? '' : "
            "last(split(messaging.outputs.dedicatedClusterId, '/'))") in block
    # Data flow: the workspace principal leaves grafana.bicep only through this one reference, which feeds
    # grafanaReader; grafana-reader.bicep exposes no outputs and declares no modules, so the principal
    # cannot travel on under another parameter name. Its only role assignments are the two above.
    # Every reference to the grafana module, in any access form (., .?, ['x'], aliases built from it),
    # is located; principalId may appear once and only inside the grafanaReader module, and every
    # other reference must be one of the top-level outputs.
    reader_block = main[main.index("module grafanaReader"):]
    reader_block = reader_block[:reader_block.index("\n}\n")]
    # The module declaration (`module grafana '...'`), its file path and 'grafana-*' names are not references.
    references = list(re.finditer(r"(?<!modules/)\bgrafana\b(?!\s*'|-)", main))
    accesses = list(re.finditer(
        r"\bgrafana\s*(?:\.\?|\.)\s*outputs\s*(?:\.\s*(\w+)|\[\s*'(\w+)'\s*\])", main))
    assert len(references) == len(accesses), "grafana is referenced other than through a named output"
    principal = [a for a in accesses if (a.group(1) or a.group(2)) == "principalId"]
    assert len(principal) == 1 and principal[0].group(0) in reader_block
    for access in accesses:
        if access in principal:
            continue
        line = main[main.rfind("\n", 0, access.start()) + 1:main.find("\n", access.start())]
        assert re.match(r"^output MANAGED_GRAFANA_(NAME|ENDPOINT) string = ", line), line
    assert not re.search(r"\bgrafanaReader\s*(?:\.\?|\.)\s*outputs", main)
    assert not re.search(r"(?m)^\s*(output|module)\s", reader)
    assert not re.search(r"(?m)^\s*module\s", _code(GRAFANA.read_text()))
    assert "Microsoft.Authorization/roleAssignments" not in _code(GRAFANA.read_text())
    for path in (LAB_ROOT / "infra").rglob("*.bicep"):
        if path == GRAFANA_READER:
            continue
        principals = [principal for _, _, principal in _role_assignments(path.read_text())]
        assert not any("grafana" in principal.lower() for principal in principals), path.name
