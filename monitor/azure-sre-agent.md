# Azure SRE Agent 소개

Azure SRE Agent는 Azure 운영 환경에서 발생한 인시던트를 자동으로 조사하고, 관련 근거를 바탕으로 근본 원인과 조치 방안을 제안하는 AI 기반 운영 도우미입니다.

이 문서에서는 Azure SRE Agent가 인시던트를 조사하는 방식과 실제 활용 예시를 소개합니다. 제품에서 제공하는 표준 기능과 이번 실증에서 확인한 내용을 구분해 설명합니다.

## Azure SRE Agent를 사용하면 무엇이 달라지나요?

운영자는 경고가 발생하면 여러 도구를 오가며 원인을 찾아야 합니다. Azure SRE Agent는 이 과정을 하나의 조사 흐름으로 연결합니다.

| 기존 장애 대응 | Azure SRE Agent를 활용한 대응 |
|---|---|
| 담당자가 경고를 확인한 뒤 조사를 시작합니다. | 대응 계획에 따라 에이전트가 자동으로 조사를 시작합니다. |
| 모니터링 화면, 로그, 변경 이력, 소스 코드를 각각 확인합니다. | 에이전트가 필요한 자료를 선택해 함께 분석합니다. |
| 담당자가 여러 가능성을 머릿속에서 비교합니다. | 에이전트가 가설을 세우고 근거를 통해 확인하거나 제외합니다. |
| 조사 결과를 티켓과 메일로 다시 작성합니다. | 같은 조사 결과를 GitHub Issue, Outlook, Microsoft Teams 등에 전달할 수 있습니다. |
| 해결 경험이 담당자 개인에게 남습니다. | 근본 원인과 해결 과정을 지식으로 축적할 수 있습니다. |

Azure SRE Agent는 단순히 오류 로그를 나열하지 않습니다. 어떤 서비스가 영향을 받았는지 확인하고, 원격 분석 데이터와 변경 이력, 소스 코드를 함께 살펴본 뒤 근본 원인과 다음 조치를 설명합니다.

## 인시던트가 발생하면 어떻게 조사하나요?

![Azure SRE Agent 공식 인시던트 대응 흐름](sre-agent-event-lab/assets/official/incident-response-flow.svg)

