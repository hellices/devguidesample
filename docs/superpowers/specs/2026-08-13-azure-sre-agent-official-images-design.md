# Azure SRE Agent 공식 이미지 통합 설계

## 목적

Microsoft Learn의 Azure SRE Agent 공식 이미지 5개를 소개 문서에 추가해 제품의 인시던트 대응, 근본 원인 분석, 추론, 메모리, 자동 학습 방식을 시각적으로 설명합니다. 기존 실증 이미지는 공식 제품 동작이 실제 환경에서 어떻게 나타났는지 보여주는 근거로 유지합니다.

## 사용할 공식 이미지

1. Incident Response Flow
2. Root Cause Analysis Flow
3. Agent Reasoning Loop
4. Memory Unified Search
5. Memory Auto-Learning

이미지는 Microsoft Learn에 게시된 SVG 원본을 수정하지 않고 repository의 `monitor/sre-agent-event-lab/assets/official/`에 저장합니다. 각 이미지에는 원문 페이지 링크와 Microsoft Learn 출처를 표시합니다.

## 문서별 배치

공식 이미지는 하나의 연속 설명으로 묶지 않습니다. 각 이미지를 기존 문서의 해당 주제 바로 옆에 배치하고, 알맞은 섹션이 없을 때만 새 섹션을 추가합니다.

### 제품 소개 문서

대상: `monitor/azure-sre-agent.md`

- `Incident Response Flow`: 기존 **인시던트가 발생하면 어떻게 조사하나요?** 섹션에 배치합니다. 기존 한국어 프로세스 다이어그램은 실증 경로 설명으로 이동합니다.
- `Root Cause Analysis Flow`: 조사 단계 설명 뒤에 **근본 원인은 어떻게 찾나요?** 섹션을 추가하고 배치합니다.
- `Agent Reasoning Loop`: 기존 **권한과 승인 절차는 어떻게 제어하나요?** 섹션에 배치합니다.
- `Memory Unified Search`: **과거 경험과 운영 문서는 어떻게 활용하나요?** 섹션을 추가하고 배치합니다.
- `Memory Auto-Learning`: **조사가 끝난 뒤 무엇을 학습하나요?** 섹션을 추가하고 배치합니다.

각 이미지 아래에는 해당 기능을 설명하는 한국어 문단과 Microsoft Learn 원문 링크를 둡니다. 다섯 이미지를 순서대로 읽지 않아도 각 섹션만으로 내용을 이해할 수 있어야 합니다.

### 실험실 재현 문서

대상: `monitor/sre-agent-event-lab/README.md`

이 문서는 배포와 재현 절차에 집중하므로 공식 개념 이미지를 본문에 반복하지 않습니다. **공식 자료** 섹션에서 제품 소개 문서와 해당 Microsoft Learn 원문으로 연결합니다.

### 실제 동작 검증 부록

대상: `docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md`

이 문서는 실측 결과와 증거 보존에 집중하므로 공식 개념 이미지를 추가하지 않습니다. 제품 설명이 필요한 독자는 제품 소개 문서로 안내합니다.

## 기존 이미지 처리

- 기존 한국어 프로세스 다이어그램은 삭제하지 않고 **이번 실증에서 사용한 방식** 섹션으로 이동합니다.
- 실제 GitHub Issue, Outlook 메일 초안, Agent 결론 카드는 그대로 유지합니다.
- Storyboard와 GIF는 소개 문서에 다시 추가하지 않습니다.

## 표시 원칙

- 공식 SVG 내부의 영어 텍스트는 수정하지 않습니다.
- 이미지 직후에 자연스러운 한국어 설명을 제공합니다.
- 이미지의 원문 Microsoft Learn 페이지를 함께 연결합니다.
- 공식 제품 동작과 이번 실증에서 확인한 동작을 계속 구분합니다.
- 로컬 파일을 사용해 외부 이미지 로딩 실패를 방지합니다.

## 검증 기준

- 공식 SVG 5개가 모두 repository에 존재하고 정상적으로 렌더링됩니다.
- 소개 문서에서 다섯 이미지를 모두 참조합니다.
- 각 이미지에 한국어 설명과 Microsoft Learn 원문 링크가 있습니다.
- 공식 제품 동작과 실증 경로의 구분이 유지됩니다.
- 기존 전체 테스트와 Bicep 검증이 통과합니다.
- 소개 문서에 외부 이미지 직접 삽입, Storyboard, GIF 참조가 없습니다.
- secret-pattern 검사에서 민감 정보가 발견되지 않습니다.
