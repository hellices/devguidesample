---
title: "Azure HorizonDB 소개: 벡터 검색·그래프와 MovieLog 적용"
description: Azure HorizonDB(미리 보기)의 PostgreSQL 호환 구조와 벡터 검색·그래프·DB 안 AI 기능을 한눈에 소개하고, MovieLog에 적용한 의미 검색과 관계 그래프 결과를 바탕으로 기술 가이드·실습·샘플 코드의 읽기 순서를 안내합니다.
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

# Azure HorizonDB 소개: 벡터 검색·그래프와 MovieLog 적용

## 핵심 흐름: 관계형 데이터 옆의 벡터와 그래프 { #message }

Azure HorizonDB는 PostgreSQL 호환 관리형 데이터베이스에 벡터 검색(`vector`·`pg_diskann`)과
그래프(`age`)를 확장으로 제공합니다. 관계형 데이터, 임베딩 열, 관계 그래프를 한 데이터베이스에 두고
"자연어로 찾고 관계로 넓혀 보는" 검색을 SQL과 openCypher로 구성하는 것이 이 topic의 핵심입니다.

1. 문서 임베딩을 `vector` 열에 저장하고 질의와 가까운 행을 찾습니다.
2. 같은 엔터티를 AGE graph에 연결하고 관계를 탐색합니다.
3. 벡터 검색 결과를 그래프 탐색의 시작점으로 사용하거나 최근접 결과를 그래프 관계로 저장합니다.

영화 리뷰 앱 MovieLog에 Wikidata·Wikipedia 영화 484편을 넣어 이 흐름을 확인했습니다. 아래 화면은
"호빗이나 오크같은게 나오는 영화"를 줄거리 의미로 찾고, 결과 사이의 공통 인물과 `SIMILAR_TO`
관계를 함께 보여 줍니다.

![MovieLog 의미 검색 화면. 질의 '호빗이나 오크같은게 나오는 영화'에 대해 결과 영화 사이의 관계 그래프가 포스터를 붙인 영화 노드, 주황 원의 인물(피터 잭슨, 이언 매켈런, 케이트 블란쳇, 봉준호 등), SIMILAR_TO 점선으로 그려지고, 그 아래에 영화·감독·출연·장르·비슷한 영화 필터 칩이 있으며 장르는 꺼져 있음. 아래 결과 목록은 호빗: 뜻밖의 여정 0.478, 호빗: 스마우그의 폐허 0.435 순서](images/discover-semantic-search.png)

| 단계 | 평균 시간 | 측정 조건 |
|---|---|---|
| 질의 임베딩 — bge-m3-ko(AKS vLLM, T4 spot) | 22.0 ms | 2026-11-15, 40분, 서버 Timer |
| 질의 임베딩 — Azure OpenAI `text-embedding-3-large` | 109.3 ms | 2026-11-15, 40분, 서버 Timer |
| HorizonDB 벡터·키워드 RRF 검색 | 10.9–11.5 ms | 2026-11-15, 40분, 두 모델 |
| HorizonDB AGE 그래프 조회 | 4.45 ms | 2026-11-13, 1시간, Grafana 대시보드 |

이 측정에서는 응답 시간의 대부분이 임베딩 호출이었고 HorizonDB의 검색·그래프 단계는 수~십여
밀리초였습니다. 수치는 이 MovieLog 구성의 관측값이며 일반적인 성능 보장은 아닙니다.

## 읽기 순서: 소개 → 기술 상세 → 실습 → 실행 코드 { #reading-order }

이 페이지는 HorizonDB가 무엇이고 MovieLog에 어떻게 적용됐는지만 빠르게 파악하는 entry입니다.
세부 내용과 실행 절차는 다음 순서로 읽습니다.

