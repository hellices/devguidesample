using './main.bicep'

param location = 'koreacentral'
param workspaceResourceId = '/subscriptions/<subscription-id>/resourceGroups/<workspace-rg>/providers/Microsoft.OperationalInsights/workspaces/<workspace-name>'
param workbookDisplayName = 'HDInsight Kafka Operations'
param dashboardDisplayName = 'HDInsight Kafka Operations Dashboard'
param dashboardName = 'kafka-ops-dash'
param tags = {
  workload: 'hdinsight-kafka'
  owner: 'platform-ops'
}
