@description('클러스터 이름')
param name string
param location string
param tags object
param kubernetesVersion string
param vmSize string
param systemNodeCount int

@allowed(['cas', 'nap'])
@description('cas: VMSS user 풀 + Cluster Autoscaler, nap: Node Auto-Provisioning')
param mode string

// 실측과 같은 운영형 기본값: Azure CNI Overlay + Cilium, 관리 ID, 시스템 풀 분리
var systemPool = {
  name: 'system'
  mode: 'System'
  vmSize: vmSize
  count: systemNodeCount
  osType: 'Linux'
  type: 'VirtualMachineScaleSets'
  nodeTaints: ['CriticalAddonsOnly=true:NoSchedule']
}

// on-demand(Regular) VMSS 풀. 축소 비교를 위해 autoscaler profile의 unneeded-time을 1분으로 줄였습니다.
var casUserPool = {
  name: 'user'
  mode: 'User'
  vmSize: vmSize
  count: 0
  minCount: 0
  maxCount: 10
  enableAutoScaling: true
  scaleSetPriority: 'Regular'
  osType: 'Linux'
  type: 'VirtualMachineScaleSets'
}

resource aks 'Microsoft.ContainerService/managedClusters@2026-06-01' = {
  name: name
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Base', tier: 'Standard' }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: name
    enableRBAC: true
    agentPoolProfiles: mode == 'cas' ? [systemPool, casUserPool] : [systemPool]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      loadBalancerSku: 'standard'
    }
    autoScalerProfile: mode == 'cas' ? {
      'scan-interval': '10s'
      'scale-down-delay-after-add': '0m'
      'scale-down-unneeded-time': '1m'
      'scale-down-unready-time': '1m'
    } : null
    // NAP 기본 NodePool(default, system-surge)은 on-demand만 허용합니다.
    nodeProvisioningProfile: mode == 'nap' ? { mode: 'Auto', defaultNodePools: 'Auto' } : null
  }
}

output name string = aks.name
