---
title: KEDA HTTP Add-on은 0개에서 첫 요청을 보류하며, 1회 실측에서 새 노드가 필요하면 첫 응답까지 약 2분 걸렸다
description: AKS KEDA add-on 위에 별도 설치한 KEDA HTTP Add-on으로 요청률 기반 확장과 scale-to-zero를 재현하고, cold start 시간과 burst 부하의 실패 조건을 측정합니다.
document_type: lab
services: [azure-kubernetes-service]
technologies: [kubernetes, keda]
tags: [build, operate]
status: verified
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Simplified application autoscaling with Kubernetes Event-driven Autoscaling (KEDA) add-on
    url: https://learn.microsoft.com/azure/aks/keda-about
  - title: Integrations with Kubernetes Event-driven Autoscaling (KEDA) on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/keda-integrations
  - title: KEDA HTTP Add-on Getting Started
    url: https://keda.sh/http-add-on/0.16/getting-started/
  - title: KEDA HTTP Add-on Installation
    url: https://keda.sh/http-add-on/0.16/operations/installation/
  - title: KEDA HTTP Add-on Configure Cold-Start Behavior
    url: https://keda.sh/http-add-on/0.16/user-guide/configure-cold-start/
  - title: KEDA ScaledObject specification
    url: https://keda.sh/docs/2.19/reference/scaledobject-spec/
last_verified: 2026-10-31
review_cycle_days: 90
estimated_time: 60m
cost: paid
cleanup_required: true
topic_order: 2
---

# KEDA HTTP Add-on은 0개에서 첫 요청을 보류하며, 1회 실측에서 새 노드가 필요하면 첫 응답까지 약 2분 걸렸다

KEDA HTTP Add-on은 요청이 지나가는 interceptor에서 요청률을 직접 세므로 앱이나
모니터링 수정 없이 HTTP 요청으로 확장하고 0개까지 줄일 수 있습니다. 기존 노드에
자리가 있으면 0개에서 첫 응답까지 1.6–4.7초(3회)였지만, NAP가 노드를 새로 만들어야
하면 약 111초(1회)가 걸렸습니다. Pod와 워크로드 노드가 모두 없는 상태에서 초당 400건
burst를 보낸 1회 실측에서는 계획한 요청의 약 22%가 timeout으로 실패하거나 아예
전송되지 못했고, `minReplicaCount: 1`로 바꾸자 실패가 사라졌습니다.

## HTTP Add-on은 AKS KEDA add-on에 포함되지 않는 별도 구성 요소다

| 구분 | 이 실습의 구성 | 지원 |
|---|---|---|
| KEDA core | AKS KEDA add-on (AKS 1.36 → KEDA 2.19) | AKS 지원 |
| HTTP Add-on 0.16.0 | Helm으로 `kube-system`에 설치한 interceptor, external scaler, operator | KEDA 커뮤니티, beta |

HTTP Add-on은 KEDA core와 같은 namespace에 설치하도록 안내하므로, AKS add-on이
KEDA를 두는 `kube-system`에 설치했습니다. 0.14부터는 `HTTPScaledObject` 대신
`InterceptorRoute`와 `external-push` trigger를 쓴 `ScaledObject`를 함께 만듭니다.

## 요청 경로에 interceptor를 넣고 Pod당 초당 50건을 목표로 둔다

```text
client ──► keda-add-ons-http-interceptor-proxy:8080 (Host: podinfo.example.com)
              │ 요청률 집계            └──► podinfo Service
              ▼
     external scaler ──► KEDA ──► HPA ──► podinfo replica (0–20)
```

운영에서는 Ingress·Gateway의 backend를 앱 Service가 아니라 interceptor proxy
Service로 바꿉니다.

## azd up이 KEDA add-on 클러스터와 HTTP Add-on 설치까지 준비한다

