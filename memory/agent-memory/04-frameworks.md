# 04. 프레임워크 · 플랫폼 비교 — 만들 것인가 가져올 것인가

자체 에이전트 프레임워크를 이미 운영 중인 팀에게 이 문서의 질문은 하나다. **"메모리 레이어까지 직접 만들 것인가, 특정 부분만 가져올 것인가."**

---

## 한눈에 보기

| # | 프레임워크 | 저장소 | 검색 방식 | 토큰 비용 | 최적 용도 |
|---|-----------|--------|----------|----------|----------|
| 24 | **Graphiti** | Neo4j | 그래프 + 시간 | 아주 작음 | 프로덕션 시간 지식 그래프 |
| 25 | **Mem0** | Mem0 클라우드 (또는 self-host) | 관리형 검색 | API 과금 | 드롭인 개인화 |
| 26 | **Letta / MemGPT** | Letta 서버 | 3계층 (core/recall/archival) | 상한 있음 | 장기 실행 자기수정 에이전트 |
| 27 | **Zep** | Zep 클라우드 / OSS | 시간 지식 그래프 | API 과금 | 대규모 대화 메모리 |
| — | **Cognee** | 벡터 + 그래프 듀얼 스토어 | 하이브리드 (벡터+그래프+LLM 추론) | 자체 호스팅 | 구조화 시맨틱 메모리 |
| — | **Azure AI Search** | Azure 관리형 | Structured RAG + 하이브리드 | Azure 과금 | 정밀 구조화 검색 백엔드 |

---

## Mem0 (기법 25)

**정체**: 대화에서 사실을 자동 추출해 **user_id 스코프**로 저장·검색하는 관리형 메모리 레이어.

**핵심 API 3개**
```python
memory.add(messages, user_id="...")   # 추출 + 저장
memory.search(query, user_id="...")   # 시맨틱 검색
memory.get_all(user_id="...")         # 유저 전체 프로필 조회
```

**동작 방식**
1. 클라이언트 초기화 (LLM / 임베딩 모델 / 벡터 스토어 — 기본 Qdrant 지정)
2. 매 턴 후 `memory.add()` 호출
3. Mem0의 LLM 파이프라인이 **사실 추출 → 기존 기억과 모순 탐지 → 중복 제거** 후 저장
4. 응답 생성 전 `memory.search()`로 관련 기억 검색
5. 검색 결과를 시스템 프롬프트에 포함해 개인화 응답 생성
6. 모든 기억이 `user_id` 스코프 → **유저 간 교차 오염 없음**

**Self-improving memory**: 새 정보나 모순이 들어오면 스스로 갱신·병합·중복제거하며 정제된다.

| 강점 | 약점 |
|------|------|
| 커스텀 추출 파이프라인·벡터DB 관리 없이 즉시 동작 | **무엇을 "기억할 만한가"에 대한 통제권이 제한적** — 중요 사실을 놓치거나 무관한 것을 저장 |
| 멀티유저 개인화가 기본 내장 | `add()` 호출마다 LLM 호출 → **분당 1,000 메시지 초과 시 비용 급증** |
| 모순 해소 내장 (이사하면 기존 도시 기억이 갱신됨) | **TTL·decay가 내장되어 있지 않다.** 수동 삭제 전까지 영구 보존 |
| LangChain/LlamaIndex/CrewAI 공식 어댑터 | 구조화 필터("category=dietary AND created after January")가 제한적 |
| | 클라우드는 호출당 50~200ms 네트워크 지연 |
| | 절차적 지식·복잡한 다단계 경험 표현에는 약함 |

---

## Zep (기법 27)

**정체**: 대화 분류·엔티티 추출·**시간 인식 그래프**를 제공하는 프로덕션 지향 관리형 메모리.

**차별점**
- 시간 스코어링을 검색 파이프라인에 **네이티브 적용**
- 하이브리드 검색을 내부적으로 수행
- 시간 기반 decay·중요도 스코어링을 관리형 서비스로 제공
- 백그라운드 통합(consolidation)을 지식 그래프 위에서 실행
- 멀티유저 격리·비동기 처리·캐싱이 내장 → 기법 30(프로덕션 패턴)의 상당 부분을 대신해 준다

**적합**: 대규모 대화 메모리를 직접 운영하고 싶지 않을 때. 프로덕션 패턴 구현 작업을 통째로 건너뛰는 선택지다.

---

## Graphiti (기법 24)

**정체**: Zep이 만든 OSS. 채팅에서 **시간 인식 지식 그래프**를 구축하고 에피소드와 일반 사실을 추출한다. 백엔드는 Neo4j.

**특징**
- 모든 그래프 엣지에 타임스탬프 → 지식 그래프 위에서 시간 질의 가능
- 에피소드 → 시맨틱 추출 파이프라인
- 관계 기반 멀티홉 추론

