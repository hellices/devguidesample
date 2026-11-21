@description('Azure region for all Event Hubs benchmark resources.')
param location string = resourceGroup().location

@description('Azure region for Premium Event Hubs namespace (defaults to koreasouth when location is koreacentral due to regional capacity restrictions).')
param premiumLocation string = location == 'koreacentral' ? 'koreasouth' : location

@minLength(3)
@maxLength(12)
@description('Short prefix for resource names.')
param namePrefix string = 'ehcubench'

@minLength(6)
@maxLength(13)
@description('Deterministic suffix generated from the resource group ID.')
param uniqueSuffix string = substring(uniqueString(resourceGroup().id), 0, 6)

@description('Deploy Standard tier Event Hubs namespace (TU model).')
param deployStandard bool = true

@allowed([1, 2, 4, 8, 16, 20, 40])
@description('Throughput Units (TU) allocated to the Standard namespace.')
param standardCapacity int = 1

@description('Deploy Premium tier Event Hubs namespace (PU isolated CPU/Memory model).')
param deployPremium bool = true

@allowed([1, 2, 4, 6, 8, 10, 12, 16])
@description('Processing Units (PU) allocated to the Premium namespace.')
param premiumCapacity int = 1

@description('Deploy Dedicated tier Event Hubs cluster (CU single-tenant model). Warning: enforces a minimum 4-hour billing lock.')
param deployDedicated bool = false

@allowed([1, 2, 4, 8, 10])
@description('Capacity Units (CU) allocated to the Dedicated cluster.')
param dedicatedCapacity int = 1

var standardNamespaceName = '${namePrefix}-std-${uniqueSuffix}'
var premiumNamespaceName = '${namePrefix}-prm-${uniqueSuffix}'
var dedicatedClusterName = '${namePrefix}-ded-cluster-${uniqueSuffix}'
var dedicatedNamespaceName = '${namePrefix}-ded-ns-${uniqueSuffix}'

resource standardNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = if (deployStandard) {
  name: standardNamespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: standardCapacity
  }
  properties: {
    isAutoInflateEnabled: false
    maximumThroughputUnits: 0
    kafkaEnabled: true
    minimumTlsVersion: '1.2'
  }
}

resource stdHubP4 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployStandard) {
  parent: standardNamespace
  name: 'telemetry-p4'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

resource stdHubP16 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployStandard) {
  parent: standardNamespace
  name: 'telemetry-p16'
  properties: {
    partitionCount: 16
    messageRetentionInDays: 1
  }
}

resource stdHubP32 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployStandard) {
  parent: standardNamespace
  name: 'telemetry-p32'
  properties: {
    partitionCount: 32
    messageRetentionInDays: 1
  }
}

resource stdCgP32 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = if (deployStandard) {
  parent: stdHubP32
  name: 'cg-benchmark'
  properties: {
    userMetadata: 'Benchmark consumer group for lag monitoring'
  }
}

resource premiumNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = if (deployPremium) {
  name: premiumNamespaceName
  location: premiumLocation
  sku: {
    name: 'Premium'
    tier: 'Premium'
    capacity: premiumCapacity
  }
  properties: {
    isAutoInflateEnabled: false
    maximumThroughputUnits: 0
    kafkaEnabled: true
    minimumTlsVersion: '1.2'
  }
}

resource prmHubP4 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployPremium) {
  parent: premiumNamespace
  name: 'telemetry-p4'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

resource prmHubP16 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployPremium) {
  parent: premiumNamespace
  name: 'telemetry-p16'
  properties: {
    partitionCount: 16
    messageRetentionInDays: 1
  }
}

resource prmHubP32 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployPremium) {
  parent: premiumNamespace
  name: 'telemetry-p32'
  properties: {
    partitionCount: 32
    messageRetentionInDays: 1
  }
}

resource prmCgP32 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = if (deployPremium) {
  parent: prmHubP32
  name: 'cg-benchmark'
  properties: {
    userMetadata: 'Benchmark consumer group for lag monitoring'
  }
}

resource dedicatedCluster 'Microsoft.EventHub/clusters@2024-01-01' = if (deployDedicated) {
  name: dedicatedClusterName
  location: location
  sku: {
    name: 'Dedicated'
    capacity: dedicatedCapacity
  }
  properties: {
    supportsScaling: true
  }
}

resource dedicatedNamespace 'Microsoft.EventHub/namespaces@2024-01-01' = if (deployDedicated) {
  name: dedicatedNamespaceName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    clusterArmId: deployDedicated ? dedicatedCluster.id : ''
    kafkaEnabled: true
    minimumTlsVersion: '1.2'
  }
}

resource dedHubP4 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p4'
  properties: {
    partitionCount: 4
    messageRetentionInDays: 1
  }
}

resource dedHubP16 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p16'
  properties: {
    partitionCount: 16
    messageRetentionInDays: 1
  }
}

resource dedHubP32 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p32'
  properties: {
    partitionCount: 32
    messageRetentionInDays: 1
  }
}

resource dedHubP64 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p64'
  properties: {
    partitionCount: 64
    messageRetentionInDays: 1
  }
}

resource dedHubP128 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p128'
  properties: {
    partitionCount: 128
    messageRetentionInDays: 1
  }
}

resource dedHubP256 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = if (deployDedicated) {
  parent: dedicatedNamespace
  name: 'telemetry-p256'
  properties: {
    partitionCount: 256
    messageRetentionInDays: 1
  }
}

output standardNamespaceName string = deployStandard ? standardNamespace.name : ''
output premiumNamespaceName string = deployPremium ? premiumNamespace.name : ''
output dedicatedClusterName string = deployDedicated ? dedicatedCluster.name : ''
output dedicatedNamespaceName string = deployDedicated ? dedicatedNamespace.name : ''
