targetScope = 'resourceGroup'

@description('Location for shared monitoring resources. Defaults to the target resource group location.')
param location string = resourceGroup().location

@description('Resource ID of the existing Log Analytics workspace that stores HDInsight Kafka metrics.')
param workspaceResourceId string

@description('Display name for the shared Azure Workbook.')
param workbookDisplayName string = 'HDInsight Kafka Operations'

@description('Display name shown in the Azure portal for the shared Azure Dashboard.')
param dashboardDisplayName string = 'HDInsight Kafka Operations Dashboard'

@description('Resource name for the shared Azure Dashboard. Use 3-24 letters, numbers, and dashes.')
param dashboardName string = 'kafka-ops-dash'

@description('Optional tags applied to the Workbook and Dashboard resources.')
param tags object = {}

module monitoring './modules/monitoring.bicep' = {
  name: 'hdinsight-kafka-monitoring-assets'
  params: {
    location: location
    workspaceResourceId: workspaceResourceId
    workbookDisplayName: workbookDisplayName
    dashboardDisplayName: dashboardDisplayName
    dashboardName: dashboardName
    tags: tags
  }
}

output workbookResourceId string = monitoring.outputs.workbookResourceId
output workbookPortalUrl string = monitoring.outputs.workbookPortalUrl
output dashboardResourceId string = monitoring.outputs.dashboardResourceId
