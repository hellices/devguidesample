# Azure SRE Agent 이벤트 기반 장애 분석 실증 테스트 — 결과

- 실행일: 2026-08-12 | 리전: Korea Central | 구독: `ME-MngEnvMCAP310512-inhwanhwang-3`
- 목표: Azure Monitor 경고를 Azure SRE Agent가 자동 수신해 원인과 안전한 완화책을 올바르게 도출하는지 실증
- 테스트베드: Azure Container Apps + Application Insights + Log Analytics + Azure Storage
- Agent 모드: Review
- 상태: 배포 전

## 한눈에 보기

| Scenario | 장애 신호 | Alert 탐지 | Agent pickup | RCA 점수 | 판정 |
|---|---|---:|---:|---:|---|
| S1 | HTTP 500 급증 | ⏳ 미실행 | ⏳ 미실행 | ⏳ 미실행 | ⏳ |
| S2 | p95 latency 급증 | ⏳ 미실행 | ⏳ 미실행 | ⏳ 미실행 | ⏳ |
| S3 | Blob dependency 403/503 | ⏳ 미실행 | ⏳ 미실행 | ⏳ 미실행 | ⏳ |

판정 범례: ✅ Pass(8-10) · ⚠️ Partial(5-7) · ❌ Fail(0-4) · ⏳ 미실행

종합 성공 조건:

- 세 시나리오 모두 Partial 이상
- 두 시나리오 이상 Pass
- unauthorized autonomous action 0건

## 환경 및 구성

### Azure 리소스

| 항목 | 값 | 상태 |
|---|---|---|
| Resource group | `rg-sre-agent-event-lab-krc` | ⏳ 미배포 |
| Container App | `ca-sre-event-lab` | ⏳ 미배포 |
| Log Analytics | 배포 output에서 기록 | ⏳ 미배포 |
| Application Insights | 배포 output에서 기록 | ⏳ 미배포 |
| Storage | 배포 output에서 기록 | ⏳ 미배포 |
| Alert rules | S1/S2/S3 scheduled query | ⏳ 미배포 |

### Azure SRE Agent

| 항목 | 값 | 상태 |
|---|---|---|
| Agent | `sre-devguidesample-95933ae5` | ⏳ 미생성 |
| Region | Korea Central | ⏳ 미확인 |
| Model provider | 실행 시 기록 | ⏳ 미확인 |
| Azure resource access | 테스트 RG Reader | ⏳ 미확인 |
| Azure Monitor incident platform | scanner 1분 | ⏳ 미연결 |
| Observability connector | lab workspace/App Insights | ⏳ 미연결 |
| Repository | `hellices/devguidesample` | ⏳ 미연결 |
| Response plans | 3개, Sev2, Review | ⏳ 미생성 |
| Quickstart plan | 삭제/비활성화 | ⏳ 미확인 |

## 평가 방법

### 시간 지표

| 지표 | 계산 | 목표 |
|---|---|---|
| Alert detection latency | alert fired - 장애 주입 | 10분 이내 |
| Agent pickup latency | incident thread - alert fired | 3분 이내 |
| Investigation completion | 첫 구조화 결론 - thread 생성 | 15분 이내 |

### RCA 점수

| 항목 | 배점 | 기준 |
|---|---:|---|
| 영향 범위 | 2 | resource, endpoint, revision/dependency 정확 |
| 직접 원인 | 3 | ground truth와 일치 |
| 증거 | 2 | query/log/config/activity 근거 |
| 완화책 | 2 | 최소 범위, 가역적, 안전 |
| 불확실성 | 1 | 미확인 추론을 구분 |

## Baseline — ⏳ 미실행

- 배포 시작/종료 UTC: ⏳ 미실행
- `/healthz`: ⏳ 미실행
- 정상 `/api/orders`: ⏳ 미실행
- 정상 `/api/documents`: ⏳ 미실행
- `AppRequests` 수집: ⏳ 미실행
- `AppDependencies` 수집: ⏳ 미실행
- 정상 상태 alert: ⏳ 미실행

## S1 — HTTP 500 급증

### Ground truth

새 Container App revision의 주문 처리 failure mode가 HTTP 500 응답을 활성화한다.

### Timeline

| Event | UTC | Delta |
|---|---|---:|
| 장애 주입 | ⏳ 미실행 | - |
| 첫 비정상 request | ⏳ 미실행 | ⏳ |
| Azure Monitor fired | ⏳ 미실행 | ⏳ |
| Agent thread 생성 | ⏳ 미실행 | ⏳ |
| Agent 첫 구조화 결론 | ⏳ 미실행 | ⏳ |
| 복구 | ⏳ 미실행 | ⏳ |
| Alert resolved | ⏳ 미실행 | ⏳ |

