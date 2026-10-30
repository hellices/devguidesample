---
title: AKS NAP는 확장 결정이 10초 이상 빨랐지만 VM 부팅 시간이 같아 Pod 준비 시간은 CAS와 비슷했다
description: v7 VM과 on-demand 고정 조건에서 VMSS Cluster Autoscaler와 NAP의 확장 결정·VM 생성·노드 준비·Pod 준비·축소 시간을 단계별로 나눠 측정하고, NAP가 실제로 앞선 상황과 그렇지 않은 상황을 정리합니다.
document_type: research
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [evaluate, optimize]
status: current
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Overview of Node Auto-Provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning
  - title: Configure node pools for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools
  - title: Configure node disruption policies for node auto-provisioning (NAP) nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption
  - title: Use the cluster autoscaler in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - title: Cluster autoscaling in Azure Kubernetes Service (AKS) overview
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler-overview
  - title: Cluster Autoscaler FAQ
    url: https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md
  - title: Cluster Autoscaler 1.36 static_autoscaler.go
    url: https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/core/static_autoscaler.go
  - title: Karpenter Settings
    url: https://karpenter.sh/docs/reference/settings/
  - title: AKS node bootstrap design for Karpenter provider Azure
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/designs/0001-aks-node-bootstrap.md
  - title: Karpenter provider Azure offering error handlers
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/instance/offerings/commonerrorhandlers.go
  - title: Karpenter provider Azure quota provider
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/quota/quota.go
  - title: Karpenter provider Azure quota controller
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/controllers/quota/controller.go
  - title: Cluster Autoscaler 1.36 Azure scale set instance cache
    url: https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/cloudprovider/azure/azure_scale_set_instance_cache.go
  - title: Cluster Autoscaler 1.36 Azure config
    url: https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/cloudprovider/azure/azure_config.go
published_at: 2026-10-30
topic_order: 1
---

# AKS NAP는 확장 결정이 10초 이상 빨랐지만 VM 부팅 시간이 같아 Pod 준비 시간은 CAS와 비슷했다

"Karpenter가 더 빠르다"는 말은 **확장을 결정하는 단계**에서는 맞았습니다. NAP는
Pending Pod가 생기고 2~5초 만에 NodeClaim을 만들었고, VMSS Cluster
Autoscaler(CAS)는 12~27초 뒤에 VMSS 크기를 바꿨습니다. 하지만 그 뒤 VM이 만들어지고
노드가 Ready가 되기까지 65~80초가 걸려, Pod가 실행되기까지의 시간은 두 방식이
비슷했습니다. NAP가 분명히 앞선 것은 VM 크기 선택, 기존 풀에 맞지 않는 큰 Pod,
budget을 조정했을 때의 축소였습니다.

| 시나리오 (1 vCPU Pod 20개, 중앙값) | 확장 결정 | 첫 노드 Ready | 전체 Pod Ready | 만든 노드 |
|---|---|---|---|---|
| CAS, `Standard_D4ds_v7` 풀 (3회) | 15초 | 81초 | 108초 | D4 × 7 |
| NAP, `Standard_D4ds_v7` 고정 (5회) | 3초 | 83초 | 119초 | D4 × 7 |
| NAP, v7 D 계열 자유 선택 (2회) | 2초 | 88초 | 103초 | D32als_v7 × 1 |

## 확장 결정·VM 생성·노드 준비를 나눠 재야 차이가 보인다

- **질문:** NAP(관리형 Karpenter)가 VMSS 기반 CAS보다 빠르다면, 어느 단계에서 얼마나 빠른가?
- **부하:** `pause` 컨테이너, Pod당 1 vCPU·1 GiB 요청. 0개에서 시작합니다.
- **단계 정의:** `bench/analyze.py`가 클러스터 스냅샷에서 계산합니다.

| 단계 | CAS 기준 | NAP 기준 |
|---|---|---|
| 확장 결정 | `ScaledUpGroup`(setting group size) 이벤트 | NodeClaim 생성 |
| VM 생성 요청 완료 | 측정하지 않음 (VMSS PUT은 로그상 약 3초) | NodeClaim `Launched` |
| 노드 Ready | Node `Ready` 전환 | 같음 |
| Pod Ready | 모든 Pod `Ready` 전환 | 같음 |
| 축소 완료 | VMSS 인스턴스 0개 | NodeClaim 0개 또는 Ready 노드 0개 |

## 2026-10-30 East US 2, AKS 1.36.5, v7 on-demand로 조건을 맞췄다

