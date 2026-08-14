targetScope = 'subscription'

@description('Name of the azd environment. Used to derive the resource group and a stable resource suffix.')
param environmentName string

@description('Azure region for the resource group and all regional lab resources.')
param location string

@description('Dedicated resource group for the disposable SRE lab. Defaults to rg-<environmentName> when not set.')
param resourceGroupName string = 'rg-${environmentName}'

@description('Container image deployed by the initial azd provision. postprovision replaces this with the ACR-built immutable image.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Optional Azure Monitor Action Group resource ID for event-driven SRE invocation.')
param actionGroupResourceId string = ''

@description('Base tags applied to the resource group and lab resources.')
param tags object = {}

@description('Optional ISO-8601 date after which the lab resources are considered expired.')
param expiresOn string = ''

// Truncated to 8 characters to satisfy lab.bicep's @minLength(6)/@maxLength(12) suffix constraint.
var suffix = substring(uniqueString(subscription().id, environmentName), 0, 8)

var requiredTags = union(tags, {
  purpose: 'sre-agent-event-lab'
  'azd-env-name': environmentName
}, empty(expiresOn) ? {} : {
  expiresOn: expiresOn
})

resource labResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: requiredTags
}

module lab 'lab.bicep' = {
  name: 'sre-agent-event-lab'
  scope: labResourceGroup
  params: {
    location: location
    suffix: suffix
    containerImage: containerImage
    deployContainerApp: true
    actionGroupResourceId: actionGroupResourceId
    tags: requiredTags
  }
}

output AZURE_RESOURCE_GROUP string = labResourceGroup.name
output AZURE_ACR_NAME string = lab.outputs.acrName
output AZURE_CONTAINER_APP_NAME string = lab.outputs.containerAppName
output AZURE_CONTAINER_APP_FQDN string = lab.outputs.containerAppFqdn
output AZURE_WORKSPACE_ID string = lab.outputs.workspaceId
output AZURE_APP_INSIGHTS_NAME string = lab.outputs.appInsightsName
output AZURE_STORAGE_CONTAINER_SCOPE string = lab.outputs.storageContainerScope
output AZURE_BLOB_ROLE_ASSIGNMENT_NAME string = lab.outputs.blobRoleAssignmentName
output AZURE_TELEMETRY_SERVICE_NAME string = lab.outputs.telemetryServiceName
