---
services:
- azure-event-hubs
- azure-monitor
official_sources:
- title: Azure Event Hubs monitoring data reference
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference
- title: Azure Event Hubs Premium overview
  url: https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview
- title: Azure Event Hubs Dedicated overview
  url: https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview
- title: OpenTelemetry Collector Contrib azuremonitorreceiver
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azuremonitorreceiver
- title: OpenTelemetry Collector Contrib azureeventhubreceiver
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azureeventhubreceiver
document_type: guide
status: needs-review
verification_status: needs-review
sources_checked_at: 2026-11-09
last_verified: 2026-11-09
review_cycle_days: 60
applies_to:
- Azure Event Hubs Premium namespace
- 기존 Event Hubs Dedicated cluster용 비생성 구성 profile
- OpenTelemetry Collector Contrib
- VictoriaMetrics와 Grafana OSS
title: Event Hubs 메트릭과 consumer lag의 OpenTelemetry 수집
description: Event Hubs Premium 메트릭과 checkpoint 기반 consumer lag를 OpenTelemetry Collector로 수집해 VictoriaMetrics와 Grafana에 연결하는 구성을 다룹니다.
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
---

# Event Hubs 메트릭과 consumer lag의 OpenTelemetry 수집

**이 가이드는 Event Hubs의 Azure Monitor 메트릭과 consumer checkpoint 기반 lag를
서로 다른 신호로 수집하고 VictoriaMetrics에서 함께 조회하는 구성을 다룹니다.**

현재 문서는 구현 전 설계 범위를 공개 문서 계약에 맞춰 등록한 상태입니다. 실제
Premium 배포, query 검증, Grafana 화면 캡처와 정리까지 완료하기 전에는
`verification_status: verified`로 승격하지 않습니다.

## 검증할 경로

- `azuremonitorreceiver`: Azure Monitor API의 namespace 메트릭 수집
- `azureeventhubreceiver`: Diagnostic Settings가 Event Hubs로 보낸 telemetry 수집
- 별도 lag exporter: 마지막 enqueue sequence와 consumer checkpoint 차이 계산
- AKS VictoriaMetrics: Collector endpoint scrape와 remote write 비교
- Grafana OSS: agent가 metric inventory를 확인한 뒤 dashboard 생성·query 검증·캡처

## SKU 적용 범위

실제 배포 대상은 Event Hubs Premium 1 PU입니다. Dedicated cluster는 생성하지
않습니다. 기존 Dedicated cluster ID가 제공된 경우에만 cluster metric profile을
렌더링하며, `CPU`, `AvailableMemory`, `ClusterUtilization`과 CU 기준 계산은
Premium 지표와 별도로 취급합니다. 이 profile은 본 실습에서 runtime 검증 대상으로
간주하지 않습니다.

## 공식 참고 자료

- [Azure Event Hubs monitoring data reference](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference)
- [Azure Event Hubs Premium overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview)
- [Azure Event Hubs Dedicated overview](https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview)
- [OpenTelemetry Collector azuremonitorreceiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azuremonitorreceiver)
- [OpenTelemetry Collector azureeventhubreceiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azureeventhubreceiver)
