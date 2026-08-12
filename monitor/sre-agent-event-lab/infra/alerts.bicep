@description('Azure region for scheduled query alert rules.')
param location string

@description('Resource ID of the workspace-based Application Insights component.')
param appInsightsResourceId string

@description('Tags applied to alert rules.')
param tags object

var alertDefinitions = [
  {
    name: 'alert-sre-lab-s1-http500'
    displayName: '[SRE-LAB-S1] HTTP 500 rate exceeded'
    description: 'Detects injected HTTP 500 responses from the SRE event lab.'
    measureColumn: 'Failures'
    threshold: 10
    query: '''
AppRequests
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where ResultCode startswith "5"
| summarize Failures=count()
'''
  }
  {
    name: 'alert-sre-lab-s2-latency'
    displayName: '[SRE-LAB-S2] Request p95 latency exceeded'
    description: 'Detects elevated p95 latency on the order endpoint.'
    measureColumn: 'P95DurationMs'
    threshold: 2000
    query: '''
AppRequests
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where Name has "/api/orders"
| summarize P95DurationMs=percentile(DurationMs, 95)
'''
  }
  {
    name: 'alert-sre-lab-s3-storage-rbac'
    displayName: '[SRE-LAB-S3] Blob dependency failures exceeded'
    description: 'Detects Blob authorization dependency failures from the SRE event lab.'
    measureColumn: 'DependencyFailures'
    threshold: 5
    query: format('''
AppDependencies
| where TimeGenerated > ago(5m)
| where AppRoleName == "sre-event-lab"
| where Target has "{0}"
| where Success == false
| summarize DependencyFailures=count()
''', environment().suffixes.storage)
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
        actionGroups: []
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
      muteActionsDuration: 'PT5M'
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
