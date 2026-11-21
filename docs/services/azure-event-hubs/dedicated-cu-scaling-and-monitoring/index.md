---
title: Event Hubs 용량 단위(TU·PU·CU) 스케일링 실측과 OTel·VictoriaMetrics 실효 사용률 모니터링
description: Standard TU의 하드 스로틀링과 Premium PU·Dedicated CU의 격리 컴퓨팅 스케일링 차이를 실측 데이터로 비교하고 파티션 상한·Gzip 압축 영향 및 OpenTelemetry Collector·VictoriaMetrics·Grafana 기반 실효 용량 사용률(%) 산출 아키텍처를 정리합니다.
document_type: guide
services:
  - azure-event-hubs
  - azure-monitor
technologies:
  - kafka
  - open-telemetry
  - prometheus
  - grafana
  - python
  - bicep
  - docker
  - kubernetes
tags:
  - evaluate
  - optimize
  - operate
status: current
verification_status: verified
sources_checked_at: 2026-11-16
official_sources:
  - title: Scaling with Event Hubs
    url: https://learn.microsoft.com/azure/event-hubs/event-hubs-scalability
  - title: Azure Event Hubs Dedicated tier overview
    url: https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview
  - title: Azure Event Hubs Premium overview
    url: https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview
  - title: Azure Event Hubs quotas and limits
    url: https://learn.microsoft.com/azure/event-hubs/event-hubs-quotas
  - title: Azure Event Hubs monitoring data reference
    url: https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference
  - title: Azure Schema Registry in Event Hubs
    url: https://learn.microsoft.com/azure/event-hubs/schema-registry-overview
last_verified: 2026-11-16
review_cycle_days: 180
applies_to:
  - Azure Event Hubs Standard (TU)
  - Azure Event Hubs Premium (PU)
  - Azure Event Hubs Dedicated (CU)
  - OpenTelemetry Collector Contrib 0.114+
  - VictoriaMetrics 1.106+
---

# Event Hubs 용량 단위(TU·PU·CU) 스케일링 실측과 OTel·VictoriaMetrics 실효 사용률 모니터링

