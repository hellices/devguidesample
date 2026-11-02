---
title: "NAP·CAS 시나리오별 실측: 비용·VM 선택과 노드 재시작·Pod 이동"
description: 크기가 다른 Pod 혼합, 큰 노드 축소, 선호 VM quota 초과, 정책 제한, 같은 zone 확장 등 9개 시나리오에서 NAP와 VMSS Cluster Autoscaler를 AKS 1.36 v7 on-demand 환경으로 실측해 비교하고, 사전 예상과 결과를 대조합니다.
document_type: research
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [evaluate, optimize]
status: current
verification_status: verified
sources_checked_at: 2026-11-02
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
  - title: Use Scale-down Mode to delete/deallocate nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/scale-down-mode
  - title: Karpenter provider Azure quota provider
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/quota/quota.go
  - title: Karpenter provider Azure quota controller
    url: https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/controllers/quota/controller.go
  - title: Cluster Autoscaler FAQ
    url: https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md
  - title: Azure Retail Prices overview
    url: https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices
  - title: AKS release notes (CHANGELOG)
    url: https://github.com/Azure/AKS/blob/master/CHANGELOG.md
published_at: 2026-10-31
topic_order: 4
---

# NAP·CAS 시나리오별 실측: 비용·VM 선택과 노드 재시작·Pod 이동

같은 환경에서 NAP와 VMSS Cluster Autoscaler(CAS)를 9개 시나리오로 비교했습니다. NAP는
VM 크기 선택과 비용에서 앞섰고, CAS는 중지한 VM 재시작과 축소 중 Pod 이동에서 앞섰습니다.
같은 조건의 확장 속도는 비슷했습니다.

## 시나리오별 결과: CAS·NAP 비교

| 시나리오 | CAS | NAP | 유리한 쪽 |
|---|---|---|---|
| 크기가 다른 Pod 20개, 시간당 비용 | 풀 3개 $3.28~3.82(6~11대). 풀 1개는 16개만 배치 | 2대 $1.78 | NAP(46~54% 저렴) |
| 큰 VM에 Pod 3개만 남음, 비용 변화 | 32 vCPU 풀 그대로(0%) | 4 vCPU VM으로 교체(−87%) | NAP |
| 선호 VM quota 초과, 대체 결정 | 23초 | 2~3초 | NAP(전체 Pod Ready는 비슷) |
| VMSS 10대·노드 풀 10개 제한 정책, 0→40대 | 정책에 거부되어 Pod 40개 Pending | 단독 VM 40대 생성 | NAP(정책 환경) |
| 같은 zone 확장, 첫 노드 Ready | 69~82초 | 54~59초 | 비슷(차이 대부분은 확장 결정) |
| 같은 zone 확장, 모든 Pod Ready 중앙값 | 108초 | 106초 | 비슷 |
| 40대 동시 확장, 모든 Pod Ready | 198초 | 221초 | 비슷(1회) |
| 축소 중 옮겨진 Pod(20 → 3 Pod) | 1개(`D4ds_v7` 풀) | 3개 | CAS |
| 중지한 VM 재시작, 첫 노드 Ready | `Deallocate` 50초(새 VM 78~104초) | 기능 없음 | CAS |
| 다른 클러스터가 같은 계열 quota를 반납한 뒤 | quota를 미리 거르지 않아 바로 1순위 풀 시도(미측정) | 약 4분 뒤까지 대체 VM, 약 7.5분 뒤 1순위 VM(1회, 대조군 실패로 원인 미확정) | CAS(추정) |

## 측정 환경: East US 2, AKS 1.36.5, v7 on-demand

- 두 클러스터 모두 Azure CNI Overlay + Cilium, 시스템 풀 `Standard_D4ds_v7` × 2입니다.
- CAS profile은 `scan-interval=10s`, `scale-down-unneeded-time=1m`, `scale-down-delay-after-add=0m`입니다.
- NAP NodePool은 모두 `capacity-type: on-demand`, `arch: amd64`를 명시했습니다.
- 비용은 2026-10-31 Azure Retail Prices API의 East US 2 Linux on-demand 시간당 가격(USD)으로
  계산했습니다. VM 가격만 포함하고 디스크·네트워크는 제외했습니다.
