targetScope = 'resourceGroup'

@description('Azure region for all regional lab resources.')
param location string = resourceGroup().location

@description('Stable alphanumeric suffix used for globally unique names.')
@minLength(6)
@maxLength(12)
param suffix string

@description('Container image deployed after the ACR build completes.')
param containerImage string

@description('Whether to deploy the Container App and alert rules.')
param deployContainerApp bool = false

@description('Port the deployed container image listens on.')
param containerTargetPort int = 8000

@description('Whether to attach /healthz probes to the Container App.')
param enableHealthProbes bool = true

@description('Optional Azure Monitor Action Group resource ID for event-driven SRE invocation.')
param actionGroupResourceId string = ''

@description('Tags applied to all resources that support tags.')
param tags object

module observability 'observability.bicep' = {
  name: 'sre-lab-observability'
  params: {
    location: location
    suffix: suffix
    tags: tags
  }
}

module workload 'workload.bicep' = {
  name: 'sre-lab-workload'
  params: {
    location: location
    suffix: suffix
    containerImage: containerImage
    deployContainerApp: deployContainerApp
    containerTargetPort: containerTargetPort
    enableHealthProbes: enableHealthProbes
    workspaceCustomerId: observability.outputs.workspaceCustomerId
    workspaceSharedKey: observability.outputs.workspaceSharedKey
    appInsightsConnectionString: observability.outputs.appInsightsConnectionString
    tags: tags
  }
}

module alerts 'alerts.bicep' = if (deployContainerApp) {
  name: 'sre-lab-alerts'
  params: {
    location: location
    appInsightsResourceId: observability.outputs.appInsightsResourceId
    actionGroupResourceId: actionGroupResourceId
    serviceName: workload.outputs.telemetryServiceName
    tags: tags
  }
}

output acrName string = workload.outputs.acrName
output acrLoginServer string = workload.outputs.acrLoginServer
output containerAppName string = workload.outputs.containerAppName
output containerAppFqdn string = workload.outputs.containerAppFqdn
output containerAppPrincipalId string = workload.outputs.workloadPrincipalId
output workloadIdentityResourceId string = workload.outputs.workloadIdentityResourceId
output storageContainerScope string = workload.outputs.storageContainerScope
output blobRoleAssignmentName string = workload.outputs.blobRoleAssignmentName
output workspaceId string = observability.outputs.workspaceId
output workspaceCustomerId string = observability.outputs.workspaceCustomerId
output appInsightsName string = observability.outputs.appInsightsName
output appInsightsResourceId string = observability.outputs.appInsightsResourceId
output alertRuleNames array = deployContainerApp ? alerts!.outputs.alertRuleNames : []
output telemetryServiceName string = workload.outputs.telemetryServiceName
