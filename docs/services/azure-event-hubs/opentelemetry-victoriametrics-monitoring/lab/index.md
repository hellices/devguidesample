---
title: Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습
description: Event Hubs Premium 메트릭과 consumer lag를 수집해 VictoriaMetrics와 Grafana에서 검증하고 모든 임시 리소스를 정리하는 실습입니다.
document_type: lab
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
status: needs-review
verification_status: needs-review
sources_checked_at: 2026-11-09
official_sources:
- title: Azure Event Hubs monitoring data reference
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference
- title: Monitor Azure Event Hubs
  url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs
- title: OpenTelemetry Collector Contrib azuremonitorreceiver
  url: https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azuremonitorreceiver
last_verified: 2026-11-09
review_cycle_days: 60
estimated_time: 2h
cost: paid
cleanup_required: true
topic_order: 1
---

# Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습

이 실습은 Event Hubs Premium의 플랫폼 메트릭과 checkpoint 기반 consumer lag를
OpenTelemetry Collector Contrib로 수집해 AKS의 VictoriaMetrics에 저장하고 Grafana
OSS에서 검증하는 구성을 대상으로 합니다.

> **검증 상태:** 배포 자동화와 실제 Azure 검증을 진행 중입니다. 실제 query 결과,
> dashboard 캡처와 resource group 삭제가 모두 확인되기 전까지 이 문서의 명령을
> 완료된 실측 절차로 간주하지 않습니다.

## 실습 범위

- Azure Monitor API와 Diagnostic Settings/Event Hub 수집 경로 비교
- Collector Prometheus endpoint scrape와 remote write 경로 비교
- producer와 느린 consumer를 이용한 lag 상승·회복 검증
- agent가 metric inventory를 확인해 dashboard를 생성하고 panel query를 검증하는 흐름
- Premium PU와 Dedicated CU·cluster metric의 의미 차이 문서화

Dedicated cluster는 이 실습에서 만들지 않습니다. 기존 Dedicated cluster ID를 받는
비생성 profile만 제공하며 해당 profile은 runtime 미검증으로 표시합니다.

## 비용과 정리 기준

Event Hubs Premium, AKS, VM, Public IP와 Storage 비용이 발생합니다. 실제 검증과
화면 캡처가 끝나면 전체 임시 resource group을 삭제하고 삭제 결과까지 확인합니다.

## 실행 샘플

구현 파일은 [`eventhubs-otel-victoriametrics-lab`](../samples/eventhubs-otel-victoriametrics-lab/README.md)에
정리합니다. 샘플은 `azd up`과 `azd down --purge`의 전체 수명주기를 제공하고,
실제 배포가 검증된 뒤 이 문서에 정확한 명령과 결과를 반영합니다.

## 공식 참고 자료

- [Azure Event Hubs monitoring data reference](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference)
- [Monitor Azure Event Hubs](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs)
- [OpenTelemetry Collector azuremonitorreceiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/azuremonitorreceiver)
