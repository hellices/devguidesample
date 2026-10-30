---
title: AKS NAP(Karpenter)로 Pending Pod에 맞는 VM을 고르고 빈 노드를 정리하기
description: AKS Node Auto-Provisioning이 VMSS 기반 Cluster Autoscaler와 다른 점, NodePool·AKSNodeClass 설정, 핵심 기능, 활성화 방법과 제약을 설명합니다.
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [operate, optimize]
status: current
verification_status: verified
sources_checked_at: 2026-10-30
official_sources:
  - title: Overview of Node Auto-Provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning
  - title: Enable or disable node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/use-node-auto-provisioning
  - title: Configure node pools for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools
  - title: Configure node disruption policies for node auto-provisioning (NAP) nodes in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption
  - title: Overview of networking configurations for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-networking
  - title: Migrate from cluster autoscaler to node auto-provisioning
    url: https://learn.microsoft.com/azure/aks/migrate-from-autoscaler-to-node-auto-provisioning
  - title: Use the cluster autoscaler in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/cluster-autoscaler
  - title: Karpenter NodePools
    url: https://karpenter.sh/docs/concepts/nodepools/
  - title: Karpenter Disruption
    url: https://karpenter.sh/docs/concepts/disruption/
last_verified: 2026-10-30
review_cycle_days: 180
applies_to: [AKS 1.36, Azure CLI 2.76+]
featured: true
---

# AKS NAP(Karpenter)로 Pending Pod에 맞는 VM을 고르고 빈 노드를 정리하기

