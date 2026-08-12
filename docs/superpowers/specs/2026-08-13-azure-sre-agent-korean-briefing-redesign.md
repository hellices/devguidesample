# Azure SRE Agent 한국어 고객 브리핑 개편 설계

- 작성일: 2026-08-13
- 대상 독자: 고객·파트너 기술 담당자, SRE, 클라우드 아키텍트
- 발표자 관점: Microsoft 직원이 제품과 실제 검증 결과를 소개
- 선택한 시각 방향: 프로세스 다이어그램 + 실제 결과 화면
- 상태: 승인된 설계

## 1. 개편 목적

현재 소개 문서는 다음 문제가 있다.

1. 한국어 문장 안에 영어 명사가 지나치게 많이 섞여 번역문처럼 읽힌다.
2. 설명문이 `-다`체로 작성되어 고객 브리핑 자료보다 내부 보고서에 가깝다.
3. Microsoft Learn의 외부 이미지 URL에 의존해 Markdown 환경에 따라 이미지가 깨진다.
4. Storyboard GIF가 자동으로 넘어가므로 상황과 결과를 충분히 읽기 어렵다.
5. 제품 소개, lab-specific 구현, 실제 검증 결과가 한 문서에서 섞인다.
6. 고객이 “그래서 실제 운영에서 어떻게 쓰는가”를 빠르게 파악하기 어렵다.

개편 후 문서는 Microsoft 직원이 고객·파트너에게 Azure SRE Agent를 설명하는 기술 브리핑 자료가 된다. 제품 동작은 직접 만든 다이어그램으로 설명하고, 실제 검증은 Agent 결론·티켓·이메일 화면으로 보여준다.

## 2. 한국어 문체 기준

### 2.1 기본 문체

- 설명문은 `-합니다`, `-할 수 있습니다`, `-하는 방식입니다`를 사용한다.
- 사용자가 직접 해야 하는 단계는 `-하세요`, `-하지 마세요`, `-해 주세요`처럼 자연스러운 존댓말을 사용한다.
- 법률 또는 계약 문구가 아니라면 딱딱한 `-하십시오`체는 사용하지 않는다.
- 제목은 짧은 명사구 또는 질문형 문장으로 작성한다.
- 한 문장은 한 가지 핵심 내용만 전달한다.
- 문단 첫 문장에서 결론을 말하고, 뒤에서 근거와 예시를 설명한다.
- 과장된 마케팅 표현보다 기능·조건·효과를 구체적으로 설명한다.
- 대명사는 의미가 분명하면 생략한다.
- 수동형보다 능동형을 우선한다.

### 2.2 용어 기준

제품명과 공식 서비스명은 영어를 유지한다.

- Azure SRE Agent
- Azure Monitor
- Application Insights
- Log Analytics
- Azure Resource Graph
- GitHub
- ServiceNow
- PagerDuty
- Microsoft Teams
- Outlook

일반 운영 용어는 한국어를 우선한다.

| 기존 표현 | 개편 표현 |
|---|---|
| alert | 경고 |
| incident | 인시던트 또는 장애 상황 |
| evidence | 근거 |
| root cause | 근본 원인 |
| hypothesis | 가설 |
| response plan | 대응 계획 |
| Review mode | 검토 모드(Review mode) |
| connector | 커넥터 |
| runbook | 운영 절차서(runbook) |
| telemetry | 원격 분석 데이터 |
| deployment history | 배포 이력 |
| affected resource | 영향을 받은 리소스 |
| mitigation | 완화 조치 |

첫 등장에서는 필요한 경우 한국어와 공식 영문 명칭을 병기하고 이후에는 한 가지 표현을 일관되게 사용한다.

제품명은 임의로 번역하거나 줄이지 않는다. 예를 들어 Microsoft를 `MS`로, Visual Studio를 `VS`로 줄이지 않는다.

제품과 기능 용어는 Microsoft Terminology에서 승인된 한국어를 우선 확인한다.

### 2.3 번역투 제거

다음 표현은 사용하지 않는다.

- 경고가 fire됩니다.
- Agent가 evidence를 collect합니다.
- root-cause hypothesis를 생성합니다.
- structured summary를 communicate합니다.
- context를 연결합니다.

다음과 같이 바꾼다.

- 경고가 발생합니다.
- Agent가 관련 근거를 수집합니다.
- 근본 원인에 대한 가설을 세웁니다.
- 조사 결과를 구조화해 티켓과 알림으로 전달합니다.
- 여러 시스템의 정보를 함께 분석합니다.

딱딱한 한자어와 명사 나열도 줄인다.

| 피할 표현 | 권장 표현 |
|---|---|
| 장애 분석을 수행합니다 | 장애를 분석합니다 |
| 정보를 제공해 줍니다 | 정보를 보여 줍니다 |
| 대응 절차를 실행합니다 | 대응 절차에 따라 조치합니다 |
| 문제 해결을 위한 작업을 수행합니다 | 문제를 해결합니다 |
| 관련 데이터에 대한 확인이 필요합니다 | 관련 데이터를 확인해야 합니다 |