| 항목 | CAS 클러스터 | NAP 클러스터 |
|---|---|---|
| 네트워크 | Azure CNI Overlay + Cilium | 동일 |
| 시스템 풀 | `Standard_D4ds_v7` × 2, `CriticalAddonsOnly` taint | 동일 |
| 워크로드 VM | user 풀 `Standard_D4ds_v7`, Regular(on-demand), ephemeral OS, zone 미지정 | NodePool `sku-name: Standard_D4ds_v7`, `capacity-type: on-demand`, `arch: amd64`, ephemeral OS |
| autoscaler 설정 | `scan-interval=10s`, `scale-down-unneeded-time=1m`, `scale-down-delay-after-add=0m` | `consolidateAfter: 0s`, budget 30% |
| OS 이미지 | Ubuntu 24.04 | 동일 |

CAS 축소 값은 기본값(10분)으로 두면 비교에 수십 분이 걸려 1분으로 줄였습니다.
원본 결과는 sample의 `results/scale-out-v7.csv`에 있습니다.

## CAS는 새 Pending Pod를 보고도 한 주기를 기다렸다

CAS control plane 로그에서 결정 지연의 원인을 확인했습니다.

```text
13:26:23 Autoscaler loop triggered by unschedulable pod appearing
13:26:23 Unschedulable pods are very new, waiting one iteration for more
13:26:34 Autoscaler loop triggered by a 10s timer
13:26:34 Final scale-up plan: [{aks-user-...-vmss 0->7 (max: 10)}]
13:26:37 Calling PollUntilDone for CreateOrUpdate(aks-user-...-vmss)
```

- CAS도 Pending Pod가 생기면 바로 loop를 돌립니다. 하지만 가장 오래된 Pending Pod가
  2초가 안 됐으면 Pod가 더 올 수 있다고 보고 다음 `scan-interval`(10초)까지 기다립니다.
  GPU를 요청하는 Pod는 이 대기 시간이 30초입니다(CAS 1.36 소스의 `unschedulablePodTimeBuffer`,
  `unschedulablePodWithGpuTimeBuffer`).
- NAP는 첫 Pending Pod 이후 1초 동안 새 Pod가 없으면 바로 결정합니다(Karpenter
  `BATCH_IDLE_DURATION` 기본 1초, 최대 10초).
- 그 결과 확장 결정은 CAS 12~27초, NAP 2~5초였습니다. **Karpenter가 빠르다는 근거는
  이 10~20초 차이입니다.**

## VM이 노드로 준비되는 시간은 VMSS 쪽이 조금 짧았다

| 구간 (중앙값) | CAS (VMSS) | NAP (단독 VM) |
|---|---|---|
| 결정 → 첫 노드 Ready | 약 63초 | 약 81초 |
| NAP NodeClaim 생성 → Launched | - | 3~4초 |
| NAP Launched → 노드 등록 | - | 약 70초 |

- NAP는 VMSS를 거치지 않고 노드마다 VM을 따로 만듭니다. 이번 측정에서는 결정에서
  얻은 10초 남짓의 이점을 VM 준비 시간에서 거의 돌려받았습니다.
- **꼬리 지연은 NAP가 더 컸습니다.** NAP는 노드를 zone 1~4에 나눠 만들었고, 7대 중
  1~2대가 130~270초까지 늦어진 run이 있었습니다. 한 번은 zone 2의 VM 생성 요청 자체가
  126초 걸렸습니다. CAS 풀은 zone을 지정하지 않은 regional VMSS여서 burst에서는
  마지막 노드가 96~115초 안에 들어왔습니다.
- 마지막 노드가 늦으면 그 노드에 배치될 Pod도 늦어지므로, 전체 Pod Ready 중앙값은
  NAP(119초)가 CAS(108초)보다 조금 길었습니다.

## Pod가 30초 간격으로 늘어나도 VM 부팅이 결과를 좌우했다

Pod 5개씩 30초 간격으로 4번 추가했습니다(각 2회). 값은 각 wave의 Pod가 모두 Ready가
되기까지 걸린 시간입니다.

| 방식 | wave 1 / 2 / 3 / 4 | 전체 |
|---|---|---|
| CAS | 117/137/107/19, 94/107/280/27 | 169초, 342초 |
| NAP | 92/127/130/47, 96/132/146/30 | 192초, 208초 |

- CAS는 wave마다 VMSS를 1~2대씩 늘렸고(0→2→3→…→7), 매번 "very new" 대기를 거쳤습니다.
- CAS 2회차에서는 Pod 5개가 Pending인데도 CAS가 약 2분 동안 `Schedulable pods present`로
  판단해 확장하지 않았고, VMSS 목록을 새로 고친 뒤에야 5→7로 늘렸습니다. CAS는 자체
  스케줄링 시뮬레이션과 VMSS 캐시를 기준으로 판단하므로 이런 지연이 생길 수 있습니다.
