// Lab resources: a SQL Server VM reachable only on a private IP, an Azure SRE
// Agent integrated with the same VNet (Azure VNet egress mode), a Key Vault
// reachable only through a private endpoint that holds the monitoring login,
// and an Azure Monitor workspace with Azure Managed Grafana for SQL Server metrics.
param location string
param prefix string
param vmSize string
param adminUsername string
@secure()
param adminPassword string
param deployerObjectId string
param tags object

var suffix = take(uniqueString(resourceGroup().id), 6)
var vmName = '${prefix}-sqlvm'
var agentName = '${prefix}-agent-${suffix}'
var keyVaultName = 'kv-${prefix}-${suffix}'
var monitorWorkspaceName = 'amw-${prefix}-${suffix}'
var grafanaName = 'amg-${prefix}-${suffix}'

var addressSpace = '10.42.0.0/16'
var sqlSubnetPrefix = '10.42.1.0/24'
var agentSubnetPrefix = '10.42.2.0/27'
var endpointSubnetPrefix = '10.42.3.0/27'
var sqlPrivateIp = '10.42.1.4'
var sqlPort = 1433

var roles = {
  reader: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
  monitoringReader: '43d0d8ad-25c7-4714-9337-8ba259a9fe05'
  logAnalyticsReader: '73c42c96-874c-492b-b04d-ab87d138a893'
  sreAgentAdministrator: 'e79298df-d852-4c6d-84f9-5d13249d1e55'
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  monitoringDataReader: 'b0d8363b-8ddd-447d-831f-62ca05bff136'
  grafanaAdmin: '22926164-76b3-42b3-bc55-97df8dab3e41'
}

// ── Network ──
// snet-sql:      SQL Server VM. Only the agent subnet may reach TCP 1433.
// snet-agent:    delegated to Microsoft.App/environments for SRE Agent VNet integration.
// snet-endpoint: Key Vault private endpoint.

resource sqlNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${prefix}-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'allow-sql-from-sre-agent'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: agentSubnetPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: sqlSubnetPrefix
          destinationPortRange: string(sqlPort)
        }
      }
      {
        name: 'deny-sql-from-other-sources'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: sqlSubnetPrefix
          destinationPortRange: string(sqlPort)
        }
      }
    ]
  }
}

resource agentNsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${prefix}-agent-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: []
  }
}

resource natIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: '${prefix}-nat-pip'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource nat 'Microsoft.Network/natGateways@2024-05-01' = {
  name: '${prefix}-nat'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIpAddresses: [ { id: natIp.id } ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${prefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [ addressSpace ] }
    subnets: [
      {
        name: 'snet-sql'
        properties: {
          addressPrefix: sqlSubnetPrefix
          networkSecurityGroup: { id: sqlNsg.id }
          natGateway: { id: nat.id }
          defaultOutboundAccess: false
        }
      }
      {
        name: 'snet-agent'
        properties: {
          addressPrefix: agentSubnetPrefix
          networkSecurityGroup: { id: agentNsg.id }
          // Agent calls to public Azure endpoints (ARM, Log Analytics) leave through the NAT Gateway.
          natGateway: { id: nat.id }
          defaultOutboundAccess: false
          delegations: [
            {
              name: 'sre-agent'
              properties: { serviceName: 'Microsoft.App/environments' }
            }
          ]
        }
      }
      {
        name: 'snet-endpoint'
        properties: {
          addressPrefix: endpointSubnetPrefix
          defaultOutboundAccess: false
        }
      }
    ]
  }
}

var sqlSubnetId = vnet.properties.subnets[0].id
var agentSubnetId = vnet.properties.subnets[1].id
var endpointSubnetId = vnet.properties.subnets[2].id

resource nic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: '${vmName}-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: { id: sqlSubnetId }
          privateIPAllocationMethod: 'Static'
          privateIPAddress: sqlPrivateIp
        }
      }
    ]
  }
}

// ── SQL Server 2022 Developer on Windows Server 2022 ──

// Prometheus on the VM uses this identity to remote-write metrics.
resource vmMetricsIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${vmName}-metrics-id'
  location: location
  tags: tags
}

