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
title: AKS 배포 Authorization 오류 진단
description: AKS 배포 과정의 Azure 권한 오류를 분류하고 진단하는 절차를 설명합니다.
technologies:
- kubernetes
- azure-cli
tags:
- authorization
- troubleshooting
---

# ✅ AKS 배포 시 Authorization 오류 트러블슈팅 가이드

**Pod 배포 시 LinkedAuthorizationFailed 오류 디버깅 및 해결 방법**

***

## 📌 핵심 요약

AKS에서 Pod를 배포할 때 `LinkedAuthorizationFailed` 오류가 발생하면, Azure 리소스 간 권한 연결 문제가 원인입니다. Kubernetes 이벤트 로그에서는 메시지가 잘려서 원인 파악이 어려울 수 있으므로, **Azure Monitor의 Kusto Query**를 활용하여 전체 오류 메시지를 확인해야 합니다.

***

## 🔍 문제 상황

### 증상

AKS 클러스터에 Pod를 배포할 때 다음과 같은 오류가 발생합니다:

```
Error: Code="LinkedAuthorizationFailed"
```

### Pod 이벤트 확인 시 문제점

`kubectl describe pod` 또는 `kubectl get events` 명령으로 확인하면 오류 메시지가 **잘려서** 표시됩니다:

```bash
kubectl describe pod <pod-name> -n <namespace>
```

출력 예시:

```
Events:
  Type     Reason             Age   From                Message
  ----     ------             ----  ----                -------
  Warning  FailedScheduling   10s   default-scheduler   Error: Code="LinkedAuthorizationFailed"
                                                        Message="The client 'xxxxxxxx-xxxx-' with object id 'xxxxxxxx-xxxx-'
                                                        has permission to perform action 'Microsoft.Network/virtualNetworks/write' on scope
                                                        '/subscriptions/<subscription-id>/resourceGroups/MyRG/providers/Microsoft.Network/virtualNetworks/my-vnet';
                                                        however, it does not have permission to perform action 'Microsoft.Network/ddosProtectionPlans/join/action'
                                                        on the linked scope(s) '/subscriptions/<subscription-id>/resourcegroups/ddos-protection-plan-rg/providers/...
```

> **참고**: Kubernetes 이벤트 메시지에는 길이 제한이 있어 긴 Azure 오류 메시지가 **잘려서 표시**됩니다. 이로 인해 정확한 원인 파악이 어려울 수 있습니다.

***

## 🔧 디버깅 방법

### 방법 1: kubectl events로 초기 확인

먼저 Pod와 관련된 이벤트를 확인합니다:

```bash
# 특정 Pod의 이벤트 확인
kubectl describe pod <pod-name> -n <namespace>

# 네임스페이스의 전체 이벤트 확인
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Warning 이벤트만 필터링
kubectl get events -n <namespace> --field-selector type=Warning
```

이 단계에서 `LinkedAuthorizationFailed` 오류가 보이면, 권한 문제가 원인임을 알 수 있습니다. 하지만 **전체 메시지를 보려면 Azure Monitor를 사용**해야 합니다.

***

### 방법 2: Azure Monitor Kusto Query로 상세 로그 확인

Azure Portal에서 Log Analytics를 통해 전체 오류 메시지를 확인할 수 있습니다.

#### 1. Azure Portal에서 Log Analytics로 이동

1. **Azure Portal** → **Log Analytics workspaces** 선택
2. AKS 클러스터와 연결된 워크스페이스 선택
3. **Logs** 클릭

#### 2. Kusto Query 실행

다음 쿼리를 사용하여 AKS 관련 권한 오류를 검색합니다:

```kusto
// AKS Activity Logs에서 Authorization 실패 찾기
AzureActivity
| where TimeGenerated > ago(24h)
| where (OperationNameValue contains "Microsoft.Compute" or OperationNameValue contains "Microsoft.Network")
| where ActivityStatusValue == "Failed"
| where Properties contains "LinkedAuthorizationFailed"
| project TimeGenerated, OperationNameValue, Caller, Properties
| order by TimeGenerated desc
```