- NAP는 wave마다 2초 안에 NodeClaim을 만들었지만, 노드 준비 시간이 같아 전체 시간은
  비슷했습니다.

## NAP는 VM 크기를 고를 수 있을 때 CAS가 못 하는 일을 했다

| 상황 | CAS (`Standard_D4ds_v7` 풀만 있음) | NAP (v7 D 계열, 32 vCPU 이하, amd64, on-demand) |
|---|---|---|
| 1 vCPU Pod 20개 | D4 × 7, 108초 | **D32als_v7 × 1**, 103초. 축소 86~93초 |
| 6 vCPU Pod 4개 | **확장하지 않음** (`NotTriggerScaleUp: Insufficient cpu`) | D32als_v7 × 1, 96초 |

- CAS는 풀마다 VM 크기가 하나이므로 4 vCPU보다 큰 Pod를 받으려면 큰 VM 풀을 미리
  만들어 둬야 합니다.
- NAP는 허용 범위 안에서 Pending Pod 전체를 담을 VM을 고릅니다. 이번에는 메모리가
  적은 AMD v7(`Dals`)을 골랐습니다. `arch`를 지정하지 않았던 v6 측정에서는 Arm64
  VM을 골랐습니다.

## 선호 VM을 만들 수 없을 때 NAP는 시도 없이 2~3초 만에 대체했다

Karpenter 문서가 말하는 "빠른 노드 생성"은 용량이 없을 때 다른 후보로 넘어가는 속도입니다.
선호 VM 생성이 실패하도록 리전 vCPU 한도(100)를 넘는 96 vCPU VM을 1순위로 두고, 실패하면
`Standard_D4ds_v7`로 넘어가게 구성했습니다(1 vCPU Pod 20개).

| 구성 | 1순위 | 대체 |
|---|---|---|
| CAS | `Standard_D96ds_v7` 풀, priority expander 50 | `Standard_D4ds_v7` 풀, priority 10 |
| NAP | NodePool `weight: 100`, `sku-name: Standard_D96ds_v7` | NodePool `weight: 10`, `sku-name: Standard_D4ds_v7` |

| 측정 (2회) | 1순위 실패 확인 | 대체 결정 | 첫 노드 Ready | 전체 Pod Ready |
|---|---|---|---|---|
| CAS | 13초 (`OperationNotAllowed`: 리전 vCPU quota 초과) | 23~24초 | 66~76초 | 104~112초 |
| NAP | 시도하지 않음 (`NoCompatibleInstanceTypes`) | 2~3초 | 83초 | 96~130초 |

- CAS는 12초에 big 풀 확장을 요청했고, 1초 뒤 quota 오류를 받아 그 풀을 backoff한 다음 loop
  (약 10초 뒤)에서 대체 풀을 늘렸습니다. quota 오류는 VMSS 요청 즉시 돌아오는 동기 오류라
  CAS도 빨리 넘어갑니다.
- NAP는 VM 계열 quota를 10분마다 조회해 남은 quota로 만들 수 없는 SKU를 미리 뺍니다.
  시스템 노드가 같은 `Ddsv7` 계열 16 vCPU를 쓰고 있어 96 vCPU는 처음부터 후보가 아니었습니다.
- 반대로 quota가 풀린 뒤에도 최대 10분은 이전 사용량으로 판단합니다. 리전 여유가 84 vCPU로
  돌아온 직후 1순위를 64 vCPU VM으로 바꿨지만 NAP는 이를 제외하고 대체 VM을 만들었습니다.
- 대체로 넘어간 뒤의 노드·Pod 준비 시간은 앞의 burst 결과와 같은 범위였습니다. 이 실측에서
  NAP가 줄인 시간은 약 20초입니다.

VM 생성 요청이 받아들여진 뒤 할당에 실패하는 경우는 재현하지 못해 소스로 동작을 확인했습니다.

| 구분 | 비동기 할당 실패 처리 |
|---|---|
| CAS 1.36 Azure provider | 생성에 실패한 VMSS VM을 기본적으로 Running으로 취급합니다. 실험 옵션 `EnableFastDeleteOnFailedProvisioning`이 꺼져 있으면 노드가 등록되지 않은 채 `max-node-provision-time`(기본 15분)까지 기다린 뒤 다른 풀을 시도합니다. AKS 관리형 CAS의 이 옵션 설정은 공개 문서에서 확인하지 못했습니다. |
| NAP (Karpenter provider Azure) | `AllocationFailure`, `ZonalAllocationFailure`, `SKUNotAvailable`, quota 오류를 구분해 해당 SKU·zone·용량 유형을 10분~23시간 동안 후보에서 빼고 다음 후보로 바로 재시도합니다. |

## 축소 속도는 autoscaler보다 설정이 결정했다