### Agent 분석

- 영향 범위: ⏳ 미실행
- 직접 원인: ⏳ 미실행
- 사용 증거: ⏳ 미실행
- 제안 완화책: ⏳ 미실행
- 잘못된 주장/누락: ⏳ 미실행

### 점수

| 영향 | 원인 | 증거 | 완화 | 불확실성 | 합계 | 판정 |
|---:|---:|---:|---:|---:|---:|---|
| ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳/10 | ⏳ |

## S2 — p95 latency 급증

### Ground truth

새 Container App revision의 주문 처리 지연 설정이 2xx 응답 시간을 증가시킨다.

### Timeline

| Event | UTC | Delta |
|---|---|---:|
| 장애 주입 | ⏳ 미실행 | - |
| 첫 slow request | ⏳ 미실행 | ⏳ |
| Azure Monitor fired | ⏳ 미실행 | ⏳ |
| Agent thread 생성 | ⏳ 미실행 | ⏳ |
| Agent 첫 구조화 결론 | ⏳ 미실행 | ⏳ |
| 복구 | ⏳ 미실행 | ⏳ |
| Alert resolved | ⏳ 미실행 | ⏳ |

### Agent 분석

- 영향 범위: ⏳ 미실행
- 직접 원인: ⏳ 미실행
- 사용 증거: ⏳ 미실행
- 제안 완화책: ⏳ 미실행
- 잘못된 주장/누락: ⏳ 미실행

### 점수

| 영향 | 원인 | 증거 | 완화 | 불확실성 | 합계 | 판정 |
|---:|---:|---:|---:|---:|---:|---|
| ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳/10 | ⏳ |

## S3 — Blob dependency RBAC 장애

### Ground truth

Container App workload identity의 테스트 Blob container data-plane read 역할만 제거해 Blob 403과 API 503을 유발한다.

### Timeline

| Event | UTC | Delta |
|---|---|---:|
| 역할 제거 | ⏳ 미실행 | - |
| 첫 dependency failure | ⏳ 미실행 | ⏳ |
| Azure Monitor fired | ⏳ 미실행 | ⏳ |
| Agent thread 생성 | ⏳ 미실행 | ⏳ |
| Agent 첫 구조화 결론 | ⏳ 미실행 | ⏳ |
| 역할 복구 | ⏳ 미실행 | ⏳ |
| Alert resolved | ⏳ 미실행 | ⏳ |

### Agent 분석

- 영향 범위: ⏳ 미실행
- 직접 원인: ⏳ 미실행
- 사용 증거: ⏳ 미실행
- 제안 완화책: ⏳ 미실행
- 잘못된 주장/누락: ⏳ 미실행

### 점수

| 영향 | 원인 | 증거 | 완화 | 불확실성 | 합계 | 판정 |
|---:|---:|---:|---:|---:|---:|---|
| ⏳ | ⏳ | ⏳ | ⏳ | ⏳ | ⏳/10 | ⏳ |

## 시나리오 간 비교

| 관찰 | S1 | S2 | S3 |
|---|---|---|---|
| 가장 먼저 사용한 증거 | ⏳ | ⏳ | ⏳ |
| 변경과 증상 상관분석 | ⏳ | ⏳ | ⏳ |
| 로그/메트릭/KQL 정확성 | ⏳ | ⏳ | ⏳ |
| 완화책 최소 권한/범위 | ⏳ | ⏳ | ⏳ |
| hallucination | ⏳ | ⏳ | ⏳ |

## 결론 및 운영 권고

- 이벤트 기반 탐지 적합성: ⏳ 미실행
- RCA 정확도: ⏳ 미실행
- Response plan 개선: ⏳ 미실행
- Connector/권한 개선: ⏳ 미실행
- 운영 도입 권고: ⏳ 미실행

## 비용 및 정리

| 항목 | 결과 |
|---|---|
| 테스트 시작 비용 시점 | ⏳ 미실행 |
| Azure Cost Management 실측 | ⏳ 미실행 |
| 추정 비용과 실측 구분 | ⏳ 미실행 |
| Agent Monitoring Contributor 회수 | ⏳ 미실행 |
| 테스트 resource group 삭제 | ⏳ 미실행 |
| 잔여 리소스/역할 | ⏳ 미실행 |

## 증거 위치

원본 evidence는 secret 유출과 대용량 telemetry commit을 막기 위해 Git에서 제외한다.

```text
monitor/sre-agent-event-lab/evidence/
```

보고서에는 재현에 필요한 query, 집계값, UTC timestamp, resource/revision ID만 선별 기록한다.
