---
title: "Azure HorizonDB 벡터·그래프 기능: pgvector·DiskANN과 Apache AGE"
description: Azure HorizonDB(미리 보기)가 PostgreSQL 확장으로 제공하는 벡터 검색(vector·pg_diskann)과 그래프(Apache AGE)의 데이터 표현, 거리 연산자, index 선택 기준, DiskANN 매개변수와 advanced filtering, AGE의 schema·label 테이블 구조, cypher() 함수와 매개변수, graph-augmented RAG 패턴을 Microsoft Learn 기준으로 정리하고 MovieLog 실습 cluster에서 확인한 실행 계획과 문서와 다른 동작을 함께 기록합니다.
document_type: guide
services: [azure-horizondb]
technologies: [postgresql]
tags: [design, evaluate]
status: current
verification_status: needs-review
sources_checked_at: 2026-11-13
official_sources:
  - title: Implement vector search with the pgvector extension in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-search-pgvector
  - title: Choose the right vector index for your workload in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-selection-guide
  - title: Scalable vector index with DiskANN in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-diskann
  - title: Optimize performance when using pgvector for Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/optimize-pgvector-performance
  - title: Graph database capabilities with Apache AGE extension for Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/graph/age-overview
  - title: Considerations for using extensions and modules in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/extensions/concepts-extensions-considerations
  - title: Graph-augmented RAG patterns in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/graph-rag
  - title: What is Azure HorizonDB (Preview)?
    url: https://learn.microsoft.com/azure/horizondb/overview
  - title: Apache AGE Prepared Statements
    url: https://github.com/apache/age-website/blob/master/docs/advanced/prepared_statements.md
  - title: Apache AGE Data Types
    url: https://github.com/apache/age-website/blob/master/docs/intro/types.md
last_verified: 2026-11-13
review_cycle_days: 30
applies_to: [Azure HorizonDB 미리 보기, PostgreSQL 17, vector 0.8.7, pg_diskann 0.7.6, age 1.8.0]
topic_order: 1
---

# Azure HorizonDB 벡터·그래프 기능: pgvector·DiskANN과 Apache AGE

Azure HorizonDB는 벡터와 그래프를 별도 데이터베이스가 아니라 PostgreSQL 확장으로
제공합니다. 벡터는 `vector`(pgvector) 타입과 `pg_diskann` index로, 그래프는 Apache AGE의
label 테이블과 openCypher로 다룹니다. 둘 다 같은 데이터베이스 안의 일반 테이블에 저장되므로
관계형 테이블과 SQL로 join하고 같은 트랜잭션·권한·백업을 공유합니다.

