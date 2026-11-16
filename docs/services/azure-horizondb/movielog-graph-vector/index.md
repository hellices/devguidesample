---
title: "Azure HorizonDB 벡터 검색과 그래프: DiskANN·age 확장과 MovieLog 적용"
description: Azure HorizonDB(미리 보기)가 PostgreSQL 확장으로 제공하는 벡터 검색(vector·pg_diskann)과 그래프(age), DB 안 AI 함수, 활용 패턴과 VS Code 확장을 소개하고, 영화 리뷰 앱 MovieLog에 적용한 DiskANN 검색·관계 그래프·Azure OpenAI와 bge-m3-ko 임베딩 병행 구성·BYOM 시험을 실측값과 함께 정리합니다.
document_type: guide
services: [azure-horizondb, azure-openai, azure-kubernetes-service, azure-api-management]
technologies: [postgresql, kubernetes]
tags: [design, evaluate]
status: current
verification_status: needs-review
sources_checked_at: 2026-11-16
official_sources:
  - title: What is Azure HorizonDB (Preview)?
    url: https://learn.microsoft.com/azure/horizondb/overview
  - title: List of extensions and modules by name in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/extensions/concepts-extensions-versions
  - title: Implement vector search with the pgvector extension in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-search-pgvector
  - title: Choose the right vector index for your workload in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-selection-guide
  - title: Scalable vector index with DiskANN in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-diskann
  - title: Graph database capabilities with Apache AGE extension for Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/graph/age-overview
  - title: AI functions in the azure_ai extension in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/ai-functions
  - title: AI Model Management in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/ai-model-management
  - title: Implement AI pipelines in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/ai-pipelines
  - title: Graph-augmented RAG patterns in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/graph-rag
  - title: What is the PostgreSQL extension for Visual Studio Code? (Preview)
    url: https://learn.microsoft.com/azure/horizondb/development/vs-code-extension/vs-code-overview
  - title: Create a fully managed GPU node pool on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/aks-managed-gpu-nodes
  - title: Apache AGE
    url: https://github.com/apache/age
last_verified: 2026-11-16
review_cycle_days: 30
applies_to: [Azure HorizonDB 미리 보기, PostgreSQL 17, vector 0.8.7, pg_diskann 0.7.6, age 1.8.0, azure_ai 2.5.6]
---

# Azure HorizonDB 벡터 검색과 그래프: DiskANN·age 확장과 MovieLog 적용

## 핵심 흐름: 같은 데이터베이스의 벡터 검색과 그래프 → MovieLog 의미 검색 { #message }

Azure HorizonDB는 PostgreSQL 확장으로 벡터 검색(`vector`·`pg_diskann`)과 그래프(`age`)를 함께 제공합니다. 그래서
관계형 데이터 옆에 임베딩 열과 관계 그래프를 두고, "자연어로 찾고 관계로 넓혀 보는" 검색을 SQL과 openCypher만으로
만들 수 있습니다.

1. **벡터 검색** — 임베딩을 `vector` 열에 두고 DiskANN index로 질의와 가까운 행을 찾습니다.
2. **그래프** — 같은 데이터베이스에 `age` 그래프를 두고 openCypher로 관계를 탐색합니다.
3. **결합** — 벡터 검색 결과를 시작점으로 그래프 이웃을 조회하거나, 최근접 결과를 그래프 관계로 저장합니다.
   별도 검색 엔진이나 그래프 DB 없이 한 데이터베이스 안에서 처리합니다.

영화 리뷰 앱 MovieLog에 Wikidata·Wikipedia 영화 484편을 넣어 이 흐름을 확인했습니다. 아래는 "호빗이나 오크같은게
나오는 영화"의 결과입니다(2026-11-13, Azure OpenAI 모델). 제목에 "호빗"이 없는 영화도
줄거리 의미로 찾고, 피터 잭슨·이언 매켈런 같은 공통 인물과 `SIMILAR_TO` 점선이 결과 사이의 관계를 보여 줍니다.

![MovieLog 의미 검색 화면. 질의 '호빗이나 오크같은게 나오는 영화'에 대해 결과 영화 사이의 관계 그래프가 포스터를 붙인 영화 노드, 주황 원의 인물(피터 잭슨, 이언 매켈런, 케이트 블란쳇, 봉준호 등), SIMILAR_TO 점선으로 그려지고, 그 아래에 영화·감독·출연·장르·비슷한 영화 필터 칩이 있으며 장르는 꺼져 있음. 아래 결과 목록은 호빗: 뜻밖의 여정 0.478, 호빗: 스마우그의 폐허 0.435 순서](images/discover-semantic-search.png)

