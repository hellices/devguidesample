# HDInsight Kafka Consumer Lag — 비율 축소 실증 테스트 설계

- 작성일: 2026-07-15
- 대상: Azure HDInsight 5.1 / Kafka 3.2, PUBG India anticheat 로그 파이프라인
- 상태: 설계안 (사용자 리뷰 대기)

## 1. 문제 정의

### 1.1 프로덕션 현상

| 항목 | 값 |
|---|---|
| 브로커 | 18 × `Standard_D8a_v4` (8 vCPU / 32 GB RAM) |
| 데이터 디스크 | S30 Standard HDD (1 TB, ~60 MB/s, ~500 IOPS) × 4/노드 |
| 토픽 | `all_gs_g_ieg_pubgm_pubgm_india`, 파티션 180, RF 2 |
| 토픽 설정 | retention 36h, segment 1 GB, max.message 1 MB, compression=producer, min.insync.replicas=2 |
| 컨슈머 | rdkafka pod 240개 (단일 그룹) |
| 프로듀서 | filebeat, 12 TB/day, 야간 무부하·게임 피크 집중 |
| 증상 | 피크(15:30경) 약 7분 consumer lag → 야간 produce 감소 시 catch-up |

### 1.2 목표

- 피크 시 consumer lag를 **1분 이내 회복**으로 낮추는 구성 도출
- 프로덕션 변경 전에 **비율 축소 테스트**로 근거(실증) 확보

### 1.3 진단 (실증 대상 가설)

**발견 1 — 컨슈머 병렬성은 180에 고정.** 단일 그룹에서 활성 컨슈머 상한 = 파티션 수 = 180. pod 240개 중 60개는 idle. pod 증설은 소비 처리량을 늘리지 못함. 고객이 관측한 "부하 50% + 컨슈머 90개 = 완화"는 컨슈머 수 효과가 아니라 **파티션당 유입률 절감** 효과.

**발견 2 — 지배 변수는 브로커당 캐시 상주 시간.**

```
브로커당 리더 파티션 = 180 / 18 = 10 (RF2 → write 2배)
page cache ≈ RAM 32 GB − JVM heap ≈ 20 GB
피크 브로커당 produce율(복제 포함) ≈ 40 MB/s (가정)
T_cache = 20 GB / 40 MB/s ≈ 8분   ← 관측 7분 lag와 동일 자릿수
```

컨슈머가 T_cache 이상 뒤처지면 읽을 오프셋이 page cache에서 축출 → S30 cold read → 디스크 IO 포화 → lag 가속 → produce가 멎는 야간에 해소. 부하 50% → T_cache 2배 → 캐시 내 소비 → lag 완화. 관측과 정합.

**결론**: lag를 1분 내로 넣는 레버는 컨슈머 증설이 아니라, **브로커당 (캐시 상주 시간 T_cache) 대비 (컨슈머 소비 지연)** 을 키우는 것 — RAM↑, 디스크 tier↑, 브로커 증설, 부하 절감.

## 2. 핵심 아이디어 — 비율 축소가 성립하는 근거

지배 무차원량:

```
ρ = (브로커당 유입률) / (브로커당 page cache)   [1/시간]
T_cache = 1/ρ = 캐시 상주 시간
```

lag 회복 조건: 컨슈머 소비 지연 < T_cache.

**브로커당 사양(RAM·디스크 tier·파티션/브로커)을 프로덕션과 동일하게 두고, 브로커 수와 총 부하만 같은 배수 k로 축소하면 ρ가 보존**된다. 따라서 3-브로커 + (프로덕션 1/6) 부하 테스트베드는 18-브로커 프로덕션의 **브로커 1대 거동을 그대로 재현**한다.

- 유지(불변): 브로커당 RAM=32 GB, 디스크 tier=S30, 브로커당 리더 파티션=10, RF=2, 토픽 설정
- 축소(비율 k=6): 브로커 18→3, 파티션 180→30, produce 12 TB/day→2 TB/day, 활성 컨슈머 180→30

이 불변식이 축소 테스트의 프로덕션 대표성을 보장한다.

## 3. 테스트베드

기존 세션 자산 재사용 + 브로커당 사양 정합.

| 구성 요소 | 프로덕션 | 테스트베드(축소, k=6) | 비고 |
|---|---|---|---|
| 브로커 수 | 18 | 3 | ARM 템플릿 `workernode.targetInstanceCount` |
| 브로커 SKU | D8a v4 (32 GB) | **D8a v4 계열 32 GB로 정합** | 현재 배포본은 D4ads_v5(16GB) → 재생성 필요 |
| 데이터 디스크 | S30 ×4 | S30 상당 ×4 | HDInsight `dataDisksGroups` |
| 파티션 | 180 | 30 | 브로커당 10 유지 |
| RF | 2 | 2 | 동일 |
| 활성 컨슈머 | 180 | 30 | 파티션과 1:1 |
| produce 부하 | 12 TB/day | 2 TB/day | 부하 생성기로 재현 |

