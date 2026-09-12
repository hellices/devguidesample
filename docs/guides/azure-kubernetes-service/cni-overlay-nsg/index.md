---
services:
- azure-kubernetes-service
official_sources:
- title: Azure Kubernetes Service documentation
  url: https://learn.microsoft.com/azure/aks/
document_type: guide
status: needs-review
verification_status: needs-review
sources_checked_at: 2026-09-12
last_verified: null
review_cycle_days: 180
applies_to:
- 공식 원문 재검토 필요
title: AKS CNI Overlay와 NSG 구성
description: AKS CNI Overlay를 사용할 때 NSG 규칙과 트래픽 경로의 주의점을 설명합니다.
technologies:
- kubernetes
tags:
- networking
- security
---

# ✅ AKS CNI Overlay 사용 시 NSG 설정 주의사항

**CNI Overlay에서 Pod IP 대역을 NSG에 허용해야 하는 이유**

***

## 📌 핵심 요약

AKS CNI Overlay 모드에서는 Pod IP가 VNet과 별도의 대역(Overlay 네트워크)에서 할당되지만, **NSG 규칙은 Overlay IP에도 적용됩니다**. 따라서 엄격한 NSG 정책을 운영하는 환경에서는 **Pod IP 대역을 명시적으로 NSG 규칙에 추가**해야 합니다.

***

## 🔍 문제 상황

### Enterprise 환경의 일반적인 시나리오

많은 기업 환경에서는 보안을 위해 VNet 내부 통신도 NSG로 강하게 제어합니다:

- ✅ VNet 내부 통신도 허용 IP 범위 지정
- ✅ 명시적으로 허용하지 않은 트래픽은 차단
- ✅ 네트워크 정책을 중앙에서 엄격하게 관리

### CNI Overlay의 특징

| 구분           | 설명                        | 예시           |
| ------------ | ------------------------- | ------------ |
| **Node IP**  | VNet 서브넷에서 할당            | 10.240.0.0/16  |
| **Pod IP**   | Overlay 네트워크에서 별도 할당 (VNet 외부) | 100.64.0.0/16 |

**문제**: Pod IP가 VNet과 다른 대역이지만, NSG는 Node와 Pod 간 통신에도 적용되므로 Pod 대역도 허용 규칙에 추가해야 합니다.

***

## ✅ 해결 방법

### 1. 현재 AKS 클러스터 구성 확인

```bash
# Pod CIDR 확인
az aks show \
  --resource-group myRG \
  --name myAKSCluster \
  --query "networkProfile.podCidr" -o tsv

# 예상 출력: 100.64.0.0/16
```

```bash
# Node 서브넷 확인
az aks show \
  --resource-group myRG \
  --name myAKSCluster \
  --query "agentPoolProfiles[0].vnetSubnetId" -o tsv

# 출력 예: /subscriptions/.../subnets/aks-subnet (10.240.0.0/16)
```

***

### 2. NSG 규칙 추가 (Node ↔ Pod 통신 허용)

#### Azure Portal 방식

1. **Azure Portal** → **Network Security Groups** → AKS 서브넷에 연결된 NSG 선택
2. **Inbound security rules** → **Add**
3. 다음과 같이 규칙 생성:

| 항목                | 값                           |
| ----------------- | --------------------------- |
| **Source**        | IP Addresses                |
| **Source IP**     | `100.64.0.0/16` (Pod CIDR)  |
| **Destination**   | IP Addresses                |
| **Destination IP**| `10.240.0.0/16` (Node 서브넷) |
| **Service**       | Custom                      |
| **Destination port ranges** | `*` (또는 필요한 포트)         |
| **Protocol**      | Any                         |
| **Action**        | Allow                       |
| **Priority**      | 1000                        |
| **Name**          | Allow-Pod-to-Node           |

4. **Outbound security rules**에도 동일하게 추가 (반대 방향):

| 항목                | 값                           |
| ----------------- | --------------------------- |
| **Source**        | IP Addresses                |
| **Source IP**     | `10.240.0.0/16` (Node 서브넷) |
| **Destination**   | IP Addresses                |
| **Destination IP**| `100.64.0.0/16` (Pod CIDR)  |
| **Service**       | Custom                      |
| **Destination port ranges** | `*` (또는 필요한 포트)         |
| **Protocol**      | Any                         |
| **Action**        | Allow                       |
| **Priority**      | 1001                        |
| **Name**          | Allow-Node-to-Pod           |

***

#### Azure CLI 방식

```bash
# NSG 이름 확인
NSG_NAME="aks-nsg"
RG_NAME="myRG"

# Inbound 규칙 추가 (Pod → Node)
az network nsg rule create \
  --resource-group $RG_NAME \
  --nsg-name $NSG_NAME \
  --name Allow-Pod-to-Node \
  --priority 1000 \
  --source-address-prefixes 100.64.0.0/16 \
  --destination-address-prefixes 10.240.0.0/16 \
  --destination-port-ranges '*' \
  --direction Inbound \
  --access Allow \
  --protocol '*'

# Outbound 규칙 추가 (Node → Pod)
az network nsg rule create \
  --resource-group $RG_NAME \
  --nsg-name $NSG_NAME \
  --name Allow-Node-to-Pod \
  --priority 1001 \
  --source-address-prefixes 10.240.0.0/16 \
  --destination-address-prefixes 100.64.0.0/16 \
  --destination-port-ranges '*' \
  --direction Outbound \
  --access Allow \
  --protocol '*'
```

