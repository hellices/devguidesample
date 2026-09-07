targetScope = 'resourceGroup'

param location string = resourceGroup().location
param adminUsername string = 'labadmin'
param sshPublicKey string
param natVmSize string = 'Standard_B2s'
param runnerVmSize string = 'Standard_D2s_v5'

var tags = {
  purpose: 'runner-private-ip-nat-experiment'
  lifecycle: 'temporary'
}
var natIp = '10.77.1.4'
var runnerSubnet = '10.77.2.0/24'

resource publicIp 'Microsoft.Network/publicIPAddresses@2026-03-01' = {
  name: 'pip-nat'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource natNsg 'Microsoft.Network/networkSecurityGroups@2026-03-01' = {
  name: 'nsg-nat'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowRunnerWeb'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: runnerSubnet
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRanges: [ '80', '443' ]
        }
      }
      {
        name: 'DenyOtherInbound'
        properties: {
          priority: 200
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource runnerNsg 'Microsoft.Network/networkSecurityGroups@2026-03-01' = {
  name: 'nsg-runner'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyNewInbound'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource runnerRoutes 'Microsoft.Network/routeTables@2026-03-01' = {
  name: 'rt-runner'
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: true
    routes: [
      {
        name: 'ForceNAT'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: natIp
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2026-03-01' = {
  name: 'vnet-runner-nat'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [ '10.77.0.0/16' ] }
    subnets: [
      {
        name: 'nat'
        properties: {
          addressPrefix: '10.77.1.0/24'
          defaultOutboundAccess: false
          networkSecurityGroup: { id: natNsg.id }
        }
      }
      {
        name: 'runner'
        properties: {
          addressPrefix: runnerSubnet
          defaultOutboundAccess: false
          networkSecurityGroup: { id: runnerNsg.id }
          routeTable: { id: runnerRoutes.id }
        }
      }
    ]
  }
}

resource natNic 'Microsoft.Network/networkInterfaces@2026-03-01' = {
  name: 'nic-nat'
  location: location
  tags: tags
  properties: {
    enableIPForwarding: true
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Static'
          privateIPAddress: natIp
          subnet: { id: '${vnet.id}/subnets/nat' }
          publicIPAddress: { id: publicIp.id }
        }
      }
    ]
  }
}

resource runnerNic 'Microsoft.Network/networkInterfaces@2026-03-01' = {
  name: 'nic-runner'
  location: location
  tags: tags
  properties: {
    enableIPForwarding: false
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          privateIPAllocationMethod: 'Static'
          privateIPAddress: '10.77.2.10'
          subnet: { id: '${vnet.id}/subnets/runner' }
        }
      }
    ]
  }
}

resource natVm 'Microsoft.Compute/virtualMachines@2026-04-01' = {
  name: 'vm-nat'
  location: location
  tags: tags
  properties: {
    hardwareProfile: { vmSize: natVmSize }
    osProfile: {
      computerName: 'vm-nat'
      adminUsername: adminUsername
      customData: base64(loadTextContent('nat-cloud-init.yml'))
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
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
        createOption: 'FromImage'
        deleteOption: 'Delete'
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: natNic.id, properties: { deleteOption: 'Delete' } }
      ]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
    }
    diagnosticsProfile: { bootDiagnostics: { enabled: true } }
  }
}

resource runnerVm 'Microsoft.Compute/virtualMachines@2026-04-01' = {
  name: 'vm-runner'
  location: location
  tags: tags
  properties: {
    hardwareProfile: { vmSize: runnerVmSize }
    osProfile: {
      computerName: 'vm-runner'
      adminUsername: adminUsername
      linuxConfiguration: {
        disablePasswordAuthentication: true
        provisionVMAgent: true
        ssh: {
          publicKeys: [
            {
              path: '/home/${adminUsername}/.ssh/authorized_keys'
              keyData: sshPublicKey
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
        createOption: 'FromImage'
        deleteOption: 'Delete'
        diskSizeGB: 64
        managedDisk: { storageAccountType: 'StandardSSD_LRS' }
      }
    }
    networkProfile: {
      networkInterfaces: [
        { id: runnerNic.id, properties: { deleteOption: 'Delete' } }
      ]
    }
    securityProfile: {
      securityType: 'TrustedLaunch'
      uefiSettings: { secureBootEnabled: true, vTpmEnabled: true }
    }
    diagnosticsProfile: { bootDiagnostics: { enabled: true } }
  }
}

output natPublicIp string = publicIp.properties.ipAddress
output natPrivateIp string = natIp
output runnerPrivateIp string = runnerNic.properties.ipConfigurations[0].properties.privateIPAddress
output natVmName string = natVm.name
output runnerVmName string = runnerVm.name
