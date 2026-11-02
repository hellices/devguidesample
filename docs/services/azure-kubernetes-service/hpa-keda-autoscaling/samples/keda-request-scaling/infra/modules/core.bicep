param location string
param tags object
param token string
param kubernetesVersion string
param systemVmSize string

// NAP 클러스터: 워크로드 노드는 AKS 기본 NodePool(default, on-demand 전용)이 만듭니다.
resource aks 'Microsoft.ContainerService/managedClusters@2026-06-01' = {
  name: 'aks-keda-${token}'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Base', tier: 'Standard' }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: 'aks-keda-${token}'
    enableRBAC: true
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        vmSize: systemVmSize
        count: 2
        osType: 'Linux'
        type: 'VirtualMachineScaleSets'
        nodeTaints: ['CriticalAddonsOnly=true:NoSchedule']
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      loadBalancerSku: 'standard'
    }
    nodeProvisioningProfile: { mode: 'Auto', defaultNodePools: 'Auto' }
    // KEDA add-on보다 Workload Identity를 먼저(같은 배포에서) 켭니다.
    oidcIssuerProfile: { enabled: true }
    securityProfile: { workloadIdentity: { enabled: true } }
    workloadAutoScalerProfile: { keda: { enabled: true } }
  }
}

resource amw 'Microsoft.Monitor/accounts@2023-04-03' = {
  name: 'amw-keda-${token}'
  location: location
  tags: tags
}

// keda-operator가 Workload Identity로 쓰는 사용자 할당 관리 ID
resource kedaId 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-keda-${token}'
  location: location
  tags: tags
}

resource kedaFic 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: kedaId
  name: 'keda-operator'
  properties: {
    issuer: aks.properties.oidcIssuerProfile.issuerURL
    subject: 'system:serviceaccount:kube-system:keda-operator'
    audiences: ['api://AzureADTokenExchange']
  }
}

// Prometheus scaler가 Azure Monitor workspace query endpoint를 읽는 권한
var monitoringDataReader = 'b0d8363b-8ddd-447d-831f-62ca05bff136'
resource amwReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(amw.id, kedaId.id, monitoringDataReader)
  scope: amw
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringDataReader)
    principalId: kedaId.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output clusterName string = aks.name
output amwId string = amw.id
output amwQueryEndpoint string = amw.properties.metrics.prometheusQueryEndpoint
output kedaClientId string = kedaId.properties.clientId
output kedaPrincipalId string = kedaId.properties.principalId
