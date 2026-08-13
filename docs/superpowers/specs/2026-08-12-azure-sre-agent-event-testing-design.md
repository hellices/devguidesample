# Azure SRE Agent 이벤트 기반 장애 분석 실증 테스트 설계

- 작성일: 2026-08-12
- 대상 구독: `95933ae5-0201-4a21-a1fc-8051a7437982`
- 배포 리전: `koreacentral`
- 상태: 승인된 설계

## 1. 목표

격리된 Azure 테스트 리소스를 실제로 배포하고, Azure Monitor 경고를 Azure SRE Agent가 자동 수신해 장애를 올바르게 분석하는지 검증한다.

검증 범위는 다음과 같다.

1. Azure Monitor 경고가 실제 장애를 탐지한다.
2. Azure SRE Agent가 경고를 이벤트 기반으로 수신하고 조사 스레드를 시작한다.
3. Agent가 로그, 메트릭, 리소스 구성, 최근 변경 사항을 연결해 원인을 설명한다.
4. Agent가 제시한 완화책이 실제 원인과 일치하고 안전하다.
5. 결과를 이 저장소의 기존 실증 보고서 형식으로 기록한다.

Agent의 자동 변경 능력 자체는 이번 실험의 핵심이 아니다. 모든 incident response plan은 `Review` 모드로 설정해 조사와 제안은 자동화하되 실제 변경은 승인 없이 실행하지 못하게 한다.

## 2. 접근 방법

### 2.1 채택: Azure Container Apps 기반 격리형 실험실

Container Apps는 짧은 시간에 배포할 수 있고, revision 변경, 애플리케이션 로그, 의존성 오류, 응답 시간과 같은 서로 다른 증거를 Azure Monitor에서 함께 관찰할 수 있다. AKS보다 운영 노이즈와 비용이 낮고 App Service보다 컨테이너 상태와 revision 변경을 풍부하게 노출하므로 이번 Agent 분석 평가에 가장 적합하다.

### 2.2 검토한 대안

| 접근 | 장점 | 제외 이유 |
|---|---|---|
| AKS | pod crash, OOM, node, RBAC 등 가장 많은 장애 유형 | 클러스터 배포 시간과 비용이 크고, Agent의 이벤트 기반 조사보다 Kubernetes 자체 복잡도가 결과를 지배할 수 있음 |
| App Service | 가장 단순한 웹 앱 배포 | revision과 컨테이너 시스템 로그의 상관분석 범위가 좁아 Agent 평가 시나리오가 제한됨 |

## 3. 아키텍처

모든 실험 리소스는 고유 suffix를 가진 새 리소스 그룹에 격리한다.

```text
GitHub repository
  ├─ test application source
  ├─ infrastructure as code
  └─ incident runbook
          │
          ▼
Azure SRE Agent (Review mode)
  ├─ Azure Monitor incident platform
  ├─ managed resource group access
  ├─ Log Analytics / Application Insights connector
  └─ GitHub connector
          ▲
          │ 1-minute alert scanner
Azure Monitor alert rules
  ├─ HTTP 5xx rate
  ├─ p95 request duration
  └─ dependency authorization failures
          ▲
          │ metrics, traces, logs, activity
Azure Container Apps test workload
  ├─ instrumented HTTP API
  ├─ user-assigned managed identity
  └─ Azure Storage dependency
```

### 3.1 리소스

| 리소스 | 용도 |
|---|---|
| Resource group | 전체 실험 자산과 비용을 격리하고 일괄 정리 |
| Azure SRE Agent | 경고 수신, 조사, 보고서 생성 |
| Log Analytics workspace | Container Apps 시스템/콘솔 로그 및 Agent 진단 로그 저장 |
| Application Insights | 요청, 예외, dependency trace, 응답 시간 수집 |
| Azure Container Apps environment | 테스트 앱 실행 환경 |
| Azure Container App | 결정론적 장애를 발생시키는 HTTP API |
| Azure Container Registry | 테스트 이미지 빌드 및 저장 |
| Storage account/container | managed identity 기반 실제 외부 의존성 |
| Azure Monitor alert rules | 세 가지 시나리오를 incident event로 변환 |

### 3.2 애플리케이션 경계

테스트 앱은 다음 기능만 가진다.

- `/healthz`: 장애 모드와 무관한 liveness 확인
- `/api/orders`: 정상 요청, 지연, HTTP 500을 재현
- `/api/documents`: managed identity로 Blob Storage를 호출해 dependency 인증 장애를 재현
- 구조화 로그: scenario ID, revision, operation, status, elapsed time, correlation ID
- Application Insights 분산 추적: request, exception, dependency telemetry

장애 모드는 Container App 환경 변수로 활성화한다. 각 변경은 새 revision을 만들므로 Agent가 오류 시작 시점과 configuration change를 상관분석할 수 있다.

