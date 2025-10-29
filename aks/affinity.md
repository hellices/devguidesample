# ✅ AKS에서 Pod 분산 예제

**PodAntiAffinity + TopologySpreadConstraints + HPA 예시**

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

## ✅ HPA YAML

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 4
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
```

***

## 🔍 핵심 포인트

*   **PodAntiAffinity**: 동일 앱의 Pod가 같은 노드에 몰리지 않도록 설정.
*   **TopologySpreadConstraints**: Pod를 노드 단위로 균등하게 분산.
*   `ScheduleAnyway` 옵션으로 스케줄링 실패 방지.
*   라벨(`app: my-app`)은 Deployment와 Constraints 모두 동일하게 유지.
*   AZ 기반 분산: `topologyKey: topology.kubernetes.io/zone`로 변경 가능.
*   HPA와 함께 사용 시 **Cluster Autoscaler 활성화** 권장.

***

## 📚 참고 링크

*   **Kubernetes 공식 문서**
    *   [Pod Affinity & Anti-Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
    *   [TopologySpreadConstraints](https://kubernetes.io/docs/concepts/scheduling-eviction/topology-spread-constraints/)

*   **Microsoft Learn**
    *   [AKS 스케줄러 Best Practices](https://learn.microsoft.com/en-us/azure/aks/operator-best-practices-advanced-scheduler)
    *   [AKS Pod Affinity/Anti-Affinity Workshop](https://microsoft.github.io/k8s-on-azure-workshop/module-3/4_advanced_scheduling/2_affinity/index.html)

***
