---
title: Managed Prometheus 요청률로 KEDA 확장 시 1회 실측에서 부하 후 약 70–75초에 Pod가 늘기 시작했다
description: podinfo의 HTTP 요청률을 Azure Monitor managed service for Prometheus에서 조회해 KEDA Prometheus scaler로 확장하고, 확장·축소 시점과 NAP 노드 추가를 측정합니다.
document_type: lab
services: [azure-kubernetes-service, azure-monitor]
technologies: [kubernetes, keda, prometheus]
tags: [build, operate]
status: verified
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Integrations with Kubernetes Event-driven Autoscaling (KEDA) on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/keda-integrations
  - title: Securely scale your applications using the KEDA add-on and workload identity on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/keda-workload-identity
  - title: Create custom Prometheus scrape job from your Kubernetes cluster using CRDs
    url: https://learn.microsoft.com/azure/azure-monitor/containers/prometheus-metrics-scrape-crd
  - title: KEDA Prometheus scaler
    url: https://keda.sh/docs/2.19/scalers/prometheus/
  - title: KEDA scaling deployments, StatefulSets and custom resources
    url: https://keda.sh/docs/2.19/concepts/scaling-deployments/
  - title: Simplified application autoscaling with Kubernetes Event-driven Autoscaling (KEDA) add-on
    url: https://learn.microsoft.com/azure/aks/keda-about
last_verified: 2026-10-31
review_cycle_days: 90
estimated_time: 60m
cost: paid
cleanup_required: true
topic_order: 1
---

# Managed Prometheus 요청률로 KEDA 확장 시 1회 실측에서 부하 후 약 70–75초에 Pod가 늘기 시작했다

앱이 내보내는 Prometheus counter를 Azure Monitor managed service for
Prometheus(Managed Prometheus)로 수집하고, KEDA core에 포함된 `prometheus`
scaler가 Workload Identity로 조회해 replica를 정합니다. 초당 400건 부하의 1회
실측에서 Pod는 약 70–75초 뒤 늘기 시작해 약 140초에 목표 수에 도달했고, 새 Pod를
담을 NAP 노드가 준비되기까지 약 2분이 더 걸렸습니다.

## 앱 요청률이 Pod당 초당 50건을 넘으면 replica를 늘린다

- 지표: podinfo의 `http_request_duration_seconds_count` 중 `path="root"`(probe·scrape 제외)
- query: `sum(rate(http_request_duration_seconds_count{namespace="demo", path="root"}[1m]))`
- 목표: `threshold: 50` → replica = ceil(전체 RPS / 50), 1–20개
- 지원 범위: Prometheus scaler와 Managed Prometheus 조합은 AKS KEDA add-on 지원
  범위입니다. 자체 운영 Prometheus는 범위 밖입니다.

## AKS 1.36 클러스터에 Workload Identity, KEDA, Managed Prometheus를 순서대로 켠다

[HPA·KEDA 가이드](../index.md)의 sample `keda-request-scaling`을 사용합니다.

```bash
cd samples/keda-request-scaling
./infra/enable-addons.sh          # WI → KEDA → Managed Prometheus(Azure Monitor workspace) → AGC
./infra/setup-keda-identity.sh    # id-keda + keda-operator federated credential, 출력: KEDA_CLIENT_ID
```

Workload Identity는 `--enable-keda`보다 먼저 켜는 것을 권장합니다. 순서가 바뀌었으면
`keda-operator`를 재시작해야 환경 변수가 주입되며, `setup-keda-identity.sh`는 annotation 뒤
`keda-operator`를 재시작합니다.

## 비용은 노드, Azure Monitor workspace 수집량, 부하 시간에 비례한다

- AKS 시스템 노드 2대와 확장 중 NAP가 만드는 노드(이 실습에서는 최대 3대 추가)
- Azure Monitor workspace의 Prometheus 수집·조회량
- 실습 후 리소스 그룹을 삭제하면 과금이 멈춥니다.

## podinfo, PodMonitor, 읽기 권한, ScaledObject 순서로 배포한다

```bash
kubectl apply -f app/podinfo.yaml -f prometheus/podmonitor.yaml

# KEDA ID에 Azure Monitor workspace 읽기 권한
AMW_ID=$(az monitor account show -g $RG -n amw-autoscale-lab --query id -o tsv)
az role assignment create --assignee-object-id $(az identity show -g $RG -n id-keda --query principalId -o tsv) \
  --assignee-principal-type ServicePrincipal --role "Monitoring Data Reader" --scope $AMW_ID

EP=$(az monitor account show -g $RG -n amw-autoscale-lab --query metrics.prometheusQueryEndpoint -o tsv)
sed -e "s|<keda-client-id>|$KEDA_CLIENT_ID|" -e "s|<amw-query-endpoint>|$EP|" \
  prometheus/scaledobject.yaml | kubectl apply -f -
kubectl -n demo get scaledobject podinfo     # READY=True
```

