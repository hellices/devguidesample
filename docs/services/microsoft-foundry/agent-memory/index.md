---
services:
- microsoft-foundry
official_sources:
- title: Microsoft Foundry documentation
  url: https://learn.microsoft.com/azure/ai-foundry/
document_type: research
status: current
verification_status: needs-review
sources_checked_at: 2026-09-12
title: Agent Memory 종합 리서치
description: AI agent memory의 분류, 아키텍처, 검색, 프레임워크와 운영 평가를 종합합니다.
technologies:
- rag
tags:
- design
- ai-agents
published_at: 2026-08-24
redirect_from:
- research/microsoft-foundry/agent-memory-overview/index.md
---

# Agent Memory 종합 리서치

자체 에이전트 프레임워크로 **B2C 서비스 에이전트**를 운영하는 개발 조직을 대상으로, 메모리를 정교화해 **실시간 추천**과 **개인 맞춤 구매 유도 메시지**를 제공하기 위한 리서치 결과물이다.

---

## 30초 요약

| # | 핵심 결론 |
|---|----------|
| 1 | **읽기(실시간)와 쓰기(비동기)를 완전히 분리한다.** LLM을 쓰는 extraction·consolidation·routing은 전부 비동기로. 실시간 경로의 LLM 호출은 응답 생성 1회만 |
| 2 | **Retention을 메모리 유형별로 분리한다.** 약정·호환 조건은 pinned, 세션 의도는 half-life 수십 분, 취향은 90~180일 |
| 3 | **constraint는 랭킹 가중치가 아니라 하드 필터다.** 커머스 메모리 설계에서 가장 흔한 실패 지점 |
| 4 | **Dual-Store에서 시작한다.** Redis(세션) + PostgreSQL/pgvector(프로필)로 개인화의 대부분을 커버. Full Cognitive는 오버엔지니어링 위험이 가장 큰 패턴 |
| 5 | **대화만이 메모리 입력이 아니다.** 조회·장바구니·구매·반품이 커머스에서는 대화보다 강한 신호 |
| 6 | **평가 하네스를 먼저 만든다.** baseline 없이는 이후 모든 최적화가 추측이 된다 |

---

## 다이어그램

| 파일 | 내용 |
|------|------|
| [images/01-memory-taxonomy.svg](https://github.com/hellices/devguidesample/blob/main/docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/images/01-memory-taxonomy.svg) | 6패밀리 30기법 전체 지도 |
| [images/02-architecture-patterns.svg](https://github.com/hellices/devguidesample/blob/main/docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/images/02-architecture-patterns.svg) | 5가지 아키텍처 패턴 비교 |
| [images/03-memory-pipeline.svg](https://github.com/hellices/devguidesample/blob/main/docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/images/03-memory-pipeline.svg) | 쓰기 경로 / 읽기 경로 분리 |
| [images/04-production-tiers.svg](https://github.com/hellices/devguidesample/blob/main/docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/images/04-production-tiers.svg) | 프로덕션 계층 저장 + 가드레일 |
| [images/05-commerce-blueprint.svg](https://github.com/hellices/devguidesample/blob/main/docs/services/microsoft-foundry/agent-memory/samples/research-artifacts/images/05-commerce-blueprint.svg) | B2C 커머스 메모리 블루프린트 |

---

## 목적별 빠른 경로

**시간이 없다면** → [06. 커머스 적용 설계](commerce/index.md) 만 읽는다. 나머지 문서의 결론이 여기 수렴한다.

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

상세는 [06. 커머스 적용 설계 §10](commerce/index.md) 참조.

---

## 참고 자료

### 1차 자료 — 이 리서치가 직접 기반한 문서

| # | 자료 | 내용 |
|---|------|------|
| 1 | **[Microsoft — ai-agents-for-beginners / 13-agent-memory](https://github.com/microsoft/ai-agents-for-beginners/tree/main/13-agent-memory)** | 메모리 유형 정의, Structured RAG, self-improving 패턴 |
| 2 | [NirDiamant — Agent Memory Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) | 30기법 / 6패밀리, [아키텍처 패턴](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/docs/architecture.md) · [비교 매트릭스](https://github.com/NirDiamant/Agent_Memory_Techniques/blob/main/docs/comparison.md) |

### 근거 문헌 — 본문 개념·수치의 원 출처

| # | 논문 | 본문에서 근거로 쓰인 부분 |
|---|------|------------------------|
| 3 | [MemGPT: Towards LLMs as Operating Systems (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560) | Tiered / Full Cognitive 패턴, core·recall·archival 3계층 |
| 4 | [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413) | extraction → update 2단계 파이프라인, 비동기 처리의 지연·비용 효과 |
| 5 | [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956) | Graph-Augmented 패턴, Graphiti 시간 인식 그래프 |
| 6 | [MemoryBank: Enhancing LLMs with Long-Term Memory (arXiv:2305.10250)](https://arxiv.org/abs/2305.10250) | Ebbinghaus 망각 곡선 기반 decay와 접근 시 reinforcement |
| 7 | [Generative Agents: Interactive Simulacra of Human Behavior (arXiv:2304.03442)](https://arxiv.org/abs/2304.03442) | memory stream, reflection, 최신성·중요도·관련도 3축 스코어링 |
| 8 | [GraphRAG (arXiv:2404.16130)](https://arxiv.org/abs/2404.16130) | 엔티티 그래프 인덱스 + 커뮤니티 요약 |
| 9 | [HyDE (arXiv:2212.10496)](https://arxiv.org/abs/2212.10496) | 가상 답변 생성 기반 쿼리 변환과 그 위험 |
| 10 | [LoCoMo (arXiv:2402.17753)](https://arxiv.org/abs/2402.17753) · [LongMemEval (arXiv:2410.10813)](https://arxiv.org/abs/2410.10813) | 표준 벤치마크의 구성과 한계 |
| 11 | [A Survey on the Memory Mechanism of LLM based Agents (arXiv:2404.13501)](https://arxiv.org/abs/2404.13501) | 학술적 분류 체계 · [정리 저장소](https://github.com/nuster1128/LLM_Agent_Memory_Survey) |
| 12 | [GDPR Article 17 — Right to erasure](https://gdpr-info.eu/art-17-gdpr/) | 전 계층 삭제 요구사항 |

> **자료 활용 원칙.** 문서 본문의 서술은 1차 자료 2건을 기준으로 구성했고, 그 안에서 언급되거나 개념의 출처가 되는 논문을 확인해 근거 문헌으로 분리했다. 표의 모든 링크는 실제 접속해 제목·저자·연도를 확인했다. 다만 RRF(SIGIR 2009)와 MMR(SIGIR 1998)은 ACM DL 유료 문헌이라 [03. 파이프라인과 검색](pipeline-retrieval/index.md)에 서지 정보만 표기했다.

문서별 상세 참고 자료는 각 문서 하단에 있다.
