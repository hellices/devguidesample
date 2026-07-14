# HDInsight Kafka Lag 축소 실증 테스트 — 결과

- 실행일: 2026-07-15 | 리전: japaneast | 클러스터: `krafton-kafka-hdi-68944`
- 목표: consumer lag **"1분 이내 회복"** 가능성을 축소 테스트로 실증
- 테스트베드: 브로커 3 × `Standard_D4ads_v5` (16 GB RAM, 데이터디스크 2/노드), 토픽 `lag-test` (30 파티션, RF 2)
- 실행 경로: 프라이빗 클러스터 → 로드젠 VM(`vm-kafka-loadgen`, D8s_v5) `run-command` 경유, 모니터링 Prometheus+Grafana(`vm-monitoring`)

## 한눈에 보기

| Arm | 구성 | 부하(produce) | Peak lag | 회복시간 | 판정 |
|---|---|---|---|---|---|
| Baseline | C=5.5MB/s | 1688 msgs/s = 16.5 MB/s (100%) | 261,542 msgs (2.5 GB) | **463s (7.7분)** | ❌ 재현 |
| Arm A-75 | C=5.5MB/s | 1266 msgs/s = 12.4 MB/s (75%) | 162,188 msgs (1.5 GB) | **298s (5.0분)** | ❌ |
| Arm A-50 | C=5.5MB/s | 844 msgs/s = 8.2 MB/s (50%) | 65,769 msgs (0.6 GB) | **116s (1.9분)** | ⚠️ |
| Arm A-40 | C=5.5MB/s | 675 msgs/s = 6.6 MB/s (40%) | 32,875 msgs (0.3 GB) | **49s** | ✅ |
| Arm A-30 | C=5.5MB/s | 506 msgs/s = 4.9 MB/s (30%) | 2,455 msgs (~0) | **0s** | ✅ |
| Cap-4MB | C=11MB/s | 1688 msgs/s = 16.5 MB/s (100%) | 120,927 msgs (1.2 GB) | **116s (1.9분)** | ⚠️ |
| Cap-5MB | C=13.7MB/s | 1688 msgs/s = 16.5 MB/s (100%) | 53,568 msgs (0.5 GB) | **33s** | ✅ |

판정 범례: ✅ 회복<60s · ⚠️ 1–3분 · ❌ >3분(=재현) · ⏳ 미실행

**실험 설계 (결정론적):** 고객 컨슈머(rdkafka pod)는 메시지당 anticheat 처리로 **처리 바운드**라 raw 처리량(272 MB/s)이 병목이 아니다. 실제 병목을 재현하려고 **컨슈머 처리 용량을 고정**하고 **프로듀서 부하율만 Arm별로 축소**한다. 컨슈머 용량은 브로커 `consumer_byte_rate` 쿼터로 고정: **2 MB/s/broker × 3 broker ≈ 5.5 MB/s (≈559 msgs/s)**. (주의: Kafka 쿼터는 브로커별로 독립 적용되므로 총 용량 = 쿼터 × 브로커 수.) 이 고정 컨슈머 대비 유입률을 100→30%로 낮춰 회복시간 변화를 실측한다.

- 이론: 회복시간 ≈ peak_lag / C, peak_lag ≈ (P − C) × burst. P가 C에 가까워질수록 peak·회복이 급감하고, **P ≤ C면 lag 자체가 발생하지 않음**.
- 실측 C ≈ 559 msgs/s (baseline build slope 1129 msgs/s = 1688 − 559에서 역산). 임계는 부하율 ≈ C/1688 ≈ **33%** 부근으로 예상.

## 환경 준비 (Phase 0) — ✅ 완료

- 로드젠 VM `Standard_B2s` → `Standard_D8s_v5` 리사이즈, 기동
- Kafka 3.2.0 클라이언트 + JDK 11 설치
- 브로커 검색: `wn0/wn1/wn2 (...):9092` (id 1001/1002/1003), 연결 확인
- 토픽 `lag-test` 생성 (30 파티션, RF 2, retention 36h, max.message 1MB)
- 컨슈머 쿼터: `consumer_byte_rate=2097152` (2 MB/s/broker), client.id `lagcons`
- 모니터링: Prometheus ready, kafka-exporter + JMX(b0/b1/b2) 타깃 `up`, Grafana health 200

## Arm별 상세

### Baseline (100%, 16.5 MB/s) — ❌ lag 재현 성공

