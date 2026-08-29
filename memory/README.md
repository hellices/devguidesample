# Agent Memory 가이드 모음

Azure 위에서 에이전트 메모리를 설계·운영하기 위한 리서치와 가이드다.

## 구성

| 항목 | 내용 |
|------|------|
| **[agent-memory/](agent-memory/)** | **Agent Memory 종합 리서치 (v2)** — 아래 요약 참조 |
| [foundry-gpt-memory-v1.md](foundry-gpt-memory-v1.md) | 1차 버전. Azure Foundry GPT-5.x 3계층 메모리 (Prompt Cache → Redis Session → Foundry Memory Service) |

---

## agent-memory/ 요약

### 1. 배경 및 목적

- 대부분의 대화형 에이전트는 **stateless** 구조로, 세션 종료 시 맥락이 소멸한다
- 재방문 고객에게도 동일한 정보를 반복 확인하게 되어 개인화·학습·장기 일관성이 성립하지 않는다
- 본 리서치는 에이전트를 운영 중이나 **메모리 계층이 아직 구성되지 않은 조직**이, 준비 단계에서 다음 세 가지를 판단할 수 있도록 정리한 것이다
  1. 메모리에는 어떤 종류가 있는가
  2. 각각을 어디에 저장할 수 있는가
  3. 우리 규모에서는 어디서부터 시작해야 하는가

---

### 2. 산출물 구성

| 문서 | 다루는 범위 |
|------|------------|
| [01. 메모리 분류 체계](agent-memory/01-memory-taxonomy.md) | Agent Memory 8유형 정의, 유형별 저장소 선택지 및 Azure 매핑, Retention 정책 |
| [02. 아키텍처 패턴](agent-memory/02-architecture-patterns.md) | Single-Store / Dual-Store / Tiered / Graph-Augmented / Full Cognitive 5패턴과 선택 기준 |
| [03. 파이프라인과 검색](agent-memory/03-pipeline-and-retrieval.md) | 쓰기(비동기)·읽기(실시간) 경로 분리, 하이브리드 검색 단계별 비용 |
| [04. 프레임워크 비교](agent-memory/04-frameworks.md) | Mem0 · Zep · Graphiti · Letta · Cognee · Azure AI Search, 자체 구현 대비 도입 판단 |
| [05. 프로덕션과 평가](agent-memory/05-production-evaluation.md) | 계층 저장, PII·GDPR, 관측성·비용, 평가 지표 및 표준 벤치마크 |
| [06. 커머스 적용 설계](agent-memory/06-commerce-application.md) | **핵심 산출물** — 메모리 스키마, 지연 예산, 안티패턴, Phase 0~4 로드맵 |

---

### 3. 메모리에는 어떤 종류가 있는가

#### 3.1 Agent Memory 8유형

"장기 메모리를 도입한다"는 말은 설계 단계에서 성립하지 않는다. 아래 중 무엇인지 특정해야 저장소와 수명이 정해진다.

| 유형 | 무엇을 기억하나 | 범위 | 수명 |
|------|---------------|------|------|
| **Working** | 단일 요청을 처리하는 동안의 스크래치패드 | 요청 1건 | 요청 종료 시 소멸 |
| **Short-term** | 진행 중인 세션의 대화 맥락 | 세션 1건 | 세션 TTL |
| **Semantic** | 시점을 벗어난 **일반화된 사실** | 유저 | 고정 또는 장기 |
| **Episodic** | 시점·맥락을 포함한 **완결된 사건 기록** | 유저 × 시점 | 중기 |
| **Procedural** | 반복 워크플로, 툴 사용 절차 | 에이전트 | 버전 관리 |
| **Entity / Graph** | 엔티티와 **엔티티 간 관계** | 전역 + 유저 | 소멸 없음 |
| **Persona** | 에이전트 자신의 역할·톤 | 에이전트 | 버전 관리 |
| **Structured RAG** | 스키마가 있는 도메인 데이터의 정밀 검색 | 도메인 데이터 | 원본 수명에 종속 |

**혼동하기 쉬운 두 쌍**