Node Auto-Provisioning(NAP)은 AKS가 관리하는 [Karpenter](https://karpenter.sh)입니다.
Cluster Autoscaler(CAS)가 **미리 만든 VMSS 노드 풀의 노드 수**만 바꾼다면,
NAP는 Pending Pod의 requests를 보고 **VM 크기와 개수를 함께 정해** 노드를 만들고,
비거나 덜 쓰이는 노드를 스스로 정리합니다. AKS Automatic에는 NAP가 기본으로
켜져 있고, AKS Standard에서는 직접 켭니다.

## CAS는 풀의 노드 수를, NAP는 VM 크기와 수를 함께 정한다

| 항목 | Cluster Autoscaler (VMSS) | NAP |
|---|---|---|
| 확장 단위 | 노드 풀(VMSS) 하나당 VM 크기 하나 | Pod 요구에 맞춰 허용 범위 안의 여러 VM 크기 |
| 설정 위치 | `az aks nodepool`·autoscaler profile | Kubernetes CRD(`NodePool`, `AKSNodeClass`) |
| 판단 방식 | 주기 스캔(기본 10초) 후 풀 선택(expander) | Pending Pod 이벤트 기반 |
| 축소 | 10분 미사용 + 추가 후 10분 지연(기본값) | consolidation: 빈 노드 삭제, 여러 노드를 하나로 합치거나 더 저렴한 노드로 교체 |
| 노드 수명 관리 | 업그레이드 시 surge | drift 감지, `expireAfter`, disruption budget |
| 다른 VM 크기가 필요할 때 | 풀을 새로 추가 | `NodePool` requirements만 수정 |

## 실측에서 NAP는 노드를 더 빨리 만들지 않았고 더 빨리 정리했다

1 vCPU Pod 20개를 같은 조건으로 확장·축소한 중앙값입니다(AKS 1.36.5, 3회).

| 시나리오 | 첫 노드 Ready | 전체 Pod Ready | 만든 노드 | 축소 완료 |
|---|---|---|---|---|
| CAS, D4 풀 | 74초 | 99초 | D4 × 7 | 812초 |
| NAP, D4 고정 | 87초 | 133초 | D4 × 7 | 335초 |
| NAP, D 계열 자유 선택 | 99초 | 116초 | D32pls_v6(Arm64) × 1 | 87초 |

두 방식 모두 결국 Azure VM을 만들기 때문에 노드 준비 시간은 비슷했습니다.
NAP의 이점은 **빈 노드를 빨리 정리하고, 허용 범위 안에서 VM 크기를 골라 노드
수를 줄이는 것**입니다. 측정 방법과 해석의 한계는
[CAS와 NAP 확장·축소 실측](scale-out-benchmark/index.md)에 있습니다.

## NodePool은 허용할 VM 범위를, AKSNodeClass는 Azure 노드 설정을 정한다

NAP를 켜면 `default`(D 계열 on-demand)와 `system-surge` NodePool이 만들어집니다.
워크로드 성격별로 NodePool을 추가하고, 하나의 Pod가 하나의 NodePool에만
맞도록 requirements를 겹치지 않게 둡니다.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  limits:
    cpu: "200"                       # 이 풀이 만들 수 있는 vCPU 총량
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "20%"                 # 동시에 정리할 수 있는 노드 비율
  template:
    spec:
      expireAfter: Never
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: [amd64]            # 생략하면 Arm64 SKU도 후보가 됨
        - key: karpenter.sh/capacity-type
          operator: In
          values: [spot, on-demand]  # 둘 다 허용하면 spot 우선
        - key: karpenter.azure.com/sku-family
          operator: In
          values: [D, E]
        - key: karpenter.azure.com/sku-cpu
          operator: Lt
          values: ["33"]
      nodeClassRef:
        group: karpenter.azure.com
        kind: AKSNodeClass
        name: general
---
apiVersion: karpenter.azure.com/v1beta1
kind: AKSNodeClass
metadata:
  name: general
spec:
  imageFamily: Ubuntu        # 또는 AzureLinux
  osDiskSizeGB: 128
  # vnetSubnetID: 사용자 지정 VNet에서 노드 서브넷을 분리할 때 지정
```

## NAP 기능은 VM 선택, 비용 정리, 수명 관리로 나뉜다

| 기능 | 설정 | 동작 |
|---|---|---|
| VM 선택 | `sku-family`, `sku-name`, `sku-cpu`, `sku-memory`, zone, arch | 조건을 만족하는 SKU 중 Pending Pod를 담을 VM을 고름 |
| Spot 혼합 | `karpenter.sh/capacity-type` | spot과 on-demand를 함께 허용하면 spot 우선 |
| 상한 | `spec.limits.cpu/memory` | 상한에 닿으면 새 노드를 만들지 않음 |
| 풀 우선순위 | `spec.weight` | 여러 NodePool이 맞으면 weight가 큰 풀 선택 |
| Consolidation | `consolidationPolicy`, `consolidateAfter` | 빈 노드 삭제, 여러 노드를 하나로 합치기, 더 저렴한 SKU로 교체 |
| Disruption budget | `disruption.budgets` (`schedule`·`duration`) | 동시에 정리하는 노드 수와 시간대 제한. 미지정 시 10% |
| Drift | NodePool·AKSNodeClass 변경 | 설정과 달라진 노드를 budget 안에서 교체 |
| Expiration | `template.spec.expireAfter` | 지정 수명이 지난 노드를 강제로 교체 |
| 보호 | Pod·노드 annotation `karpenter.sh/do-not-disrupt: "true"` | 자발적 정리 대상에서 제외 |
| Static NodePool | `spec.replicas` | 수요와 관계없이 지정한 수의 NAP 노드 유지 |

## 새 클러스터는 `--node-provisioning-mode Auto`로 켜고 NodeClaim으로 확인한다

권장 네트워크는 Azure CNI Overlay와 Cilium입니다.

```bash
az aks create -g $RG -n $CLUSTER \
  --node-provisioning-mode Auto \
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium \
  --generate-ssh-keys

# 기존 클러스터
az aks update -g $RG -n $CLUSTER --node-provisioning-mode Auto

kubectl get nodepools.karpenter.sh,aksnodeclasses.karpenter.azure.com
kubectl get nodeclaims                       # NAP가 만든(또는 만드는 중인) 노드
kubectl get events -A --field-selector source=karpenter -w
```

`--node-provisioning-default-pools None`을 주면 기본 NodePool 없이 직접 정의한
풀만 사용합니다.

## 네트워크·ID 구성이 맞지 않으면 NAP를 켤 수 없다

- **지원 네트워크:** Azure CNI Overlay 또는 Azure CNI Node Subnet(선택적으로
  Cilium 데이터플레인). Kubenet, Azure CNI Pod Subnet 동적 할당, Calico network
  policy는 지원하지 않습니다.
- **ID:** 시스템 또는 사용자 할당 관리 ID. 서비스 주체 클러스터는 지원하지 않습니다.
- **기타:** Windows 노드 풀, IPv6 단일 스택 클러스터 미지원. NAP 클러스터는
  중지(stop)할 수 없고 생성 후 outbound type을 바꿀 수 없습니다. 사용자 지정
  VNet에서는 Standard Load Balancer가 필요합니다.
- **CAS와의 관계:** 같은 클러스터에서 함께 쓰려면 마이그레이션용
  feature flag가 필요합니다. 일반적으로는 CAS를 끄고 NAP로 전환합니다.

기존 CAS 클러스터를 옮기는 절차와 위 조건 때문에 전환할 수 없을 때의 재생성
전략은 [Cluster Autoscaler에서 NAP로 무중단 전환](cluster-autoscaler-migration/index.md)에
정리했습니다.

## 공식 참고 자료

- [Overview of Node Auto-Provisioning (NAP) in AKS](https://learn.microsoft.com/azure/aks/node-auto-provisioning)
- [Enable or disable NAP](https://learn.microsoft.com/azure/aks/use-node-auto-provisioning)
- [Configure node pools for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-node-pools)
- [Configure node disruption policies for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-disruption)
- [Networking configurations for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-networking)
- [Use the cluster autoscaler in AKS](https://learn.microsoft.com/azure/aks/cluster-autoscaler)
- [Karpenter NodePools](https://karpenter.sh/docs/concepts/nodepools/)
- [Karpenter Disruption](https://karpenter.sh/docs/concepts/disruption/)