- 프로듀서 1688 msgs/s × 10 KB = 16.5 MB/s, 240s burst (405k records)
- 컨슈머 고정 용량 ≈ 5.5 MB/s (559 msgs/s) → 유입이 처리를 ~1129 msgs/s로 초과 → lag 누적
- build slope 실측 ≈ 1129 msgs/s (t=34s 38,490 → t=100s 112,983)
- **peak lag 261,542 msgs ≈ 2.5 GB** (burst 종료 t=249s)
- 드레인 ≈ 562 msgs/s (= 고정 컨슈머 용량) → lag≤2000 복귀 → **회복 463s ≈ 7.7분**
- → 프로덕션 관측 "피크 시 약 7분 lag"와 **정합**. 축소 테스트베드가 프로덕션 동역학을 재현함을 확인.

### Arm A (부하 축소 75/50/40/30%, 컨슈머 용량 C=5.5MB/s 고정) — ✅ 완료

| Arm | 부하율 | 부하 | Peak lag | 회복 | 판정 |
|---|---|---|---|---|---|
| A-75 | 75% | 12.4 MB/s | 162,188 msgs (1.5 GB) | 298s (5.0분) | ❌ |
| A-50 | 50% | 8.2 MB/s | 65,769 msgs (0.6 GB) | 116s (1.9분) | ⚠️ |
| A-40 | 40% | 6.6 MB/s | 32,875 msgs (0.3 GB) | **49s** | ✅ |
| A-30 | 30% | 4.9 MB/s | 2,455 msgs (~0) | **0s** | ✅ |

- **부하율이 낮아질수록 peak lag·회복시간이 단조 감소.** 회복시간 ∝ peak_lag ∝ (P − C).
- **1분 임계**는 40%~50% 부하 사이(≈ C/P_base ≈ 33%보다 약간 위, 실측 ~45%). 즉 이 테스트베드에서 유입을 **약 40% 이하로 줄이면 <60s** 회복.
- **P ≤ C(30% arm)면 lag 자체가 미발생** — 유입이 컨슈머 처리 용량 이하이므로 큐잉 없음.
- **함의:** 부하 축소는 확실히 효과적이나, 고객의 12TB 로그는 비즈니스 데이터라 40% 감축은 비현실적. → 실효 레버는 **컨슈머 처리 용량(C) 증대** (아래 Cap arm).

### Arm Cap (부하 100% 고정, 컨슈머 용량 증대) — ✅ 완료

| Arm | 컨슈머 용량 C | 부하 | Peak lag | 회복 | 판정 |
|---|---|---|---|---|---|
| Baseline | 5.5 MB/s (1×) | 16.5 MB/s (100%) | 261,542 msgs (2.5 GB) | 463s (7.7분) | ❌ |
| Cap-4MB | ~11 MB/s (2×) | 16.5 MB/s (100%) | 120,927 msgs (1.2 GB) | 116s (1.9분) | ⚠️ |
| Cap-5MB | ~13.7 MB/s (2.5×) | 16.5 MB/s (100%) | 53,568 msgs (0.5 GB) | **33s** | ✅ |

- **부하를 전혀 줄이지 않고도**, 컨슈머 처리 용량을 **약 2.5배**로 올리면 회복 **463s → 33s (<60s)**.
- 회복시간 ≈ peak_lag / C, peak_lag ≈ (P − C)×burst. C를 키우면 **분자(peak)는 줄고 분모(drain)는 커져** 이중으로 회복이 빨라짐.
- 임계(<60s)는 C ≈ 2.3× (≈12.7 MB/s, drain으로 역산한 실효 C 기준) 부근.
- **이것이 고객의 실효 해법**: 12TB 로그 유입은 못 줄이므로, 축을 컨슈머/브로커 **처리 용량 증대**로 잡아야 함.

## 결론 및 프로덕션 권고

### 실증된 두 레버 (테스트베드 3브로커·16GB 기준)

| 레버 | 방법 | 회복 <60s 조건 | 고객 적용성 |
|---|---|---|---|
| ① 유입 축소 | produce 부하율 ↓ | 부하 ≤ ~40% | ❌ 비현실적(12TB 로그=비즈니스 데이터) |
| ② 처리 용량 증대 | 컨슈머/브로커 throughput ↑ | C ≥ ~2.5× | ✅ 실효 레버 |