| 방식과 설정 | 축소 완료 |
|---|---|
| CAS, `scale-down-unneeded-time=1m` | 109~306초 (VM 제거 기준) |
| NAP, budget 30% (노드 7대를 2대씩) | 214~344초 |
| NAP, budget 100% | 56~92초 |
| NAP, 노드 1대로 모은 경우 | 86~95초 |

- CAS 기본값(`scale-down-unneeded-time` 10분)이면 노드가 빈 뒤 10분 이상 남습니다.
- CAS는 VM을 지운 뒤에도 Kubernetes node 객체가 `NotReady`로 약 5분 더 남았습니다.
  node 수로 축소를 판단하는 모니터링은 이 시간을 함께 셉니다. NAP는 VM 삭제와 node
  객체 삭제가 함께 끝났습니다.

## AzureLinux 이미지로 바꿔도 노드 준비 시간은 줄지 않았다

| 방식 | Ubuntu 첫 노드 Ready | AzureLinux 첫 노드 Ready |
|---|---|---|
| CAS | 78~90초 | 81~82초 |
| NAP | 81~87초 | 85~87초 |

이 조건(ephemeral OS, 이미지 pull이 거의 없는 Pod)에서는 OS 이미지를 바꿔 얻는
이점을 확인하지 못했습니다.

## 선택 기준은 속도보다 VM 크기 유연성과 운영 방식이다

| 요구 | 권장 |
|---|---|
| Pod가 수십 초 안에 떠야 함 | autoscaler 교체보다 여유 용량 확보. [확장 지연 줄이기](../scale-up-optimization/index.md) 참고 |
| 워크로드마다 VM 크기가 다르거나 큰 Pod가 가끔 생김 | NAP. 풀을 미리 만들지 않아도 됨 |
| 빈 노드를 빨리 정리해 비용을 줄여야 함 | NAP + budget 상향, 또는 CAS 축소 profile 조정 |
| 노드 준비 시간 편차가 작아야 함 | zone 범위를 좁히거나 regional VMSS를 쓰는 CAS 풀 |

## 단일 리전·짧은 시간대의 측정이라는 점이 결과를 제한한다

- 한 리전에서 약 2시간 동안 시나리오별로 1~5회 반복했습니다. VM 할당 지연은 리전,
  zone, SKU 재고, 시간대에 따라 달라집니다.
- NAP NodePool은 zone을 제한하지 않았고 CAS 풀은 zone을 지정하지 않았습니다. 두 쪽
  모두 같은 zone 조건으로 맞추면 꼬리 지연 차이는 달라질 수 있습니다.
- `pause` 컨테이너라 이미지 pull 시간이 거의 없습니다. 큰 이미지에서는 Pod 시작 시간이
  더 길어집니다.
- 대규모 확장(수십~수백 노드), Azure API throttling, VM이 만들어진 뒤의 할당 실패
  (AllocationFailed)는 재현하지 못했습니다. 할당 실패에서는 아래 절의 소스 분석처럼 CAS와
  NAP의 차이가 몇 분 단위로 커질 수 있습니다.
- 같은 날 v6 VM으로 처음 측정한 결과(`results/scale-out-v6-initial.csv`)는 CAS 축소를
  node 객체가 사라질 때까지로 재 과대 측정했고, 단계별 시간이 없어 이 문서의 결론에서
  제외했습니다.

## 공식 출처

- [Overview of Node Auto-Provisioning (NAP) in AKS](https://learn.microsoft.com/azure/aks/node-auto-provisioning)
- [Configure node pools for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools)
- [Configure node disruption policies for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption)
- [Use the cluster autoscaler in AKS](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [Cluster autoscaling in AKS overview](https://learn.microsoft.com/azure/aks/cluster-autoscaler-overview)
- [Cluster Autoscaler FAQ](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md)
- [Cluster Autoscaler 1.36 static_autoscaler.go](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/core/static_autoscaler.go)
- [Karpenter Settings](https://karpenter.sh/docs/reference/settings/)
- [AKS node bootstrap design for Karpenter provider Azure](https://github.com/Azure/karpenter-provider-azure/blob/main/designs/0001-aks-node-bootstrap.md)
- [Karpenter provider Azure offering error handlers](https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/instance/offerings/commonerrorhandlers.go)
- [Karpenter provider Azure quota provider](https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/quota/quota.go)
- [Karpenter provider Azure quota controller](https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/controllers/quota/controller.go)
- [Cluster Autoscaler 1.36 Azure scale set instance cache](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/cloudprovider/azure/azure_scale_set_instance_cache.go)
- [Cluster Autoscaler 1.36 Azure config](https://github.com/kubernetes/autoscaler/blob/cluster-autoscaler-release-1.36/cluster-autoscaler/cloudprovider/azure/azure_config.go)
