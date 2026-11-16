---
title: "MovieLog 실습: HorizonDB 의미 검색과 관계 그래프 검증"
description: MovieLog sample을 통해 관계형 영화 카탈로그에서 모델별 임베딩과 DiskANN 검색, Apache AGE 관계 그래프를 만들고 AKS 앱에서 검색·그래프·관측 결과를 검증하는 학습 흐름을 설명합니다. 실행 명령과 배포 절차는 고정 버전 sample 저장소로 안내합니다.
document_type: lab
services: [azure-horizondb, azure-kubernetes-service, azure-openai, azure-monitor, azure-application-gateway-for-containers]
technologies: [postgresql, java, spring-boot, kubernetes, bicep]
tags: [build, deploy]
status: verified
verification_status: needs-review
sources_checked_at: 2026-11-16
official_sources:
  - title: Customize your Azure Developer CLI workflows using command and event hooks
    url: https://learn.microsoft.com/azure/developer/azure-developer-cli/azd-extensibility
  - title: Create a fully managed GPU node pool on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/aks-managed-gpu-nodes
  - title: Use GPUs for compute-intensive workloads on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/use-nvidia-gpu
  - title: Allow extensions in Azure HorizonDB
    url: https://learn.microsoft.com/azure/horizondb/extensions/how-to-allow-extensions
  - title: Load libraries in Azure HorizonDB
    url: https://learn.microsoft.com/azure/horizondb/extensions/how-to-load-libraries
  - title: Graph database capabilities with Apache AGE extension for Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/graph/age-overview
  - title: "Quickstart: Deploy Application Gateway for Containers ALB Controller using AKS Add-on"
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon
  - title: Cert-manager and Let's Encrypt with Application Gateway for Containers - Gateway API
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/how-to-cert-manager-lets-encrypt-gateway-api
  - title: URL Redirect for Azure Application Gateway for Containers - Gateway API
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/how-to-url-redirect-gateway-api
  - title: Application Gateway for Containers components
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-components
  - title: Autoinstrument AKS apps with Azure Monitor Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless
  - title: Use Microsoft Entra Workload ID with Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/workload-identity-overview
  - title: ID token claims reference
    url: https://learn.microsoft.com/entra/identity-platform/id-token-claims-reference
  - title: Connect your Azure identity provider to the Azure Key Vault Secrets Store CSI Driver in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/csi-secrets-store-identity-access
  - title: Integrate Key Vault with Azure Private Link
    url: https://learn.microsoft.com/azure/key-vault/general/private-link-service
  - title: Apache AGE
    url: https://github.com/apache/age
last_verified: 2026-11-15
review_cycle_days: 30
estimated_time: 90m
cost: paid
cleanup_required: true
topic_order: 2
---

# MovieLog 실습: HorizonDB 의미 검색과 관계 그래프 검증

## 실습 목표: 데이터 흐름과 결과 검증 { #scope }

이 실습은 [HorizonDB 소개](../index.md)에서 본 MovieLog 결과가 어떤 데이터 흐름으로 만들어지는지
이해하고 직접 확인하는 문서입니다. 복사해 실행할 명령과 환경값은 중복해서 관리하지 않습니다.
실행할 때는 다음 고정 버전 문서를 사용합니다.