기존 배포 자산:
- HDInsight 클러스터: `krafton-kafka-hdi-68944` (RG `rg-krafton-kafka-dev-jpe`, japaneast)
- 세션 파일: `hdi-kafka-template-public.json`, `recreate-public.sh`, `teardown.sh`
- 모니터링: JMX Exporter + Kafka Exporter + Prometheus + Grafana (VM + Managed Grafana) — `monitor/assets/prometheus-grafana/`

### 3.1 부하 발생·소비 실행 위치

produce/consume는 **브로커와 분리된 전용 클라이언트에서 실행**한다. HDInsight headnode/workernode에서 직접 돌리면 브로커 CPU·네트워크를 잠식해 측정이 오염되므로 금지.

**컨슈머를 VM으로? AKS pod로?** — 목적에 따라 갈린다. 이 테스트의 지배 가설은 브로커측(page cache eviction)이며, 브로커의 캐시·디스크 거동은 클라이언트가 VM이든 rdkafka pod든 **동일하다**(소비율과 뒤처짐 정도만 같으면 됨). 따라서 브로커를 증명하는 Arm은 VM으로 충분하고, 실제 rdkafka pod 재현은 **앱 자체가 병목인지 검증하는 Arm D에서만** 필요하다.

```
[클라이언트 VM]  ──produce──▶  [HDInsight Kafka 3 broker]  ◀──consume──  [클라이언트 VM]
 (같은 VNet, Kafka bin)              (측정 대상)                         (동일/별도 VM)
                                          │
                          JMX/Kafka Exporter ─▶ Prometheus/Grafana (모니터 호스트)
```

| 옵션 | 장점 | 단점 | 채택 |
|---|---|---|---|
| **A. 전용 클라이언트 VM** | 브로커 부하 격리, produce/consume율 정밀 제어, SKU 자유 | VM 1대 추가 | **Baseline·A·B·C 채택** |
| B. HDInsight edge node | 같은 클러스터·VNet, Kafka bin 기본 | edge node 비용, 브로커와 자원 근접 | 대안 |
| **C. AKS pod (rdkafka)** | 실제 앱 거동·fetch 재현 | 구성 복잡, 정밀 부하 제어 난이 | **Arm D 채택** |

- 프로듀서는 전 Arm 공통으로 **클라이언트 VM**에서 `kafka-producer-perf-test.sh` 실행(부하율은 브로커측 변수이지 앱 무관).
- 컨슈머:
  - Baseline·A·B·C → **VM `kafka-consumer-perf-test.sh`** (또는 sleep 주입 컨슈머). 앱 변수 제거로 병목을 브로커로 격리.
  - **Arm D → AKS pod에 고객 실제 rdkafka 설정** 배포(fetch 튜닝 없음/msg_cache 버퍼 그대로). 브로커 개선이 실제 pod 컨슈머에 이득으로 전달되는지, fetch 파라미터 튜닝 효과가 있는지 검증.
- 클라이언트 VM: HDInsight와 **동일 VNet**, 브로커보다 넉넉한 SKU(예: `Standard_D8s_v5`/`D16s_v5`)로 두어 부하 생성기 자신이 병목이 되지 않게 함. AKS도 동일 VNet(또는 peering).
- 도구: `kafka-producer-perf-test.sh --throughput <rate> --record-size 1000000` 로 produce율을 배율 k(2 TB/day 상당)에 고정. 소비측은 "피크 시 뒤처짐"을 인위 유발(일시 정지 또는 처리 지연 주입) 후 회복 시간 측정.
- produce율은 `--throughput`으로 인위 제한 → 클라이언트가 상한이 아니라 **브로커 동역학이 병목**임을 보장.

## 4. 실험 매트릭스 (한 번에 한 변수)

| Arm | 변경 대상 | 가설 | 성공 판정 |
|---|---|---|---|
| **Baseline** | 없음 (축소 정합 구성) | 7분급 lag 재현 | 피크 부하서 lag 정체가 재현됨 |
| **A. 부하 비율** | produce율만 100→75→50% 단계 | T_cache↑ | lag 회복<1분 되는 produce 임계 확인 |
| **B. 브로커 RAM** | 브로커 SKU → E-series(64 GB) | 캐시 2배 → cold read 방지 | 동일 부하서 회복<1분 |
| **C. 디스크 tier** | S30 → Premium SSD (가능 시) | cold read도 고속 | 회복<1분 + 디스크 포화 해소 |
| **D. 컨슈머 fetch** | fetch.min.bytes / queued.max.messages 튜닝 | 앱 병목 격리 | 브로커 지연 vs 소비 처리 분리 |

