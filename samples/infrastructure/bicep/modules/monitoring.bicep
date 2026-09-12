@description('Location for the Workbook and Dashboard resources.')
param location string

@description('Resource ID of the existing Log Analytics workspace that stores HDInsight Kafka metrics.')
param workspaceResourceId string

@description('Display name for the shared Azure Workbook.')
param workbookDisplayName string

@description('Display name shown in the Azure portal for the shared Azure Dashboard.')
param dashboardDisplayName string

@description('Resource name for the shared Azure Dashboard. Use 3-24 letters, numbers, and dashes.')
param dashboardName string

@description('Optional tags applied to the Workbook and Dashboard resources.')
param tags object = {}

var workbookName = guid(resourceGroup().id, 'Microsoft.Insights/workbooks', workbookDisplayName, workspaceResourceId)
var workbookSerializedData = string(json(replace(
  loadTextContent('../../monitor/assets/hdinsight-kafka-workbook.template.json'),
  '__WORKSPACE_RESOURCE_ID__',
  workspaceResourceId
)))
var workbookPortalUrl = '${environment().portal}/#view/AppInsightsExtension/UsageNotebookBlade/ComponentId/Azure%20Monitor/ConfigurationId/${uriComponent(resourceId('Microsoft.Insights/workbooks', workbookName))}/Type/workbook/WorkbookTemplateName/${uriComponent(workbookDisplayName)}'
var dashboardProperties = json(replace(replace(
  loadTextContent('../../monitor/assets/hdinsight-kafka-dashboard.properties.template.json'),
  '__WORKSPACE_RESOURCE_ID__',
  workspaceResourceId
), '__WORKBOOK_PORTAL_URL__', workbookPortalUrl))

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: workbookName
  location: location
  kind: 'shared'
  tags: tags
  properties: {
    category: 'workbook'
    description: 'Workbook for HDInsight Kafka operational monitoring backed by Log Analytics.'
    displayName: workbookDisplayName
    serializedData: workbookSerializedData
    sourceId: workspaceResourceId
    version: 'Notebook/1.0'
  }
}

resource dashboard 'Microsoft.Portal/dashboards@2022-12-01-preview' = {
  name: dashboardName
  location: location
  tags: union(tags, {
    'hidden-title': dashboardDisplayName
  })
  properties: dashboardProperties
}

output workbookResourceId string = workbook.id
output workbookPortalUrl string = workbookPortalUrl
output dashboardResourceId string = dashboard.id
