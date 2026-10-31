targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd 환경 이름. 리소스 그룹과 리소스 이름에 쓰입니다.')
param environmentName string

@minLength(1)
@description('리소스를 만들 리전. 실측은 eastus2에서 했습니다.')
param location string

@description('AKS Kubernetes 버전. 비워 두면 리전 기본 버전을 씁니다.')
param kubernetesVersion string = '1.36'

@description('시스템 풀 VM 크기. k6 부하 Job도 시스템 풀에서 실행합니다.')
param systemVmSize string = 'Standard_D4ds_v7'

var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module core 'modules/core.bicep' = {
  name: 'keda-core'
  scope: rg
  params: {
    location: location
    tags: tags
    token: token
    kubernetesVersion: kubernetesVersion
    systemVmSize: systemVmSize
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AKS_CLUSTER_NAME string = core.outputs.clusterName
output AZURE_MONITOR_WORKSPACE_ID string = core.outputs.amwId
output AMW_QUERY_ENDPOINT string = core.outputs.amwQueryEndpoint
output KEDA_CLIENT_ID string = core.outputs.kedaClientId
output KEDA_PRINCIPAL_ID string = core.outputs.kedaPrincipalId