resource vm 'Microsoft.Compute/virtualMachines@2024-07-01' = {
  name: vmName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${vmMetricsIdentity.id}': {} }
  }
  properties: {
    hardwareProfile: { vmSize: vmSize }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'MicrosoftSQLServer'
        offer: 'sql2022-ws2022'
        sku: 'sqldev-gen2'
        version: 'latest'
      }
      osDisk: {
        name: '${vmName}-osdisk'
        createOption: 'FromImage'
        managedDisk: { storageAccountType: 'Premium_LRS' }
        deleteOption: 'Delete'
      }
    }
    osProfile: {
      computerName: take(replace(vmName, '-', ''), 15)
      adminUsername: adminUsername
      adminPassword: adminPassword
      windowsConfiguration: {
        enableAutomaticUpdates: true
        provisionVMAgent: true
        patchSettings: { patchMode: 'AutomaticByOS' }
      }
    }
    networkProfile: {
      networkInterfaces: [ { id: nic.id, properties: { deleteOption: 'Delete' } } ]
    }
    diagnosticsProfile: {
      bootDiagnostics: { enabled: true }
    }
  }
}

// PRIVATE connectivity: SQL Server listens on TCP 1433 for the VNet, and the
// SQL IaaS Agent opens the Windows Firewall port. No public IP exists.
resource sqlVm 'Microsoft.SqlVirtualMachine/sqlVirtualMachines@2023-10-01' = {
  name: vm.name
  location: location
  tags: tags
  properties: {
    virtualMachineResourceId: vm.id
    sqlServerLicenseType: 'PAYG'
    sqlImageSku: 'Developer'
    serverConfigurationsManagementSettings: {
      sqlConnectivityUpdateSettings: {
        connectivityType: 'PRIVATE'
        port: sqlPort
      }
    }
  }
}

// ── Key Vault behind a private endpoint ──

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      bypass: 'None'
      defaultAction: 'Deny'
    }
  }
}

resource kvDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

resource kvDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: kvDnsZone
  name: '${prefix}-vnet-link'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

resource kvEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: '${keyVaultName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: endpointSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'vault'
        properties: {
          privateLinkServiceId: kv.id
          groupIds: [ 'vault' ]
        }
      }
    ]
  }
}

resource kvEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: kvEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vault'
        properties: { privateDnsZoneId: kvDnsZone.id }
      }
    ]
  }
}

// ── Agent observability ──

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-${prefix}-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-${prefix}-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    Request_Source: 'SreAgent'
    WorkspaceResourceId: law.id
  }
}

// ── Metrics: Azure Monitor workspace (managed Prometheus) and Managed Grafana ──

resource monitorWorkspace 'Microsoft.Monitor/accounts@2023-04-03' = {
  name: monitorWorkspaceName
  location: location
  tags: tags
}

resource grafana 'Microsoft.Dashboard/grafana@2024-10-01' = {
  name: grafanaName
  location: location
  tags: tags
  sku: { name: 'Standard' }
  identity: { type: 'SystemAssigned' }
  properties: {
    publicNetworkAccess: 'Enabled'
    apiKey: 'Disabled'
    zoneRedundancy: 'Disabled'
    // Creates the Prometheus data source for the workspace.
    grafanaIntegrations: {
      azureMonitorWorkspaceIntegrations: [
        { azureMonitorWorkspaceResourceId: monitorWorkspace.id }
      ]
    }
  }
}

resource grafanaReadsWorkspace 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(monitorWorkspace.id, grafanaName, roles.monitoringDataReader)
  scope: monitorWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringDataReader)
    principalId: grafana.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// The deployer imports dashboards and verifies the metrics with PromQL.
resource deployerGrafanaAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(grafana.id, deployerObjectId, roles.grafanaAdmin)
  scope: grafana
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.grafanaAdmin)
    principalId: deployerObjectId
  }
}

resource deployerReadsWorkspace 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(monitorWorkspace.id, deployerObjectId, roles.monitoringDataReader)
  scope: monitorWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringDataReader)
    principalId: deployerObjectId
  }
}

