targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name used for resource naming and tags.')
param environmentName string

@description('Azure region for the temporary lab resources.')
param location string = 'koreacentral'

@description('Region for both Event Hubs namespaces. Empty uses location. Diagnostic Settings require the sink Event Hub in the same region as the Premium namespace, so both move together.')
param eventHubsLocation string = ''

@description('Single IPv4 CIDR allowed to reach Grafana and the AKS API server.')
param operatorEgressCidr string

@description('AKS Kubernetes major.minor or patch version.')
param kubernetesVersion string = '1.36'

@description('Optional existing Event Hubs Dedicated cluster resource ID. This template never creates a Dedicated cluster.')
param existingDedicatedClusterResourceId string = ''

@secure()
@description('Grafana administrator password stored in Key Vault and never returned as an output.')
param grafanaAdminPassword string

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
param gatewayAdminSshPublicKey string

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
