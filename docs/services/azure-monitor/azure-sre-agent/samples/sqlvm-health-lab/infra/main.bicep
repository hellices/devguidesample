// Entry point: creates the lab resource group and every lab resource.
targetScope = 'subscription'

@description('Resource group that holds every lab resource.')
param resourceGroupName string = 'rg-sqlvm-sre-lab'

@description('Region for every lab resource. Must support Azure SRE Agent.')
param location string = 'koreacentral'

@description('Short prefix used in resource names.')
@maxLength(12)
param prefix string = 'sqlsre'

@description('VM size for SQL Server.')
param vmSize string = 'Standard_D4s_v5'

@description('Local administrator name of the Windows VM.')
param adminUsername string = 'azureadmin'

@secure()
@description('Local administrator password of the Windows VM. scripts/configure-sql.sh resets it to a one-time value, so it is not stored.')
param adminPassword string

@description('Object ID of the user who deploys the lab. Receives SRE Agent Administrator on the agent.')
param deployerObjectId string

param tags object = {
  workload: 'sqlvm-sre-agent-lab'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module lab 'resources.bicep' = {
  name: 'sqlvm-sre-lab'
  scope: rg
  params: {
    location: location
    prefix: prefix
    vmSize: vmSize
    adminUsername: adminUsername
    adminPassword: adminPassword
    deployerObjectId: deployerObjectId
    tags: tags
  }
}

output resourceGroupName string = rg.name
output vmName string = lab.outputs.vmName
output vmId string = lab.outputs.vmId
output sqlHost string = lab.outputs.sqlHost
output sqlPort int = lab.outputs.sqlPort
output keyVaultName string = lab.outputs.keyVaultName
output keyVaultId string = lab.outputs.keyVaultId
output agentName string = lab.outputs.agentName
output agentId string = lab.outputs.agentId
output agentIdentityClientId string = lab.outputs.agentIdentityClientId
output agentIdentityPrincipalId string = lab.outputs.agentIdentityPrincipalId
output vmMetricsClientId string = lab.outputs.vmMetricsClientId
output vmMetricsPrincipalId string = lab.outputs.vmMetricsPrincipalId
output monitorWorkspaceId string = lab.outputs.monitorWorkspaceId
output prometheusQueryEndpoint string = lab.outputs.prometheusQueryEndpoint
output grafanaName string = lab.outputs.grafanaName
output grafanaEndpoint string = lab.outputs.grafanaEndpoint
