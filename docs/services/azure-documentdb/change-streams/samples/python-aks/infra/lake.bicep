// ADLS Gen2 landing zone for the Airflow export path.
// Public network access and shared key access are disabled. AKS pods reach the
// account through blob and dfs private endpoints and authenticate with a
// user-assigned managed identity federated to a Kubernetes service account.

targetScope = 'resourceGroup'

@description('Region for every resource.')
param location string = resourceGroup().location

@description('Short prefix used in resource names. Must match cluster.bicep.')
param prefix string = 'docdbcs'

@description('OIDC issuer URL of the AKS cluster.')
param oidcIssuerUrl string

@description('Kubernetes namespace and service account that run the export task.')
param serviceAccountNamespace string = 'cslab'
param serviceAccountName string = 'cs-lake'

@description('File system (container) for exported change events.')
param fileSystemName string = 'cdc'

var suffix = uniqueString(resourceGroup().id)
var storageName = '${prefix}lake${suffix}'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: 'vnet-${prefix}'
}

resource storage 'Microsoft.Storage/storageAccounts@2024-01-01' = {
  name: storageName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    isHnsEnabled: true
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2024-01-01' = {
  parent: storage
  name: 'default'
}

resource fileSystem 'Microsoft.Storage/storageAccounts/blobServices/containers@2024-01-01' = {
  parent: blobService
  name: fileSystemName
}

// Data Lake Storage needs both blob and dfs private endpoints.
var endpoints = [
  {
    groupId: 'blob'
    zone: 'privatelink.blob.${environment().suffixes.storage}'
  }
  {
    groupId: 'dfs'
    zone: 'privatelink.dfs.${environment().suffixes.storage}'
  }
]

resource zones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for ep in endpoints: {
  name: ep.zone
  location: 'global'
}]

resource zoneLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (ep, i) in endpoints: {
  parent: zones[i]
  name: 'link-${prefix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for ep in endpoints: {
  name: 'pe-${storageName}-${ep.groupId}'
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/snet-pe'
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${storageName}-${ep.groupId}'
        properties: {
          privateLinkServiceId: storage.id
          groupIds: [
            ep.groupId
          ]
        }
      }
    ]
  }
}]

resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (ep, i) in endpoints: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: ep.groupId
        properties: {
          privateDnsZoneId: zones[i].id
        }
      }
    ]
  }
}]

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-${prefix}-lake'
  location: location
}

resource federation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: identity
  name: 'aks-${serviceAccountNamespace}-${serviceAccountName}'
  properties: {
    issuer: oidcIssuerUrl
    subject: 'system:serviceaccount:${serviceAccountNamespace}:${serviceAccountName}'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

// Storage Blob Data Contributor on the account.
resource lakeWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, identity.id, 'blobcontrib')
  scope: storage
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}

output storageAccountName string = storage.name
output dfsEndpoint string = storage.properties.primaryEndpoints.dfs
output fileSystemName string = fileSystem.name
output identityClientId string = identity.properties.clientId