**커머스 적합성**: 상품–브랜드–카테고리–대체재 관계가 본질적으로 그래프이므로 잠재력이 크다. 다만 Neo4j 운영 부담과 엔티티 추출 정확도 리스크를 감수해야 한다.

---

## Letta / MemGPT (기법 26)

**정체**: **자기수정(self-editing) 메모리**. 에이전트가 자신의 메모리를 함수 호출로 직접 편집한다.

**3계층 구조**
| 계층 | 역할 |
|------|------|
| **Core memory** | 항상 컨텍스트에 포함되는 고정 블록 (페르소나, 유저 핵심 사실) |
| **Recall memory** | 대화 이력 검색 |
| **Archival memory** | 대용량 장기 저장 |

**개념**: inner monologue, heartbeat 이벤트, **memory pressure** 처리. 컨텍스트가 가득 차면 에이전트가 스스로 오래된 것을 archival로 내리고 필요할 때 다시 꺼낸다. 상태 전체(core/recall/archival)를 세션 간 직렬화한다.

**자체 프레임워크 운영 팀에 대한 판단**: Letta 서버를 통째로 도입하는 것은 아키텍처 강제가 크다. **개념(3계층, memory pressure 기반 자동 승강, 자기수정)만 차용**하는 편이 현실적이다.

---

## Cognee

**정체**: 오픈소스 **시맨틱 메모리**. 구조화·비구조화 데이터를 **임베딩으로 뒷받침되는 질의 가능한 지식 그래프**로 변환한다.

**듀얼 스토어 아키텍처**: 벡터 유사도 검색 + 그래프 관계를 결합해, 에이전트가 *"무엇이 비슷한가"* 뿐 아니라 *"개념들이 어떻게 연결되는가"* 를 이해하게 한다.

**하이브리드 검색**: 벡터 유사도 + 그래프 구조 + LLM 추론을 혼합 — 원시 청크 조회부터 그래프 인식 QA까지.

**Living memory**: 진화·성장하면서도 **하나의 연결된 그래프로 질의 가능한 상태**를 유지. 단기 세션 컨텍스트와 장기 영속 메모리를 모두 지원.

