---
title: AKS CAS와 NAP 확장 실측에서 노드 준비 시간은 비슷했고 축소와 VM 선택에서 차이가 났다
description: VMSS Cluster Autoscaler와 NAP 클러스터에 같은 Pending Pod 20개를 만들어 첫 노드·전체 Pod 준비 시간, 노드 수, 축소 완료 시간을 3회씩 측정한 결과입니다.
document_type: research
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [evaluate, optimize]
status: current
verification_status: verified
sources_checked_at: 2026-10-30
official_sources:
  - title: Overview of Node Auto-Provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning
  - title: Configure node pools for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools
  - title: Configure node disruption policies for node auto-provisioning (NAP) nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption
  - title: Use the cluster autoscaler in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - title: Karpenter Disruption
    url: https://karpenter.sh/docs/concepts/disruption/
published_at: 2026-10-30
topic_order: 1
---

# AKS CAS와 NAP 확장 실측에서 노드 준비 시간은 비슷했고 축소와 VM 선택에서 차이가 났다

같은 Pending Pod를 만들었을 때 노드가 준비되는 시간은 VMSS Cluster
Autoscaler(CAS)와 NAP가 비슷했습니다. 차이가 크게 난 것은 **축소 속도**와
**VM 크기 선택**입니다. 기본 설정에서 NAP는 CAS보다 약 2.4배 빨리 노드를 정리했고,
VM 계열만 허용하자 4 vCPU 노드 7대 대신 32 vCPU 노드 1대를 골랐습니다.

| 시나리오 (중앙값, 3회) | 첫 노드 Ready | 전체 Pod Ready | 만든 노드 | 축소 완료 |
|---|---|---|---|---|
| CAS, `Standard_D4ds_v6` 풀 | 74초 | 99초 | D4 × 7 | 812초 |
| NAP, `Standard_D4ds_v6` 고정 | 87초 | 133초 | D4 × 7 | 335초 |
| NAP, D 계열 32 vCPU 이하 자유 선택 | 99초 | 116초 | D32pls_v6 × 1 | 87초 |

## 같은 Pending Pod를 두 autoscaler에 주고 확장·축소 시간을 비교했다

- 질문: 기존 VMSS 기반 CAS 대비 NAP가 실제로 얼마나 빨리 노드를 만들고 정리하는가?
- 부하: 1 vCPU·1 GiB를 요청하는 `pause` Pod 20개를 0에서 한 번에 생성한 뒤
  0으로 줄였습니다.
- 지표: 생성 명령부터 첫 워크로드 노드 Ready, 20개 Pod Ready, 축소 명령부터
  워크로드 노드 0개까지 걸린 시간(2초 간격 polling).

## 2026-10-30 East US 2의 AKS 1.36.5에서 같은 네트워크로 측정했다

| 항목 | CAS 클러스터 | NAP 클러스터 |
|---|---|---|
| Kubernetes | 1.36.5 | 1.36.5 |
| 네트워크 | Azure CNI Overlay + Cilium | 동일 |
| 시스템 풀 | `Standard_D4ds_v6` × 2, `CriticalAddonsOnly` taint | 동일 |
| 워크로드 노드 | user 풀 `Standard_D4ds_v6`, min 0 / max 10, profile 기본값 | NodePool `limits.cpu: 40`, `consolidateAfter: 0s`, budget 30% |

두 클러스터는 같은 리전에서 동시에 실행했고, 각 반복은 워크로드 노드가 0개인
상태에서 시작했습니다. 측정 스크립트와 원본 CSV는 sample의 `bench/bench.sh`,
`results/scale-out.csv`에 있습니다.

## 노드 준비 시간은 CAS가 조금 빨랐고 꼬리 지연은 VM 부팅이 결정했다

- 첫 노드 Ready는 CAS 70–74초, NAP 고정 SKU 87–88초였습니다. NAP는 Pending Pod를
  감지하고 몇 초 안에 NodeClaim을 만들었지만, VM이 준비되기까지의 시간이
  대부분을 차지했습니다.
