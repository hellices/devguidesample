# 파티션·컨슈머 수를 고정한 상태에서 ① 브로커 VM 사양과 ② 컨슈머 fetch 크기를 바꿔본 Kafka catch-up 측정 기록

- 실행일: 2026-07-15 | 리전: japaneast | 클러스터: `krafton-kafka-hdi-68944` (Azure HDInsight Kafka, 브로커 3대)
- 이 문서는 **특정 구성·조건에서 관측한 값을 기록한 것**이며, 모든 경우의 수를 검증한 결론이 아니다. 수치는 이번 셋업에서의 관측이고, 다른 규모·부하·데이터 특성에서는 달라질 수 있다.

## 배경 (측정 동기)

고객은 **파티션 수와 컨슈머 pod 수를 항상 1:1로 맞춰서** 운영한다.
- 로그를 절반으로 줄이고 파티션·컨슈머도 줄였을 때 → 정상.
- 로그를 100%로 보내고 파티션·컨슈머를 늘렸을 때 → 지연(lag) 발생.

즉 "파티션·컨슈머 늘리기"는 이미 적용된 상태다. 이 조건을 고정한 채, 아래 두 가지를 바꾸면 catch-up(밀린 데이터를 따라잡는) 시간이 어떻게 관측되는지만 측정했다.
1. 브로커 VM 사양(SKU)만 변경.
2. 컨슈머가 한 번에 가져오는 크기(fetch size)만 변경.

---

## 1. 용어 (Kafka를 기본만 아는 분들을 위해)

- **브로커(broker)**: 데이터를 저장·전달하는 Kafka 서버. 여기서는 HDInsight 워커 노드 = VM 3대.
- **파티션(partition)**: 토픽을 잘게 나눈 조각. 한 컨슈머 그룹 안에서 파티션 하나는 컨슈머 1개만 읽는다. 따라서 동시에 일하는 컨슈머 최대 개수 = 파티션 개수다.
- **컨슈머(consumer)**: 데이터를 읽어가는 쪽(고객은 pod 형태, rdkafka 사용).
- **lag / catch-up**: lag은 아직 안 읽고 밀린 양. catch-up은 그 밀린 양을 따라잡는 것. 대략 `catch-up 시간 ≈ 밀린 양 ÷ 초당 소비 속도`.
- **fetch 크기**: 컨슈머가 브로커에 1회 요청할 때 받아오는 최대 크기.
  - `max.partition.fetch.bytes`: 파티션 하나당 1회 최대 크기(기본 1MB).
  - `fetch.max.bytes`: 요청 1건 전체 최대 크기(기본 50MB).
- **page cache**: 브로커가 최근 데이터를 RAM에 임시 보관하는 것. RAM에 있으면 디스크 대신 RAM에서 바로 읽어 빠르고, RAM에 없으면 디스크에서 다시 읽는다.

---

## 2. 스펙 및 실험 방법

파티션 수 = 컨슈머 수 = 12로 고정하고, 브로커 VM 사양과 컨슈머 fetch 크기만 바꿔 측정했다.

### 클러스터 스펙

| 별칭 | VM SKU | vCPU | 브로커당 RAM | 브로커 수 |
|---|---|---|---|---|
| D4 | Standard_D4ads_v5 | 4 | 16 GB | 3 |
| D16 | Standard_D16ads_v5 | 16 | 64 GB | 3 |

- 부하 발생·소비 위치: 별도 VM(`vm-kafka-loadgen`, 16 vCPU)에서 Kafka 기본 CLI 도구로 실행.
- 토픽 `sku-test`: 파티션 12, 복제 계수(RF) 2.

### backlog(밀린 데이터) 만들기

- 컨슈머를 꺼둔 채 1KB 메시지 3,000만 개 ≈ **30.7 GB** 를 먼저 적재. RF2 포함 저장량은 약 61 GB → 브로커당 약 20 GB.
  - D4(16GB RAM): 브로커당 20GB가 RAM을 초과 → 일부는 디스크에서 읽는 상태.
  - D16(64GB RAM): 브로커당 20GB가 RAM에 담기는 상태.

### 측정 절차

- 파티션과 같은 수(12)의 컨슈머를 from-beginning으로 붙여 backlog를 비우고, **다 따라잡는 데 걸린 시간(초)** 과 **20~85% 구간의 초당 소비 속도(MB/s)** 를 기록.
- 각 조건마다 backlog는 동일(30.7 GB). fetch 크기(`max.partition.fetch.bytes` / `fetch.max.bytes`)를 바꿔가며 반복.

### 측정 범위의 한계 (해석 시 참고)

- 브로커 **3대**의 축소 클러스터이며, 고객 규모의 절대 재현이 아니다.
- 측정 도구(Kafka 기본 컨슈머)는 고객 rdkafka pod의 **메시지당 처리 로직을 수행하지 않는다.** 따라서 절대 시간(초)은 고객의 실제 값과 1:1이 아니다.
- 각 조건은 대체로 1회 측정으로, ±10~20% 편차가 있을 수 있다.
- fetch 크기·SKU·backlog 크기 외의 변수(네트워크, 디스크 종류, 프로듀서 특성, pod 처리 CPU 등)는 이번 범위에서 다루지 않았다.

---

## 3. 관측 결과

아래 수치는 모두 **파티션 = 컨슈머 = 12 고정, 동일 30.7 GB backlog** 조건에서 관측한 값이다.

### 3-1. 컨슈머 fetch 크기를 바꿨을 때 (D4)