- [sample README (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/README.md) — 준비물, 로컬 테스트, 빠른 배포와 저장소 구조
- [Azure 배포 절차 (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md) — 환경값, 단계별 동작, 검증과 장애 대응
- [고정된 source commit](https://github.com/hellices/sample-movielog-horizondb/tree/eedbe2c47c779730151fce2947157e87f4925270) — 이 문서가 설명하는 실제 코드

실습에서는 다음 순서로 결과를 확인합니다.

1. 관계형 카탈로그가 벡터 열과 AGE graph의 원본인지 확인합니다.
2. 같은 문서를 두 모델로 임베딩하되 열과 index를 분리한 이유를 확인합니다.
3. 의미 검색 결과와 그래프 이웃 조회가 하나의 사용자 흐름으로 결합되는지 확인합니다.
4. 임베딩·검색·그래프 시간을 분리해 관측합니다.
5. 유료 리소스와 외부 공개 구성을 정리합니다.

sample은 GPU를 포함한 유료 Azure 리소스를 만듭니다. 2026-11-15 Korea Central의 새 구독 환경에서는
HorizonDB cluster·pool 준비와 카탈로그 적재를 포함해 약 1시간이 걸렸습니다. 최신 준비물, 비용 영향과
정리 명령은 위 배포 문서가 단일 출처입니다.

## 아키텍처: AKS MovieLog → 임베딩 → HorizonDB { #architecture }

MovieLog는 AKS에서 동작하고, 질의를 AKS 내부 vLLM의 bge-m3-ko 또는 Azure OpenAI로 임베딩합니다.
앱은 얻은 벡터를 HorizonDB SQL parameter로 보내고, 검색 결과 영화의 ID로 AGE graph를 조회합니다.
카탈로그 적재와 graph 생성은 배포 hook이 준비하며 Application Insights와 Managed Grafana가 각 단계를
관측합니다.

![MovieLog on Azure HorizonDB 아키텍처. 브라우저가 HTTPS로 App Gateway for Containers에 들어오고(cert-manager가 발급한 Let's Encrypt 인증서), AKS 관리형 VNet 안의 MovieLog 앱이 요청마다 같은 VNet의 GPU spot 노드에서 vLLM이 서빙하는 bge-m3-ko(model=bge) 또는 클러스터 밖 Azure OpenAI text-embedding-3-large(model=openai)에 질의 임베딩을 요청한 뒤 Azure HorizonDB에 SQL과 Cypher를 보냄. HorizonDB 안에는 관계형 테이블, pgvector와 DiskANN(1024·1536차원), Apache AGE movie_graph가 있음. 카탈로그 로더는 Wikidata와 Wikipedia 데이터를 HorizonDB에 적재하고, 문서를 Azure OpenAI로 직접, bge-m3-ko는 port-forward로 vLLM에 보내 임베딩함. MovieLog의 텔레메트리는 Application Insights로, Application Insights는 KQL로 Managed Grafana에 연결됨](../images/architecture.svg)

| 구성 요소 | 실습에서 확인할 책임 |
|---|---|
| MovieLog | 질의 교정, 모델 선택, 의미 검색 결과와 graph API 조합 |
| bge-m3-ko · Azure OpenAI | 같은 문서·질의를 모델별로 임베딩 |
| HorizonDB 관계형 schema | 영화·인물·장르의 원본과 앱의 회원·리뷰 저장 |
| `vector` · `pg_diskann` | 모델별 임베딩 열과 최근접 검색 |
| Apache AGE | 원본에서 파생한 영화·인물·장르 관계 탐색 |
| Application Insights · Grafana | 임베딩·검색·그래프 단계별 시간과 실패 관측 |

HorizonDB의 제품 기능과 선택 기준은 이 문서에서 반복하지 않습니다. 거리 연산, index 선택, DiskANN과
AGE 제약은 먼저 [HorizonDB 벡터·그래프 기능](../vector-graph-features/index.md)을 확인합니다.

### HorizonDB 리소스 구조: cluster · pool · parameter group { #resource-model }

2026-11-13 실습의 Azure CLI `horizondb` 1.0.0b9에서는 cluster, compute pool, parameter group과 firewall
rule이 분리돼 있었습니다. sample의 azd hook은 이 구조에 맞춰 HorizonDB를 준비하고, parameter group에
`vector`, `pg_diskann`, `age`를 허용하며 `age`를 preload합니다. 이 내용은 미리 보기 API에 따라 달라질 수
있으므로 현재 명령과 실제 배포 동작은 [배포 절차](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)를
기준으로 확인합니다.

## 데이터 흐름: 관계형 원본 → 벡터 → 그래프 { #data-flow }

관계형 테이블이 원본이고, 벡터는 문서 행에 붙은 모델별 열이며, graph는 관계형 행과 임베딩에서 다시
만들 수 있는 파생 데이터입니다. 세 표현은 같은 `movielog` 데이터베이스에 있고 영화 `tmdb_id`와 인물
`qid`로 이어집니다.

![HorizonDB 데이터 모델과 작성 순서. 왼쪽에 ⓪ 앱 기동, ① 카탈로그 적재(build_catalog.py → catalog.sql), ② 문서 임베딩(embed_catalog.py, bge-m3-ko 1024·OpenAI 1536차원), ③ DiskANN index(20-vector-index.sql), ④ 그래프 재생성(30-graph.sql) 단계가 있고 각각 관계형·벡터·그래프 영역으로 화살표가 이어짐. 관계형 영역에는 public.movies, public.reviews·members, catalog.people, catalog.movie_credits, catalog.movie_genres와 조인 키 설명이 있음. 벡터 영역에는 catalog.movie_docs의 embedding_bge vector(1024)·embedding vector(1536) 열, 두 열 각각의 DiskANN index, 코사인 거리 쿼리가 있음. 그래프 영역에는 Movie·Person·Genre vertex와 DIRECTED·ACTED_IN·IN_GENRE·SIMILAR_TO edge가 개수와 함께 있고, bge 임베딩 최근접 3편 → SIMILAR_TO 파생 화살표가 그래프로 이어짐](../images/horizondb-data-model.svg)

| 단계 | 입력 | 결과 | 검증 포인트 |
|---|---|---|---|
| 앱 기동 | JPA entity | `public.*` | 회원·리뷰와 영화 원본 table 생성 |
| 카탈로그 적재 | Wikidata·Wikipedia | 영화·인물·출연·장르와 검색 문서 | 같은 `tmdb_id` 재실행 시 upsert |
| 모델별 임베딩 | `movie_docs.doc` | `embedding_bge`, `embedding` | 비어 있는 행만 처리하고 모델별 차원 분리 |
| 벡터 index | 두 임베딩 열 | 열마다 DiskANN index | 작은 데이터에서는 planner가 seq scan을 고를 수 있음 |
| graph 생성 | 관계형 행과 bge 최근접 결과 | `movie_graph` | Movie·Person·Genre와 4종 관계 생성 |
| graph 동기화 | 변경 queue | 바뀐 영화와 `SIMILAR_TO` 보정 | 전체 재생성 결과와 label별 hash 비교 |

### 데이터 모델: 원본과 파생 데이터의 경계 { #data-model }

| 모델 | 저장 위치 | 변경 책임 |
|---|---|---|
| 앱 원본 | `public.movies`, `reviews`, `members`, `comments` | 앱의 JPA 쓰기와 카탈로그 upsert |
| 카탈로그 원본 | `catalog.people`, `movie_credits`, `movie_genres`, `movie_docs.doc` | 로더와 새 영화 indexer |
| 벡터 | `movie_docs.embedding_bge vector(1024)`, `embedding vector(1536)` | 문서와 같은 모델로 다시 임베딩 |
| graph | `movie_graph`의 label table | 최초 생성 SQL과 변경 queue 처리 함수 |

앱 role은 `public`에 쓰고 `catalog`와 `movie_graph`는 제한된 경로로만 바꿉니다. graph table을 앱이 직접
수정하지 않고 관리자 소유 함수가 queue를 처리하므로, 원본과 파생 데이터의 책임이 섞이지 않습니다.

### 작성 순서: 적재 → 임베딩 → index → graph { #authoring }

순서는 의존성을 보여 줍니다. graph의 `SIMILAR_TO`는 bge 임베딩을 읽으므로 임베딩과 index 이후에
만들고, 모델을 교체할 때는 `REINDEX`만 하지 않고 문서와 질의를 같은 모델로 다시 임베딩합니다.
두 모델의 차원이 같더라도 서로 다른 모델의 벡터를 섞으면 SQL 오류 없이 잘못된 결과가 나올 수 있어
sample은 모델마다 열과 index를 분리합니다.

실행 파일과 정확한 순서는 sample의 [`db/`](https://github.com/hellices/sample-movielog-horizondb/tree/v2.7.1/db),
[`data/`](https://github.com/hellices/sample-movielog-horizondb/tree/v2.7.1/data),
[배포 hook](https://github.com/hellices/sample-movielog-horizondb/tree/v2.7.1/hooks)을 기준으로 읽습니다.

## 의미 검색 검증: 모델별 벡터와 키워드 RRF { #search }

<span id="hybrid"></span><span id="spelling"></span>

의미 검색은 질의를 선택한 모델로 임베딩하고, 같은 모델의 열에서 코사인 거리 순위를 구합니다. 짧은
영화 제목과 인물 이름이 전체 문서 임베딩에서 밀리지 않도록 제목·인물 키워드 순위를 RRF로 합칩니다.

| 확인 항목 | 기대 결과 |
|---|---|
| 서술형 질의 | 제목에 같은 단어가 없어도 줄거리 의미가 가까운 영화가 나타남 |
| 짧은 제목·인물 질의 | 키워드 순위가 정확한 제목과 관련 작품을 보완 |
| `model=bge|openai` | 요청 모델에 맞는 열·차원·index만 선택 |
| 484행 실행 계획 | index가 있어도 기본 planner가 seq scan을 선택할 수 있음 |
| 화면 점수 | RRF 순서와 별개로 해당 모델의 코사인 유사도 표시 |

MovieLog에서는 「듄」과 「드니 빌뇌브」 같은 짧은 질의에서 벡터 상위 50편과 키워드 상위 50편을
RRF로 결합해 관련 작품을 보완했습니다. 「드늬 뷜베브」 같은 한글 표기 오류는 인물·제목 사전과 자모
편집 거리로 먼저 고칩니다. 구체적인 구현은 고정 commit의
[`discover` package](https://github.com/hellices/sample-movielog-horizondb/tree/eedbe2c47c779730151fce2947157e87f4925270/src/main/java/com/example/springsample/discover)와
테스트를 함께 읽습니다.

## 그래프 동기화: 변경 queue와 파생 데이터 보정 { #graph-sync }

최초 graph는 관계형 원본 전체에서 만들지만, 이후에는 trigger가 영향을 받은 영화를 queue에 넣고 앱이
주기적으로 그 영화의 노드와 관계를 반영합니다. `SIMILAR_TO`는 새 영화 하나가 기존 영화의 최근접 3편도
바꿀 수 있어 전체 쌍을 다시 계산해 차이만 적용합니다.

| 경로 | 역할 | 검증 결과 |
|---|---|---|
| 변경 trigger | graph에 영향을 주는 영화 ID를 queue에 upsert | 무관한 열 변경은 제외 |
| queue 처리 | 해당 영화의 Movie·Person·Genre 관계 갱신 | 한 transaction으로 적용 |
| `SIMILAR_TO` reconcile | 모든 영화의 최근접 3편과 graph 비교 | 다른 쌍만 삭제·생성 |
| 1시간 정합성 점검 | 원본과 graph 한쪽에만 있는 행과 관계 복구 | 강제 손상 뒤 전체 재생성과 동일 |

2026-11-14 실습에서는 482편 전체 queue 처리가 9.3초였고, 영화·인물 이름 변경과 손상된 node·edge를
반영한 뒤 7개 label의 속성 hash가 전체 재생성 결과와 같았습니다. SQL과 동기화 함수는
[`db/30-graph.sql`](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/db/30-graph.sql)과
[`db/40-graph-sync.sql`](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/db/40-graph-sync.sql)에서 확인합니다.

## 앱 검증: 검색 결과에서 관계 탐색까지 { #app-verification }

<span id="app-access"></span>

브라우저의 한 화면은 서버 검색과 graph API 두 경로를 조합합니다. 서버가 질의를 임베딩해 결과 영화
목록을 만들고, 브라우저는 그 영화 ID로 graph JSON을 받아 Cytoscape.js에 그립니다.

![MovieLog 앱의 HorizonDB 접근 sequence. ① 의미 검색에서 브라우저가 GET /discover?q=를 보내면 MovieLog 앱의 BgeEmbeddingClient가 클러스터 내부의 vLLM에 POST /v1/embeddings(bge-m3-ko)를 요청해 float[1024]를 받고, VectorSearchRepository가 JdbcClient로 movie_docs와 movies를 조인해 <=> 순위와 문서 머리 키워드 순위를 RRF로 합친 영화 12편과 코사인 유사도를 받아 HTML 결과 목록과 그래프 URL을 돌려줌. ② 관계 그래프에서 graph.js가 GET /api/discover/graph?ids=를 보내면 MovieGraphRepository가 JdbcTemplate으로 UNWIND [ids] AS t MATCH (a:Movie {tmdb_id: t})-[r]-(b) Cypher를 실행해 vertex·edge 행을 받고 JSON nodes·edges를 돌려줘 Cytoscape.js가 그림. ③ 다른 화면에서 리뷰·회원·영화는 Spring Data JPA가 public.*에 Hibernate SQL을 보내고, 상세 화면의 비슷한 영화는 임베딩 호출 없이 embedding_bge와 <=>로 6편을 조회함](../images/horizondb-app-access.svg)

| 사용자 동작 | HorizonDB 경로 |
|---|---|
| 의미 검색 | 질의 임베딩 → `movie_docs`와 `movies`의 벡터·키워드 RRF |
| 결과 graph | 검색 결과 ID → `cypher()`의 Movie 이웃 조회 |
| 인물 펼치기 | Person `qid` → 감독·출연 영화 최대 30편 |
| 비슷한 영화 | 저장된 영화 벡터끼리 거리 비교, 새 임베딩 호출 없음 |
| 리뷰·회원 | 같은 연결 pool의 일반 JPA 관계형 경로 |

### 그래프 화면: 포스터 · 관계 필터 · 인물 펼치기 { #graph-ui }

![의미 검색 결과 그래프에서 티모시 샬라메를 펼친 화면. 티모시 샬라메 노드가 강조되고 듄(2021), 듄: 파트 2(2024)와 펼치기로 더해진 웡카(2023), 인터스텔라(2014), 콜 미 바이 유어 네임(2017) 포스터 노드가 주황 선으로 이어지며, 나머지 노드는 흐리게 보임. 아래 정보 패널에 '그래프의 연결된 영화 5편'과 '3편을 더했습니다'가 표시됨](../images/movie-graph.png)

화면은 영화 node를 포스터로 표시하고 감독·출연, 장르, `SIMILAR_TO` 관계를 필터링합니다. 인물 node를
펼치면 현재 graph에 없던 다른 작품을 추가합니다. 그래프를 그리지 못해도 같은 JSON으로 만든 관계 목록을
DOM에 제공해 탐색 결과를 잃지 않습니다.

## 관측: 임베딩 · 검색 · 그래프 단계 분리 { #observe }

MovieLog는 `movielog.discover.embedding`, `search`, `similar`, `graph` Timer를 모델 tag와 함께 기록합니다.
HorizonDB SQL과 임베딩 HTTP 호출은 Application Insights dependency로도 수집됩니다. 따라서 전체 응답
시간만 보지 않고 임베딩 모델, 벡터 검색, AGE 조회 중 어디에서 시간이 쓰였는지 분리합니다.

![MovieLog HorizonDB 의미 검색 대시보드. 의미 검색 4.68K, 평균 질의 임베딩 93.8 ms, 평균 벡터 검색 5.28 ms, 평균 그래프 조회 4.45 ms, 실패 0 stat과 단계별 지연·호출 수, HorizonDB SQL 호출 수와 평균 시간, Azure OpenAI 임베딩 호출 시간, 쿼리 유형별 시간 표, 엔드포인트별 p95와 실패율이 보임](../images/grafana-discover-dashboard.png)

2026-11-13 Azure OpenAI 단일 모델 운영 구간에서는 임베딩 평균 93.8 ms, 벡터 검색 5.28 ms, graph 조회
4.45 ms가 기록됐습니다. [topic entry의 두 모델 측정](../index.md#message)은 이후 40분 구간이므로 날짜와
조건을 섞어 비교하지 않습니다.

## 공개 구성: 선택 기능과 보안 경계 { #public-access }

`APP_HOST`가 없으면 sample은 공개 진입점을 만들지 않고 port-forward로 확인합니다. 공개 구성을 선택하면
Application Gateway for Containers, cert-manager 인증서와 HTTPS redirect, Microsoft Entra ID 로그인을
사용합니다. 앱은 로그인·회원가입을 제외한 화면과 API에 인증을 요구하고 임베딩 호출 전에 요청률을
제한합니다.

DNS, 인증서, NSG, Key Vault와 Entra app은 실행 환경에 직접 영향을 주는 절차이므로 이 문서에서 명령을
복제하지 않습니다. [고정 버전 배포 절차](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)의
공개 구성과 검증·정리 순서를 그대로 따릅니다.

## 완료 기준: 기능 · 데이터 · 관측 · 정리 { #completion }

| 영역 | 완료 확인 |
|---|---|
| 데이터 | 관계형 영화 수, 모델별 non-null 임베딩 수와 graph label 수가 일관됨 |
| 검색 | 서술형·제목·인물 질의와 두 모델 경로가 응답함 |
| graph | 결과 graph, 인물 펼치기와 `SIMILAR_TO`가 표시됨 |
| 동기화 | 새 영화 또는 변경 queue가 처리되고 정합성 점검이 통과함 |
| 관측 | 임베딩·검색·graph Timer와 dependency가 구분됨 |
| 보안 | 공개 구성을 썼다면 HTTPS, 인증, 요청률 제한을 확인함 |
| 정리 | sample 배포 문서에 따라 유료 리소스와 외부 DNS·Entra 구성을 제거함 |

## 정리: sample 배포 문서의 단일 절차 { #cleanup }

정확한 정리 명령과 resource group 밖의 DNS·Entra app 처리 순서는
[Azure 배포 절차 (v2.7.1)](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)를
따릅니다. 이 문서는 정리 명령을 별도로 유지하지 않으므로 sample 버전이 바뀌어도 실행 절차가 둘로
갈라지지 않습니다.