- NAP 2회차의 전체 Pod Ready 253초는 노드 7대 중 1대가 다른 노드보다 2분 이상
  늦게 등록된 결과입니다. 여러 VM을 동시에 만들 때는 가장 느린 VM이 완료
  시간을 정합니다.
- 이 실측에서 NAP가 노드를 더 빨리 만든다는 근거는 찾지 못했습니다. Pod가
  기다리지 않게 하려면 노드 autoscaler의 종류보다 여유 replica, 미리 확장하는
  일정 같은 Pod 측 대비가 더 중요합니다.

## 축소는 기본값 차이 때문에 NAP가 약 2.4배 빨랐다

- CAS는 profile 기본값(`scale-down-delay-after-add` 10분, `scale-down-unneeded-time`
  10분)을 기다린 뒤 노드를 지워 775–872초가 걸렸습니다.
- NAP 고정 SKU는 빈 노드를 바로 정리 대상으로 잡았지만 disruption budget 30%
  때문에 7대를 2대씩 나누어 지웠고 219–349초가 걸렸습니다.
- NAP 자유 선택 시나리오는 노드가 1대라 46–115초 만에 정리됐습니다.
- CAS도 공식 문서의 aggressive profile(`scale-down-delay-after-add=0m`,
  `scale-down-unneeded-time=3m` 등)로 줄일 수 있으므로, 이 차이는 **기본 설정의
  차이**로 해석합니다.

## VM 계열만 허용하면 NAP는 큰 VM 한 대에 Pod를 모으고 Arm64도 고른다

`sku-family In [D]`, `sku-cpu Lt 33`만 지정하자 NAP는 세 번 모두 Arm64 기반
`Standard_D32pls_v6` 1대를 만들었습니다. 같은 20 vCPU 요청을 4 vCPU 노드
7대(28 vCPU) 대신 32 vCPU 노드 1대로 처리한 것입니다.

- 노드 수가 줄어 축소와 관리가 빨라지는 대신, 노드 1대 장애의 영향이 커집니다.
  가용성이 중요하면 topology spread나 `sku-cpu` 상한으로 노드를 나눕니다.
- `kubernetes.io/arch`를 지정하지 않으면 Arm64 SKU도 후보가 됩니다. AKS가 만드는
  `default` NodePool은 `amd64`로 제한되어 있지만, 직접 만든 NodePool은 이미지가
  multi-arch가 아니라면 `amd64`를 명시해야 합니다.

## 선택 기준은 속도보다 축소 비용과 VM 크기 관리 부담이다

| 요구 | 권장 |
|---|---|
| 노드 준비를 몇십 초라도 줄여야 함 | autoscaler 교체보다 여유 replica, 사전 확장, 빠른 이미지 pull을 먼저 검토 |
| 부하가 끝난 뒤 빈 노드 비용을 빨리 줄여야 함 | NAP의 consolidation과 budget 조정 |
| 워크로드마다 다른 VM 크기가 필요함 | NAP NodePool requirements로 허용 범위만 관리 |
| 특정 VM 크기만 써야 함 | NAP `sku-name` 고정 또는 기존 CAS 유지 |

## 단일 리전·단일 크기 부하라는 조건이 결과를 제한한다

- 한 리전, 한 시점, 반복 3회의 결과입니다. VM 할당 지연은 리전·시간대·SKU 재고에
  따라 달라집니다.
- 이미지 pull이 거의 없는 `pause` 컨테이너를 사용했습니다. 실제 앱은 이미지 크기와
  readiness 조건만큼 더 늦어집니다.
- CAS는 profile 기본값, NAP는 실측용 NodePool 설정으로 비교했습니다. 두 쪽 모두
  축소 관련 값을 바꾸면 축소 시간은 달라집니다.
- 일부 Pod만 줄어 노드가 덜 쓰이는 상황(underutilized consolidation)은 측정하지
  않았습니다.

## 공식 출처

- [Overview of Node Auto-Provisioning (NAP) in AKS](https://learn.microsoft.com/azure/aks/node-auto-provisioning)
- [Configure node pools for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools)
- [Configure node disruption policies for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption)
- [Use the cluster autoscaler in AKS](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [Karpenter Disruption](https://karpenter.sh/docs/concepts/disruption/)
