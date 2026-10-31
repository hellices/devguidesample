---
title: AKS 노드 확장 지연은 VM 준비 시간이 대부분이므로 여유 용량과 VM 재사용으로 줄인다
description: Cluster Autoscaler와 NAP 환경에서 Pod가 새 노드를 기다리는 시간을 단계별로 나누고, 실측으로 효과를 확인한 overprovisioning, Deallocate 모드, VM 크기 범위, 축소 설정과 나머지 최적화 수단을 정리합니다.
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [optimize, operate]
status: current
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Azure Kubernetes Service (AKS) scaling overview — HPA, VPA, Cluster Autoscaler, and KEDA
    url: https://learn.microsoft.com/azure/aks/concepts-scale
  - title: Cluster autoscaling in Azure Kubernetes Service (AKS) overview
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler-overview
  - title: Use the cluster autoscaler in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - title: Use Scale-down Mode to delete/deallocate nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/scale-down-mode
  - title: Configure node pools for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools
  - title: Configure AKSNodeClass resources for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-aksnodeclass
  - title: Configure node disruption policies for node auto-provisioning (NAP) nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption
  - title: Concepts - Storage in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/concepts-storage
  - title: Reduce time to deployment with Artifact Streaming on Azure Kubernetes Service (AKS) with Azure Container Registry (ACR)
    url: https://learn.microsoft.com/azure/aks/artifact-streaming
  - title: Overview of Node Auto-Provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning
  - title: Cluster Autoscaler FAQ
    url: https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md
  - title: Cluster Autoscaler 1.35 static_autoscaler.go
    url: https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.35/cluster-autoscaler/core/static_autoscaler.go
  - title: Karpenter Settings
    url: https://karpenter.sh/docs/reference/settings/
  - title: Karpenter Disruption
    url: https://karpenter.sh/docs/concepts/disruption/
last_verified: 2026-10-31
review_cycle_days: 180
applies_to: [AKS 1.36]
topic_order: 3
---

# AKS 노드 확장 지연은 VM 준비 시간이 대부분이므로 여유 용량과 VM 재사용으로 줄인다

새 노드가 필요한 Pod는 autoscaler가 확장을 결정하고, VM이 만들어져 노드로 등록되고,
Pod가 시작된 뒤에야 요청을 받습니다. 실측에서 이 시간의 대부분은 **VM 준비(60~80초)**였고,
autoscaler 종류에 따른 차이는 CAS가 새 Pending Pod를 보고 한 주기를 기다릴 때 생긴 확장
결정 단계의 10~20초였습니다. 그래서 가장 효과가 큰 방법은 VM을
기다리지 않게 하는 것입니다.

| 방법 | 대상 | 실측 효과 | 비용·제약 |
|---|---|---|---|
| overprovisioning(placeholder Pod) | CAS·NAP | 추가 Pod 시작 CAS 1~3초, NAP 1~22초 (새 노드를 기다리면 100초 안팎) | 여유 노드 비용 상시 발생 |
| Scale-down Mode `Deallocate` | CAS | 첫 노드 Ready 50초 (새 VM 78~104초) | Managed OS disk만 지원, 디스크 비용 유지 |
| VM 크기 범위 확대 | NAP | 노드 7대 → 1대, Pod Ready 102~104초 | 노드 1대 장애 영향 증가 |
| 축소 budget·profile 조정 | CAS·NAP | NAP budget 100%에서 축소 56~92초 | 노드 교체가 잦아질 수 있음 |
| OS 이미지 AzureLinux | CAS·NAP | 효과 없음 (첫 노드 Ready 81~87초) | - |

측정 조건과 단계별 원본 값은 [CAS와 NAP 확장 실측](../scale-out-benchmark/index.md)에 있습니다.

## Pod가 새 노드를 기다리는 시간은 결정, VM 준비, Pod 시작으로 나뉜다

