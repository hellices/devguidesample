param location string
@minLength(8)
param token string
param tags object
param gatewayPrincipalId string
param producerPrincipalId string
param consumerPrincipalId string

var premiumNamespaceName = 'ehp-${token}'
var telemetryNamespaceName = 'eht-${token}'
var workloadEventHubName = 'workload'
var workloadConsumerGroup = 'slow-consumer'
var telemetryEventHubName = 'platform-metrics'
var telemetryConsumerGroup = 'otel-collector'
var monitoringReaderRoleDefinitionId = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
var eventHubsDataSenderRoleDefinitionId = '2b629674-e913-4c01-ae53-ef4638d8f975'
var eventHubsDataReceiverRoleDefinitionId = 'a638d3c7-ab3a-418d-83e6-5f17a39d4fde'

resource premiumNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: premiumNamespaceName
  location: location
  // azuremonitorreceiver filters on this tag so the Standard telemetry sink in the same RG is not polled.
  tags: union(tags, {
    'otel-metrics-source': 'premium'
  })
  sku: {
    name: 'Premium'
    tier: 'Premium'
    capacity: 1
  }
  properties: {
    disableLocalAuth: true
    isAutoInflateEnabled: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
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

resource telemetryNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = {
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

resource telemetryHub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: telemetryNamespace
  name: telemetryEventHubName
  properties: {
    messageRetentionInDays: 1
    partitionCount: 2
    status: 'Active'
  }
}

resource telemetryCollectorConsumer 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = {
  parent: telemetryHub
  name: telemetryConsumerGroup
  properties: {
    userMetadata: 'OpenTelemetry Collector diagnostic metrics consumer.'
  }
}

resource telemetryDiagnosticRule 'Microsoft.EventHub/namespaces/authorizationRules@2024-01-01' = {
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

resource premiumMetricsToTelemetryHub 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
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

resource gatewayMonitoringReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(premiumNamespace.id, gatewayPrincipalId, monitoringReaderRoleDefinitionId)
  scope: premiumNamespace
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

resource gatewayTelemetryReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(telemetryHub.id, gatewayPrincipalId, eventHubsDataReceiverRoleDefinitionId)
  scope: telemetryHub
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
output telemetryNamespaceName string = telemetryNamespace.name
output telemetryEventHubName string = telemetryHub.name
