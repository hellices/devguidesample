# Azure Monitor Dynamic Thresholds와 SRE Agent 연계 설계

- 대상: Azure Monitor 정적 임계값을 사용하는 Azure SRE Agent 이벤트 연계 환경

## 1. 목적

현재 실험의 정적 임계값이 빠르고 결정론적인 장애 재현에 적합한 이유를 설명하고, 장기 운영에서는 Azure Monitor Dynamic Thresholds를 같은 SRE Agent event bridge에 연결하는 확장 방향을 소개한다.

Dynamic Thresholds 자체는 이번 결과에 포함된 실증 대상이 아니다. 새 rule은 최소 3일·30 samples를 수집하기 전에는 발화하지 않으므로 수 시간짜리 disposable lab에서 결과를 주장하면 안 된다.

## 2. Static과 Dynamic의 역할 분리

### Static Threshold

- 실험 목표: 정해진 장애가 짧은 시간 안에 반드시 alert를 발생시키는지 검증
- evaluation: 1분(window 5분)
- 조건: 5xx count, p95 > 2000ms, Blob 403 count
- 전제: rule scope는 Log Analytics workspace이고 query는 workspace schema known table(`AppRequests`, `AppDependencies`)을 사용한다. Application Insights component scope의 legacy `requests`/`dependencies`는 다른 table을 호출하는 function이라 1분 주기에서 `QueryNotContainKnownTable`로 거부된다.
- 장점: 결정론적이고 당일 재현 가능
- 한계: workload별 정상 범위와 계절성을 수동으로 관리

### Dynamic Threshold

- 운영 목표: 정상 패턴을 학습하고 예상 범위를 벗어난 anomaly를 탐지
- evaluation: Log Search alert에서 5분 이상
- 조건: Boolean이 아닌 numeric query result
- 장점: 시간대·일간·주간 패턴과 다수 series를 자동 학습
- 한계: cold start, 서서히 변하는 degradation, 최근 behavior change에 즉시 반응하지 못함

## 3. 공식 학습·제약

- 초기 threshold 계산에는 최근 10일 data를 사용한다.
- 3일과 최소 30 samples 전에는 alert가 발화하지 않는다.
- weekly seasonality는 최소 3주 data가 필요하다.
- Log Search dynamic threshold는 1분 evaluation을 지원하지 않는다.
- multiple conditions를 한 dynamic rule에서 사용할 수 없다.
- 천천히 진화하는 문제보다 유의미한 deviation 탐지에 적합하다.
- noise를 줄이려면 Medium 또는 Low sensitivity를 우선 검토한다.

## 4. 이 lab에서의 후보 signal

| Scenario | Numeric KQL signal | Dynamic operator | 운영 의도 |
|---|---|---|---|
| S1 HTTP 500 | 5분당 5xx count 또는 error rate | Greater than upper bound | 평상시 오류 패턴을 벗어난 급증 |
| S2 latency | `/api/orders` p95 duration(ms) | Greater than upper bound | 시간대별 latency baseline 이상 |
| S3 dependency | Blob 403 count 또는 dependency failure rate | Greater than upper bound | 정상적으로 0에 가까운 인증 실패 anomaly |

query는 `summarize` 결과가 하나 이상의 numeric series를 반환해야 한다. `count() > 10`과 같은 Boolean 결과는 사용하지 않는다.

## 5. 권장 운영 설정

- Frequency: 5분
- Lookback/window: 15~20분
- Sensitivity: Medium으로 시작, noise가 크면 Low
- Failing periods: 4회 평가 중 2회 위반
- `ignoreDataBefore`: 정상 telemetry가 안정적으로 쌓이기 시작한 UTC
- Action Group: 기존 `ag-sre-agent-event-lab`
- Event path(기본): Dynamic alert → Azure Monitor incident platform 연결 → Review 모드 response plan → investigation. 현재 실습이 배포하는 표준 경로이며 Dynamic rule도 같은 경로를 그대로 쓴다.
- Event path(레거시 bridge): Dynamic alert → Action Group → Logic App managed identity → SRE HTTP Trigger → Review-mode investigation. 2026-08-12 실측에 쓰인 legacy 구성이고 기본 실습에는 배포하지 않는다([validation-results.md](validation-results.md)).

이는 시작점이지 모든 workload의 정답이 아니다. Preview Chart와 incident 결과를 보고 sensitivity와 failing periods를 조정한다.

## 6. 도입 순서

1. 현재 static rule을 유지해 known failure와 critical safety boundary를 보호한다.
2. 같은 numeric signal로 Dynamic rule을 alert action 없이 shadow mode로 생성한다.
3. 최소 3일·30 samples 이후 preview band와 violation을 관찰한다.
4. 주간 pattern이 중요한 workload는 3주 이후 재평가한다.
5. false positive/negative를 static rule과 비교한다.
6. 품질 기준을 통과하면 기존 Action Group을 연결한다.
7. Dynamic rule이 놓치는 cold-start·hard-limit 사건은 static rule을 계속 유지한다.

## 7. 검증 기준

- Dynamic rule이 충분한 학습 data 전에는 실증 완료로 표시되지 않는다.
- Preview Chart의 allowed range와 실제 violation을 보존한다.
- alert fired, Agent pickup, conclusion latency를 static 결과와 같은 방식으로 기록한다.
- 동일 anomaly를 static/dynamic이 각각 탐지했는지 비교한다.
- 계절성, 최근 배포, traffic shift 때문에 threshold가 왜 변했는지 설명할 수 있어야 한다.
- Action Group 연결 후 unauthorized autonomous action은 0건이어야 한다.

## 8. 공식 자료

- [Azure Monitor alerts with dynamic thresholds](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds)
- [Create a log search alert rule](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-create-log-alert-rule)
- [ARM templates for log alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-log)
