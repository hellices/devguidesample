targetScope = 'resourceGroup'

// ─── Parameters ───────────────────────────────────────────────────────────────
@description('Prefix for all resource names (3-8 lowercase alphanum)')
param prefix string = 'dbsim'

@description('Azure region')
param location string = resourceGroup().location

@description('MySQL admin username')
param mysqlAdminUser string = 'simadmin'

@secure()
@description('MySQL admin password (min 8 chars, upper+lower+digit+special)')
param mysqlAdminPassword string

@description('Name of the simulation database')
param dbName string = 'simdb'

@description('AKS system node count')
param aksNodeCount int = 4

@description('AKS VM size')
param aksNodeSize string = 'Standard_D2s_v3'

// ─── VNet ─────────────────────────────────────────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: '${prefix}-vnet'
  location: location
  properties: {
    addressSpace: { addressPrefixes: ['10.0.0.0/8'] }
  }
}

// AKS subnet — no PE network policies needed here
resource aksSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = {
  parent: vnet
  name: 'aks-subnet'
  properties: {
    addressPrefix: '10.1.0.0/16'
  }
}

// MySQL subnet — delegated to Microsoft.DBforMySQL/flexibleServers (VNet Integration)
resource mysqlSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-11-01' = {
  parent: vnet
  name: 'mysql-subnet'
  properties: {
    addressPrefix: '10.2.0.0/24'
    delegations: [
      {
        name: 'mysql-delegation'
        properties: { serviceName: 'Microsoft.DBforMySQL/flexibleServers' }
      }
    ]
  }
  dependsOn: [aksSubnet] // Bicep deploys subnets sequentially
}

// ─── ACR ──────────────────────────────────────────────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: '${prefix}acr${uniqueString(resourceGroup().id)}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: true }
}

// ─── AKS ──────────────────────────────────────────────────────────────────────
resource aks 'Microsoft.ContainerService/managedClusters@2024-02-01' = {
  name: '${prefix}-aks'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    dnsPrefix: '${prefix}-aks'
    agentPoolProfiles: [
      {
        name: 'system'
        count: aksNodeCount
        vmSize: aksNodeSize
        vnetSubnetID: aksSubnet.id
        mode: 'System'
        osType: 'Linux'
        type: 'VirtualMachineScaleSets'
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      serviceCidr: '10.200.0.0/16'
      dnsServiceIP: '10.200.0.10'
    }
  }
}

// ─── MySQL Flexible Server: old-db (Blue) ────────────────────────────────────
// new-db(Green) 는 02b-setup-replication.ps1 에서 standalone v8.4 로 생성 후
// SQL binlog replication 설정. VNet Integration 방식 (delegatedSubnet + privateDnsZone).
resource mysqlOld 'Microsoft.DBforMySQL/flexibleServers@2023-06-30' = {
  name: '${prefix}-old-db'
  location: location
  sku: {
    name: 'Standard_D4ds_v4'
    tier: 'GeneralPurpose'
  }
  properties: {
    administratorLogin: mysqlAdminUser
    administratorLoginPassword: mysqlAdminPassword
    network: {
      delegatedSubnetResourceId: mysqlSubnet.id
      privateDnsZoneResourceId: privateDnsZone.id
    }
    storage: {
      storageSizeGB: 20
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 1
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: { mode: 'Disabled' }
    version: '8.0.21'
  }
  dependsOn: [privateDnsZone, privateDnsZoneLink]
}

// ─── Private DNS Zone: {prefix}.mysql.database.azure.com ───────────────────
// VNet Integration 방식: MySQL 서버 생성 시 privateDnsZoneResourceId 로 이 zone 을 지정하면
// Azure 가 자동으로 {server-name} A record 를 등록 → {server-name}.{prefix}.mysql.database.azure.com
// VNet 내에서 VNet IP 로 해석. (PE/privatelink 불필요)
// ※ Azure 는 'mysql.database.azure.com' 단독은 허용하지 않음 — prefix 필수
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: '${prefix}.mysql.database.azure.com'
  location: 'global'
}

resource privateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: '${prefix}-vnet-link'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

// ─── Custom DNS Zone: db.{prefix}.internal ────────────────────────────────────
// 앱은 이 zone 의 CNAME record 를 통해 DB 에 접속.
// Cutover 시 CNAME 값만 교체 (old FQDN → new FQDN). PE IP 관리 불필요.
resource customDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'db.${prefix}.internal'
  location: 'global'
}

resource customDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: customDnsZone
  name: '${prefix}-custom-vnet-link'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnet.id }
    registrationEnabled: false
  }
}

// CNAME: primary → {prefix}-old-db.{prefix}.mysql.database.azure.com (TTL=5s)
// Cutover 시 05-cutover.ps1 이 이 값을 old FQDN → new FQDN 으로 교체
resource cnamePrimary 'Microsoft.Network/privateDnsZones/CNAME@2020-06-01' = {
  parent: customDnsZone
  name: 'primary'
  properties: {
    ttl: 5
    cnameRecord: { cname: '${mysqlOld.name}.${prefix}.mysql.database.azure.com' }
  }
}

// ─── Outputs (setup 스크립트에서 사용) ────────────────────────────────────────
output aksName string = aks.name
output acrLoginServer string = acr.properties.loginServer
output acrName string = acr.name
output mysqlOldName string = mysqlOld.name
output mysqlOldFqdn string = '${mysqlOld.name}.${prefix}.mysql.database.azure.com'
// mysqlNewName / mysqlNewFqdn: 02b-setup-replication.ps1 에서 sim-env.json 에 추가
// (peOldName 제거 — VNet Integration 은 PE 불필요)
output privateDnsZoneName string = privateDnsZone.name  // '{prefix}.mysql.database.azure.com'
output customDnsZone string = customDnsZone.name
output appFqdn string = 'primary.db.${prefix}.internal'
output dbName string = dbName
output vnetId string = vnet.id