| 순서 | 문서 | 이 문서에서 답하는 질문 |
|---|---|---|
| 1 | 현재 페이지 | HorizonDB를 왜 쓰고, 벡터와 그래프를 어떻게 결합하는가? |
| 2 | [HorizonDB 벡터·그래프 기능](vector-graph-features/index.md) | 거리 연산자, index, DiskANN, AGE와 graph-RAG는 어떻게 동작하고 무엇을 선택하는가? |
| 3 | [MovieLog 실습](movielog-lab/index.md) | 관계형 원본에서 벡터와 그래프를 만들고 앱에서 어떻게 검증하는가? |
| 4 | [sample-movielog-horizondb README (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/README.md) | 어떤 명령으로 배포하고 코드·스크립트는 어디에 있는가? |

실행할 때는 sample README와
[배포 절차 (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)를
기준으로 사용합니다. 실습 문서는 명령을 반복하지 않고 구성의 이유와 확인할 결과를 설명합니다.

## HorizonDB 개요: PostgreSQL 호환 AI-ready 관리형 데이터베이스 { #horizondb }

Azure HorizonDB는 PostgreSQL 위에 만든 cloud native 완전 관리형 데이터베이스이며 2026-11-16 현재
미리 보기입니다. compute와 storage를 분리하고, PostgreSQL 확장과 Microsoft Foundry 연동으로
RAG·추천·의미 검색을 데이터베이스 계층에서 구성할 수 있게 합니다.

| 구분 | 핵심 내용 |
|---|---|
| 구조 | 쓰기 primary와 읽기 replica가 storage를 공유하고 compute는 로컬 NVMe cache를 사용 |
| 접속 | read-write endpoint와 read-only endpoint 분리 |
| 벡터 | `vector` 타입과 Flat·IVFFlat·HNSW·DiskANN 선택 |
| 그래프 | Apache AGE 기반 `age` 확장과 openCypher |
| AI | `azure_ai` model registry, AI 함수와 pipeline |
| 도구 | PostgreSQL extension for Visual Studio Code의 SQL·Cypher·graph·pipeline 지원 |

HorizonDB의 차별점은 별도 벡터 검색 엔진과 그래프 데이터베이스를 반드시 함께 운영하지 않아도
관계형 데이터 가까이에서 두 모델을 조합할 수 있다는 점입니다. 반대로 각 기능은 독립 제품보다
지원 범위가 좁거나 미리 보기 제약이 있을 수 있으므로, 기능별 선택 기준과 제약은
[기술 가이드](vector-graph-features/index.md)에서 확인합니다.

### 확장 구성: vector · pg_diskann · age · azure_ai { #extensions }

확장은 parameter group에서 허용한 뒤 데이터베이스에 설치합니다. 공유 메모리를 쓰는 `age`에는
`shared_preload_libraries` 설정도 필요합니다. 다음 버전은 MovieLog cluster에서 확인한 값입니다.

| 확장 | 역할 | MovieLog cluster 버전 |
|---|---|---|
| `vector` | 벡터 타입과 거리 연산자 | 0.8.7 |
| `pg_diskann` | SSD 기반 근사 최근접 이웃 index | 0.7.6 |
| `age` | property graph와 openCypher | 1.8.0 |
| `azure_ai` | Foundry model registry, AI 함수와 pipeline | 2.5.6 |

허용·설치 방법, 버전별 차이와 실제 cluster에서 확인한 동작은
[기술 가이드의 Learn 문서와 실습 cluster 차이](vector-graph-features/index.md#observed-differences)에
정리했습니다.

## 기능 지도: 벡터 검색 · 그래프 · AI 함수 { #capability-map }

<span id="vector"></span><span id="index-options"></span><span id="why-diskann"></span>
<span id="graph"></span><span id="in-database-ai"></span><span id="patterns"></span><span id="vscode"></span>

| 기능 | HorizonDB에서 맡는 일 | 상세 문서 |
|---|---|---|
| 벡터 검색 | `vector(n)` 열을 거리로 정렬하고 Flat·IVFFlat·HNSW·DiskANN 중 workload에 맞는 경로 선택 | [벡터 저장과 index 선택](vector-graph-features/index.md#vector-type) |
| DiskANN | 대부분의 index를 SSD에 두고, 고차원·증가하는 데이터와 필터 결합 검색 지원 | [DiskANN 동작과 매개변수](vector-graph-features/index.md#diskann) |
| AGE graph | graph를 schema와 label 테이블로 저장하고 `cypher()`로 openCypher 실행 | [그래프 저장 구조](vector-graph-features/index.md#age-storage) |
| graph-augmented RAG | 벡터 후보를 graph 이웃·경로·구조적 중요도로 보완 | [벡터와 그래프 결합](vector-graph-features/index.md#graph-rag) |
| DB 안 AI | 등록한 Foundry·Azure OpenAI 모델로 임베딩·생성·재순위와 pipeline 구성 | [Microsoft Learn의 AI functions](https://learn.microsoft.com/azure/horizondb/ai/ai-functions) |

기능별 SQL, index 매개변수, AGE 저장 구조와 제약은 이 페이지에서 반복하지 않습니다. 구현 전에
[기술 가이드](vector-graph-features/index.md)를 읽고 workload 크기, recall, 필터, 모델 지원 범위를 기준으로
선택합니다.

## MovieLog 적용: 의미 검색과 관계 확장 { #movielog }

MovieLog는 AKS에서 동작하는 Spring Boot 영화 리뷰 앱입니다. 관계형 영화 카탈로그를 원본으로 두고,
같은 HorizonDB에 모델별 임베딩 열과 AGE graph를 만들었습니다.

| HorizonDB 기능 | MovieLog 적용 | 확인 위치 |
|---|---|---|
| 벡터 검색 | 1,024차원 bge-m3-ko와 1,536차원 Azure OpenAI 열, 열마다 DiskANN index, 벡터·키워드 RRF | [실습의 데이터 흐름](movielog-lab/index.md#data-flow) |
| 관계 그래프 | 영화·인물·장르 노드와 감독·출연·장르·유사 관계 | [실습의 그래프 구성](movielog-lab/index.md#graph-sync) |
| 벡터와 그래프 결합 | 검색 결과 영화를 시작점으로 이웃 조회, 최근접 3편을 `SIMILAR_TO`로 저장 | [실습의 앱 검증](movielog-lab/index.md#app-verification) |
| 임베딩 서빙 | AKS vLLM의 bge-m3-ko 또는 Azure OpenAI를 요청마다 선택 | [실습 아키텍처](movielog-lab/index.md#architecture) |
| 관측 | 임베딩·검색·그래프 단계를 Timer와 dependency로 분리 | [실습 관측](movielog-lab/index.md#observe) |

### 벡터 검색 결과: 작은 데이터의 planner 선택 { #vector-movielog }

MovieLog의 484행은 Learn의 index 선택 기준으로는 flat scan 범위입니다. 샘플은 데이터 증가와 index
경로 확인을 위해 DiskANN을 만들었지만, 기본 계획에서는 seq scan이 선택됐습니다. 작은 샘플에
DiskANN이 존재한다는 사실을 곧바로 성능 이점으로 해석하지 않습니다.

### 그래프 결과: 관계 조회와 동기화 { #graph-movielog }

2026-11-16 기준 `movie_graph`에는 영화 484개, 인물 1,812개, 장르 125개와 `ACTED_IN` 2,801개,
`DIRECTED` 525개, `IN_GENRE` 1,659개, `SIMILAR_TO` 1,081개가 있었습니다. 검색 결과 영화의
이웃 조회는 AGE 속성 조건과 index를 쓰도록 질의를 바꾼 뒤 26.7초에서 0.12초로 줄었습니다.
[개선한 Cypher 질의 구조](vector-graph-features/index.md#cypher)는 기술 가이드에, 원본 변경을 반영하는
[graph 동기화 방식](movielog-lab/index.md#graph-sync)은 실습 문서에 있습니다.

### 임베딩 구성: 관리형 모델과 AKS 서빙 병행 { #embedding-comparison }

<span id="in-database-ai-movielog"></span><span id="patterns-movielog"></span><span id="vscode-movielog"></span>

문서와 질의는 같은 임베딩 모델을 사용해야 하므로 MovieLog는 모델별 벡터 열과 index를 분리했습니다.
Azure OpenAI `text-embedding-3-large`와 AKS vLLM의 `dragonkue/BGE-m3-ko`를 요청마다 선택할 수 있지만,
12개 질의를 눈으로 확인한 결과만으로 모델 우열을 판단하지 않았습니다. 실제 선택에는 서비스 질의와
정답 집합을 사용한 recall@k·nDCG 평가가 필요합니다.

DB 안 임베딩도 시험했지만 최종 앱은 임베딩을 앱 계층에서 수행합니다. 당시 관리형 model 기능은 승인
대기였고, 클러스터 내부 bge-m3-ko endpoint를 HorizonDB가 직접 호출할 수 없었기 때문입니다. 날짜별
시험 결과, `azure_ai` 버전 차이와 BYOM 인증 관측은
[기술 가이드의 DB 안 AI 함수 관측](vector-graph-features/index.md#in-database-ai-observations)에 보존하고,
최종 앱의 호출 경로는 [실습 아키텍처](movielog-lab/index.md#architecture)에서 설명합니다.

## 실습과 샘플 코드: 해설과 실행 절차의 분리 { #lab }

- [MovieLog 실습](movielog-lab/index.md) — 아키텍처, 데이터 흐름, 검색·그래프 검증과 관측 결과
- [sample README (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/README.md) — 준비물, 로컬 테스트, 배포 명령과 저장소 구성
- [Azure 배포 절차 (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md) — 환경값, 단계별 동작, 검증과 장애 대응

샘플 앱, Bicep, azd hook, DB 스크립트, Kubernetes manifest와 dashboard는 외부 코드 레포에 있습니다.
이 topic은 `v2.7.1`과 commit `eedbe2c47c779730151fce2947157e87f4925270`을 기준으로 합니다.

## 미리 보기 제약: 서비스 · 확장 · AI 기능 { #constraints }

- HorizonDB, `age`, AI Model Management, AI pipeline과 VS Code 확장의 일부 기능은 2026-11-16 현재
  미리 보기입니다.
- MovieLog cluster의 확장 버전은 당시 Learn 문서 기준보다 높아 일부 함수와 CLI·API 구조가 달랐습니다.
- DB 안 임베딩 함수가 문서화한 지원 모델과 BYOM endpoint 등록 가능 범위는 같은 개념이 아닙니다.
- 실제 구현 전 현재 Learn 문서와 대상 cluster의 확장 버전·함수 signature를 다시 확인합니다.

구체적인 차이와 확인 명령은
[Learn 문서와 실습 cluster의 차이](vector-graph-features/index.md#observed-differences)에 있습니다.

## 공식 참고 자료

- [What is Azure HorizonDB (Preview)?](https://learn.microsoft.com/azure/horizondb/overview)
- [Implement vector search with the pgvector extension](https://learn.microsoft.com/azure/horizondb/ai/vector-search-pgvector)
- [Choose the right vector index](https://learn.microsoft.com/azure/horizondb/ai/vector-index-selection-guide)
- [Scalable vector index with DiskANN](https://learn.microsoft.com/azure/horizondb/ai/vector-index-diskann)
- [Graph database capabilities with Apache AGE](https://learn.microsoft.com/azure/horizondb/graph/age-overview)
- [AI functions in the azure_ai extension](https://learn.microsoft.com/azure/horizondb/ai/ai-functions)
- [Graph-augmented RAG patterns](https://learn.microsoft.com/azure/horizondb/ai/graph-rag)