두 레버 모두 **회복시간 ∝ (P − C)** 라는 동일한 물리에서 나옴. 고객은 P를 못 낮추므로 **C를 키우는 방향**이 유일하게 현실적.

### 고객 상황(18 broker / 180 partition / 240 pod)에 대한 진단

- **컨슈머 pod 증설은 이미 무효 구간.** 파티션 180개가 병렬성 상한 → 활성 컨슈머 최대 180. 현재 240 pod 중 **60개는 idle**. pod을 더 붙여도 처리 용량(C)은 안 늘어남.
- 고객 컨슈머는 rdkafka로 메시지당 anticheat 처리를 하는 **처리 바운드**. 따라서 C를 키우려면 **병렬 처리 슬롯(=파티션)** 또는 **슬롯당 처리속도**를 올려야 함.

### 권고 (우선순위)

1. **파티션 증설이 1순위 레버.** 180 → **약 360~540** (테스트에서 <60s에 필요했던 ~2.3–2.5× C에 대응). 파티션을 늘리면 (a) 놀고 있는 60 pod가 즉시 활성화되고 (b) 추가 pod 투입으로 병렬 처리 슬롯이 선형 증가 → 실효 C 상승. **가장 저렴하고 즉효.**
   - 주의: 파티션 증가는 되돌리기 어렵고, key 기반 순서 보장이 있으면 재해싱 영향 검토 필요. anticheat 로그가 순서 무관이면 부담 적음.
2. **브로커 fetch 용량 보강 (파티션 증설과 병행).** 피크에 lag 데이터가 page cache를 벗어나면 컨슈머 catch-up이 디스크 read 바운드가 됨.
   - 브로커 **RAM ↑** (page cache로 hot segment 유지 → 재읽기 시 디스크 우회),
   - **데이터 디스크 tier ↑** (Premium SSD v2 등 IOPS/throughput),
   - 또는 **브로커 대수 ↑** (파티션 리더 분산).
3. **rdkafka 컨슈머 튜닝.** `fetch.message.max.bytes` / `queued.min.messages` / `fetch.wait.max.ms` 조정으로 fetch batch 키우고, pod당 CPU를 확보해 메시지당 처리속도(처리 바운드 완화)를 올림.
4. **모니터링 상시화.** 파티션별 consumer lag, 브로커 page cache hit·디스크 read throughput, consumer fetch latency를 피크(15:30) 구간에 관찰 → 병목이 fetch(브로커)인지 처리(pod CPU)인지 구분.

### 프로덕션 환산 주석

- 테스트베드는 3브로커·16GB로 고객(18브로커)의 1/6 규모. 절대 수치가 아닌 **비율(부하율·용량배수)과 물리 관계**를 실증한 것.
- 고객 피크 7분 lag는 테스트 Baseline 7.7분과 **정성·자릿수 정합** → 축소 모델의 타당성 확인.
- "1분 이내"는 **C를 약 2.3–2.5배** 확보하면 달성 가능(테스트 Cap-5MB=33s). 파티션 증설+브로커 보강 조합으로 현실화.

## 정리(Teardown) 상태

- 로드젠/모니터링/점프박스 VM: **deallocated** (비용 정지)
- HDInsight 클러스터 `krafton-kafka-hdi-68944`: **유지 중** (후속 파티션/브로커 arm 대비). HDInsight는 중지가 불가하고 시간당 과금되므로, 후속 테스트 계획이 없으면 아래로 삭제:

```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944
# 리소스그룹 통째 정리(스토리지·VM·Grafana 포함):
# az group delete -n rg-krafton-kafka-dev-jpe --yes
```
- 재생성 필요 시: 세션 파일 `recreate-public.sh` + `hdi-kafka-template-public.json` 사용.

## 후속 (오늘 범위 밖)


- **브로커 스펙 arm (RAM 32GB / Premium SSD v2):** 컨슈머 용량을 쿼터로 고정한 본 테스트에선 브로커 RAM 효과가 드러나지 않음(회복 = peak/C, C 고정). 실측하려면 쿼터를 풀고 lag 데이터가 page cache를 초과하도록 대용량 burst를 걸어 **디스크 read 바운드 catch-up**을 재현해야 함 → 별도 테스트.
- **파티션 증설 arm:** 180→360→540 파티션에서 동일 부하의 회복 곡선 실측(권고 ①의 정량 근거 강화).
- **Arm D:** AKS + 실제 rdkafka 컨슈머로 fetch 파라미터·pod CPU 튜닝 효과 검증.
