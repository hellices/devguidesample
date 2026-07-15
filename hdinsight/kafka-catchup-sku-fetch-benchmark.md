# HDInsight Kafka lag/catch-up 벤치마크 — broker SKU / consumer fetch size

- Date: 2026-07-15 | Region: japaneast | Cluster: `krafton-kafka-hdi-68944` (HDInsight Kafka, broker 3)
- Scope: partition·consumer 수 고정 조건에서 broker VM SKU, consumer fetch size 2개 변수만 스윕. 특정 축소 구성 한정 관측값이며 일반화 결론 아님.

## 1. 측정 동기

- 운영 관찰:
  - partition 수 = consumer pod 수 (1:1 고정 운영).
  - log 50% + partition/consumer 축소 → 정상.
  - log 100% + partition/consumer 증설 → 주간 peak 구간에서 consumer lag 7분 이상.
- 유입 특성: 일 15TB 규모, 야간 무부하 / 주간 특정 시간대 집중. peak 구간에서 순간 유입률 상승.
- 점검 항목: partition·consumer 수 고정 상태에서 아래 2개 변수만으로 lag 완화 여부.
  - `broker VM SKU`
  - `consumer fetch size` (`max.partition.fetch.bytes`, `fetch.max.bytes`)

## 2. lag 메커니즘 (측정 해석 기준)

- 정의: `lag(t) = ∫ (P − C) dt`. P = 순간 produce rate, C = 순간 consume rate.
  - `P ≤ C`: lag 미발생 또는 감소.
  - `P > C`: lag 증가. 증가 기울기 = `P − C`.
  - burst 종료 후 catch-up 속도 = `C − P_잔여`. lag 해소 시간 ≈ `누적 lag ÷ (C − P)`.
- 연속 파이프라인(producer→kafka→consumer 상시)에서 consumer는 log tail(최근 오프셋)을 읽음.
  - tail 데이터는 broker page cache에 상주 → 정상 소비 시 disk read 비중 낮음.
  - 즉 본 시나리오의 lag 원인은 "page cache 초과로 인한 disk read"가 아니라 `P > C` 불균형.
- 따라서 점검 대상은 **소비 상한 C를 무엇이 제한하며, SKU/fetch 조정이 C를 올리는가**.
- C 제한 후보:
  1. broker fetch 처리 + replication (broker CPU/network) → broker SKU-up 시 완화 가능.
  2. consumer pod의 per-message 처리 (역직렬화·애플리케이션 로직) → broker SKU-up 무관, pod 증설/파티션 증설 필요.
  3. partition 직렬화 (partition 1 = consumer 1) → partition 증설 필요.

## 3. 스펙

| item | value |
|---|---|
| Cluster | HDInsight Kafka, worker(broker) 3 |
| SKU (worker) | D4 = Standard_D4ads_v5 (4 vCPU / 16GB) ↔ D16 = Standard_D16ads_v5 (16 vCPU / 64GB) |
| Topic | partition 12, RF 2, min.insync.replicas 1 |
| partition : consumer | 12 : 12 (fixed) |
| Backlog | 1KB × 6,000,000 msg ≈ 6 GB |
| Loadgen | `vm-kafka-loadgen` (16 vCPU) 단일 VM, Kafka CLI (`/opt/kafka/bin`) |

## 4. 방법

### 4-1. 소비 상한 C 분리 측정 (catch-up drain)

- consumer off 상태로 backlog 6GB 적재(record-size 1024, acks 1, linger 20ms, batch 256KB, compression none).
- 적재 후 소비 시작 → backlog 전량 drain 소요 시간 측정. `consume_MBps = 6GB ÷ drain_time`.
- 소비 상한을 두 경로로 분리 측정:
  - `BROKER-side`: `kafka-consumer-perf-test` (per-record 처리 없음, byte count만) → broker fetch·network 상한.
  - `CLIENT-side`: `kafka-console-consumer` ×12 (per-record decode 수행, rdkafka pod 유사) → client 처리 상한.
- fetch size(`max.partition.fetch.bytes`) 1MB / 4MB 스윕.

### 4-2. 연속 파이프라인 관찰 (P vs C)

- producer 지속 실행 + consumer 12개 상시 부착 상태에서 producer 병렬 수를 늘려 유입 P 상향.
- consumer group lag 기울기 측정 → `P ≤ C` (lag 평탄) / `P > C` (lag 증가) 경계 확인.

## 5. 측정 범위 한계

- broker 3대 축소 구성. 운영 규모(18 broker, partition 180, pod 240) 절대 재현 아님.
- producer·consumer가 **동일 단일 VM(loadgen)** 에서 실행 → client-side 측정은 해당 VM CPU/network에 의해 상한. broker-side 측정과 성격 다름.
- CLIENT-side tool은 운영 rdkafka pod의 실제 애플리케이션 로직 미포함 → 절대 처리량 1:1 비교 불가, 경향 참고용.
- 조건별 대부분 1회 측정 (±10~20% 편차 가능).
- 미고정/미검증 변수: scale-out(partition·broker 증설), disk type, network, producer 특성, pod 처리 CPU.

