targetScope = 'resourceGroup'

param apiManagementServiceName string
param apiPathPrefix string = 'ai'
param entraTenantId string
param entraAudience string
param requiredScope string = 'ai.invoke'
param rateLimitCalls int = 60
param rateLimitRenewalPeriod int = 60
param maxInlinePiiCharacters int = 4096
param piiLanguage string = 'ko'
param languageEndpoint string
@secure()
param geminiApiKeySecretIdentifier string
@secure()
param anthropicApiKeySecretIdentifier string
@secure()
param bedrockAccessKeySecretIdentifier string
@secure()
param bedrockSecretKeySecretIdentifier string
@secure()
param languageApiKeySecretIdentifier string
param bedrockRegion string
param vertexBrokerUrl string
param mcpAuthorizationServerOpenIdConfigurationUrl string
param mcpAuthorizationServerIssuer string
param mcpResourceAudience string
param mcpResourceMetadataUrl string
param mcpBackendUrl string

var forbiddenVertexPublicHost = 'aiplatform.${'googleapis.com'}'
var validatedVertexBrokerUrl = !contains(toLower(vertexBrokerUrl), forbiddenVertexPublicHost)
  ? vertexBrokerUrl
  : fail('vertexBrokerUrl must target the private broker, not the public Vertex AI host.')

resource apim 'Microsoft.ApiManagement/service@2024-05-01' existing = {
  name: apiManagementServiceName
}

resource geminiApiKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-gemini-api-key'
  properties: {
    displayName: 'ai-hub-gemini-api-key'
    secret: true
    keyVault: {
      secretIdentifier: geminiApiKeySecretIdentifier
    }
  }
}

resource anthropicApiKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-anthropic-api-key'
  properties: {
    displayName: 'ai-hub-anthropic-api-key'
    secret: true
    keyVault: {
      secretIdentifier: anthropicApiKeySecretIdentifier
    }
  }
}

resource bedrockAccessKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-bedrock-access-key'
  properties: {
    displayName: 'ai-hub-bedrock-access-key'
    secret: true
    keyVault: {
      secretIdentifier: bedrockAccessKeySecretIdentifier
    }
  }
}

resource bedrockSecretKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-bedrock-secret-key'
  properties: {
    displayName: 'ai-hub-bedrock-secret-key'
    secret: true
    keyVault: {
      secretIdentifier: bedrockSecretKeySecretIdentifier
    }
  }
}

resource languageApiKeyNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-language-api-key'
  properties: {
    displayName: 'ai-hub-language-api-key'
    secret: true
    keyVault: {
      secretIdentifier: languageApiKeySecretIdentifier
    }
  }
}

resource entraTenantIdNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-entra-tenant-id'
  properties: {
    displayName: 'ai-hub-entra-tenant-id'
    value: entraTenantId
  }
}

resource entraAudienceNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-entra-audience'
  properties: {
    displayName: 'ai-hub-entra-audience'
    value: entraAudience
  }
}

resource requiredScopeNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-required-scope'
  properties: {
    displayName: 'ai-hub-required-scope'
    value: requiredScope
  }
}

resource rateLimitCallsNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-rate-limit-calls'
  properties: {
    displayName: 'ai-hub-rate-limit-calls'
    value: string(rateLimitCalls)
  }
}

resource rateLimitRenewalPeriodNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-rate-limit-renewal-period'
  properties: {
    displayName: 'ai-hub-rate-limit-renewal-period'
    value: string(rateLimitRenewalPeriod)
  }
}

resource maxInlinePiiCharactersNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-max-inline-pii-characters'
  properties: {
    displayName: 'ai-hub-max-inline-pii-characters'
    value: string(maxInlinePiiCharacters)
  }
}

resource piiLanguageNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-pii-language'
  properties: {
    displayName: 'ai-hub-pii-language'
    value: piiLanguage
  }
}

resource languageEndpointNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-language-endpoint'
  properties: {
    displayName: 'ai-hub-language-endpoint'
    value: languageEndpoint
  }
}

resource bedrockRegionNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-bedrock-region'
  properties: {
    displayName: 'ai-hub-bedrock-region'
    value: bedrockRegion
  }
}

resource mcpOpenIdConfigNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp-openid-config'
  properties: {
    displayName: 'ai-hub-mcp-openid-config'
    value: mcpAuthorizationServerOpenIdConfigurationUrl
  }
}

resource mcpAuthorizationServerIssuerNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp-authorization-server-issuer'
  properties: {
    displayName: 'ai-hub-mcp-authorization-server-issuer'
    value: mcpAuthorizationServerIssuer
  }
}

resource mcpResourceAudienceNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp-resource-audience'
  properties: {
    displayName: 'ai-hub-mcp-resource-audience'
    value: mcpResourceAudience
  }
}

resource mcpResourceMetadataUrlNamedValue 'Microsoft.ApiManagement/service/namedValues@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp-resource-metadata-url'
  properties: {
    displayName: 'ai-hub-mcp-resource-metadata-url'
    value: mcpResourceMetadataUrl
  }
}

