# Azure SRE Agent 소개 자료 재구성 설계

- 작성일: 2026-08-12
- 대상 독자: Azure 운영자, SRE, 클라우드 아키텍트, 기술 의사결정자
- 상태: 승인된 설계

## 1. 문제 정의

현재 문서는 실험 환경, 시간 지표, 점수부터 시작하는 실증 보고서다. Azure SRE Agent를 처음 접하는 독자는 다음 내용을 먼저 이해하기 어렵다.

1. Azure SRE Agent가 어떤 운영 문제를 해결하는가
2. Azure Monitor, Application Insights, source code, incident platform을 어떻게 연결하는가
3. Agent가 단순 log search가 아니라 어떤 방식으로 가설을 만들고 검증하는가
4. Review mode와 approval이 실제 조치 위험을 어떻게 통제하는가
5. 분석 결과가 ticket, email, Teams 같은 기존 운영 흐름으로 어떻게 전달되는가
6. 각 GIF에서 어떤 장애가 발생했고 무엇을 확인해야 하는가

새 문서는 제품 소개를 주 산출물로 만들고, 기존 실증 보고서는 제품의 실제 동작을 입증하는 부록으로 재배치한다.

## 2. 접근 방식

### 채택: Hybrid 제품 소개 + 대표 운영 패턴

제품 개념을 짧고 시각적으로 소개한 뒤, HTTP 500 대표 시나리오를 end-to-end로 깊게 설명한다. latency와 RBAC 시나리오는 “다른 유형에도 같은 조사 패턴이 적용된다”는 비교 사례로 정리한다.

### 검토한 대안

| 접근 | 장점 | 제외 이유 |
|---|---|---|
| Product-first 기능 카탈로그 | Microsoft Learn 구조와 유사, 참조성이 높음 | 초반이 설명서처럼 느껴지고 실제 가치 이해가 늦음 |
| 시나리오 사례집 | 읽기 쉽고 GIF 활용이 자연스러움 | 제품 기능, 권한, connector, safety model 설명이 부족 |

## 3. 산출물

### 3.1 주 소개 문서

경로:

```text
monitor/azure-sre-agent.md
```

목차:

1. 한 문장 소개
2. 운영 전후 비교
3. Azure SRE Agent가 동작하는 방식
4. 핵심 구성 요소와 연결
5. 안전 모델: ReadOnly, Review, Autonomous
6. 대표 운영 패턴: HTTP 500 → 분석 → ticket → email
7. 실제 Agent 조사 storyboard와 GIF
8. 추가 패턴: latency, RBAC, Dynamic Thresholds
9. 티켓/알림 connector 운영화
10. 도입 체크리스트와 한계
11. 상세 실증 보고서 링크

### 3.2 실증 보고서

기존 파일을 유지하되 제목과 도입부를 “소개 자료의 실제 동작 검증 부록”으로 변경한다.

```text
docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md
```

보고서에는 원본 시간·점수·증거를 유지하고, 주 소개 문서로 돌아가는 링크를 추가한다.

### 3.3 시나리오 시각 자료

```text
monitor/sre-agent-event-lab/assets/storyboards/
  s1/
    investigation-guide.gif
    01-situation.png
    02-expectation.png
    03-alert-fired.png
    04-thread-created.png
    05-evidence.png
    06-conclusion.png
    07-operational-output.png
  s2/
  s3/
```

### 3.4 운영 결과 artifact

```text
monitor/sre-agent-event-lab/assets/notifications/
  s1-incident-summary.html
  s1-incident-summary.eml
  s1-email-preview.png
  github-issue.json
  github-issue.png
```

## 4. Microsoft Learn 이미지 사용

공식 이미지는 repository에 복제하지 않고 Microsoft Learn 원본 URL을 Markdown에서 직접 참조한다. 각 이미지 바로 아래에 원문 제목과 링크를 표시한다.

| 소개 위치 | 공식 이미지 |
|---|---|
| 가설 기반 RCA | `media/root-cause-analysis/root-cause-analysis.svg` |
| Response plan | `media/tutorial-incident-response/incident-response-plans.png` |
| Memory search | `media/tutorial-incident-response/sample-app-memory-search-results.png` |
| Managed connectors | `media/managed-connectors/managed-connectors-icon-grid.png` |
| Connector operation selection | `media/managed-connectors/office365-operations.png` |
| Locked parameters / governance | `media/managed-connectors/office365-parameter-policy.png` |