## 6. 결과 (partition = consumer = 12 고정, backlog 6GB)

### 6-1. BROKER-side 소비 상한 (perf-consumer, broker fetch·network)

| fetch size | D4 (MB/s) | D16 (MB/s) | D4→D16 |
|---|---|---|---|
| 1 MB (default) | 224 | 241 | +8% |
| 4 MB | 342 | 607 | +77% |

- fetch-size 효과 (동일 SKU): D4 224→342 (+53%), D16 241→607 (+77%).

### 6-2. CLIENT-side 소비 상한 (console-consumer ×12, per-record 처리)

| fetch size | D4 (MB/s) | D16 (MB/s) |
|---|---|---|
| 1 MB | 279 | 192 |
| 4 MB | 267 | 192 |

- CLIENT-side는 broker SKU 상향에도 개선 없음. 단일 loadgen VM CPU에 의해 상한(측정 상한 아티팩트 포함).

### 6-3. 연속 파이프라인 lag 관찰 (D4, fetch 1MB)

| 병렬 producer | lag 증가 기울기 (MB/s) |
|---|---|
| 1 | ~1.4 |
| 2 | ~15 |
| 4 | ~19 |
| 6 | ~98 |

- 유입 P 상향에 따라 lag 단조 증가. producer·consumer 동일 VM 공유로 client-side C가 제한되어 낮은 P에서 이미 `P > C` 진입.

## 7. 관측 경향 (본 조건 한정)

- lag 발생 조건: 순간 유입 P가 소비 상한 C를 초과할 때. catch-up 속도 = `C − P`.
- broker-side C:
  - fetch 1MB 기준 D4→D16 상향 효과 미미(+8%).
  - fetch 4MB 기준 D4→D16 상향 시 +77% (342→607). SKU 효과는 큰 fetch size에서 관측.
- fetch-size C: 1MB→4MB에서 broker-side 상한 증가(D4 +53%, D16 +77%).
- client-side(per-record 처리) C: broker SKU와 무관하게 loadgen VM 상한에 수렴 → **소비 병목이 pod 처리에 있으면 broker SKU-up 단독으로는 완화 미관측**.
- 7x(≈7min→1min) 수준 단축: 본 2개 변수 스윕 범위에서 단일 변수로 미관측. scale-out(partition·pod·broker 동시 증설)은 본 테스트 미측정.

## 8. 해석 시 주의

- 본 결과는 broker-side 소비 상한과 client-side 소비 상한을 **분리** 측정한 값.
- 운영 lag의 병목 위치(broker fetch/network vs pod 처리 CPU vs partition 직렬화)는 운영 모니터링으로 식별 필요.
  - broker 병목: broker CPU/network util, `RequestHandlerAvgIdlePercent`, fetch latency.
  - pod 병목: consumer pod CPU util, per-record 처리 시간.
- 병목 위치에 따라 유효 레버가 다름:
  - broker fetch/network 병목 → broker SKU-up + fetch size 상향.
  - pod 처리 병목 → pod/partition scale-out (broker SKU 무관).

## 9. 후속 측정 후보 (미검증)

- scale-out(partition·pod·broker 동시 증설) catch-up 영향.
- 운영 rdkafka pod 로직 포함 end-to-end 측정 (별도 consumer VM에서 producer와 분리).
- broker-side C를 producer와 분리된 다수 client에서 측정하여 broker 상한 정밀화.
- disk type(Premium SSD v2 등), network, producer 특성 영향.
- 조건별 다회 반복 편차.

## 10. Teardown

- Cluster `krafton-kafka-hdi-68944`: deleted (D4·D16 각 테스트 후 재생성/삭제).
- VM `vm-kafka-loadgen`, `vm-jumpbox`, `vm-monitoring`: deallocated.

```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
# 전체 정리: az group delete -n rg-krafton-kafka-dev-jpe --yes
```

- 재현 아티팩트: worker SKU별 private template(`hdi-priv-Standard_D4ads_v5.json`, `hdi-priv-Standard_D16ads_v5.json`), drain harness(`drain.sh`: preload 후 broker/client 분리 drain).

## 관련 문서

- [`../monitor/hdinsight-kafka-monitoring.md`](../monitor/hdinsight-kafka-monitoring.md) — HDInsight Kafka 모니터링 개요(Azure Monitor·Log Analytics·Ambari·진단설정).
- [`../monitor/hdinsight-kafka-prometheus-grafana.md`](../monitor/hdinsight-kafka-prometheus-grafana.md) — Prometheus + Grafana broker JMX·kafka-exporter(partition별 lag) 대시보드 구성.
