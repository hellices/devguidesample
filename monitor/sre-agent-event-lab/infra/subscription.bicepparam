using './subscription.bicep'

param location = 'koreacentral'
param resourceGroupName = 'rg-sre-agent-event-lab-krc'
param suffix = '95933ae5'
param containerImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param deployContainerApp = false
param actionGroupResourceId = ''
param tags = {
  purpose: 'sre-agent-event-lab'
  expiresOn: '2026-08-13'
}
