# Agent Memory 종합 리서치

자체 에이전트 프레임워크로 **B2C 서비스 에이전트**를 운영하는 개발 조직을 대상으로, 메모리를 정교화해 **실시간 추천**과 **개인 맞춤 구매 유도 메시지**를 제공하기 위한 리서치 결과물이다.

---

## 30초 요약

| # | 핵심 결론 |
|---|----------|
| 1 | **읽기(실시간)와 쓰기(비동기)를 완전히 분리한다.** LLM을 쓰는 extraction·consolidation·routing은 전부 비동기로. 실시간 경로의 LLM 호출은 응답 생성 1회만 |
| 2 | **Retention을 메모리 유형별로 분리한다.** 알레르기·사이즈는 pinned, 세션 의도는 half-life 수십 분, 취향은 90~180일 |
| 3 | **constraint는 랭킹 가중치가 아니라 하드 필터다.** 커머스 메모리 설계에서 가장 흔한 실패 지점 |
| 4 | **Dual-Store에서 시작한다.** Redis(세션) + PostgreSQL/pgvector(프로필)로 개인화의 대부분을 커버. Full Cognitive는 오버엔지니어링 위험이 가장 큰 패턴 |
| 5 | **대화만이 메모리 입력이 아니다.** 조회·장바구니·구매·반품이 커머스에서는 대화보다 강한 신호 |
| 6 | **평가 하네스를 먼저 만든다.** baseline 없이는 이후 모든 최적화가 추측이 된다 |

---

## 문서 구성

| 문서 | 내용 | 대상 |
|------|------|------|
| **[01. 메모리 분류 체계](01-memory-taxonomy.md)** | Agent Memory **8유형 통합 정의**, 유형별 **저장소 선택지**와 Azure 매핑, Retention 정책, 30기법 6패밀리 지도 | 전원 |
| **[02. 아키텍처 패턴](02-architecture-patterns.md)** | Single-Store / Dual-Store / Tiered / Graph-Augmented / Full Cognitive 5패턴, 비교표, 선택 결정 트리 | 아키텍트 |
| **[03. 파이프라인과 검색](03-pipeline-and-retrieval.md)** | 쓰기 경로(추출→중복·모순 해소→라우팅) / 읽기 경로(hybrid search→RRF→rerank→MMR→temporal), 단계별 지연 비용 | 개발자 |
| **[04. 프레임워크 비교](04-frameworks.md)** | Mem0 · Zep · Graphiti · Letta(MemGPT) · Cognee · Azure AI Search, **자체 구현 vs 도입 판단 기준** | 의사결정자 |
| **[05. 프로덕션과 평가](05-production-evaluation.md)** | Tiered storage, PII·GDPR, TTL·샤딩·관측성·비용, 평가 지표, LoCoMo/LongMemEval 벤치마크 | SRE / 개발자 |
| **[06. 커머스 적용 설계](06-commerce-application.md)** | **메모리 스키마 · 지연 예산 · 개인화 강도 단계화 · 안티패턴 · Phase 0~4 로드맵 · 기술+비즈니스 지표** | 전원 (핵심) |

---

## 다이어그램

| 파일 | 내용 |
|------|------|
| [images/01-memory-taxonomy.svg](images/01-memory-taxonomy.svg) | 6패밀리 30기법 전체 지도 |
| [images/02-architecture-patterns.svg](images/02-architecture-patterns.svg) | 5가지 아키텍처 패턴 비교 |
| [images/03-memory-pipeline.svg](images/03-memory-pipeline.svg) | 쓰기 경로 / 읽기 경로 분리 |
| [images/04-production-tiers.svg](images/04-production-tiers.svg) | 프로덕션 계층 저장 + 가드레일 |
| [images/05-commerce-blueprint.svg](images/05-commerce-blueprint.svg) | B2C 커머스 메모리 블루프린트 |

---

## 읽는 순서

**시간이 없다면** → [06. 커머스 적용 설계](06-commerce-application.md) 만 읽는다. 나머지 문서의 결론이 여기 수렴한다.

**설계를 시작한다면**
```
01 (유형·저장소 정의)  →  02 (아키텍처 선택)  →  06 (커머스 설계)
```

**구현에 들어간다면**
```
03 (파이프라인)  →  04 (직접 만들지 도입할지)  →  05 (운영·평가)
```

---

## Phase 요약

| Phase | 내용 | 산출물 |
|-------|------|--------|
| **0** | 평가 하네스 + baseline + 이벤트 스키마 + PII·동의 게이트 | 측정 가능한 상태 |
| **1** | Dual-Store (Redis + pgvector), 비동기 추출, hybrid search, constraint 하드 필터, 기본 로깅 | 되묻지 않는 에이전트 |
| **2** | Temporal Memory, Episodes, Consolidation, Decay, 개인화 강도 L1~L4 | 의도와 취향을 구분하는 추천 |
| **3** | HOT/WARM 티어링, Structured RAG, Product Graph, 관측성 | 규모에서의 지연·비용 통제 |
| **4** | Memory Routing, Procedural, Self-Reflection, COLD 아카이브 | 선택적 고도화 |

상세는 [06. 커머스 적용 설계 §10](06-commerce-application.md) 참조.

---

## 참고 자료

| # | 자료 | 내용 |
|---|------|------|
| 1 | **[Microsoft — ai-agents-for-beginners / 13-agent-memory](https://github.com/microsoft/ai-agents-for-beginners/tree/main/13-agent-memory)** | 메모리 유형 정의, Structured RAG, self-improving 패턴 |
| 2 | [NirDiamant — Agent Memory Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) | 30기법 / 6패밀리, [아키텍처 패턴](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/docs/architecture.md) · [비교 매트릭스](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/docs/comparison.md) |
| 3 | [MemGPT 논문 (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560) · [Letta docs](https://docs.letta.com) | 자기수정 3계층 메모리의 원형 |
| 4 | [Mem0](https://github.com/mem0ai/mem0) | 관리형 메모리 레이어 (extraction → update) |
| 5 | [Zep](https://github.com/getzep/zep) | 시간 인식 지식 그래프 기반 프로덕션 메모리 |
| 6 | [Memory Mechanism of LLM-Based Agents 서베이 (arXiv:2404.13501)](https://arxiv.org/abs/2404.13501) | 학술적 분류 체계 |

문서별 상세 참고 자료는 각 문서 하단에 있다.
