targetScope = 'subscription'

@minLength(6)
@maxLength(10)
param environmentName string
param location string
param operatorObjectId string
param expiresOn string
param customApiClientId string
@secure()
param customApiClientSecret string
param azureApiClientId string
param publicClientId string
param pythonImage string = ''

var cliClientId = '04b07795-8ddb-461a-bbee-02f9e1bf7b46'
var vsCodeClientId = 'aebc6443-996d-45c2-90f0-388ff96faa56'
var clients = [cliClientId, publicClientId]

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: {
    'azd-env-name': environmentName
    purpose: 'mcp-entra-walkthrough'
    expiresOn: expiresOn
  }
}

module foundation './foundation.bicep' = {
  name: 'foundation'
  scope: group
  params: {
    location: location
    suffix: environmentName
    operatorObjectId: operatorObjectId
    expiresOn: expiresOn
  }
}

module apps './apps.bicep' = {
  name: 'apps'
  scope: group
  params: {
    location: location
    suffix: environmentName
    environmentName: foundation.outputs.environmentName
    environmentDomain: foundation.outputs.environmentDomain
    environmentStaticIp: foundation.outputs.environmentStaticIp
    vnetId: foundation.outputs.vnetId
    appIdentityId: foundation.outputs.appIdentityId
    appIdentityClientId: foundation.outputs.appIdentityClientId
    registryHost: foundation.outputs.registryHost
    pythonImage: pythonImage
    tenantId: tenant().tenantId
    customApiClientId: customApiClientId
    customApiClientSecret: customApiClientSecret
    azureApiClientId: azureApiClientId
    allowedClientIds: join(clients, ',')
    nativeAllowedClientIds: concat(clients, [vsCodeClientId])
  }
}

module apim './apim.bicep' = {
  name: 'apim-apis'
  scope: group
  params: {
    serviceName: foundation.outputs.apimName
    gatewayUrl: foundation.outputs.apimGateway
    backendUrl: apps.outputs.pythonUrl
    tenantId: tenant().tenantId
    apiClientId: customApiClientId
    allowedClientIds: clients
    scopeUri: 'api://${customApiClientId}/Mcp.Access'
  }
}

output AZURE_RESOURCE_GROUP string = group.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = foundation.outputs.registryHost
output AZURE_CONTAINER_REGISTRY_NAME string = foundation.outputs.registryName
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = foundation.outputs.environmentId
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = foundation.outputs.environmentName
output MCP_ENVIRONMENT_DOMAIN string = foundation.outputs.environmentDomain
output MCP_ALLOWED_CLIENT_IDS string = join(clients, ',')
output AZURE_TENANT_ID string = tenant().tenantId
output MCP_APP_IDENTITY_OBJECT_ID string = foundation.outputs.appIdentityPrincipalId
output MCP_APP_IDENTITY_CLIENT_ID string = foundation.outputs.appIdentityClientId
output MCP_APP_IDENTITY_ID string = foundation.outputs.appIdentityId
output MCP_PYTHON_APP_NAME string = apps.outputs.pythonAppName
output MCP_AZURE_APP_NAME string = apps.outputs.azureAppName
output MCP_PYTHON_URL string = '${apps.outputs.pythonUrl}/mcp'
output MCP_AZURE_URL string = '${apps.outputs.azureUrl}/'
output MCP_APIM_NAME string = foundation.outputs.apimName
output MCP_APIM_REST_URL string = apim.outputs.nativeMcpUrl
output MCP_APIM_LEARN_URL string = apim.outputs.learnMcpUrl
output MCP_REST_URL string = apim.outputs.restUrl
output MCP_AKS_NAME string = foundation.outputs.aksName
