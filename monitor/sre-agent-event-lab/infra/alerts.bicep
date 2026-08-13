@description('Azure region for scheduled query alert rules.')
param location string

@description('Resource ID of the workspace-based Application Insights component.')
param appInsightsResourceId string

@description('Optional Action Group that forwards fired alerts to Azure SRE Agent.')
param actionGroupResourceId string = ''

@description('Deployment-unique OpenTelemetry service name.')
param serviceName string

@description('Tags applied to alert rules.')
param tags object

var alertDefinitions = [
  {
    name: 'alert-sre-lab-s1-http500'
    displayName: '[SRE-LAB-S1] HTTP 500 rate exceeded'
    description: 'Detects injected HTTP 500 responses from the SRE event lab.'
    measureColumn: 'Failures'
    threshold: 10
    query: format('''
requests
| where timestamp > ago(5m)
| where cloud_RoleName == "{0}"
| where name has "/api/orders"
| where resultCode == "500"
| summarize Failures=count()
''', serviceName)
  }
  {
    name: 'alert-sre-lab-s2-latency'
    displayName: '[SRE-LAB-S2] Request p95 latency exceeded'
    description: 'Detects elevated p95 latency on the order endpoint.'
    measureColumn: 'P95DurationMs'
    threshold: 2000
    query: format('''
requests
| where timestamp > ago(5m)
| where cloud_RoleName == "{0}"
| where name has "/api/orders"
| summarize P95DurationMs=percentile(duration, 95)
''', serviceName)
  }
  {
    name: 'alert-sre-lab-s3-storage-rbac'
    displayName: '[SRE-LAB-S3] Blob dependency failures exceeded'
    description: 'Detects Blob authorization dependency failures from the SRE event lab.'
    measureColumn: 'DependencyFailures'
    threshold: 5
    query: format('''
dependencies
| where timestamp > ago(5m)
| where cloud_RoleName == "{0}"
| where target has "{1}"
| where resultCode == "403"
| summarize DependencyFailures=count()
''', serviceName, environment().suffixes.storage)
  }
]

resource alertRules 'Microsoft.Insights/scheduledQueryRules@2023-12-01' = [
  for definition in alertDefinitions: {
    name: definition.name
    location: location
    kind: 'LogAlert'
    tags: tags
    properties: {
      actions: {
        actionGroups: empty(actionGroupResourceId) ? [] : [
          actionGroupResourceId
        ]
      }
      autoMitigate: true
      checkWorkspaceAlertsStorageConfigured: false
      criteria: {
        allOf: [
          {
            failingPeriods: {
              minFailingPeriodsToAlert: 1
              numberOfEvaluationPeriods: 1
            }
            metricMeasureColumn: definition.measureColumn
            operator: 'GreaterThan'
            query: definition.query
            threshold: definition.threshold
            timeAggregation: 'Maximum'
          }
        ]
      }
      description: definition.description
      displayName: definition.displayName
      enabled: true
      evaluationFrequency: 'PT1M'
      scopes: [
        appInsightsResourceId
      ]
      severity: 2
      skipQueryValidation: false
      targetResourceTypes: [
        'Microsoft.Insights/components'
      ]
      windowSize: 'PT5M'
    }
  }
]

output alertRuleNames array = [
  for (definition, index) in alertDefinitions: alertRules[index].name
]
