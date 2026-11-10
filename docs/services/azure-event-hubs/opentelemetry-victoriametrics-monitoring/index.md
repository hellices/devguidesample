---
title: "Event Hubs 지표 수집 방식 비교 — OpenTelemetry Collector·VictoriaMetrics"
description: Event Hubs 플랫폼 지표를 외부 VictoriaMetrics로 가져오는 다섯 가지 방식(Azure Monitor 직접 조회, Metrics API pull 두 가지, Diagnostic Settings 스트림, Azure 내부 저장)의 지표 범위·지연·운영 차이를 실제 배포한 Grafana 대시보드와 측정값으로 비교합니다.
document_type: guide
services:
- azure-event-hubs
- azure-monitor
technologies:
- open-telemetry
- victoriametrics
- grafana
- kubernetes
- python
- bicep
tags:
- deploy
- operate
- evaluate
status: current
verification_status: verified
sources_checked_at: 2026-11-10
last_verified: 2026-11-10
review_cycle_days: 60
official_sources:
- title: Monitor Azure Event Hubs
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs
- title: Azure Event Hubs monitoring data reference
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference
- title: Diagnostic settings in Azure Monitor
  url: https://learn.microsoft.com/azure/azure-monitor/platform/diagnostic-settings
- title: Azure Monitor Metrics overview
  url: https://learn.microsoft.com/azure/azure-monitor/metrics/data-platform-metrics
- title: Log data ingestion time in Azure Monitor
  url: https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time
- title: How to migrate from the metrics API to the getBatch API
  url: https://learn.microsoft.com/azure/azure-monitor/metrics/migrate-to-batch-api
- title: Monitor Azure Functions and Event Hubs
  url: https://learn.microsoft.com/azure/architecture/serverless/event-hubs-functions/observability