[Managed Prometheus 실습](../prometheus-rps/index.md)과 같은 sample·클러스터를 씁니다.
`azd up`의 postprovision hook이 `http-add-on/install.sh`로 HTTP Add-on 0.16.0을 `kube-system`에
설치하고 `values.yaml`로 interceptor·scaler·operator를 시스템 풀에 고정합니다. 비용은 노드와
실습 시간에 비례하며, 실습 후 `azd down`으로 리소스 그룹 전체를 삭제합니다.

## ScaledObject는 0개부터 시작하고 cooldown을 노드 준비보다 길게 둔다

postdeploy hook이 `http-add-on/scaling.yaml`을 적용합니다. 핵심 설정입니다.

```yaml
# InterceptorRoute
scalingMetric:
  requestRate:
    targetValue: 50     # Pod당 초당 요청
    window: 1m
---
# ScaledObject
minReplicaCount: 0      # min1 패턴은 hook이 1로 바꿔 적용
cooldownPeriod: 300     # 새 노드 준비 시간보다 길게
triggers:
  - type: external-push
    metadata:
      scalerAddress: keda-add-ons-http-external-scaler.kube-system:9090
      interceptorRoute: podinfo
```

## cold start와 burst 부하를 따로 측정한다

```bash
azd env set PATTERN "http-add-on-cold-start http-add-on-min0 http-add-on-min1"
azd hooks run postdeploy
```

- **`http-add-on-cold-start`:** replica가 0이 된 뒤 시스템 노드의 임시 curl Pod에서
  `http://keda-add-ons-http-interceptor-proxy.kube-system:8080/`로 `Host: podinfo.example.com`
  요청을 보냅니다. kube-system Service DNS는 클러스터 안에서만 해석되기 때문입니다. 작은
  keeper Pod로 워크로드 노드를 남긴 상태에서 3회, keeper를 지우고 워크로드 노드가 0대가 된
  뒤 1회 측정합니다.
- **`http-add-on-min0`, `http-add-on-min1`:** k6가 같은 interceptor 주소로 초당 최대 400건을
  보냅니다. min0은 replica가 0이 된 뒤 시작합니다.

## 기존 노드에서는 첫 응답이 5초 안쪽, 새 노드가 필요하면 약 111초였다

AKS 1.36.5, HTTP Add-on 0.16.0에서 `PATTERN=http-add-on-cold-start`로 측정했습니다
(`results/http-add-on-cold-start.txt`). 응답에는 `X-KEDA-HTTP-Cold-Start: true` header가 붙었습니다.

| 조건 | 첫 응답 | 결과 |
|---|---|---|
| replica 0, 기존 노드에 자리 있음 (3회) | 1.6–4.7초 | 200 |
| replica 0, 워크로드 노드 0대에서 NAP가 노드를 새로 생성 (1회) | 110.6초 | 200 |
| 각 cold start 직후 요청(warm, 4회) | 4–21 ms | 200 |

같은 초당 400건 부하를 두 설정으로 1회씩 보냈습니다. k6 부하 계획은 138,000건이며
결과는 `results/k6-summary.csv`, replica 변화는 `results/http-add-on-min0.csv`와
`results/http-add-on-min1.csv`에 있습니다.

| 설정 | 전송 요청 | 실패 | p95 | 관측 |
|---|---|---|---|---|
| `minReplicaCount: 0`, Pod·워크로드 노드 0개에서 시작 | 116,065 | 8,859 (전송 대비 7.63%) | 9.99초 | NAP 노드가 약 60초에 생기고 첫 Pod가 약 110초에 Ready 될 때까지 interceptor가 요청을 보류. k6 10초 timeout을 넘긴 요청이 실패했고, VU 한도(1,000)가 차서 21,934건(`dropped_iterations`)은 보내지 못함. 실패와 미전송을 합치면 계획의 약 22.3% |
| `minReplicaCount: 1` | 137,999 | 0 | 1.14 ms | 약 40초 후 첫 확장, 약 115초에 8개, 약 185초에 8개 Ready |

