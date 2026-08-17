targetScope = 'subscription'

@description('Name of the azd environment. Used to derive the resource group and a stable resource suffix.')
param environmentName string

@description('Azure region for the resource group and all regional lab resources.')
param location string

@description('Dedicated resource group for the disposable SRE lab. Defaults to rg-<environmentName> when not set.')
param resourceGroupName string = 'rg-${environmentName}'

@description('Container image deployed by azd. Leave empty for the first provision: the public placeholder image is used until the deploy phase (`postdeploy` hook, scripts/azd-deploy-app.sh) builds the lab image and records it in SRE_CONTAINER_IMAGE.')
param containerImage string = ''

@description('Optional Azure Monitor Action Group resource ID for event-driven SRE invocation.')
param actionGroupResourceId string = ''

@description('Base tags applied to the resource group and lab resources.')
param tags object = {}

@description('Optional ISO-8601 date after which the lab resources are considered expired.')
param expiresOn string = ''

// Truncated to 8 characters to satisfy lab.bicep's @minLength(6)/@maxLength(12) suffix constraint.
var suffix = substring(uniqueString(subscription().id, environmentName), 0, 8)

// The public placeholder serves port 80 and has no /healthz, so the first
// provision must expose port 80 without probes. Once the deploy phase
// (`postdeploy` hook, scripts/azd-deploy-app.sh) records the ACR-built
// image in SRE_CONTAINER_IMAGE, every later provision deploys that image
// on port 8000 with matching /healthz probes instead of reverting to the
// placeholder.
var placeholderContainerImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var effectiveContainerImage = empty(containerImage) ? placeholderContainerImage : containerImage
var usesPlaceholderImage = effectiveContainerImage == placeholderContainerImage

// azd substitutes an unset ${AZURE_RESOURCE_GROUP} with an empty string and
// passes it through, because this parameter's default is a non-empty
// expression. Fall back here so provisioning never asks for a resource group
// with an empty name.
var effectiveResourceGroupName = empty(resourceGroupName) ? 'rg-${environmentName}' : resourceGroupName

var requiredTags = union(tags, {
  purpose: 'sre-agent-event-lab'
  'azd-env-name': environmentName
}, empty(expiresOn) ? {} : {
  expiresOn: expiresOn
})

resource labResourceGroup 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: effectiveResourceGroupName
  location: location
  tags: requiredTags
}

module lab 'lab.bicep' = {
  name: 'sre-agent-event-lab'
  scope: labResourceGroup
  params: {
    location: location
    suffix: suffix
    containerImage: effectiveContainerImage
    deployContainerApp: true
    containerTargetPort: usesPlaceholderImage ? 80 : 8000
    enableHealthProbes: !usesPlaceholderImage
    actionGroupResourceId: actionGroupResourceId
    tags: requiredTags
  }
}

output AZURE_RESOURCE_GROUP string = labResourceGroup.name
output AZURE_ACR_NAME string = lab.outputs.acrName
output AZURE_CONTAINER_APP_NAME string = lab.outputs.containerAppName
output AZURE_CONTAINER_APP_FQDN string = lab.outputs.containerAppFqdn
// Read by scripts/azd-deploy-app.sh: the deploy phase waits for AcrPull on
// exactly the registry below for exactly this principal, then points the
// app's registry configuration at the identity that holds it.
output AZURE_CONTAINER_APP_PRINCIPAL_ID string = lab.outputs.containerAppPrincipalId
output AZURE_WORKLOAD_IDENTITY_RESOURCE_ID string = lab.outputs.workloadIdentityResourceId
output AZURE_ACR_LOGIN_SERVER string = lab.outputs.acrLoginServer
output AZURE_WORKSPACE_ID string = lab.outputs.workspaceId
output AZURE_APP_INSIGHTS_NAME string = lab.outputs.appInsightsName
output AZURE_STORAGE_CONTAINER_SCOPE string = lab.outputs.storageContainerScope
output AZURE_BLOB_ROLE_ASSIGNMENT_NAME string = lab.outputs.blobRoleAssignmentName
output AZURE_TELEMETRY_SERVICE_NAME string = lab.outputs.telemetryServiceName
output AZURE_WORKSPACE_CUSTOMER_ID string = lab.outputs.workspaceCustomerId
output AZURE_BASELINE_WEB_TEST_NAME string = lab.outputs.baselineWebTestName
output AZURE_DYNAMIC_THRESHOLD_ALERT_NAME string = lab.outputs.dynamicThresholdAlertName

// Deployment outputs the lab scripts (common.sh `deployment_output`,
// run-scenario.sh, query-evidence.sh) still read by their original names.
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
output baselineWebTestName string = lab.outputs.baselineWebTestName
output dynamicThresholdAlertName string = lab.outputs.dynamicThresholdAlertName
output telemetryServiceName string = lab.outputs.telemetryServiceName