| 단계 | 평균 시간 | 측정 조건 |
|---|---|---|
| 질의 임베딩 — bge-m3-ko(AKS vLLM, T4 spot) | 22.0 ms | 2026-11-15, 40분, 서버 Timer |
| 질의 임베딩 — Azure OpenAI `text-embedding-3-large` | 109.3 ms | 2026-11-15, 40분, 서버 Timer |
| HorizonDB 벡터 검색(벡터·키워드 RRF 결합) | 10.9–11.5 ms | 2026-11-15, 40분, 두 모델 |
| HorizonDB AGE 그래프 조회 | 4.45 ms | 2026-11-13, 1시간, Grafana 대시보드 |

응답 시간의 대부분은 임베딩 호출이고 DB 단계는 수~십여 밀리초입니다.

이 문서는 앞부분에서 HorizonDB의 벡터·그래프·AI 기능을 Microsoft Learn 기준으로 소개하고, 뒷부분
[MovieLog 적용](#movielog)에서 샘플에 적용한 구성과 실측값을 정리합니다. 배포와 구현 절차는 자식 문서에 있습니다.

| 문서 | 성격 | 내용 |
|---|---|---|
| [HorizonDB 벡터·그래프 기능](vector-graph-features/index.md) | 기능 가이드 | 거리 연산자, index 매개변수, advanced filtering, AGE 저장 구조와 `cypher()` 함수의 세부 동작 |
| [MovieLog 실습](movielog-lab/index.md) | 샘플 실습 | `azd up` 한 번으로 재현하는 배포, 데이터 모델, 그래프 동기화, 앱 구현, 관측 |

## Azure HorizonDB 개요: PostgreSQL 호환 AI-ready 관리형 데이터베이스 { #horizondb }

Azure HorizonDB는 PostgreSQL 위에 만든 cloud native 완전 관리형 데이터베이스이며 2026-11-16 현재
**미리 보기**입니다. compute와 storage를 나누고 WAL만 storage로 쓰는 database-as-a-log 구조이며,
벡터 임베딩과 Microsoft Foundry 연동을 기본으로 제공해 RAG·추천·의미 검색을 데이터베이스 계층에서
구현하는 것을 주요 사용 사례로 듭니다.

| 구분 | 내용 |
|---|---|
| 구조 | 쓰기 primary 1개와 읽기 replica가 같은 storage를 공유합니다. compute replica는 vCore당 메모리 8 GB와 로컬 NVMe cache를 가지며, WAL 전송·checkpoint·백업은 storage 계층이 맡습니다. |
| 접속 | read-write endpoint와 읽기 replica에 분산하는 read-only endpoint |
| 과금 | 프로비저닝한 compute(core hour), 사용한 storage(GB/월), 단기 보존 백업 storage |
| 미리 보기 제약 | 백업 보존 7일 고정, 지역 간 read replica·고객 관리 키·내장 PgBouncer·VNet injection 미지원(private link는 지원) |

### 벡터·그래프·AI 확장: vector · pg_diskann · age · azure_ai { #extensions }

확장은 parameter group의 `azure.extensions`로 허용한 뒤 `CREATE EXTENSION`으로 설치하며, 공유 메모리를 쓰는
`age`는 `shared_preload_libraries`도 필요합니다. 마지막 열은 MovieLog cluster에서 확인한 설치 버전으로, Learn
목록보다 높았습니다.

| 확장 | 용도 | Learn 목록 버전 | MovieLog cluster 버전 |
|---|---|---|---|
| `vector` | pgvector 벡터 타입과 거리 연산자 | 0.8.0 | 0.8.7 |
| `pg_diskann` | DiskANN 근사 최근접 이웃 index | 0.7.1 | 0.7.6 |
| `age` | Apache AGE 그래프, openCypher | 1.6.0 | 1.8.0 |
| `azure_ai` | Foundry 모델을 부르는 AI 함수와 AI pipeline | 2.2.1 | 2.5.6 |

## 벡터 검색: `vector` 열 · 거리 연산자 · index 선택 { #vector }

벡터는 `vector(n)` 타입의 일반 열이고, 검색은 질의 벡터와의 거리(`<=>` 코사인 거리, `<->` L2 거리, `<#>` 음의 내적)로
오름차순 정렬하는 SQL 한 문장입니다. `<#>`는 index 탐색을 위해 내적의 부호를 뒤집은 값이므로, 내적 점수가
필요하면 `-(embedding <#> :query_vector)`로 바꿔 표시합니다. 일반 열이므로 관계형 테이블과 join하거나 `WHERE`
조건과 함께 쓸 수 있고, 임베딩 모델마다 열과 index를 따로 둘 수 있습니다.

```sql
ALTER TABLE documents ADD COLUMN embedding vector(1024);
CREATE INDEX ON documents USING diskann (embedding vector_cosine_ops);

SELECT id, title, 1 - (embedding <=> :query_vector) AS score
FROM documents
ORDER BY embedding <=> :query_vector
LIMIT 10;
```

### 벡터 index 선택지: Flat · IVFFlat · HNSW · DiskANN { #index-options }

HorizonDB에서 고를 수 있는 벡터 검색 방식은 네 가지이며, 질의 SQL은 같고 index만 바뀝니다.

| 방식 | 구조 | 최대 차원 | 메모리 | 데이터 변경 | 필터 결합 |
|---|---|---|---|---|---|
| Flat(index 없음) | 전체 비교, recall 100% | 16,000 | 없음 | 비용 없음 | 항상 정확 |
| IVFFlat | list 분할 탐색 | 2,000 | 작음 | recall 저하, 주기적 재생성 | 후필터 |
| HNSW | 다층 그래프 | 2,000 | 큼(RAM에 올라가야 함) | 제자리 반영 | 후필터 |
| DiskANN(`pg_diskann`) | SSD 최적화 그래프 | 16,000(`sq_bits=1`), 4,000(`sq_bits=4`) | 작음(대부분 SSD) | 제자리 반영 | index 안에서 필터(advanced filtering) |

Learn은 10만 행 미만이고 지연이 중요하지 않으면 flat scan을 먼저 권하고, 2,000차원 초과·높은 recall의
필터 결합·RAM보다 크거나 계속 늘어나는 데이터에는 DiskANN, 정적이고 RAM에 들어가는 데이터에는 HNSW,
빠른 build를 위해 recall을 양보할 때는 IVFFlat을 권합니다. 매개변수와 실행 계획은
[벡터 index 선택](vector-graph-features/index.md#vector-index)에 있습니다.

### DiskANN 특징: 기본 권장 · SSD 기반 · 필터 결합 · 차원 여유 { #why-diskann }

- **기본 권장** — Learn은 HorizonDB의 production AI 워크로드 기본값으로 DiskANN을 듭니다.
- **SSD 기반 확장** — HNSW와 달리 index 전체가 메모리에 올라갈 필요가 없어, 데이터가 늘어도 compute를
  키우지 않고 버틸 수 있습니다.
- **필터 결합** — 메타데이터 조건을 붙인 검색을 index 탐색 안에서 거르는 방식(advanced filtering)은
  DiskANN만 제공합니다. planner가 비용과 필터 선택도로 사용 여부를 정하므로 `EXPLAIN`으로 계획을 확인합니다.
- **차원 여유** — spherical quantization(SQ, 미리 보기)을 index 옵션 `spherical_quantized = true`로 켜면 3,072차원 같은
  고차원 임베딩도 index할 수 있습니다. 최대 차원은 `sq_bits`가 4면 4,000, 1이면 16,000이며, 모델을 바꿔도 index
  방식을 바꾸지 않습니다.

## 그래프 기능: `age` 확장(Apache AGE)과 openCypher { #graph }

HorizonDB는 그래프 기능을 Apache AGE 기반 `age` 확장(미리 보기)으로 제공합니다. parameter group에서
`azure.extensions`와 `shared_preload_libraries`에 AGE를 켜고 `CREATE EXTENSION age`로 설치합니다.
Apache AGE는 PostgreSQL 안에 property graph를 두는 오픈 소스 확장입니다. graph 하나는 schema 하나, vertex·edge label은
각각 테이블이 되고, openCypher 질의는 `cypher()` 함수로 SQL 안에서 실행해 `agtype` 결과를 받습니다. 그래서
그래프를 관계형 테이블·벡터와 같은 트랜잭션·같은 데이터베이스에서 다룰 수 있습니다.

- **매개변수** — Cypher 매개변수는 `cypher()`의 셋째 인자로 prepared statement parameter만 받습니다.
- **성능** — 시작점 목록을 `UNWIND`로 펼치고 `MATCH (a:Label {key: value})` 속성 map으로 찾으며, label 테이블의
  `properties`에 GIN index를 둡니다.
- **제약** — 원본 테이블이 바뀌어도 graph를 자동으로 따라가는 기능은 없어 trigger나 주기적 재생성을 씁니다.
  저장 구조와 제약은 [그래프 저장 구조](vector-graph-features/index.md#age-storage)에 있습니다.

## DB 안 AI 함수: model registry · 관리형 모델 · BYOM { #in-database-ai }

`azure_ai` 확장을 쓰면 앱 대신 HorizonDB가 모델을 불러 SQL 안에서 임베딩·생성·재순위를 실행합니다. 모델은
model registry에 alias로 등록하며, 등록 방법은 두 가지입니다.

| 방식 | 동작 | 상태 |
|---|---|---|
| 관리형 모델(AI Model Management) | cluster에서 켜면 Microsoft Foundry에 `default-embedding`(`text-embedding-3-small`), `default-chat`, `default-reranker`를 배포·등록하고 과금과 관리를 HorizonDB에 통합합니다. 함수에서 `model`을 생략하면 이 모델을 씁니다. | limited preview(참여 승인 필요) |
| BYOM(Bring Your Own Model) | 직접 배포한 Foundry·Azure OpenAI 모델을 `model_registry.model_add()`로 등록합니다. 지원 endpoint는 `*.services.ai.azure.com`, `*.openai.azure.com`, `*.cognitiveservices.azure.com`이며, API Management endpoint로 요청을 보내 부하 분산·정책을 적용할 수도 있습니다. | 미리 보기 |

```sql
SELECT model_registry.model_add(
    '<model-alias>', '<endpoint-URL>', '<deployment-name>', '<model-name>',
    '<API-version>', 'subscription-key', '<endpoint-key>');

SELECT azure_openai.create_embeddings('<model-alias>', 'Alternatives to LEGO');
```

- **지원 모델** — DB 안 임베딩 함수의 지원 모델은 `text-embedding-3-small`, `text-embedding-3-large`,
  `text-embedding-ada-002`입니다. 그 밖의 모델은 앱이나 별도 서비스에서 임베딩해 벡터를 SQL parameter로 넘깁니다.
- **두 가지 호출 방식** — `azure_ai.*`·`azure_openai.*` 함수는 호출한 문장 안에서 바로 실행됩니다. AI pipeline(미리
  보기)은 `ai.create_pipeline()`에 source 테이블·chunk·embed·extract·rank 단계·sink·`on_change` trigger를 SQL로 선언해
  `pg_durable` 위에서 재시도와 checkpoint를 갖춘 채 나중에 실행하며, 대량 적재와 새 행 자동 임베딩에 맞습니다. Learn은
  pipeline 단계 함수(`ai.embed()` 등)를 모델을 부르지 않는 단계 정의로 설명하지만, `azure_ai` 2.5.6에서는
  `ai.embed()`가 모델을 바로 불러 벡터를 돌려주었으므로 사용 전 `\df ai.embed`로 시그니처를 확인합니다
  ([BYOM 시험](#in-database-ai-movielog)).
- **접근 제어** — 등록한 모델은 기본적으로 모든 DB 사용자가 쓸 수 있으며, `model_user_add`·`model_user_set`으로
  사용자를 제한합니다.

## 활용 패턴: 하이브리드 검색 · graph-augmented RAG · 재순위 · AI pipeline { #patterns }

벡터·그래프·AI 함수가 한 데이터베이스에 있으면 다음 패턴을 별도 검색 엔진이나 그래프 DB 없이 조합할 수 있습니다.

| 패턴 | HorizonDB 구성 |
|---|---|
| 하이브리드 검색 | 벡터 순위와 키워드 순위를 SQL에서 RRF로 결합 |
| 관계 확장(context expansion) | 벡터 결과를 시작점으로 AGE 이웃 탐색 |
| 벡터 관계 저장 | 최근접 결과를 그래프 관계로 저장 |
| 필터 결합 검색 | DiskANN advanced filtering |
| 재순위 | `azure_ai.rank()`로 벡터 후보 재정렬. 관리형 `default-reranker` 또는 BYOM으로 등록한 `Cohere-rerank-v4.0-pro`·`-fast`, GPT 모델 |
| graph-augmented RAG | 벡터 후보 + 그래프 탐색 + RRF 결과를 `azure_ai.generate()`에 문맥으로 전달 |
| 임베딩 자동화 | AI pipeline `on_change` trigger로 새 행 임베딩 |

graph-augmented RAG의 Learn 패턴(authority boosting, context expansion, graph filtering, path-based retrieval)은
[벡터와 그래프 결합](vector-graph-features/index.md#graph-rag)에 있고, MovieLog에 적용한 패턴은
[적용한 활용 패턴](#patterns-movielog)에 있습니다.

## VS Code PostgreSQL 확장: 연결 · AGE 그래프 시각화 · pipeline 보기 { #vscode }

Microsoft의 PostgreSQL extension for Visual Studio Code(`ms-ossdata.vscode-pgsql`, 미리 보기)는 HorizonDB를
구독·resource group·cluster로 찾아 연결하고, 같은 편집기에서 SQL·Cypher·AI 함수를 실행합니다.

| 기능 | HorizonDB에서 쓰는 방법 |
|---|---|
| Connection Manager | read-write endpoint와 read-only endpoint를 profile 두 개로 저장해 작업에 따라 바꿉니다. |
| Apache AGE Graph Visualizer | Cypher 결과가 vertex·edge 객체면 node-edge 그래프로 그립니다. |
| Schema Visualizer | 데이터베이스를 우클릭해 **Visualize Schema**로 테이블과 외래 키 관계를 봅니다. |
| Pipelines & Workflows | AI pipeline 정의와 실행 이력, `pg_durable` workflow 상태를 봅니다. |
| GitHub Copilot `@pgsql` | 연결된 cluster의 확장(`vector`, `pg_diskann`, `azure_ai`, `age`)을 아는 상태로 질의를 돕습니다. |

그래프로 그리려면 속성 대신 객체 전체를 반환하고, 반환한 객체마다 `AS (...)` 열을 하나씩 둡니다. node 이름은
`disp_label` 속성으로 정하며 없으면 내부 id가 보입니다. Learn 예제처럼 `SET`으로 넣으면 graph에 쓰기가 일어나므로
쓰기 권한이 있는 역할로 실행하거나 그래프를 만들 때 `disp_label`을 함께 저장합니다.

## MovieLog 적용: 영화 카탈로그의 의미 검색과 관계 그래프 { #movielog }

MovieLog는 AKS에서 동작하는 Spring Boot 영화 리뷰 앱입니다. 앞에서 소개한 HorizonDB 기능을 다음처럼 썼습니다.
아키텍처, 데이터 모델, 작성 순서, 앱 코드는 [MovieLog 실습](movielog-lab/index.md)에 있고, 이 절은 구성의 요점과
실측값만 정리합니다.

| HorizonDB 기능 | MovieLog 구성 | 자세한 내용 |
|---|---|---|
| 벡터 검색 | `catalog.movie_docs`에 모델별 열(`embedding` 1,536차원, `embedding_bge` 1,024차원)과 열마다 DiskANN index | [데이터 모델](movielog-lab/index.md#data-model) |
| 그래프 | 관계형 테이블에서 만든 `movie_graph`(영화·인물·장르와 감독·출연·장르·유사 관계), trigger 기반 동기화 | [그래프 동기화](movielog-lab/index.md#graph-sync) |
| 벡터와 그래프 결합 | 검색 결과 영화를 시작점으로 그래프 이웃 조회, 임베딩 최근접 3편을 `SIMILAR_TO`로 저장 | [앱 접근 경로](movielog-lab/index.md#app-access) |
| 임베딩 | 앱이 Azure OpenAI 또는 AKS vLLM의 bge-m3-ko로 질의를 임베딩해 SQL parameter로 전달 | [아키텍처](movielog-lab/index.md#architecture) |

### 벡터 검색: DiskANN 선택과 484행 실행 계획 { #vector-movielog }

지금은 484행이라 Learn 기준으로는 flat 범위지만, 리뷰와 영화가 계속 늘어나고 장르·연도 조건 검색을 붙일 계획이라
DiskANN을 골랐습니다.

- **484행 실행 계획** — planner는 seq scan을 골랐고, `SET LOCAL enable_seqscan TO OFF`일 때만 DiskANN index를
  썼습니다.
- **키워드 결합** — 벡터 순위에 제목·인물 이름 일치로 만든 키워드 순위를 Reciprocal Rank Fusion으로 합쳐, 「듄」처럼
  짧은 제목 질의도 놓치지 않게 했습니다. 질의 SQL과 순위 규칙은 [의미 검색 구현](movielog-lab/index.md#search)에
  있습니다.

### 관계 그래프: `movie_graph` 규모와 조회 성능 { #graph-movielog }

MovieLog는 그래프를 관계형 테이블에서 다시 만들 수 있는 파생 데이터로 둡니다. 2026-11-16 기준 그래프는 다음과 같습니다.

| 노드 | 수 | 관계 | 수 |
|---|---|---|---|
| `Movie` | 484 | `ACTED_IN` | 2,801 |
| `Person` | 1,812 | `DIRECTED` | 525 |
| `Genre` | 125 | `IN_GENRE` | 1,659 |
| | | `SIMILAR_TO`(bge-m3-ko 임베딩 최근접 3편, 쌍 단위) | 1,081 |

- **`UNWIND` 효과** — 검색 결과 영화들의 이웃을 처음에는 `MATCH (a:Movie)-[r]-(b) WHERE a.tmdb_id IN [...]`로
  조회해 영화 8편에 26.7초가 걸렸습니다. 같은 결과(134행)를 `UNWIND ... MATCH (a:Movie {tmdb_id: t})`로 바꾸자
  0.12초가 됐습니다. 앱의 Cypher 질의는 [앱 접근 경로](movielog-lab/index.md#app-access)에 있습니다.
- **벡터를 그래프로** — `SIMILAR_TO`는 임베딩 최근접 결과를 관계로 저장한 것이라, "이 영화와 비슷한 영화에 나온
  배우"처럼 벡터와 관계를 섞은 질의를 Cypher 한 번으로 풉니다.
- **화면** — 포스터 노드, 관계 필터, 인물 펼치기는 Cytoscape.js로 그렸으며 화면과 구현은
  [그래프 화면](movielog-lab/index.md#graph-ui)에 있습니다.

### 임베딩 모델: Azure OpenAI와 bge-m3-ko 병행 구성 { #embedding-comparison }

임베딩은 문서와 질의를 같은 모델로 만들어야 하므로 모델마다 벡터 열과 index를 따로 둡니다. DB 안 임베딩 함수의 지원
모델은 OpenAI 세 모델이므로, 한국어 특화 오픈 모델 `dragonkue/BGE-m3-ko`는 AKS에서 직접 서빙했습니다. AKS의 관리형
GPU 노드 풀은 NVIDIA driver와 device plugin을 설치·관리합니다.

MovieLog는 두 모델의 열을 함께 채우고 API의 `model=openai|bge` 매개변수로 요청마다 고르게 했습니다. 두 경로 모두 같은
DiskANN 검색과 RRF 결합 흐름에서 동작하므로, 어느 쪽이든 HorizonDB 쪽 구성은 같습니다. 어느 모델을 쓸지는 아래 운영
조건을 보고, 서비스 데이터로 별도 검색 품질 평가를 거쳐 정합니다.

| 항목 | Azure OpenAI `text-embedding-3-large` | `dragonkue/BGE-m3-ko` |
|---|---|---|
| 차원 | 3,072를 `dimensions`로 1,536으로 줄임 | 1,024 |
| 서빙 | 관리형 Azure OpenAI, Entra ID 인증 | AKS의 vLLM 0.32(OpenAI 호환 `/v1/embeddings`), `Standard_NC4as_T4_v3` spot 노드 1대 |
| 질의 임베딩 평균 | 109.3 ms | 22.0 ms |
| 질의 텍스트 경로 | Azure OpenAI endpoint로 전송 | 클러스터 안에서 처리 |
| 라이선스·비용 | 토큰 과금 | Apache-2.0, GPU VM(spot) 시간 과금 |

- **검색 품질** — 2026-11-16에 질의 12개로 두 모델의 상위 3편을 나란히 확인했고, 두 모델 모두 대부분의 질의에서
  의도에 맞는 영화를 찾았으며 둘 다 놓친 질의도 있었습니다. 정답 집합 없이 눈으로 본 소규모 점검이라 모델 간 품질
  우열의 근거로 쓰지 않습니다. 모델을 고르려면 실제 질의와 관련 영화 정답 집합으로 recall@k·nDCG 같은 지표를 재는
  평가가 필요합니다. 코사인 점수는 모델마다 분포가 달라 두 모델 사이에서 비교하지 않습니다.
- **앱 기본값** — MovieLog 앱의 기본값은 bge-m3-ko이지만 품질 평가에 따른 선택이 아니라 샘플 구성이며, 요청마다
  `model`로 바꿀 수 있습니다.
- **spot 노드 회수** — spot VM이 회수되면 새 노드가 뜰 때까지 `model=bge` 검색은 503을 돌려주고 `model=openai`는
  계속 동작합니다.
- **모델 추가** — bge-m3-ko는 기존 카탈로그 484편을 1분 26초(배치 32)에 임베딩했습니다. 새 열을 추가해 채운 뒤
  index를 만들고 기본 모델을 바꾸므로, 기존 열은 그대로라 되돌리기 쉽습니다.

### DB 안 임베딩 시험: BYOM 등록과 `ai.embed` { #in-database-ai-movielog }

MovieLog 구독에서 두 방식을 시험했고, 최종 앱은 DB 안 임베딩 대신 앱에서 임베딩하는 구조를 유지했습니다.

| 항목 | 2026-11-15 결과 |
|---|---|
| 관리형 모델 | 기능 flag `Microsoft.HorizonDB/enableAiModelManagement`가 승인 대기(`Pending`)라 켤 수 없었습니다. |
| BYOM 인증 | Learn은 `subscription-key`와 `managed-identity`를 적지만, `managed-identity`는 BYOM에서 거부돼 `subscription-key`만 동작했습니다. |
| API Management 경유 | 구독 정책으로 Azure OpenAI key 인증이 꺼져 있어, API Management가 자기 managed identity로 Azure OpenAI를 부르고(`authentication-managed-identity` 정책) HorizonDB에는 API Management subscription key를 등록했습니다. `text-embedding-3-small`과 `-large` 모두 동작했고 첫 호출은 192–253 ms였습니다. |
| `ai.embed` | `azure_ai` 2.5.6에서 `ai.embed(text, model, ...)`가 바로 `real[]`을 돌려주었고, `azure_openai.create_embeddings`는 `ai.embed`를 쓰라는 deprecation 경고를 냈습니다. Learn의 AI pipeline 문서(`azure_ai` 2.3.2 기준)는 `ai.embed()`를 모델을 부르지 않는 pipeline 단계 정의로 설명하므로, 사용 전 `\df ai.embed`로 시그니처를 확인합니다. |
| 오픈 모델 등록 | BYOM의 API Management endpoint 등록 경로를 그대로 쓰되, API Management에 OpenAI 형식(`/openai/deployments/{d}/embeddings`)으로 응답하는 mock을 두고 모델 이름을 `bge-m3-ko`로 등록하자 `ai.embed`가 응답을 받아들였습니다. 등록 경로는 BYOM이고, `bge-m3-ko`가 Learn의 임베딩 지원 모델 목록에 없다는 점만 다릅니다. mock으로 확인했으며 실제 bge-m3-ko 서버를 연결해 보지는 않았습니다. |

```sql
SELECT array_length(ai.embed('마피아 가문의 권력 승계', 'byom-embed-small'), 1);  -- 1536
```

앱 임베딩을 유지한 이유는 bge-m3-ko vLLM 서버가 클러스터 안에만 있어, DB에서 부르려면 지원 형식의 공개 endpoint
뒤에 두어야 했기 때문입니다.

### 적용한 활용 패턴: 하이브리드 검색 · 관계 확장 · 벡터 관계 저장 { #patterns-movielog }

| 패턴 | MovieLog 적용 |
|---|---|
| 하이브리드 검색 | 적용(벡터 상위 50편 + 키워드 상위 50편) |
| 관계 확장(context expansion) | 적용(결과 영화 사이의 인물·장르·유사 관계 그래프) |
| 벡터 관계 저장 | 적용(`SIMILAR_TO`) |
| 필터 결합 검색 | 미적용(장르 열을 `movie_docs`에 두면 가능) |
| 재순위 | 미적용(관리형 `default-reranker`는 승인 대기였고, BYOM으로 지원 rerank·GPT 모델을 등록하면 적용 가능) |
| graph-augmented RAG | 미적용 |
| 임베딩 자동화 | 미적용(앱이 색인 시 임베딩) |

### VS Code 확인: `movie_graph` 시각화용 질의 { #vscode-movielog }

다음 질의는 MovieLog cluster에서 vertex·edge 객체를 그대로 돌려주는 것을 확인했습니다. 확장 화면에서 그려지는
모습은 확인하지 않았습니다.

```sql
SET search_path = ag_catalog, "$user", public;
SELECT * FROM cypher('movie_graph', $$
  MATCH (p:Person)-[r:DIRECTED]->(m:Movie {tmdb_id: 27205})
  RETURN p, r, m
$$) AS (p agtype, r agtype, m agtype);
```

## 실습과 샘플 코드: azd 배포와 외부 코드 레포 { #lab }

앱 소스, Bicep과 azd hook, DB 스크립트, 데이터셋 빌더, Kubernetes manifest, Grafana dashboard는 샘플 코드 레포
[`hellices/sample-movielog-horizondb`](https://github.com/hellices/sample-movielog-horizondb)에 있으며 이 문서는
`v2.7.1` 릴리스를 기준으로 합니다. 앱 이미지는 release workflow가 `ghcr.io/hellices/sample-movielog-horizondb:2.7.1`으로
게시하고, `azd up`의 hook이 digest로 지정해 실습 Azure Container Registry로 가져옵니다.

- [MovieLog 실습](movielog-lab/index.md) — 아키텍처, 데이터 모델, 작성 순서, 앱 구현, 관측, 공개 구성
- [sample-movielog-horizondb README (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/README.md)
- [Azure 배포 절차 (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)

## 미리 보기 제약: 서비스 · 확장 · AI 기능 { #constraints }

- **미리 보기 범위** — HorizonDB, `age` 확장, AI Model Management(limited preview), AI pipeline, VS Code 확장이
  2026-11-16 현재 미리 보기입니다. CLI와 API 구조가 Learn 예제와 달랐으므로 사용 전 `az horizondb -h`와
  provider API 버전을 확인합니다. MovieLog에서 만난 차이는
  [Learn 문서와 실습 cluster의 차이](vector-graph-features/index.md#observed-differences)와
  [실습 문서](movielog-lab/index.md)에 있습니다.
- **AI 함수 버전** — MovieLog cluster의 `azure_ai` 버전(2.5.6)이 Learn 기준(2.2.1–2.3.2)보다 높아 함수 시그니처가 달랐습니다.
- **임베딩 모델 지원** — DB 안 임베딩 함수의 지원 모델 목록은 OpenAI 세 모델입니다. BYOM과 API Management endpoint
  등록은 지원 경로이지만, 그 뒤에 둔 모델이 이 목록 밖이면 문서에 지원 모델로 적힌 구성은 아닙니다.

## 공식 참고 자료

- [What is Azure HorizonDB (Preview)?](https://learn.microsoft.com/azure/horizondb/overview)
- [List of extensions and modules by name in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/extensions/concepts-extensions-versions)
- [Implement vector search with the pgvector extension in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/vector-search-pgvector)
- [Choose the right vector index for your workload in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/vector-index-selection-guide)
- [Scalable vector index with DiskANN in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/vector-index-diskann)
- [Graph database capabilities with Apache AGE extension for Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/graph/age-overview)
- [AI functions in the azure_ai extension in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/ai-functions)
- [AI Model Management in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/ai-model-management)
- [Implement AI pipelines in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/ai-pipelines)
- [Graph-augmented RAG patterns in Azure HorizonDB (Preview)](https://learn.microsoft.com/azure/horizondb/ai/graph-rag)
- [What is the PostgreSQL extension for Visual Studio Code? (Preview)](https://learn.microsoft.com/azure/horizondb/development/vs-code-extension/vs-code-overview)
- [Create a fully managed GPU node pool on Azure Kubernetes Service (AKS)](https://learn.microsoft.com/azure/aks/aks-managed-gpu-nodes)
- [Apache AGE](https://github.com/apache/age)
