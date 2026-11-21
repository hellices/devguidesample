@description('Primary region for the Azure SRE Agent and Hub VNet.')
param agentLocation string = 'koreacentral'

@description('Region for the Multi-Hub Firewall and Private AKS clusters.')
param aksLocation string = 'australiaeast'

@description('Object ID of the signed-in administrator.')
param adminPrincipalId string

var suffix = uniqueString(resourceGroup().id)
var agentName = 'sre-aks-fleet-${take(suffix, 6)}'
var uamiName = 'id-sre-aks-fleet-${take(suffix, 6)}'

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: agentLocation
}

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-sre-aks-${take(suffix, 6)}'
  location: agentLocation
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appi 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-sre-aks-${take(suffix, 6)}'
  location: agentLocation
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

resource rtAgentSandbox 'Microsoft.Network/routeTables@2024-01-01' = {
  name: 'rt-sre-agent-sandbox'
  location: agentLocation
  properties: {
    routes: [
      {
        name: 'to-aks-hub2-via-hub1-fw'
        properties: {
          addressPrefix: '10.52.0.0/16'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: '10.51.250.4'
        }
      }
      {
        name: 'to-aks-spokes-via-hub1-fw'
        properties: {
          addressPrefix: '10.60.0.0/16'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: '10.51.250.4'
        }
      }
    ]
  }
}

resource vnetAgent 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: 'vnet-sre-agent-hub'
  location: agentLocation
  properties: {
    addressSpace: { addressPrefixes: [ '10.42.0.0/16' ] }
    subnets: [
      {
        name: 'snet-sre-agent-sandbox'
        properties: {
          addressPrefix: '10.42.4.0/24'
          routeTable: { id: rtAgentSandbox.id }
          delegations: [
            {
              name: 'delegation-app-env'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
    ]
  }
}

resource vnetHub1 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: 'vnet-fleet-hub-01'
  location: aksLocation
  properties: {
    addressSpace: { addressPrefixes: [ '10.51.0.0/16' ] }
    subnets: [
      {
        name: 'snet-firewall'
        properties: { addressPrefix: '10.51.250.0/24' }
      }
    ]
  }
}

resource vnetHub2 'Microsoft.Network/virtualNetworks@2024-01-01' = {
  name: 'vnet-fleet-aks-hub'
  location: aksLocation
  properties: {
    addressSpace: { addressPrefixes: [ '10.52.0.0/16' ] }
    subnets: [
      {
        name: 'snet-firewall'
        properties: { addressPrefix: '10.52.250.0/24' }
      }
      {
        name: 'snet-aks-01'
        properties: {
          addressPrefix: '10.52.11.0/24'
          privateEndpointNetworkPolicies: 'Enabled'
        }
      }
    ]
  }
}

resource agent 'Microsoft.App/agents@2025-05-01-preview' = {
  name: agentName
  location: agentLocation
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    actionConfiguration: {
      accessLevel: 'Low'
      mode: 'review'
      identity: uami.id
    }
    knowledgeGraphConfiguration: {
      identity: uami.id
      managedResources: [ resourceGroup().id ]
    }
    logConfiguration: {
      applicationInsightsConfiguration: {
        appId: appi.properties.AppId
        applicationInsightsResourceId: appi.id
      }
    }
    vnetConfiguration: {
      subnetResourceId: '${vnetAgent.id}/subnets/snet-sre-agent-sandbox'
    }
    sandboxConfiguration: {
      egress: {
        mode: 'AzureVNet'
        allowHttpMcpServerNetworkAccess: true
        allowedRegistries: [ 'pypi' ]
        allowedCodeRepositories: [ 'Github' ]
        allowedHosts: [
          'management.azure.com'
          'learn.microsoft.com'
          'api.loganalytics.io'
        ]
      }
    }
  }
}

var sreAdminRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'e79298df-d852-4c6d-84f9-5d13249d1e55')

resource adminRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(agent.id, adminPrincipalId, sreAdminRoleId)
  scope: agent
  properties: {
    principalId: adminPrincipalId
    principalType: 'User'
    roleDefinitionId: sreAdminRoleId
  }
}

output agentId string = agent.id
output agentName string = agent.name
output agentUamiPrincipalId string = uami.properties.principalId
