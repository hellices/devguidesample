from pathlib import Path


WORKLOAD_BICEP = Path(__file__).parents[1] / "workload.bicep"


def test_storage_dependency_uses_private_networking():
    template = WORKLOAD_BICEP.read_text()

    assert "publicNetworkAccess: 'Disabled'" in template
    assert "Microsoft.Network/virtualNetworks@" in template
    assert "Microsoft.Network/privateEndpoints@" in template
    assert "Microsoft.Network/privateDnsZones@" in template
    assert "infrastructureSubnetId:" in template
    assert "privatelink.blob." in template


def test_telemetry_service_name_is_deployment_unique():
    template = WORKLOAD_BICEP.read_text()

    assert "var telemetryServiceName = 'sre-event-lab-${suffix}'" in template
    assert "value: telemetryServiceName" in template
    assert "output telemetryServiceName string" in template
