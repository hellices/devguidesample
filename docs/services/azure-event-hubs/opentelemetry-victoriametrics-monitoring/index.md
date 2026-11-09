---
title: "Event Hubs 지표·consumer lag · OpenTelemetry Collector · VictoriaMetrics 대시보드"
description: Event Hubs Premium의 Azure Monitor 지표와 checkpoint 기반 consumer lag를 OpenTelemetry Collector Contrib로 수집해 VictoriaMetrics에 scrape와 remote write로 저장하고, agent가 실제 데이터로 Grafana 대시보드를 만들고 검증한 결과입니다. Azure Monitor API와 Diagnostic Settings 두 수집 경로, scrape와 remote write 두 전달 경로를 Azure Monitor 직접 조회와 분 단위로 대조해 차이를 정리합니다.
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
sources_checked_at: 2026-11-09
last_verified: 2026-11-09
review_cycle_days: 60
official_sources:
- title: Azure Event Hubs monitoring data reference
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference
- title: Azure Event Hubs Premium overview
  url: https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview
- title: Azure Event Hubs Dedicated tier overview
  url: https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview
- title: Create a Dedicated Azure Event Hubs cluster using Azure portal
  url: https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-cluster-create-portal
- title: Diagnostic settings in Azure Monitor
  url: https://learn.microsoft.com/azure/azure-monitor/platform/diagnostic-settings
- title: Partition load balancing for event processing
  url: https://learn.microsoft.com/azure/event-hubs/event-processor-balance-partition-load
- title: How to migrate from the metrics API to the getBatch API
  url: https://learn.microsoft.com/azure/azure-monitor/metrics/migrate-to-batch-api
- title: Azure Policy built-in definitions for Azure Event Hubs
  url: https://learn.microsoft.com/azure/event-hubs/policy-reference
