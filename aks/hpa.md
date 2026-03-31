# ✅ AKS HPA(Horizontal Pod Autoscaler) 설정 가이드 및 Best Practice

**CPU/메모리 기반 자동 스케일링부터 커스텀 메트릭(KEDA)까지 실무 예시**

***

## 📌 HPA란?

HPA(Horizontal Pod Autoscaler)는 Kubernetes에서 Pod의 부하(CPU, 메모리, 커스텀 메트릭 등)에 따라 **Deployment/ReplicaSet의 Pod 수를 자동으로 조절**하는 리소스입니다.

> **권장 API 버전**: `autoscaling/v2` (Kubernetes 1.23+, AKS 기본 지원)
> `autoscaling/v1`은 CPU 단일 메트릭만 지원하므로 `v2` 사용 권장

***

## ✅ 1. 기본 HPA — CPU 기반 스케일링

### 전제 조건

- Pod에 **CPU `requests`** 설정 필수 (없으면 HPA 동작 불가)
- `metrics-server` 활성화 (AKS에서는 기본 포함)

### Deployment 예시

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: default
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
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

### HPA YAML (CPU 기반)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60   # 요청 대비 60% 초과 시 스케일 아웃
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60   # 스케일 아웃 전 안정화 대기(초)
      policies:
        - type: Pods
          value: 2
          periodSeconds: 60            # 60초마다 최대 2개씩 증가
    scaleDown:
      stabilizationWindowSeconds: 300  # 스케일 인 전 5분 대기 (플래핑 방지)
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60            # 60초마다 최대 10%씩 감소
```

***

## ✅ 2. 메모리 기반 HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa-mem
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70   # 요청 대비 70% 초과 시 스케일 아웃
```

> ⚠️ 메모리 기반 HPA는 스케일 인 시 메모리가 즉각 해제되지 않을 수 있어, `scaleDown.stabilizationWindowSeconds`를 넉넉히 설정하는 것이 중요합니다.

***

## ✅ 3. CPU + 메모리 복합 메트릭 HPA

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-app-hpa-combined
  namespace: default
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-app
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 70
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
```

> 📝 복합 메트릭 사용 시, HPA는 **각 메트릭에서 계산된 목표 replica 수 중 가장 큰 값**을 선택합니다.

***

## ✅ 4. KEDA를 이용한 커스텀 메트릭 기반 HPA

[KEDA(Kubernetes Event-driven Autoscaling)](https://keda.sh/)는 Azure Service Bus, Event Hub, HTTP 요청 수 등 다양한 이벤트 소스를 기반으로 스케일링할 수 있게 해주는 AKS 애드온입니다.

### KEDA 애드온 활성화 (AKS)

```bash
az aks update \
  --resource-group myRG \
  --name myAKS \
  --enable-keda
```

### Azure Service Bus 큐 기반 ScaledObject 예시

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: my-app-scaledobject
  namespace: default
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 1
  maxReplicaCount: 20
  cooldownPeriod: 300        # 스케일 인 전 대기 시간(초)
  pollingInterval: 30        # 메트릭 폴링 주기(초)
  triggers:
    - type: azure-servicebus
      metadata:
        queueName: my-queue
        namespace: my-servicebus-namespace
        messageCount: "10"   # 큐 메시지 10개당 Pod 1개
      authenticationRef:
        name: my-trigger-auth
```

### Azure Event Hub 기반 ScaledObject 예시

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: eventhub-scaledobject
  namespace: default
spec:
  scaleTargetRef:
    name: my-app
  minReplicaCount: 0         # 이벤트 없을 때 0으로 스케일 인 가능
  maxReplicaCount: 30
  triggers:
    - type: azure-event-hub
      metadata:
        consumerGroup: $Default
        unprocessedEventThreshold: "100"  # 처리 안 된 이벤트 100개당 Pod 1개
        activationUnprocessedEventThreshold: "10"
        storageConnectionFromEnv: STORAGE_CONNECTION_STRING
        eventHubConnectionFromEnv: EVENTHUB_CONNECTION_STRING
```

### HTTP 요청 기반 ScaledObject 예시 (http-add-on)

```yaml
apiVersion: http.keda.sh/v1alpha1
kind: HTTPScaledObject
metadata:
  name: my-app-http-scaledobject
  namespace: default
spec:
  hosts:
    - my-app.example.com
  targetPendingRequests: 100   # 대기 요청 100개당 Pod 1개
  scaleTargetRef:
    name: my-app
    port: 8080
  replicas:
    min: 1
    max: 10