- **Working vs Short-term** — Working은 요청 1건 안에서만 살고, Short-term은 세션 전체를 산다. 둘을 같게 다루면 토큰 예산 관리가 무너진다
- **Semantic vs Episodic** — *"화요일에 알려줬다"* 는 사건(Episodic), *"생일은 3월 15일"* 은 증류된 사실(Semantic)이다. **Episodic으로 포착하고 Semantic으로 증류하는** 조합이 프로덕션의 기본형이다

#### 3.2 실무에서 가장 많이 쓰는 구분 — Semantic Memory의 하위 분류

개인화 품질은 대부분 이 네 가지를 구분했는지에서 갈린다.

| 구분 | 판단 기준 | 보존 정책 | 예시 |
|------|----------|----------|------|
| **constraint** | 미충족 시 **구매·사용 자체가 불가** | Pinned (소멸 없음) | 통신사·자급제 구분, eSIM 지원 여부 / 업무 정책상 요구되는 노트북 OS 사양 / 보험 가입 가능 기간 및 대상 모델 / 기존 기기와의 모니터 포트·VESA 규격 / 가전 설치 공간 치수, 문 열림 방향 |
| **preference** | 만족도에 영향, 구매 불가 사유는 아님 | Long half-life (90~180일) | 폴더블 선호, 고용량 스토리지 선택 성향 / 노트북 휴대성 우선 / 모니터 고주사율 선호 / 비스포크 색상 패널 취향 |
| **intent** | 이번 구매 건에 한정, 시간 경과 시 무효 | Short half-life (30분~수시간) | 현재 탐색 중인 카테고리, 이번 건의 가격대, 약정 만료에 따른 기기 변경 검토 |
| **context** | 여러 카테고리에 공통 적용되는 배경 | Very long half-life (180일+) | 기존 보유 갤럭시 기기 및 생태계 자산, 사용 목적(업무용·학습용), 가구원 수·주거 형태 |

> **constraint는 랭킹 가중치가 아니라 하드 필터로 처리한다.** 가중치로 두면 타 속성 점수가 높을 때 가입 불가 상품이나 호환되지 않는 제품이 상위에 노출된다.

---

### 4. 어떻게 구성할 수 있는가

#### 4.1 유형별 저장소와 Azure 매핑

접근 패턴이 다르므로 유형마다 적합한 저장소가 다르다.

| 유형 | 1순위 저장소 | Azure 매핑 |
|------|-------------|-----------|
| Working | 프로세스 인메모리 | (앱 프로세스 내부 — 외부 저장 불필요) |
| Short-term | Redis (TTL) | Azure Managed Redis |
| Semantic | PostgreSQL + pgvector | Azure Database for PostgreSQL |
| Episodic | 벡터 인덱스 + 시간 필터 | Azure AI Search, Cosmos DB |
| Procedural | JSON / YAML (Git 관리) | Blob Storage, Azure App Configuration |
| Entity / Graph | 그래프 DB | Cosmos DB for Apache Gremlin |
| Persona | 설정 파일 / 프롬프트 템플릿 | Azure App Configuration |
| Structured RAG | 검색 엔진 | Azure AI Search |
| *(Cold Archive)* | 오브젝트 스토리지 | Azure Blob Storage (Cool / Archive) |

#### 4.2 최소 구성부터 시작한다

```
[ 최소 구성 ]  저장소 2개로 개인화의 대부분을 커버한다
  Azure Managed Redis                → Short-term (세션 버퍼, TTL)
  Azure DB for PostgreSQL (pgvector) → Semantic (프로필) + Episodic (이벤트 테이블)

[ 확장 구성 ]  필요가 실제로 발생한 뒤에 추가한다
  + Azure AI Search   → Structured RAG (상품·주문 정밀 질의)
  + 그래프 DB          → Entity / Graph (관계 기반 추천)
  + Blob Storage      → Cold Archive (감사·규제 보존)
```

#### 4.3 아키텍처 패턴 5종

저장소를 어떻게 조합하느냐가 검색 품질과 확장성을 결정한다.

| 패턴 | 저장소 구성 | 적합한 상황 |
|------|-----------|-----------|
| **Single-Store** | 벡터 DB 1개 | 프로토타입·데모. 커지면 검색 품질이 급락 |
| **Dual-Store** | 세션 버퍼 + 장기 저장소 | **대부분의 실서비스 출발점** |
| **Tiered** | HOT / WARM / COLD | 이력이 방대하고 지연 요구가 엄격할 때 |
| **Graph-Augmented** | 벡터 + 지식 그래프 | 엔티티 관계 기반 추천이 필요할 때 |
| **Full Cognitive** | 유형별 전용 저장소 + 라우터 | 대규모 어시스턴트. 오버엔지니어링 위험 최대 |

