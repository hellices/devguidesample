targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd 환경 이름. 리소스 그룹과 클러스터 이름에 쓰입니다.')
param environmentName string

@minLength(1)
@description('클러스터를 만들 리전. 실측은 eastus2에서 했습니다.')
param location string

@description('AKS Kubernetes 버전. 비워 두면 리전 기본 버전을 씁니다.')
param kubernetesVersion string = '1.36'

@description('시스템 풀과 CAS user 풀의 VM 크기')
param vmSize string = 'Standard_D4ds_v7'

@description('시스템 풀 노드 수')
param systemNodeCount int = 2

var token = toLower(uniqueString(subscription().id, environmentName, location))
var tags = { 'azd-env-name': environmentName }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module cas 'modules/aks.bicep' = {
  name: 'aks-cas'
  scope: rg
  params: {
    name: 'aks-cas-${token}'
    location: location
    tags: tags
    kubernetesVersion: kubernetesVersion
    vmSize: vmSize
    systemNodeCount: systemNodeCount
    mode: 'cas'
  }
}

module nap 'modules/aks.bicep' = {
  name: 'aks-nap'
  scope: rg
  params: {
    name: 'aks-nap-${token}'
    location: location
    tags: tags
    kubernetesVersion: kubernetesVersion
    vmSize: vmSize
    systemNodeCount: systemNodeCount
    mode: 'nap'
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output CAS_CLUSTER_NAME string = cas.outputs.name
output NAP_CLUSTER_NAME string = nap.outputs.name
