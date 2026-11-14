targetScope = 'subscription'

@description('Resource group for the Multi-Hub Private AKS fleet and SRE Agent lab.')
param resourceGroupName string = 'rg-private-aks-fleet'

@description('Primary region for the Azure SRE Agent and Hub VNet.')
param agentLocation string = 'koreacentral'

@description('Region for the Multi-Hub Firewall and Private AKS clusters.')
param aksLocation string = 'australiaeast'

@description('Object ID of the signed-in administrator who receives SRE Agent Administrator.')
param adminPrincipalId string

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: agentLocation
}

module lab 'resources.bicep' = {
  name: 'private-aks-fleet-lab'
  scope: rg
  params: {
    agentLocation: agentLocation
    aksLocation: aksLocation
    adminPrincipalId: adminPrincipalId
  }
}

output agentId string = lab.outputs.agentId
output agentName string = lab.outputs.agentName
output agentUamiPrincipalId string = lab.outputs.agentUamiPrincipalId
output resourceGroupName string = rg.name