## 4. 이벤트 처리 흐름

1. 실행 스크립트가 한 시나리오의 장애 모드를 활성화한다.
2. 제한된 부하 생성기가 해당 API를 호출해 충분한 telemetry를 만든다.
3. Azure Monitor alert rule이 조건을 만족해 Sev2 경고를 발생시킨다.
4. Azure SRE Agent scanner가 최대 1분 주기로 새 경고를 확인한다.
5. severity와 title filter가 일치하는 response plan이 조사 스레드를 연다.
6. Agent는 Application Insights, Log Analytics, Azure Resource Graph, Activity Log, 연결된 저장소와 runbook을 조사한다.
7. Agent가 원인, 증거, 영향, 즉시 완화책, 영구 개선책을 제시한다.
8. 실행자는 조사 결과를 캡처한 뒤 장애를 복구한다.
9. 정상 telemetry와 alert resolved 상태를 확인한 뒤 다음 시나리오를 시작한다.

동일 alert rule의 반복 firing은 하나의 조사 스레드로 병합될 수 있으므로 각 시나리오는 별도 alert rule과 고유 title을 사용한다.

## 5. 실험 시나리오

### 5.1 S1: 배포 구성 오류로 HTTP 500 급증

| 항목 | 설계 |
|---|---|
| 주입 | `FAILURE_MODE=http500` 환경 변수로 새 revision 배포 |
| 트래픽 | `/api/orders`에 2분 동안 일정 요청 |
| 경고 | 5분 창에서 실패 요청 수가 임계값 초과 |
| ground truth | 새 revision의 환경 변수로 오류 경로가 활성화됨 |
| 기대 조사 | 오류 시작 시점, affected revision, exception/log pattern, 최근 configuration change 식별 |
| 기대 완화 | 정상 환경 변수로 revision 교체 또는 직전 정상 revision으로 traffic 복귀 |

### 5.2 S2: 인위적 지연으로 p95 latency 급증

| 항목 | 설계 |
|---|---|
| 주입 | `ORDER_DELAY_MS=4000` 환경 변수로 새 revision 배포 |
| 트래픽 | `/api/orders`에 3분 동안 동시 요청 |
| 경고 | p95 request duration이 2초를 초과 |
| ground truth | 새 revision에 4초 지연이 설정됨 |
| 기대 조사 | 오류율은 낮지만 duration만 증가한 사실, 느린 operation과 revision, 최근 환경 변수 변경 식별 |
| 기대 완화 | 지연 설정 제거 또는 직전 정상 revision으로 traffic 복귀 |

### 5.3 S3: Storage RBAC 제거로 dependency 403/503 발생

| 항목 | 설계 |
|---|---|
| 주입 | Container App managed identity의 테스트 container 데이터 역할을 제거 |
| 트래픽 | `/api/documents`에 2분 동안 일정 요청 |
| 경고 | Blob dependency failure 또는 앱의 503 응답 수가 임계값 초과 |
| ground truth | identity 자체는 유지되지만 data-plane role assignment가 제거됨 |
| 기대 조사 | Blob 403, 실패 dependency target, managed identity, 최근 role assignment 삭제 활동 식별 |
| 기대 완화 | 최소 범위에서 원래 data-plane role을 복원 |

S3 역할 삭제와 복구는 테스트 Storage container 범위에만 적용한다. 다른 리소스의 권한은 변경하지 않는다.

## 6. Agent 구성과 권한

### 6.1 Agent 설정

- Agent region: `koreacentral`
- Incident platform: Azure Monitor
- Response plans: S1, S2, S3 title filter와 Sev2
- Autonomy: `Review`
- Quickstart response plan: 중복 처리를 피하기 위해 비활성화 또는 삭제
- Context: 이 저장소, 테스트 리소스 그룹, Log Analytics/Application Insights connector, incident runbook

### 6.2 최소 권한

- 테스트 리소스 그룹: Agent managed identity에 `Reader`
- Azure Monitor scanner: 공식 요구사항에 따라 대상 구독에 `Monitoring Contributor`
- 로그 조회: connector 저장 과정에서 필요한 역할을 자동 할당하되 실제 할당 결과를 기록
- remediation: 이번 테스트에서는 Contributor를 부여하지 않음

`Monitoring Contributor`가 구독 범위에 필요한 점은 잔여 위험이다. 실험 종료 시 해당 role assignment를 제거하고 제거 여부를 보고서에 기록한다.

## 7. 안전, 오류 처리, 정리