// ── Azure SRE Agent identity and permissions ──

resource agentIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: '${agentName}-id'
  location: location
  tags: tags
}

var rgReadRoles = [ roles.reader, roles.monitoringReader, roles.logAnalyticsReader ]

resource agentRgRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in rgReadRoles: {
  name: guid(resourceGroup().id, agentIdentity.id, roleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    principalId: agentIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource agentKvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, agentIdentity.id, roles.keyVaultSecretsUser)
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.keyVaultSecretsUser)
    principalId: agentIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// The agent's SqlServerMetricsQuery tool runs PromQL against the workspace.
resource agentReadsWorkspace 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(monitorWorkspace.id, agentIdentity.id, roles.monitoringDataReader)
  scope: monitorWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.monitoringDataReader)
    principalId: agentIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

#disable-next-line BCP081
resource agent 'Microsoft.App/agents@2025-05-01-preview' = {
  name: agentName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: { '${agentIdentity.id}': {} }
  }
  properties: {
    knowledgeGraphConfiguration: {
      identity: agentIdentity.id
      managedResources: [ resourceGroup().id ]
    }
    actionConfiguration: {
      accessLevel: 'Low'
      identity: agentIdentity.id
      mode: 'Review'
    }
    logConfiguration: {
      applicationInsightsConfiguration: {
        appId: appInsights.properties.AppId
        connectionString: appInsights.properties.ConnectionString
        applicationInsightsResourceId: appInsights.id
      }
    }
    upgradeChannel: 'Stable'
    monthlyAgentUnitLimit: 2000
    defaultModel: {
      provider: 'MicrosoftFoundry'
      name: 'Automatic'
    }
    experimentalSettings: {
      EnableWorkspaceTools: true
      EnablePythonTools: true
    }
    // Azure VNet egress: tool traffic leaves from snet-agent and resolves names
    // with the VNet's private DNS zones. Only PyPI uses the managed path.
    // The SQL driver is preinstalled in the sandbox image because the tool's
    // runtime `dependencies` were not installed in Azure VNet mode (observed).
    vnetConfiguration: {
      subnetResourceId: agentSubnetId
    }
    sandboxConfiguration: {
      egress: {
        mode: 'AzureVNet'
        allowedHosts: []
        allowedRegistries: [ 'pypi' ]
        allowedCodeRepositories: []
        allowHttpMcpServerNetworkAccess: false
        vnetConfiguration: {
          usePrivateDnsResolution: true
        }
      }
      packages: [
        {
          name: 'pymssql'
          version: '2.4.5'
          packageManager: 'pip'
        }
      ]
    }
  }
  dependsOn: [ agentRgRoles, agentKvSecretsUser, kvDnsLink ]
}

resource agentSystemRgRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in rgReadRoles: {
  name: guid(resourceGroup().id, agentName, 'system', roleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    principalId: agent.identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource agentAdmins 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(agent.id, deployerObjectId, roles.sreAgentAdministrator)
  scope: agent
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sreAgentAdministrator)
    principalId: deployerObjectId
  }
}

// Same assignment as the official microsoft/sre-agent templates.
resource agentIdentityAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(agent.id, agentIdentity.id, roles.sreAgentAdministrator)
  scope: agent
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.sreAgentAdministrator)
    principalId: agentIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output vmName string = vm.name
output vmId string = vm.id
output sqlHost string = sqlPrivateIp
output sqlPort int = sqlPort
output keyVaultName string = kv.name
output keyVaultId string = kv.id
output agentName string = agent.name
output agentId string = agent.id
output agentIdentityClientId string = agentIdentity.properties.clientId
output agentIdentityPrincipalId string = agentIdentity.properties.principalId
output vmMetricsClientId string = vmMetricsIdentity.properties.clientId
output vmMetricsPrincipalId string = vmMetricsIdentity.properties.principalId
output monitorWorkspaceId string = monitorWorkspace.id
output prometheusQueryEndpoint string = monitorWorkspace.properties.metrics.prometheusQueryEndpoint
output grafanaName string = grafana.name
output grafanaEndpoint string = grafana.properties.endpoint