```

***

## ✅ 5. HPA + Cluster Autoscaler 조합

HPA는 Pod 수를 늘리지만, **노드가 부족한 경우 Cluster Autoscaler(CA)와 함께 사용**해야 합니다.

```bash
# Cluster Autoscaler 활성화 (노드 풀 생성 시)
az aks nodepool add \
  --resource-group myRG \
  --cluster-name myAKS \
  --name workload \
  --enable-cluster-autoscaler \
  --min-count 2 \
  --max-count 10 \
  --node-count 2
```

```bash
# 기존 노드 풀에 Cluster Autoscaler 활성화
az aks nodepool update \
  --resource-group myRG \
  --cluster-name myAKS \
  --name workload \
  --enable-cluster-autoscaler \
  --min-count 2 \
  --max-count 10
```

### HPA + CA 동작 흐름

```
부하 증가
  └─▶ HPA: Pod 수 증가 요청
        └─▶ 노드 여유 있음 → 즉시 Pod 스케줄링
        └─▶ 노드 부족 (Pending Pod 발생)
              └─▶ Cluster Autoscaler: 노드 추가
                    └─▶ Pod 스케줄링 완료
```

> 💡 **VMSS Node Pool** 사용 시 CA 동작이 더 빠르고 안정적입니다.

***

## 🔍 Best Practice 정리

| 항목 | 권장 사항 |
|------|----------|
| **API 버전** | `autoscaling/v2` 사용 (다중 메트릭, behavior 지원) |
| **requests 설정** | 모든 컨테이너에 CPU/메모리 `requests` 반드시 설정 |
| **minReplicas** | 고가용성을 위해 최소 2 이상 권장 |
| **스케일 아웃 임계값** | CPU 기준 60~70% 권장 (너무 높으면 대응 지연) |
| **scaleDown 안정화** | `stabilizationWindowSeconds: 300` (5분) 이상 권장, 플래핑 방지 |
| **scaleUp 속도** | 급격한 트래픽 증가에 대비해 `scaleUp.policies` 로 증가 속도 제어 |
| **Cluster Autoscaler** | HPA와 반드시 함께 사용, 노드 자동 증설 필수 |
| **VPA와 혼용** | 동일 Deployment에 HPA(CPU/메모리)와 VPA를 함께 쓰지 않음 (충돌 위험) |
| **커스텀 메트릭** | 비즈니스 특성에 맞는 메트릭(큐 길이, HTTP RPS 등)에는 KEDA 사용 |
| **PDB 설정** | 스케일 인 시 서비스 중단 방지를 위해 PodDisruptionBudget 함께 설정 |

### PodDisruptionBudget 예시

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
  namespace: default
spec:
  minAvailable: 2        # 스케일 인/노드 드레인 중에도 최소 2개 Pod 유지
  selector:
    matchLabels:
      app: my-app
```

***

## 🔍 HPA 상태 확인 명령어

```bash
# HPA 상태 조회
kubectl get hpa -n default

# HPA 상세 정보 (이벤트, 현재 메트릭 포함)
kubectl describe hpa my-app-hpa -n default

# 실시간 Pod 수 변화 모니터링
kubectl get hpa my-app-hpa -n default -w

# KEDA ScaledObject 상태 확인
kubectl get scaledobject -n default
kubectl describe scaledobject my-app-scaledobject -n default
```

***

## 📚 참고 링크

- **Kubernetes 공식 문서**
  - [Horizontal Pod Autoscaling](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)
  - [HPA Walkthrough](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/)
  - [autoscaling/v2 API Reference](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/horizontal-pod-autoscaler-v2/)

- **Microsoft Learn**
  - [AKS에서 애플리케이션 자동 스케일링](https://learn.microsoft.com/ko-kr/azure/aks/concepts-scale)
  - [AKS KEDA 애드온](https://learn.microsoft.com/ko-kr/azure/aks/keda-about)
  - [AKS Cluster Autoscaler](https://learn.microsoft.com/ko-kr/azure/aks/cluster-autoscaler)
  - [AKS Best Practices — 스케줄러](https://learn.microsoft.com/ko-kr/azure/aks/operator-best-practices-advanced-scheduler)

- **KEDA**
  - [KEDA 공식 문서](https://keda.sh/docs/)
  - [KEDA Azure Service Bus 트리거](https://keda.sh/docs/scalers/azure-service-bus/)
  - [KEDA Azure Event Hub 트리거](https://keda.sh/docs/scalers/azure-event-hub/)

***