이미지를 수정하거나 Microsoft UI처럼 보이는 가짜 화면을 만들지 않는다. 자체 제작 diagram과 official screenshot을 명확히 구분한다.

## 5. 제품 소개 메시지

### 5.1 한 문장

Azure SRE Agent는 alert를 받아 Azure telemetry, resource configuration, deployment history, source code, past incident knowledge를 연결해 root cause와 안전한 mitigation을 제안하는 AI 기반 reliability assistant다.

### 5.2 핵심 가치

```text
Detect → Investigate → Recommend/Act → Communicate → Learn
```

- **Detect:** Azure Monitor, PagerDuty, ServiceNow, HTTP Trigger
- **Investigate:** Application Insights, Log Analytics, Resource Graph, Activity Log
- **Correlate:** GitHub/Azure DevOps source, runbook, past incident memory
- **Recommend/Act:** Review approval 또는 제한된 Autonomous action
- **Communicate:** ticket, email, Teams/Slack
- **Learn:** resolved incident의 root cause와 resolution을 memory에 축적

### 5.3 단순 log search와의 차이

Agent는 log를 나열하지 않고 다음 순서로 조사한다.

1. incident boundary와 사용자 영향을 정의
2. 가능한 root-cause hypothesis 생성
3. metrics, logs, changes, code로 hypothesis 검증/기각
4. evidence chain과 uncertainty를 포함한 결론 작성
5. reversible하고 최소 범위인 mitigation 제안

## 6. 대표 시나리오 storyboard

### 6.1 상황

새 Container App revision의 설정 오류로 `/api/orders`가 HTTP 500을 반환한다. 사용자는 주문 처리 실패를 경험하고 on-call engineer는 Azure Monitor alert를 받는다.

### 6.2 기대 동작

1. Azure Monitor가 500 anomaly를 감지한다.
2. Action Group이 Review-mode SRE workflow를 호출한다.
3. Agent가 affected endpoint와 UTC onset을 찾는다.
4. Application Insights의 120개 failed request를 확인한다.
5. Container App revision과 `FAILURE_MODE=http500`을 상관 분석한다.
6. connected repository와 Activity Log로 code/change evidence를 보강한다.
7. rollback/config restoration을 최소 mitigation으로 제안한다.
8. 결과를 ticket으로 생성하고 on-call email 초안을 만든다.

### 6.3 실제 결과

- Alert fired 후 Agent thread 생성: 2초
- 첫 구조화 결론: thread 생성 후 143초
- 영향을 받은 request: `/api/orders` HTTP 500 120건
- root cause: revision `0000010`, `FAILURE_MODE=http500`
- mitigation: 정상 setting revision으로 traffic 복귀
- Agent는 resource를 변경하지 않고 Review mode에서 결론만 제시

## 7. GIF 재설계

기존 GIF는 실제 event만 보여주므로 처음 보는 독자가 상황을 알기 어렵다. 새 GIF는 설명 frame과 실측 frame을 구분한다.

### Frame 구조

| 순서 | 유형 | 내용 |
|---:|---|---|
| 1 | 설명 | 상황: 주문 API 500, 사용자 영향 |
| 2 | 설명 | 기대: telemetry/change/code를 조사하고 rollback 제안 |
| 3 | 실측 | Azure Monitor alert fired |
| 4 | 실측 | Agent thread created |
| 5 | 실측 | Application Insights/revision evidence |
| 6 | 실측 | root cause conclusion |
| 7 | 설명+실제 output | GitHub Issue URL, email preview, Review 상태 |

설명 frame에는 `SCENARIO` badge, 실제 API evidence frame에는 `ACTUAL` badge를 표시한다. 마지막 frame은 “무엇이 해결됐고 다음 운영 action이 무엇인지”를 한눈에 보여준다.

### 문서 내 배치

GIF 앞:

1. 상황
2. 사용자 영향
3. Agent에게 기대하는 것

GIF 뒤:

1. Agent가 실제 확인한 evidence
2. conclusion
3. ticket/email output
4. 기대와 실제의 차이

S2/S3도 같은 구조를 사용하되 본문에서는 scenario card와 대표 conclusion frame을 먼저 보여주고 GIF는 접이식 상세 또는 링크로 배치한다.