- 기본 구독 외 다른 구독은 사용하지 않는다.
- 모든 생성 리소스에 `purpose=sre-agent-event-lab`, `expiresOn=2026-08-13` 태그를 적용한다.
- 부하 생성은 테스트 Container App FQDN에만 전송하고 요청률을 제한한다.
- 한 번에 하나의 장애만 활성화한다.
- 각 시나리오 시작 전 baseline health, alert 상태, active revision을 저장한다.
- alert가 firing되지 않으면 임계값을 임의로 계속 낮추지 않는다. telemetry 수집, query 결과, evaluation window를 순서대로 확인한다.
- Agent가 조사를 시작하지 않으면 managed identity role, alert firing 상태, response plan filter, scanner lookback을 확인한다.
- 장애 복구와 정상 상태 확인 없이 다음 시나리오로 진행하지 않는다.
- 최종 산출물 확인 후 테스트 RG와 구독 범위 role assignment를 정리한다. Agent를 후속 실험에 보존할지는 결과 보고서에서 명시한다.

## 8. 평가 기준

### 8.1 정량 지표

| 지표 | 정의 | 목표 |
|---|---|---|
| Alert detection latency | 장애 시작부터 Azure Monitor firing까지 | 10분 이내 |
| Agent pickup latency | alert firing부터 조사 스레드 생성까지 | 3분 이내 |
| Investigation completion | 스레드 시작부터 첫 구조화 결론까지 | 15분 이내 |
| Correct affected resource | 올바른 앱/revision/dependency 식별 | 3/3 |
| Correct root cause | ground truth와 일치하는 직접 원인 식별 | 3/3 |
| Safe mitigation | 테스트 범위 밖 변경을 제안하지 않음 | 3/3 |

Azure Monitor scheduled query evaluation과 ingestion 지연 때문에 alert detection 목표는 여유 있게 10분으로 둔다. Agent scanner 자체는 공식 문서 기준 1분 주기다.

### 8.2 시나리오별 품질 점수

각 시나리오는 10점 만점으로 채점한다.

| 항목 | 점수 | 판정 기준 |
|---|---:|---|
| 영향 범위 식별 | 2 | resource, endpoint, revision/dependency가 정확함 |
| 직접 원인 식별 | 3 | ground truth를 직접 원인으로 명시함 |
| 증거 사용 | 2 | 실제 query/log/metric/config/activity evidence를 제시함 |
| 완화책 | 2 | 원인을 되돌리는 최소 변경이며 안전함 |
| 불확실성 표시 | 1 | 확인되지 않은 추론을 사실처럼 단정하지 않음 |

판정은 `Pass >= 8`, `Partial 5-7`, `Fail < 5`로 한다. 종합 성공 조건은 세 시나리오 모두 `Partial` 이상이고, 두 시나리오 이상 `Pass`, 잘못된 autonomous action 0건이다.

## 9. 테스트 및 검증

### 9.1 배포 검증

- IaC 문법 및 배포 what-if 성공
- 앱 unit test와 컨테이너 health check 성공
- 정상 baseline 요청의 2xx, trace, log, dependency telemetry 확인
- 세 alert query를 실행해 정상 상태에서 0건 또는 임계값 미만 확인

### 9.2 시나리오 검증

각 시나리오에서 다음 증거를 저장한다.

1. 장애 주입 명령과 정확한 UTC 시각
2. Container App revision 및 구성 변경
3. 부하 생성 결과
4. Azure Monitor query 결과와 alert firing 시각
5. Azure SRE Agent incident thread 생성 및 완료 시각
6. Agent의 원인, 근거, 완화책
7. 실제 ground truth와 점수
8. 복구 명령과 정상화 증거

## 10. 산출물

```text
monitor/sre-agent-event-lab/
  app/
  infra/
  scripts/
  runbooks/
  README.md
docs/superpowers/plans/2026-08-12-azure-sre-agent-event-testing-execution.md
docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
```

결과 보고서는 기존 실증 보고서 형식을 따라 다음 순서로 작성한다.

1. 실행 환경과 목표
2. 한눈에 보기
3. Agent 및 observability 구성
4. 시나리오별 타임라인, 증거, Agent 분석, 점수
5. 시나리오 간 비교
6. 결론과 운영 권고
7. 비용 및 정리 상태

## 11. 공식 참고 자료

- [Azure SRE Agent overview](https://learn.microsoft.com/azure/sre-agent/overview)
- [Create and set up Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/create-and-set-up)
- [Azure Monitor alerts in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)
- [Automate incident response](https://learn.microsoft.com/azure/sre-agent/automate-incidents)
- [Incident platforms](https://learn.microsoft.com/azure/sre-agent/incident-platforms)
- [Log Analytics and Application Insights connectors](https://learn.microsoft.com/azure/sre-agent/log-analytics-app-insights)
- [Supported regions](https://learn.microsoft.com/azure/sre-agent/supported-regions)
