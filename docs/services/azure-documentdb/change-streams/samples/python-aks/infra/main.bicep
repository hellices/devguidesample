// azd entry point. Creates the resource group, then deploys the cluster, AKS
// and ACR (cluster.bicep) and the ADLS Gen2 landing zone (lake.bicep) into it.
// The outputs become azd environment values that the README's kubectl steps use.

targetScope = 'subscription'

@minLength(1)
@maxLength(60)
@description('azd environment name. The resource group is rg-<environmentName>.')
param environmentName string

@description('Region for every resource.')
param location string

@description('DocumentDB administrator user name.')
param adminUserName string = 'csadmin'

@secure()
@description('DocumentDB administrator password, from the DOCDB_ADMIN_PASSWORD azd environment value.')
param adminPassword string

@description('AKS node count.')
param nodeCount int = 2

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: {
    'azd-env-name': environmentName
  }
}

module cluster 'cluster.bicep' = {
  name: 'cluster'
  scope: group
  params: {
    location: location
    adminUserName: adminUserName
    adminPassword: adminPassword
    nodeCount: nodeCount
  }
}

module lake 'lake.bicep' = {
  name: 'lake'
  scope: group
  params: {
    location: location
    oidcIssuerUrl: cluster.outputs.oidcIssuerUrl
  }
}

output AZURE_RESOURCE_GROUP string = group.name
output AZURE_AKS_CLUSTER_NAME string = cluster.outputs.aksName
output AZURE_CONTAINER_REGISTRY_NAME string = cluster.outputs.acrName
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = cluster.outputs.acrLoginServer
output DOCDB_CLUSTER_NAME string = cluster.outputs.clusterName
output DOCDB_ADMIN_USER string = adminUserName
output DOCDB_CONNECTION_STRING string = cluster.outputs.connectionString
output LAKE_URL string = lake.outputs.dfsEndpoint
output LAKE_CLIENT_ID string = lake.outputs.identityClientId