resource geminiBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-hub-gemini'
  properties: {
    protocol: 'http'
    url: 'https://generativelanguage.googleapis.com'
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource anthropicBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-hub-anthropic'
  properties: {
    protocol: 'http'
    url: 'https://api.anthropic.com'
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource bedrockBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-hub-bedrock'
  properties: {
    protocol: 'http'
    url: 'https://bedrock-runtime.${bedrockRegion}.amazonaws.com'
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource vertexBrokerBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-hub-vertex-broker'
  properties: {
    protocol: 'http'
    url: validatedVertexBrokerUrl
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource mcpBackend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp'
  properties: {
    protocol: 'http'
    url: mcpBackendUrl
    tls: {
      validateCertificateChain: true
      validateCertificateName: true
    }
  }
}

resource geminiApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-gemini'
  properties: {
    displayName: 'AI Hub Gemini'
    path: '${apiPathPrefix}/gemini'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../openapi/gemini.json')
  }
}

resource anthropicApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-anthropic'
  properties: {
    displayName: 'AI Hub Anthropic'
    path: '${apiPathPrefix}/anthropic'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../openapi/anthropic.json')
  }
}

resource bedrockApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-bedrock'
  properties: {
    displayName: 'AI Hub Bedrock'
    path: '${apiPathPrefix}/bedrock'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../openapi/bedrock.json')
  }
}

resource vertexApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-vertex'
  properties: {
    displayName: 'AI Hub Vertex'
    path: '${apiPathPrefix}/vertex'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../openapi/vertex.json')
  }
}

resource mcpApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp'
  properties: {
    displayName: 'AI Hub MCP'
    path: '${apiPathPrefix}/mcp'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: loadTextContent('../openapi/mcp.json')
  }
}

resource mcpMetadataApi 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'ai-hub-mcp-metadata'
  properties: {
    displayName: 'AI Hub MCP Metadata'
    path: '.well-known'
    protocols: [
      'https'
    ]
    subscriptionRequired: false
    format: 'openapi+json'
    value: replace(
      loadTextContent('../openapi/mcp-metadata.json'),
      '__API_PATH_PREFIX__',
      apiPathPrefix
    )
  }
}

resource clientAuthPolicyFragment 'Microsoft.ApiManagement/service/policyFragments@2024-05-01' = {
  parent: apim
  name: 'ai-hub-client-auth'
  dependsOn: [
    entraTenantIdNamedValue
    entraAudienceNamedValue
    requiredScopeNamedValue
  ]
  properties: {
    description: 'AI Hub caller JWT validation fragment.'
    format: 'rawxml'
    value: loadTextContent('../policies/common-client-auth.xml')
  }
}

resource rateLimitPolicyFragment 'Microsoft.ApiManagement/service/policyFragments@2024-05-01' = {
  parent: apim
  name: 'ai-hub-rate-limit'
  dependsOn: [
    rateLimitCallsNamedValue
    rateLimitRenewalPeriodNamedValue
  ]
  properties: {
    description: 'AI Hub per-caller throttling fragment.'
    format: 'rawxml'
    value: loadTextContent('../policies/common-rate-limit.xml')
  }
}

resource piiInboundPolicyFragment 'Microsoft.ApiManagement/service/policyFragments@2024-05-01' = {
  parent: apim
  name: 'ai-hub-pii-inbound'
  dependsOn: [
    maxInlinePiiCharactersNamedValue
    piiLanguageNamedValue
    languageEndpointNamedValue
    languageApiKeyNamedValue
  ]
  properties: {
    description: 'AI Hub fail-closed inbound PII inspection fragment.'
    format: 'rawxml'
    value: loadTextContent('../policies/common-pii-inbound.xml')
  }
}

resource geminiApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: geminiApi
  name: 'policy'
  dependsOn: [
    clientAuthPolicyFragment
    rateLimitPolicyFragment
    piiInboundPolicyFragment
    geminiBackend
    geminiApiKeyNamedValue
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/gemini.xml')
  }
}

resource anthropicApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: anthropicApi
  name: 'policy'
  dependsOn: [
    clientAuthPolicyFragment
    rateLimitPolicyFragment
    piiInboundPolicyFragment
    anthropicBackend
    anthropicApiKeyNamedValue
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/anthropic.xml')
  }
}

resource bedrockApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: bedrockApi
  name: 'policy'
  dependsOn: [
    clientAuthPolicyFragment
    rateLimitPolicyFragment
    piiInboundPolicyFragment
    bedrockBackend
    bedrockAccessKeyNamedValue
    bedrockSecretKeyNamedValue
    bedrockRegionNamedValue
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/bedrock.xml')
  }
}

resource vertexApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: vertexApi
  name: 'policy'
  dependsOn: [
    clientAuthPolicyFragment
    rateLimitPolicyFragment
    piiInboundPolicyFragment
    vertexBrokerBackend
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/vertex.xml')
  }
}

resource mcpApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: mcpApi
  name: 'policy'
  dependsOn: [
    mcpBackend
    mcpOpenIdConfigNamedValue
    mcpAuthorizationServerIssuerNamedValue
    mcpResourceAudienceNamedValue
    mcpResourceMetadataUrlNamedValue
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/mcp-resource-server.xml')
  }
}

resource mcpMetadataApiPolicy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: mcpMetadataApi
  name: 'policy'
  dependsOn: [
    mcpOpenIdConfigNamedValue
    mcpAuthorizationServerIssuerNamedValue
    mcpResourceAudienceNamedValue
    mcpResourceMetadataUrlNamedValue
  ]
  properties: {
    format: 'rawxml'
    value: loadTextContent('../policies/mcp-metadata.xml')
  }
}
