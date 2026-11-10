param location string
@minLength(8)
param token string
param tags object
param kubernetesVersion string
param operatorEgressCidr string
@description('NSG that foundation attaches to the gateway subnet; also bound to the gateway NIC.')
param gatewayNsgId string
param gatewayAdminSshPublicKey string
param adminUsername string = 'azureuser'
param aksSubnetId string
param gatewaySubnetId string
param gatewayIdentityId string
param acrId string
param vnetName string
@description('Object ID of the operator running azd. Receives cluster-admin through Azure RBAC for Kubernetes.')
param deployerPrincipalId string = ''
@allowed([
  'User'
  'ServicePrincipal'
  'Group'
])
param deployerPrincipalType string = 'User'

var acrPullRoleDefinitionId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var networkContributorRoleDefinitionId = '4d97b98b-1d4f-4787-a291-c67834d212e7'
var aksRbacClusterAdminRoleDefinitionId = 'b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b'
var gatewayCloudInit = '''
#cloud-config
package_update: true
packages:
  - ca-certificates
  - curl
  - docker.io
  - docker-compose-v2
  - jq
runcmd:
  - [systemctl, enable, --now, docker]
  - [mkdir, -p, /opt/eventhubs-observability]
  - [chmod, '0755', /opt/eventhubs-observability]
  - [curl, -fsSL, https://aka.ms/InstallAzureCLIDeb, -o, /tmp/install-azure-cli.sh]
  - [bash, /tmp/install-azure-cli.sh]
  - [rm, -f, /tmp/install-azure-cli.sh]
'''

resource aks 'Microsoft.ContainerService/managedClusters@2026-06-01' = {
  name: 'aks-${token}'
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: 'Base'
    tier: 'Free'
  }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: 'aks-${token}'
    enableRBAC: true
    aadProfile: {
      enableAzureRBAC: true
      managed: true
    }
    agentPoolProfiles: [
      {
        name: 'system'
        count: 1
        enableAutoScaling: false
        maxPods: 250
        mode: 'System'
        osDiskSizeGB: 128
        osDiskType: 'Managed'
        osSKU: 'AzureLinux3'
        osType: 'Linux'
        type: 'VirtualMachineScaleSets'
        vmSize: 'Standard_D4as_v5'
        vnetSubnetID: aksSubnetId
      }
    ]
    apiServerAccessProfile: {
      authorizedIPRanges: [
        operatorEgressCidr
      ]
    }
    autoUpgradeProfile: {
      nodeOSUpgradeChannel: 'SecurityPatch'
      upgradeChannel: 'patch'
    }
    linuxProfile: {
      adminUsername: adminUsername
      ssh: {
        publicKeys: [
          {
            keyData: gatewayAdminSshPublicKey
          }
        ]
      }
    }
    networkProfile: {
      networkDataplane: 'cilium'
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkPolicy: 'cilium'
      podCidr: '10.244.0.0/16'
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
    }
    oidcIssuerProfile: { enabled: true }
    securityProfile: {
      workloadIdentity: { enabled: true }
    }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: last(split(acrId, '/'))
}

resource kubeletAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, acrPullRoleDefinitionId)
  scope: acr
  properties: {
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleDefinitionId)
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
}

resource aksSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: last(split(aksSubnetId, '/'))
}

// BYO subnet: the cluster identity must manage the internal load balancer frontend IP in this subnet.
resource aksSubnetNetworkContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aksSubnet.id, aks.id, networkContributorRoleDefinitionId)
  scope: aksSubnet
  properties: {
    principalId: aks.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributorRoleDefinitionId)
  }
}

resource deployerClusterAdmin 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  name: guid(aks.id, deployerPrincipalId, aksRbacClusterAdminRoleDefinitionId)
  scope: aks
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', aksRbacClusterAdminRoleDefinitionId)
  }
}

resource gatewayPublicIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-gateway-${token}'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAddressVersion: 'IPv4'
    publicIPAllocationMethod: 'Static'
  }
}

resource gatewayNic 'Microsoft.Network/networkInterfaces@2024-05-01' = {
  name: 'nic-gateway-${token}'
  location: location
  tags: tags
  properties: {
    enableAcceleratedNetworking: false
    networkSecurityGroup: {
      id: gatewayNsgId
    }
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          primary: true
          privateIPAddressVersion: 'IPv4'
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: gatewayPublicIp.id
          }
          subnet: {
            id: gatewaySubnetId
          }
        }
      }
    ]
  }
}

resource gatewayVm 'Microsoft.Compute/virtualMachines@2024-11-01' = {
  name: 'vm-gateway-${token}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${gatewayIdentityId}': {}
    }
  }
  properties: {
    hardwareProfile: {
      vmSize: 'Standard_D2as_v5'
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: gatewayNic.id
          properties: {
            deleteOption: 'Delete'
          }
        }
      ]
    }
    osProfile: {
      computerName: 'otel-gateway'
      adminUsername: adminUsername
      customData: base64(gatewayCloudInit)
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              keyData: gatewayAdminSshPublicKey
              path: '/home/${adminUsername}/.ssh/authorized_keys'
            }
          ]
        }
      }
    }
    storageProfile: {
      imageReference: {
        publisher: 'Canonical'
        offer: 'ubuntu-24_04-lts'
        sku: 'server'
        version: 'latest'
      }
      osDisk: {
        name: 'osdisk-gateway-${token}'
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 64
        managedDisk: {
          storageAccountType: 'Premium_LRS'
        }
      }
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: {
        secureBootEnabled: true
        vTpmEnabled: true
      }
    }
    diagnosticsProfile: {
      bootDiagnostics: {
        enabled: true
      }
    }
  }
}

output aksName string = aks.name
output aksOidcIssuer string = aks.properties.oidcIssuerProfile.issuerURL
output gatewayVmName string = gatewayVm.name
output gatewayPublicIp string = gatewayPublicIp.properties.ipAddress
output gatewayPrivateIp string = gatewayNic.properties.ipConfigurations[0].properties.privateIPAddress
