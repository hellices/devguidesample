# Azure SRE Agent 실제 동작 증거 캡처 설계

- 작성일: 2026-08-12
- 대상: Azure SRE Agent 이벤트 기반 장애 분석 실증 테스트
- 상태: 승인된 설계

## 1. 목적

각 장애 시나리오에서 Azure Monitor 경고가 발생한 뒤 Azure SRE Agent가 incident를 수신하고 조사·결론에 도달하는 실제 흐름을 재현 가능한 증거로 남긴다.

Portal UI 녹화만으로는 API evidence를 검증하기 어렵고 현재 실행 환경에는 UI 자동화 도구가 없다. 따라서 실제 SRE Agent data-plane 상태를 원본으로 캡처하고, 그 상태 변화를 자동으로 GIF와 Markdown 타임라인으로 렌더링한다. Portal 녹화는 사용자가 UI 모양 자체를 보존하려는 경우의 선택 절차로 둔다.

## 2. 채택 방식

### Hybrid actual-evidence capture

각 scenario마다 다음 세 계층을 만든다.

1. **원본 증거:** Azure Monitor alert와 SRE Agent API response JSON
2. **정규화 증거:** secret을 제거한 timestamp/event timeline JSON
3. **표현 자료:** PNG frame, animated GIF, Mermaid sequence, Markdown 표

GIF는 실제 UI를 흉내 낸 mockup이 아니다. 실제 alert/thread/message/action 상태를 timestamp 순으로 카드에 표시한 시각적 재생 자료다. 각 frame은 원본 evidence의 event ID를 포함해 추적 가능해야 한다.

## 3. 캡처 대상

### 3.1 Azure Monitor

- alert ID, rule, severity, monitor condition
- fired/resolved timestamp
- target resource
- alert context와 search interval

### 3.2 Azure SRE Agent

- incident thread ID와 생성 timestamp
- thread status와 title
- message ID, role, timestamp, text 요약
- tool/action event 이름, 시작/완료 상태, timestamp
- approval request와 decision 상태
- 첫 구조화 결론 timestamp

API response에 tool/action 세부 정보가 없으면 message와 thread status만 사용하고, 없는 데이터를 추정해 만들지 않는다.

### 3.3 Observability

- alert query 집계값
- 관련 request, exception, dependency 요약
- Container App revision/configuration change
- Activity Log 변경 event

## 4. 파일 구조

```text
monitor/sre-agent-event-lab/evidence/
  s1-20260812T050000Z/
    alert.json
    thread-snapshots/
      0001.json
      0002.json
    messages.json
    normalized-timeline.json

monitor/sre-agent-event-lab/assets/captures/
  s1/
    01-alert-fired.png
    02-thread-created.png
    03-investigating.png
    04-conclusion.png
    investigation.gif
    timeline.mmd
```

`evidence/`는 Git에서 제외한다. redaction을 통과한 `assets/captures/`만 commit한다.

## 5. 데이터 흐름

1. scenario runner가 장애 주입 UTC와 alert ID를 저장한다.
2. capture script가 SRE Agent `/api/v1/threads`를 polling한다.
3. alert title 또는 target resource와 일치하는 새 thread를 식별한다.
4. thread와 message endpoint를 상태 변경 시마다 snapshot한다.
5. 완료 또는 timeout 뒤 normalizer가 events를 시간순으로 정렬하고 redact한다.
6. renderer가 정규화 JSON에서 frame PNG와 GIF를 만든다.
7. Markdown generator가 보고서용 표와 Mermaid sequence를 만든다.
8. verifier가 GIF frame 수, 원본 event ID 대응, secret pattern 부재를 검사한다.

## 6. 시각 디자인

각 frame은 1280×720 고정 크기와 다음 영역을 사용한다.

- header: scenario, UTC, elapsed time, current state
- left: Azure Monitor alert card
- center: investigation timeline
- right: latest Agent message/tool/action
- footer: alert ID/thread ID의 짧은 hash, evidence file name

상태 색상:

- alert fired: red
- thread created / investigating: amber
- evidence found: blue
- conclusion / resolved: green
- timeout / API failure: gray

한 frame은 1.5초, 결론 frame은 3초 표시한다. 동일 상태가 반복되면 한 frame으로 병합한다.

## 7. Redaction과 안전

다음 값은 저장 또는 렌더링 전에 제거한다.

- bearer token과 access token
- connection string, instrumentation key
- Authorization/Cookie header
- repository credential/PAT
- 전체 query result 중 사용자 식별 정보
- managed identity token endpoint response

resource ID, alert ID, thread ID, message ID는 실험 추적에 필요하므로 유지하되 GIF footer에는 짧은 hash만 표시한다.

normalizer가 redaction forbidden pattern을 발견하면 렌더링을 실패시킨다. 성공 모양의 빈 GIF를 만들지 않는다.

## 8. 오류 처리

- thread가 timeout 내 생성되지 않으면 alert와 polling 로그를 보존하고 `thread-not-created` frame을 만든다.
- API가 401/403이면 즉시 중단하고 SRE Agent RBAC를 확인한다.
- API가 429/5xx이면 `Retry-After`를 존중해 bounded retry한다.
- message schema가 달라지면 원본 JSON을 보존하고 renderer가 unknown event를 명시한다.
- GIF 생성 도구가 없으면 PNG와 Mermaid/Markdown을 생성하고 보고서에 GIF 미생성 이유를 기록한다.

## 9. Portal 수동 녹화

Portal UI 원본이 필요한 경우:

1. SRE Agent incident thread를 연다.
2. macOS 화면 기록으로 해당 창만 녹화한다.
3. alert card, investigation plan, evidence, conclusion을 순서대로 보여준다.
4. token, 계정 메뉴, unrelated resource를 녹화하지 않는다.
5. 30~60초 MP4를 GIF로 변환하고 시나리오 asset 폴더에 둔다.

수동 녹화는 API evidence를 대체하지 않는다. 보고서의 사실 판정은 원본 API와 Azure Monitor evidence를 기준으로 한다.

## 10. 검증 기준

각 scenario는 다음을 만족해야 한다.

- alert fired, thread created, investigating, conclusion의 4개 상태가 있거나 누락 상태를 명시
- 모든 frame timestamp가 정규화 timeline event와 일치
- alert ID와 thread ID가 원본 JSON과 연결
- PNG 최소 4장, GIF 최소 4 frame
- forbidden secret pattern 0건
- GIF 재생성 명령이 README에 존재
- 보고서에서 capture asset과 원본 evidence 경로를 찾을 수 있음

## 11. 보고서 반영

각 scenario section에 다음을 추가한다.

1. investigation GIF
2. 결론 frame PNG
3. alert-to-conclusion Mermaid sequence
4. 실제 event timeline 표
5. evidence 경로와 재생성 명령
6. Portal 수동 녹화가 있으면 별도 링크