- interceptor를 거친 p99는 1.42 ms로, Service로 직접 보낸 [Managed Prometheus 실습](../prometheus-rps/index.md)의
  1 ms와 큰 차이가 없었습니다.
- `minReplicaCount: 0` 실행에서는 부하가 끝난 뒤 HPA 안정화 창(300초)이 지나 약
  720초에 1개로 줄었고, 약 10초 뒤 0개가 됐습니다. `cooldownPeriod`(300초)는 trigger가
  마지막으로 활성으로 보고된 때부터 세므로 HPA 안정화 창과 함께 흘렀습니다.

## 0개 운영은 첫 요청 대기를 감당할 수 있는 경로에만 쓴다

- 사용자 트래픽이 갑자기 몰리는 경로는 `minReplicaCount: 1` 이상을 두고, 야간·주말처럼
  유휴가 확실한 시간에만 0개로 줄입니다. 시간대별 최소값은 `cron` trigger를 함께
  쓰면 됩니다.
- 0개를 유지해야 하면 `coldStart.placeholder`로 즉시 안내 응답을 주거나
  `maxPendingRequests`로 보류 요청 수를 제한합니다.

## 판정 기준은 첫 요청 성공과 부하 중 실패율 0이다

- `kubectl -n demo get scaledobject podinfo`: `READY=True`, 유휴 시 replica 0
- 0개 상태의 첫 요청이 200으로 응답하고 cold start header가 `true`
- `minReplicaCount: 1` 부하에서 실패율 0%, replica가 `ceil(RPS/50)` 근처에 머묾

## 실습 후 azd down으로 리소스 그룹을 삭제한다

```bash
azd down --purge --force
```

클러스터를 남기고 HTTP Add-on만 지우려면 `ScaledObject`·`InterceptorRoute`를 삭제한 뒤
`helm uninstall http-add-on -n kube-system`과 CRD 삭제(`httpscaledobjects.http.keda.sh`,
`interceptorroutes.http.keda.sh`)를 실행합니다.

## cold start 요청이 끊기면 cooldown과 interceptor 위치를 확인한다

실습 중 실제로 겪은 문제입니다.

| 증상 | 원인 | 조치 |
|---|---|---|
| 새 노드가 필요한 cold start에서 응답이 오지 않음 | `cooldownPeriod: 60`이 노드 준비보다 짧아 Pod가 Ready 되기 전에 다시 0으로 줄어듦 | `cooldownPeriod`를 노드 준비 시간보다 길게(기본 300초) |
| 보류 중이던 요청 연결이 끊김 | interceptor Pod가 NAP 노드에 있다가 consolidation으로 옮겨짐 | Helm values로 interceptor·scaler·operator를 시스템 풀에 고정 |
| HTTP Add-on Pod가 예상과 다른 노드에 배치됨 | `capacity-type`을 지정하지 않은 사용자 NodePool은 spot을 먼저 고름 | 운영 NodePool에 `karpenter.sh/capacity-type: on-demand`를 명시하고, HTTP Add-on은 시스템 풀에 고정 |
| 0개에서 깨어나지 않음 | 요청이 interceptor를 거치지 않고 Service로 직접 감 | Ingress·Gateway backend를 interceptor proxy로 변경 |

## 공식 참고 자료

- [KEDA add-on overview (HTTP Add-on은 별도 배포)](https://learn.microsoft.com/azure/aks/keda-about)
- [Integrations with KEDA on AKS](https://learn.microsoft.com/azure/aks/keda-integrations)
- [KEDA HTTP Add-on Getting Started](https://keda.sh/http-add-on/0.16/getting-started/)
- [KEDA HTTP Add-on Installation](https://keda.sh/http-add-on/0.16/operations/installation/)
- [KEDA HTTP Add-on Configure Cold-Start Behavior](https://keda.sh/http-add-on/0.16/user-guide/configure-cold-start/)
- [KEDA ScaledObject specification](https://keda.sh/docs/2.19/reference/scaledobject-spec/)