| 단계 | CAS (VMSS) | NAP | 줄이는 방법 |
|---|---|---|---|
| 확장 결정 | 12~27초 (대기가 없으면 3초) | 2~5초 | CAS `scan-interval`, NAP는 기본 동작 |
| VM 생성·첫 노드 Ready | 결정 후 약 63초 (zone 1 고정 시 55~69초) | 결정 후 약 81초 (zone 1 고정 시 50~57초), 일부 노드 130~270초 | 여유 용량, VM 재사용 |
| Pod 시작 | 수 초 + 이미지 pull | 같음 | 작은 이미지, artifact streaming |

- CAS는 가장 오래된 Pending Pod가 2초 미만이면 다음 `scan-interval`(기본 10초)까지
  기다립니다. GPU Pod는 이 대기 시간이 30초입니다.
- NAP는 Pending Pod가 1초 동안 더 생기지 않으면 결정합니다(최대 10초).
- VM 준비 시간은 autoscaler보다 zone 조건과 측정 시점에 따라 달랐습니다. zone을 나누지 않은
  첫 측정에서는 CAS가, zone 1로 고정한 측정에서는 NAP가 조금 빨랐습니다(각 3~5회).
  자세한 조건은 [NAP와 CAS 시나리오별 실측](../scenario-comparison/index.md)에 있습니다.
- AKS Automatic은 NAP가 기본 구성되어 있고, 적격 Pod 준비 작업의 99.9%가 5분 안에
  끝나는 SLA를 제공합니다.

## placeholder Pod로 여유 용량을 잡아 두면 Pod는 VM을 기다리지 않는다

우선순위가 낮은 placeholder Pod가 노드 자리를 미리 차지합니다. 실제 Pod가 Pending이 되면
scheduler가 placeholder를 밀어내고(preemption) 그 자리에 바로 실행합니다. 밀려난
placeholder가 Pending이 되면 autoscaler가 다음 노드를 미리 만듭니다.

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovisioning
value: -10                # CAS는 -10 미만 Pod로는 확장하지 않음
preemptionPolicy: Never
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: overprovisioning
spec:
  replicas: 3             # 급증 시 바로 받아야 할 Pod 수만큼
  selector:
    matchLabels: {app: overprovisioning}
  template:
    metadata:
      labels: {app: overprovisioning}
    spec:
      priorityClassName: overprovisioning
      terminationGracePeriodSeconds: 0
      containers:
        - name: pause
          image: mcr.microsoft.com/oss/kubernetes/pause:3.6
          resources:
            requests: {cpu: "1", memory: 1Gi}   # 실제 Pod와 같은 크기
```

| 측정 (1 vCPU Pod 3개 추가) | 실제 Pod 시작 | placeholder 다시 Running |
|---|---|---|
| CAS (2회) | 1~3초 | 76~127초 |
| NAP (3회) | 대부분 1초, 마지막 Pod 11~22초 | 93~100초 |

NAP 측정에서는 Pod 2개가 바로 시작했고, 세 번째 Pod는 scheduler가 placeholder를 한 번 더
밀어낼 때까지 약 10초를 기다렸습니다. CAS 1회차는 컨테이너가 1초 만에 시작했지만
Deployment 상태 갱신이 늦어 측정 스크립트에는 126초로 기록됐습니다.

- placeholder 수는 "VM을 기다리지 않고 바로 받아야 하는 Pod 수"로 정합니다. 그만큼 노드
  비용이 항상 듭니다.
- placeholder가 다시 Running이 되기 전에 다음 급증이 오면 그 Pod는 VM을 기다립니다.
- NAP에서는 수요와 관계없이 노드 수를 고정하는 static NodePool(`spec.replicas`)로도 여유
  노드를 둘 수 있습니다.

## CAS Deallocate 모드는 할당 해제한 VM을 다시 시작해 첫 노드 Ready를 28~40초 앞당겼다

`--scale-down-mode Deallocate` 풀은 축소할 때 VM을 지우지 않고 할당 해제(중지)합니다.
다시 확장할 때는 새 VM보다 할당 해제된 VM을 먼저 시작합니다. 컨테이너 이미지도 디스크에
남아 있습니다.

```bash
az aks nodepool add -g $RG --cluster-name $CLUSTER -n burst \
  --node-osdisk-type Managed --scale-down-mode Deallocate \
  --enable-cluster-autoscaler --min-count 0 --max-count 10
