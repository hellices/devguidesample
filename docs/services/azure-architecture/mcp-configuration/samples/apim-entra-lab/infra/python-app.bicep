param location string
param suffix string
param environmentId string
param environmentDomain string
param appIdentityId string
param registryHost string
param pythonImage string = ''
param tenantId string
param customApiClientId string
param allowedClientIds string
@secure()
param customApiClientSecret string

var appName = 'ca-mcp-python-${suffix}'
var placeholder = empty(pythonImage)

resource app 'Microsoft.App/containerApps@2025-01-01' = {
  name: appName
  location: location
  tags: {
    'azd-service-name': 'mcp'
    'azd-env-name': suffix
    purpose: 'mcp-entra-walkthrough'
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${appIdentityId}': {} }
  }
  properties: {
    managedEnvironmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: [{ name: 'entra-client-secret', value: customApiClientSecret }]
      registries: [{ server: registryHost, identity: appIdentityId }]
      ingress: {
        external: true
        allowInsecure: false
        targetPort: placeholder ? 80 : 8000
        transport: 'http'
      }
    }
    template: {
      containers: [{
        name: 'mcp'
        image: placeholder ? 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest' : pythonImage
        resources: { cpu: json('0.5'), memory: '1Gi' }
        env: [
          { name: 'ENTRA_TENANT_ID', value: tenantId }
          { name: 'ENTRA_API_CLIENT_ID', value: customApiClientId }
          { name: 'ENTRA_API_CLIENT_SECRET', secretRef: 'entra-client-secret' }
          { name: 'ENTRA_ALLOWED_CLIENT_IDS', value: allowedClientIds }
          { name: 'MCP_RESOURCE_URL', value: 'https://${appName}.${environmentDomain}/mcp' }
          { name: 'LAB_SUBSCRIPTION_ID', value: subscription().subscriptionId }
          { name: 'LAB_RESOURCE_GROUP', value: resourceGroup().name }
        ]
        probes: placeholder ? [] : [{
          type: 'Readiness'
          httpGet: { path: '/healthz', port: 8000, scheme: 'HTTP' }
          initialDelaySeconds: 3
          periodSeconds: 10
        }]
      }]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output pythonUrl string = 'https://${appName}.${environmentDomain}'
output pythonAppName string = app.name