- 리전 vCPU 한도(100) 때문에 시나리오를 순서대로 실행했고, 반복 횟수는 1~3회입니다.

## 크기가 다른 Pod 혼합: NAP 노드 2대, 비용 절반

6 vCPU·8 GiB Pod 4개, 1 vCPU·8 GiB Pod 6개, 0.5 vCPU·1 GiB Pod 10개를 동시에 만들었습니다.

| 구성 | 배치 | 노드 | 요청/용량 (CPU·메모리) | 시간당 비용 | 모든 Pod Ready |
|---|---|---|---|---|---|
| CAS, `D4as_v7` 풀 1개 | 16/20 | D4as × 6 | 0.46·0.62 | $1.09 | 6 vCPU Pod 4개 미배치 |
| CAS, D4as·E4as·F8as 풀 3개, expander `random`(AKS 기본값) | 20/20 | F8as × 6 / D4as × 6 + F8as × 5 | 0.73·0.48 / 0.55·0.36 | $3.28 / $3.82 | 92초 / 148초 |
| CAS, 같은 풀 3개, expander `least-waste` | 20/20 | F8as × 7 (2회 동일) | 0.62·0.41 | $3.82 | 96초 / 80초 |
| NAP, D·E·F v7(32 vCPU 이하) NodePool 1개 | 20/20 | D32as × 1 + D8als × 1 (2회 동일) | 0.88·0.64 | $1.78 | 139초 / 102초 |

- CAS는 확장할 때마다 풀 하나를 골라 그 VM 크기로 늘립니다. 남은 Pod는 다음 loop에서
  다른 풀로 갈 수 있어 random 2회차처럼 여러 풀이 섞이기도 합니다. 세 가지
  Pod를 모두 담을 수 있는 F8as 풀이 주로 선택돼 메모리 Pod까지 8 vCPU VM에 들어갔고,
  메모리용 E4as 풀은 한 번도 쓰이지 않았습니다.
- NAP는 Pod 묶음 전체를 보고 32 vCPU VM 1대와 8 vCPU VM 1대를 골랐습니다. 노드 용량 대비
  요청 비율이 가장 높고, 비용은 CAS 3개 풀보다 46~54% 낮습니다.
- 속도에서는 NAP가 앞서지 않았습니다. CAS가 8 vCPU VM 여러 대를 VMSS로 만드는 동안 NAP는
  32 vCPU VM을 기다렸습니다. 모든 Pod Ready는 CAS 80~148초, NAP 102~139초입니다.

## 큰 노드 축소: NAP만 VM을 작게 교체

Pod 20개(각 1 vCPU)를 띄운 뒤 3개로 줄이고 12분 동안 30초마다 기록했습니다.

| 구성 | 축소 전 | 축소 후 최종 | 비용 변화 | 도달 시간 | 옮겨진 Pod |
|---|---|---|---|---|---|
| NAP, v7 D 계열 자유 선택 | D32als × 1, $1.29/h | D4als × 1, $0.16/h | −87% | 약 194초 | 3 |
| CAS, `D32als_v7` 풀 | D32als × 1, $1.29/h | 그대로 | 0% | - | 0 |
| CAS, `D4ds_v7` 풀 | D4ds × 7, $2.28/h | D4ds × 1, $0.33/h | −86% | 약 224초 | 1 |

도달 시간과 비용은 node 객체 기준입니다. 이 실행의 기록에는 Ready 여부가 없어, CAS가 VM을
삭제한 뒤 node 객체가 NotReady로 남은 시간이 224초에 포함됐는지 구분할 수 없습니다. 실제 VM
과금이 줄어든 시점은 이보다 이를 수 있습니다. 공개한 `rightsize.sh`는 이후 이런 잔류 객체를
비용에서 빼고 `ready_nodes`·`removed_nodes` 열로 따로 기록합니다.

