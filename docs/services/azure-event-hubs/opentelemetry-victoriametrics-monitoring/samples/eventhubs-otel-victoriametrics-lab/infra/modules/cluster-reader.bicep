// Lets the gateway read metrics of an existing Event Hubs Dedicated cluster that this lab does not create.
@description('Name of the existing Event Hubs Dedicated cluster in the deployment resource group.')
param clusterName string

@description('Principal ID of the gateway managed identity.')
param gatewayPrincipalId string

var monitoringReaderRoleDefinitionId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

resource cluster 'Microsoft.EventHub/clusters@2024-01-01' existing = {
  name: clusterName
}

resource gatewayClusterMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cluster.id, gatewayPrincipalId, monitoringReaderRoleDefinitionId)
  scope: cluster
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleDefinitionId)
  }
}

// predown deletes exactly this assignment; it lives outside the lab resource group that azd down removes.
output roleAssignmentId string = gatewayClusterMonitoringReader.id
