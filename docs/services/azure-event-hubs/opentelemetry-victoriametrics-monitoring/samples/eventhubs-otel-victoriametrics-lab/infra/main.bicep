targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name used for resource naming and tags.')
param environmentName string

@description('Azure region for the temporary lab resources.')
param location string = 'koreacentral'

@description('Region for both Event Hubs namespaces. Empty uses location. Diagnostic Settings require the sink Event Hub in the same region as the Premium namespace, so both move together.')
param eventHubsLocation string = ''

// The preprovision hook fills operatorEgressCidr, grafanaAdminPassword and
// gatewayAdminSshPublicKey and fails if it cannot produce them. azd up checks required inputs
// before it runs hooks, so these parameters default to ''. That default also rules out
// @minLength (BCP333), and ARM preflight accepts empty values, so the hook is the guard.
@description('Single IPv4 CIDR allowed to reach Grafana and the AKS API server.')
param operatorEgressCidr string = ''

@description('AKS Kubernetes major.minor or patch version.')
param kubernetesVersion string = '1.36'

@description('Optional existing Event Hubs Dedicated cluster to collect metrics from. Ignored when eventHubsSku is Dedicated.')
param existingDedicatedClusterResourceId string = ''

@description('Workload Event Hubs tier. Dedicated (default) creates a 1 CU cluster that cannot be deleted for four hours; Premium creates a 1 PU namespace.')
@allowed([
  'Premium'
  'Dedicated'
])
param eventHubsSku string = 'Dedicated'

@description('Enabled streams ApplicationMetricsLogs and RuntimeAuditLogs of the workload namespace to the telemetry namespace.')
@allowed([
  'Enabled'
  'Disabled'
])
param eventHubsLogs string = 'Enabled'

@description('Enabled adds an Azure Managed Grafana (Standard) that reads VMSingle through a managed private endpoint.')
@allowed([
  'Enabled'
  'Disabled'
])
param managedGrafana string = 'Disabled'

@secure()
@description('Grafana administrator password stored in Key Vault and never returned as an output.')
param grafanaAdminPassword string = ''

@description('Object ID of the operator running azd; azd supplies AZURE_PRINCIPAL_ID.')
param deployerPrincipalId string = ''

@description('Principal type of deployerPrincipalId.')
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param deployerPrincipalType string = 'User'

@description('Public key used only to satisfy the VM OS profile. No inbound SSH rule is created.')
param gatewayAdminSshPublicKey string = ''

var token = toLower(uniqueString(subscription().id, environmentName, location))
var messagingLocation = empty(eventHubsLocation) ? location : eventHubsLocation
var tags = {
  'azd-env-name': environmentName
  lab: 'eventhubs-otel-victoriametrics'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module foundation 'modules/foundation.bicep' = {
  name: 'foundation'
  scope: rg
  params: {
    location: location
    token: token
    tags: tags
    grafanaAdminPassword: grafanaAdminPassword
    operatorEgressCidr: operatorEgressCidr
  }
}

module messaging 'modules/messaging.bicep' = {
  name: 'messaging'
  scope: rg
  params: {
    location: messagingLocation
    token: token
    tags: tags
    gatewayPrincipalId: foundation.outputs.gatewayPrincipalId
    producerPrincipalId: foundation.outputs.producerPrincipalId
    consumerPrincipalId: foundation.outputs.consumerPrincipalId
    eventHubsSku: eventHubsSku
    eventHubsLogs: eventHubsLogs
  }
}

module compute 'modules/compute.bicep' = {
  name: 'compute'
  scope: rg
  params: {
    location: location
    token: token
    tags: tags
    kubernetesVersion: kubernetesVersion
    operatorEgressCidr: operatorEgressCidr
    gatewayNsgId: foundation.outputs.gatewayNsgId
    gatewayAdminSshPublicKey: gatewayAdminSshPublicKey
    aksSubnetId: foundation.outputs.aksSubnetId
    gatewaySubnetId: foundation.outputs.gatewaySubnetId
    gatewayIdentityId: foundation.outputs.gatewayIdentityId
    acrId: foundation.outputs.acrId
    vnetName: foundation.outputs.vnetName
    deployerPrincipalId: deployerPrincipalId
    deployerPrincipalType: deployerPrincipalType
  }
}

module grafana 'modules/grafana.bicep' = if (managedGrafana == 'Enabled') {
  name: 'grafana'
  scope: rg
  params: {
    location: location
    token: token
    tags: tags
  }
}

// A Premium lab can also observe an existing cluster; the gateway needs Monitoring Reader on it.
// The placeholder ID keeps every index valid when no cluster is given.
var observeExistingCluster = eventHubsSku != 'Dedicated' && !empty(existingDedicatedClusterResourceId)
var existingClusterIdParts = split(observeExistingCluster
  ? existingDedicatedClusterResourceId
  : '/subscriptions/${subscription().subscriptionId}/resourceGroups/none/providers/Microsoft.EventHub/clusters/none', '/')

module existingClusterReader 'modules/cluster-reader.bicep' = if (observeExistingCluster) {
  name: 'existing-cluster-reader'
  scope: resourceGroup(existingClusterIdParts[2], existingClusterIdParts[4])
  params: {
    clusterName: existingClusterIdParts[8]
    gatewayPrincipalId: foundation.outputs.gatewayPrincipalId
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AKS_CLUSTER_NAME string = compute.outputs.aksName
output ACR_NAME string = foundation.outputs.acrName
output ACR_LOGIN_SERVER string = foundation.outputs.acrLoginServer
output GATEWAY_VM_NAME string = compute.outputs.gatewayVmName
output GATEWAY_PUBLIC_IP string = compute.outputs.gatewayPublicIp
output GATEWAY_PRIVATE_IP string = compute.outputs.gatewayPrivateIp
output GATEWAY_CLIENT_ID string = foundation.outputs.gatewayClientId
output EVENTHUBS_LOCATION string = messagingLocation
output PREMIUM_NAMESPACE_NAME string = messaging.outputs.premiumNamespaceName
output WORKLOAD_EVENTHUB_NAME string = messaging.outputs.workloadEventHubName
output WORKLOAD_CONSUMER_GROUP string = messaging.outputs.workloadConsumerGroup
output TELEMETRY_NAMESPACE_NAME string = messaging.outputs.telemetryNamespaceName
output TELEMETRY_EVENTHUB_NAME string = messaging.outputs.telemetryEventHubName
output CHECKPOINT_ACCOUNT_NAME string = foundation.outputs.storageName
output KEY_VAULT_NAME string = foundation.outputs.keyVaultName
output PRODUCER_CLIENT_ID string = foundation.outputs.producerClientId
output CONSUMER_CLIENT_ID string = foundation.outputs.consumerClientId
output AKS_OIDC_ISSUER string = compute.outputs.aksOidcIssuer
output CHECKPOINT_ACCOUNT_URL string = foundation.outputs.storageBlobEndpoint
output VMSINGLE_PRIVATE_IP string = foundation.outputs.vmSinglePrivateIp
output EXISTING_DEDICATED_CLUSTER_RESOURCE_ID string = existingDedicatedClusterResourceId
output EVENTHUBS_SKU string = eventHubsSku
output TELEMETRY_LOGS_EVENTHUB_NAME string = messaging.outputs.telemetryLogsEventHubName
output MANAGED_GRAFANA_NAME string = grafana.?outputs.name ?? ''
output MANAGED_GRAFANA_ENDPOINT string = grafana.?outputs.endpoint ?? ''
output DEDICATED_CLUSTER_RESOURCE_ID string = messaging.outputs.dedicatedClusterId
