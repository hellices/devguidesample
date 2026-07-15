# HDInsight Kafka lag/catch-up 벤치마크 — broker SKU / consumer fetch size

- Date: 2026-07-15 | Region: japaneast | Cluster: `krafton-kafka-hdi-68944` (HDInsight Kafka, broker 3)
- Scope: partition·consumer 수 고정 조건에서 broker VM SKU, consumer fetch size 2개 변수만 스윕. 특정 축소 구성·특정 배포 인스턴스 한정 관측값이며 일반화 결론 아님.

## 1. 측정 동기

- 운영 관찰:
  - partition 수 = consumer pod 수 (1:1 고정 운영).
  - log 50% + partition/consumer 축소 → 정상.
  - log 100% + partition/consumer 증설 → 주간 peak 구간에서 consumer lag 7분 이상.
- 유입 특성: 일 15TB 규모, 야간 무부하 / 주간 특정 시간대 집중. peak 구간에서 순간 유입률 상승.
- 점검 항목: partition·consumer 수 고정 상태에서 아래 2개 변수만으로 소비 상한(C) 완화 여부.
  - `broker VM SKU`
  - `consumer fetch size` (`max.partition.fetch.bytes`, `fetch.max.bytes`)

## 2. lag 메커니즘 (측정 해석 기준)

- 정의: `lag(t) = ∫ (P − C) dt`. P = 순간 produce rate, C = 순간 consume rate.
  - `P ≤ C`: lag 미발생 또는 감소.
  - `P > C`: lag 증가. 증가 기울기 = `P − C`.
  - burst 종료 후 catch-up 속도 = `C − P_잔여`. lag 해소 시간 ≈ `누적 lag ÷ (C − P)`.
- 연속 파이프라인(producer→kafka→consumer 상시)에서 consumer는 log tail(최근 오프셋)을 읽음.
  - tail 데이터가 broker page cache에 상주하면 disk read 비중 낮음.
  - 반대로 유입 P가 커져 consumer가 뒤처지면 read 오프셋이 tail에서 멀어지고, working set이 broker page cache를 초과하면 read가 disk로 내려가 C가 하락.
- 따라서 점검 대상은 **소비 상한 C를 무엇이 제한하며, SKU/fetch 조정이 C를 올리는가**.
- C 제한 후보:
  1. broker fetch 처리 + replication + page cache 적중률 (broker CPU/RAM/disk/network) → broker SKU-up 시 완화 가능.
  2. consumer pod의 per-message 처리 (역직렬화·애플리케이션 로직) → broker SKU-up 무관, pod 증설/파티션 증설 필요.
  3. partition 직렬화 (partition 1 = consumer 1) → partition 증설 필요.

## 3. 스펙 / 측정 구성

| item | value |
|---|---|
| Cluster | HDInsight Kafka, worker(broker) 3 |
| SKU (worker) | D4 = Standard_D4ads_v5 (4 vCPU / 16GB) ↔ D16 = Standard_D16ads_v5 (16 vCPU / 64GB) |
| Topic | `cont2`, partition 12, RF 2, `retention.ms=1800000`(30min), `retention.bytes` 무제한 |
| partition : consumer | 12 : 12 (fixed) |
| Producer | `vm-kafka-producer` (별도 VM), 8 parallel `kafka-producer-perf-test` 상시 유입 (record 1KB, acks 1, linger 15ms, batch 256KB, compression none) |
| Consumer(측정) | `vm-kafka-loadgen` (별도 VM), 단일 `kafka-consumer-perf-test`, from-earliest, `--messages 4,000,000` (≈4GB) |
| 지표 | perf 출력의 `fetch.MB.sec` (rebalance 시간 제외한 순수 fetch 구간 처리율) |

## 4. 방법 (연속 파이프라인 소비 상한 측정)

- producer VM에서 8 parallel producer를 상시 실행해 유입 P를 지속 발생시킨다(연속 파이프라인 재현).
- 유입이 도는 상태에서, consumer VM에서 단일 `kafka-consumer-perf-test`(from-earliest, 4M msg ≈ 4GB)를 실행해 소비 상한 C를 측정한다.
  - producer와 consumer를 **서로 다른 VM**에서 실행 → 단일 VM CPU/NIC 공유로 인한 측정 아티팩트 배제.
  - 지표는 `fetch.MB.sec` 사용(group rebalance 대기 시간 제외).
- 변수: broker SKU(D4 / D16) × fetch size(`max.partition.fetch.bytes` 1MB / 4MB), 조건별 3회 측정 후 중앙값.
- 각 SKU 클러스터는 측정 전 단일-thread producer로 health check(정상 disk 배포 인스턴스 여부 확인) 후 측정.

## 5. 측정 범위 한계

- broker 3대 축소 구성. 운영 규모(18 broker, partition 180, pod 240) 절대 재현 아님.
- 측정 consumer는 `kafka-consumer-perf-test`로 byte 처리만 수행 → 운영 rdkafka pod의 애플리케이션 로직(역직렬화·처리) 미포함. 절대 처리량 1:1 비교 불가, broker/디스크/네트워크 측 소비 상한의 경향 참고용.
- **HDInsight worker data disk 성능은 배포 인스턴스마다 편차 존재**(내부 관리 디스크, RG에 비노출). 절대값은 배포 편차를 포함하므로, 아래 결과는 개별 수치보다 SKU 간 차수(order of magnitude) 차이를 robust한 관측으로 해석.
- 조건별 3회 측정(중앙값). 미고정/미검증 변수: scale-out(partition·broker 증설), disk type, network, producer 특성, pod 처리 CPU.