- CAS는 VM 크기를 바꾸지 못하므로 큰 VM 풀에 Pod가 조금만 남으면 그 노드를 계속 유지합니다.
- 작은 VM 풀이면 CAS도 빈 노드를 지워 비슷하게 줄입니다. NAP는 여기에 더해 큰 VM을 작은
  VM으로 교체합니다.

## 선호 VM quota 초과: 대체 결정 단계만 NAP 우세

[CAS·NAP 확장 시간 단계별 실측](../scale-out-benchmark/index.md)에서 측정한 결과입니다(각 2회). 시스템 풀이 같은
계열 16 vCPU를 쓰는 상태에서 96 vCPU VM을 1순위로 두자 CAS는 요청이 리전 quota 초과로 실패한
뒤 23초에 대체 풀로 넘어갔고, NAP는 1순위 VM을 시도하지 않고 2~3초 만에 대체 VM을
골랐습니다. NAP 이벤트에는 제외 이유가 없고 계열 quota 한도도 기록하지 않아, VM 계열 quota 사전 확인
때문이라는 해석은 소스 코드에 근거한 추정입니다. NAP가 앞선 단계는 대체 결정뿐입니다. 첫 노드 Ready는 CAS 66~76초, NAP 83초였고
모든 Pod Ready는 CAS 104~112초, NAP 96~130초였습니다.

## VMSS·노드 풀 수 제한 정책: CAS만 영향

실험 구독에는 관리 그룹 수준의 Azure Policy가 적용되어 있었습니다.

| 정책 | CAS에 미친 영향 | NAP에 미친 영향 |
|---|---|---|
| VMSS 인스턴스 10대 초과 배포 거부 | 2 vCPU 풀을 0→40대로 늘리는 요청이 거부되어 풀이 backoff, Pod 40개가 Pending으로 남음 | 단독 VM 40대 생성, 영향 없음 |
| AKS 노드 풀 10개 초과 거부 | 풀이 11개가 되자 클러스터 설정 변경이 거부됨 | NodePool은 AKS 노드 풀이 아니므로 영향 없음. 다만 2026-10-25 릴리스부터 NAP 클러스터에는 AKS 관리 `aksmanagednap` 노드 풀 1개가 추가됨 |

CAS는 VM 크기마다, 그리고 VMSS 크기 제한마다 노드 풀을 따로 만들어야 합니다. 같은 40대를
CAS로 만들 때는 10대 상한 풀 4개와 `balance-similar-node-groups=true`를 사용했습니다. 이 정책은
실험 구독의 조직 정책이지만, 거버넌스 정책이 있는 환경에서는 같은 차이가 생길 수 있습니다.

## 같은 zone 확장: NAP 첫 노드가 먼저 Ready, 차이는 대부분 확장 결정

이전 측정에서 NAP의 노드 준비가 더 오래 걸린 원인이 단독 VM 방식인지 확인하려고, 두 쪽 모두
zone 1에 `Standard_D4ds_v7` 노드를 만들게 하고 Pod 20개로 3회씩 측정했습니다.

| 구성 | 확장 결정 | 첫 노드 Ready | 마지막 노드 Ready | 모든 Pod Ready |
|---|---|---|---|---|
| CAS, zone 1 VMSS 풀 | 12~14초 | 69~82초 | 94~260초 | 102~271초 (중앙값 108) |
| NAP, zone `eastus2-1` | 2~5초 | 54~59초 | 86~122초 | 98~131초 (중앙값 106) |

- 가설과 반대로 NAP의 첫 노드가 중앙값 13초(56초 대 69초) 빨랐습니다. 이 중 약 8초는 확장
  결정 차이였고, 결정 → 첫 노드 Ready는 NAP 50~57초, CAS 55~70초로 비슷했습니다.
- 이전 측정의 차이는 NAP가 노드를 4개 zone(`eastus2-1`~`eastus2-4`)에 나눠 만들고 CAS 풀은 zone을 지정하지 않은 조건
  차이에서 왔을 가능성이 큽니다. 다만 다른 시간대의 3회 측정이라 원인을 단정하지 않습니다.