> 패턴은 자연스럽게 중첩된다. **Dual-Store로 시작해 진화시키는 것**이 권장 경로이며, Full Cognitive를 처음부터 짓지 않는다.

#### 4.4 보존 정책은 유형별로 분리한다

같은 저장소에 넣더라도 보존 정책은 반드시 나눈다. 하나로 통일하는 것이 가장 흔한 설계 실패다.

| 유형 | 방식 | 값 |
|------|------|-----|
| Working | Request-scoped | — |
| Short-term | TTL | 30분 ~ 24시간 (세션 정의에 따름) |
| Semantic — constraint | Pinned (decay 면제) | — |
| Semantic — context | Very long half-life | 180일+ |
| Semantic — preference | Long half-life | 90~180일 |
| Semantic — intent | Short half-life | 30분 ~ 수시간 |
| Episodic | Medium half-life + 접근 시 강화 | 14~60일 |
| Entity / Graph · Procedural · Persona | 소멸 없음 | 버전 관리 |
| Cold Archive | 규제 기준 보존 기간 | 3~5년 |

---

### 5. 도입 방안

#### 5.1 단계별 로드맵

| Phase | 주요 과제 | 기대 효과 |
|-------|----------|----------|
| 0 | 평가 하네스, baseline 측정, PII·동의 게이트 | 개선 효과의 측정 가능성 확보 |
| 1 | Dual-Store 구성, 비동기 추출, constraint 하드 필터 | 반복 질의 없는 응대 |
| 2 | 시간 인식 메모리, 통합·정리 배치 | 현재 의도와 장기 취향의 분리 |
| 3 | 계층 저장, Structured RAG, 제품 관계 그래프 | 규모 확장 시 지연·비용 통제 |
| 4 | 라우팅, 아카이브, 샤딩 | 선택적 고도화 |

> **Phase 0을 선행하지 않을 경우, 이후의 모든 개선 활동에 대한 효과 검증이 불가능하다.**

#### 5.2 자체 구현과 외부 도입의 경계

- **정책과 스키마는 직접 소유한다** — 메모리 유형 정의, 추출 규칙, 보존 정책, 저장소 라우팅
- **인프라 컴포넌트는 가져온다** — 벡터 검색, 그래프 백엔드, 리랭커, 평가 하네스, 관측성
- 관리형 메모리 서비스(Mem0 · Zep 등)의 도입 판단 기준은 [04. 프레임워크 비교](agent-memory/04-frameworks.md)에 정리되어 있다

---

### 6. 구성 시 유의사항

| 항목 | 내용 |
|------|------|
| **읽기·쓰기 경로 분리** | 사실 추출·중복 해소·라우팅은 응답 반환 후 비동기로. 실시간 경로에 두면 사용자 대기 시간이 늘어난다 |
| **행동 데이터도 입력이다** | 커머스에서는 조회·비교·구매·반품 이력이 대화만큼 중요하다. 처음부터 동일 스키마로 수집한다 |
| **틀린 기억의 비용** | 오기억 1회가 신뢰를 크게 깎는다. confidence를 함께 저장하고 낮으면 확인 절차를 둔다 |

---

### 7. 그 외 문서에서 다루는 사항

- 하이브리드 검색 파이프라인과 단계별 지연 비용
- 개인화 강도의 단계 정의 및 과잉 개인화 방지 기준
- 추천 신뢰도 지표(거절률·옵트아웃률)를 포함한 기술·비즈니스 지표 체계
- 커머스 메모리 설계에서 반복 관찰되는 안티패턴
- GDPR 삭제권 대응을 위한 전 계층 삭제 체크리스트

> 개념 이해는 [01. 메모리 분류 체계](agent-memory/01-memory-taxonomy.md)와 [02. 아키텍처 패턴](agent-memory/02-architecture-patterns.md)을, 실제 적용 설계는 [06. 커머스 적용 설계](agent-memory/06-commerce-application.md)를 참조할 것.
