param location string
@minLength(8)
param token string
param tags object
param gatewayPrincipalId string
param producerPrincipalId string
param consumerPrincipalId string
@allowed([
  'Premium'
  'Dedicated'
])
param eventHubsSku string = 'Premium'
@description('Stream the workload namespace ApplicationMetricsLogs and RuntimeAuditLogs (Premium and Dedicated only) to a telemetry hub.')
@allowed([
  'Enabled'
  'Disabled'
])
param eventHubsLogs string = 'Enabled'
@description('Also stream AllMetrics of the namespace (and cluster) to a telemetry hub. Off by default: the Metrics API already returns every one of these metrics sooner and with dimensions; enable only to compare the paths.')
@allowed([
  'Enabled'
  'Disabled'
])
param eventHubsDiagnosticMetrics string = 'Disabled'

var premiumNamespaceName = 'ehp-${token}'
var telemetryNamespaceName = 'eht-${token}'
var workloadEventHubName = 'workload'
var workloadConsumerGroup = 'slow-consumer'
var telemetryEventHubName = 'platform-metrics'
var telemetryConsumerGroup = 'otel-collector'
var telemetryLogsEventHubName = 'runtime-logs'
var logsEnabled = eventHubsLogs == 'Enabled'
var diagnosticMetricsEnabled = eventHubsDiagnosticMetrics == 'Enabled'
// The telemetry namespace exists only as a Diagnostic Settings sink.
var telemetryEnabled = logsEnabled || diagnosticMetricsEnabled
var dedicated = eventHubsSku == 'Dedicated'
var monitoringReaderRoleDefinitionId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var eventHubsDataSenderRoleDefinitionId = '2b629674-e913-4c01-ae53-ef4638d8f975'
var eventHubsDataReceiverRoleDefinitionId = 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'

// Opt-in (EVENTHUBS_SKU=Dedicated): a 1 CU cluster cannot be deleted for four hours after creation.
resource dedicatedCluster 'Microsoft.EventHub/clusters@2024-01-01' = if (dedicated) {
  name: 'ehc-${token}'
  location: location
  tags: tags
  sku: {
    name: 'Dedicated'
    capacity: 1
  }
  properties: {
    supportsScaling: true
  }
}

// The workload namespace: Premium 1 PU, or a namespace inside the Dedicated cluster.
resource premiumNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: premiumNamespaceName
  location: location
  // azuremonitorreceiver filters on this tag so the Standard telemetry sink in the same RG is not polled.
  tags: union(tags, {
    'otel-metrics-source': 'premium'
  })
  sku: dedicated ? {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  } : {
    name: 'Premium'
    tier: 'Premium'
    capacity: 1
  }
  properties: union({
    disableLocalAuth: true
    isAutoInflateEnabled: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }, dedicated ? {
    clusterArmId: dedicatedCluster.id
  } : {})
}

resource workloadHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: premiumNamespace
  name: workloadEventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 4
    status: 'Active'
  }
}

resource workloadSlowConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: workloadHub
  name: workloadConsumerGroup
  properties: {
    userMetadata: 'Slow consumer used to create and recover observable backlog.'
  }
}

resource telemetryNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = if (telemetryEnabled) {
  name: telemetryNamespaceName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    disableLocalAuth: false
    isAutoInflateEnabled: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

resource telemetryHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (diagnosticMetricsEnabled) {
  parent: telemetryNamespace
  name: telemetryEventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
    status: 'Active'
  }
}

resource telemetryCollectorConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = if (diagnosticMetricsEnabled) {
  parent: telemetryHub
  name: telemetryConsumerGroup
  properties: {
    userMetadata: 'OpenTelemetry Collector diagnostic metrics consumer.'
  }
}

// Logs get their own hub: the metrics receiver would otherwise parse log records as metrics.
resource telemetryLogsHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (logsEnabled) {
  parent: telemetryNamespace
  name: telemetryLogsEventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
    status: 'Active'
  }
}

resource telemetryLogsCollectorConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = if (logsEnabled) {
  parent: telemetryLogsHub
  name: telemetryConsumerGroup
  properties: {
    userMetadata: 'OpenTelemetry Collector Event Hubs resource log consumer.'
  }
}

