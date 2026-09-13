param location string
param suffix string
param environmentName string
param environmentDomain string
param environmentStaticIp string
param vnetId string
param appIdentityId string
param appIdentityClientId string
param registryHost string
param pythonImage string
param tenantId string
param customApiClientId string
param azureApiClientId string
param allowedClientIds string
@minLength(1)
param nativeAllowedClientIds array

@secure()
param customApiClientSecret string

var pythonName = 'ca-mcp-python-${suffix}'
var azureName = 'ca-mcp-azure-${suffix}'
var tags = {
  purpose: 'mcp-entra-walkthrough'
  environment: 'lab'
  labId: suffix
  'azd-env-name': suffix
}

resource environment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: environmentName
}

module dns './private-dns.bicep' = {
  name: 'container-apps-dns'
  params: {
    zoneName: environmentDomain
    address: environmentStaticIp
    recordName: '*'
    vnetId: vnetId
    tags: tags
  }
}

module pythonApp './python-app.bicep' = {
  name: 'python-mcp'
  params: {
    location: location
    suffix: suffix
    environmentId: environment.id
    environmentDomain: environmentDomain
    appIdentityId: appIdentityId
    registryHost: registryHost
    pythonImage: pythonImage
    tenantId: tenantId
    customApiClientId: customApiClientId
    customApiClientSecret: customApiClientSecret
    allowedClientIds: allowedClientIds
  }
}

resource azureApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: azureName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        allowInsecure: false
        targetPort: 8080
        transport: 'http'
      }
    }
    template: {
      containers: [{
        name: 'azure-mcp'
        image: 'mcr.microsoft.com/azure-sdk/azure-mcp@sha256:2285f62dc1720ebf5da90498828b27e73d8fae6fd6fb89cab8cf67e3646fce3a'
        args: [
          '--transport'
          'http'
          '--outgoing-auth-strategy'
          'UseOnBehalfOf'
          '--mode'
          'all'
          '--read-only'
          '--namespace'
          'group'
        ]
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'ASPNETCORE_ENVIRONMENT', value: 'Production' }
          { name: 'ASPNETCORE_URLS', value: 'http://+:8080' }
          { name: 'AZURE_MCP_COLLECT_TELEMETRY', value: 'false' }
          { name: 'AzureAd__Instance', value: az.environment().authentication.loginEndpoint }
          { name: 'AzureAd__TenantId', value: tenantId }
          { name: 'AzureAd__ClientId', value: azureApiClientId }
          { name: 'AzureAd__ClientCredentials__0__SourceType', value: 'SignedAssertionFromManagedIdentity' }
          { name: 'AzureAd__ClientCredentials__0__ManagedIdentityClientId', value: appIdentityClientId }
          { name: 'AzureAd__ClientCredentials__0__TokenExchangeUrl', value: 'api://AzureADTokenExchange' }
          // TLS terminates at the private ACA ingress; never expose port 8080 directly.
          { name: 'AZURE_MCP_DANGEROUSLY_DISABLE_HTTPS_REDIRECTION', value: 'true' }
          { name: 'AZURE_MCP_DANGEROUSLY_ENABLE_FORWARDED_HEADERS', value: 'true' }
        ]
        probes: [{
          type: 'Readiness'
          httpGet: { path: '/health', port: 8080, scheme: 'HTTP' }
          initialDelaySeconds: 5
          periodSeconds: 10
        }]
      }]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

module nativeAuth './native-auth.bicep' = {
  name: 'native-mcp-client-authorization'
  params: {
    appName: azureApp.name
    tenantId: tenantId
    apiClientId: azureApiClientId
    allowedClientIds: nativeAllowedClientIds
  }
}

output pythonUrl string = 'https://${pythonName}.${environmentDomain}'
output azureUrl string = 'https://${azureName}.${environmentDomain}'
output pythonAppName string = pythonApp.outputs.pythonAppName
output azureAppName string = azureApp.name