- 한두 대가 크게 늦어지는 꼬리 지연은 두 방식 모두 생겼습니다. CAS 3회차에서는 마지막 노드가
  260초에야 Ready가 됐습니다.

## 40대 동시 확장: 두 방식의 차이 작음

2 vCPU VM 40대가 필요한 Pod 40개를 만들었습니다(각 1회).

| 구성 | 확장 결정 | 첫 노드 Ready | 마지막 노드 Ready | 모든 Pod Ready |
|---|---|---|---|---|
| CAS, 10대 상한 풀 4개 + 풀 균형 | 3초 | 80초 | 180초 | 198초 |
| NAP, `Standard_D2ds_v7` | 3초 | 73초 | 196초 | 221초 |

- NAP는 3초에 NodeClaim 40개를 만들었고 모두 8초 안에 `Launched`가 됐습니다. 실패나 재시도는
  없었습니다(`results/nap-nodeclaim-phases.csv`).
- CAS는 한 loop에서 VMSS 4개를 차례로 10대씩 늘렸습니다. 이번에는 Pod가 이미 2초 넘게 지난
  시점에 loop가 돌아 대기 없이 3초 만에 결정했습니다.
- 1회 측정이라 23초 차이는 VM 준비 편차 범위로 봅니다.

## quota 정보 갱신 지연: 반납 뒤 1순위 VM 복귀 지연(원인 미확정)

실측 리전의 vCPU 한도는 100입니다. NAP는 리전 전체가 아니라 VM 계열별 quota
(`StandardDdsv7Family`)로 판단하며, 계열 한도 값은 따로 기록하지 않았습니다. `pref64`(weight 100, `Standard_D64ds_v7`)와 `alt`(weight 10,
`Standard_D4as_v7`, 다른 계열) NodePool을 두고, CAS 클러스터의 `Standard_D4ds_v7` 노드 6대로
같은 Ddsv7 계열 사용량을 16에서 40 vCPU로 올렸다가 반납했습니다. 각 시점에 1 vCPU Pod 20개를
만들어 NAP가 고른 NodePool만 확인하고 바로 지웠습니다.

| 시점 | 실제 Ddsv7 사용량 | NAP 선택 |
|---|---|---|
| 직전 시도의 점유를 반납한 직후(대조군, `pref64` 예상) | 16 | `alt` × 7 |
| 점유 11분 뒤 | 40 | `alt` × 7 (예상대로) |
| 반납 약 20초 뒤 | 16 | `alt` × 7 |
| 반납 약 235초(약 4분) 뒤 | 16 | `alt` × 7 |
| 반납 약 450초(약 7.5분) 뒤 | 16 | `pref64` × 1 |

반납 뒤 시각은 NodePool 선택을 읽은 시점입니다. 실측 당시 스크립트는 확인용 NodeClaim 정리가
끝난 뒤 시각(170·383·483초)을 기록했으므로, 스크립트 순서(확장 후 15초 대기, 45초 간격)로
선택 시점을 역산했습니다(±5초). 공개한 스크립트는 선택을 읽은 시각을 바로 기록합니다.

- 관측: quota가 풀린 뒤 적어도 약 4분 동안 1순위 VM을 시도하지 않고 대체 NodePool로 노드
  7대를 만들었고, 약 7.5분 뒤에는 1순위 VM으로 돌아왔습니다. 전환 시점은 그 사이입니다(1회).
- 이 관측만으로 원인을 quota 캐시라고 확정할 수 없습니다. 대조군이 예상한 `pref64` 대신 `alt`를
  골라 대조군 역할을 하지 못했고, 각 시점의 `StandardDdsv7Family` 한도와 NAP controller 로그를
  기록하지 않아 다른 선택 조건을 배제하지 못했습니다.
- 소스 코드 기준 해석: karpenter-provider-azure의 quota provider는 계열별 quota 사용량을 10분마다
  조회해 캐시합니다. NAP 자신이 만들고 지운 VM은 바로 반영하지만, 다른 클러스터나 VMSS가 쓰고
  반납한 quota는 다음 조회까지 반영하지 않습니다. 관측된 복귀 지연은 이 동작과 맞지만 실측으로
  인과를 확인하지는 않았습니다.