## 6. 결과 (partition = consumer = 12 고정, 연속 파이프라인)

측정 전 health check(단일-thread producer): D4 76.5 MB/s, D16 정상 → 두 배포 인스턴스 모두 정상 disk 배포로 확인.

### 6-1. 소비 상한 C (single perf-consumer, from-earliest, `fetch.MB.sec` 중앙값)

| fetch size | D4 (MB/s) | D16 (MB/s) | D4→D16 |
|---|---|---|---|
| 1 MB (default) | ~44 | ~757 | ~17× |
| 4 MB | ~51 | ~788 | ~15× |

- 원시값: D4 fetch1M 44.5 / 44.4 / 41.2, fetch4M 50.9 / 57.6 / 47.6. D16 fetch1M 757 / 774 / 754, fetch4M 779 / 788 / 791.
- fetch-size 효과(동일 SKU): D4 1MB→4MB +16%(44→51), D16 1MB→4MB +4%(757→788).

### 6-2. 유입 P (8 parallel producer 합산 유입률, 참고)

| item | D4 (MB/s) | D16 (MB/s) |
|---|---|---|
| producer aggregate (8 parallel) | ~303 | ~588 |

- 동일 8-parallel 유입에서 broker가 수용하는 합산 유입률도 SKU에 따라 차이(D4 303 → D16 588).

## 7. 관측 경향 (본 조건·본 배포 인스턴스 한정)

- 연속 파이프라인에서 소비 상한 C:
  - D4(16GB): fetch 1MB ~44, 4MB ~51 MB/s. 유입 P가 소비 오프셋을 tail에서 밀어낼 때 read working set이 16GB page cache를 초과, disk read 비중 증가로 C가 수십 MB/s 대에 머묾.
  - D16(64GB): fetch 1MB ~757, 4MB ~788 MB/s. 동일 working set이 64GB page cache 내 상주 → RAM 속도로 소비.
  - 동일 fetch·partition·consumer 조건에서 SKU만 D4→D16으로 상향 시 C가 차수 수준(약 15~17×)으로 상승 관측. 이 차이는 vCPU 2배를 넘어서며, page cache 용량(16GB→64GB) 임계 효과 + disk throughput headroom이 함께 작용한 것으로 해석.
- fetch-size 효과: 동일 SKU에서 1MB→4MB 상향은 D4 +16%, D16 +4%로 SKU 상향 대비 작음.
- 7x(≈7min→1min) 수준 catch-up 단축을 단일 변수로 단정하지 않음. 본 관측은 "동일 partition·consumer 조건에서 broker SKU 상향이 연속 파이프라인 소비 상한 C를 크게 올릴 수 있다"는 경향까지.

## 8. 해석 시 주의

- 본 결과의 C는 broker/disk/network 측 소비 상한이며, 운영 rdkafka pod의 per-record 처리 상한은 별도.
- 운영 lag의 병목 위치(broker fetch/page cache vs pod 처리 CPU vs partition 직렬화)는 운영 모니터링으로 식별 필요:
  - broker 병목: broker CPU/RAM(page cache)·disk read util, `RequestHandlerAvgIdlePercent`, fetch latency.
  - pod 병목: consumer pod CPU util, per-record 처리 시간.
- 병목 위치에 따라 유효 레버가 다름:
  - broker fetch/page cache/disk 병목 → broker SKU-up(RAM·vCPU·disk headroom) + fetch size 상향.
  - pod 처리 병목 → pod/partition scale-out (broker SKU 무관).
- 절대 수치는 배포 인스턴스 disk 편차를 포함. 재측정 시 값이 달라질 수 있으므로 SKU 간 상대 차이를 우선 참고.

## 9. 후속 측정 후보 (미검증)

- scale-out(partition·pod·broker 동시 증설) catch-up 영향.
- 운영 rdkafka pod 로직 포함 end-to-end 측정.
- 다수 client에서 broker-side C 정밀화, 배포 인스턴스 반복 측정으로 disk 편차 정량화.
- disk type(Premium SSD v2 등), network, producer 특성 영향.

## 10. Teardown

- Cluster `krafton-kafka-hdi-68944`: deleted (D4·D16 각 테스트 후 재생성/삭제).
- VM `vm-kafka-producer`, `vm-kafka-loadgen`, `vm-jumpbox`, `vm-monitoring`: deallocated/삭제.

```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
# 전체 정리: az group delete -n rg-krafton-kafka-dev-jpe --yes
```

- 재현 아티팩트: worker SKU별 private template(`hdi-priv-Standard_D4ads_v5.json`, `hdi-priv-Standard_D16ads_v5.json`), 연속 파이프라인 harness(producer VM 8-parallel flood + consumer VM single perf-consumer, fetch size 스윕).

## 관련 문서

- [`../monitor/hdinsight-kafka-monitoring.md`](../monitor/hdinsight-kafka-monitoring.md) — HDInsight Kafka 모니터링 개요(Azure Monitor·Log Analytics·Ambari·진단설정).
- [`../monitor/hdinsight-kafka-prometheus-grafana.md`](../monitor/hdinsight-kafka-prometheus-grafana.md) — Prometheus + Grafana broker JMX·kafka-exporter(partition별 lag) 대시보드 구성.
