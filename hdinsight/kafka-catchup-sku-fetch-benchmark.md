# HDInsight Kafka catch-up 벤치마크 — broker SKU / consumer fetch size

- Date: 2026-07-15 | Region: japaneast | Cluster: `krafton-kafka-hdi-68944` (HDInsight Kafka, broker 3)
- Scope: 파티션·컨슈머 수 고정 조건에서 broker VM SKU, consumer fetch size 2개 변수만 스윕한 catch-up 측정치. 특정 구성 한정 관측값이며 일반화된 결론 아님.

## 1. 측정 동기

- 운영 제약: 파티션 수 = consumer pod 수 (1:1 고정 운영).
  - log 50% + partition/consumer 축소 → 정상.
  - log 100% + partition/consumer 증설 → lag 발생.
- partition/consumer 증설은 적용 완료 상태. 해당 조건 고정 후 아래 2개 변수만 스윕.
  - `broker VM SKU`
  - `consumer fetch size` (`max.partition.fetch.bytes`, `fetch.max.bytes`)

## 2. 용어

- `broker`: HDInsight worker node = VM. 본 테스트 3대.
- `partition`: consumer group 내 partition 1개 = consumer 1개. 동시 consumer 상한 = partition 수.
- `lag / catch-up`: lag = 미소비 누적량. catch-up ≈ backlog ÷ consume rate.
- `max.partition.fetch.bytes`: partition당 1회 fetch 상한 (default 1MB).
- `fetch.max.bytes`: 요청 1건 전체 fetch 상한 (default 50MB).
- `page cache`: broker의 RAM 캐시. hit 시 disk 우회, miss 시 disk read.

## 3. 스펙

| item | value |
|---|---|
| Cluster | HDInsight Kafka, broker 3 |
| SKU (worker) | D4 = Standard_D4ads_v5 (4 vCPU / 16GB) ↔ D16 = Standard_D16ads_v5 (16 vCPU / 64GB) |
| Topic | `sku-test`, partition 12, RF 2 |
| partition : consumer | 12 : 12 (fixed) |
| Backlog | 1KB × 30,000,000 msg ≈ 30.7 GB (RF2 포함 ~61 GB → broker당 ~20 GB) |
| Loadgen | `vm-kafka-loadgen` (16 vCPU), Kafka CLI |

- D4: broker당 backlog 20GB > RAM 16GB → 일부 disk read.
- D16: broker당 backlog 20GB < RAM 64GB → page cache 내 수용.

## 4. 방법

- 적재: consumer off 상태로 backlog 30.7GB produce (record-size 1024, acks 1, linger 10ms, batch 128KB, compression none).
- 소비: partition 수와 동일한 consumer 12개를 from-beginning 부착 → backlog drain.
- 측정치:
  - `catch-up_sec`: backlog 전량 소비 완료까지 경과(초).
  - `steady_MBps`: drain 20~85% 구간 평균 처리량.
- fetch size(`max.partition.fetch.bytes` / `fetch.max.bytes`)를 스윕하며 동일 backlog로 반복.

## 5. 측정 범위 한계

- broker 3대 축소 구성. 운영 규모 절대 재현 아님.
- 측정 tool(Kafka console/perf consumer)은 운영 rdkafka pod의 per-message 처리 미포함 → 절대 시간 1:1 비교 불가.
- 조건별 대부분 1회 측정 (±10~20% 편차 가능).
- 미고정/미검증 변수: scale-out(partition·broker 증설), disk type, network, producer 특성, pod 처리 CPU.

## 6. 결과

조건: partition = consumer = 12 고정, backlog 30.7GB 동일.

### 6-1. consumer fetch size sweep (D4)

| `max.partition.fetch.bytes` | catch-up_sec | steady_MBps |
|---|---|---|
| 1 MB (default) | 54 | 1052 |
| 4 MB | 36 | 1740 |
| 16 MB | 35 | 1455 |
| 64 MB | 36 | 1089 |

### 6-2. broker SKU sweep (fetch default 1MB)

| SKU | RAM/broker | catch-up_sec | steady_MBps |
|---|---|---|---|
| D4 | 16 GB | 54 | 1052 |
| D16 | 64 GB | 40 | 1428 |

### 6-3. broker SKU sweep (fetch 4MB)

| 설정 | catch-up_sec | steady_MBps |
|---|---|---|
| D4 + 4MB | 36 | 1740 |
| D16 + 4MB | 36 | 1612 |

### 6-4. single-consumer fetch sweep (참고, 1 consumer)

| fetch size | D4 MBps | D16 MBps |
|---|---|---|
| 256 KB | 403 | 419 |
| 1 MB | 441 | 452 |
| 4 MB | 441 | 446 |
| 16 MB | 443 | 442 |
| 64 MB | 434 | 445 |

## 7. 관측 경향 (본 조건 한정)

- fetch size: 1MB → 4MB 구간에서 catch-up 감소(54→36s). 4MB 이상 정체(35~36s).
- broker SKU: fetch default에서 D4 → D16 catch-up 감소(54→40s). 해당 backlog는 D4에서 RAM 초과, D16에서 RAM 수용.
- 조합: fetch 4MB 고정 시 D4 = D16 = 36s.
- 7x(≈7min→1min) 수준 단축: 본 스윕 2개 변수 범위에서 미관측. 관련 방향(partition·broker 동시 증설=scale-out)은 본 테스트 미측정.

## 8. 후속 측정 후보 (미검증)

- scale-out(partition·broker 증설) catch-up 영향.
- 운영 rdkafka pod 로직 포함 end-to-end 측정.
- backlog 크기 다단계(RAM 수용/초과 경계) 세분화.
- disk type(Premium SSD v2 등), network, producer 특성 영향.
- 조건별 다회 반복 편차.

## 9. Teardown

- Cluster `krafton-kafka-hdi-68944`: deleted (D4·D16 각 테스트 후).
- VM `vm-kafka-loadgen`, `vm-jumpbox`, `vm-monitoring`: deallocated.

```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
# 전체 정리: az group delete -n rg-krafton-kafka-dev-jpe --yes
```

- 재현 아티팩트: worker SKU별 template(`hdi-priv-Standard_D4ads_v5.json`, `hdi-priv-Standard_D16ads_v5.json`), harness(`produce_backlog.sh`, `drain_fetch.sh`, `perf_fetch_sweep.sh`).

## 관련 문서

- [`../monitor/hdinsight-kafka-monitoring.md`](../monitor/hdinsight-kafka-monitoring.md) — HDInsight Kafka 모니터링 개요(Azure Monitor·Log Analytics·Ambari·진단설정).
- [`../monitor/hdinsight-kafka-prometheus-grafana.md`](../monitor/hdinsight-kafka-prometheus-grafana.md) — Prometheus + Grafana broker JMX·kafka-exporter(partition별 lag) 대시보드 구성.
