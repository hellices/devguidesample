targetScope = 'subscription'

@description('Azure region for the resource group and all regional lab resources.')
param location string

@description('Dedicated resource group for the disposable SRE lab.')
param resourceGroupName string

@description('Stable alphanumeric suffix used for globally unique names.')
param suffix string

@description('Container image deployed after the ACR build completes.')
param containerImage string

@description('Whether to deploy the Container App and alert rules.')
param deployContainerApp bool = false

@description('Tags applied to the resource group and lab resources.')
param tags object

resource labResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module lab 'main.bicep' = {
  name: 'sre-agent-event-lab'
  scope: labResourceGroup
  params: {
    location: location
    suffix: suffix
    containerImage: containerImage
    deployContainerApp: deployContainerApp
    tags: tags
  }
}

output resourceGroupName string = labResourceGroup.name
output acrName string = lab.outputs.acrName
output acrLoginServer string = lab.outputs.acrLoginServer
output containerAppName string = lab.outputs.containerAppName
output containerAppFqdn string = lab.outputs.containerAppFqdn
output containerAppPrincipalId string = lab.outputs.containerAppPrincipalId
output storageContainerScope string = lab.outputs.storageContainerScope
output blobRoleAssignmentName string = lab.outputs.blobRoleAssignmentName
output workspaceId string = lab.outputs.workspaceId
output workspaceCustomerId string = lab.outputs.workspaceCustomerId
output appInsightsName string = lab.outputs.appInsightsName
output appInsightsResourceId string = lab.outputs.appInsightsResourceId
output alertRuleNames array = lab.outputs.alertRuleNames
