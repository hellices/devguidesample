param appName string
param tenantId string
param apiClientId string

@minLength(1)
param allowedClientIds array

resource app 'Microsoft.App/containerApps@2025-01-01' existing = {
  name: appName
}

resource auth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = {
  parent: app
  name: 'current'
  properties: {
    platform: { enabled: true }
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
      excludedPaths: ['/health', '/.well-known/oauth-protected-resource']
    }
    httpSettings: {
      requireHttps: true
      forwardProxy: { convention: 'Standard' }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: apiClientId
          openIdIssuer: '${az.environment().authentication.loginEndpoint}${tenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [apiClientId]
          defaultAuthorizationPolicy: {
            allowedApplications: allowedClientIds
          }
        }
      }
    }
    login: {
      tokenStore: { enabled: false }
    }
  }
}

output authConfigId string = auth.id