```

| 측정 (1 vCPU Pod 20개, 노드 7대) | 첫 노드 Ready | 전체 Pod Ready |
|---|---|---|
| 일반 풀, ephemeral OS, 새 VM | 78~90초 | 101~127초 |
| Deallocate 풀, 첫 확장(새 VM, Managed OS) | 104초 | 142초 |
| Deallocate 풀, 재시작 2회 | 50초 | 82초, 123초 |

- ephemeral OS disk를 쓸 수 없어 처음 만드는 VM은 1회 측정에서 104초로 일반 풀보다
  늦었습니다. 확장·축소가 반복되는 풀에 씁니다.
- 할당 해제된 VM은 compute 비용은 없지만 OS 디스크 비용이 남습니다.
- 재시작한 노드는 Ready가 된 뒤에도 taint가 남아 Pod 배치가 중앙값 약 23초 늦었습니다
  (`results/cas-dealloc-pod-scheduling.csv`, 재시작 2회).
- 할당 해제된 노드는 `NotReady`로 API server에 남습니다. 노드 수를 세는 모니터링은 이를
  감안해야 합니다.

## NAP는 VM 크기 범위를 넓히면 적은 수의 큰 노드로 꼬리 지연을 피한다

| NodePool requirements | 1 vCPU Pod 20개 결과 |
|---|---|
| `sku-name: Standard_D4ds_v7` | 노드 7대, Pod Ready 102~273초 |
| `sku-family: D`, `sku-version: 7`, `sku-cpu < 33` | `Standard_D32als_v7` 1대, Pod Ready 102~104초 |

- VM 여러 대를 동시에 만들면 가장 늦은 VM이 전체 완료 시간을 정합니다. 큰 VM 1대로 모으면
  그 위험이 줄어듭니다. 대신 노드 1대 장애의 영향이 커지므로 replica를 여러 노드에 나눠야
  하면 topology spread를 함께 둡니다.
- `karpenter.sh/capacity-type`은 `on-demand`로 고정합니다. 생략하거나 spot을 함께 허용하면 NAP는 spot을 먼저 고르므로, 운영 워크로드의 확장 시간과 가용성이 spot 재고와 회수에 좌우됩니다.
- 이미지가 amd64 전용이면 `kubernetes.io/arch: amd64`를 지정합니다. 지정하지 않으면 Arm64
  VM도 후보가 됩니다.

## 확장 결정 대기는 10초 안팎이라 설정 조정의 효과가 작다

- CAS `scan-interval`을 줄이면 "very new" 대기도 짧아지지만, 줄일 수 있는 시간은 최대 10초
  남짓이고 autoscaler loop가 더 자주 돕니다.
- GPU 노드를 CAS로 확장하면 최소 30초를 기다립니다. GPU 워크로드는 placeholder로 여유 노드를
  두는 편이 효과가 큽니다.
- CAS `new-pod-scale-up-delay`(기본 0초)를 늘리면 오히려 결정이 늦어집니다. 짧은 batch Pod를
  무시하려는 경우에만 씁니다.

## 이미지 pull은 Premium ACR의 artifact streaming으로 줄인다

이번 실측은 `pause` 이미지라 pull 시간이 거의 없었습니다. 큰 이미지에서는 새 노드에서
이미지를 받는 시간이 VM 준비 다음으로 큽니다.

- **artifact streaming:** Premium ACR에서 이미지를 streaming 형식으로 만들고 노드 풀(NAP는
  `AKSNodeClass.spec.artifactStreaming.enabled`)에서 켜면, 시작에 필요한 부분만 먼저 받습니다.
  Linux AMD64 이미지와 tag 기반 pull만 지원하고 `imagePullSecrets`는 지원하지 않습니다.
- **ephemeral OS disk:** 노드 확장을 빠르게 하므로 가능하면 사용합니다. CAS 풀은 VM이 지원하고
  임시 저장소가 충분하면 기본값이고, NAP는 조건이 맞으면 자동으로 씁니다. 1회 측정에서 Managed
  OS disk 새 VM은 첫 노드 Ready가 104초로 ephemeral(78~90초)보다 늦었습니다.
- **OS 이미지:** AzureLinux로 바꿔도 노드 준비 시간 차이는 측정되지 않았습니다.

## 축소 속도는 CAS profile과 NAP budget으로 조정한다

| 설정 | 실측 축소 완료 |
|---|---|
| CAS 기본 profile (`scale-down-unneeded-time` 10분) | 10분 이상 |
| CAS `scale-down-unneeded-time=1m`, `scale-down-delay-after-add=0m` | 109~306초 |
| NAP `consolidateAfter: 0s`, budget 30% | 214~344초 |
| NAP `consolidateAfter: 0s`, budget 100% | 56~92초 |

```yaml
# NAP: 빈 노드를 한 번에 정리하되, 평일 업무 시간에는 동시 정리를 제한
spec:
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "100%"
      - nodes: "20%"
        schedule: "0 0 * * 1-5"   # UTC 기준
        duration: 10h
