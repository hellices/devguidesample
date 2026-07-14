# HDInsight Kafka Lag 축소 실증 테스트 — 결과

- 실행일: 2026-07-15 | 리전: japaneast | 클러스터: `krafton-kafka-hdi-68944`
- 목표: consumer lag **"1분 이내 회복"** 가능성을 축소 테스트로 실증
- 테스트베드: 브로커 3 × `Standard_D4ads_v5` (16 GB RAM, 데이터디스크 2/노드), 토픽 `lag-test` (30 파티션, RF 2)
- 실행 경로: 프라이빗 클러스터 → 로드젠 VM(`vm-kafka-loadgen`, D8s_v5) `run-command` 경유, 모니터링 Prometheus+Grafana(`vm-monitoring`)

## 한눈에 보기

| Arm | 구성 | 부하(produce) | Peak lag | 회복시간 | 판정 |
|---|---|---|---|---|---|
| 캘리브레이션 | 16GB×3 | 상한 측정 | — | — | ⏳ |
| Baseline | 16GB×3 | 100% | — | — | ⏳ |
| Arm A-75 | 16GB×3 | 75% | — | — | ⏳ |
| Arm A-50 | 16GB×3 | 50% | — | — | ⏳ |
| Arm A-25 | 16GB×3 | 25% | — | — | ⏳ |
| Arm B | 32GB×3 | 100% | — | — | ⏳ (게이트) |

판정 범례: ✅ 회복<60s · ⚠️ 1–3분 · ❌ >3분 · ⏳ 미실행

## 환경 준비 (Phase 0) — ✅ 완료

- 로드젠 VM `Standard_B2s` → `Standard_D8s_v5` 리사이즈, 기동
- Kafka 3.2.0 클라이언트 + JDK 11 설치
- 브로커 검색: `wn0/wn1/wn2 (...):9092` (id 1001/1002/1003), 연결 확인
- 토픽 `lag-test` 생성 (30 파티션, RF 2, retention 36h, max.message 1MB)
- 모니터링: Prometheus ready, kafka-exporter + JMX(b0/b1/b2) 타깃 `up`, Grafana health 200

## Arm별 상세

_(각 Arm 실행 시 갱신: 실행 시각, produce 요약, lag 폴링 원자료, Grafana 관측)_

## 결론 및 프로덕션 권고

_(Phase 4에서 작성)_

## 후속 (오늘 범위 밖)

- **Arm C**: Premium SSD 디스크 tier 효과 — HDInsight Kafka 데이터디스크의 Premium 지원 확인 후
- **Arm D**: AKS + 실제 rdkafka 컨슈머 fetch 파라미터 튜닝 검증