또는 Container Insights가 활성화된 경우:

```kusto
// ContainerLog에서 오류 메시지 찾기
ContainerLogV2
| where TimeGenerated > ago(24h)
| where (LogMessage contains "LinkedAuthorizationFailed" or LogMessage contains "authorization")
| project TimeGenerated, PodName, ContainerName, LogMessage
| order by TimeGenerated desc
```

#### 3. Azure Activity Log에서 직접 확인

```kusto
// Azure Resource 작업 실패 로그 조회
AzureActivity
| where TimeGenerated > ago(24h)
| where ResourceGroup contains "MC_" // AKS 관리 리소스 그룹
| where ActivityStatusValue == "Failed"
| project TimeGenerated, OperationNameValue, ResourceId, Properties
| order by TimeGenerated desc
```

***

### 방법 3: Azure CLI로 Activity Log 확인

```bash
# 최근 24시간의 실패한 작업 조회 (Linux/GNU date 사용)
az monitor activity-log list \
  --resource-group MC_<resource-group>_<aks-cluster>_<region> \
  --status Failed \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ) \
  --query "[?contains(properties.message, 'LinkedAuthorizationFailed')]" \
  --output table

# macOS의 경우 다음 명령 사용
# --start-time $(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ)
```

***

## 📋 일반적인 원인 및 해결 방법

### 사례 1: DDoS Protection Plan 권한 부족

#### 오류 메시지

```
Message="The client 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' with object id 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
has permission to perform action 'Microsoft.Network/virtualNetworks/write' on scope
'/subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.Network/virtualNetworks/<vnet>';
however, it does not have permission to perform action 'Microsoft.Network/ddosProtectionPlans/join/action'
on the linked scope(s) '/subscriptions/<subscription-id>/resourcegroups/<ddos-rg>/providers/microsoft.network/ddosprotectionplans/<ddos-plan>'."
```

#### 해결 방법

AKS 서비스 주체 또는 Managed Identity에 DDoS Protection Plan에 대한 권한을 부여합니다:

```bash
# AKS Managed Identity의 Object ID 확인
AKS_IDENTITY=$(az aks show \
  --resource-group <aks-resource-group> \
  --name <aks-cluster-name> \
  --query identityProfile.kubeletidentity.objectId -o tsv)

# DDoS Protection Plan에 Network Contributor 역할 부여
az role assignment create \
  --assignee $AKS_IDENTITY \
  --role "Network Contributor" \
  --scope "/subscriptions/<subscription-id>/resourceGroups/<ddos-rg>/providers/Microsoft.Network/ddosProtectionPlans/<ddos-plan>"
```

***

### 사례 2: Disk Encryption Set 권한 부족

#### 오류 메시지

```
Message="The client 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx' with object id 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
has permission to perform action 'Microsoft.Compute/virtualMachineScaleSets/virtualMachines/write' on scope
'/subscriptions/<subscription-id>/resourceGroups/MC_<rg>_<aks>_<region>/providers/Microsoft.Compute/virtualMachineScaleSets/<vmss>/virtualMachines/0'; 
however, it does not have permission to perform action 'Microsoft.Compute/diskEncryptionSets/read'
on the linked scope(s) '/subscriptions/<subscription-id>/resourceGroups/<enc-rg>/providers/Microsoft.Compute/diskEncryptionSets/<des-name>'
or the linked scope(s) are invalid."
```

#### 해결 방법

Disk Encryption Set에 대한 읽기 권한을 부여합니다:

