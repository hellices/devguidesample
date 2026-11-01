---
title: 짧은 원칙·경로별 예시·밀도 검사로 줄이는 AGENTS.md 한국어 문서의 AI 문체
description: LLM 문체 연구, 한국어 번역투 규범과 공개 저장소의 한국어 규칙집을 비교해 에이전트가 쓴 한국어 문서가 AI처럼 읽히지 않게 하는 AGENTS.md 구성을 제안한다.
document_type: research
services:
  - application-development
technologies:
  - agents-md
  - python
tags:
  - evaluate
  - ai-agents
status: current
verification_status: verified
sources_checked_at: 2026-11-01
published_at: 2026-11-01
official_sources:
  - title: Localization Style Guides
    url: https://learn.microsoft.com/globalization/reference/microsoft-style-guides
  - title: Microsoft Learn style and voice quick start
    url: https://learn.microsoft.com/contribute/content/style-quick-start
  - title: Writing tips - Microsoft Writing Style Guide
    url: https://learn.microsoft.com/style-guide/global-communications/writing-tips
  - title: Prompt engineering techniques
    url: https://learn.microsoft.com/azure/foundry/openai/concepts/prompt-engineering
  - title: AGENTS.md
    url: https://github.com/agentsmd/agents.md
  - title: 자연스러운 한국어 표현 쓰기 - toss/technical-writing
    url: https://github.com/toss/technical-writing/blob/main/docs/sentence/natural-kor-expression.mdx
  - title: 쿠버네티스 한글화 모범 사례 - kubernetes/website
    url: https://github.com/kubernetes/website/blob/main/content/ko/docs/contribute/localization_ko_best_practice.md
  - title: humanize-korean quick rules - epoko77-ai/im-not-ai
    url: https://github.com/epoko77-ai/im-not-ai/blob/main/skills/humanize-korean/references/quick-rules.md
---

# 짧은 원칙·경로별 예시·밀도 검사로 줄이는 AGENTS.md 한국어 문서의 AI 문체

에이전트가 쓴 한국어 문서는 내용이 정확해도 기계가 쓴 글처럼 읽히는 경우가 많다.
원인은 감으로 짚을 문제가 아니다. LLM 문체 연구는 명사화와 분사구문 과다,
특정 어휘의 과잉, 영어식 쉼표를 수치로 보여 준다. 한국어 번역투 규범과 국내외
기술 문서 가이드도 같은 지점을 오래전부터 고치라고 해 왔다.

결론부터 적는다. AGENTS.md에는 열 줄 안팎의 핵심 원칙만 둔다. 고쳐 쓰기 예시가
담긴 상세 규칙은 문서 경로에만 적용되는 별도 지시 파일로 뺀다. 초안을 쓴 뒤에는
기계 검사로 밀도를 재고 걸린 문장만 다시 쓰게 한다. 금지어 목록을 길게 늘리는
방식은 지시 파일을 비대하게 만들고 사람도 쓰는 표현까지 지우게 한다.

## 문법·어휘·서식에서 측정되는 LLM 문체