## 8. 티켓 시나리오

### 8.1 실제 GitHub Issue

`hellices/devguidesample`에 다음 구조로 실제 issue를 생성한다.

```text
Title: [SRE-LAB] ca-sre-event-lab-vnet HTTP 500 incident

Impact
Detection
Root cause
Evidence
Current status
Recommended follow-up
Agent thread ID
Detailed report path
```

issue에는 token, connection string, private callback URL, user identity claim을 포함하지 않는다. issue 생성 결과의 number/URL을 JSON과 screenshot으로 보존한다.

### 8.2 운영 전환

Microsoft Learn 기준으로 다음 선택지를 설명한다.

- GitHub connector: issue 생성·검색·comment
- Azure DevOps connector: work item 생성
- ServiceNow/PagerDuty incident platform: acknowledge, update, resolve
- Jira managed connector 또는 custom MCP ticketing server

## 9. 이메일 시나리오

### 9.1 이번 실증

실제 수신자와 Outlook OAuth consent가 없으므로 email을 전송하지 않는다. Agent의 S1 conclusion에서 다음 artifact를 생성한다.

- RFC 5322 `.eml`
- HTML body
- browser screenshot

email 내용:

```text
Subject: [Resolved][SRE-LAB] Order API HTTP 500 incident
Severity / Service / UTC window
Customer impact
Root cause
Evidence
Mitigation / Current status
Ticket link
Follow-up actions
```

### 9.2 운영 전환

Outlook connector의 Send email operation을 사용한다.

- `To`: User-defined locked parameter
- `Subject`, `Body`: Agent-defined
- Permission: Review workflow에서 `Ask`
- Autonomous workflow에서는 `Ask`가 bypass될 수 있으므로 별도 read-only/limited connector 사용

Teams channel notification도 같은 structured summary를 재사용할 수 있다.

## 10. 추가 실사용 패턴

### Latency anomaly

- HTTP 200이지만 p95가 4초
- Agent는 dependency failure와 application delay를 구분
- Dynamic Threshold shadow alert의 대표 후보

### RBAC dependency failure

- Blob role assignment 삭제 직후 403/503
- Agent는 Activity Log와 dependency trace를 연결
- ticket에는 exact scope와 least-privilege role을 기록

### Scheduled operations

- daily health summary
- certificate/secret expiration
- compliance drift
- failed deployment review

## 11. 오류 처리와 진실성

- 실제로 보내지 않은 email은 `Draft`라고 표시한다.
- GitHub Issue는 실제 URL이 있을 때만 “발행 완료”로 표시한다.
- Microsoft Learn 공식 기능과 이번 lab에서 사용한 HTTP Trigger bridge를 구분한다.
- ServiceNow/PagerDuty/Outlook을 이번 lab에서 실제 연결했다고 주장하지 않는다.
- GIF의 설명 frame과 실제 API evidence frame을 명확히 구분한다.
- S3의 old app 혼동처럼 Agent의 오류도 숨기지 않고 한계로 설명한다.

## 12. 검증 기준

- 주 소개 문서가 제품 정의·가치·동작·안전·connector·도입 절차를 포함
- Microsoft Learn 공식 이미지 5개 이상과 출처 링크 포함
- S1 storyboard가 상황→기대→실측→ticket/email 결과 순서
- S1/S2/S3 GIF에 `SCENARIO`와 `ACTUAL` frame 포함
- GitHub Issue가 실제 존재하고 URL을 문서에 기록
- `.eml`, HTML, email screenshot 생성
- 모든 notification artifact에 secret pattern 0건
- 실증 보고서는 주 소개 문서를 링크하고 “검증 부록”으로 명시
- 37개 기존 test와 신규 storyboard/notification test가 통과

## 13. 공식 자료

- [Overview of Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/overview)
- [Set up incident response](https://learn.microsoft.com/azure/sre-agent/tutorial-incident-response)
- [Root cause analysis](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [Connectors](https://learn.microsoft.com/azure/sre-agent/connectors)
- [Managed connectors](https://learn.microsoft.com/azure/sre-agent/managed-connectors)
- [PagerDuty incident indexing](https://learn.microsoft.com/azure/sre-agent/pagerduty-incidents)
- [ServiceNow incident indexing](https://learn.microsoft.com/azure/sre-agent/servicenow-incidents)