- quota가 남아 있는데도 부족하다고 판단하면 시도 없이 대체 VM으로 갑니다. 반대로 quota가
  부족한데도 충분하다고 판단하면 VM 생성이 실패하고 일반 오류 처리로 넘어갑니다.
- CAS는 quota를 미리 거르지 않고 매번 VMSS 확장을 시도합니다. 실패하면 그 풀을 처음 5분(최대
  30분, upstream 기본값) backoff하므로, 한 번 실패한 뒤에는 CAS도 수 분 동안 1순위 풀을 쓰지 않습니다. 이번
  시나리오처럼 실패 없이 quota만 바뀐 경우에는 CAS가 바로 반영합니다.
- 같은 구독에서 여러 클러스터나 VMSS가 같은 VM 계열 quota를 나눠 쓰면, 위 소스 코드 동작대로
  NAP가 고르는 VM 크기가 최대 10분 전 quota 상태를 따를 수 있습니다. 1순위 VM 계열에는 quota
  여유를 두는 편이 안전합니다. 원인을 확정하려면 시점별 계열 quota와 controller 로그를 함께
  기록하고 `pref64`를 정상 선택하는 대조군을 확보해 다시 측정해야 합니다.

## 축소 중 Pod 이동: VM 교체로 NAP가 더 많이 이동

큰 노드 축소 시나리오에서 NAP는 큰 VM을 작은 VM으로 바꾸면서 남은 Pod 3개를 모두 새 노드로 옮겼습니다. CAS의
`D4ds_v7` 풀은 빈 노드를 지우면서 1개를 옮겼고, `D32als_v7` 풀은 아무것도 옮기지 않았습니다.
재시작 비용이 큰 워크로드의 이동 자체를 막으려면 `karpenter.sh/do-not-disrupt` annotation을 붙이거나
`consolidationPolicy: WhenEmpty`로 빈 노드만 정리하게 합니다. PDB는 이동 중 동시에 내려가는 Pod 수만
제한하므로, 예를 들어 replica 3·`minAvailable: 2`이면 한 번에 하나씩 옮겨 결국 3개 모두 이동할 수 있습니다.

## 할당 해제 VM 재시작: CAS에만 있는 방식

CAS 풀의 `--scale-down-mode Deallocate`는 축소 때 VM을 지우지 않고 중지했다가 다시 시작합니다.
재시작 시 첫 노드 Ready는 50초(2회)로 새 VM(78~104초)보다 빨랐습니다. NAP에는 같은 기능이 없습니다.
자세한 측정은 [AKS 노드 확장 지연 단축](../scale-up-optimization/index.md)에 있습니다.

## CAS 운영상 약점: NotReady node 객체 잔류와 expander 기본값

- CAS가 축소를 결정한 노드는 약 75초 동안 `Ready,SchedulingDisabled`였다가 VM이 지워진 뒤
  `NotReady`로 중앙값 약 4분(노드 101대, 최대 7분) 더 남았습니다
  (`results/cas-node-object-linger.csv`). node 수로 상태를 보는 모니터링과 자동화가 이 시간을 함께 셉니다.
- AKS의 CAS expander 기본값은 `random`입니다. 여러 풀을 운영하면 expander와 풀 구성을 함께
  설계해야 합니다.

## 사전 예상과 실측: 맞은 예상과 빗나간 예상

실험 전에 세운 예상과 결과입니다. NAP나 VMSS 중 한쪽이 더 빠를 것이라는 예상은 같은 조건에서
대부분 확인되지 않았습니다.