```

비율 budget은 `roundup(노드 수 × 비율)`에서 삭제 중·`NotReady` 노드를 뺀 수만큼 동시 정리를
허용합니다(노드 7대에 30%면 3대). 여러 budget이 동시에 적용되면 가장 제한적인 값이 쓰입니다.
Microsoft Learn의 NAP 예시 주석은 `consolidateAfter`를 `WhenEmpty`에서만 설정할 수 있다고
적지만, Karpenter v1 문서는 두 정책 모두에 적용하며 이번 실측 NodePool도
`WhenEmptyOrUnderutilized`와 함께 사용했습니다. 축소를 너무 빠르게 하면 급증이
반복될 때 노드를 지웠다가 다시 만드는 일이 생깁니다. 부하가 몇 분 간격으로 오르내리면
`consolidateAfter`나 `scale-down-unneeded-time`을 그 간격보다 길게 둡니다.

## 공식 참고 자료

- [AKS scaling overview](https://learn.microsoft.com/azure/aks/concepts-scale)
- [Cluster autoscaling in AKS overview](https://learn.microsoft.com/azure/aks/cluster-autoscaler-overview)
- [Use the cluster autoscaler in AKS](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [Use Scale-down Mode to delete/deallocate nodes](https://learn.microsoft.com/azure/aks/scale-down-mode)
- [Configure node pools for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools)
- [Configure AKSNodeClass resources for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-aksnodeclass)
- [Configure node disruption policies for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption)
- [Concepts - Storage in AKS (Ephemeral OS disks)](https://learn.microsoft.com/azure/aks/concepts-storage)
- [Artifact Streaming on AKS](https://learn.microsoft.com/azure/aks/artifact-streaming)
- [Overview of NAP (AKS Automatic SLA)](https://learn.microsoft.com/azure/aks/node-auto-provisioning)
- [Cluster Autoscaler FAQ (overprovisioning)](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md)
- [Cluster Autoscaler 1.35 static_autoscaler.go](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.35/cluster-autoscaler/core/static_autoscaler.go)
- [Karpenter Settings](https://karpenter.sh/docs/reference/settings/)
- [Karpenter Disruption](https://karpenter.sh/docs/concepts/disruption/)