> 출처: [인시던트 대응 자동화](https://learn.microsoft.com/azure/sre-agent/incident-response)

Azure SRE Agent는 다음 순서로 인시던트를 조사합니다.

1. **경고를 받습니다.**

   Azure Monitor, PagerDuty 또는 ServiceNow에서 조사 요청을 받습니다. 이번 실증에서 사용한 별도 연결 방식은 뒤에서 설명합니다.

2. **조사 범위를 확인합니다.**

   영향을 받은 서비스, 발생 시각, 고객 영향을 먼저 정리합니다.

3. **관련 근거를 수집합니다.**

   Application Insights, Log Analytics, Azure Resource Graph, Azure Activity Log, 배포 이력, 소스 코드를 확인합니다.

4. **가설을 세우고 검증합니다.**

   가능한 원인을 여러 개 세운 뒤 수집한 근거와 맞지 않는 원인을 제외합니다.

5. **근본 원인과 조치 방안을 제안합니다.**

   확인한 근거, 현재 상태, 최소 범위의 완화 조치를 함께 설명합니다.

6. **사람이 검토하고 승인합니다.**

   검토 모드에서는 변경 작업을 실행하기 전에 담당자의 승인을 받습니다.

7. **조사 결과를 공유합니다.**

   ServiceNow, PagerDuty, GitHub, Outlook, Microsoft Teams 등 기존 운영 도구로 결과를 전달할 수 있습니다.

## 근본 원인은 어떻게 찾나요?

![Azure SRE Agent 공식 근본 원인 분석 흐름](sre-agent-event-lab/assets/official/root-cause-analysis.svg)

> 출처: [근본 원인 분석](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)

Azure SRE Agent는 오류 로그를 나열하는 데서 멈추지 않습니다. 증상을 기준으로 관련 로그, 메트릭, 배포 이력, 소스 코드와 과거 경험을 모으고 가능한 원인을 가설로 세웁니다. 이후 각 가설을 근거와 비교해 제외하거나 확인하고, 결론을 뒷받침하는 자료와 함께 조치 방안을 제시합니다.

## 어떤 정보를 조사할 수 있나요?

Azure SRE Agent는 관리 ID와 Azure RBAC 권한을 사용해 Azure 리소스를 조사합니다.

| 분류 | 확인할 수 있는 정보 |
|---|---|
| 애플리케이션 상태 | Application Insights 요청, 예외, 종속성 호출 |
| 로그 | Log Analytics 작업 영역의 로그 |
| 인프라 상태 | Azure Monitor 메트릭, 리소스 구성, Resource Graph |
| 변경 이력 | Azure Activity Log, 배포 이력, Container Apps 수정 버전 |
| 소스와 문서 | GitHub, Azure DevOps, 운영 절차서, 기술 문서 |
| 과거 경험 | 유사한 인시던트, 이전의 근본 원인과 해결 방법 |

Azure 내부 원격 분석 데이터는 기본 도구만으로도 조회할 수 있습니다. 외부 시스템이나 특정 데이터 원본을 지속해서 사용해야 하는 경우에는 커넥터를 추가합니다.

## 과거 경험과 운영 문서는 어떻게 활용하나요?

![Azure SRE Agent 공식 메모리 통합 검색 구조](sre-agent-event-lab/assets/official/memory-unified-search.svg)

> 출처: [메모리와 지식 관리](https://learn.microsoft.com/azure/sre-agent/memory)

Azure SRE Agent는 과거 조사 대화, 사용자가 기억하도록 지정한 내용, 업로드한 운영 문서와 연결된 지식 원본을 함께 검색합니다. 답변에는 근거와 출처를 포함해 어떤 경험과 문서를 사용했는지 확인할 수 있습니다.

## 조사가 끝난 뒤 무엇을 학습하나요?

![Azure SRE Agent 공식 자동 학습 흐름](sre-agent-event-lab/assets/official/memory-auto-learning.svg)

> 출처: [메모리와 지식 관리](https://learn.microsoft.com/azure/sre-agent/memory)

조사가 완료되면 Azure SRE Agent는 확인한 증상, 효과가 있었던 해결 단계, 근본 원인과 피해야 할 접근을 추출합니다. 이렇게 축적한 내용은 이후 유사한 인시던트를 조사할 때 다시 검색할 수 있습니다.

## 어떤 시스템과 연결할 수 있나요?

### 인시던트 관리

- Azure Monitor 경고
- PagerDuty
- ServiceNow

### 소스와 작업 관리

- GitHub 저장소, Issue, Pull Request
- Azure DevOps 저장소와 Work Item
- Jira와 같은 관리형 커넥터 또는 MCP 기반 티켓 시스템

### 알림과 협업

- Outlook 메일
- Microsoft Teams 채널
- Slack 채널

### 외부 관찰 도구

- Grafana
- Datadog
- Dynatrace
- New Relic
- Splunk
- MCP를 지원하는 사용자 지정 도구

커넥터에서는 사용할 작업만 선택할 수 있습니다. 메일 수신자나 Jira 프로젝트 키처럼 에이전트가 임의로 바꾸면 안 되는 값은 고정할 수 있습니다.

## 권한과 승인 절차는 어떻게 제어하나요?

![Azure SRE Agent 공식 추론과 실행 흐름](sre-agent-event-lab/assets/official/agent-reasoning-flow.svg)

> 출처: [에이전트 추론과 실행](https://learn.microsoft.com/azure/sre-agent/agent-reasoning)

Azure SRE Agent는 실행 수준에 따라 권한을 제어합니다.

| 모드 | 동작 |
|---|---|
| 읽기 전용 모드 | 자료를 조회하고 분석하지만 변경 작업은 실행하지 않습니다. |
| 검토 모드(Review mode) | 조치 방안을 제안하고 담당자의 승인을 기다립니다. |
| 자율 모드 | 허용된 작업을 별도 승인 없이 실행합니다. |

처음 도입할 때는 **검토 모드로 시작하는 것을 권장합니다.** 조사 결과와 도구 선택이 실제 운영 절차에 맞는지 충분히 확인한 뒤 자동화 범위를 넓히는 편이 안전합니다.

커넥터를 설정할 때도 최소 권한 원칙을 적용해야 합니다.

- 읽기 작업과 쓰기 작업을 구분합니다.
- 필요한 작업만 에이전트에 노출합니다.
- 메일 수신자와 프로젝트 키처럼 중요한 값은 고정합니다.
- 삭제나 변경 작업은 승인을 받도록 설정합니다.
- 자율 모드에서는 일부 승인 절차가 생략될 수 있으므로 별도의 최소 권한 연결을 사용합니다.

## 제품에서 기본으로 지원하는 방식

제품의 표준 Azure Monitor 연계는 **Azure Monitor 인시던트 플랫폼 → 대응 계획 → Azure SRE Agent** 순서로 동작합니다. 이 방식에서는 Logic App과 같은 중간 연결이 필요하지 않습니다.

Azure SRE Agent는 다음 기능을 제품에서 기본으로 지원합니다.

- Azure Monitor, PagerDuty, ServiceNow를 통한 인시던트 수신
- 조건에 맞는 인시던트를 담당 에이전트로 전달하는 대응 계획
- Application Insights와 Log Analytics 조사
- GitHub와 Azure DevOps 소스 연결
- ServiceNow와 PagerDuty 상태 갱신
- Outlook과 Microsoft Teams 알림 커넥터
- 읽기 전용, 검토, 자율 실행 모드

자세한 제품 기능은 다음 자료에서 확인할 수 있습니다.

- [Azure SRE Agent 개요](https://learn.microsoft.com/azure/sre-agent/overview)
- [인시던트 대응 설정](https://learn.microsoft.com/azure/sre-agent/tutorial-incident-response)
- [근본 원인 분석](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [커넥터](https://learn.microsoft.com/azure/sre-agent/connectors)
- [관리형 커넥터](https://learn.microsoft.com/azure/sre-agent/managed-connectors)

## 이번 실증에서 사용한 방식

![Azure SRE Agent의 인시던트 대응 흐름](sre-agent-event-lab/assets/briefing/sre-agent-process.png)

[편집 가능한 SVG 보기](sre-agent-event-lab/assets/briefing/sre-agent-process.svg)

이번 실증에서는 대응 계획을 공개 API로 자동 구성하는 데 제약이 있어 Azure SRE Agent의 HTTP Trigger를 사용했습니다.

```text
Azure Monitor 경고
  → Action Group
  → Logic App 관리 ID
  → Azure SRE Agent HTTP Trigger
  → 검토 모드 조사
```

이 연결은 실증 자동화를 위해 사용한 방식이며, 표준 Azure Monitor 연계에 필요한 필수 구성은 아닙니다.

이번 실증에서 실제로 확인한 기능은 다음과 같습니다.

- Azure Monitor 경고에서 Azure SRE Agent 조사 시작
- Application Insights와 Azure Activity Log 분석
- Container Apps 설정과 배포 이력 확인
- GitHub 저장소 검색
- 근본 원인과 조치 방안 작성
- 검토 모드에서 변경 작업을 실행하지 않는 안전 제어
- 실제 GitHub Issue 생성
- Outlook에서 열 수 있는 메일 초안 생성

다음 기능은 이번 실증에서 실제 연결하지 않았습니다.

- ServiceNow
- PagerDuty
- Outlook OAuth 커넥터
- Microsoft Teams 커넥터
- Azure Monitor 기본 대응 계획

## 실제 활용 예시: 주문 API에서 HTTP 500 발생

배포 설정 오류로 주문 API가 HTTP 500을 반환하는 상황을 만들고, Azure SRE Agent가 어떤 근거를 확인하는지 검증했습니다.

![주문 API HTTP 500 실증 요약](sre-agent-event-lab/assets/briefing/s1-three-panel.png)

[편집 가능한 SVG 보기](sre-agent-event-lab/assets/briefing/s1-three-panel.svg)

### 상황

- 서비스: `ca-sre-event-lab-vnet`
- 영향: `GET /api/orders` 요청 120건 실패
- 탐지: Azure Monitor 경고
- 실행 수준: 검토 모드

### 에이전트에게 기대한 조사

1. 영향을 받은 서비스와 API를 정확히 찾아야 합니다.
2. 장애가 시작된 시각을 확인해야 합니다.
3. 외부 종속성 문제와 애플리케이션 문제를 구분해야 합니다.
4. 장애 직전에 변경된 배포 설정을 찾아야 합니다.
5. 서비스가 정상으로 돌아왔는지 확인해야 합니다.
6. 추가로 필요한 조치를 제안해야 합니다.

### 실제 확인 결과

![Azure SRE Agent가 확인한 결과](sre-agent-event-lab/assets/briefing/s1-agent-conclusion.png)

- Azure Monitor 경고가 발생한 뒤 2초 안에 조사 대화가 생성됐습니다.
- Application Insights에서 실패한 요청 120건을 확인했습니다.
- Container Apps 수정 버전 `0000010`에서 `FAILURE_MODE=http500` 설정을 확인했습니다.
- 정상 설정을 사용한 후속 수정 버전으로 트래픽이 이동한 사실을 확인했습니다.
- 에이전트는 검토 모드에서 Azure 리소스를 직접 변경하지 않았습니다.

## 조사 결과를 티켓으로 전달하기

Azure SRE Agent가 정리한 근본 원인과 조치 방안을 작업 항목으로 전달할 수 있습니다. 이번 실증에서는 같은 조사 결과로 실제 GitHub Issue를 만들었습니다.

![실제 GitHub Issue #43](sre-agent-event-lab/assets/notifications/github-issue.png)

- [GitHub Issue #43 열기](https://github.com/hellices/devguidesample/issues/43)
- [Issue 본문 보기](sre-agent-event-lab/assets/notifications/s1-github-issue.md)

Issue에는 다음 내용을 포함했습니다.

- 고객 영향
- 탐지 시각과 조사 시작 시각
- 근본 원인
- 확인한 근거
- 현재 복구 상태
- 후속 권장 사항
- Azure SRE Agent 조사 식별자

실제 운영 환경에서는 ServiceNow, PagerDuty, Azure DevOps Work Item, Jira 등으로 같은 형식을 전달할 수 있습니다.

## 조사 결과를 메일로 공유하기

이번 실증에서는 외부 수신자에게 메일을 보내지 않았습니다. 대신 Azure SRE Agent의 조사 결과로 Outlook에서 열 수 있는 메일 초안과 화면 미리보기를 만들었습니다.

![Outlook 메일 초안](sre-agent-event-lab/assets/notifications/s1-email-preview.png)

- [HTML 메일 보기](sre-agent-event-lab/assets/notifications/s1-incident-summary.html)
- [RFC 5322 메일 파일 보기](sre-agent-event-lab/assets/notifications/s1-incident-summary.eml)

실제 운영에서는 Outlook 커넥터의 메일 보내기 작업을 사용할 수 있습니다.

- 받는 사람은 담당자 또는 배포 목록으로 고정합니다.
- 제목과 본문은 에이전트가 조사 결과를 바탕으로 작성하도록 설정할 수 있습니다.
- 검토 모드에서는 담당자가 내용을 확인한 뒤 전송합니다.
- 자율 모드에는 중요한 수신자나 작업을 별도의 최소 권한 연결로 분리합니다.

## 다른 장애에도 같은 조사 방식을 적용할 수 있나요?

이번 실증에서는 세 가지 유형을 확인했습니다.

| 상황 | Azure SRE Agent가 확인한 내용 | 결과 |
|---|---|---|
| 주문 API HTTP 500 | 실패한 요청, 수정 버전, 설정 변경 | 설정 오류를 근본 원인으로 확인했습니다. |
| 주문 API 지연 | 성공한 요청의 응답 시간, 외부 종속성, 지연 설정 | `ORDER_DELAY_MS=4000`을 확인했습니다. |
| Blob 권한 오류 | 역할 삭제 이력, Blob 403, API 503 | 역할 삭제를 근본 원인으로 확인했습니다. 복구 확인 대상은 한 차례 잘못 선택해 한계로 기록했습니다. |

상세 수치, 시간 순서, 평가 기준은 [실제 동작 검증 부록](../docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md)에서 확인할 수 있습니다.

## Dynamic Thresholds와 함께 사용할 수 있나요?

이번 실증은 같은 날 결과를 확인하기 위해 고정 임계값을 사용했습니다. 실제 운영에서는 Dynamic Thresholds를 함께 사용해 평소와 다른 패턴을 찾을 수 있습니다.

- 최소 3일과 30개 표본이 있어야 경고가 발생합니다.
- 최근 10일의 데이터를 기준으로 허용 범위를 계산합니다.
- 주간 패턴을 학습하려면 최소 3주가 필요합니다.
- 로그 검색 경고에서는 1분 단위 평가를 지원하지 않습니다.

처음에는 기존 고정 임계값을 유지하고, Dynamic Thresholds를 별도의 관찰용 경고로 추가하는 방식을 권장합니다. 충분한 학습 기간을 거친 뒤 오탐과 누락을 비교해 실제 대응 흐름에 연결합니다.

자세한 내용은 [Dynamic Thresholds와 Azure SRE Agent 연계 설계](../docs/superpowers/specs/2026-08-12-azure-monitor-dynamic-thresholds-sre-integration-design.md)를 참고하세요.

## 도입 전에 무엇을 확인해야 하나요?

### 조사 범위

- [ ] 필요한 구독과 리소스 그룹만 연결하세요.
- [ ] Application Insights와 Log Analytics에 필요한 데이터가 들어오는지 확인하세요.
- [ ] 실제 배포에 사용한 소스 분기와 운영 절차서를 연결하세요.

### 인시던트 전달

- [ ] Azure Monitor, PagerDuty, ServiceNow 중 사용할 인시던트 플랫폼을 정하세요.
- [ ] 심각도, 서비스, 제목 기준으로 대응 계획을 만드세요.
- [ ] 빠른 시작 대응 계획과 사용자 정의 대응 계획이 중복되지 않는지 확인하세요.
- [ ] 처음에는 검토 모드로 시작하세요.

### 권한과 안전

- [ ] 읽기 권한부터 시작하세요.
- [ ] 변경 작업은 필요한 리소스 범위에만 허용하세요.
- [ ] 삭제와 변경 작업은 승인을 받도록 설정하세요.
- [ ] 커넥터에는 필요한 작업만 노출하세요.
- [ ] 메일 수신자와 프로젝트 키처럼 중요한 값은 고정하세요.

### 조사 품질

- [ ] 영향을 받은 서비스와 발생 시각이 정확한지 확인하세요.
- [ ] 결론에 근거가 포함되어 있는지 확인하세요.
- [ ] 확인하지 못한 내용과 불확실성을 표시하는지 확인하세요.
- [ ] 조치 방안이 최소 범위이며 되돌릴 수 있는지 확인하세요.
- [ ] 올바른 서비스와 API에서 복구를 확인하는지 확인하세요.

## 알아두어야 할 제한 사항

- AI가 잘못된 결론이나 적절하지 않은 조치 방안을 제시할 수 있습니다.
- 연결한 소스가 실제 배포 분기와 다르면 코드 변경을 정확히 찾지 못할 수 있습니다.
- 여러 서비스가 같은 원격 분석 이름을 사용하면 서로 다른 데이터를 혼동할 수 있습니다.
- 외부 커넥터는 연결을 설정한 사용자의 권한으로 동작할 수 있습니다.
- 자율 모드에서는 일부 승인 절차가 생략될 수 있습니다.
- 지역과 테넌트에 따라 사용할 수 있는 기능이 다를 수 있습니다.

따라서 충분한 근거, 최소 권한, 검토 모드 우선 적용, 실제 복구 확인을 운영 원칙으로 삼는 것이 좋습니다.

## 참고 자료

### 한국어 문체와 용어

- [Microsoft Korean Localization Style Guide](https://aka.ms/korean-styleguide)
- [Microsoft Terminology](https://learn.microsoft.com/globalization/reference/microsoft-terminology)
- [Microsoft language resources](https://learn.microsoft.com/globalization/reference/microsoft-language-resources)
- [Microsoft Writing Style Guide](https://learn.microsoft.com/style-guide/welcome/)

### Azure SRE Agent

- [Azure SRE Agent 개요](https://learn.microsoft.com/azure/sre-agent/overview)
- [인시던트 대응 설정](https://learn.microsoft.com/azure/sre-agent/tutorial-incident-response)
- [근본 원인 분석](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [커넥터](https://learn.microsoft.com/azure/sre-agent/connectors)
- [관리형 커넥터](https://learn.microsoft.com/azure/sre-agent/managed-connectors)

### 실증 자료

- [실제 동작 검증 부록](../docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md)
- [실험 환경과 재현 방법](sre-agent-event-lab/README.md)