### 2.4 Microsoft 고객 브리핑 톤

- “이번 문서에서는 …을 소개합니다.”
- “다음과 같은 상황에서 활용할 수 있습니다.”
- “처음 도입할 때는 검토 모드로 시작하는 것을 권장합니다.”
- “이번 실증에서는 …을 확인했습니다.”
- “실제 운영 환경에서는 …을 추가로 검토해야 합니다.”

Microsoft Learn 한국어 번역문은 제품 용어를 확인하는 보조 자료로만 사용한다. 문장 구조와 어투는 Microsoft Korean Localization Style Guide를 우선 적용한다.

### 2.5 공식 기준의 우선순위

1. Microsoft Korean Localization Style Guide
2. Microsoft Terminology와 UI translation resources
3. Microsoft Writing Style Guide의 brand voice, headings, verbs, numbers
4. Microsoft Trademark and Brand Guidelines
5. 위 자료에 없는 표현은 표준국어대사전

## 3. 시각 자료 전략

### 3.1 본문에서 제거

- 외부 Microsoft Learn 이미지 직접 삽입
- Storyboard GIF 자동 재생
- 전체 Azure resource ID
- 내부 thread status JSON
- 같은 내용을 반복하는 decorative image

Microsoft Learn 이미지는 본문에 삽입하지 않고 관련 섹션의 “참고 자료” 링크로 제공한다.

### 3.2 새로 만드는 로컬 시각 자료

#### A. 제품 동작 프로세스

```text
경고 수신
  → 조사 범위 확인
  → 원격 분석·변경 이력·코드에서 근거 수집
  → 가설 수립 및 검증
  → 근본 원인과 조치 방안 제시
  → 사람의 검토와 승인
  → 티켓·이메일·Teams로 공유
  → 해결 경험 축적
```

경로:

```text
monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.svg
monitor/sre-agent-event-lab/assets/briefing/sre-agent-process.png
```

#### B. 대표 시나리오 3단계 패널

한 장에서 다음을 보여준다.

```text
1. 상황
   주문 API에서 HTTP 500 발생
   고객 주문 요청 120건 실패

2. Azure SRE Agent 조사
   Application Insights request 확인
   Container App revision 변경 확인
   FAILURE_MODE=http500 식별

3. 운영 결과
   근본 원인과 복구 상태 정리
   GitHub Issue #43 생성
   Outlook 이메일 초안 생성
```

경로:

```text
monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.svg
monitor/sre-agent-event-lab/assets/briefing/s1-three-panel.png
```

#### C. 실제 결과 화면

- 실제 Agent 결론을 정리한 public-safe 정적 카드
- 실제 GitHub Issue #43 화면
- 실제 이메일 초안 화면

경로:

```text
monitor/sre-agent-event-lab/assets/briefing/s1-agent-conclusion.png
monitor/sre-agent-event-lab/assets/notifications/github-issue.png
monitor/sre-agent-event-lab/assets/notifications/s1-email-preview.png
```

### 3.3 Storyboard 처리

기존 Storyboard GIF와 생성 코드는 검증 부록 또는 lab artifact로 유지할 수 있지만 주 소개 문서에서는 제거한다. 소개 문서는 정적 이미지와 설명을 사용한다.

## 4. 소개 문서 구조

대상 파일:

```text
monitor/azure-sre-agent.md
```

### 4.1 제목과 도입

```text
# Azure SRE Agent 소개

Azure SRE Agent는 Azure 운영 환경에서 발생한 인시던트를 자동으로 조사하고,
관련 근거를 바탕으로 근본 원인과 조치 방안을 제안하는 AI 기반 운영 도우미입니다.
```

첫 화면에는 한 문장 소개, 활용 가치 3개, 제품 동작 프로세스 이미지를 배치한다.

### 4.2 문서 목차

1. Azure SRE Agent란 무엇인가요?
2. 기존 장애 대응과 무엇이 달라지나요?
3. 인시던트가 발생하면 어떻게 조사하나요?
4. 어떤 시스템과 연결할 수 있나요?
5. 권한과 승인 절차는 어떻게 제어하나요?
6. 실제 활용 예시: 주문 API HTTP 500
7. 조사 결과를 티켓과 이메일로 전달하기
8. 다른 활용 패턴
9. Dynamic Thresholds와 함께 사용하기
10. 도입 전 확인할 사항
11. 실제 동작 검증 부록

## 5. 대표 시나리오 구성

### 5.1 상황

배포 설정 오류로 주문 API가 HTTP 500을 반환한다. 이로 인해 고객 주문 요청 120건이 실패한다.

### 5.2 기대하는 조사

Agent는 다음 질문에 답해야 한다.