- title: OpenTelemetry Collector Contrib azuremonitorreceiver (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azuremonitorreceiver
- title: OpenTelemetry Collector Contrib azureeventhubreceiver (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azureeventhubreceiver
- title: OpenTelemetry Collector Contrib prometheusremotewriteexporter (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/exporter/prometheusremotewriteexporter
- title: webdevops azure-metrics-exporter
  url: https://github.com/webdevops/azure-metrics-exporter
applies_to:
- Azure Event Hubs Premium namespace (1 PU에서 실측)
- Azure Event Hubs Standard namespace (지연 측정)
- 기존 Event Hubs Dedicated cluster용 수집 profile (문서 기반, runtime 미검증)
- OpenTelemetry Collector Contrib 0.165.0
- VictoriaMetrics Operator 0.75.2, VictoriaMetrics v1.155.0, Grafana OSS 13.3.0
---

# Event Hubs 지표 수집 방식 비교 — OpenTelemetry Collector·VictoriaMetrics

## 핵심 흐름: 수집 방식 5가지와 실측 결과 { #message }

Event Hubs의 CPU·memory·요청·처리량 지표는 Azure Monitor가 1분 단위로 자동 수집하므로,
외부 VictoriaMetrics로 모을 때 정할 것은 그 지표를 꺼내 오는 방식입니다. 이 topic은 다섯
방식을 비교하고, 그중 세 방식(②·③·④)을 하나의 OpenTelemetry Collector로 실제 Azure에
배포해 같은 구간의 Azure Monitor 조회값과 대조했습니다.

![Event Hubs 지표 수집 방식 5가지. Event Hubs namespace의 플랫폼 지표가 Azure Monitor에 1분 단위로 쌓이고, ① Azure Monitor 직접 조회, ② Metrics API를 OpenTelemetry azuremonitorreceiver가 60초마다 조회, ③ Metrics API를 azure-metrics-exporter가 조회하고 Collector가 scrape, ④ Diagnostic Settings가 telemetry Event Hub로 보내고 azureeventhubreceiver가 읽음, ⑤ Diagnostic Settings가 Log Analytics·Storage에 저장. ②·③·④는 VictoriaMetrics로 모임](images/collection-methods.svg)

아래는 Premium 1 PU namespace에 producer 200 events/s 부하를 10분 준 구간(2026-11-09
19:35–20:00 UTC)을 이 구성으로 수집해 agent가 만든 Grafana 대시보드입니다.

![Event Hubs 관측 대시보드. Premium CPU·Memory gauge와 추이, 요청·throttle 합계 stat, PU당 분당 message·byte 막대, partition별 peak lag와 누적 lag 영역, source_path·delivery_path별 series 수와 분당 sample 수 표, scrape와 remote write의 IncomingMessages 시차, Metrics API와 Diagnostic Settings의 IncomingMessages·CPU 비교, Collector 실패 0건](images/grafana-dashboard.png)

같은 25분 구간을 Azure Monitor에서 직접 조회한 값과 비교하면, 원본 timestamp를 유지하는
remote write 경로는 ②·④ 모두 합계가 정확히 일치했습니다.

| 지표 | Azure Monitor 직접 조회 | ② Metrics API → remote write | ④ Diagnostic Settings → remote write |
|---|---:|---:|---:|
| `IncomingMessages` | 120,200 | 120,200 (25/25분 일치) | 120,200 (값이 있는 11분) |
| `OutgoingMessages` | 122,400 | 122,400 (25/25분 일치) | 122,400 (값이 있는 17분) |
| `IncomingRequests` | 1,538 | 1,538 (25/25분 일치) | 1,538 |
| `ThrottledRequests` | 0 | 0 (25/25분 일치) | 수신 안 됨 |

## 방식별 주요 차이: 지표 범위·dimension·지연·운영 { #metrics }

외부 TSDB로 지표를 모을 때 기본은 ② Metrics API pull이고, ④·⑤ Diagnostic Settings는
처리량 지표를 로그 파이프라인과 함께 보내야 할 때의 보조 경로입니다. 다섯 방식 모두 원본은
Azure Monitor의 같은 1분 집계이므로, 차이는 꺼내는 방식에서 생깁니다.

| 방식 | 지표 범위·dimension | 지연(실측) | 운영·권한 | 맞는 용도 |
|---|---|---|---|---|
| ① Azure Monitor 직접 조회 | 모든 지표, dimension 분할 | 약 1분 30초(Metrics API 조회 가능 72–102초) | 추가 구성 없음 | portal 확인, Azure Monitor 경보 |
| ② Metrics API — `azuremonitorreceiver` | 모든 지표, dimension 분할 | 약 4분(이벤트 → VictoriaMetrics 230–232초) | Collector 운영, 대상 namespace의 Monitoring Reader. 다수 리소스는 batch API(구독 범위 권한)로 호출 수 절감 | 외부 TSDB의 기본 경로 |
| ③ Metrics API — `azure-metrics-exporter` | 모든 지표, dimension 분할 | 측정 안 함(②와 같은 Metrics API 조회에 scrape 주기 추가) | exporter 컨테이너 추가, ②와 같은 권한·호출 제약 | Prometheus exporter 중심 환경 |
| ④ Diagnostic Settings → Event Hub | 내보내기 가능한 지표만, dimension 합산, 값이 있는 분만 | ②보다 약 4분 더 늦음, 설정 직후 최대 90분 | telemetry Event Hub(같은 리전)와 receiver checkpoint | 로그와 같은 스트림으로 외부 연동 |
| ⑤ Diagnostic Settings → Log Analytics·Storage | ④와 같음 | ④와 비슷 | workspace·storage 비용 | KQL 분석, 장기 보관 |

- **CPU·memory·성공·throttle과 dimension별 분석이 필요하면 ②**를 씁니다. 이 지표는
  Diagnostic Settings로 오지 않거나 dimension이 합쳐져 옵니다([지표 차이](#receivers)).
- **Prometheus exporter 중심으로 운영하면 ③**이 같은 데이터를 줍니다. 실습에서는 ②를 끄고
  ③으로 전환해 Premium 지표 9개 × 집계 3개, 27개 series를 받았습니다.
- **④·⑤는 경보나 용량 판단의 기준으로 삼지 않습니다.** 0값 구간이 비고 지연이 길며,
  설정 직후 수십 분 동안 비어 있을 수 있습니다.

## 지연 시간: Azure Monitor + OpenTelemetry Collector { #latency }

Azure Monitor를 원본으로 하는 방식은 초 단위 신호가 아닙니다. Premium 1 PU namespace로 이벤트를
보낸 뒤 Azure Monitor Metrics API에서 보이기까지 약 1분 30초, OpenTelemetry Collector를 거쳐
VictoriaMetrics에 저장되기까지 약 4분이 걸렸습니다.

![이벤트 전송 후 조회 가능까지 걸린 시간. Premium 1 PU는 Metrics API 72–102초(중앙값 92), VictoriaMetrics 230–232초. Standard 1 TU는 Metrics API 81–151초(중앙값 115), VictoriaMetrics 221–281초(중앙값 250). Premium의 Collector 구간은 130–160초](images/metric-latency.svg)

| 구간 | Premium 1 PU (15회) | Standard 1 TU (20회) |
|---|---|---|
| 이벤트 → Metrics API 조회 가능 | 72–102초 (중앙값 92) | 81–151초 (중앙값 115) |
| Metrics API → VictoriaMetrics(Collector 구간) | 130–160초 (중앙값 140) | 120–150초 (중앙값 130) |
| 이벤트 → VictoriaMetrics 저장 | 230–232초 | 221–281초 (중앙값 250) |
| bin timestamp | 이벤트를 보낸 분보다 1분 뒤 | 2분 단위 |

- **Collector 구간이 수집 주기(60초)의 두 배를 넘습니다.** receiver는 60초마다 최근 1분(`PT1M`)
  창만 조회하므로 bin이 Azure Monitor에 나타난 뒤 다음 조회 창에 들어올 때까지 기다릴 가능성이
  큽니다. VictoriaMetrics에 저장된 값은 모두 Azure Monitor의 최종값과 같았습니다.
- **대시보드의 마지막 sample 경과 시간은 bin timestamp 기준입니다.** 실습 환경에서 194–213초로
  보인 값이 이 측정의 범위와 같습니다. 같은 기준으로 ④ Diagnostic Settings 경로는 434–513초로
  ②보다 약 4분 더 늦었습니다.
- **용량·추세·분 단위 경보에는 충분하지만 초 단위 감지에는 맞지 않습니다.** 빠른 감지가 필요하면
  Event Hubs·client에서 직접 얻는 신호를 함께 씁니다. checkpoint 기반 lag는 같은 실습에서 38초
  안에 반영됐습니다([추가](#events)).

측정 방법과 원본 값은 [실습의 지연 측정](lab/index.md#latency)에 있습니다.

## Azure Monitor와 Diagnostic Settings의 지표 차이 { #receivers }

Azure Monitor(Metrics explorer·Metrics API)는 Learn `Microsoft.EventHub/namespaces`
지표표의 38개 지표를 모두 dimension과 함께 조회할 수 있지만, Diagnostic Settings는 일부만
dimension을 합쳐 내보냅니다. 실제 스트림은 지표표의 DS Export 값과도 달랐으므로 두 기준을
함께 적었습니다. 실측은 Premium 1 PU 환경(2026-11-09 19:35–20:00 UTC)에서 telemetry Event
Hub로 받은 지표입니다.

| 지표(REST API 이름) | Azure Monitor dimension | Diagnostic Settings: DS Export(Learn) → 실측 |
|---|---|---|
| `SuccessfulRequests`, `ThrottledRequests`, `ServerErrors`, `UserErrors`, `QuotaExceededErrors` | `EntityName`, `OperationResult` | **Azure Monitor에서만.** No → 없음. 성공 수는 레거시 `SUCCREQ`로만 도착 |
| `CaptureBacklog`, `CapturedBytes`, `CapturedMessages`, `ReplicationLagCount` | `EntityName` | **Azure Monitor에서만.** No → 없음(Capture·geo-replication 미사용) |
| `NamespaceCpuUsage`, `NamespaceMemoryUsage` | `Replica` | **문서와 달리 도착.** No → 도착. replica를 합친 값이라 API maximum과 다름 |
| `ActiveConnections`, `ConnectionsOpened`, `ConnectionsClosed`, `Size` | `ActiveConnections`는 없음, 나머지는 `EntityName` | **문서와 달리 도착.** No → 도착. dimension 없음 |
| `IncomingRequests`, `IncomingMessages`, `OutgoingMessages`, `IncomingBytes`, `OutgoingBytes` | `EntityName` | **양쪽, DS는 dimension 없음.** Yes → 도착. 값이 있는 분만 전달, 합계는 Azure Monitor와 일치 |
| `INREQS`, `SUCCREQ`, `INMSGS`, `OUTMSGS`, `EHINMSGS`, `EHOUTMSGS`, `EHINBYTES`, `EHOUTBYTES`, `EHINMBS`, `EHOUTMBS` | 없음(지표표에 Deprecated로 표시) | **양쪽(레거시 namespace 지표).** Yes → 도착 |
| `FAILREQ`, `INTERR`, `MISCERR`, `SVRBSY` | 없음(Deprecated) | **DS 대상, 실측 없음.** Yes → 없음(오류가 없어 0값만 있던 것으로 추정) |
| `EHABL`, `EHAMBS`, `EHAMSGS`, `ReplicationLagDuration` | `ReplicationLagDuration`만 `EntityName` | **DS 대상, 실측 없음.** Yes → 없음(Capture·geo-replication 미사용) |

![IncomingMessages를 Metrics API(초록 실선)와 Diagnostic Settings(노랑 점선)로 받은 Grafana 그래프. 두 선이 19:42–19:52에 겹치고 Diagnostic Settings는 값이 있는 분만 존재](images/api-vs-diagnostic-settings.png)

- **dimension이 사라집니다.** 같은 19:44의 CPU가 Metrics API maximum 2%, Diagnostic Settings
  maximum 1%·average 0.5%로 달랐습니다. replica별 값이 합쳐진 결과입니다.
- **값이 있는 분만 옵니다.** 합계는 같지만 `IncomingMessages`는 25분 중 11분만 도착했습니다.
  Learn은 0값만 내보내는 동안 export 간격을 늘린다고 설명합니다.
- **지표 이름은 지표표가 아니라 받은 데이터로 확인합니다.** 레거시 이름이 함께 오고 일부
  지표는 오지 않으므로 대시보드는 probe 결과로 만듭니다.

## VictoriaMetrics 전달 경로: remote write와 scrape { #delivery }

같은 Collector 출력을 remote write와 Prometheus scrape 두 경로로 VictoriaMetrics에 보내면
저장되는 timestamp가 다릅니다. remote write는 Azure Monitor 분 bin의 timestamp를 그대로
쓰고, scrape는 Collector가 들고 있는 마지막 값을 scrape 시각으로 다시 기록합니다.

![같은 IncomingMessages를 remote write(초록)와 scrape(노랑)로 저장한 Grafana 그래프. scrape 곡선이 약 2–2.5분 늦게 오르내림](images/delivery-path-comparison.png)

| 항목 | remote write | scrape |
|---|---|---|
| timestamp | 원본 분 bin | scrape 시각 |
| Metrics API 지표 series당 분당 sample | 1.00 | 2.00 (30초 scrape) |
| 25분 합계의 Azure Monitor 대비 | 1.0배 | 2.0–2.3배 |
| 마지막 sample 경과 시간 | 194–213초(실제 원본 지연) | 37–48초(원본 지연을 가림) |

구간 합계와 지연 경보는 remote write 경로로 계산합니다. scrape 경로는 같은 분 값을 여러 번
저장하므로 합계가 부풀고, 최신 sample이 실제보다 새로워 보입니다.

## 추가: 내부 event(message) 모니터링 — consumer lag·runtime log·분산 추적 { #events }

여기부터는 지표 수집에 더해 볼 수 있는 추가 내용입니다. 플랫폼 지표는 namespace가
받은·내보낸 양만 보여 주므로, consumer가 처리하지 못하고 쌓인 양이나 개별 메시지의 흐름이
필요하면 별도 신호를 더합니다. 이 topic은 checkpoint 기반 consumer lag만 실측했고([실습의
lag 시나리오](lab/index.md#lag)), 나머지는 선택지로 정리합니다.

| 신호 | 내용 | 조건·주의 |
|---|---|---|
| checkpoint 기반 lag (이 topic) | partition 마지막 enqueue sequence − consumer group checkpoint sequence | 재시작하면 다시 처리할 양. 15초마다 Event Hubs를 직접 조회해 플랫폼 지표보다 빠름(실측 38초) |
| `ApplicationMetricsLogs`의 `ConsumerLag` | Diagnostic Settings 로그. partition·consumer group별 lag와 연결·처리량 runtime 지표 | Premium·Dedicated만 지원. AMQP는 receiver에 마지막으로 전달된 sequence와의 차이이며, 받을 것이 없으면 레코드가 없음(0이 아님). Kafka는 commit offset 기준으로 1분마다 평가 |
| `RuntimeAuditLogs` | publish·consume 같은 data plane 접근을 client별로 집계한 감사 로그 | Premium·Dedicated만 지원 |
| 분산 추적 | 이벤트 속성의 W3C Trace Context 형식 `Diagnostic-Id`로 producer와 consumer 처리를 연결 | 추적 backend와 양쪽 instrumentation 필요. backlog 크기는 보여 주지 않음 |

## 실습 { #lab }

[Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습](lab/index.md)에 이 비교를 재현한
배포 구성, Collector 설정, lag 시나리오, agent 대시보드 검증, 지연 측정 방법, 배포 중 만난
오류와 정리 과정을 실제 실행 결과와 함께 정리했습니다. 약 2시간이 걸리고 Event Hubs
Premium·AKS·VM 비용이 발생합니다.

## 공식 참고 자료

- [Monitor Azure Event Hubs](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs)
- [Azure Event Hubs monitoring data reference](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference)
- [Diagnostic settings in Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/platform/diagnostic-settings)
- [Azure Monitor Metrics overview](https://learn.microsoft.com/azure/azure-monitor/metrics/data-platform-metrics)
- [Log data ingestion time in Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/logs/data-ingestion-time)
- [How to migrate from the metrics API to the getBatch API](https://learn.microsoft.com/azure/azure-monitor/metrics/migrate-to-batch-api)
- [Monitor Azure Functions and Event Hubs](https://learn.microsoft.com/azure/architecture/serverless/event-hubs-functions/observability)
- [OpenTelemetry Collector Contrib azuremonitorreceiver v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azuremonitorreceiver)
- [OpenTelemetry Collector Contrib azureeventhubreceiver v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azureeventhubreceiver)
- [OpenTelemetry Collector Contrib prometheusremotewriteexporter v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/exporter/prometheusremotewriteexporter)
- [webdevops azure-metrics-exporter](https://github.com/webdevops/azure-metrics-exporter)