Azure Event Hubs의 용량 단위는 티어에 따라 동작 원리가 다르다. Standard 티어의 [Throughput Unit(TU)](https://learn.microsoft.com/azure/event-hubs/event-hubs-scalability#throughput-units)은 단위당 `1 MB/s`(또는 `1,000 events/s`)에서 즉시 `ServerBusy` 예외를 반환하는 하드 스로틀링 상한인 반면 Premium 티어의 [Processing Unit(PU)](https://learn.microsoft.com/azure/event-hubs/event-hubs-scalability#processing-units)와 Dedicated 티어의 [Capacity Unit(CU)](https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview#capacity-units)는 사전 할당된 전용 CPU·메모리 리소스 번들이다.

Dedicated `1 CU`(공식 기준 약 `100~200 MB/s` Ingress)나 Premium `1 PU`(공식 기준 약 `5~10 MB/s` Ingress) 환경에서는 용량 단위를 `4 CU → 8 CU`로 2배 증설하더라도 토픽 [파티션 수](https://learn.microsoft.com/azure/event-hubs/event-hubs-scalability#partitions)와 파티션 키 편중(파티션당 권장 상한 `1~2 MB/s`), Filebeat·Kafka Gzip 압축과 배치 크기에 따른 브로커 CPU 소모율, 다중 컨슈머 동시 Egress와 스토리지 I/O 경합이 실제 최대 처리량을 좌우한다. Azure Portal 기본 화면은 할당된 CU 대비 대역폭·파티션 상한 사용률(%)과 Kafka 컨슈머 그룹 지연(Lag)을 단일 지표로 계산해 주지 않으므로 컴퓨팅 포화도·할당 대역폭 사용률·파티션 상한 사용률의 3대 실효 용량 사용률(%)을 별도 모니터링 파이프라인으로 산출해야 클러스터 축소(Scale-in)나 증설(Scale-out) 여부를 판단할 수 있다.

---

## 1. Standard TU 하드 스로틀링과 Premium PU·Dedicated CU 격리 컴퓨팅의 구조적 차이

Standard 티어에서 익숙한 `1 단위 = 1 MB/s, 1,000건` 공식을 Dedicated `CU`나 Premium `PU`에 그대로 대입하면 용량을 과대 산정하거나 반대로 파티션 병목을 놓치게 된다. [Event Hubs 티어별 할당량 및 한도](https://learn.microsoft.com/azure/event-hubs/event-hubs-quotas#basic-vs-standard-vs-premium-vs-dedicated-tiers)와 [모니터링 데이터 레퍼런스](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference#metrics)에 따른 세 용량 단위의 차이는 아래 표와 같다.

| 비교 항목 | Standard: `TU` (Throughput Unit) | Premium: `PU` (Processing Unit) | Dedicated: `CU` (Capacity Unit) |
|---|---|---|---|
| **용량 단위의 물리적 의미** | 멀티테넌트 공유 클러스터의 **API 전송률 쿼터(Rate Limit)** | 멀티테넌트 내 CPU·메모리가 격리된 **컨테이너 번들(Cluster-in-Cluster)** | 단일 고객 전용(Single-Tenant) **물리/가상 CPU·메모리 클러스터 번들** |
| **단위당 공식 Ingress 용량** | **엄격한 상한**: `1 MB/s` 또는 `1,000 events/s` (먼저 도달하는 값 적용) | **소프트 용량**: 1 PU(100 파티션 기준) 약 `5~10 MB/s` (하드 리밋 없음) | **소프트 용량**: 1 CU당 약 **`100~200 MB/s`** (워크로드·파티션·압축에 따라 변동) |
| **단위당 공식 Egress 용량** | **엄격한 상한**: `2 MB/s` 또는 `4,096 events/s` | 1 PU당 약 `10~20 MB/s` | 워크로드 및 CPU 여유도에 비례 (별도 하드 스로틀링 없음) |
| **한도 초과 시 동작** | 즉시 요청 거부 (`ServerBusy` / `ThrottledRequests` 증가, Kafka `throttle_time_ms` 지연) | 하드 스로틀링 없음. 할당된 CPU·메모리가 포화될 때까지 처리 후 점진적 지연 증가 | 하드 스로틀링 없음. 클러스터 `CPU`가 **70%**를 넘으면 최대 용량 근접 신호로 판정 |
| **파티션 1개당 권장 상한** | Ingress `~1 MB/s` / Egress `~2 MB/s` | Ingress **`~1~2 MB/s`** / Egress **`~2~5 MB/s`** | Ingress **`~1~2 MB/s`** / Egress **`~2~5 MB/s`** |
| **최대 파티션 수** | Event Hub당 `32개` (생성 후 증설 불가) | Event Hub당 `100개`, PU당 네임스페이스 합산 `200개` (동적 증설 가능) | Event Hub당 `1,024개`, CU당 클러스터 합산 `2,000개` (동적 증설 가능) |
| **핵심 리소스 메트릭** | `IncomingBytes`, `IncomingMessages`, `ThrottledRequests` (`CPU` 메트릭 미제공) | `NamespaceCpuUsage`, `NamespaceMemoryUsage` (`Replica` 차원), `IncomingBytes` | `CPU`, `AvailableMemory` (`Role: Backend, Gateway` 차원), `ClusterUtilization` |
| **스케일 단위 및 과금 제약** | `1~40 TU` (최소 1시간 과금, Auto-inflate 지원) | `1, 2, 4, 6, 8, 10, 12, 16 PU` (최소 1시간 과금) | `1~10 CU` Self-serve (10 CU 초과는 지원 티켓, **생성 후 최소 4시간 삭제 불가·과금**) |

### 4 CU에서 8 CU 증설 시 비선형 처리량이 나타나는 원인

Dedicated `CU`와 Premium `PU`에서 실제 처리량은 아래 세 가지 물리적 경계의 최솟값(`min`)으로 결정된다.

$$\text{실제 달성 가능한 최대 Ingress (MB/s)} = \min\Big(\text{클러스터 CU 컴퓨팅 용량},\; \text{활성 파티션 수} \times \text{파티션당 처리 상한},\; \text{Producer 배치·압축 전송 한계}\Big)$$

1. **파티션 커밋 로그 직렬화 한계(`1~2 MB/s per partition` 권장, 배치 버스트 시 `~11 MB/s`)**: Event Hubs의 각 파티션은 순서 보장을 위해 하부 스토리지와 복제본(3 Replicas)에 동기 플러시되는 독립 커밋 로그다. 토픽 파티션이 적거나 특정 `partition_key`로 트래픽이 쏠리면 클러스터를 `4 CU`에서 `8 CU`로 늘려도 파티션 합산 상한에 막혀 처리량이 늘어나지 않는다.
2. **Gzip 압축 및 소형 배치 요청의 Gateway/Backend CPU 소모**: Filebeat 등 수집기가 파이프(`|`) 구분자 평문 로그를 Gzip으로 압축해 전송하면 네트워크 유입 바이트(`IncomingBytes`)는 75~80% 줄어들지만 초당 이벤트 수(`IncomingMessages`)와 요청 프레임 처리, 멀티 컨슈머 팬아웃(Fan-out) 시 브로커 `CPU` 및 메모리가 먼저 [권장 스케일링 임계치인 70%](https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview#when-should-i-scale-my-dedicated-cluster)에 도달한다.
3. **클러스터 적정 용량 산정(Scale-in / Scale-out) 시의 전제 조건**: 과대 할당된 클러스터(예: `8 CU`)를 하위 용량(`4 CU` 또는 `2 CU`)으로 축소하려면 피크 시점 컴퓨팅 포화도(`CPU < 70%`)와 파티션 수 확보 여부를 함께 검증해야 한다.

---

## 2. 용량 단위 스케일링·파티션 병목·Gzip 압축 실측 벤치마크

한국 리전(`Standard·Dedicated: koreacentral`, `Premium: koreasouth`)에 실제 Azure Event Hubs Standard(`1·2·4 TU`), Premium(`1·2·4 PU`), 단일 고객 전용 Dedicated 클러스터(`Microsoft.EventHub/clusters@2024-01-01`, `1 CU → 2 CU → 4 CU → 8 CU`)를 배포하고 변인 통제 원칙에 따라 실험했다.

- **고정 통제변인(Control Variables)**: 모든 실험에서 페이로드를 `1,024 Byte` 고정 크기 파이프(`|`) 구분자 게임 서버 텔레메트리(`TLOGv3|timestamp|BATTLE_TICK|...`)로 통일하고 클라이언트 측의 인위적인 전송 속도 제한(Rate Limit / Sleep)을 완전히 제거(Unthrottled)했다. 로컬 WAN 업링크 병목(`~20 MB/s`)을 제거하기 위해 **Dedicated(`1·2·4·8 CU`) 실험은 동일한 `koreacentral` 리전 내부의 고대역폭 Linux 부하 생성 노드(`8 × P3v3 = 64 vCPUs`, `32~64개` 워커 프로세스, `64~256개` 파티션 스트림, C 기반 `librdkafka 2.16.1`)**에서 `35초`씩 전속력으로 전송하고 Azure Monitor(`--interval PT1M`)에서 실제 클러스터 `CPU`(`Role: Gateway, Backend`), `AvailableMemory`, 네임스페이스 `IncomingBytes`, `IncomingMessages`, `ThrottledRequests`를 수집했다.

### 용량 단위(1 → 2 → 4 → 8 Unit) 증가에 따른 Standard TU·Premium PU·Dedicated CU 스케일링 비교

Standard(`1·2·4 TU`) 및 Premium(`1·2·4 PU`, `telemetry-p32`)과 In-Region Dedicated 클러스터(`1·2·4·8 CU`, `telemetry-p64`, `100 KB` 배치)에서 속도 제한 없이 전송했을 때의 실측 결과다.

| 티어 및 용량 단위 | 고정 통제변인 (`Workers / Batch / Partitions`) | 공식 용량 기준 | 실측 Ingress (`MB/s`) | 실측 처리율 (`Events/s`) | 스로틀링 (`ServerBusy` / 분당) | 전송 지연 `p50` (`ms`) | 전송 지연 `p95` (`ms`) | 전송 지연 `p99` (`ms`) | 브로커 CPU (`Gateway / Backend Max %`) | 브로커 Memory Used (`%`) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Standard `1 TU`** | `32 / 100건 / 32p` | `1.0 MB/s` (`1,000 msg/s`) 하드 상한 | **1.230 MB/s** | 1,259.4 | **291건** (`615건/분`) | 132.60 | 1,350.76 | 1,442.08 | N/A | N/A |
| **Standard `2 TU`** | `32 / 100건 / 32p` | `2.0 MB/s` (`2,000 msg/s`) 하드 상한 | **3.268 MB/s** | 3,346.6 | **287건** (`618건/분`) | 44.87 | 1,285.35 | 1,363.87 | N/A | N/A |
| **Standard `4 TU`** | `32 / 100건 / 32p` | `4.0 MB/s` (`4,000 msg/s`) 하드 상한 | **5.745 MB/s** | 5,883.4 | **238건** (`550건/분`) | 76.26 | 1,255.85 | 1,366.06 | N/A | N/A |
| **Premium `1 PU`** | `32 / 100건 / 32p` (WAN 경유) | `~5~10 MB/s` 격리 컴퓨팅 | **20.269 MB/s** | 20,755.8 | **0건** (`0건/분`) | 140.44 | 215.13 | 431.66 | `13.0%` (`NamespaceCpu`) | `16.0%` |
| **Premium `2 PU`** | `32 / 100건 / 32p` (WAN 경유) | `~10~20 MB/s` 격리 컴퓨팅 | **20.937 MB/s** | 21,439.9 | **0건** (`0건/분`) | 137.09 | 222.63 | 443.27 | `4.0%` (`NamespaceCpu`) | `7.0%` |
| **Premium `4 PU`** | `32 / 100건 / 32p` (WAN 경유) | `~20~40 MB/s` 격리 컴퓨팅 | **20.654 MB/s** | 21,150.0 | **0건** (`0건/분`) | 135.88 | 212.30 | 430.51 | `12.0%` (`NamespaceCpu`) | `20.0%` |
| **Dedicated `1 CU`** | `64 / 100건 / 64p` (In-Region) | `~100~200 MB/s` 전용 클러스터 | **354.781 MB/s** | **363,295.9** | **0건** (`0건/분`) | 28.36 | 47.75 | 61.57 | **`95.37% / 78.29%`** | `58.0%` |
| **Dedicated `2 CU`** | `64 / 100건 / 64p` (In-Region) | `~200~400 MB/s` 전용 클러스터 | **448.275 MB/s** | **459,033.9** | **0건** (`0건/분`) | 23.81 | 37.74 | 47.34 | **`55.18% / 95.78%`** | `67.0%` |
| **Dedicated `4 CU`** | `64 / 100건 / 64p` (In-Region) | `~400~800 MB/s` 전용 클러스터 | **708.380 MB/s** | **725,381.4** | **0건** (`0건/분`) | 26.19 | 53.34 | 82.68 | **`51.95% / 84.61%`** | `66.0%` |
| **Dedicated `8 CU`** | `256 / 100건 / 64p` (In-Region) | `~800~1,600 MB/s` 전용 클러스터 | **897.719 MB/s** | **919,263.9** | **0건** (`0건/분`) | 43.48 | 234.12 | 767.28 | **`48.19% / 64.79%`** | `61.0%` |

![실험 1: Standard TU · Premium PU · Dedicated CU(1 -> 2 -> 4 -> 8 CU) 용량 스케일링 및 브로커 CPU 실측](images/01_unit_scaling_curve.png)

- **Standard `TU`의 하드 쿼터 차단과 지연 급증**: 32개 워커가 무제한 전송을 시도하자 Standard 티어는 즉시 `ServerBusy` 예외(클라이언트 시행당 `238~291건`, Azure Monitor `ThrottledRequests` 분당 `550~618건`)를 반환하며 요청을 차단했다. 유휴 구간의 단기 버스트 크레딧 소진분을 포함해 `1 TU → 2 TU → 4 TU`에서 각각 `1.230 MB/s`, `3.268 MB/s`, `5.745 MB/s`로 제한되었고 서버 측 크레딧 홀딩으로 인해 `p95` 전송 지연이 `1,255~1,350 ms`까지 치솟았다.
- **Dedicated `1 CU → 2 CU → 4 CU → 8 CU`의 실제 CPU 포화 곡선과 `354.8 → 448.3 → 708.4 → 897.7 MB/s` 확장**: In-Region(`koreacentral`) 64파티션 부하에서 Dedicated 티어는 전 구간 하드 스로틀링(`ThrottledRequests`)이 **0건**이었다.
  - **`1 CU`**: 순수 Ingress 기준 공식 보수적 가이드라인(`100~200 MB/s`)을 상회하는 **`354.781 MB/s`(`363,295.9 msg/s`, 35초간 `1,272.6만 건`)**를 처리하며 클러스터 **`Gateway CPU`가 `95.37%`**, **`Backend CPU`가 `78.29%`**에 도달해 물리적 CPU 포화 상한에 걸렸다.
  - **`2 CU`**: 클러스터를 `2 CU`로 증설하자 `Gateway CPU`가 **`95.37% → 55.18%`**로 낮아지면서 Gateway 병목이 해소되었고 처리량이 **`448.275 MB/s`(`459,033.9 msg/s`)**까지 상승하며 이번에는 `Backend CPU`가 **`95.78%`**에 도달했다(`p95` 지연도 `47.75 ms → 37.74 ms`로 단축).
  - **`4 CU`**: 클러스터를 `4 CU`로 증설하자 처리량이 **`708.380 MB/s`(`725,381.4 msg/s`, 순간 피크 `830.97 MB/s`, 35초간 `2,542.8만 건` / `26.29 GB`)**까지 도약했으며 이때 `Gateway CPU`는 `51.95%`, `Backend CPU`는 `84.61%`를 기록했다.
  - **`8 CU`**: 클러스터를 `8 CU`로 증설하자 `64p` 기준 처리량이 **`897.719 MB/s`(`919,263.9 msg/s`, 35초간 `3,222.0만 건`)**까지 상승하면서도 `Gateway CPU`는 `48.19%`, `Backend CPU`는 `64.79%`에 머물러 `64`개 파티션만으로는 `8 CU` 클러스터의 CPU(`70%` 임계치)를 다 채우지 못함을 확인했다.

---

### Dedicated 클러스터(1 → 2 → 4 → 8 CU)의 파티션 수(4 → 256)별 병목과 포화 수렴 실측

동일한 페이로드(`1,024 Byte` 파이프 구분자 T-Log)와 배치 크기(`100 KB` = `100건`) 조건에서 토픽 파티션 수를 `4개`(`telemetry-p4`), `16개`(`telemetry-p16`), `32개`(`telemetry-p32`), `64개`(`telemetry-p64`), `128개`(`telemetry-p128`), `256개`(`telemetry-p256`)로 늘려가며 클러스터 용량(`1 CU → 2 CU → 4 CU → 8 CU`)별 최대 처리 한계와 실제 브로커 `CPU`(`Gateway / Backend Max %`)가 어디서 완전히 수렴(Plateau)하는지 측정했다.

| 토픽 파티션 구성 (`100 KB` 배치 고정) | **`1 CU`** 실측 (`MB/s` / `GW·BE CPU %`) | **`2 CU`** 실측 (`MB/s` / `GW·BE CPU %`) | **`4 CU`** 실측 (`MB/s` / `GW·BE CPU %`) | **`8 CU`** 실측 (`MB/s` / `GW·BE CPU %`) | 실측 분석 및 포화 수렴 판정 |
|---|---:|---:|---:|---:|---|
| **`4 Partitions` (`telemetry-p4`)** | **47.331 MB/s** (`14.7% / 13.1%`) | **45.164 MB/s** (`7.8% / 9.2%`) | **46.431 MB/s** (`7.3% / 10.0%`) | **46.417 MB/s** (`10.4% / 7.6%`) | **`1→8 CU` 증설 효과 0% (`~46 MB/s` 고정)**. 클러스터 CPU는 `7~14%`로 유휴 상태이나 4개 파티션 직렬화 상한에 막힘 |
| **`16 Partitions` (`telemetry-p16`)** | **180.244 MB/s** (`40.0% / 42.8%`) | **177.623 MB/s** (`25.2% / 29.1%`) | **180.601 MB/s** (`18.2% / 35.0%`) | **179.640 MB/s** (`12.9% / 23.0%`) | **`1→8 CU` 증설 시 처리량(`~180 MB/s`) 정체**, 브로커 CPU만 `42.8% → 23.0%`로 낮아짐 |
| **`32 Partitions` (`telemetry-p32`)** | **298.483 MB/s** (`76.2% / 78.7%`) | **310.366 MB/s** (`39.8% / 64.8%`) | **316.076 MB/s** (`31.6% / 57.4%`) | **332.533 MB/s** (`22.3% / 32.2%`) | `1 CU`만 CPU `78.7%`로 스케일 아웃 임계치(`70%`)를 돌파하고 `2·4·8 CU`는 32개 파티션 파이프라인 한계(`~310~333 MB/s`)에 머묾 |
| **`64 Partitions` (`telemetry-p64`)** | **354.781 MB/s** (**`95.4% / 78.3%`**) | **448.275 MB/s** (`55.2% / `**`95.8%`**) | **708.380 MB/s** (`52.0% / `**`84.6%`**) | **897.719 MB/s** (`48.2% / 64.8%`) | `1·2 CU`는 CPU `95%+` 포화 진입, `4 CU`(`708.4 MB/s`)와 `8 CU`(`897.7 MB/s`)는 크게 도약하나 `8 CU`는 아직 CPU `64.8%`로 여유 존재 |
| **`128 Partitions` (`telemetry-p128`)** | **379.685 MB/s** (**`96.6% / 84.8%`**) | **473.768 MB/s** (`64.0% / `**`86.0%`**) | **828.682 MB/s** (`61.3% / `**`92.7%`**) | **965.510 MB/s** (`50.0% / `**`70.9%`**) | `1·2 CU` 수렴 완료, **`4 CU`는 CPU `92.7%`로 최대 처리 한계(`828.7 MB/s`) 도달**, `8 CU`는 `965.5 MB/s`(분당 `35.74 GB`)로 상승하며 CPU `70.9%` 진입 |
| **`256 Partitions` (`telemetry-p256`)** | **364.288 MB/s** (**`94.6% / 79.0%`**) | **453.473 MB/s** (`71.7% / `**`86.0%`**) | **776.018 MB/s** (`53.5% / `**`89.0%`**) | **1,000.201 MB/s** (`53.6% / `**`81.0%`**) | `1·2·4 CU`는 추가 상승 없이 수렴 완료된 반면 **`8 CU`는 256개 파티션 병렬성을 활용해 `1,000.2 MB/s` (`1.00 GB/s`, 초당 `102.4만 건`, 분당 `36.42 GB`, `Backend CPU 81.0%`) 도달** |

![실험 2: 토픽 파티션 수(4 -> 256) 증가에 따른 1 CU · 2 CU · 4 CU · 8 CU 처리량 포화 수렴 및 브로커 CPU 한계 비교](images/02_partition_bottleneck.png)

- **`4개 → 32개` 파티션 구간 (파티션 병목 구간)**: `telemetry-p4`(`4` 파티션)와 `telemetry-p16`(`16` 파티션)에서는 클러스터를 `1 CU`에서 `8 CU`로 8배 증설해도 처리량이 각각 **`47.33 → 45.16 → 46.43 → 46.42 MB/s`** 및 **`180.24 → 177.62 → 180.60 → 179.64 MB/s`**로 동일했다. Azure Monitor의 클러스터 `CPU` 역시 `8 CU` 기준 `4p`에서 `10.4%`, `16p`에서 `23.0%`, `32p`에서 `32.2%`에 머물렀다. 클러스터 컴퓨팅 용량(`CU`)이 남아돌아도 개별 파티션의 순서 보장 커밋 파이프라인이 먼저 포화되면 `CU` 증설만으로는 처리량이 늘어나지 않는다.
- **`64개 → 128개 → 256개` 파티션 구간 (CU별 최대 처리 한계 포화 수렴 및 `4 CU → 8 CU` 비선형 스케일링)**:
  - **`1 CU`의 포화 수렴 (`~355~380 MB/s`)**: `64p`에서 이미 `Gateway CPU`가 `95.37%`(`354.781 MB/s`)에 도달했기 때문에 파티션을 `128p`와 `256p`로 2배·4배 늘려도 **`379.685 MB/s` (`+7.0%`) → `364.288 MB/s` (`-4.1%`)**에서 수평으로 수렴했다.
  - **`2 CU`의 포화 수렴 (`~448~474 MB/s`)**: `64p`에서 `Backend CPU`가 `95.78%`(`448.275 MB/s`)에 도달한 뒤 `128p`와 `256p`에서 각각 **`473.768 MB/s` (`+5.7%`) → `453.473 MB/s` (`-4.3%`)**로 수렴했다.
  - **`4 CU`의 도약 및 포화 수렴 (`708.4 → 828.7 → 776.0 MB/s`)**: `64p` 시점에 아직 CPU 여유(`Backend CPU 84.61%`)가 남아 있던 `4 CU`는 `128p`에서 **`828.682 MB/s`(`848,571.0 msg/s`, 순간 피크 `882.45 MB/s`, 분당 유입 `29.12 GB`, `Backend CPU 92.66%`)**까지 상승하며 최대 처리 한계에 도달했고 `256p`에서는 **`776.018 MB/s`**로 완전히 수렴했다.
  - **`8 CU`의 `1.00 GB/s` 도달과 `4 CU → 8 CU` 비선형 특성**: `8 CU` 클러스터는 `64p`(`897.719 MB/s`, `CPU 64.79%`)와 `128p`(`965.510 MB/s`, `CPU 70.90%`)를 거쳐 `256p`에서 **`1,000.201 MB/s`(`1.00 GB/s`, `1,024,205.4 msg/s`, 분당 유입 `36.42 GB`, `Backend CPU 81.02%`)**에 도달했다. 단일 클러스터를 `4 CU → 8 CU`로 증설할 때 처리량이 단순 정량 2배가 되지 않고 `828.7 → 1,000.2 MB/s`로 수렴하는 이유는 파티션당 커밋 로그 직렬화 한계와 클러스터 CPU 85~96% 도달 시 브로커가 `ACK` 응답을 지연시켜 유입 속도를 제어하는 자체 보호 동작이 함께 작용하기 때문이다.

---

### Dedicated 2 CU 환경의 파이프(|) 평문 단건·배치·Gzip 압축 전송(Kafka 9093) 실측

Dedicated `2 CU` 클러스터의 Event Hubs Kafka 엔드포인트(`9093`, `SASL_SSL`, `telemetry-p64`)로 `1,024 Byte` 파이프(`|`) 구분자 텍스트 로그를 속도 제한 없이 전송할 때 배치(`linger.ms=20`, `batch.size=65536`)와 `compression.type=gzip` 설정이 논리적 처리량, 와이어 바이트, 실제 Dedicated 클러스터 `CPU`에 미치는 영향을 측정했다.

| 전송 모드 (Kafka 9093, `Dedicated 2 CU`) | 압축 및 배치 설정 | 원본 로그 처리량 (`Logical MB/s`) | 브로커 네트워크 유입 (`Wire MB/s`) | 압축률 (와이어 절감률) | 초당 이벤트 수 (`Events/s`) | 전송 지연 `p50 / p95 / p99` (`ms`) | 클러스터 CPU (`Gateway / Backend Max %`) |
|---|---|---:|---:|---|---:|---:|---:|
| **`plain_single` (평문 단건)** | `none`, `linger.ms=0`, `batch.num.messages=1` | **2.525 MB/s** | **2.525 MB/s** | `1.00x` (`0%`) | 2,584.3 msg/s | 4.76 / 16.98 / 22.19 | **`12.55% / 20.01%`** |
| **`plain_batched` (평문 배치)** | `none`, `linger.ms=20`, `64 KB` 배치 | **360.225 MB/s** | **360.225 MB/s** | `1.00x` (`0%`) | 368,870.9 msg/s | 19.76 / 31.78 / 42.43 | **`54.94% / 59.07%`** |
| **`gzip_batched` (Gzip 배치)** | `gzip`, `linger.ms=20`, `64 KB` 와이어 배치 | **502.410 MB/s** | **97.882 MB/s** | **`5.13x` (`-80.5%`)** | **514,467.6 msg/s** | 71.56 / 100.41 / 152.55 | **`38.83% / 62.64%`** |

![실험 3: Kafka 9093 파이프(|) T-Log 평문 단건 vs 배치 vs Gzip 압축 실측](images/03_gzip_vs_plain_throughput.png)

- **배치 및 Gzip 압축의 극적인 처리량 향상(`2.53 → 360.23 → 502.41 MB/s`)**: In-Region 환경에서도 `plain_single`은 매 메시지마다 커밋 RTT(`4.76 ms`)를 대기하느라 `2.525 MB/s`(`2,584.3 msg/s`)에 머물면서도 초당 요청 프레임 오버헤드로 인해 `Backend CPU`를 `20.01%`나 소모했다. `plain_batched`(`64 KB` 배치)를 적용하자 처리량이 **`360.225 MB/s`(`368,870.9 msg/s`, 단건 대비 142.7배)**로 급증했다. 여기에 `gzip_batched`를 적용하자 파이프(`|`) 구분자 텍스트 로그가 **`5.13:1`(`-80.5%`)**로 압축되면서 브로커 와이어 유입량은 **`97.882 MB/s`**로 평문 배치 대비 **72.8% 감소**한 반면 원본 로그 기준 논리적 처리량은 **`502.410 MB/s`(`514,467.6 msg/s`, 35초간 `1,803.6만 건`)**까지 상승했다.
- **`IncomingBytes`만 보면 Dedicated `CU` 사용률을 오판하는 이유**: `gzip_batched` 구간에서 네트워크로 유입되는 바이트(`Wire MB/s`)는 **`97.882 MB/s`**(Azure Monitor 분당 `5.92 GB`)로 `plain_batched`(`360.225 MB/s`, 분당 `10.35 GB`)의 1/3 이하로 줄어들고 `Gateway CPU`도 `54.94% → 38.83%`로 낮아졌지만 초당 유입 메시지 수가 `368,870.9 msg/s → 514,467.6 msg/s`(분당 `1,000만 건 → 2,098만 건`)로 증가함에 따라 스토리지 인덱싱·처리를 담당하는 **`Backend CPU`는 오히려 `59.07%(평균 18.22%) → 62.64%(평균 22.60%)`로 상승**했다. Gzip 압축 파이프라인에서 Azure Portal의 `IncomingBytes` 그래프 하나만 보고 클러스터 축소(`Scale-in`)를 결정하면 안 되며 반드시 **클러스터 `CPU`(`Role=Backend, Gateway`) 사용률(%)**과 **초당 메시지 처리율(`IncomingMessages/s`)**을 함께 평가해야 한다.

---

## 3. OTel Collector Contrib·VictoriaMetrics·Grafana 기반 실효 CU 사용률 모니터링

Azure Portal 기본 메트릭 창에서는 할당된 `CU`/`PU` 대비 현재 몇 %의 실효 용량을 쓰고 있는지와 Kafka Consumer Group Lag을 한 화면에서 대조할 수 없다. 또한 단일 게이트웨이 VM에서 `OpenTelemetry Collector` 하나로 모든 메트릭을 수집해 인메모리 큐로 내보내면 수집 대상이나 카디널리티가 늘어날 때 스크래핑 주기가 `10초 → 60초`로 밀리거나 큐 포화(`otelcol_exporter_queue_size == otelcol_exporter_queue_capacity`)로 메트릭이 조용히 Drop된다.

### 단일 OTel 게이트웨이 큐 지연·Drop 원인과 분리형 아키텍처

```text
[Azure Monitor REST API (PT1M)] ──► [OTel Gateway #1: azuremonitorreceiver] ──┐
                                      (60s 간격, 리소스 CPU/Bytes/Throttled)   │  Prometheus Remote Write
                                                                              ├──► [VictoriaMetrics Cluster] ──► [Grafana]
[Event Hubs Kafka 9093 SASL_SSL] ──► [OTel Gateway #2: kafkametricsreceiver] ──┘    (vminsert -> vmstorage <- vmselect)
                                      (15s 간격, 토픽 오프셋·Consumer Lag 전용)
```

1. **수집 주기와 프로토콜이 다른 Receiver 분리**:
   - `azuremonitorreceiver`는 [Azure Monitor Event Hubs 플랫폼 메트릭](https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference#supported-metrics-for-microsofteventhubclusters)(집계 입도 `PT1M`)을 호출하므로 `collection_interval: 60s`가 적합하다.
   - `kafkametricsreceiver`는 Event Hubs Kafka 엔드포인트(`9093`)에 접속해 파티션별 최신 오프셋(`current_offset`, `log_end_offset`)과 컨슈머 그룹 지연(`kafka_consumer_group_lag`)을 `15s` 주기로 수집한다.
   - 두 파이프라인을 분리하고 `remote_write_queue`(큐 크기 `10,000`, 병렬 컨슈머 `8`)와 `memory_limiter`를 적용하면 API 응답 지연이 Kafka Lag 수집 주기를 블로킹하지 않는다.
2. **VictoriaMetrics 클러스터(`vminsert` / `vmstorage` / `vmselect`) 구성**:
   - 토픽·파티션(`EntityName`) × 컨슈머 그룹 카디널리티가 높은 환경에서는 AKS 위에 쓰기 경로(`vminsert`)와 읽기 경로(`vmselect`), 상태 저장소(`vmstorage` StatefulSet)를 분리해 수평 확장한다.

### Grafana 3대 실효 용량 사용률(%) PromQL 수식

할당된 `CU`(또는 `PU`)를 축소·증설할지 판단하려면 아래 3가지 사용률(%) 중 가장 높은 값(`max`)을 기준으로 삼는다.

| 지표 구분 | 의미 및 임계치 기준 | PromQL 수식 (`VictoriaMetrics` / `Grafana`) |
|---|---|---|
| **① 컴퓨팅 포화도 (%)** | 브로커 전용 CPU·메모리 사용률. Microsoft 공식 문서 기준 **CPU 70% 도달 시 스케일 아웃 검토**, **40% 이하 지속 시 스케일 인(축소) 후보** | `max by (resource_name, role) (azure_eventhub_clusters_cpu_maximum or azure_eventhub_namespaces_namespace_cpu_usage_maximum)` |
| **② 할당 CU 대역폭 사용률 (%)** | 할당된 `CU`의 보수적 하한(`1 CU = 100 MB/s`) 대비 현재 유입 바이트 비율 (Gzip 사용 시 원본 압축률을 곱해 보정 가능) | `(sum by (resource_name) (rate(azure_eventhub_namespaces_incoming_bytes_total[1m])) / ($allocated_cu * 100 * 1024 * 1024)) * 100` |
| **③ 파티션 상한 사용률 (%)** | 토픽의 활성 파티션 수(`$partition_count × 1.5 MB/s`) 대비 현재 유입 바이트 비율. **80% 초과 시 CU 증설이 아닌 파티션 증설 필요** | `(sum by (entity_name) (rate(azure_eventhub_namespaces_incoming_bytes_total[1m])) / ($partition_count * 1.5 * 1024 * 1024)) * 100` |
| **④ OTel 큐 점유율 및 Drop 감시** | 수집기 자체 인메모리 큐 포화율(`80%` 이상 경고) 및 분당 유실 메트릭 포인트 수(`0`이어야 정상) | `(otelcol_exporter_queue_size / otelcol_exporter_queue_capacity) * 100` 및 `rate(otelcol_exporter_enqueue_failed_metric_points_total[1m]) * 60` |

![실험 4 (실측 베이스라인 기반 4단계 용량 사용률·OTel 큐 평가 모델): CU/PU 실효 용량 사용률 3대 지표 시계열 및 OTel Collector 큐 적체 비교](images/04_effective_capacity_utilization.png)

위 실험 4 그래프는 실험 1~3에서 측정한 Dedicated `1 CU` 실측 피크 처리량(`354.78 MB/s`)과 `4p` 파티션 상한(`47.33 MB/s`)을 베이스라인으로 삼아 4단계 운영 시나리오(① 평시 베이스라인 → ② 정상 피크 → ③ 소수 파티션 편중 버스트 → ④ 다중 컨슈머·컴팩션 동시 부하)를 모사한 실측 베이스라인 기반 4단계 용량 사용률 및 OTel 큐 평가 모델이다. 시계열(`00:06~00:08` 구간)에서 보듯 클러스터 전체 대역폭 사용률(파란색 선)이 `72.9~82.0%`이고 CPU(빨간색 선)가 `78.7~85.6%`일 때 특정 토픽의 파티션 편중이 발생하면 ③ 파티션 상한 사용률(주황색 점선)이 `115.0%`로 먼저 치솟는다. 대시보드가 세 지표를 분리해 보여주면 운영자는 불필요하게 `CU`를 증설하는 대신 해당 토픽의 파티션 수나 파티션 키 분산을 교정할 수 있다.

---

## 4. 파이프(|) 평문 로그의 Schema Registry·Apache Avro 전환 구조

파이프(`|`) 구분자 평문 로그를 Gzip으로 압축해 전송하는 구조는 네트워크 바이트를 줄이는 데는 효과적이지만 하위 컨슈머(Spark, Databricks, 스트리밍 ETL)가 매번 전체 Gzip 블록을 압축 해제하고 문자열 `split('|')`으로 파싱한 뒤 타입을 변환해야 하므로 하위 컴퓨팅 비용과 스키마 파손 위험이 크다.

| 비교 항목 | 현행: 파이프(`\|`) 구분자 평문 + Gzip | 권장: Event Hubs Schema Registry + Apache Avro |
|---|---|---|
| **메시지당 스키마 메타데이터** | 매 레코드마다 텍스트 포맷·구분자 반복 (순서 변경 시 하위 파서 장애) | 페이로드에는 `Schema ID(GUID)` 참조만 포함, 본문은 순수 이진(Binary) 직렬화 |
| **직렬화 크기 및 CPU 효율** | Gzip 블록 압축 시 크기는 작으나 브로커·컨슈머 양측의 압축/해제 CPU 부하 높음 | 단일 레코드 자체 크기가 평문 대비 50~70% 작으며, 블록 압축 없이도 높은 처리량 달성 |
| **스키마 진화(Schema Evolution)** | 컬럼 추가·순서 변경 시 Producer와 모든 Consumer 동시 배포 필요 | `Azure Schema Registry`에서 Backward/Forward 호환성 검증 및 버전 관리(`Standard/Premium/Dedicated` 모두 기본 지원, Dedicated 최대 `1,000개` 스키마 그룹 무료 포함) |

`Event Hubs Dedicated` 및 `Premium` 티어는 추가 비용 없이 내장 [Azure Schema Registry](https://learn.microsoft.com/azure/event-hubs/schema-registry-overview)를 제공한다. 차기 파이프라인 고도화 시점에 Producer SDK에서 `Apache Avro` 직렬화를 적용하면 네트워크 대역폭과 하위 Databricks/컨슈머 파싱 CPU를 동시에 절감할 수 있다.

---

## 5. 샘플 패키지와 재현 구성

이 문서의 Bicep 인프라 템플릿, AMQP/Kafka 부하 생성기(`load_generator.py`), 차트 렌더러(`plot_results.py`), `OpenTelemetry Collector Contrib` + `VictoriaMetrics` + `Grafana` 설정 파일은 페이지 하단의 관련 샘플 카드(`cu-benchmark-and-otel-vm-stack`)에서 확인할 수 있다.

- `infra/main.bicep` & `infra/deploy.sh`: `Standard(TU)` / `Premium(PU)` 즉시 배포 및 `--include-dedicated` 전용 4시간 최소 과금 가드레일 스크립트
- `benchmark/load_generator.py` & `benchmark/plot_results.py`: 4대 실험 자동 측정 및 `results/charts/*.png` 그래프 생성기
- `monitoring/otel-collector-config.yaml`, `monitoring/docker-compose.yml`, `monitoring/victoriametrics/vmcluster-aks.yaml`, `monitoring/grafana/dashboards/eventhubs-cu-utilization.json`: 즉시 기동 가능한 모니터링 스택과 대시보드 JSON