같은 저장소의 [Cognee 노트북](https://github.com/microsoft/ai-agents-for-beginners/blob/main/13-agent-memory/13-agent-memory-cognee.ipynb)은 다양한 데이터 소스 수집 · 지식 그래프 시각화 · 니즈별 검색 전략 질의를 다룬다.

---

## Azure AI Search — Structured RAG 백엔드

Mem0 같은 전용 메모리 도구 대신, **검색 서비스를 메모리 백엔드로** 쓰는 접근이다.

**핵심 주장**: Azure AI Search는 **Structured RAG**를 지원하며, 대화 이력·이메일·이미지 같은 대규모 데이터셋에서 **밀도 높은 구조화 정보를 추출·검색**하는 데 탁월하다. 전통적인 텍스트 청킹·임베딩 방식 대비 *"superhuman precision and recall"* 을 제공한다고 기술한다.

**용도**
- 유저별 메모리, 상품 카탈로그, 도메인 지식 저장
- 자체 데이터로 응답을 그라운딩

**커머스 관점**: 상품 속성·주문 이력처럼 **스키마가 명확한 데이터**는 순수 벡터 검색보다 Structured RAG가 압도적으로 유리하다. `"화요일에 파리행 무슨 항공편 예약했지?"` 같은 정밀 질의가 가능해진다.

관련 노트북: [13-agent-memory.ipynb](https://github.com/microsoft/ai-agents-for-beginners/blob/main/13-agent-memory/13-agent-memory.ipynb) — Mem0 + Azure AI Search + Microsoft Agent Framework 조합.

---

## Microsoft Agent Framework의 위치

프레임워크 내장 메모리의 범위는 다음과 같이 규정된다.

- **Short-term memory = `AgentSession`** (`agent.create_session()`으로 생성). 프레임워크의 내장 단기 메모리로, **동일 세션이 재사용되는 동안만** 대화 컨텍스트를 유지한다.
- **세션이 끝나거나 애플리케이션이 재시작되면 컨텍스트는 영속되지 않는다.**
- 세션을 넘어 살아남아야 하는 사실·선호는 **장기 메모리**로 — 보통 데이터베이스, 벡터 인덱스, 또는 다른 영속 저장소를 통해 처리한다.
- 여러 에이전트가 공유하는 작업 공간이 필요하면 **Whiteboard memory**를 별도 도구로 제공한다.

> 자체 프레임워크를 쓰는 팀에게 이 구분이 그대로 적용된다. **세션 객체는 단기 메모리일 뿐이며, 장기 메모리는 별도 저장소로 반드시 분리해야 한다.**

---

## 자체 구현 vs 도입 — 판단 기준

### 도입이 유리한 경우

| 조건 | 추천 |
|------|------|
| 빠르게 개인화를 붙이고 싶고 추출 로직을 직접 관리할 이유가 없다 | **Mem0** |
| 프로덕션 운영(캐싱·격리·비동기·decay)을 직접 만들기 싫다 | **Zep** |
| 관계 기반 추천이 핵심이고 그래프 운영이 가능하다 | **Graphiti** |
| 구조화된 정밀 검색이 필요하고 Azure를 이미 쓴다 | **Azure AI Search (Structured RAG)** |

### 자체 구현이 유리한 경우

| 조건 | 이유 |
|------|------|
| **무엇을 저장할지에 대한 도메인 규칙이 강하다** | 커머스 제약(약정·호환 규격·가입 조건)은 놓치면 안 되는 사실이다. Mem0의 자동 추출은 "중요 사실을 놓칠 수 있다"고 명시된 한계가 있다 |
| **TTL·decay 정책이 비즈니스 로직이다** | Mem0에는 TTL·decay가 내장되어 있지 않다. 세션 의도와 고정 프로필의 half-life를 다르게 가져가야 하는 커머스에는 치명적 |
| **호출량이 매우 크다** | `add()`마다 LLM 호출 — 분당 1,000 메시지 초과 시 비용 급증. 자체 구현하면 "저장 가치 1차 게이트"를 저비용 모델로 앞단에 둘 수 있다 |
| **개인정보 처리 위치를 통제해야 한다** | 클라우드 SaaS에 유저 발화를 넘기는 것이 규제상 부담일 수 있다 |
| **행동 이벤트(클릭·장바구니)도 메모리 입력이다** | 대화 중심 SaaS는 이 경로를 1급 시민으로 다루지 않는다 |
| **벤더 락인을 피하고 싶다** | Mem0/Zep 모두 락인이 명시적 트레이드오프로 기술된다 |

### 현실적 하이브리드 (권장)

```
자체 구현             ┃ 외부 도입 후보
──────────────────────╂────────────────────────────
메모리 스키마 정의     ┃
추출 규칙 · 게이트     ┃
TTL / Decay 정책        ┃
저장소 라우팅          ┃
────────────────────  ┃
벡터 검색 백엔드       ┃ ← Azure AI Search / Qdrant / pgvector
그래프 백엔드          ┃ ← Neo4j / Graphiti (Phase 3)
리랭커                 ┃ ← sentence-transformers cross-encoder
평가 하네스            ┃ ← RAGAS / DeepEval
관측성                 ┃ ← OpenTelemetry
```

**정책과 스키마는 직접 소유하고, 인프라 컴포넌트만 가져온다.** 이것이 자체 프레임워크를 운영하는 팀의 합리적 경계선이다.

---

## 라이브러리 참고 (구현 단축용)

| 필요 | 도구 |
|------|------|
| BM25 + 벡터 융합 | LangChain `EnsembleRetriever`, LlamaIndex `QueryFusionRetriever` |
| Cross-encoder 리랭크 | LangChain `CrossEncoderReranker`, sentence-transformers |
| BM25 단독 | `rank-bm25` |
| 벡터 검색 | **Azure AI Search**, pgvector, Qdrant, Chroma, FAISS |
| 캐싱 | **Azure Managed Redis**, Azure Cache for Redis |
| 영속화 | Azure Database for PostgreSQL, Azure SQL, Cosmos DB |
| 그래프 | Neo4j, **Cosmos DB for Apache Gremlin** |
| 아카이브 | Azure Blob Storage (Cool / Archive tier) |
| 관측성 | OpenTelemetry → **Azure Monitor / Application Insights**, LangSmith |
| 평가 | RAGAS, DeepEval |

> 참고 규모감: 하이브리드 검색 풀 파이프라인은 위 라이브러리로 **50~100줄**, 라우팅 로직은 **50~150줄**, decay + pruning은 **30~50줄** 수준으로 조립 가능하다.

---

## 다음 문서

- [05. 프로덕션과 평가](05-production-evaluation.md)
- [06. 커머스 적용 설계](06-commerce-application.md)

---

## 참고 자료

1. [Microsoft — 13-agent-memory](https://github.com/microsoft/ai-agents-for-beginners/tree/main/13-agent-memory) — Mem0 / Cognee / Azure AI Search / Agent Framework 세션 모델
   · [Mem0 + Azure AI Search 노트북](https://github.com/microsoft/ai-agents-for-beginners/blob/main/13-agent-memory/13-agent-memory.ipynb) · [Cognee 노트북](https://github.com/microsoft/ai-agents-for-beginners/blob/main/13-agent-memory/13-agent-memory-cognee.ipynb)
2. [Agent Memory Techniques](https://github.com/NirDiamant/Agent_Memory_Techniques) — 기법 24(Graphiti) · 25(Mem0) · 26(Letta) · 27(Zep)
3. [Mem0](https://github.com/mem0ai/mem0) · [Letta docs](https://docs.letta.com) · [Zep](https://github.com/getzep/zep)
4. [MemGPT 논문 (arXiv:2310.08560)](https://arxiv.org/abs/2310.08560)
