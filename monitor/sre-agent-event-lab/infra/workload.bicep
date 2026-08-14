@description('Azure region for workload resources.')
param location string

@description('Stable alphanumeric suffix used for globally unique names.')
param suffix string

@description('Container image to deploy.')
param containerImage string

@description('Whether to deploy the Container App.')
param deployContainerApp bool

@description('Port the deployed container image listens on. The public placeholder image serves port 80; the lab image serves 8000.')
param containerTargetPort int = 8000

@description('Whether to attach /healthz liveness and readiness probes. Disabled while the placeholder image runs, because it serves no /healthz.')
param enableHealthProbes bool = true

@description('Log Analytics workspace customer ID.')
param workspaceCustomerId string

@description('Log Analytics workspace shared key.')
@secure()
param workspaceSharedKey string

@description('Application Insights connection string.')
@secure()
param appInsightsConnectionString string

@description('Tags applied to workload resources.')
param tags object

var acrName = 'acrsrelab${suffix}'
var storageName = 'stsrelab${suffix}'
var appName = 'ca-sre-event-lab-vnet'
var telemetryServiceName = 'sre-event-lab-${suffix}'
var privateDnsZoneName = 'privatelink.blob.${az.environment().suffixes.storage}'
var acrPullRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)
var blobDataReaderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
)

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    dataEndpointEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
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
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
    }
    publicNetworkAccess: 'Disabled'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: false
    }
  }
}

resource documentsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'documents'
  properties: {
    publicAccess: 'None'
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-sre-event-lab-${suffix}'
  location: location
  tags: tags
}

resource virtualNetwork 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-sre-event-lab-${suffix}'
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

resource containerAppsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-container-apps'
  properties: {
    addressPrefix: '10.42.0.0/23'
    delegations: [
      {
        name: 'container-apps-delegation'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
  }
}

resource privateEndpointSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' = {
  parent: virtualNetwork
  name: 'snet-private-endpoints'
  properties: {
    addressPrefix: '10.42.2.0/24'
    privateEndpointNetworkPolicies: 'Disabled'
  }
}

resource blobPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: privateDnsZoneName
  location: 'global'
  tags: tags
}

resource blobPrivateDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobPrivateDnsZone
  name: 'link-sre-event-lab'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

resource blobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${storageName}-blob'
  location: location
  tags: tags
  properties: {
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: {
          groupIds: [
            'blob'
          ]
          privateLinkServiceId: storage.id
          requestMessage: 'Azure SRE Agent event lab Blob access'
        }
      }
    ]
    subnet: {
      id: privateEndpointSubnet.id
    }
  }
}

resource blobPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'blob'
        properties: {
          privateDnsZoneId: blobPrivateDnsZone.id
        }
      }
    ]
  }
  dependsOn: [
    blobPrivateDnsLink
  ]
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, workloadIdentity.id, acrPullRoleDefinitionId)
  scope: registry
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRoleDefinitionId
  }
}

resource blobReaderAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(documentsContainer.id, workloadIdentity.id, blobDataReaderRoleDefinitionId)
  scope: documentsContainer
  properties: {
    principalId: workloadIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: blobDataReaderRoleDefinitionId
  }
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-sre-event-lab-private-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspaceCustomerId
        sharedKey: workspaceSharedKey
      }
    }
    vnetConfiguration: {
      infrastructureSubnetId: containerAppsSubnet.id
      internal: false
    }
    zoneRedundant: false
  }
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = if (deployContainerApp) {
  name: appName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${workloadIdentity.id}': {}
    }
  }
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: containerTargetPort
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
        transport: 'auto'
      }
      maxInactiveRevisions: 10
      registries: [
        {
          identity: workloadIdentity.id
          server: registry.properties.loginServer
        }
      ]
      secrets: [
        {
          name: 'appinsights-connection-string'
          value: appInsightsConnectionString
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'sre-event-lab'
          image: containerImage
          env: [
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-connection-string'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: workloadIdentity.properties.clientId
            }
            {
              name: 'AZURE_STORAGE_ACCOUNT_URL'
              value: storage.properties.primaryEndpoints.blob
            }
            {
              name: 'FAILURE_MODE'
              value: 'none'
            }
            {
              name: 'ORDER_DELAY_MS'
              value: '0'
            }
            {
              name: 'OTEL_SERVICE_NAME'
              value: telemetryServiceName
            }
          ]
          probes: enableHealthProbes ? [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: containerTargetPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 10
              periodSeconds: 10
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: containerTargetPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 5
            }
          ] : []
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
        rules: [
          {
            name: 'http-scaling'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
  dependsOn: [
    acrPullAssignment
    blobReaderAssignment
    blobPrivateDnsZoneGroup
  ]
}

output acrName string = registry.name
output acrLoginServer string = registry.properties.loginServer
output containerAppName string = deployContainerApp ? containerApp.name : appName
output containerAppFqdn string = deployContainerApp ? containerApp!.properties.configuration.ingress.fqdn : ''
output workloadPrincipalId string = workloadIdentity.properties.principalId
output storageContainerScope string = documentsContainer.id
output blobRoleAssignmentName string = blobReaderAssignment.name
output telemetryServiceName string = telemetryServiceName
