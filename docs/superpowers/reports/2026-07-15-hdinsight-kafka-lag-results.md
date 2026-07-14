# HDInsight Kafka Lag 축소 실증 테스트 — 결과

- 실행일: 2026-07-15 | 리전: japaneast | 클러스터: `krafton-kafka-hdi-68944`
- 목표: consumer lag **"1분 이내 회복"** 가능성을 축소 테스트로 실증
- 테스트베드: 브로커 3 × `Standard_D4ads_v5` (16 GB RAM, 데이터디스크 2/노드), 토픽 `lag-test` (30 파티션, RF 2)
- 실행 경로: 프라이빗 클러스터 → 로드젠 VM(`vm-kafka-loadgen`, D8s_v5) `run-command` 경유, 모니터링 Prometheus+Grafana(`vm-monitoring`)

## 한눈에 보기

| Arm | 구성 | 부하(produce) | Peak lag | 회복시간 | 판정 |
|---|---|---|---|---|---|
| Baseline | 16GB×3 | 1688 msgs/s = 16.5 MB/s (100%) | 261,542 msgs (2.5 GB) | **463s (7.7분)** | ❌ 재현 |
| Arm A-75 | 16GB×3 | 1266 msgs/s = 12.4 MB/s (75%) | — | — | ⏳ |
| Arm A-50 | 16GB×3 | 844 msgs/s = 8.2 MB/s (50%) | — | — | ⏳ |
| Arm A-40 | 16GB×3 | 675 msgs/s = 6.6 MB/s (40%) | — | — | ⏳ |
| Arm A-30 | 16GB×3 | 506 msgs/s = 4.9 MB/s (30%) | — | — | ⏳ |
| Arm B | 32GB×3 | 1688 msgs/s = 16.5 MB/s (100%) | — | — | ⏳ (게이트) |

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

### Arm A (부하 축소 75/50/40/30%) — ⏳ 실행 중

_(완료 시 각 Arm의 peak lag / 회복시간 / build·drain slope 기록)_

## 결론 및 프로덕션 권고

_(Phase 4에서 작성)_

## 후속 (오늘 범위 밖)

- **Arm B**: 브로커 RAM 2배(32 GB) — 페이지캐시 확대로 동일 부하에서 회복 개선 확인
- **Arm C**: Premium SSD 디스크 tier 효과 — HDInsight Kafka 데이터디스크의 Premium 지원 확인 후
- **Arm D**: AKS + 실제 rdkafka 컨슈머 fetch 파라미터 튜닝 검증
