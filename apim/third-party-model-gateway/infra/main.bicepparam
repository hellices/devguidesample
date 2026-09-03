using './main.bicep'

param apiManagementServiceName = '<existing-apim-name>'
param apiPathPrefix = 'ai'
param entraTenantId = '<entra-tenant-id>'
param entraAudience = 'api://<ai-hub-api-app-id>'
param requiredScope = 'ai.invoke'
param rateLimitCalls = 60
param rateLimitRenewalPeriod = 60
param maxInlinePiiCharacters = 4096
param piiLanguage = 'ko'
param languageEndpoint = 'https://<language-resource>.cognitiveservices.azure.com'
param bedrockRegion = 'us-east-1'
param vertexBrokerUrl = 'https://<private-vertex-broker-host>'
param mcpAuthorizationServerOpenIdConfigurationUrl = 'https://<mcp-authorization-server>/.well-known/openid-configuration'
param mcpAuthorizationServerIssuer = 'https://<mcp-authorization-server>'
param mcpResourceAudience = 'https://<gateway-host>/ai/mcp'
param mcpResourceMetadataUrl = 'https://<gateway-host>/.well-known/oauth-protected-resource/ai/mcp'
param mcpBackendUrl = 'https://<private-mcp-server-host>'
