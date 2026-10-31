---
title: Cluster Autoscaler에서 NAP로 무중단 전환하고 불가능하면 새 클러스터로 옮기기
description: VMSS Cluster Autoscaler 클러스터를 NAP로 전환하는 세 가지 경로, PDB를 지키며 Pod를 순차 이동하는 절차, 실제 전환 리허설 결과와 롤백 방법을 설명합니다.
document_type: guide
services: [azure-kubernetes-service]
technologies: [kubernetes, karpenter]
tags: [migrate, operate]
status: current
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Migrate from cluster autoscaler to node auto-provisioning
    url: https://learn.microsoft.com/azure/aks/migrate-from-autoscaler-to-node-auto-provisioning
  - title: Enable or disable node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/use-node-auto-provisioning
  - title: Overview of networking configurations for node auto-provisioning (NAP) in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/node-auto-provisioning-networking
  - title: Update Azure CNI IPAM mode and data plane technology for Azure Kubernetes Service (AKS) clusters
    url: https://learn.microsoft.com/azure/aks/update-azure-cni
  - title: Zero-downtime migration to Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/zero-downtime-migration
  - title: Blue-green deployment of AKS clusters
    url: https://learn.microsoft.com/azure/architecture/guide/aks/blue-green-deployment-for-aks
  - title: Safely Drain a Node
    url: https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/
  - title: Container Lifecycle Hooks
    url: https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/
  - title: Karpenter Scheduling
    url: https://karpenter.sh/docs/concepts/scheduling/
last_verified: 2026-10-30
review_cycle_days: 180
applies_to: [AKS 1.36, Azure CLI 2.76+]
topic_order: 2
---

# Cluster Autoscaler에서 NAP로 무중단 전환하고 불가능하면 새 클러스터로 옮기기

NAP를 지원하는 네트워크·ID 구성이면 **같은 클러스터에서** CAS를 끄고 NAP를 켠
뒤 기존 VMSS 풀을 단계적으로 줄입니다. Pod는 PDB를 지키며 NAP 노드로 옮겨집니다.
구성이 맞지 않으면 먼저 클러스터 설정을 바꿀 수 있는지 보고, 바꿀 수 없으면
NAP를 켠 **새 클러스터를 만들어 트래픽을 단계적으로 넘깁니다.**

## 전환 경로는 NAP 지원 여부와 동시 운영 기간으로 고른다

| 상황 | 경로 | 특징 |
|---|---|---|
| Azure CNI Overlay/Node Subnet, 관리 ID, Linux 풀 | **경로 1: CAS 끄기 → NAP 켜기 → 풀 단계 축소** | 가장 단순. 전환 중 기존 풀은 고정 크기 |
| 워크로드별로 몇 주에 걸쳐 옮겨야 함 | **경로 2: CAS·NAP 동시 운영** | `AllowClusterAutoscalerAndNAP` feature flag 등록과 taint·toleration 관리 필요 |
| kubenet, Calico, 서비스 주체 | **먼저 클러스터 설정 변경 검토**, 불가하면 **경로 3: 새 클러스터 blue-green** | 설정 변경은 노드 재이미지를 동반. 새 클러스터는 비용이 두 배지만 롤백이 가장 빠름 |
| Azure CNI Pod Subnet 동적 할당 | **경로 3만 가능** | Overlay로 바꿀 수 없고 NAP도 지원하지 않음 |

클러스터 설정 변경에는 다음 조건이 붙습니다.

- **kubenet → Azure CNI Overlay:** `az aks update --network-plugin azure --network-plugin-mode overlay`로
  바꿀 수 있지만 되돌릴 수 없고, 모든 노드 풀이 동시에 재이미지됩니다. network policy가
  켜져 있으면 먼저 제거해야 하고, kubenet route table을 떼려면 **사용자 할당 관리 ID**가
  필요합니다(시스템 할당 ID는 지원하지 않음).
- **Calico → Cilium:** 데이터플레인을 Azure CNI Powered by Cilium으로 바꾸면 기존 network
  policy 엔진이 Cilium으로 교체됩니다. kubenet은 Overlay로 먼저 바꾼 뒤 별도 작업으로
  Cilium을 적용합니다.
- **순서:** NAP가 켜진 클러스터는 Cilium으로 업데이트할 수 없습니다. 네트워크 변경을 먼저
  끝내고 NAP를 켭니다.

이런 위험을 피하려면 경로 3을 택합니다.

## 전환 전에 Pod가 어느 노드로든 옮겨질 수 있는지 확인한다

- **requests:** NAP는 Pending Pod의 requests로 VM을 고릅니다. requests가 없으면
  너무 작은 노드에 몰립니다.
- **PDB와 replica:** replica 2개 이상과 `maxUnavailable: 1` 같은 PDB가 있어야
  drain 중에도 요청을 받습니다. replica 1개 + `minAvailable: 1`이면 eviction이 계속
  거부되어 drain이 진행되지 않습니다.
- **종료 대기:** Pod가 Service endpoint에서 빠지기 전에 종료되면 짧은 `503`이
  생깁니다. 아래 실측처럼 `preStop` 대기를 둡니다.