각 Arm은 Baseline 대비 단일 변수만 변경. B·C는 HDInsight 특성상 클러스터 재생성 필요(§7 제약).

## 5. 측정 지표 및 수집

| 지표 | 의미 | 수집원 |
|---|---|---|
| **consumer group lag 회복 시간** | 핵심 성공 지표 | Kafka Exporter → Grafana |
| page cache hit/miss | cold read 발생 여부 | node_exporter(추가) `node_vmstat_pgpgin` 등 |
| 디스크 read MB/s·IOPS·util | 디스크 병목 판정 | node_exporter `node_disk_*` |
| 브로커 BytesIn/Out, MessagesIn | 유입률 검증 | JMX Exporter |
| request/fetch 지연 | 브로커 처리 지연 | JMX Exporter |
| 컨슈머 처리율 | 소비측 처리 한계 | consumer-perf-test 출력 / 앱 지표 |

기존 Grafana 대시보드로 대부분 커버. **node_exporter만 워커에 추가**하여 page cache/디스크 지표 확보.

## 6. 실험 절차

1. **테스트베드 정합 배포** — ARM 템플릿을 브로커당 프로덕션 사양(32 GB, S30 ×4)으로 조정, 3-브로커 배포. node_exporter 추가. **동일 VNet에 클라이언트 VM(부하 생성기) 배포**.
2. **토픽 생성** — 파티션 30, RF 2, 프로덕션과 동일 설정.
3. **Baseline 재현** — 클라이언트 VM에서 2 TB/day 상당 produce + VM `consumer-perf-test` 30개(파티션 1:1). 컨슈머에 소량 지연/일시 정지를 주입해 "피크 시 뒤처짐" 유발 → lag 발생·회복 시간 측정. 7분급 정체 재현 확인.
4. **Arm A** — produce율 단계 감소, 각 단계에서 회복 시간 측정 → 회복<1분 임계 부하 도출.
5. **Arm B** — 브로커 E-series 재생성, Baseline 부하 반복 → 회복 시간 비교.
6. **Arm C** — Premium SSD 재생성(지원 확인 후), 반복.
7. **Arm D** — **AKS pod에 고객 rdkafka 설정 배포**, 브로커 개선안 위에서 fetch 파라미터(fetch.min.bytes/queued.max.messages) 조정·비교. VM 컨슈머 대비 실제 앱 거동 차이 확인.
8. **환산 및 권고** — §2 불변식으로 18-브로커 프로덕션에 대한 최소 비용 구성(SKU/디스크/부하/파티션) 권고 도출.

각 실행: 워밍업 → 정상상태 → lag 유발 이벤트 → 회복 관측. 실행당 30–60분, 동일 조건 3회 반복해 분산 확인.

## 7. 제약 및 오픈 이슈

- **HDInsight SKU/디스크 변경 = 클러스터 재생성** (in-place resize 불가). Arm B·C는 재배포 비용·시간이 큼. `recreate-public.sh` 활용.
- **HDInsight Kafka 데이터 디스크의 Premium SSD 지원 여부 확인 필요** — 미지원 시 Arm C는 "디스크 개수 증설" 또는 "브로커 증설"로 대체.
- **부하 생성기가 실제 filebeat 트래픽 특성(메시지 크기 분포·배치)을 근사** — max.message 1 MB, compression=producer 반영해 record-size 정렬.
- **비용 관리** — 각 Arm 테스트 후 즉시 teardown. 야간 유휴 클러스터·클라이언트 VM·AKS 방치 금지.
- **Arm D AKS 구성** — 실제 rdkafka 컨슈머 이미지·설정 확보 필요(고객 이미지 또는 동등 재현). AKS는 HDInsight와 동일 VNet 또는 peering.
- **테스트베드 리전/구독** — 프로덕션과 동일 japaneast, contoso 구독(검증됨).

## 8. 산출물

`monitor/` 문서 패턴에 맞춘 실증 리포트:
- 축소 재현 방법론(§2 불변식)과 절차
- Arm별 lag 회복 시간 비교표 + Grafana 캡처
- 결론: "브로커당 T_cache > 소비 지연이면 lag<1분 회복" + 프로덕션 권고(권장 SKU/디스크/파티션/부하 임계)

## 9. 비범위 (YAGNI)

- 18-브로커 풀스케일 재현 (비용 과다, 축소로 충분)
- rdkafka 앱 코드 리팩터링 (fetch 파라미터 외)
- MirrorMaker/멀티 리전 등 토폴로지 변경
- Locust 기반 HTTP 부하 자산 (Kafka 벤치와 무관)
