param serviceName string
param gatewayUrl string
param backendUrl string
param tenantId string
param apiClientId string
param allowedClientIds array
param scopeUri string

var clientsXml = join(map(allowedClientIds, client => '<application-id>${client}</application-id>'), '')
var globalTenant = replace(loadTextContent('policies/global.xml'), '__TENANT_ID__', tenantId)
var globalClients = replace(globalTenant, '__CLIENT_APPLICATIONS__', clientsXml)
var globalAudience = replace(globalClients, '__API_CLIENT_ID__', apiClientId)
var globalGateway = replace(globalAudience, '__GATEWAY_URL__', gatewayUrl)
var globalXml = replace(globalGateway, '__SCOPE__', scopeUri)
var metadataDefinitions = [
  { name: 'rest-tools', endpoint: 'rest-tools/mcp' }
  { name: 'learn', endpoint: 'learn/mcp' }
]

resource service 'Microsoft.ApiManagement/service@2025-09-01-preview' existing = {
  name: serviceName
}

resource authorization 'Microsoft.ApiManagement/service/policies@2025-09-01-preview' = {
  parent: service
  name: 'policy'
  properties: { format: 'rawxml', value: globalXml }
}

resource restApi 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: service
  name: 'lab-rest'
  properties: {
    type: 'http'
    displayName: 'Private lab inventory REST API'
    path: 'rest'
    protocols: ['https']
    serviceUrl: backendUrl
    subscriptionRequired: false
  }
  dependsOn: [authorization]
}

resource inventoryOperation 'Microsoft.ApiManagement/service/apis/operations@2025-09-01-preview' = {
  parent: restApi
  name: 'get-inventory'
  properties: {
    displayName: 'Get fictitious inventory'
    description: 'Invoke the private REST fixture and return a fresh invocation marker.'
    method: 'GET'
    urlTemplate: '/inventory'
    templateParameters: []
    responses: [{
      statusCode: 200
      description: 'A harmless inventory fixture from the real REST backend.'
      representations: [{ contentType: 'application/json' }]
    }]
  }
}

resource restOutbound 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: restApi
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('policies/remove-upstream-token.xml')
  }
}

resource nativeMcp 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: service
  name: 'rest-tools'
  properties: {
    type: 'mcp'
    displayName: 'REST operations as native MCP tools'
    path: 'rest-tools'
    protocols: ['https']
    subscriptionRequired: false
  }
  dependsOn: [authorization, restOutbound]
}

resource inventoryTool 'Microsoft.ApiManagement/service/apis/tools@2025-09-01-preview' = {
  parent: nativeMcp
  name: 'getInventory'
  properties: {
    displayName: 'getInventory'
    description: 'Read the fictitious inventory through the existing REST operation.'
    operationId: inventoryOperation.id
  }
}

resource learnBackend 'Microsoft.ApiManagement/service/backends@2025-09-01-preview' = {
  parent: service
  name: 'learn-backend'
  properties: {
    url: 'https://learn.microsoft.com/api'
    protocol: 'http'
    type: 'Single'
    tls: { validateCertificateChain: true, validateCertificateName: true }
  }
}

resource learnMcp 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: service
  name: 'learn-mcp'
  properties: {
    type: 'mcp'
    displayName: 'Microsoft Learn MCP proxy'
    path: 'learn'
    protocols: ['https']
    #disable-next-line BCP037 // The live API and official AI-Gateway sample require backendId; this pinned Bicep model omits it.
    backendId: learnBackend.name
    mcpProperties: {
      transportType: 'streamable'
      #disable-next-line BCP036 // The live API and official AI-Gateway sample use a keyed object, not the published array type.
      endpoints: {
        message: { uriTemplate: '/mcp' }
      }
    }
    subscriptionRequired: false
  }
  dependsOn: [authorization]
}

resource learnOutbound 'Microsoft.ApiManagement/service/apis/policies@2025-09-01-preview' = {
  parent: learnMcp
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: loadTextContent('policies/remove-upstream-token.xml')
  }
}

resource metadataApi 'Microsoft.ApiManagement/service/apis@2025-09-01-preview' = {
  parent: service
  name: 'mcp-metadata'
  properties: {
    type: 'http'
    displayName: 'OAuth protected resource metadata only'
    path: 'oauth-metadata'
    protocols: ['https']
    subscriptionRequired: false
  }
  dependsOn: [authorization]
}

resource metadataOperations 'Microsoft.ApiManagement/service/apis/operations@2025-09-01-preview' = [for definition in metadataDefinitions: {
  parent: metadataApi
  name: definition.name
  properties: {
    displayName: 'Metadata for ${definition.name}'
    method: 'GET'
    urlTemplate: '/${definition.endpoint}'
    templateParameters: []
    responses: [{ statusCode: 200, description: 'Public OAuth metadata, not tool data.' }]
  }
}]

resource metadataPolicies 'Microsoft.ApiManagement/service/apis/operations/policies@2025-09-01-preview' = [for (definition, index) in metadataDefinitions: {
  parent: metadataOperations[index]
  name: 'policy'
  properties: {
    format: 'rawxml'
    value: replace(loadTextContent('policies/metadata.xml'), '__METADATA_JSON__', string({
      resource: '${gatewayUrl}/${definition.endpoint}'
      authorization_servers: ['${az.environment().authentication.loginEndpoint}${tenantId}/v2.0']
      scopes_supported: [scopeUri]
      bearer_methods_supported: ['header']
    }))
  }
}]

output restUrl string = '${gatewayUrl}/rest/inventory'
output nativeMcpUrl string = '${gatewayUrl}/rest-tools/mcp'
output learnMcpUrl string = '${gatewayUrl}/learn/mcp'
output nativeToolOperationId string = inventoryTool.properties.operationId