1. 어떤 서비스와 API가 영향을 받았는가?
2. 장애는 언제 시작됐는가?
3. 외부 종속성 문제인가, 애플리케이션 문제인가?
4. 어떤 배포 또는 설정 변경이 장애와 연결되는가?
5. 현재 서비스는 정상으로 돌아왔는가?
6. 추가로 필요한 후속 조치는 무엇인가?

### 5.3 실제 확인 결과

- Azure Monitor 경고 후 2초 안에 조사 thread 생성
- Application Insights에서 실패한 요청 120건 확인
- Container App revision의 `FAILURE_MODE=http500` 확인
- 정상 revision으로 트래픽이 이동한 사실 확인
- Agent는 검토 모드에서 리소스를 직접 변경하지 않음
- GitHub Issue #43 생성
- Outlook 이메일 초안 생성

### 5.4 배치 방식

1. 3단계 패널 이미지
2. Agent 결론 카드
3. GitHub Issue 화면
4. 이메일 초안 화면
5. “이번 실증에서 확인한 점” 요약

## 6. 제품 기능과 실증 구분

### 제품에서 지원하는 표준 기능

- Azure Monitor, PagerDuty, ServiceNow incident platform
- 대응 계획 기반 라우팅
- Application Insights와 Log Analytics 조사
- GitHub/Azure DevOps source 연결
- ServiceNow/PagerDuty incident update
- Teams/Outlook 알림 커넥터
- 검토 모드와 자율 모드

### 이번 lab에서 실제 확인한 기능

- Azure Monitor 경고에서 Agent HTTP Trigger 호출
- Application Insights, Azure Activity Log, source repository 조사
- 검토 모드에서 근본 원인과 조치 방안 생성
- GitHub Issue 실제 생성
- Outlook-compatible 이메일 초안 생성

### 이번 lab에서 실제 연결하지 않은 기능

- ServiceNow
- PagerDuty
- Outlook OAuth connector
- Microsoft Teams connector
- Native Azure Monitor response plan

이 구분을 각 섹션에서 명시해 제품 기능과 실증 결과가 혼동되지 않게 한다.

## 7. 이미지 안정성

- 핵심 이미지는 모두 repository 내 상대 경로를 사용한다.
- SVG와 PNG를 함께 제공한다.
- Markdown에서는 PNG를 기본으로 사용한다.
- SVG는 고해상도 또는 편집용 링크로 제공한다.
- 모든 local image path를 자동 검사한다.
- 외부 이미지는 링크로만 제공하고 본문 렌더링에 의존하지 않는다.

## 8. 검증 기준

### 문체

- 설명문이 `-합니다/-할 수 있습니다`체로 일관됨
- 일반 용어의 불필요한 영어 혼용이 없음
- 고객에게 직접 설명하는 문장 구조를 사용함
- `alert`, `incident`, `evidence`, `root cause`, `hypothesis`, `mitigation`의 본문 혼용을 제거

### 이미지

- 본문 외부 이미지 직접 삽입 0건
- 로컬 이미지 링크 누락 0건
- 새 PNG 3개 이상
- 이미지 가로 폭 1200px 이상
- subscription ID, token, callback URL 노출 0건

### 내용

- 제품 표준 기능과 lab 실증 결과 구분
- 프로세스 다이어그램 포함
- 대표 시나리오 3단계 패널 포함
- 실제 Agent 결론, Issue #43, 이메일 초안 화면 포함
- Storyboard GIF가 주 소개 문서에서 제거됨
- 상세 수치와 원본 근거는 검증 부록으로 연결

### 기술 검증

- 기존 전체 test 통과
- 신규 문체 검사 test 통과
- 신규 image link test 통과
- GitHub Issue #43 존재 확인
- live Azure resource 상태 확인

## 9. 참고한 문체 자료

- [Microsoft Korean Localization Style Guide](https://aka.ms/korean-styleguide)
- [Microsoft Localization Style Guides](https://learn.microsoft.com/globalization/reference/microsoft-style-guides)
- [Microsoft Terminology](https://learn.microsoft.com/globalization/reference/microsoft-terminology)
- [Microsoft language resources](https://learn.microsoft.com/globalization/reference/microsoft-language-resources)
- [Microsoft Writing Style Guide](https://learn.microsoft.com/style-guide/welcome/)
- [Microsoft brand voice: simple and human](https://learn.microsoft.com/style-guide/brand-voice-above-all-simple-human)
- [Microsoft Writing Style Guide: headings](https://learn.microsoft.com/style-guide/scannable-content/headings)
- [Microsoft Writing Style Guide: verbs](https://learn.microsoft.com/style-guide/grammar/verbs)
- [Microsoft Trademark and Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks)

## 10. 참고할 제품 자료

- [Azure SRE Agent overview](https://learn.microsoft.com/azure/sre-agent/overview)
- [Incident response](https://learn.microsoft.com/azure/sre-agent/tutorial-incident-response)
- [Root cause analysis](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [Connectors](https://learn.microsoft.com/azure/sre-agent/connectors)
- [Managed connectors](https://learn.microsoft.com/azure/sre-agent/managed-connectors)
