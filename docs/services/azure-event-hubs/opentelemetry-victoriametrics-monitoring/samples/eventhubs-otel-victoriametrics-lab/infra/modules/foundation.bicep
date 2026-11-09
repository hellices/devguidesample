param location string
@minLength(8)
param token string
param tags object

@secure()
param grafanaAdminPassword string

var gatewaySubnetPrefix = '10.42.1.0/24'
var aksSubnetPrefix = '10.42.2.0/24'
var endpointsSubnetPrefix = '10.42.3.0/24'
var vmSinglePrivateIp = '10.42.2.20'
var acrPullRoleDefinitionId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUserRoleDefinitionId = '4633458b-17de-408a-b874-0445c86b69e6'
var storageBlobDataContributorRoleDefinitionId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var storageBlobDataReaderRoleDefinitionId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${token}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.42.0.0/16'
      ]
    }
  }
}

resource gatewaySubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'gateway'
  properties: {
    addressPrefix: gatewaySubnetPrefix
  }
}

resource aksSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'aks'
  properties: {
    addressPrefix: aksSubnetPrefix
  }
  dependsOn: [
    gatewaySubnet
  ]
}

resource endpointsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: vnet
  name: 'private-endpoints'
  properties: {
    addressPrefix: endpointsSubnetPrefix
  }
  dependsOn: [
    aksSubnet
  ]
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acr${token}'
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    policies: {
      exportPolicy: {
        status: 'enabled'
      }
      quarantinePolicy: {
        status: 'disabled'
      }
      retentionPolicy: {
        days: 7
        status: 'disabled'
      }
      trustPolicy: {
        status: 'disabled'
        type: 'Notary'
      }
    }
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${token}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    // Data-plane access only through the private endpoint. Many governed tenants enforce this with a modify policy anyway.
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    changeFeed: {
      enabled: false
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource workloadCheckpoints 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'workload-checkpoints'
  properties: {
    publicAccess: 'None'
  }
}

resource collectorCheckpoints 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'collector-checkpoints'
  properties: {
    publicAccess: 'None'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-${token}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: true
    publicNetworkAccess: 'Disabled'
    softDeleteRetentionInDays: 7
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource grafanaPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'grafana-admin-password'
  properties: {
    attributes: {
      enabled: true
    }
    contentType: 'Grafana administrator password'
    value: grafanaAdminPassword
  }
}

var privateLinks = [
  {
    name: 'vault'
    zone: 'privatelink.vaultcore.azure.net'
    groupId: 'vault'
    targetId: keyVault.id
  }
  {
    name: 'blob'
    zone: 'privatelink.blob.${environment().suffixes.storage}'
    groupId: 'blob'
    targetId: storage.id
  }
]

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for link in privateLinks: {
  name: link.zone
  location: 'global'
  tags: tags
}]

resource privateDnsLinks 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (link, i) in privateLinks: {
  parent: privateDnsZones[i]
  name: 'vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2024-05-01' = [for link in privateLinks: {
  name: 'pe-${link.name}-${token}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: endpointsSubnet.id
    }
    privateLinkServiceConnections: [
      {
        name: link.name
        properties: {
          privateLinkServiceId: link.targetId
          groupIds: [
            link.groupId
          ]
        }
      }
    ]
  }
}]

resource privateDnsGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = [for (link, i) in privateLinks: {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: link.name
        properties: {
          privateDnsZoneId: privateDnsZones[i].id
        }
      }
    ]
  }
}]

resource gatewayIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-gateway-${token}'
  location: location
  tags: tags
}

resource producerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-producer-${token}'
  location: location
  tags: tags
}

resource consumerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-consumer-${token}'
  location: location
  tags: tags
}

resource gatewayAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, gatewayIdentity.id, acrPullRoleDefinitionId)
  scope: acr
  properties: {
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleDefinitionId)
  }
}

resource gatewayKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, gatewayIdentity.id, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleDefinitionId)
  }
}

resource consumerCheckpointContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workloadCheckpoints.id, consumerIdentity.id, storageBlobDataContributorRoleDefinitionId)
  scope: workloadCheckpoints
  properties: {
    principalId: consumerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleDefinitionId)
  }
}

// The lag exporter only lists workload checkpoints; it never writes them.
resource gatewayCheckpointReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workloadCheckpoints.id, gatewayIdentity.id, storageBlobDataReaderRoleDefinitionId)
  scope: workloadCheckpoints
  properties: {
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleDefinitionId)
  }
}

// azureeventhubreceiver's blob checkpoint store writes ownership and checkpoint blobs.
resource gatewayCollectorCheckpointContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(collectorCheckpoints.id, gatewayIdentity.id, storageBlobDataContributorRoleDefinitionId)
  scope: collectorCheckpoints
  properties: {
    principalId: gatewayIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleDefinitionId)
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output gatewaySubnetId string = gatewaySubnet.id
output aksSubnetId string = aksSubnet.id
output acrId string = acr.id
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output storageName string = storage.name
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output keyVaultName string = keyVault.name
output gatewayIdentityId string = gatewayIdentity.id
output gatewayPrincipalId string = gatewayIdentity.properties.principalId
output gatewayClientId string = gatewayIdentity.properties.clientId
output producerPrincipalId string = producerIdentity.properties.principalId
output producerClientId string = producerIdentity.properties.clientId
output consumerPrincipalId string = consumerIdentity.properties.principalId
output consumerClientId string = consumerIdentity.properties.clientId
output vmSinglePrivateIp string = vmSinglePrivateIp
