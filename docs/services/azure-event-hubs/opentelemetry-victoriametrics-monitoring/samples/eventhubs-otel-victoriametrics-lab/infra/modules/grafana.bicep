// Optional Azure Managed Grafana (MANAGED_GRAFANA=Enabled). The postprovision hook connects it to the
// private VMSingle through a managed private endpoint and a Private Link Service on the AKS internal LB.
// Grafana Admin for the deployer is granted by the hook only if missing: creating the workspace
// assigned it to the caller automatically, and a second Bicep assignment then fails as a duplicate.
param location string
@minLength(8)
param token string
param tags object
resource grafana 'Microsoft.Dashboard/grafana@2024-10-01' = {
  name: 'amg-${token}'
  location: location
  tags: tags
  // Managed private endpoints require the Standard tier.
  sku: {
    name: 'Standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    apiKey: 'Disabled'
    deterministicOutboundIP: 'Disabled'
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
  }
}

output name string = grafana.name
output endpoint string = grafana.properties.endpoint
output principalId string = grafana.identity.principalId