***

### 3. Pod 간 통신 허용 (필요 시)

Pod 간 직접 통신이 필요한 경우:

```bash
# Pod 간 통신 허용 (Inbound)
az network nsg rule create \
  --resource-group $RG_NAME \
  --nsg-name $NSG_NAME \
  --name Allow-Pod-to-Pod-Inbound \
  --priority 1002 \
  --source-address-prefixes 100.64.0.0/16 \
  --destination-address-prefixes 100.64.0.0/16 \
  --destination-port-ranges '*' \
  --direction Inbound \
  --access Allow \
  --protocol '*'

# Pod 간 통신 허용 (Outbound)
az network nsg rule create \
  --resource-group $RG_NAME \
  --nsg-name $NSG_NAME \
  --name Allow-Pod-to-Pod-Outbound \
  --priority 1003 \
  --source-address-prefixes 100.64.0.0/16 \
  --destination-address-prefixes 100.64.0.0/16 \
  --destination-port-ranges '*' \
  --direction Outbound \
  --access Allow \
  --protocol '*'
```

> **참고**: Azure NSG의 기본 아웃바운드 규칙은 일반적으로 VNet 내부로의 아웃바운드 트래픽을 허용합니다. 그러나 **아웃바운드 트래픽도 NSG로 제한**하고 있는 엄격한 환경이라면 위와 같이 Inbound와 Outbound 규칙을 모두 추가해야 합니다.

***

### 4. 검증

```bash
# Pod에서 다른 Pod로 통신 테스트
kubectl run test-pod --image=busybox --rm -it --restart=Never -- /bin/sh

# Pod 내부에서
wget -O- http://<다른-pod-ip>:8080
ping <다른-pod-ip>
```

***

## 🔍 주의사항

### 1. 최소 권한 원칙

가능하면 모든 포트(`*`)를 열지 말고 **필요한 포트만 명시**:

```bash
# 예: HTTP(80), HTTPS(443), 사용자 정의 포트(8080)만 허용
--destination-port-ranges 80 443 8080
```

### 2. 멀티 노드 풀 환경

노드 풀마다 서브넷이 다르면 각각의 서브넷 CIDR을 NSG에 추가해야 합니다:

```bash
# 예시: 멀티 노드 풀 환경
# 노드 풀1 서브넷: 10.240.0.0/24
# 노드 풀2 서브넷: 10.240.1.0/24
# Pod CIDR: 100.64.0.0/16

# 각 노드 풀 서브넷 ↔ Pod CIDR 간 규칙 생성 필요
# 또는 더 큰 CIDR 범위(예: 10.240.0.0/16)로 통합하여 규칙 관리 단순화 가능
```

### 3. Kubernetes Network Policy와의 관계

- **NSG**: Azure 네트워크 레벨 (L3/L4)
- **Network Policy**: Kubernetes 레벨 (Pod 단위 제어)

둘 다 사용하면 **NSG → Network Policy 순서로 적용**되므로, NSG에서 차단되면 Network Policy와 무관하게 통신 불가.

***

## 🎯 Best Practice

### 권장 NSG 규칙 구성 (CNI Overlay 환경)

#### Inbound 규칙

| Priority | Name                     | Direction | Source            | Destination      | Ports | Action |
| -------- | ------------------------ | --------- | ----------------- | ---------------- | ----- | ------ |
| 100      | Allow-AzureLoadBalancer  | Inbound   | AzureLoadBalancer | *                | *     | Allow  |
| 1000     | Allow-Pod-to-Node        | Inbound   | 100.64.0.0/16     | 10.240.0.0/16    | *     | Allow  |
| 1001     | Allow-Node-to-Pod        | Inbound   | 10.240.0.0/16     | 100.64.0.0/16    | *     | Allow  |
| 1002     | Allow-Pod-to-Pod         | Inbound   | 100.64.0.0/16     | 100.64.0.0/16    | *     | Allow  |
| 4000     | Deny-All-Inbound         | Inbound   | *                 | *                | *     | Deny   |

#### Outbound 규칙

| Priority | Name                     | Direction | Source            | Destination      | Ports | Action |
| -------- | ------------------------ | --------- | ----------------- | ---------------- | ----- | ------ |
| 1001     | Allow-Node-to-Pod        | Outbound  | 10.240.0.0/16     | 100.64.0.0/16    | *     | Allow  |
| 1002     | Allow-Pod-to-Pod         | Outbound  | 100.64.0.0/16     | 100.64.0.0/16    | *     | Allow  |
| 1003     | Allow-Pod-to-Node        | Outbound  | 100.64.0.0/16     | 10.240.0.0/16    | *     | Allow  |
| 4001     | Deny-All-Outbound        | Outbound  | *                 | *                | *     | Deny   |

***

## 📚 참고 링크

*   [AKS Network Concepts - CNI Overlay](https://learn.microsoft.com/en-us/azure/aks/concepts-network)
*   [Azure CNI Overlay Networking](https://learn.microsoft.com/en-us/azure/aks/azure-cni-overlay)
*   [Configure Azure CNI Overlay](https://learn.microsoft.com/en-us/azure/aks/configure-azure-cni-overlay)
*   [Network Security Groups (NSG)](https://learn.microsoft.com/en-us/azure/virtual-network/network-security-groups-overview)
*   [Kubernetes Network Policies in AKS](https://learn.microsoft.com/en-us/azure/aks/use-network-policies)

***
