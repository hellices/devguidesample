// Lets the Azure Managed Grafana system-assigned identity query Azure Monitor metrics of the workload
// namespace and, for Dedicated, the cluster. Portal creation can add Monitoring Reader on the whole
// subscription; a Bicep deployment does not, so the lab grants it only on the resources it charts.
@description('Principal ID of the Managed Grafana system-assigned identity.')
param grafanaPrincipalId string

@description('Workload Event Hubs namespace name.')
param namespaceName string

@description('Dedicated cluster name, or empty for a Premium namespace.')
param clusterName string = ''

var monitoringReaderRoleDefinitionId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

resource namespace 'Microsoft.EventHub/namespaces@2024-01-01' existing = {
  name: namespaceName
}

resource cluster 'Microsoft.EventHub/clusters@2024-01-01' existing = if (!empty(clusterName)) {
  name: empty(clusterName) ? 'none' : clusterName
}

resource namespaceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(namespace.id, grafanaPrincipalId, monitoringReaderRoleDefinitionId)
  scope: namespace
  properties: {
    principalId: grafanaPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleDefinitionId)
  }
}

resource clusterReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(clusterName)) {
  name: guid(cluster.id, grafanaPrincipalId, monitoringReaderRoleDefinitionId)
  scope: cluster
  properties: {
    principalId: grafanaPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleDefinitionId)
  }
}