- **기존 풀 이름에 묶인 스케줄링:** `nodeSelector: agentpool: user`나 풀 전용 taint에
  의존하는 Pod는 NAP 노드로 갈 수 없습니다. 같은 label·taint를 NodePool
  template에 넣거나 selector를 바꿉니다.
- **노드 서브넷과 network policy:** 사용자 지정 서브넷이 필요하면 `AKSNodeClass`의
  `vnetSubnetID`를 먼저 설정합니다.
- **시스템 풀:** 시스템 풀은 그대로 두고 user 풀만 옮깁니다.

## 경로 1은 CAS를 끄고 NAP를 켠 뒤 기존 풀을 한 대씩 줄인다

```bash
# 1. CAS가 켜진 모든 풀의 CAS를 끕니다. 풀은 현재 노드 수로 고정됩니다.
#    하나라도 남아 있으면 AllowClusterAutoscalerAndNAP 없이는 NAP를 켤 수 없습니다.
for p in $(az aks nodepool list -g $RG --cluster-name $CLUSTER --query "[?enableAutoScaling].name" -o tsv); do
  az aks nodepool update -g $RG --cluster-name $CLUSTER -n $p --disable-cluster-autoscaler
done
az aks nodepool list -g $RG --cluster-name $CLUSTER --query "[?enableAutoScaling].name" -o tsv   # 빈 결과 확인

# 2. NAP 활성화. default·system-surge NodePool이 생성됩니다.
az aks update -g $RG -n $CLUSTER --node-provisioning-mode Auto
kubectl get nodepools.karpenter.sh

# 3. (선택) 기존 풀의 label·taint를 재현한 NodePool 적용
# 4. 기존 풀을 한 대씩 축소. AKS가 cordon·drain하며 PDB를 지킵니다.
for n in 2 1 0; do
  az aks nodepool scale -g $RG --cluster-name $CLUSTER -n user --node-count $n
  kubectl rollout status deploy/web -n app          # 모든 replica Ready 확인 후 다음 단계
done

# 5. 비어 있는 풀 삭제
az aks nodepool delete -g $RG --cluster-name $CLUSTER -n user
```

노드별로 더 세밀하게 제어하려면 풀을 줄이기 전에 직접 옮깁니다.
모든 기존 노드를 `kubectl cordon`으로 막아 새 Pod가 다시 들어오지 않게 한 뒤,
`kubectl drain <node> --ignore-daemonsets --delete-emptydir-data`를 한 대씩
실행합니다. drain은 eviction API를 쓰므로 PDB가 허용하는 만큼만 Pod를 내보내고,
쫓겨난 Pod는 Pending이 되어 NAP가 새 노드를 만듭니다.

## 실제 전환에서 기존 풀은 약 19분 만에 비었고 요청 실패는 NAP 활성화 중 1건이었다

azd로 만든 AKS 1.36.5 클러스터에서 user 풀(`Standard_D4ds_v7` 2대, on-demand, CAS)에 1 vCPU
Pod 6개, PDB `maxUnavailable: 1`을 두고 경로 1을 실행했습니다. 시스템 노드에서 0.2초마다
요청을 보냈습니다.

| 단계 | 소요 |
|---|---|
| CAS 비활성화 | 1분 12초 |
| NAP 활성화 | 6분 46초 |
| user 풀 2 → 1 → 0 | 5분 22초 + 4분 28초 |
| 빈 풀 삭제 | 35초 |

- 요청 5,605건 중 1건(0.02%)이 NAP 활성화 중 timeout으로 실패했습니다. 풀을 줄이는 동안에는
  실패가 없었습니다.
- 같은 앱을 NAP drift로 노드 6대 모두 교체하자 `preStop` 대기가 없을 때 요청 2,470건 중
  4건이 Pod 종료 순간의 `503`으로 실패했습니다. `preStop` 10초 대기를 넣고 rollout이 끝난 뒤
  다시 교체하자 3,730건 중 실패가 0건이었습니다.
- NAP는 Pod 6개를 on-demand 2 vCPU 노드 6대에 하나씩 배치했습니다. Karpenter는
  `whenUnsatisfiable: ScheduleAnyway` spread도 먼저 지키려고 노드를 더 만들기
  때문입니다. 노드 수를 줄이려면 spread 기준을 zone으로 바꾸거나 `maxSkew`를
  늘립니다.

종료 직전 요청 실패를 막으려면 Pod에 다음을 추가합니다. endpoint에서 빠지는
동안 기존 프로세스가 요청을 계속 받습니다. `sleep` 동작은 Kubernetes 1.30부터
기본으로 사용할 수 있습니다.

```yaml
spec:
  terminationGracePeriodSeconds: 30
  containers:
    - name: app
      lifecycle:
        preStop:
          sleep:
            seconds: 10
```

단계별 시각과 drift 교체 명령은 sample의 `results/migration-timeline.md`에 있습니다.

## 경로 2는 taint로 CAS 풀과 NAP 노드를 분리해 워크로드를 하나씩 옮긴다

