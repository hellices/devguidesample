@description('Azure region for the isolated, non-production lab.')
param location string = resourceGroup().location

@minLength(6)
@maxLength(10)
@description('The alphanumeric azd environment name.')
param suffix string

@description('Object ID of the lab operator, used only on the new AKS cluster.')
param operatorObjectId string

@description('A supported non-preview AKS minor version, checked before deployment.')
param kubernetesVersion string = '1.35'

@description('Informational expiry tag; tags do not automatically delete resources.')
param expiresOn string

var tags = {
  purpose: 'mcp-entra-walkthrough'
  environment: 'lab'
  labId: suffix
  'azd-env-name': suffix
  expiresOn: expiresOn
}
var apimName = 'apim-mcplab-${suffix}'
var environmentName = 'cae-mcplab-${suffix}'

resource apimNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-apim-${suffix}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowApiManagementControlPlane'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '3443'
          sourceAddressPrefix: 'ApiManagement'
          destinationAddressPrefix: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-mcplab-${suffix}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: ['10.62.0.0/16']
    }
    subnets: [
      {
        name: 'container-apps'
        properties: {
          addressPrefix: '10.62.0.0/23'
          delegations: [
            {
              name: 'container-apps'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: 'apim'
        properties: {
          addressPrefix: '10.62.2.0/24'
          networkSecurityGroup: { id: apimNsg.id }
        }
      }
      {
        name: 'aks'
        properties: {
          addressPrefix: '10.62.4.0/22'
        }
      }
    ]
  }
}

resource apimIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-apim-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: { domainNameLabel: apimName }
  }
}

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: apimName
  location: location
  tags: tags
  sku: { name: 'Developer', capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherName: 'MCP isolated lab'
    publisherEmail: 'mcp-lab@example.com'
    virtualNetworkType: 'Internal'
    virtualNetworkConfiguration: {
      subnetResourceId: '${vnet.id}/subnets/apim'
    }
    publicIpAddressId: apimIp.id
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: 'acrmcplab${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mcp-app-${suffix}'
  location: location
  tags: tags
}

resource registryPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, appIdentity.id, 'AcrPull')
  scope: registry
  properties: {
    principalId: appIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
  }
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    infrastructureResourceGroup: '${resourceGroup().name}-aca-managed'
    vnetConfiguration: {
      infrastructureSubnetId: '${vnet.id}/subnets/container-apps'
      internal: true
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

module apimDns './private-dns.bicep' = {
  name: 'apim-dns'
  params: {
    zoneName: '${apim.name}.azure-api.net'
    address: apim.properties.privateIPAddresses[0]
    recordName: '@'
    vnetId: vnet.id
    tags: tags
  }
}

resource aksIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-mcp-aks-${suffix}'
  location: location
  tags: tags
}

resource aksNetworkRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vnet.id, aksIdentity.id, 'NetworkContributor')
  scope: vnet
  properties: {
    principalId: aksIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7')
  }
}

resource aks 'Microsoft.ContainerService/managedClusters@2025-01-01' = {
  name: 'aks-mcplab-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Base', tier: 'Free' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${aksIdentity.id}': {} }
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: 'aks-mcplab-${suffix}'
    nodeResourceGroup: '${resourceGroup().name}-nodes'
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: { managed: true, enableAzureRBAC: true }
    agentPoolProfiles: [
      {
        name: 'system'
        count: 1
        vmSize: 'Standard_D4as_v5'
        osType: 'Linux'
        osSKU: 'Ubuntu'
        mode: 'System'
        type: 'VirtualMachineScaleSets'
        osDiskSizeGB: 64
        osDiskType: 'Managed'
        vnetSubnetID: '${vnet.id}/subnets/aks'
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      podCidr: '172.20.0.0/16'
      serviceCidr: '10.64.0.0/16'
      dnsServiceIP: '10.64.0.10'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
    }
  }
  dependsOn: [aksNetworkRole]
}

resource operatorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aks.id, operatorObjectId, 'lab-operator')
  scope: aks
  properties: {
    principalId: operatorObjectId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b')
  }
}

output apimName string = apim.name
output apimGateway string = apim.properties.gatewayUrl
output registryName string = registry.name
output registryHost string = registry.properties.loginServer
output environmentName string = environment.name
output environmentDomain string = environment.properties.defaultDomain
output environmentStaticIp string = environment.properties.staticIp
output vnetId string = vnet.id
output appIdentityId string = appIdentity.id
output appIdentityClientId string = appIdentity.properties.clientId
output appIdentityPrincipalId string = appIdentity.properties.principalId
output environmentId string = environment.id
output aksName string = aks.name
output managedNodeResourceGroup string = aks.properties.nodeResourceGroup
