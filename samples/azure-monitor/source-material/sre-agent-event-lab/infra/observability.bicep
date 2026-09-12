@description('Azure region for observability resources.')
param location string

@description('Stable alphanumeric suffix used for resource names.')
param suffix string

@description('Tags applied to observability resources.')
param tags object

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'law-sre-event-lab-${suffix}'
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-sre-event-lab-${suffix}'
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    IngestionMode: 'LogAnalytics'
    WorkspaceResourceId: workspace.id
  }
}

// The alert rules in alerts.bicep are scoped to this workspace resource ID:
// their queries read the workspace-schema tables (AppRequests,
// AppDependencies), which are known tables only under the workspace scope.
output workspaceId string = workspace.id
output workspaceCustomerId string = workspace.properties.customerId
@secure()
output workspaceSharedKey string = workspace.listKeys().primarySharedKey
output appInsightsName string = appInsights.name
output appInsightsResourceId string = appInsights.id
@secure()
output appInsightsConnectionString string = appInsights.properties.ConnectionString
