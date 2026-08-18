# memory

에이전트 메모리 관련 가이드 모음.

## 구성

| 항목 | 내용 |
|------|------|
| **[agent-memory/](agent-memory/)** | **Agent Memory 종합 리서치 (v2)** — 아래 요약 참조 |
| [foundry-gpt-memory-v1.md](foundry-gpt-memory-v1.md) | 1차 버전. Azure Foundry GPT-5.x 3계층 메모리 (Prompt Cache → Redis Session → Foundry Memory Service) |

---

## agent-memory/ 요약

LLM 에이전트가 한 번의 대화를 넘어 사용자를 기억하게 만드는 기법들을 정리한 리서치다. 대화 버퍼·요약 같은 단기 기억부터 사실 추출·사건 기록·관계 그래프 같은 장기 기억, 그리고 이를 어떻게 저장·검색·보존(retention)할지까지 30여 개 기법을 **유형 · 저장소 · 아키텍처** 관점으로 통합했고, 마지막에는 이걸 **B2C 커머스 에이전트의 실시간 추천과 개인 맞춤 구매 유도 메시지**에 적용하는 설계로 연결한다.

**문서 6개**

| 문서 | 한 줄 요약 |
|------|-----------|
| [01. 메모리 분류 체계](agent-memory/01-memory-taxonomy.md) | Agent Memory 8유형 통합 정의 + 유형별 저장소 선택지(Azure 매핑 포함) |
| [02. 아키텍처 패턴](agent-memory/02-architecture-patterns.md) | Single-Store / Dual-Store / Tiered / Graph-Augmented / Full Cognitive 5패턴과 선택 기준 |
| [03. 파이프라인과 검색](agent-memory/03-pipeline-and-retrieval.md) | 쓰기(비동기) / 읽기(실시간) 경로 분리, hybrid search 파이프라인의 단계별 지연 비용 |
| [04. 프레임워크 비교](agent-memory/04-frameworks.md) | Mem0 · Zep · Graphiti · Letta · Cognee · Azure AI Search, 자체 구현 vs 도입 판단 |
| [05. 프로덕션과 평가](agent-memory/05-production-evaluation.md) | Tiered storage, PII·GDPR, 관측성·비용, 평가 지표와 LoCoMo/LongMemEval |
| [06. 커머스 적용 설계](agent-memory/06-commerce-application.md) | **핵심 산출물** — 메모리 스키마, 지연 예산, 안티패턴, Phase 0~4 로드맵 |

**핵심 결론 3가지**
1. 읽기(실시간)와 쓰기(비동기)를 완전히 분리한다 — 실시간 경로의 LLM 호출은 응답 생성 1회만
2. Retention을 메모리 유형별로 분리한다 — constraint는 pinned, 세션 의도는 짧은 half-life, 취향은 90~180일
3. constraint(알레르기·사이즈·예산)는 랭킹 가중치가 아니라 **하드 필터**로 처리한다
