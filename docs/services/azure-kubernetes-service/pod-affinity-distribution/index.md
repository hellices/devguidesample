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
title: Pod Affinity를 이용한 AKS 워크로드 분산
description: AKS에서 Pod affinity와 anti-affinity로 워크로드를 분산하는 예제를 설명합니다.
technologies:
- kubernetes
tags:
- operate
redirect_from:
- guides/azure-kubernetes-service/pod-affinity-distribution/index.md
---

# ✅ AKS에서 Pod 분산 예제

**PodAntiAffinity + TopologySpreadConstraints 예시와 HPA 연계**

***

## 📌 Deployment YAML (PodAntiAffinity + SpreadConstraints)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 4
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchExpressions:
                    - key: app
                      operator: In
                      values:
                        - my-app
                topologyKey: "kubernetes.io/hostname"
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: "kubernetes.io/hostname"
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: my-app
      containers:
        - name: my-app
          image: myregistry.azurecr.io/my-app:latest
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
```

***

## ✅ HPA로 replica 수 조정

분산된 Deployment의 replica 수를 부하에 맞추는 HPA 예시, 동작 기본값과
KEDA를 이용한 요청 수 기반 확장은
[AKS HPA와 KEDA로 지표별 Pod 확장 방식 고르기](../hpa-keda-autoscaling/index.md)에서
다룹니다.

***

## 🔍 핵심 포인트

*   **PodAntiAffinity**: 동일 앱의 Pod가 같은 노드에 몰리지 않도록 설정.
*   **TopologySpreadConstraints**: Pod를 노드 단위로 균등하게 분산.
*   `ScheduleAnyway` 옵션으로 스케줄링 실패 방지.
*   라벨(`app: my-app`)은 Deployment와 Constraints 모두 동일하게 유지.
*   AZ 기반 분산: `topologyKey: topology.kubernetes.io/zone`로 변경 가능.
*   HPA와 함께 사용 시 노드 autoscaler(Cluster Autoscaler 또는 [NAP](../node-auto-provisioning/index.md)) 활성화 권장. NAP는 `ScheduleAnyway` spread도 우선 지키려고 노드를 더 만들 수 있습니다.

***

## 📚 참고 링크

*   **Kubernetes 공식 문서**
    *   [Pod Affinity & Anti-Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
    *   [TopologySpreadConstraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/)

*   **Microsoft Learn**
    *   [AKS 스케줄러 Best Practices](https://learn.microsoft.com/en-us/azure/aks/operator-best-practices-advanced-scheduler)
    *   [AKS Pod Affinity/Anti-Affinity Workshop](https://microsoft.github.io/k8s-on-azure-workshop/module-3/4_advanced_scheduling/2_affinity/index.html)

***