PodMonitor는 OSS와 같은 스펙이지만 API group이 `azmonitoring.coreos.com/v1`입니다.
첫 데이터가 workspace에 보이기까지 1–2분이 걸립니다.

## 시스템 노드에서 k6로 초당 400건을 6분간 보낸다

```bash
./load/watch-replicas.sh > results/prometheus-rps.csv &   # 5초 간격, 기본 1200초 replica·노드 기록
kubectl apply -f load/k6-job.yaml                          # 1분 ramp-up → 400 RPS 5분 유지 → 30초 감소
```

## 1회 실측에서 첫 확장은 약 70–75초, 노드 준비가 약 2분을 더했다

부하 시작을 0초로 둔 1회 관측값입니다(2026-10-30, AKS 1.36.5, KEDA 2.19). 5초 간격 기록
(`results/prometheus-rps.csv`)이라 시점을 구간으로 적습니다.

| 시점 | 관측 |
|---|---|
| 0초 | k6 시작, 1분간 0 → 400 RPS |
| 약 70–75초 | 첫 확장 1 → 2 |
| 약 135–140초 | 목표 replica 9 도달 |
| 약 175–200초 | NAP가 워크로드 노드 1 → 4대로 확장 |
| 약 250초 | 9개 Pod 모두 Ready |
| 약 470초 | 부하 종료 후 query 값 0 |
| 약 660–745초 | HPA 300초 안정화 창 이후 9 → 1로 축소 |
| 약 990초 | NAP consolidation으로 워크로드 노드 1대로 정리 |

- k6 결과(`results/k6-summary.csv`): 137,999건, 실패 0건, p99 1.45 ms. podinfo는 가벼워 2개로도 처리할 수 있었지만,
  replica 수는 설정한 Pod당 RPS 목표를 그대로 따랐습니다.
- 확장 지연은 `rate(...[1m])` 창, 15초 scrape, 수집 지연, HPA sync 주기(기본 15초)가
  더해진 결과입니다. 1 → N 구간에서는 HPA가 sync 주기마다 KEDA metrics server를 거쳐
  query를 실행하므로, `useCachedMetrics`를 쓰지 않는 한 `pollingInterval`은 이 지연에
  영향을 주지 않습니다(`pollingInterval`은 0 ↔ 1 판단 주기). 더 빨리 반응해야 하면
  rate 창과 scrape 간격을 줄이되 흔들림이 커지는 것을 함께 확인합니다.

## ScaledObject가 Ready이고 HPA 목표가 RPS 값을 따라가면 성공이다

- `kubectl -n demo get scaledobject podinfo`: `READY=True`, 부하 중 `ACTIVE=True`
- `kubectl -n demo get hpa keda-hpa-podinfo`: `TARGETS`가 `<값>/50 (avg)`로 갱신
- 부하 중 replica가 `ceil(RPS/50)` 근처에 머물고 요청 실패가 없어야 합니다.

## 실습 후 ScaledObject와 리소스 그룹을 삭제한다

```bash
kubectl -n demo delete scaledobject podinfo; kubectl -n demo delete triggerauthentication azure-wi
kubectl -n demo delete job k6
az group delete -n $RG --yes --no-wait     # 전체 정리
```

## 인증·query 오류는 ScaledObject 이벤트에 먼저 나타난다

| 증상 | 원인과 조치 |
|---|---|
| `TARGETS`가 `<unknown>` | KEDA ID에 `Monitoring Data Reader`가 없거나 federated credential subject가 `system:serviceaccount:kube-system:keda-operator`가 아님 |
| `ScaledObject` 생성 실패 | 같은 Deployment에 HPA가 이미 있음. 기존 HPA 삭제 |
| query 값이 계속 0 | PodMonitor가 다른 namespace의 Pod를 선택하거나 port 이름 불일치. `up{job="demo/podinfo"}` 확인 |
| replica가 예상보다 많음 | probe·scrape 요청까지 세는 지표 사용. 앱 경로로 필터링 |

## 공식 참고 자료

- [Integrations with KEDA on AKS](https://learn.microsoft.com/azure/aks/keda-integrations)
- [KEDA add-on and workload identity](https://learn.microsoft.com/azure/aks/keda-workload-identity)
- [Create custom Prometheus scrape job using CRDs](https://learn.microsoft.com/azure/azure-monitor/containers/prometheus-metrics-scrape-crd)
- [KEDA Prometheus scaler](https://keda.sh/docs/2.19/scalers/prometheus/)
- [KEDA scaling deployments: caching metrics](https://keda.sh/docs/2.19/concepts/scaling-deployments/#caching-metrics)
