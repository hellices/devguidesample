targetScope = 'subscription'

param resourceGroupName string
param location string
param suffix string
param operatorObjectId string
param expiresOn string

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: {
    purpose: 'mcp-entra-validation'
    environment: 'lab'
    labId: suffix
    expiresOn: expiresOn
  }
}

module foundation './foundation.bicep' = {
  name: 'mcp-foundation'
  scope: group
  params: {
    location: location
    suffix: suffix
    operatorObjectId: operatorObjectId
    expiresOn: expiresOn
  }
}

output foundationOutputs object = {
  apimName: foundation.outputs.apimName
  apimGateway: foundation.outputs.apimGateway
  registryName: foundation.outputs.registryName
  registryHost: foundation.outputs.registryHost
  environmentName: foundation.outputs.environmentName
  environmentDomain: foundation.outputs.environmentDomain
  environmentStaticIp: foundation.outputs.environmentStaticIp
  vnetId: foundation.outputs.vnetId
  appIdentityId: foundation.outputs.appIdentityId
  aksName: foundation.outputs.aksName
  managedNodeResourceGroup: foundation.outputs.managedNodeResourceGroup
}