CAS와 NAP는 모두 Pending Pod에 반응하므로 같은 Pod를 두고 둘 다 노드를 만들 수
있습니다. 공식 절차는 두 쪽을 taint로 완전히 나눕니다.

1. `AllowClusterAutoscalerAndNAP` feature flag를 등록합니다.
2. CAS 풀에 `autoscaling.azure.com/cas-block=true:NoSchedule` taint를 추가하고,
   당분간 남길 워크로드에 같은 toleration을 넣습니다.
3. `--node-provisioning-default-pools None`으로 NAP를 켜고, 직접 만든 NodePool
   template에 `autoscaling.azure.com/nap-block` taint를 넣습니다.
4. 옮길 워크로드의 toleration을 `cas-block`에서 `nap-block`으로 바꿔 배포합니다.
5. 모두 옮기면 CAS 풀을 삭제하고 두 taint·toleration을 제거합니다.

동시 운영을 오래 유지하면 예측하기 어려운 확장이 생길 수 있으므로 전환 기간에만
사용합니다.

## 경로 3은 NAP 클러스터를 새로 만들고 트래픽 비중을 단계적으로 옮긴다

클러스터를 바꾸면 Pod를 "이동"하는 것이 아니라 **새 클러스터에 같은 워크로드를
배포하고 요청을 넘기는** 방식이 됩니다.

1. **Green 클러스터 준비:** NAP, Azure CNI Overlay + Cilium, 관리 ID로 만들고
   인증서·Workload Identity·Key Vault·ACR 권한·관측 구성을 먼저 맞춥니다.
2. **같은 매니페스트 배포:** GitOps나 CI/CD로 blue와 같은 버전을 배포합니다.
   probe, requests, PDB가 있어야 NAP가 노드를 만들고 안전하게 정리합니다.
3. **데이터 경로 확인:** 상태는 가능하면 클러스터 밖(Azure DB, Storage)에 두고,
   PV가 있으면 CSI snapshot, Azure Files, Velero로 복사·동기화합니다.
4. **트래픽 비중 이동:** Front Door·Traffic Manager weight를 10 → 50 → 100%처럼
   올리고 단계마다 5xx 비율, p95 지연, 재시작 수를 확인합니다. DNS 기반 전환은
   TTL 동안 이전 클러스터로도 요청이 갑니다.
5. **이전 클러스터 정리:** weight 0에서 관측 기간을 지난 뒤 삭제합니다.

롤백은 weight를 blue로 되돌리는 것입니다. 큐 consumer나 batch는 새 클러스터에서
consumer를 켜기 전에 이전 클러스터의 consumer를 멈춰 중복 처리를 막습니다.

## NAP를 되돌리려면 NAP 노드를 먼저 비워야 한다

NAP는 NAP 노드가 남아 있는 동안 끌 수 없습니다. 옮겨 갈 자리를 먼저 만들어 두면
노드를 비우는 동안 Pod가 Pending으로 남지 않습니다.

1. 고정 크기 AKS 풀을 늘리거나 새로 만들고, 노드가 Ready이며 NAP 노드의 워크로드를
   담을 수 있는지 확인합니다.
2. 모든 NodePool의 `spec.limits.cpu`를 `0`으로 바꿔 새 NAP 노드 생성을 막습니다.
3. 모든 NodePool template에 `karpenter.azure.com/disable:NoSchedule` taint를
   추가합니다. NAP가 PDB와 disruption budget을 지키며 노드를 비웁니다.
4. `kubectl get nodes -l karpenter.sh/nodepool`이 비면
   `az aks update --node-provisioning-mode Manual`을 실행하고 필요하면 CAS를
   다시 켭니다. NAP 노드가 남으면 고정 크기 용량이 부족한 것이므로 풀을 더 늘립니다.

Learn 절차는 2·3단계 뒤에 고정 크기 풀을 늘리지만, 순서를 바꿔도 조건(노드 없음,
`limits.cpu: 0`)은 같고 Pending 구간만 줄어듭니다.

## 공식 참고 자료

- [Migrate from cluster autoscaler to node auto-provisioning](https://learn.microsoft.com/azure/aks/migrate-from-autoscaler-to-node-auto-provisioning)
- [Enable or disable NAP](https://learn.microsoft.com/azure/aks/use-node-auto-provisioning)
- [Networking configurations for NAP](https://learn.microsoft.com/azure/aks/node-auto-provisioning-networking)
- [Update Azure CNI IPAM mode and data plane](https://learn.microsoft.com/azure/aks/update-azure-cni)
- [Zero-downtime migration to AKS](https://learn.microsoft.com/azure/aks/zero-downtime-migration)
- [Blue-green deployment of AKS clusters](https://learn.microsoft.com/azure/architecture/guide/aks/blue-green-deployment-for-aks)
- [Kubernetes: Safely Drain a Node](https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/)
- [Kubernetes: Container Lifecycle Hooks](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/)
- [Karpenter Scheduling](https://karpenter.sh/docs/concepts/scheduling/)