resource telemetryDiagnosticRule 'Microsoft.EventHub/namespaces/authorizationRules@2024-01-01' = if (telemetryEnabled) {
  parent: telemetryNamespace
  name: 'diagnostics-send'
  properties: {
    rights: [
      'Listen'
      'Manage'
      'Send'
    ]
  }
}

resource premiumMetricsToTelemetryHub 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (diagnosticMetricsEnabled) {
  name: 'platform-metrics-to-eventhub'
  scope: premiumNamespace
  properties: {
    eventHubAuthorizationRuleId: telemetryDiagnosticRule.id
    eventHubName: telemetryHub.name
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          days: 0
          enabled: false
        }
      }
    ]
  }
}

// Data plane logs: ConsumerLag and other runtime values per partition, and aggregated access audit.
resource premiumLogsToTelemetryHub 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (logsEnabled) {
  name: 'runtime-logs-to-eventhub'
  scope: premiumNamespace
  properties: {
    eventHubAuthorizationRuleId: telemetryDiagnosticRule.id
    eventHubName: telemetryLogsHub.name
    logs: [
      {
        category: 'ApplicationMetricsLogs'
        enabled: true
      }
      {
        category: 'RuntimeAuditLogs'
        enabled: true
      }
    ]
  }
}

// The cluster has its own metric set (CPU, AvailableMemory by Role); stream it next to the namespace's.
resource clusterMetricsToTelemetryHub 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (dedicated && diagnosticMetricsEnabled) {
  name: 'platform-metrics-to-eventhub'
  scope: dedicatedCluster
  properties: {
    eventHubAuthorizationRuleId: telemetryDiagnosticRule.id
    eventHubName: telemetryHub.name
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          days: 0
          enabled: false
        }
      }
    ]
  }
}

resource gatewayMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(premiumNamespace.id, gatewayPrincipalId, monitoringReaderRoleDefinitionId)
  scope: premiumNamespace
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleDefinitionId)
  }
}

resource gatewayClusterMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (dedicated) {
  name: guid(dedicatedCluster.id, gatewayPrincipalId, monitoringReaderRoleDefinitionId)
  scope: dedicatedCluster
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReaderRoleDefinitionId)
  }
}

resource producerWorkloadSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workloadHub.id, producerPrincipalId, eventHubsDataSenderRoleDefinitionId)
  scope: workloadHub
  properties: {
    principalId: producerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataSenderRoleDefinitionId)
  }
}

resource consumerWorkloadReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workloadHub.id, consumerPrincipalId, eventHubsDataReceiverRoleDefinitionId)
  scope: workloadHub
  properties: {
    principalId: consumerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataReceiverRoleDefinitionId)
  }
}

resource gatewayWorkloadReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workloadHub.id, gatewayPrincipalId, eventHubsDataReceiverRoleDefinitionId)
  scope: workloadHub
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataReceiverRoleDefinitionId)
  }
}

resource gatewayTelemetryReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (diagnosticMetricsEnabled) {
  name: guid(telemetryHub.id, gatewayPrincipalId, eventHubsDataReceiverRoleDefinitionId)
  scope: telemetryHub
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataReceiverRoleDefinitionId)
  }
}

resource gatewayTelemetryLogsReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (logsEnabled) {
  name: guid(telemetryLogsHub.id, gatewayPrincipalId, eventHubsDataReceiverRoleDefinitionId)
  scope: telemetryLogsHub
  properties: {
    principalId: gatewayPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', eventHubsDataReceiverRoleDefinitionId)
  }
}

output premiumNamespaceName string = premiumNamespace.name
output premiumNamespaceId string = premiumNamespace.id
output workloadEventHubName string = workloadHub.name
output workloadConsumerGroup string = workloadSlowConsumer.name
output telemetryNamespaceName string = telemetryEnabled ? telemetryNamespace.name : ''
output telemetryEventHubName string = diagnosticMetricsEnabled ? telemetryHub.name : ''
output telemetryLogsEventHubName string = logsEnabled ? telemetryLogsHub.name : ''
output dedicatedClusterId string = dedicated ? dedicatedCluster.id : ''