- title: OpenTelemetry Collector Contrib azuremonitorreceiver (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azuremonitorreceiver
- title: OpenTelemetry Collector Contrib azureeventhubreceiver (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azureeventhubreceiver
- title: OpenTelemetry Collector Contrib prometheusremotewriteexporter (v0.165.0)
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/exporter/prometheusremotewriteexporter
- title: VictoriaMetrics Operator VMStaticScrape
  url: https://docs.victoriametrics.com/operator/resources/vmstaticscrape/
applies_to:
- Azure Event Hubs Premium namespace (1 PU에서 실측)
- 기존 Event Hubs Dedicated cluster용 수집 profile (문서 기반, runtime 미검증)
- OpenTelemetry Collector Contrib 0.165.0
- VictoriaMetrics Operator 0.75.2, VictoriaMetrics v1.155.0, Grafana OSS 13.3.0
---

# Event Hubs 지표·consumer lag · OpenTelemetry Collector · VictoriaMetrics 대시보드

## 핵심 흐름: Azure Monitor 지표·checkpoint lag → Collector fan-out → VictoriaMetrics → agent 대시보드 { #message }

Event Hubs를 운영할 때 필요한 두 신호는 출처가 다릅니다. namespace의 CPU·memory·
요청·처리량은 Azure Monitor 플랫폼 지표이고, consumer가 얼마나 밀렸는지는 Event Hubs
partition 속성과 consumer checkpoint를 비교해야 알 수 있습니다. 이 topic은 두 신호를
하나의 OpenTelemetry Collector로 모아 VictoriaMetrics에 저장하고, agent가 실제
데이터를 확인하며 Grafana 대시보드를 완성하는 흐름을 Azure에 직접 배포해 검증한
결과입니다.

1. **Collector가 지표와 lag를 함께 수집합니다.** `azuremonitorreceiver`는 Managed
   Identity로 Azure Monitor API를 조회하고, `azureeventhubreceiver`는 Diagnostic
   Settings가 Event Hub로 보낸 지표를 읽습니다. lag exporter는 마지막 enqueue
   sequence와 checkpoint sequence의 차이를 partition별로 계산합니다.
2. **source마다 두 전달 경로로 fan-out합니다.** 같은 receiver 출력을 Prometheus
   exporter(VMAgent가 scrape)와 Prometheus remote write로 동시에 보내고,
   `source_path`·`delivery_path` label로 구분합니다.
3. **agent가 probe → build → verify → look 순서로 대시보드를 만듭니다.** 실제 metric
   이름과 label을 조회한 뒤 panel을 만들고, 모든 query를 Grafana API로 실행하고,
   렌더링한 화면을 캡처해 직접 확인합니다.

아래는 새 환경에서 `azd up` 한 번으로 배포한 뒤, 2026-11-09 19:35–20:00 UTC에 Premium
1 PU namespace로 producer 200 events/s 부하를 10분 주고 느린 consumer가 회복하는
과정을 그대로 캡처한 대시보드입니다. 수치와 화면은 모두 실제 배포에서 나왔습니다.

![Event Hubs 관측 대시보드. Premium CPU·Memory gauge와 추이, 요청 1,533건과 throttle 0건 stat, Outgoing Requests 미지원 안내, PU당 분당 message·byte 막대, partition별 peak lag 10,700–10,880건과 누적 lag 영역, checkpoint 존재 표, source_path·delivery_path별 series 수와 분당 sample 수 표, Diagnostic Settings series 178개, scrape와 remote write의 IncomingMessages 시차, API와 Diagnostic Settings의 IncomingMessages·CPU 비교, Collector 실패 0건](images/grafana-dashboard.png)

같은 25분 구간을 Azure Monitor에서 직접 조회한 값과 비교하면 remote write와
Diagnostic Settings 경로의 합계가 모두 정확히 일치했습니다.

| 지표 | Azure Monitor 직접 조회 | API → remote write | API → scrape | Diagnostic Settings → remote write |
|---|---:|---:|---:|---:|
| `IncomingMessages` | 120,200 | 120,200 (25/25분 일치) | 240,400 | 120,200 (값이 있는 11분) |
| `OutgoingMessages` | 122,400 | 122,400 (25/25분 일치) | 278,100 | 122,400 (값이 있는 17분) |
| `IncomingRequests` | 1,538 | 1,538 (25/25분 일치) | 3,222 | 1,538 (25분) |
| `ThrottledRequests` | 0 | 0 (25/25분 일치) | 0 | 없음 |

scrape 합계가 두 배 안팎인 이유는 [전달 경로 차이](#delivery)에서, Diagnostic Settings에
값이 있는 분만 들어오는 이유는 [수집 경로 차이](#receivers)에서 설명합니다.

캡처의 Incoming requests stat(1,533)은 표의 1,538과 다릅니다. Azure Monitor 표본은
분 bin 시작 시각을 timestamp로 쓰는데, 캡처 당시 stat은 Grafana 구간 끝에서
`[$__range]`로 조회해 `(from, to]` 창이 되었고 첫 분 bin이 빠지고 끝 bin이 들어갔습니다.
리뷰에서 이를 찾아 `offset 1s`로 `[from, to)` 창에 맞췄고, 로컬 VictoriaMetrics
v1.155.0에 같은 형태의 표본을 넣어 두 식의 결과가 각각 `(from, to]`와 `[from, to)` 합계와
같음을 확인했습니다.

## 수집 구조: 4개 source × 2개 전달 경로 { #architecture }

Collector는 receiver 4개를 source로 두고, source마다 scrape용과 remote write용 pipeline
두 개를 만듭니다. 두 pipeline은 같은 receiver instance를 공유하므로 비교 결과가 서로
다른 Azure API 호출의 차이가 되지 않습니다.

![실습 아키텍처. Korea South의 Event Hubs Premium 1 PU와 Diagnostic Settings, telemetry용 Standard namespace, Azure Monitor Metrics API, 생성하지 않는 Dedicated profile. Korea Central VNet의 AKS subnet에 producer·slow consumer·VMAgent·VMSingle, gateway subnet에 OpenTelemetry Collector·lag exporter·Grafana와 두 exporter, private endpoint subnet에 Storage Blob·Key Vault](images/architecture.png)

```yaml
# gateway/render_collector.py가 만드는 pipeline 일부
metrics/azure_monitor_api-scrape:
  receivers: [azure_monitor/premium]
  processors: [memory_limiter, resource/source_azure_monitor_api, resource/delivery_scrape, batch]
  exporters: [prometheus]
metrics/azure_monitor_api-remote_write:
  receivers: [azure_monitor/premium]
  processors: [memory_limiter, resource/source_azure_monitor_api, resource/delivery_remote_write, batch]
  exporters: [prometheusremotewrite]
```

두 exporter는 `resource_constant_labels.included: [source_path, delivery_path]`로 이
두 resource attribute만 label로 올립니다. v0.165.0에서 deprecated된
`resource_to_telemetry_conversion` 대신 이 설정을 사용해 불필요한 resource attribute가
label로 퍼지지 않게 했습니다.

## Azure Monitor API와 Diagnostic Settings 경로의 차이 { #receivers }

두 경로는 같은 플랫폼 지표를 다른 방식으로 전달하며, 지표 이름·dimension·0값 처리·
지연이 모두 다릅니다. Microsoft Learn의 `Microsoft.EventHub/namespaces` 지표표는
지표마다 Diagnostic Settings 내보내기(DS Export) 가능 여부를 정해 둡니다.

| 지표 | DS Export | API 경로 series | Diagnostic Settings 경로 실측 |
|---|---|---|---|
| `NamespaceCpuUsage` | No | `azure_namespacecpuusage_{average,maximum}_Percent` | `namespacecpuusage_*` 레코드 도착 |
| `NamespaceMemoryUsage` | No | `azure_namespacememoryusage_{average,maximum}_Percent` | `namespacememoryusage_*` 레코드 도착 |
| `IncomingRequests` | Yes | `azure_incomingrequests_total_Count` | `incomingrequests_*` |
| `SuccessfulRequests` | No | `azure_successfulrequests_total_Count` | 없음(레거시 `SUCCREQ`만 도착) |
| `ThrottledRequests` | No | `azure_throttledrequests_total_Count` | 없음 |
| `IncomingMessages`·`OutgoingMessages` | Yes | `azure_{incoming,outgoing}messages_total_Count` | `{incoming,outgoing}messages_*` |
| `IncomingBytes`·`OutgoingBytes` | Yes | `azure_{incoming,outgoing}bytes_total_Bytes` | `{incoming,outgoing}bytes_*` |
| Outgoing Requests | — | 없음 | 없음. 지표표에 없는 지표이므로 추정하지 않음 |

실측에서 확인한 차이는 다음과 같습니다.

- **API 경로의 0값과 데이터 없음.** `ThrottledRequests`를 기본값대로 `EntityName`·
  `OperationResult`로 분할 조회하면 throttle이 없는 동안 time series 자체가 오지 않아
  series가 생기지 않았습니다. `dimensions.overrides`로 이 지표만 분할하지 않게 하자
  명시적인 0이 저장됐고, 대시보드는 "throttle 없음"과 "데이터 없음"을 구분합니다.
- **API 경로의 권한 범위.** namespace 범위 `Monitoring Reader`만으로 리소스 목록 조회와
  ARM metrics API는 동작했지만, `use_batch_api: true`의 `metrics:getBatch` 호출은
  403이었습니다. Learn은 batch API에 조회 대상 구독의 Monitoring Reader가 필요하다고
  설명합니다. namespace 하나만 수집하므로 batch API를 끄고 최소 권한을 유지했습니다.
- **Diagnostic Settings는 dimension을 합친 값만 보냅니다.** Learn에 따르면 다차원
  지표는 dimension 값을 합친 단일 값으로 내보냅니다. 실측 series에도 `EntityName`이나
  `Replica` label이 없었고, 19:44의 CPU는 API maximum 2%, Diagnostic Settings maximum
  1%·average 0.5%로 집계 결과가 달랐습니다.
- **Diagnostic Settings는 값이 있는 분만 보냅니다.** 합계는 Azure Monitor와 같지만
  `IncomingMessages`는 25분 중 부하가 있던 11분만 도착했습니다. Learn은 리소스가 0값만
  내보내면 export 주기를 늘린다고 설명합니다. 대시보드는 이 경로의 빈 구간을 0으로
  채우지 않습니다.
- **지표 이름이 지표표와 다릅니다.** `INREQS`, `SUCCREQ`, `INMSGS`, `EHINMSGS`,
  `EHOUTBYTES`, `Size`, `ActiveConnections` 같은 이름이 함께 들어오고,
  `SuccessfulRequests`·`ThrottledRequests`는 없었습니다. 지표표의 DS Export 값과 실제
  스트림 내용이 다를 수 있으므로 probe로 받은 이름을 확인한 뒤 panel을 만듭니다.
- **지연이 더 깁니다.** 마지막 sample의 경과 시간이 API 경로 194–213초, Diagnostic
  Settings 경로 434–513초였습니다.

결론적으로 Diagnostic Settings 경로는 내보내기 가능한 처리량 지표를 외부 시스템으로
흘려보내는 보조 경로로 쓰고, CPU·memory·성공·throttle과 dimension별 분석은 Azure
Monitor API 경로를 기준으로 삼습니다.

## scrape·remote write의 timestamp·sample 밀도 차이 { #delivery }

같은 receiver 출력이라도 전달 경로에 따라 저장되는 timestamp와 sample 수가 다릅니다.
remote write는 원본 timestamp를 그대로 쓰고, scrape는 Collector가 노출한 마지막 값을
VMAgent가 가져간 시각으로 다시 기록합니다.

![같은 IncomingMessages 지표를 remote write(초록)와 scrape(노랑)로 저장한 그래프. scrape 곡선이 약 2–2.5분 늦게 오르내림](images/delivery-path-comparison.png)

| 관측 항목 | remote write | scrape |
|---|---|---|
| timestamp | 원본(Azure Monitor 분 bin, lag exporter 수집 시각) | VMAgent scrape 시각 |
| Azure Monitor API 지표 series당 분당 sample | 1.00 | 2.00 (30초 scrape) |
| lag exporter series당 분당 sample | 4.00 (Collector 15초 수집) | 2.00 |
| Diagnostic Settings series당 분당 sample | 0.76 (값이 있는 분만) | 1.92 |
| API 지표 마지막 sample 경과 시간(probe 시점) | 194–213초 | 37–48초 |
| 25분 합계의 Azure Monitor 대비 | 1.0배 | 2.0–2.3배 |

이 결과에서 대시보드 규칙 두 가지를 정했습니다.

- **구간 합계는 remote write에서만 계산합니다.** scrape 경로는 1분 값을 scrape마다 다시
  저장하므로 `sum_over_time`이 값을 중복해서 더합니다.
- **scrape의 freshness는 원본 지연을 숨깁니다.** scrape는 40초 안팎으로 보이지만 실제
  Azure Monitor 값은 3분 이상 전 bin입니다. 지연 경보에는 remote write 경로의 마지막
  sample timestamp를 사용합니다.

## checkpoint 기반 consumer lag 상승·회복 { #lag }

consumer lag는 partition의 마지막 enqueue sequence에서 consumer가 마지막으로 저장한
checkpoint sequence를 뺀 값입니다. Event Hubs는 checkpoint를 consumer group과
partition 단위로 저장하므로 lag exporter는 같은 consumer group의 Blob checkpoint만
읽습니다. checkpoint가 없는 partition은 lag 값을 만들지 않고 존재 여부만 표시합니다.

![partition 4개의 lag를 누적한 영역 그래프. 19:40 부하 시작 후 꾸준히 늘어 19:50 무렵 합계 약 43,000건으로 정점을 찍고, producer 중지 후 19:56 무렵 0으로 회복](images/consumer-lag-rise-recovery.png)

| 단계 | UTC | 관측 |
|---|---|---|
| baseline | 19:35:19 | producer 중지, 모든 partition lag 0 |
| 부하 | 19:40:19–19:50:24 | producer 목표 200 events/s, 1 KiB. Azure Monitor 기준 수신 12,000 msg/min, 처리 7,200–8,400 msg/min |
| lag 정점 | 19:50 무렵 | partition별 최대 10,700–10,880건, 합계 약 43,000건 |
| 회복 | 19:55:57 | 최대 lag가 정점의 20% 이하로 감소(producer 중지 후 5분 33초), 이후 0 |

lag 해상도는 consumer의 checkpoint 주기(20 event)와 exporter 조회 주기(15초)에 묶여
있습니다. checkpoint blob 수정 시각을 시간 단위 lag로 해석하지 않습니다.

lag exporter는 실제 시각으로 기록되지만 Azure Monitor의 `IncomingMessages` 분 bin은
19:42–19:52에 값이 나타나, producer 실제 구간보다 약 1.5–2분 늦게 기록됐습니다. 디버깅용
첫 환경에서도 같은 차이가 있었습니다. 두 신호를 같은 그래프에서 비교할 때는 이 차이를
감안합니다.

## Premium PU와 Dedicated CU의 지표 의미 차이 { #sku }

Premium과 Dedicated는 수집 구조가 같아도 용량 단위와 CPU·memory 지표의 의미가
다릅니다. 이 실습은 Dedicated cluster를 만들지 않고, 기존 cluster resource ID를
입력했을 때만 수집 profile을 렌더링합니다. Dedicated cluster는 만든 뒤 최소 4시간
동안 삭제할 수 없고 그만큼 과금됩니다.

| 항목 | Premium namespace | Dedicated cluster |
|---|---|---|
| 용량 단위 | PU(Processing Unit) | CU(Capacity Unit) |
| CPU | `NamespaceCpuUsage`, `Replica` | `CPU`, `Role`, Maximum |
| memory | `NamespaceMemoryUsage`(사용률) | `AvailableMemory`(가용률, 낮을수록 위험) |
| 종합 사용률 | 없음 | `ClusterUtilization`(preview) |
| 이 실습 | 1 PU로 runtime 검증 | 문서 기반 profile, runtime 미검증 |

대시보드는 처리량을 `$pu` 변수로 나눠 PU당 값으로 보여 주며, Dedicated profile에서는
가용 메모리 gauge의 threshold 방향을 반대로 둡니다.

## agent 대시보드: probe·build·verify·look { #agent }

agent는 대시보드를 만들기 전에 실제 저장된 metric을 조회하고, 만든 뒤에는 query와
화면을 모두 확인합니다.

1. **probe**: VictoriaMetrics에서 metric 이름, label key, `source_path × delivery_path`
   조합별 series·sample 수와 freshness를 조회합니다. 식별자가 담긴 label 값은 저장하지
   않습니다.
2. **build**: 질문 → 지표 → MetricsQL → 시각화 표에 따라 panel을 만듭니다. 합계는
   stat, 정상 범위는 gauge, 비교는 table·bar gauge, 추이만 time series로 씁니다.
3. **verify**: 모든 panel query를 Grafana `/api/ds/query`로 실행해 오류·0행·NaN을
   찾습니다. `Exporter send failures`가 0행이어서 첫 실패 때 생기는 counter의 특성을
   반영하도록 고쳤습니다. 최종 실행에서 28개 query가 모두 통과했습니다.
4. **look**: Playwright로 렌더링한 전체 화면을 직접 봅니다. 첫 캡처에서는 time series의
   모든 선이 같은 색이고, 과거 구간의 "now" lag가 0으로 보이며, checkpoint 표의
   partition 열까지 경고색이 칠해져 있었습니다.

![look 단계에서 고치기 전 첫 캡처. CPU·memory와 lag 선이 모두 같은 초록색이고 lag 패널이 현재 값 0만 보여 줌](images/look-step-before-fix.png)

look 단계에서 찾은 문제는 series별 palette, 구간 peak lag, 공통 눈금 bar gauge,
열 단위 색상, 겹치는 비교 선의 점선 구분으로 고쳐 맨 위 최종 화면에 반영했습니다.

![IncomingMessages를 Azure Monitor API(초록 실선)와 Diagnostic Settings(노랑 점선)로 받은 그래프. 두 선이 19:42–19:52에 겹치고 Diagnostic Settings는 값이 있는 분만 존재](images/api-vs-diagnostic-settings.png)

## 배포 제약: 리전 제한·조직 정책·권한 범위 { #constraints }

실제 구독에 배포하면서 sample에 반영한 제약입니다. 오류 원문과 수정 과정은
[실습 문서](lab/index.md#errors)에 정리했습니다.

- 이 구독은 Korea Central·Japan East·Southeast Asia에서 Premium namespace 신규 생성이
  제한되어 Event Hubs만 Korea South에 두었습니다(`EVENTHUBS_LOCATION`). Diagnostic
  Settings의 sink Event Hub는 원본과 같은 리전이어야 하므로 두 namespace를 함께
  옮깁니다.
- 관리 그룹 정책이 Key Vault·Storage public network access와 Event Hubs local(SAS)
  인증을 끕니다. Key Vault·Storage는 private endpoint로만 접근하도록 구성했고,
  Diagnostic Settings는 telemetry namespace의 local 인증이 꺼진 상태에서도 전달됐습니다.
- AKS cluster identity는 internal load balancer 고정 IP를 위해 BYO subnet 권한이
  필요하고, 배포자는 Azure RBAC for Kubernetes의 cluster admin 역할이 필요합니다.

## 실습 { #lab }

[Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습](lab/index.md)에서 `azd up`부터
lag 시나리오, agent 검증, fallback exporter 전환, `azd down --purge`까지 실제 실행
결과와 함께 재현합니다. 약 2시간이 걸리고 Event Hubs Premium·AKS·VM 비용이
발생합니다.

## 공식 참고 자료

- [Azure Event Hubs monitoring data reference](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference)
- [Azure Event Hubs Premium overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview)
- [Azure Event Hubs Dedicated tier overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview)
- [Create a Dedicated Azure Event Hubs cluster using Azure portal](https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-cluster-create-portal)
- [Diagnostic settings in Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/platform/diagnostic-settings)
- [Partition load balancing for event processing](https://learn.microsoft.com/azure/event-hubs/event-processor-balance-partition-load)
- [How to migrate from the metrics API to the getBatch API](https://learn.microsoft.com/azure/azure-monitor/metrics/migrate-to-batch-api)
- [Azure Policy built-in definitions for Azure Event Hubs](https://learn.microsoft.com/azure/event-hubs/policy-reference)
- [OpenTelemetry Collector Contrib azuremonitorreceiver v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azuremonitorreceiver)
- [OpenTelemetry Collector Contrib azureeventhubreceiver v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/receiver/azureeventhubreceiver)
- [OpenTelemetry Collector Contrib prometheusremotewriteexporter v0.165.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.165.0/exporter/prometheusremotewriteexporter)
- [VictoriaMetrics Operator VMStaticScrape](https://docs.victoriametrics.com/operator/resources/vmstaticscrape/)