| 시나리오 | 사전 예상 | 결과 |
|---|---|---|
| 크기가 다른 Pod 혼합 | NAP가 노드·비용 최소 | 맞음 |
| 큰 노드 축소 | NAP만 VM을 작게 교체 | 맞음 |
| 선호 VM quota 초과 | NAP가 빨리 대체 | 대체 결정 단계만 맞음 |
| VMSS·풀 수 제한 정책 | 사전 예상 없음 | 실험 중 발견 |
| 같은 zone 확장 | NAP VM 준비가 느림 | 틀림 |
| 40대 동시 확장 | NAP 꼬리 지연이 큼 | 차이 작음 |
| quota 정보 갱신 지연 | NAP가 최대 10분 선호 VM 제외 | 관측은 예상과 일치, 원인 미확정(1회, 대조군 실패) |
| 축소 중 Pod 이동 | NAP가 더 많이 옮김 | 맞음 |
| 할당 해제 VM 재시작 | CAS만 가능 | 맞음 |

## 선택 기준: 워크로드 모양, 축소 비용, 정책 환경

| 환경 | 권장 |
|---|---|
| Pod 크기가 다양하거나 자주 바뀜 | NAP. 이번 혼합 시나리오(2회)에서 풀 설계 없이 비용이 46~54% 낮음 |
| 큰 VM에서 부하가 크게 줄어드는 패턴 | NAP. VM 교체로 비용 절감, 이동 중 가용성은 PDB로 보호 |
| 선호 VM의 quota가 자주 부족함 | NAP. NAP가 캐시한 quota 정보가 부족 상태를 반영하고 있으면 다른 VM으로 빨리 대체. 다른 클러스터·VMSS가 같은 계열 quota를 바꾸면 최대 10분 전 정보로 판단할 수 있고, VM 생성 요청 뒤의 용량 부족(`AllocationFailed`) 대체 속도는 측정하지 않음 |
| VMSS 인스턴스 수를 제한하는 정책이 있음 | NAP(NAP 노드는 VMSS 인스턴스가 아님) |
| 같은 크기 Pod 위주, 풀 설계가 끝남 | CAS로도 충분. 속도 차이는 작음 |
| 축소·재확장이 잦고 노드를 빨리 되살려야 함 | CAS `Deallocate` 풀(Managed OS disk 필요, 중지 중에도 디스크 비용 발생) |
| 노드 이동을 최소화해야 하는 장시간 워크로드 | CAS 또는 NAP `WhenEmpty`·`karpenter.sh/do-not-disrupt`(PDB는 이동 중 가용성만 보호) |

## 측정 한계: 반복 횟수와 실험 환경

- 시나리오별 반복은 1~3회입니다. 속도 차이 수십 초는 VM 준비 편차 범위일 수 있습니다.
- VM 생성 요청이 받아들여진 뒤의 할당 실패(AllocationFailed)는 재현하지 못했습니다.
- VMSS 인스턴스 10대·AKS 노드 풀 10개 제한 정책은 실험 구독의 조직 정책입니다. 정책이 없는 구독에서는 CAS도 VMSS 하나로 40대까지
  늘릴 수 있습니다.
- 비용은 VM 시간당 가격만 비교했습니다. 예약 인스턴스, 절감 플랜, 디스크 비용은 포함하지 않았습니다.

## 공식 출처

- [Overview of Node Auto-Provisioning (NAP) in AKS](https://learn.microsoft.com/azure/aks/node-auto-provisioning)
- [Configure node pools for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools)
- [Configure node disruption policies for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption)
- [Use the cluster autoscaler in AKS](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [Cluster autoscaling in AKS overview](https://learn.microsoft.com/azure/aks/cluster-autoscaler-overview)
- [Use Scale-down Mode to delete/deallocate nodes](https://learn.microsoft.com/azure/aks/scale-down-mode)
- [Karpenter provider Azure quota provider](https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/providers/quota/quota.go)
- [Karpenter provider Azure quota controller](https://github.com/Azure/karpenter-provider-azure/blob/main/pkg/controllers/quota/controller.go)
- [Cluster Autoscaler FAQ](https://github.com/kubernetes/autoscaler/blob/master/cluster-autoscaler/FAQ.md)
- [Azure Retail Prices overview](https://learn.microsoft.com/rest/api/cost-management/retail-prices/azure-retail-prices)
- [AKS release notes](https://github.com/Azure/AKS/blob/master/CHANGELOG.md)
