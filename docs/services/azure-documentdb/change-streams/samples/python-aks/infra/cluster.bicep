// Azure DocumentDB (vCore) + AKS + ACR for the Python change stream lab.
// Deployed by main.bicep into the azd resource group.
// The cluster has public network access disabled and is reached from AKS
// through a private endpoint and the privatelink.mongocluster.cosmos.azure.com zone.

targetScope = 'resourceGroup'

@description('Region for every resource.')
param location string = resourceGroup().location

@description('Short prefix used in resource names.')
param prefix string = 'docdbcs'

@description('DocumentDB administrator user name.')
param adminUserName string = 'csadmin'

@secure()
@description('DocumentDB administrator password.')
param adminPassword string

@description('DocumentDB compute tier, for example M30.')
param clusterTier string = 'M30'

@description('Storage size per shard in GiB.')
param storageSizeGb int = 32

@description('AKS node VM size.')
param nodeVmSize string = 'Standard_D4s_v6'

@description('AKS node count.')
param nodeCount int = 2

var suffix = uniqueString(resourceGroup().id)
var clusterName = '${prefix}-${suffix}'
var privateDnsZoneName = 'privatelink.mongocluster.cosmos.azure.com'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${prefix}'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.40.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'snet-aks'
        properties: {
          addressPrefix: '10.40.0.0/22'
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '10.40.8.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

resource cluster 'Microsoft.DocumentDB/mongoClusters@2025-09-01' = {
  name: clusterName
  location: location
  properties: {
    administrator: {
      userName: adminUserName
      password: adminPassword
    }
    compute: {
      tier: clusterTier
    }
    storage: {
      sizeGb: storageSizeGb
    }
    sharding: {
      shardCount: 1
    }
    highAvailability: {
      targetMode: 'Disabled'
    }
    publicNetworkAccess: 'Disabled'
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneName
  location: 'global'
}

resource privateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: privateDnsZone
  name: 'link-${prefix}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${clusterName}'
  location: location
  properties: {
    subnet: {
      id: '${vnet.id}/subnets/snet-pe'
    }
    privateLinkServiceConnections: [
      {
        name: 'plsc-${clusterName}'
        properties: {
          privateLinkServiceId: cluster.id
          groupIds: [
            'MongoCluster'
          ]
        }
      }
    ]
  }
}

resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'mongocluster'
        properties: {
          privateDnsZoneId: privateDnsZone.id
        }
      }
    ]
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${prefix}acr${suffix}'
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-09-01' = {
  name: 'aks-${prefix}'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    dnsPrefix: 'aks-${prefix}-${suffix}'
    // Workload identity lets the Airflow export pods use a managed identity (lake.bicep).
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        count: nodeCount
        vmSize: nodeVmSize
        osType: 'Linux'
        vnetSubnetID: '${vnet.id}/subnets/snet-aks'
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      podCidr: '192.168.0.0/16'
      serviceCidr: '172.16.0.0/16'
      dnsServiceIP: '172.16.0.10'
    }
  }
}

// AcrPull for the kubelet identity so pods can pull the lab image.
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'acrpull')
  scope: acr
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

// AKS needs Network Contributor on its subnet when using a custom VNet.
resource aksSubnetRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vnet.id, aks.id, 'netcontrib')
  scope: vnet
  properties: {
    principalId: aks.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')
  }
}

output clusterName string = cluster.name
output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output aksName string = aks.name
output oidcIssuerUrl string = aks.properties.oidcIssuerProfile.issuerURL
// Template with <user> and <password> placeholders. It holds no secret.
output connectionString string = cluster.properties.connectionString
