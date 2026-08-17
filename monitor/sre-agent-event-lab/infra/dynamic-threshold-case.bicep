@description('Azure region for the Dynamic Threshold case resources.')
param location string

@description('Stable alphanumeric suffix used for resource names.')
param suffix string

@description('Resource ID of the Log Analytics workspace backing Application Insights.')
param workspaceResourceId string

@description('Resource ID of the Application Insights component linked to the web test.')
param appInsightsResourceId string

@description('Public FQDN of the deployed Container App.')
param containerAppFqdn string

@description('Deployment-unique OpenTelemetry service name.')
param serviceName string

@description('Tags applied to Dynamic Threshold case resources.')
param tags object

var baselineWebTestName = 'webtest-sre-lab-orders-${suffix}'
var dynamicThresholdAlertName = 'alert-sre-lab-s2-dynamic-latency'
var latencyQuery = format('''
AppRequests
| where AppRoleName == "{0}"
| where Name has "/api/orders"
| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)
''', serviceName)

resource baselineWebTest 'Microsoft.Insights/webTests@2022-06-15' = {
  name: baselineWebTestName
  location: location
  kind: 'standard'
  tags: union(tags, {
    'hidden-link:${appInsightsResourceId}': 'Resource'
  })
  properties: {
    Description: 'Produces one bounded /api/orders request every five minutes for the Dynamic Threshold lab.'
    Enabled: true
    Frequency: 300
    Kind: 'standard'
    // DurationMs is measured server-side, so one stable location is enough to
    // keep the baseline dense without multiplying probe traffic across regions.
    Locations: [
      {
        Id: 'us-va-ash-azr'
      }
    ]
    Name: baselineWebTestName
    Request: {
      FollowRedirects: false
      HttpVerb: 'GET'
      ParseDependentRequests: false
      RequestUrl: 'https://${containerAppFqdn}/api/orders'
    }
    RetryEnabled: false
    SyntheticMonitorId: baselineWebTestName
    Timeout: 15
    ValidationRules: {
      ExpectedHttpStatusCode: 200
      SSLCheck: true
    }
  }
}

resource dynamicLatencyAlert 'Microsoft.Insights/scheduledQueryRules@2025-01-01-preview' = {
  name: dynamicThresholdAlertName
  location: location
  kind: 'LogAlert'
  tags: tags
  properties: {
    actions: {
      actionGroups: []
    }
    autoMitigate: true
    checkWorkspaceAlertsStorageConfigured: false
    criteria: {
      allOf: [
        {
          alertSensitivity: 'Medium'
          criterionType: 'DynamicThresholdCriterion'
          failingPeriods: {
            minFailingPeriodsToAlert: 2
            numberOfEvaluationPeriods: 4
          }
          metricMeasureColumn: 'P95DurationMs'
          operator: 'GreaterThan'
          query: latencyQuery
          timeAggregation: 'Average'
        }
      ]
    }
    description: 'Shadow-mode Dynamic Threshold for abnormal /api/orders p95 latency.'
    displayName: '[SRE-LAB-S2-DYNAMIC] Request p95 latency outside learned range'
    enabled: true
    evaluationFrequency: 'PT5M'
    scopes: [
      workspaceResourceId
    ]
    severity: 3
    skipQueryValidation: false
    targetResourceTypes: [
      'Microsoft.OperationalInsights/workspaces'
    ]
    windowSize: 'PT20M'
  }
}

output baselineWebTestName string = baselineWebTest.name
output dynamicThresholdAlertName string = dynamicLatencyAlert.name