[Reinhart 등(PNAS, 2025)](https://arxiv.org/abs/2410.16107)은 같은 지시로 사람과
LLM에게 글을 쓰게 하고 Biber의 문법·수사 특징을 비교했다. GPT-4o는 현재분사절을
사람보다 5.3배, 명사화를 2.1배 많이 썼다. 이 차이는 모델이 커져도 줄지 않았고
지시 튜닝을 거친 모델에서 더 컸다. 에이전트가 쓰는 모델은 대부분 지시 튜닝
모델이므로 이 경향을 그대로 물려받는다고 봐야 한다.

어휘도 좁다. [Kobak 등(Science Advances, 2025)](https://arxiv.org/abs/2406.07016)은
2024년 PubMed 초록에서 delves, underscores, showcasing 같은 단어가 예상보다 크게
늘어난 것을 근거로 초록의 13.5% 이상이 LLM을 거쳤다고 추정했다.
[Liang 등(ICML 2024)](https://arxiv.org/abs/2403.07183)은 학회 심사평에서 같은 현상을
찾았다. [Juzek과 Ward(COLING 2025)](https://arxiv.org/abs/2412.11385)는 과잉 단어
21개를 추리고 모델 구조나 학습 데이터보다 RLHF가 원인일 가능성을 실험으로 보였다.
특정 단어를 지우라는 지시가 실제로 존재하는 편향을 겨냥한다는 뜻이다.

Wikipedia 편집자들이 정리한
[Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing)은
연구라기보다 현장 관찰이지만 기술 문서에 바로 옮길 수 있는 목록을 준다. 의미를
부풀리는 표현, 습관적인 "A가 아니라 B" 대조, 무엇이든 셋씩 맞춘 나열, 글머리표
앞의 굵은 꼬리표, 절마다 붙는 요약과 잦은 대시가 대표적이다.

## 한국어 LLM 글에서 먼저 드러나는 영어식 쉼표와 번역투

한국어 LLM 글의 언어 특징을 사람 글과 비교해 국제 학회 정식 논문으로 보고한 연구는
이번 조사에서
[KatFishNet(Park 등, ACL 2025)](https://aclanthology.org/2025.acl-long.1030/)만
확인했다. 사람 글 470편과 LLM 글 1,624편을 비교한 결과 LLM은 띄어쓰기 규정을
지나치게 정확히 지켰고 품사 n-gram 다양성은 사람보다 낮았다. 가장 뚜렷한 차이는
쉼표였다. LLM은 쉼표를 더 많은 문장에 더 자주 찍었고 문장의 더 뒤쪽에 찍었다.
연결어미 바로 뒤에 쉼표가 오는 비율은 에세이에서 LLM 19.83%, 사람 4.10%였다.
"그리고", "그러나" 같은 접속부사 뒤 쉼표도 LLM 글에 많았다. 연구진은 영어 중심
다국어 학습에서 영어 쉼표 습관이 옮겨 온 것으로 해석한다. 쉼표 특징을 쓴 판별기는
기존 최고 방법보다 AUC-ROC가 평균 19.78% 높았다.

번역투는 LLM 이전부터 연구된 주제다.
[Wastl 등(ACL 2025 Findings)](https://arxiv.org/abs/2401.06769)은 번역문이 원문보다
단순해지는 번역투 효과를 이용해 번역 방향을 82–96% 정확도로 맞혔다. 번역문에는
통계로 잡히는 흔적이 남는다는 뜻이다.
[이창수(번역학연구, 2023)](https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11527532)는
ChatGPT 번역이 다른 기계 번역과도 문체가 다르고 격식 있는 문어 쪽으로 강하게
쏠린다고 보고했다. 국내 번역투 연구서와 규범이 짚어 온 패턴 가운데 LLM 글에서
자주 보이는 것을 고쳐 쓴 예와 함께 모았다.

| 패턴 | AI 문체 | 고쳐 쓴 문장 |
|---|---|---|
| ~에 의해 | 파일이 애플리케이션에 의해 저장된다 | 애플리케이션이 파일을 저장한다 |
| 이중 피동 | 활용되어진다, 보여진다 | 활용된다, 보인다 |
| ~에 있어서 | 설계에 있어서 중요한 것은 | 설계에서 중요한 것은 |
| 수행·진행·제공 덧붙이기 | 로그 파일을 삭제하는 작업을 수행합니다 | 로그 파일을 삭제합니다 |
| 영어식 명사화 | 흐름 런타임 뷰의 부재 | 흐름 런타임 뷰가 없다 |
| ~의 연쇄 | 쿠버네티스의 컴포넌트의 구성 | 쿠버네티스 컴포넌트 구성 |
| ~을 가지고 있다 | 강한 경쟁력을 가지고 있다 | 경쟁력이 강하다 |
| ~하는 것이 중요하다 | 검사하는 것이 중요하다 | 검사해야 한다 |
| 대명사·'들' 직역 | 그것은 이것들을 통해 검증된다 | 주어를 빼거나 구체적인 명사로 쓴다 |
| 연결어미 뒤 쉼표 | 설정을 바꾸고, 다시 배포하며, 로그를 본다 | 설정을 바꾸고 다시 배포한 뒤 로그를 본다 |

수행·진행 예시는 토스 테크니컬 라이팅 가이드에서, '~의' 연쇄 예시는 쿠버네티스
한글화 모범 사례에서, '~을 가지고 있다' 예시는 im-not-ai 규칙집에서 가져왔다.

## 사람 글에도 있는 표지의 밀도 기준

AI 문체 목록을 금지어처럼 쓰면 사람 글에도 흔한 표현까지 지운다. 한국어 고쳐
쓰기 스킬 가운데 가장 널리 쓰이는
[im-not-ai](https://github.com/epoko77-ai/im-not-ai)는 사람 글 말뭉치와 비교해
규칙마다 조건을 달았다. "~에 대해"는 사람이 세 배 더 쓰는 표현이라 한 문단에 세
번 이상 몰릴 때만 고친다. "A가 아니라 B" 대조는 사람 글 532편 중 31편에서도 나와
두 번 이상 이어질 때만 하나를 남기고 바꾼다. 연결어미 뒤 쉼표는 여섯 번 이상을
강한 신호로 본다.

이 규칙집은 고쳐 쓸 때 지킬 불변 조건도 둔다. 고유명사, 수치, 날짜와 인용은 한
글자도 바꾸지 않는다. "~해야 한다"와 "~일 수 있다" 같은 서법과 문서의 격식
등급도 그대로 둔다. 원문에 없던 비유나 상투구를 새로 넣지 않으며 변경률이 30%를
넘으면 경고하고 50%를 넘으면 되돌린다. 고쳐 쓰기가 새 AI 문체를 주입할 수 있다는
점을 실측으로 확인하고 넣은 장치다.

영어 연구도 같은 주의를 준다.
[Fitterer 등(ACL 2025 SRW)](https://aclanthology.org/2025.acl-srw.95/)은 2018년과
2024년 뉴스 말뭉치에서 LLM 스타일 단어 비율은 올랐지만 어휘 다양성 지표 일부는
떨어지지 않았다고 보고했다. "다양하게 써라" 같은 막연한 지시보다 측정할 수 있는
구체적인 표지를 겨냥하는 편이 낫다.

## LLM 문체와 반대 방향을 가리키는 국내외 문서 가이드

Microsoft는 언어별 현지화 스타일 가이드를
[Microsoft Learn](https://learn.microsoft.com/globalization/reference/microsoft-style-guides)에서
배포한다. [한국어 가이드](https://aka.ms/korean-styleguide)는 제품 문구가 처음부터
한국어로 쓴 것처럼 읽혀야 한다고 정한다. 영어 단어를 하나씩 옮기는 번역을 피하고
문단 전체의 의도를 이해한 뒤 직접 쓰듯 다시 쓰라고 한다(2.1.1, 2.1.4). '수행',
'실행', '제공'으로 서술형 명사를 꾸미지 말고 "제거를 수행합니다" 대신
"제거합니다"로 쓰라고 한다(2.1.2). 수식어는 동사나 부사로 바꾸고(4.1.7) '들'과
대명사는 의미가 통하면 생략한다(4.1.8, 4.1.9). 소유 중심 영어 표현은 존재 중심
한국어 표현으로 바꾼다("권한을 가지고 있지 않을 수 있습니다"를 "권한이 없을 수
있습니다"로, 4.1.11). Copilot 프롬프트 현지화 절은 기계처럼 들리는 어조를 피하라고
따로 적었다(5.3).

[Microsoft Learn 스타일 빠른 시작](https://learn.microsoft.com/contribute/content/style-quick-start)과
[글로벌 콘텐츠 작성 팁](https://learn.microsoft.com/style-guide/global-communications/writing-tips)은
영어 문서 기준이지만 짧은 문장, 문장 앞쪽에 둔 주어, 한 개념에 한 단어를 권한다.
수식어를 길게 쌓지 말고 등위 접속으로 세 개 넘는 절을 잇지 말라는 조언은 한국어
연결어미 문장에도 그대로 통한다.

국내 가이드도 방향이 같다.
[토스 테크니컬 라이팅](https://github.com/toss/technical-writing)은 불필요한 한자어와
영어식 명사형을 동사로 되돌리라고 한다.
[카카오디벨로퍼스 문서 스타일 가이드](https://developers.kakao.com/docs/ko/documentation-guideline/document-style-open)는
종결 표현을 통일하고 외래어는 처음 한 번만 병기하라고 한다.
[쿠버네티스 한글화 모범 사례](https://github.com/kubernetes/website/blob/main/content/ko/docs/contribute/localization_ko_best_practice.md)는
리뷰에서 실제로 고친 사례를 모았다. 영어 콜론으로 끝나는 문장을 마침표로 바꾸고
'~의'를 덜어 내는 규칙은
[Hugging Face 한국어 번역 가이드](https://github.com/Hugging-Face-KREW/hf-workflow)에도
독립적으로 들어 있다. [React 한국어 문서](https://github.com/reactjs/ko.react.dev)는
용어집 위반을 textlint 규칙으로 잡되 문체는 사람이 판단하도록 자동 수정 기능을 일부러
넣지 않았다.

## 규칙집·고쳐 쓰기 스킬·검사 도구로 나뉘는 공개 저장소

2026년 11월 1일 기준으로 확인한 저장소다.

| 저장소 | 방식 | 가져올 점 | 한계 |
|---|---|---|---|
| [blader/humanizer](https://github.com/blader/humanizer) | Wikipedia 목록 기반 영어 고쳐 쓰기 스킬 | 여러 에이전트에 같은 스킬을 배포하는 구성 | 한국어 규칙 없음 |
| [epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai) | 한국어 고쳐 쓰기 스킬, 규칙 약 70개와 심각도 | 밀도 조건, 불변 조건, 변경률 상한 | 규칙집이 커서 지시 파일에 통째로 넣기 어렵다 |
| [DaleSeo/korean-skills](https://github.com/DaleSeo/korean-skills) | 한국어 문체 일관성 검사 스킬 | 문서 장르별 기본값 표, 다수결로 표기 통일 | AI 문체보다 일관성에 초점 |
| [toss/technical-writing](https://github.com/toss/technical-writing) | 사람이 만든 기술 글쓰기 교재 | 고쳐 쓰기 전후 예문 | 에이전트 지시용 형식이 아니다 |
| [kubernetes/website](https://github.com/kubernetes/website/blob/main/content/ko/docs/contribute/localization_ko_best_practice.md) | 리뷰 사례 기반 현지화 규칙 | PR로 검증된 실제 판단 | 번역 문서 기준 |
| [reactjs/ko.react.dev](https://github.com/reactjs/ko.react.dev) | 용어집과 textlint 규칙 | 코드 블록과 인용을 건너뛰는 검사 범위 | 문체 규칙은 자동화하지 않았다 |
| [sam-paech/antislop-sampler](https://github.com/sam-paech/antislop-sampler) | 영어 상투구 목록과 디코딩 단계 억제 | 상투구 목록을 데이터 파일로 분리 | 모델 출력 단계를 바꿀 수 있어야 한다 |

에이전트 지시 파일 표준인 [AGENTS.md](https://github.com/agentsmd/agents.md)는 개발
환경, 테스트와 PR 절차 같은 운영 정보를 예로 들 뿐 문체 규칙은 다루지 않는다.
한국어 규칙은 저장소마다 직접 써야 한다. 범용 한국어 textlint나 Vale 프리셋도
찾지 못했다. 그래서 이 문서의 sample로 정규식 기반 밀도 검사기를 함께 둔다.

## 짧고 구체적인 지시와 예시의 이행 효과

GitHub Copilot은 저장소의 AGENTS.md 가운데
[작업 위치에서 가장 가까운 파일을 우선](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions)한다.
`.github/instructions/*.instructions.md`에 `applyTo` glob을 지정하면 해당 경로를
다룰 때만 지시가 더해진다. 같은 문서가 저장소 지시 파일을 자동 생성할 때 쓰는
기준은 두 쪽을 넘기지 않고 특정 작업에 묶이지 않는 것이다.
[VS Code 문서](https://code.visualstudio.com/docs/agent-customization/custom-instructions)도
지시를 가장 좁은 범위에 두라고 권한다.

Claude Code 문서는 [메모리 파일](https://code.claude.com/docs/en/memory)을 강제 설정이
아닌 맥락으로 다루며 구체적이고 짧을수록 더 일관되게 따른다고 적었다. Anthropic의
[프롬프트 작성 모범 사례](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)는
금지만 적기보다 이유를 함께 줄 때 모델이 규칙을 일반화한다고 설명한다. 어조와
구조를 맞추는 가장 믿을 만한 방법으로는 예시를 꼽는다.
[Microsoft Foundry 프롬프트 엔지니어링 문서](https://learn.microsoft.com/azure/foundry/openai/concepts/prompt-engineering)도
구체적으로 지시하고 예시를 주며 필요하면 지시를 앞뒤에 반복하라고 한다. 다만 이
문서는 해당 기법을 GPT-5나 o 시리즈 같은 추론 모델에는 권하지 않는다고 밝힌다.

연구 결과도 같은 쪽을 가리킨다.
[IFEval(Zhou 등, 2023)](https://arxiv.org/abs/2311.07911)은 글자 수나 키워드 횟수처럼
기계로 확인할 수 있는 지시를 기준으로 지시 이행을 평가한다. 규칙을 셀 수 있는
형태로 쓰면 이행 여부를 검사할 수 있다.
[Self-Refine(Madaan 등, NeurIPS 2023)](https://arxiv.org/abs/2303.17651)은 같은 모델이
초안을 쓰고 스스로 비평한 뒤 고치게 해 일곱 과제에서 평균 약 20%p 개선했다. 초안
작성과 고쳐 쓰기를 나누는 근거다. 소수 예시로 문체를 옮기는 연구인
[Prompt-and-Rerank](https://arxiv.org/abs/2205.11503)와
[TinyStyler](https://arxiv.org/abs/2406.15586)는 추상적인 문체 설명보다 구체적인 예문이
문체 전이에 더 강한 지렛대라는 결과를 냈다.

## 짧은 원칙·분리된 규칙집·검사 단계의 권장 조합

| 방식 | 구성 | 장점 | 문제 |
|---|---|---|---|
| 금지 목록형 | AGENTS.md에 금지어·금지 패턴 수십 개 | 바로 적용 | 지시 파일이 길어지고 사람도 쓰는 표현까지 지운다. 대체 표현이 없어 다른 상투구로 옮겨 간다 |
| 원칙·규칙집·검사 분리형 | AGENTS.md 핵심 원칙, 경로 지정 규칙집, 밀도 검사기, 고쳐 쓰기 단계 | 지시가 짧고 예시가 필요한 때만 붙는다. 결과를 숫자로 확인한다 | 규칙집과 검사기를 저장소가 관리해야 한다 |
| 외부 고쳐 쓰기 스킬 위임형 | 초안 뒤 im-not-ai 같은 스킬로 일괄 윤문 | 규칙 품질이 높고 유지 부담이 적다 | 처음부터 잘 쓰게 하지는 못한다. 문서 전체를 다시 쓰므로 변경 검토 범위가 넓다 |

두 번째 방식을 기본으로 삼고 큰 문서를 정리할 때만 세 번째 방식을 함께 쓰기를
권한다. 이 저장소의 AGENTS.md도 상세 기준을 `docs/contributing/index.md` 한 곳에
두고 지시 파일에는 요약만 남기는 구조라 같은 방식이 잘 맞는다.

### 이유를 붙인 AGENTS.md 핵심 원칙

아래 예시는 공개 문서를 `~다`로 끝맺는 저장소를 기준으로 했다. 마지막 줄의 검사기는
이 topic의 sample을 저장소의 `scripts/`에 복사했다고 가정한다.

```markdown
## 한국어 문서 문체

- 공개 문서는 `~다`로 끝맺는다. 한 문서에서 `~합니다`와 섞지 않는다.
- 처음부터 한국어로 쓴 글처럼 쓴다. 영어 문장 구조를 옮기면 번역투가 된다.
  고쳐 쓰기 예시는 `.github/instructions/korean-docs.instructions.md`를 따른다.
- 누가 무엇을 하는지 주어를 세우고 동사로 끝낸다. "~의 부재"처럼 명사로 끝내지 않는다.
- 설명은 문단으로 쓴다. 글머리표는 순서나 실제 나열에만, 표는 같은 기준의 비교에만 쓴다.
- 굵은 글씨는 처음 정의하는 용어에만 쓴다. `**꼬리표**:` 줄, `X: Y` 형식 제목과 대시(—)는
  LLM 글의 전형이므로 문장으로 풀어 쓴다.
- 제목은 절의 핵심을 담은 명사구로 쓴다. "~합니다"나 "~다"로 끝나는 문장형 제목은
  본문 문장처럼 읽혀 목차를 훑기 어렵다.
- 연결어미(-고·-며·-지만)와 접속부사(그리고·따라서) 뒤에는 쉼표를 찍지 않는다.
  LLM이 영어 습관으로 과하게 찍는 대표 패턴이다.
- "다양한", "효과적인", "중요한"을 쓰고 싶으면 그 자리에 수치나 사례를 넣는다.
  확인한 사실은 단정하고 불확실하면 무엇이 불확실한지 적는다.
- 기존 문서를 고칠 때는 수치·고유명사·인용과 원문의 확신 정도("~해야 한다",
  "~일 수 있다")를 바꾸지 않는다. 고치면서 새 수사를 넣지 않는다.
- 문서를 다 쓰면 `python scripts/check_korean_style.py --strict <파일>`을 실행하고
  걸린 문장만 다시 쓴다.
```

### 문서 경로에만 적용하는 고쳐 쓰기 예시

예시는 지시보다 길지만 문체를 옮기는 힘이 크다. 문서를 다룰 때만 붙도록
`applyTo`로 범위를 좁힌다. 규칙마다 고쳐 쓴 문장을 함께 주고 밀도 조건을 단다.

```markdown
---
applyTo: "docs/**/*.md"
---

# 한국어 문서 고쳐 쓰기 예시

각 줄은 "AI 문체 → 고쳐 쓴 문장" 순서다. 같은 표현이 한두 번 나오는 것은 괜찮다.
한 문단에 몰릴 때 고친다.

- 행위자를 주어로: "파일이 애플리케이션에 의해 저장된다" → "애플리케이션이 파일을 저장한다"
- 덧붙인 한자어 동사 빼기: "삭제하는 작업을 수행합니다" → "삭제합니다"
- 명사화 풀기: "인증 처리가 완료된 후 접속 설정 진행이 가능합니다"
  → "사용자를 인증한 후 접속하도록 설정할 수 있습니다"
- '~의' 줄이기: "흐름의 모양의 검사의 결과" → "흐름 모양을 검사한 결과"
- 소유 대신 존재: "필요한 권한을 가지고 있지 않을 수 있습니다" → "필요한 권한이 없을 수 있습니다"
- 결론 상자 대신 마지막 문장: "**결론**: 코드가 문서를 이겼다." → "시간이 지나자 그림은 코드와 맞지 않게 됐다."
- 대조 남발 줄이기: "효과는 지연이 아니라 신뢰성에서 나왔다" → "지연 시간은 그대로였고 화면 실패율이 줄었다"
- 콜론 제목 풀기: "## 흐름 런타임 뷰의 부재: 기존 시스템의 문제" → "## 흐름 전체를 보여 주는 기록이 없는 기존 시스템"
- 문장형 제목 줄이기: "## 처음 1,024 토큰이 바이트 단위로 같아야 캐시가 적중합니다" → "## 처음 1,024 토큰의 바이트 일치 조건"
- 영어 용어는 처음 한 번만 병기: "구간(hop)" 이후에는 "구간"
```

### 초안과 고쳐 쓰기의 분리와 수치 확인

에이전트에게 한 번에 잘 쓰라고 요구하기보다 초안을 쓴 뒤 검사기를 돌리고 걸린
문장만 고치게 한다. 이 topic의 sample인 한국어 문체 밀도 검사기는 표준
라이브러리만 쓰는 Python 스크립트다. 콜론 제목, 문장형 제목, 굵은 글씨 밀도, 굵은 꼬리표,
연결어미와 접속부사 뒤 쉼표, 번역투, 결산 접속어, 대조, 대시, 종결어미 혼용과
글머리표·표 비율을 세고 예시 문구를 함께 출력한다. `--strict`를 주면 기준을 넘을 때
종료 코드 1을 돌려준다. 작업 종료 전 점검이나 pre-commit 훅에 연결할 수 있다.

고치는 순서는 다음이 효율적이었다.

1. 같은 기준으로 비교하는 표만 남기고 나머지 표와 글머리표를 문단으로 바꾼다.
2. 굵은 꼬리표를 걷어 내고 콜론 제목과 문장형 제목을 명사구로 줄인다.
3. 명사로 끝난 문장과 '~의' 연쇄를 동사 문장으로 바꾼다.
4. 대조, 결산 접속어와 부풀린 표현을 찾아 줄인다.
5. 소리 내어 읽고 같은 길이의 문장이 이어지는 곳을 나누거나 합친다.

## 콜론 부제목과 문장형 제목을 뺀 내용 중심 명사구 제목

이 저장소는 제목이 내용의 결론을 요약하도록 요구한다. 이 요구를 에이전트에게
주면 "흐름 패턴: 규격화의 단위"처럼 일반 명사구 뒤에 콜론과 부제를 붙이는 형식이
늘기 쉽다. 이 형식은 Wikipedia 목록과 im-not-ai 규칙집이 모두 LLM 전형으로 꼽는다.
결론을 담으면서도 이 형식을 피하려면 "흐름 전체를 보여 주는 기록이 없는 기존
시스템"처럼 핵심을 명사구 하나로 압축한다. 저장소 기여 가이드의 예시도 "연결 종료 뒤
요청이 복구되지 않는 현상", "TTL·키 값 검증 후 새 저장소로 트래픽 전환"처럼 모두
명사구다.

콜론을 없애려고 제목을 문장으로 바꾸면 다른 문제가 생긴다. 이 문서의 검사기로 가장
점수가 나빴던 Microsoft Foundry 메모리 계층 문서를 고칠 때 처음에는 제목 36개를
"처음 1,024 토큰이 바이트 단위로 같아야 캐시가 적중합니다"처럼 `~합니다` 문장으로
바꿨다. 굵은 글씨, 꼬리표와 대시는 모두 없어졌지만 목차가 본문 문장을 늘어놓은 것처럼
읽혔다. 그래서 검사기에 문장형 제목 항목을 더하고 "처음 1,024 토큰의 바이트 일치
조건"처럼 명사구로 다시 줄였다.

한 설계 문서(373줄)에 이 기준을 적용한 결과다. 처음 상태에서 굵은 글씨는 68곳,
굵은 꼬리표로 시작하는 줄은 13줄, 콜론 부제목은 17개였다. 표 행은 148줄로 문서의
40%였고 "A가 아니라 B"는 다섯 번 나왔다. 고쳐 쓴 뒤 문서는 321줄이 됐다. 굵은 글씨와
콜론 부제목은 모두 없앴고 표 행은 43줄로 줄였다. 남은 표는 후보, 명령, 검증 계획처럼
같은 기준으로 여러 대상을 비교하는 것뿐이다. 대조는 두 번만 남겼다.

## 부족한 한국어 실증 연구와 측정되지 않은 지시 효과

한국어 LLM 글의 특징을 국제 학회 정식 논문으로 보고한 연구는 이번 조사에서
KatFishNet만 확인했다. 대상 장르는 에세이, 시, 논문 초록이라 기술 문서에서 같은
비율이 나온다는 증거는 아직 없다. 국내에서도 음운과 품사 특징으로 한국어 AI 글을
판별한 실증 연구로
[KoboNet(Jang 등, KCC 2025)](https://hyeonjongjang.github.io/publication/2025-07-01-poster-1)이
있다. 다만 세 쪽 분량의 학술대회 발표로 판별 모델 설계가 중심이고, 문체를 고치는
방법은 두 연구 모두 다루지 않는다.

AGENTS.md의 한국어 문체 지시가 결과를 얼마나 바꾸는지 직접 잰 연구는 찾지 못했다.
"하지 마라" 형태 지시가 덜 지켜진다는 주장도 이번 조사에서는 원문으로 확인한
논문이 없어 근거로 쓰지 않았다. 권장안은 공급자 문서, 문체 전이 연구와 Self-Refine
같은 간접 근거를 조합한 것이다.

im-not-ai의 사람 글 대비 수치는 저장소가 스스로 측정해 공개한 값이며 동료 심사를
거치지 않았다. 검사기의 기본 기준값도 이 저장소 문서를 읽으며 정한 출발점이다.
목표는 읽는 사람이 막히지 않는 문장이다. AI 판별기 점수는 품질 지표로 쓰지 않는다.

국립국어원의 [다듬은 말](https://www.korean.go.kr/front/imprv/refineList.do)과
어문 규범은 용어와 맞춤법 판단의 기준이지만 이번 조사에서 PDF 지침 원문은 직접
열람하지 못했다. 번역투 단행본(이오덕 『우리글 바로쓰기』, 이희재 『번역의 탄생』,
오경순 『번역투의 유혹』)도 서지와 요약으로만 확인했다.

## 참고한 연구와 저장소

연구

- Reinhart et al., "Do LLMs write like humans? Variation in grammatical and rhetorical styles", PNAS 122 (2025). <https://arxiv.org/abs/2410.16107>
- Kobak et al., "Delving into LLM-assisted writing in biomedical publications through excess vocabulary", Science Advances 11 (2025). <https://arxiv.org/abs/2406.07016>
- Liang et al., "Monitoring AI-Modified Content at Scale: A Case Study on the Impact of ChatGPT on AI Conference Peer Reviews", ICML 2024. <https://arxiv.org/abs/2403.07183>
- Juzek and Ward, "Why Does ChatGPT 'Delve' So Much? Exploring the Sources of Lexical Overrepresentation in Large Language Models", COLING 2025. <https://arxiv.org/abs/2412.11385>
- Fitterer et al., "Testing English News Articles for Lexical Homogenization Due to Widespread Use of Large Language Models", ACL 2025 SRW. <https://aclanthology.org/2025.acl-srw.95/>
- Park et al., "KatFishNet: Detecting LLM-Generated Korean Text through Linguistic Feature Analysis", ACL 2025. <https://aclanthology.org/2025.acl-long.1030/>
- Wastl et al., "Machine Translation Models are Zero-Shot Detectors of Translation Direction", ACL 2025 Findings. <https://arxiv.org/abs/2401.06769>
- 이창수, 「챗GPT 출현 이후 기계 번역과 인간 번역 간의 번역 문체 차이 변화 연구」, 번역학연구 24(3), 2023. <https://www.dbpia.co.kr/journal/articleDetail?nodeId=NODE11527532>
- Zhou et al., "Instruction-Following Evaluation for Large Language Models", 2023. <https://arxiv.org/abs/2311.07911>
- Madaan et al., "Self-Refine: Iterative Refinement with Self-Feedback", NeurIPS 2023. <https://arxiv.org/abs/2303.17651>
- Suzgun et al., "Prompt-and-Rerank: A Method for Zero-Shot and Few-Shot Arbitrary Textual Style Transfer with Small Language Models", EMNLP 2022. <https://arxiv.org/abs/2205.11503>
- Horvitz et al., "TinyStyler: Efficient Few-Shot Text Style Transfer with Authorship Embeddings", EMNLP 2024 Findings. <https://arxiv.org/abs/2406.15586>

가이드와 저장소

- Microsoft, Korean Localization Style Guide. <https://aka.ms/korean-styleguide>
- Wikipedia, "Signs of AI writing" (WikiProject AI Cleanup). <https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing>
- Google developer documentation style guide. <https://developers.google.com/style>
- 카카오디벨로퍼스 문서 스타일 가이드. <https://developers.kakao.com/docs/ko/documentation-guideline/document-style-open>
- GitHub Docs, Adding repository custom instructions for GitHub Copilot. <https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions>
- Visual Studio Code, Use custom instructions in VS Code. <https://code.visualstudio.com/docs/agent-customization/custom-instructions>
- Anthropic, Prompting best practices. <https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices>
- Anthropic, How Claude remembers your project. <https://code.claude.com/docs/en/memory>

## 공식 출처

- [Localization Style Guides](https://learn.microsoft.com/globalization/reference/microsoft-style-guides)
- [Microsoft Learn style and voice quick start](https://learn.microsoft.com/contribute/content/style-quick-start)
- [Writing tips - Microsoft Writing Style Guide](https://learn.microsoft.com/style-guide/global-communications/writing-tips)
- [Prompt engineering techniques](https://learn.microsoft.com/azure/foundry/openai/concepts/prompt-engineering)
- [AGENTS.md](https://github.com/agentsmd/agents.md)
- [자연스러운 한국어 표현 쓰기 - toss/technical-writing](https://github.com/toss/technical-writing/blob/main/docs/sentence/natural-kor-expression.mdx)
- [쿠버네티스 한글화 모범 사례 - kubernetes/website](https://github.com/kubernetes/website/blob/main/content/ko/docs/contribute/localization_ko_best_practice.md)
- [humanize-korean quick rules - epoko77-ai/im-not-ai](https://github.com/epoko77-ai/im-not-ai/blob/main/skills/humanize-korean/references/quick-rules.md)