| `max.partition.fetch.bytes` | catch-up 시간 | 초당 소비 속도 |
|---|---|---|
| 1 MB (기본값) | 54초 | 1,052 MB/s |
| 4 MB | 36초 | 1,740 MB/s |
| 16 MB | 35초 | 1,455 MB/s |
| 64 MB | 36초 | 1,089 MB/s |

- 1MB → 4MB 구간에서 catch-up 시간이 54초 → 36초로 관측되었다.
- 4MB 이상에서는 catch-up 시간이 35~36초로 큰 변화가 없었다.

### 3-2. 브로커 VM 사양을 바꿨을 때 (fetch 기본값 1MB 고정)

| 브로커 VM | 브로커당 RAM | catch-up 시간 | 초당 소비 속도 |
|---|---|---|---|
| D4 | 16 GB | 54초 | 1,052 MB/s |
| D16 | 64 GB | 40초 | 1,428 MB/s |

- D4 → D16에서 catch-up 시간이 54초 → 40초로 관측되었다.
- 이 backlog는 D4에서는 브로커당 20GB로 RAM(16GB)을 초과했고, D16에서는 RAM(64GB)에 담기는 규모였다.

### 3-3. fetch 크기를 맞춘 뒤 사양을 바꿨을 때 (fetch 4MB 고정)

| 설정 | catch-up 시간 | 초당 소비 속도 |
|---|---|---|
| D4 + fetch 4MB | 36초 | 1,740 MB/s |
| D16 + fetch 4MB | 36초 | 1,612 MB/s |

- fetch를 4MB로 맞춘 조건에서는 D4와 D16의 catch-up 시간이 모두 36초로 관측되었다.

### 3-4. 단일 컨슈머(1파티션 상당) fetch 크기 스윕

참고용으로, 컨슈머 1개로 fetch 크기만 바꿨을 때의 처리량(MB/s):

| fetch size | D4 | D16 |
|---|---|---|
| 256 KB | 403 | 419 |
| 1 MB | 441 | 452 |
| 4 MB | 441 | 446 |
| 16 MB | 443 | 442 |
| 64 MB | 434 | 445 |

- 단일 컨슈머 기준으로는 fetch 크기·SKU에 따른 처리량 차이가 크지 않았다.

---

## 4. 관측값에서 읽히는 경향 (이번 조건 한정)

아래는 위 표에서 관측된 경향을 정리한 것으로, 이번 구성·조건에 한정된 서술이다.

- **fetch 크기**: 이번 조건에서 기본 1MB보다 4MB일 때 catch-up 시간이 짧게 관측되었고, 4MB 이상에서는 추가 변화가 관측되지 않았다.
- **브로커 SKU**: fetch 기본값에서 D4→D16으로 올렸을 때 catch-up 시간이 짧게 관측되었다. 이 backlog가 D4에서는 RAM을 초과하고 D16에서는 RAM에 담기는 규모였다는 점과 함께 볼 수 있다.
- **둘의 조합**: fetch를 4MB로 맞춘 조건에서는 D4와 D16의 catch-up 시간이 같게(36초) 관측되었다.
- **"7분 → 1분"에 대해**: catch-up 시간을 크게(예: 약 7배) 줄이는 것은 이번에 바꾼 두 변수(SKU, fetch)의 관측 범위만으로는 확인되지 않았다. 그 수준의 변화는 동시 소비 슬롯(파티션 수)과 브로커 대수를 함께 늘리는 방향과 관련이 있으나, 이는 이번 실험에서 측정하지 않았다.

---

## 5. 다음에 확인해볼 만한 것 (미검증 항목)

이번 실험에서 다루지 않아 결론을 내릴 수 없는, 후속 측정 후보:

- 파티션·브로커 수를 함께 늘렸을 때의 catch-up 변화(scale-out).
- 고객 pod의 실제 처리 로직(rdkafka + 메시지당 처리)을 포함한 end-to-end 측정.
- backlog 크기를 여러 단계로 바꿔 "RAM에 담기는 경우 / 초과하는 경우"를 더 세분화한 비교.
- 데이터 디스크 종류(예: Premium SSD v2), 네트워크, 프로듀서 특성 변화의 영향.
- 각 조건 다회 반복을 통한 편차 확인.

---

## 6. 정리(Teardown) 상태

- HDInsight 클러스터 `krafton-kafka-hdi-68944`: **삭제 완료**(D4·D16 각 테스트 후 삭제).
- 로드젠 VM `vm-kafka-loadgen`, 점프박스 `vm-jumpbox`, 모니터링 `vm-monitoring`: **deallocated**.
- 리소스그룹 전체 정리 명령(참고):

```bash
# 클러스터 개별 삭제 (이미 수행)
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
# 리소스그룹 통째 정리:
# az group delete -n rg-krafton-kafka-dev-jpe --yes
```

- 재현용 아티팩트: 워커 SKU별 템플릿(`hdi-priv-Standard_D4ads_v5.json`, `hdi-priv-Standard_D16ads_v5.json`)과 하네스(`produce_backlog.sh`, `drain_fetch.sh`, `perf_fetch_sweep.sh`). 워커 SKU만 바꿔 삭제·재생성하면 동일 절차로 반복 측정 가능.

## 부록. 함께 보는 모니터링 문서

- `monitor/hdinsight-kafka-monitoring.md` — HDInsight Kafka 모니터링 개요(Azure Monitor·Log Analytics·Ambari·진단설정).
- `monitor/hdinsight-kafka-prometheus-grafana.md` — Prometheus + Grafana로 브로커 JMX·kafka-exporter(파티션별 lag) 대시보드 구성 가이드.