```bash
# AKS Managed Identity의 Object ID 확인
AKS_IDENTITY=$(az aks show \
  --resource-group <aks-resource-group> \
  --name <aks-cluster-name> \
  --query identityProfile.kubeletidentity.objectId -o tsv)

# Disk Encryption Set에 Reader 역할 부여
az role assignment create \
  --assignee $AKS_IDENTITY \
  --role "Reader" \
  --scope "/subscriptions/<subscription-id>/resourceGroups/<enc-rg>/providers/Microsoft.Compute/diskEncryptionSets/<des-name>"

# 추가로 Disk Encryption Set User 역할이 필요한 경우
az role assignment create \
  --assignee $AKS_IDENTITY \
  --role "Disk Encryption Set User" \
  --scope "/subscriptions/<subscription-id>/resourceGroups/<enc-rg>/providers/Microsoft.Compute/diskEncryptionSets/<des-name>"
```

***

### 사례 3: Private DNS Zone 권한 부족

#### 오류 메시지

```
Message="... does not have permission to perform action 'Microsoft.Network/privateDnsZones/join/action'
on the linked scope(s) '/subscriptions/<subscription-id>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/<private-dns-zone>'."
```

#### 해결 방법

```bash
# Private DNS Zone에 Contributor 역할 부여
az role assignment create \
  --assignee $AKS_IDENTITY \
  --role "Private DNS Zone Contributor" \
  --scope "/subscriptions/<subscription-id>/resourceGroups/<dns-rg>/providers/Microsoft.Network/privateDnsZones/<private-dns-zone>"
```

***

## ✅ 권한 부여 후 확인

### 1. 역할 할당 확인

```bash
# 할당된 역할 확인
az role assignment list \
  --assignee $AKS_IDENTITY \
  --all \
  --output table
```

### 2. Pod 재배포

권한 부여 후 Pod를 다시 배포하여 문제가 해결되었는지 확인합니다:

```bash
# Deployment 재시작
kubectl rollout restart deployment <deployment-name> -n <namespace>

# 또는 Pod 삭제하여 재생성
kubectl delete pod <pod-name> -n <namespace>

# 이벤트 확인
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | head -20
```

***

## 🔍 예방 및 Best Practice

### 1. 사전 권한 검토

AKS 클러스터 생성 전에 필요한 권한을 미리 확인합니다:

| 연결 리소스               | 필요한 권한                                   |
| ----------------------- | ------------------------------------------- |
| Virtual Network         | Network Contributor                          |
| Private DNS Zone        | Private DNS Zone Contributor                 |
| Disk Encryption Set     | Reader, Disk Encryption Set User             |
| DDoS Protection Plan    | Network Contributor                          |
| Container Registry      | AcrPull                                      |
| Key Vault               | Key Vault Secrets User (또는 Reader)          |

### 2. Managed Identity 사용 권장

서비스 주체(Service Principal) 대신 **Managed Identity**를 사용하면 권한 관리가 더 용이합니다:

```bash
# Managed Identity가 활성화된 AKS 클러스터 생성
az aks create \
  --resource-group <resource-group> \
  --name <aks-cluster-name> \
  --enable-managed-identity \
  --node-resource-group MC_<rg>_<aks>_<region>
```

### 3. Azure Policy로 권한 감사

Azure Policy를 사용하여 AKS 클러스터의 권한 구성을 감사합니다.

***

## 📚 참고 링크

* [AKS Managed Identity](https://learn.microsoft.com/en-us/azure/aks/use-managed-identity)
* [AKS Access and Identity](https://learn.microsoft.com/en-us/azure/aks/concepts-identity)
* [Azure RBAC 기본 역할](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles)
* [Azure Activity Log 쿼리](https://learn.microsoft.com/en-us/azure/azure-monitor/essentials/activity-log)
* [Kusto Query Language (KQL)](https://learn.microsoft.com/en-us/azure/data-explorer/kusto/query/)
* [AKS 문제 해결](https://learn.microsoft.com/en-us/troubleshoot/azure/azure-kubernetes/welcome-azure-kubernetes)

***
