# ✅ AKS에서 Pod 스케줄링 제어 Best Practice

**taint + toleration, affinity, nodeSelector 비교 및 조합**

***

## 📌 각 방식의 특징

| 방식                     | 강제성                           | 유연성 | 주요 목적                                 |
| ---------------------- | ----------------------------- | --- | ------------------------------------- |
| **nodeSelector**       | 강함 (단일 조건)                    | 낮음  | 특정 라벨이 있는 노드에만 배치                     |
| **nodeAffinity**       | 강제(required) 또는 선호(preferred) | 높음  | 복잡한 조건(AND/OR) 가능                     |
| **taint + toleration** | 매우 강함                         | 낮음  | 특정 노드에 Pod를 차단, toleration 있는 Pod만 허용 |

***

## ✅ 왜 taint + affinity를 같이 쓰나?

*   **taint**: 잘못된 Pod가 시스템 노드 풀에 들어가는 것을 원천 차단.
*   **affinity**: 시스템 Pod가 특정 노드 풀을 선호하거나 반드시 배치되도록 설정.
*   **조합 효과**: 안정성 + 유연성 → 운영 실수 방지 + 고가용성 확보.

***

## ✅ nodeSelector는 언제?

*   단순히 특정 노드 풀에 고정하고 싶을 때.
*   하지만 멀티 노드 풀 환경에서는 실수 가능성 → taint가 더 안전.

***

## ✅ Best Practice (AKS)

*   **시스템 노드 풀**: `CriticalAddonsOnly=true:NoSchedule` taint 적용.
*   **시스템 Pod**: toleration + nodeAffinity 설정.
*   **워크로드 노드 풀**: taint 없이 운영.

***

### ✅ Apply Taint to Node Pool (AKS CLI)
```yaml
# Add a taint to a node pool during creation
az aks nodepool add \
  --resource-group myRG \
  --cluster-name myAKS \
  --name systempool \
  --node-taints CriticalAddonsOnly=true:NoSchedule
```


### ✅ Add Taint to Existing Node
```yaml
kubectl taint nodes <node-name> CriticalAddonsOnly=true:NoSchedule
```

### ✅ Toleration & affinity을 kube-system 의 주요 리소스(DaemonSet/Deployment)에 적용합니다.

```yaml
spec:
  tolerations:
    - key: "CriticalAddonsOnly"
      operator: "Equal"
      value: "true"
      effect: "NoSchedule"
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: agentpool
                operator: In
                values:
                  - systempool
```

***

## 📚 참고 링크

*   <https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/>
*   [Node Affinity](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
*   <https://learn.microsoft.com/en-us/azure/aks/use-multiple-node-pools>

***