이 문서는 2026-11-13 Microsoft Learn의 HorizonDB 문서를 기준으로 두 기능을 정리하고,
[MovieLog 의미 검색 실습](../index.md) cluster에서 확인한 실행 계획과 문서와 다른 동작을
덧붙입니다. 실습의 데이터 모델과 앱 접근 경로는 entry의
[HorizonDB 데이터 모델](../index.md#data-model)에 있습니다.

| 구분 | 벡터 | 그래프 |
|---|---|---|
| 확장 | `vector`, `pg_diskann` | `age`(`shared_preload_libraries` 필요) |
| 저장 형태 | 테이블의 `vector(n)` 열 | graph마다 schema 1개, label마다 테이블 1개 |
| 질의 | `ORDER BY embedding <=> :q LIMIT k` | `SELECT * FROM cypher('graph', $$ MATCH ... $$) AS (...)` |
| index | Flat·IVFFlat·HNSW·DiskANN | `properties` GIN, edge `start_id`·`end_id` btree |
| MovieLog 적용 | `catalog.movie_docs.embedding vector(1536)`, DiskANN 코사인 | `movie_graph`: Movie·Person·Genre, 관계 4종 |

## 벡터 저장과 거리 연산: `vector` 타입과 pgvector 연산자 { #vector-type }

벡터는 `vector(n)` 열에 `'[x, y, ...]'` 문자열로 넣고, 거리 연산자로 정렬해 최근접 이웃을
찾습니다. 확장 이름은 커뮤니티 명칭인 pgvector가 아니라 `vector`이며, parameter group의
`azure.extensions`에 허용한 뒤 데이터베이스마다 `CREATE EXTENSION vector`를 실행합니다.

| 연산자 | 거리 | index operator class |
|---|---|---|
| `<->` | Euclidean(L2) | `vector_l2_ops` |
| `<=>` | 코사인 거리 | `vector_cosine_ops` |
| `<#>` | 음의 내적 | `vector_ip_ops` |

- **연산자와 operator class 일치** — index는 만들 때 지정한 operator class의 연산자로 정렬할
  때만 쓰입니다. Learn은 Azure OpenAI `text-embedding-3-*`를 포함한 대부분의 임베딩 모델에
  코사인 거리를 기본으로 권합니다.
- **함수와 집계** — `cosine_distance`, `l2_distance`, `inner_product`, `l1_distance`,
  `vector_dims`, `vector_norms` 함수와 `AVG`·`SUM` 집계도 제공합니다.
- **MovieLog 적용** — `catalog.movie_docs.embedding vector(1536)`에 코사인 operator class index를
  만들고, 화면 점수는 `1 - (embedding <=> :q)`로 계산합니다. 앱은 질의 벡터를 문자열로
  만들어 `CAST(:v AS vector)`로 넘깁니다.

## 벡터 index 선택: Flat · IVFFlat · HNSW · DiskANN { #vector-index }

Learn은 HorizonDB의 production AI 워크로드 기본값으로 DiskANN을 권하지만, 10만 행 미만이고
지연이 중요하지 않으면 index 없는 flat scan을 첫 선택으로 둡니다. 네 방식 모두 같은 SQL과
연산자를 쓰므로 `CREATE INDEX`만 바꿔 옮길 수 있습니다.

| 항목 | Flat | IVFFlat | HNSW | DiskANN |
|---|---|---|---|---|
| 방식 | 전체 비교 | 분할(list) 탐색 | 다층 그래프 | SSD 최적화 그래프 |
| recall | 100% | 낮음–중간 | 높음 | 높음 |
| 메모리 | 없음 | 작음 | 큼(RAM에 올라가야 함) | 작음(대부분 SSD) |
| 삽입·갱신 | 비용 없음 | recall 저하, 주기적 재생성 | 제자리 반영 | 제자리 반영 |
| 최대 차원 | 16,000 | 2,000 | 2,000 | 16,000 |
| 필터 결합 | 항상 정확 | 후필터, recall 저하 | 후필터, recall 저하 | index 안에서 필터(advanced filtering) |

선택 순서는 다음과 같습니다. 10만 행 미만이면 flat, 16,000차원을 넘거나 메타데이터 필터를
높은 recall로 결합해야 하면 DiskANN, RAM보다 커지거나 계속 늘어날 데이터면 DiskANN, 정적이고
RAM에 들어가며 recall이 중요하면 HNSW, 빠른 build를 위해 낮은 recall을 감수하면 IVFFlat입니다.

MovieLog의 영화 문서는 479행이라 이 기준으로는 flat scan 범위입니다. 실습은 index 경로를
확인하려고 DiskANN을 만들었고, planner는 평소에 seq scan을 골랐습니다. 트랜잭션 안에서
`SET LOCAL enable_seqscan TO OFF`를 주면 DiskANN index를 씁니다.

```text
-- 2026-11-13, catalog.movie_docs 479행, SET LOCAL enable_seqscan TO OFF
Limit
  ->  Index Scan using movie_docs_embedding_diskann on movie_docs
        Order By: (embedding <=> (InitPlan 1).col1)
```

## DiskANN 동작과 매개변수: build·검색 L 값과 spherical quantization { #diskann }

DiskANN은 Microsoft Research의 그래프 기반 근사 최근접 이웃 알고리즘입니다. 대부분의 데이터를
SSD에 둔 채 높은 recall과 낮은 지연을 유지하도록 설계됐고, 삽입·갱신을 index에 바로
반영합니다. parallel build와 `REINDEX CONCURRENTLY`도 지원합니다.

| 매개변수 | 시점 | 기본값 | 의미 |
|---|---|---|---|
| `max_neighbors` | index build | 32 | 그래프 node당 최대 간선 수. 키우면 일정 수준까지 recall이 오릅니다. |
| `l_value_ib` | index build | 100 | build 중 검색 목록 크기. 키우면 build가 느려지고 index 품질이 오릅니다. |
| `spherical_quantized` | index build | false | spherical quantization(SQ) 사용 여부 |
| `sq_bits` | index build | 4 | 차원당 bit 수. 4는 최대 4,000차원, 1은 최대 16,000차원 |
| `sq_training_samples` | index build | 25,000 | quantizer 보정 표본 수 |
| `diskann.l_value_is` | 질의 | 100 | 검색 목록 크기. 키우면 recall이 오르고 질의가 느려질 수 있습니다. |
| `diskann.iterative_search` | 질의 | `relaxed_order` | `LIMIT`을 채울 때까지 L 단위로 반복 탐색합니다. `strict_order`는 거리 순서를 보장하고, `off`는 최대 L개만 돌려줍니다. |

- **고차원 임베딩** — 3,072차원 `text-embedding-3-large`를 그대로 index하려면 SQ를 켜고
  `sq_bits = 4`를 씁니다. MovieLog는 모델의 `dimensions` 매개변수로 1,536차원을 받아
  SQ 없는 기본 index를 썼습니다.
- **대량 build** — bulk insert 뒤에 index를 만들고, `maintenance_work_mem`과 parallel worker를
  늘립니다. 300만 행을 넘으면 `TABLESPACE temptablespace`를 붙입니다.
- **설정 확인** — 실습 cluster에서는 세션이 DiskANN index를 쓰기 전에 `SHOW diskann.l_value_is`가
  `unrecognized configuration parameter`로 실패했습니다. index를 쓴 뒤에는 `100`과
  `Relaxed_Order`가 보였습니다.

## 필터 결합 검색: DiskANN advanced filtering { #advanced-filtering }

DiskANN의 advanced filtering(미리 보기)은 `WHERE` 조건을 index 탐색 안에서 평가해, 조건을
통과한 행으로 `LIMIT`을 채울 때까지 그래프를 계속 탐색합니다. IVFFlat·HNSW는 상위 K개를 먼저
찾은 뒤 거르므로 조건이 선택적일수록 결과가 모자라고 recall이 떨어집니다.

```sql
SELECT id, category, price
FROM products
WHERE tenant_id = 42 AND category = 'kitchen'
ORDER BY embedding <=> :query_embedding
LIMIT 10;
```

- **문법** — 별도 문법은 없으며 DiskANN index가 있으면 planner가 자동으로 씁니다. 자주
  거르는 열에는 btree index를 함께 둡니다.
- **세션 조정** — `diskann.enable_filter_hook`, `diskann.selectivity_min`,
  `diskann.selectivity_threshold`, `diskann.filtering_beta`, `diskann.l_value_is`로 필터 적용
  강도와 recall을 조정합니다. 주로 benchmark와 recall 조정용입니다.
- **제약** — 조건은 벡터 열과 같은 테이블의 열이어야 하며, join은 벡터 검색이 끝난 뒤
  평가됩니다. 필터 열에 함수를 씌운 조건은 index로 내려가지 않고 후필터가 됩니다.
- **MovieLog에 적용할 때** — 현재 질의는 필터 없이 `public.movies`와 join합니다. 이 제약에
  따르면 장르 조건을 index 안에서 거르려면 `catalog.movie_genres` join이 아니라
  `movie_docs`에 장르 열을 두어야 합니다. 실습에서는 측정하지 않았습니다.
- **선택도 판정** — 실습 cluster에서 `embedding IS NOT NULL AND tmdb_id <> :id`처럼 거의 모든
  행이 통과하는 조건을 붙이면 `pg_diskann: Filter selectivity too high (0.9979), skipping
  filtered vector scan` NOTICE를 내고 필터 탐색을 건너뛰었습니다. 이 질의는 `public.movies`와
  join해, seq scan을 꺼도 DiskANN 대신 정렬 계획을 썼습니다.

## 그래프 저장 구조: graph는 schema, label은 테이블 { #age-storage }

Apache AGE는 PostgreSQL에 그래프 기능과 openCypher를 더하는 Apache 프로젝트입니다. graph를
만들면 같은 이름의 schema가 생기고, vertex·edge label마다 그 schema에 테이블이 하나씩
생깁니다. 노드와 관계는 PostgreSQL ACID 트랜잭션으로 쓰입니다.

| 객체 | 내용 | `movie_graph` 실측 |
|---|---|---|
| `ag_catalog.ag_graph` | graph 이름과 namespace(schema) | `movie_graph` → schema `movie_graph` |
| `ag_catalog.ag_label` | label 이름, 종류(`v`/`e`), 저장 테이블 | vertex `Movie`·`Person`·`Genre`, edge `ACTED_IN`·`DIRECTED`·`IN_GENRE`·`SIMILAR_TO` |
| vertex 테이블 | `id graphid`, `properties agtype` | `movie_graph."Movie"` 등. `_ag_label_vertex`를 상속 |
| edge 테이블 | `id`, `start_id`, `end_id`, `properties agtype` | `movie_graph."SIMILAR_TO"` 등. `_ag_label_edge`를 상속 |

- **활성화** — parameter group에서 `azure.extensions`와 `shared_preload_libraries`에 AGE를
  넣고 연결하면 cluster가 재시작합니다. 그 뒤 `CREATE EXTENSION IF NOT EXISTS age CASCADE`를
  실행합니다. preload를 빠뜨리면 첫 Cypher 질의에서 `unhandled cypher(cstring) function call`
  오류가 납니다.
- **`LOAD 'age'` 불필요** — preload가 라이브러리를 올리므로 실행하지 않습니다. 실습 cluster에서
  관리자 계정으로 실행하면 `access to library "age" is not allowed`가 났습니다.
- **일반 테이블로 다루기** — label이 테이블이므로 `GRANT SELECT`로 읽기 권한을 주고,
  `properties`에 GIN index를 만들 수 있습니다. edge label 테이블은 AGE가 `start_id`·`end_id`
  btree index를 함께 만들었습니다. Learn은 자주 거르는 node 속성에 GIN index를 권합니다.
- **graph id** — `graphid`는 label id와 label별 sequence를 조합한 값입니다. 앱이 영화를
  찾을 때는 이 값 대신 속성의 `tmdb_id`·`qid`로 관계형 테이블과 잇습니다.

## openCypher 실행: `cypher()` 함수, agtype 결과, 실행 계획 { #cypher }

openCypher는 `ag_catalog.cypher(graph, query[, params])` 함수 안에서 실행하며, 반환 열 목록을
`AS (...)`로 직접 선언합니다. AGE가 돌려주는 타입은 JSON의 상위 집합인 `agtype` 하나이고,
`RETURN` 항목 수와 `AS (...)` 열 수가 맞아야 합니다. `search_path`에 `ag_catalog`를 넣으면
함수와 타입을 schema 이름 없이 쓸 수 있습니다.

```sql
SET search_path = ag_catalog, "$user", public;

SELECT * FROM cypher('movie_graph', $$
  UNWIND [27205, 157336, 155] AS t
  MATCH (a:Movie {tmdb_id: t})-[r]-(b)
  RETURN id(b)
$$) AS (b agtype);
```

이 질의는 PostgreSQL 실행 계획으로 바뀌어 label 테이블의 index를 씁니다. 실습 cluster에서
영화 3편의 이웃 53행을 2.2 ms에 돌려줬습니다.

```text
Bitmap Index Scan on "Movie_properties_idx"
  Index Cond: (properties @> agtype_build_map('tmdb_id', age_unnest('[27205, 157336, 155]')))
Append                                    -- edge label 테이블 전체
  ->  Bitmap Heap Scan on "SIMILAR_TO" r_5
        ->  BitmapOr
              ->  Bitmap Index Scan on "SIMILAR_TO_start_id_idx"
              ->  Bitmap Index Scan on "SIMILAR_TO_end_id_idx"
```

- **속성 map 조건** — `{tmdb_id: t}`는 `properties @>` 포함 조건이 되어 GIN index를 씁니다.
  같은 조건을 `WHERE a.tmdb_id IN [...]`으로 쓴 질의는 26.7초가 걸렸습니다
  ([entry 측정](../index.md#graph)).
- **label 없는 관계** — `-[r]-`는 `_ag_label_edge`를 상속한 edge 테이블을 모두 `Append`로
  읽고, 테이블마다 `start_id`·`end_id` index를 `BitmapOr`로 씁니다.
- **매개변수** — Cypher의 `$name` 값은 셋째 인자에 agtype map으로 넘기며, 이 인자는 SQL
  parameter여야 합니다. 실습 cluster에서 `PREPARE ... cypher(..., $1)`는 동작했고, 상수나
  `jsonb_build_object(...)::text::agtype` 식을 넘기면 SQL과 PL/pgSQL `DO` 블록 모두에서
  `third argument of cypher function must be a parameter`로 거부됐습니다.

```sql
PREPARE movie_title(agtype) AS
SELECT * FROM cypher('movie_graph', $$
  MATCH (m:Movie {tmdb_id: $t}) RETURN m.title
$$, $1) AS (title agtype);

EXECUTE movie_title('{"t": 27205}');
```

### openCypher 지원 범위와 graph 제약 { #age-limits }

AGE는 openCypher의 일부만 구현합니다. Learn은 다음 제약을 듭니다.

| 제약 | 내용 | 대응 |
|---|---|---|
| Cypher 부분 지원 | `MERGE ... ON CREATE SET`, `EXISTS` subquery, `datetime()`을 쓸 수 없습니다. | 중복 검사를 둔 `CREATE`나 PL/pgSQL로 감쌉니다. |
| 수동 유지 | 원본 데이터가 바뀌어도 graph를 자동으로 따라가는 CDC가 없습니다. | 원본 테이블 trigger나 주기적 재생성을 씁니다. MovieLog는 스크립트로 graph를 지우고 다시 만듭니다. |
| 가변 길이 경로 | `[*1..N]`이 3–4 hop을 넘으면 경로가 지수적으로 늘어납니다. | hop을 제한하고 중간 node 속성으로 일찍 거릅니다. |
| 데이터베이스 경계 | 다른 데이터베이스의 graph는 조회할 수 없습니다. | graph와 벡터를 같은 데이터베이스에 둡니다. |
| major version 업그레이드 | AGE는 in-place major version 업그레이드에서 모든 버전을 지원하지 않습니다. | 업그레이드 전 지원 여부를 확인합니다. |

### graph 시각화: VS Code PostgreSQL 확장 { #age-visualization }

Learn은 PostgreSQL extension for Visual Studio Code가 AGE Cypher 결과를 node-edge 그래프로
그린다고 설명합니다. 속성 대신 vertex·edge 객체 전체를 반환하고, 반환한 객체마다 `AS (...)`
열을 하나씩 둡니다. node 표시 이름은 `disp_label` 속성을 쓰며, Learn 예제처럼
`SET`으로 넣으면 graph에 속성이 저장되므로 쓰기 권한이 필요합니다. MovieLog 앱 role은
`movie_graph`에 SELECT 권한만 있으며, 앱 화면은 Cytoscape.js로 그립니다. VS Code 확장은
실습에서 확인하지 않았습니다.

```sql
SELECT * FROM cypher('movie_graph', $$
  MATCH (a:Movie {tmdb_id: 27205})-[r]-(b)
  RETURN a, r, b
$$) AS (a agtype, r agtype, b agtype);
```

## 벡터와 그래프 결합: graph-augmented RAG 패턴 { #graph-rag }

Learn은 벡터 검색만으로 부족한 질의에 graph 탐색을 더하는 graph-augmented RAG를 HorizonDB
안에서 실행하는 패턴을 제시합니다. 벡터 유사도는 엔터티 사이 관계, 여러 단계 추론,
의미는 멀지만 구조상 중요한 결과, 동음이의어 구분에 약하기 때문입니다.

1. 질의를 임베딩해 pgvector(DiskANN 또는 HNSW)로 후보를 찾습니다.
2. `azure_ai.rank()`의 cross-encoder로 후보를 다시 정렬합니다.
3. AGE graph를 탐색해 관계로 이어진 엔터티와 문서를 찾습니다.
4. 두 순위를 Reciprocal Rank Fusion(RRF)으로 합칩니다.
5. 합친 상위 결과를 LLM에 문맥으로 넘깁니다.

| 패턴 | 그래프의 역할 | MovieLog에 대응하는 예 |
|---|---|---|
| Authority boosting | 인용·연결 수 같은 구조적 중요도로 벡터 결과를 다시 매김 | 출연·감독 관계가 많은 영화에 가산점(미구현) |
| Context expansion | 질의 엔터티의 이웃을 탐색해 벡터가 놓친 문서를 추가 | 결과 영화의 인물·장르·`SIMILAR_TO` 이웃. 현재는 화면에 그리기만 하고 순위에는 섞지 않음 |
| Graph filtering | 관계를 경계(권한·소유·분류)로 써서 후보를 제한 | 특정 감독 작품 안에서 의미 검색(미구현) |
| Path-based retrieval | 경로 자체가 답인 질의 | 두 배우를 잇는 출연작 경로(미구현) |

Learn은 graph를 만드는 방법으로 LLM 추출(`azure_ai.extract()`), 관계형 테이블에서 만드는
schema-driven 방식, Microsoft GraphRAG 라이브러리를 듭니다. MovieLog는 schema-driven
방식입니다. 카탈로그 테이블에서 Movie·Person·Genre와 출연·감독·장르 관계를 만들고, 벡터
최근접 3편으로 `SIMILAR_TO`를 더해 벡터 결과를 graph 관계로 저장했습니다. Learn의 도메인
예 가운데 content recommendation이 이 구조에 해당합니다.

## Learn 문서와 실습 cluster의 차이 { #observed-differences }

2026-11-13 실습 cluster에서 확인한 차이입니다. 미리 보기 서비스이므로 사용 전 실제 cluster에서
다시 확인합니다. 확장 버전 차이는 entry의 [확장 표](../index.md#extensions)에 있습니다.

| 항목 | Learn | 실습 cluster |
|---|---|---|
| `cypher()` 셋째 인자 | graph-augmented RAG 예제가 `jsonb_build_object(...)::text::agtype` 식을 넘깁니다. | 식은 거부되고 prepared statement parameter만 동작했습니다(AGE 1.8.0). AGE 문서는 SQL parameter를 요구합니다. |
| `l_value_ib` 기본값 | DiskANN 문서는 100, pgvector 성능 문서는 50으로 적습니다. | 확인하지 않았습니다. 이 문서는 DiskANN 문서 값을 따릅니다. |
| pgvector 성능 문서의 DiskANN 설명 | "DiskANN is only supported in Azure PostgreSQL Flexible Server" 문구가 있습니다. | HorizonDB에서 `pg_diskann` 0.7.6으로 DiskANN index를 만들고 썼습니다. |
| `pg_diskann` 문서 버전 | 0.7.3 기준 | 0.7.6 |
| connection pooling | graph-augmented RAG 문서는 내장 PgBouncer(6432)를 권합니다. | 개요 문서는 미리 보기 제약으로 내장 PgBouncer 미지원을 듭니다. 실습은 앱의 HikariCP만 썼습니다. |
