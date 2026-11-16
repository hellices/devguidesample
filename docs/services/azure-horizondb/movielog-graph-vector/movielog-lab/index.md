---
title: "MovieLog 실습: AKS·HorizonDB 의미 검색과 관계 그래프 앱 구현"
description: Azure Developer CLI 한 번으로 Azure HorizonDB, AKS(GPU spot 노드), Azure OpenAI, Key Vault, Managed Grafana를 만들고 MovieLog 앱을 배포해 영화 카탈로그를 bge-m3-ko 임베딩·DiskANN 의미 검색과 Apache AGE 관계 그래프로 보여 주는 실습입니다. 데이터 모델과 작성 순서, trigger 기반 그래프 동기화, 앱의 JPA·JdbcClient·JdbcTemplate 접근 경로, RRF 키워드 결합과 철자 교정, 그래프 화면, HTTPS·Entra ID 공개 구성을 실측값과 함께 정리합니다.
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

# MovieLog 실습: AKS·HorizonDB 의미 검색과 관계 그래프 앱 구현

## 실습 범위: `azd up` 한 번으로 재현하는 MovieLog { #scope }

[topic 개요](../index.md)의 결과를 직접 재현하는 실습입니다. 샘플 코드 레포
[`hellices/sample-movielog-horizondb`](https://github.com/hellices/sample-movielog-horizondb)의 `v2.7.1` 릴리스를 받아 `azd up`을 실행하면 Bicep이 Azure 리소스를 만들고,
hook이 Bicep 형식이 없는 HorizonDB(미리 보기)와 DB·Kubernetes 구성·카탈로그를 준비합니다. 2026-11-15 Korea Central의
새 구독 환경에서 약 1시간이 걸렸고(HorizonDB cluster·pool 약 25분, 카탈로그 적재와 두 모델 임베딩 약 20분), GPU를
포함한 유료 자원을 쓰므로 끝나면 `azd down --purge`로 지웁니다.

```bash
git clone --branch v2.7.1 https://github.com/hellices/sample-movielog-horizondb.git && cd sample-movielog-horizondb
azd auth login && az login
azd env new movielog --location koreacentral
azd up
```

`APP_HOST`를 넣지 않으면 공개 진입점을 만들지 않습니다. 앱 Service는 클러스터 내부용(ClusterIP)이라
`kubectl port-forward`로만 접속합니다. 공개 HTTPS와 Microsoft Entra ID 로그인이 필요하면 `azd up` 전에 직접 관리하는
도메인의 호스트명을 넣습니다. Let's Encrypt HTTP-01 검증이 통과하려면 그 호스트명의 CNAME이 Gateway 주소를 가리켜야
합니다. 이 경우 Application Gateway for Containers에 HTTPS listener를 열고, HTTP listener는 앱으로 전달하지 않고
HTTPS로 301 redirect만 합니다([공개 구성](#public-access)).

```bash
azd env set APP_HOST <your-host-name>   # a host name in a DNS zone you manage
```

| 단계 | 만드는 것 |
|---|---|
| Bicep(`infra/`) | AKS(GPU spot 노드 풀 포함), ACR, Azure OpenAI(키 인증 끔), Key Vault(공용 접근 끔), Application Insights, Managed Grafana, managed identity와 역할 |
| `postprovision` hook | HorizonDB parameter group·cluster·pool·관리자·방화벽, `movielog` DB와 schema, Key Vault private endpoint와 secret, Entra ID 앱 등록, namespace·instrumentation |
| `postdeploy` hook | GHCR 릴리스 이미지 `az acr import`, vLLM(bge-m3-ko)과 앱 배포, 카탈로그 적재·두 모델 임베딩·DiskANN index·AGE 그래프, Grafana dashboard, HTTPS |

환경 값, 단계별 동작, 실습 중 고친 문제는 코드 레포의
[배포 절차](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/docs/deploy.md)에 있습니다.

## 아키텍처: AGFC → AKS MovieLog → HorizonDB { #architecture }

요청은 커스텀 도메인의 HTTPS로 Application Gateway for Containers(AGFC)를 거쳐 AKS의 MovieLog Pod로 들어오고,
앱은 같은 클러스터의 GPU spot 노드에서 vLLM이 서빙하는 bge-m3-ko로 질의를 임베딩한 뒤 HorizonDB에 SQL과 openCypher를 보냅니다.
카탈로그와 그래프는 배치 로더가 한 번 만들고, 텔레메트리는 Application Insights를 거쳐
Managed Grafana에서 봅니다.

![MovieLog on Azure HorizonDB 아키텍처. 브라우저가 HTTPS로 App Gateway for Containers에 들어오고(cert-manager가 발급한 Let's Encrypt 인증서), AKS 관리형 VNet 안의 MovieLog 앱이 요청마다 같은 VNet의 GPU spot 노드에서 vLLM이 서빙하는 bge-m3-ko(model=bge) 또는 클러스터 밖 Azure OpenAI text-embedding-3-large(model=openai)에 질의 임베딩을 요청한 뒤 Azure HorizonDB에 SQL과 Cypher를 보냄. HorizonDB 안에는 관계형 테이블, pgvector와 DiskANN(1024·1536차원), Apache AGE movie_graph가 있음. 카탈로그 로더는 Wikidata와 Wikipedia 데이터를 HorizonDB에 적재하고, 문서를 Azure OpenAI로 직접, bge-m3-ko는 port-forward로 vLLM에 보내 임베딩함. MovieLog의 텔레메트리는 Application Insights로, Application Insights는 KQL로 Managed Grafana에 연결됨](../images/architecture.svg)

| 구성 요소 | 역할 | 구성 |
|---|---|---|
| App Gateway for Containers | 공개 진입점, TLS 종료 | AKS add-on의 ALB Controller, 커스텀 도메인의 HTTP·HTTPS listener, HTTP→HTTPS 301 redirect, 로그인 session을 한 Pod에 묶는 `RoutePolicy` managed cookie |
| cert-manager | 인증서 발급·갱신 | Let's Encrypt `ClusterIssuer`, Gateway API HTTP-01 challenge, `Certificate`가 만든 TLS secret을 HTTPS listener가 참조 |
| Microsoft Entra ID | 로그인 | 아이디·비밀번호 로그인 옆의 OpenID Connect 로그인(single-tenant 앱 등록). 첫 로그인 때 ID token의 `tid`·`oid`로 회원을 만듦 |
| Azure Key Vault | 앱 비밀값 | TMDB·OMDb 키와 Entra ID client secret. AKS Secrets Store CSI driver가 앱 workload identity로 private endpoint를 거쳐 읽음 |
| MovieLog 앱 | 의미 검색·그래프 API와 화면 | Spring Boot 4.1, Pod 2개. 요청의 `model`에 따라 클러스터 내부 vLLM(기본값) 또는 Azure OpenAI(workload identity)를 호출 |
| Azure HorizonDB | 관계형·벡터·그래프 저장과 조회 | 아래 [리소스 구조](#resource-model), 확장은 [topic 개요](../index.md#extensions) |
| vLLM · GPU spot 노드 | 임베딩 모델 서빙(`model=bge`, 앱 기본값) | `dragonkue/BGE-m3-ko`(1,024차원, commit 고정), vLLM 0.32 OpenAI 호환 `/v1/embeddings`, `Standard_NC4as_T4_v3` spot 1대 |
| Azure OpenAI | 임베딩 모델(`model=openai`) | `text-embedding-3-large`, `dimensions=1536`, key 인증 없이 Entra token |
| 카탈로그 로더 | 데이터셋 생성과 적재 | 표준 라이브러리 Python 스크립트, `psql` |
| Application Insights · Managed Grafana | 관측 | AKS 자동 계측(Java agent 3.7.10), 모델별 `movielog.discover.*` Timer, HorizonDB·임베딩 dependency |

### HorizonDB 리소스 구조: cluster · pool · parameter group { #resource-model }

2026-11-13 Azure CLI `horizondb` 확장 1.0.0b9(API `2026-10-01-preview`)에서는 리소스가 다음처럼
나뉘었습니다. Learn quickstart는 `az horizondb create` 한 번으로 관리자와 vCore까지 지정하는
이전 형식을 보여 주므로, 실습은 새 API 구조를 따랐습니다.

| 리소스 | 이 실습의 값 | 메모 |
|---|---|---|
| cluster | PostgreSQL 17, public access | 관리자 계정은 cluster 생성 인자가 아니라 `authentications/passwordMethod` 리소스로 설정했습니다. |
| pool | Intel 1세대, 4 vCores, node 1개, HA 없음 | pool 생성 시에는 기본 parameter group만 받아, 사용자 parameter group은 생성 후 연결했습니다. |
| parameter group | `azure.extensions=vector,pg_diskann,age`, `shared_preload_libraries=age` | 확장은 parameter group으로 허용하고, 공유 메모리를 쓰는 AGE는 preload가 필요합니다. 연결하면 pool이 재시작합니다. |
| firewall rule | 운영자 IP, AKS outbound IP | pool 하위 리소스입니다. |

### HorizonDB 데이터 모델: 관계형 원본 → 벡터 → 그래프 { #data-model }

관계형 테이블이 원본이고, 벡터와 그래프는 같은 데이터베이스 `movielog` 안에서 그 원본에
붙거나 원본에서 다시 만드는 데이터입니다. 세 모델은 별도 저장소 없이 `tmdb_id`(영화)와
`qid`(인물) 두 키로 이어집니다. 벡터 열은 문서가 바뀌면 다시 임베딩하고, 그래프는 trigger와 queue를 거쳐
반영합니다([그래프 동기화](#graph-sync)).

![HorizonDB 데이터 모델과 작성 순서. 왼쪽에 ⓪ 앱 기동, ① 카탈로그 적재(build_catalog.py → catalog.sql), ② 문서 임베딩(embed_catalog.py, bge-m3-ko 1024·OpenAI 1536차원), ③ DiskANN index(20-vector-index.sql), ④ 그래프 재생성(30-graph.sql) 단계가 있고 각각 관계형·벡터·그래프 영역으로 화살표가 이어짐. 관계형 영역에는 public.movies, public.reviews·members, catalog.people, catalog.movie_credits, catalog.movie_genres와 조인 키 설명이 있음. 벡터 영역에는 catalog.movie_docs의 embedding_bge vector(1024)·embedding vector(1536) 열, 두 열 각각의 DiskANN index, 코사인 거리 쿼리가 있음. 그래프 영역에는 Movie·Person·Genre vertex와 DIRECTED·ACTED_IN·IN_GENRE·SIMILAR_TO edge가 개수와 함께 있고, bge 임베딩 최근접 3편 → SIMILAR_TO 파생 화살표가 그래프로 이어짐](../images/horizondb-data-model.svg)

| 모델 | 저장 위치 | 성격 | 연결 키 | 쓰는 주체 |
|---|---|---|---|---|
| 관계형 | `public.movies`, `public.reviews`·`members`·`comments` | 원본. 앱의 리뷰·회원은 요청마다 바뀜 | `movies.tmdb_id`(UNIQUE), `reviews.movie_id → movies.id` | 앱(Hibernate·JPA), 로더(`movies` upsert) |
| 관계형 | `catalog.people`, `catalog.movie_credits`, `catalog.movie_genres` | 원본. Wikidata 구조 | `tmdb_id`, `qid`(`person_qid → people.qid`) | 로더, 앱(`CatalogIndexer`: TMDB credits·장르) |
| 벡터 | `catalog.movie_docs.embedding_bge vector(1024)`(`model=bge`), `embedding vector(1536)`(`model=openai`) + 열마다 DiskANN index | 원본 행에 붙은 열. 문서가 바뀌면 두 열을 비우고 다시 임베딩 | `movie_docs.tmdb_id`(PK) | 로더, 앱(`CatalogIndexer`: 카탈로그 적재 뒤 TMDB에서 가져온 영화) |
| 그래프 | `movie_graph`의 label별 테이블(`"Movie"`, `"ACTED_IN"` 등) | 파생. 관계형 행과 임베딩에서 다시 생성 | vertex 속성 `tmdb_id`, `qid` | `30-graph.sql`(최초 생성), `catalog.process_graph_queue`(변경분) |

- **키로 잇는 이유** — `catalog.*` 테이블은 `public.movies`에 외래 키를 두지 않고 `tmdb_id`로
  조인합니다. 앱이 Hibernate로 `public.*`를 만드는 시점과 로더가 `catalog.*`를 채우는 시점이
  달라도 서로를 막지 않습니다.
- **그래프도 테이블** — 2026-11-13 실습 DB에서 AGE는 graph 이름과 같은 schema `movie_graph`에
  label마다 일반 테이블을 만들었습니다. 그래서 vertex 속성 `tmdb_id`로 Cypher 결과를 다시
  관계형 행과 맞출 수 있고, GIN·btree index와 `GRANT`도 일반 테이블처럼 적용합니다.
- **권한 경계** — 앱 role `movielog`는 `public`에 쓰고, `catalog`와 `movie_graph`에는
  `SELECT`를 받습니다. 새 영화를 위해 `catalog`의 `movie_docs`·`people`·`movie_credits`·
  `movie_genres`에 `INSERT`만 더 받고, 그래프 테이블과 변경 queue에는 직접 쓰지 못합니다. 그래프는
  관리자가 소유한 `SECURITY DEFINER` 함수 `catalog.process_graph_queue`·`enqueue_graph_drift`를 통해서만
  바뀝니다.

### 작성 순서: 적재 → 임베딩 → index → 그래프 { #authoring }

데이터는 앞 단계의 결과를 다음 단계가 읽는 순서로 만들며, 모든 단계는 중복 없이 다시 실행할 수
있습니다. 영화 약 480편 기준 소요 시간은 실습에서 측정한 값입니다.

| 단계 | 스크립트 | 읽는 것 | 쓰는 것 | 재실행 동작 | 소요 시간 |
|---|---|---|---|---|---|
| ⓪ 앱 기동 | Hibernate `ddl-auto=update` | JPA entity | `public.*` 테이블 | 없는 테이블·열만 추가 | 앱 시작 시 |
| ① 카탈로그 적재 | `build_catalog.py` → `catalog.sql` | Wikidata SPARQL, Wikipedia 요약 API | `public.movies`, `catalog.*`, `movie_docs.doc` | `ON CONFLICT` upsert. `doc`이 바뀐 행만 두 임베딩 열을 `NULL`로 비움 | 생성 8–11분, 적재 약 3.5분 |
| ② 문서 임베딩 | `embed_catalog.py --model bge`, `--model openai` | 모델 열이 `NULL`인 `doc` | `embedding_bge`, `embedding` | 비어 있는 행만 처리. `--all`은 전체 재임베딩. 임베딩한 `doc`이 그사이 바뀐 행은 비워 둠 | 479건 bge 약 1.5분(T4), OpenAI 약 3.5분 |
| ③ 벡터 index | `20-vector-index.sql` | `embedding_bge`, `embedding` | 열마다 DiskANN index | `IF NOT EXISTS`. 모델을 바꾸면 아래 순서를 따름 | 수 초 |
| ④ 그래프 재생성 | `30-graph.sql` | `movies`, `catalog.*`, `embedding_bge` | `movie_graph` 전체 | graph를 지우고 다시 생성. 최초 1회 | 약 6–8초 |
| ⑤ 그래프 동기화 설치 | `40-graph-sync.sql` | — | 변경 queue, trigger, 동기화 함수 | `CREATE OR REPLACE`. 이후 그래프는 변경분만 반영 | 수 초 |

임베딩 모델을 바꿀 때는 `REINDEX`만으로 저장된 벡터가 바뀌지 않습니다. 같은 차원의 모델끼리는(예:
`text-embedding-3-small`과 `-large`를 모두 1,536차원으로 실행) 문서와 질의를 서로 다른 모델로 임베딩해도 SQL
오류 없이 엉뚱한 결과가 나옵니다. 그래서 이 실습은 모델마다 열을 따로 두고, 앱은 열 이름과 `vector(n)` 차원을
요청 값이 아닌 모델 목록(`EmbeddingModel`)에서만 고릅니다. 기존 열의 모델을 바꾸려면 ②를 `--all`로 실행해 전체
문서를 다시 임베딩하고 앱의 질의 모델을 같은 값으로 맞춘 뒤 `REINDEX`합니다. `SIMILAR_TO`는 1시간마다 도는
[정합성 점검](#graph-sync)이 새 임베딩 기준으로 다시 맞춥니다.

Wikidata와 Wikipedia에는 포스터가 없으므로 ① 다음에 `enrich_tmdb.py` → `tmdb.sql`로 TMDB 상세
API의 포스터 경로·상영 시간·IMDb id를 `public.movies`의 빈 열에만 채웁니다. 제목·요약·임베딩·그래프에는
영향이 없으며 478편 기준 약 2분 걸렸습니다.

①–④는 카탈로그에 있는 영화만 다룹니다. 회원이 영화 검색으로 카탈로그 밖의 영화를 처음 열면
앱은 TMDB 상세를 `public.movies`에만 저장하므로, 그 영화는 문서·임베딩이 없어 의미 검색에
나오지 않습니다. 2026-11-14 실습에서 「듄: 파트 2」에 리뷰를 쓴 뒤 「듄」, 「드니 빌뇌브」로
검색해도 나오지 않은 원인이 이것이었습니다. 앱의 `CatalogIndexer`가 30초마다 문서가 없는 영화를
찾아 영화 한 편을 한 transaction으로 처리합니다.

1. TMDB credits에서 감독과 출연 6명을 받고, 인물마다 TMDB `external_ids`의 Wikidata id를 받습니다.
2. ①과 같은 형식의 문서를 만들어 설정된 모든 모델로 임베딩하고 `catalog.movie_docs`에 넣습니다.
3. 인물·출연·장르를 `catalog.people`·`movie_credits`·`movie_genres`에 넣습니다. 인물 키는
   Wikidata id라서 표기가 달라도(TMDB 「조쉬 브롤린」, Wikidata 「조시 브롤린」) 카탈로그의 같은
   인물로 이어집니다. Wikidata id가 없으면 `tmdb:<person id>`를 씁니다.
4. 이 행들이 바뀌면 아래 trigger가 영화를 그래프 변경 queue에 넣고, 색인 직후 앱이 queue를 반영합니다.

여러 Pod 중 PostgreSQL advisory lock을 잡은 하나만 실행합니다. 2026-11-14 실습에서 「웡카」를 처음 연 뒤
14초 만에 색인과 그래프 반영이 끝났고, 「티모시 샬라메」·「휴 그랜트」 노드와 「찰리와 초콜릿 공장」
`SIMILAR_TO`로 연결됐습니다.

### 그래프 동기화: trigger 변경 queue와 주기 반영 { #graph-sync }

그래프는 관계형 행에서 만든 파생 데이터라서, 원본이 바뀔 때마다 ④로 전체를 다시 만들면 그래프를
지운 6–8초 동안 앱이 빈 그래프를 읽고, 관리자 비밀번호를 가진 작업이 cluster 안에 있어야 합니다.
그래서 HorizonDB trigger가 바뀐 영화를 queue에 기록하고, 앱이 그 영화만 반영하는 방식으로 바꿨습니다.
[`db/40-graph-sync.sql`](https://github.com/hellices/sample-movielog-horizondb/blob/v2.7.1/db/40-graph-sync.sql)이 queue, trigger, 함수를 만듭니다.

| 단계 | 구성 요소 | 동작 |
|---|---|---|
| 변경 감지 | `public.movies`, `catalog.movie_docs`·`movie_credits`·`movie_genres`·`people` trigger | 그래프에 영향을 주는 열이 바뀐 행의 `tmdb_id`를 `catalog.graph_queue`에 upsert합니다. 인물 이름이 바뀌면 그 인물의 영화를 모두 넣습니다. TMDB 갱신처럼 제목·개봉일이 그대로인 수정은 넣지 않습니다. |
| 반영(30초) | 앱 `MovieGraphSync` → `catalog.process_graph_queue()` | 그래프 advisory lock을 잡고 queue에서 꺼낸 영화의 `Movie` 노드와 `DIRECTED`·`ACTED_IN`·`IN_GENRE`를 ④의 규칙으로 다시 만든 뒤, `SIMILAR_TO` 전체를 bge 임베딩 최근접 3편 규칙과 비교해 다른 쌍만 지우고 만듭니다. 한 transaction이라 앱은 반쯤 바뀐 그래프를 읽지 않습니다. |
| 정합성 점검(1시간) | 앱 → `catalog.enqueue_graph_drift()` + 강제 reconcile | 관계형과 그래프 한쪽에만 있는 영화를 queue에 넣고, queue가 비어 있어도 `SIMILAR_TO`를 맞춥니다. 실패한 실행이나 그래프를 직접 고친 흔적을 정리합니다. |
| 전체 재생성 | `30-graph.sql` | 같은 lock을 잡아 반영 작업과 겹치지 않고, 시작 전에 쌓인 queue를 비웁니다. 최초 생성 때만 씁니다. |

- **`SIMILAR_TO` 전체 비교** — 영화 한 편이 바뀌어도 다른 영화의 최근접 3편이 바뀔 수 있습니다.
  처음에는 바뀐 영화와 닿는 쌍만 다시 만들었는데, 새 영화 때문에 다른 영화의 최근접 3편에서 밀려난
  기존 관계가 남았습니다. 그래서 반영할 때마다 모든 영화의 최근접 3편을 다시 계산해 그래프와
  비교합니다. 482편에서 약 1.3초 걸립니다.
- **Cypher 제약** — 지울 edge를 `WHERE id(r) IN [...]`로 고르면 id가 두 개 이상일 때 AGE가
  `not a common type: 17175`(agtype)로 실패했습니다. 양 끝 `Movie`의 `tmdb_id`로 `MATCH`해 지웁니다.
- **실행 위치** — HorizonDB의 `pg_available_extensions`에는 `pg_cron`이 있지만 2026-11-14 실습 DB의
  `shared_preload_libraries`에는 없어서, 쓰려면 server parameter 변경과 재시작이 필요했습니다. 이미
  workload identity와 advisory lock을 쓰는 앱의 scheduler에서 실행합니다. 실행 시간과 결과는
  `movielog.discover.graph.sync` Timer(`mode`=`queue`·`drift`, `outcome`=`applied`·`idle`·`skipped`·`error`)로 남깁니다.

2026-11-14 실습 DB에서 다음 경우마다 그래프를 label별 속성 hash로 비교했고, 모두 ④로 전체를 다시 만든
결과와 같았습니다.

| 경우 | 결과 |
|---|---|
| 482편 전체를 queue에 넣고 반영 | 9.3초, 7개 label 모두 같음 |
| 앱에서 카탈로그 밖 영화 2편(「패스트 라이브즈」, 「퓨리오사」)을 처음 열고 색인·반영 | 다른 영화에서 밀려난 `SIMILAR_TO`까지 정리되어 같음 |
| 영화 제목과 인물 이름 변경 | 다음 반영에서 노드 속성이 바뀌고, 인물 노드는 1개로 유지 |
| `Movie` 노드 삭제, 그래프에만 있는 영화, 중복·방향 반대·점수가 다른·근거 없는 `SIMILAR_TO` | 정합성 점검 한 번(약 1.3초)으로 복구 |

④는 노드를 먼저 만들고 label 테이블에 GIN index를 건 뒤 관계를 만듭니다. Cypher 문자열에
값을 직접 넣어야 하므로 행을 Cypher map 문자열로 바꿔 200개씩 `UNWIND`합니다.

```sql
-- 30-graph.sql 발췌: 관계형 행 → ACTED_IN 관계
SELECT pg_temp.unwind(
  array_agg(format('{p: %s, m: %s, position: %s}', pg_temp.cy(c.person_qid), c.tmdb_id, c.position)),
  'MATCH (p:Person {qid: e.p}), (m:Movie {tmdb_id: e.m}) CREATE (p)-[:ACTED_IN {position: e.position}]->(m)')
FROM catalog.movie_credits c JOIN public.movies USING (tmdb_id)
WHERE c.role = 'actor';

-- bge 임베딩 → SIMILAR_TO: 영화마다 코사인 거리가 가장 가까운 3편, 서로를 고른 쌍은 하나로 합침
WITH knn AS (
  SELECT a.tmdb_id AS a, b.tmdb_id AS b, 1 - (a.embedding_bge <=> b.embedding_bge) AS score
  FROM catalog.movie_docs a
  CROSS JOIN LATERAL (
    SELECT tmdb_id, embedding_bge FROM catalog.movie_docs b
    WHERE b.tmdb_id <> a.tmdb_id AND b.embedding_bge IS NOT NULL
    ORDER BY b.embedding_bge <=> a.embedding_bge LIMIT 3) b
  WHERE a.embedding_bge IS NOT NULL)
SELECT DISTINCT ON (least(a, b), greatest(a, b)) least(a, b) AS a, greatest(a, b) AS b, score
FROM knn ORDER BY least(a, b), greatest(a, b), score DESC;
```

### 앱 접근 경로: JPA · JdbcClient · JdbcTemplate { #app-access }

앱은 커넥션 풀 하나(HikariCP, 앱 role `movielog`)로 세 모델에 접근하며, 모델마다 다른
Spring 데이터 접근 방식을 씁니다. 연결을 만들 때 `SET search_path = public, ag_catalog`를
실행해 JPA는 `public`을 그대로 쓰고 AGE의 `cypher()` 함수도 찾게 합니다.

![MovieLog 앱의 HorizonDB 접근 sequence. ① 의미 검색에서 브라우저가 GET /discover?q=를 보내면 MovieLog 앱의 BgeEmbeddingClient가 클러스터 내부의 vLLM에 POST /v1/embeddings(bge-m3-ko)를 요청해 float[1024]를 받고, VectorSearchRepository가 JdbcClient로 movie_docs와 movies를 조인해 <=> 순위와 문서 머리 키워드 순위를 RRF로 합친 영화 12편과 코사인 유사도를 받아 HTML 결과 목록과 그래프 URL을 돌려줌. ② 관계 그래프에서 graph.js가 GET /api/discover/graph?ids=를 보내면 MovieGraphRepository가 JdbcTemplate으로 UNWIND ids MATCH (a:Movie {tmdb_id})-[r]-(b) Cypher를 실행해 vertex·edge 행을 받고 JSON nodes·edges를 돌려줘 Cytoscape.js가 그림. ③ 다른 화면에서 리뷰·회원·영화는 Spring Data JPA가 public.*에 Hibernate SQL을 보내고, 상세 화면의 비슷한 영화는 임베딩 호출 없이 embedding_bge와 <=>로 6편을 조회함](../images/horizondb-app-access.svg)

| 기능 | 앱 클래스 | HorizonDB 접근 | 대상 |
|---|---|---|---|
| 리뷰·댓글·회원·영화 상세 | `MovieRepository`, `ReviewRepository` 등 Spring Data JPA | Hibernate SQL | `public.*` |
| 의미 검색 `/discover` | `QueryCorrector` → `EmbeddingModels`(`BgeEmbeddingClient` 또는 `EmbeddingClient`) → `VectorSearchRepository`(`JdbcClient`) | 철자 교정 뒤 질의 벡터 `<=>` 순위와 문서 머리 키워드 순위를 RRF로 결합 | `movie_docs` ⋈ `movies` |
| 새 영화 색인(30초 주기) | `CatalogIndexer` → `TmdbCreditsClient`, `EmbeddingModels`, `CatalogIndexRepository` | advisory lock 뒤 `INSERT ... ON CONFLICT DO NOTHING` | `movie_docs`, `people`·`movie_credits`·`movie_genres` |
| 그래프 동기화(30초, 점검 1시간) | `MovieGraphSync` → `GraphSyncRepository` | `SELECT catalog.process_graph_queue(:limit, :reconcile)`, `catalog.enqueue_graph_drift()` | `graph_queue`, `movie_graph` |
| 비슷한 영화(상세 화면) | `VectorSearchRepository.similar` | 저장된 영화 벡터끼리 `<=>`. 임베딩 호출 없음 | `movie_docs` |
| 관계 그래프 `/api/discover/graph` | `MovieGraphRepository`(`JdbcTemplate`) | `ag_catalog.cypher()` 안의 openCypher | `movie_graph` |

```java
// VectorSearchRepository: 열과 차원은 EmbeddingModel enum에서만 오고(bge → embedding_bge, vector(1024)),
// 질의 벡터는 bind parameter로 전달(키워드 결합 부분은 생략)
jdbc.sql("""
    SELECT d.tmdb_id, m.title, ..., 1 - (d.%1$s <=> CAST(:v AS vector(%2$d))) AS score
    FROM catalog.movie_docs d JOIN public.movies m ON m.tmdb_id = d.tmdb_id
    WHERE d.%1$s IS NOT NULL
    ORDER BY d.%1$s <=> CAST(:v AS vector(%2$d))
    LIMIT :limit""".formatted(model.column(), model.dimensions()))
  .param("v", toLiteral(embedding)).param("limit", limit)
  .query(VectorSearchRepository::hit).list();

// MovieGraphRepository: 검증된 숫자 tmdb_id만 Cypher 문자열에 넣음
jdbc.query("""
    SELECT a_id::text AS a_id, ... FROM ag_catalog.cypher('movie_graph', $cy$
      UNWIND [%s] AS t MATCH (a:Movie {tmdb_id: t})-[r]-(b) RETURN ...
    $cy$) AS (a_id ag_catalog.agtype, ...)""".formatted(ids), MovieGraphRepository::row);
```

- **의미 검색 화면은 두 번 요청합니다.** 서버가 벡터 검색으로 결과 목록을 렌더링하고, 그 결과의
  `tmdb_id` 목록을 그래프 API URL로 내려 줍니다. 브라우저는 그 URL로 그래프 JSON을 받아 그립니다.
- **결과 변환** — Cypher 결과는 `agtype`이라 SQL에서 `::text`로 바꿔 받고, 앱이 vertex·edge
  속성을 Cytoscape.js 형식(`nodes`, `edges`)으로 바꿉니다.
- **계측** — 각 단계는 `DiscoverService`가 `movielog.discover.embedding`·`search`·`similar`·`graph`
  Timer(`model` tag 포함)로 감싸고, 세 접근 방식의 SQL은 모두 Application Insights dependency로 수집됩니다.

## 의미 검색 구현: 키워드 결합과 철자 교정 { #search }

의미 검색은 질의 철자를 고친 뒤 벡터 순위와 키워드 순위를 합칩니다. 두 임베딩 모델의 병행 구성과 선택 기준은
[topic 개요](../index.md#embedding-comparison)에 있습니다.

### 키워드 보완: 벡터 순위와 키워드 순위의 RRF 결합 { #hybrid }

문서 전체를 하나로 임베딩하면 줄거리 같은 서술형 질의에는 강하지만, 제목이나 인물 이름만 넣은
짧은 질의에는 약합니다. 2026-11-14에 「듄: 파트 2」를 색인한 뒤 Azure OpenAI 임베딩 벡터만으로 검색하면 「듄」에서
10위, 「드니 빌뇌브」에서 12위였습니다. 그래서 `VectorSearchRepository.search`는 벡터 상위 50편과
키워드 상위 50편의 순위를 Reciprocal Rank Fusion(`1 / (60 + 순위)`의 합)으로 합칩니다.

- **키워드 순위** — 질의 단어가 문서 머리(제목·원제·개봉·장르·감독·출연)에 몇 개 들어 있는지로
  정하고, 같으면 벡터 거리로 정렬합니다. 줄거리는 벡터 쪽에만 맡깁니다.
- **반영 조건** — 질의 단어의 절반 이상이 들어 있는 영화만 키워드 순위에 넣습니다. 이 조건이 없을
  때는 「a shark terrorizes a beach town」에서 원제에 beach가 들어간 「밤의 해변에서 혼자」가
  「죠스」보다 앞섰습니다. 영어 단어는 4자 이상만 씁니다.
- **점수 표시** — 순서는 결합 순위를 따르고, 화면의 점수는 그대로 코사인 유사도입니다.

| 질의 | 벡터만 상위 3편 | RRF 결합 상위 3편 |
|---|---|---|
| 듄 | 듄(2021), 듄(1984), 디워 | 듄(2021), 듄(1984), 듄: 파트 2 |
| 드니 빌뇌브 | 블루 벨벳, 듄(2021), 다빈치 코드 | 듄(2021), 듄: 파트 2, 블레이드 러너 2049 |
| 꿈속에서 벌어지는 하이스트 | 호프, 인터스텔라, 위플래쉬 | 같음 |
| 아이와 함께 보는 판타지 애니메이션 | 센과 치히로의 행방불명, 위쳐: 늑대의 악몽, 신비한 동물사전 | 같음 |

- **전체 일치 가중치** — 질의 단어가 모두 문서 머리에 있는 영화는 키워드 쪽 점수를 두 배로 셉니다.
  가중치가 없을 때 「티모시 샬라메」는 키워드 2위인 「듄」(1/62)이 벡터 1위인 「아멜리에」(1/61)보다
  뒤였습니다. 가중치를 둔 뒤 상위 3편이 「콜 미 바이 유어 네임」, 「듄: 파트 2」, 「듄」이 됐고, 위 표의
  서술형 질의를 포함한 8개 질의(「SF 모험」 포함)의 상위 5편은 달라지지 않았습니다.

### 철자 교정: 자모 편집 거리와 인물·제목 사전 { #spelling }

「드늬 뷜베브」처럼 이름 철자가 틀리면 키워드가 일치하지 않고, 임베딩도 같은 인물로 보지 못해
「듄」 계열이 상위에 나오지 않았습니다. `QueryCorrector`는 질의를 임베딩하기 전에 인물 이름
(`catalog.people`의 한국어·영어 이름)과 영화 제목 사전에서 가장 가까운 항목으로 고칩니다.

- **자모 비교** — 한글을 NFD로 자모까지 분해해 편집 거리를 재고, 모음끼리 바뀐 경우는 0.5로
  셉니다. 외국 이름의 한글 표기는 주로 모음이 달라서, 이 가중치로 「드늬 뷜베브」와 「드니 빌뇌브」의
  유사도가 0.64에서 0.77이 됐습니다.
- **교정 대상** — 어떤 영화 문서에도 없는 단어(뒤의 조사 와·을 등을 떼고도 없는 단어)가 들어 있는
  1–3단어 구간만 고칩니다. 이 조건이 없으면 「아이와」가 「아이유」로, 「하이스트」가 「아티스트」로
  바뀌었습니다.
- **채택 기준** — 유사도 0.75 이상이고 2위보다 0.1 이상 높을 때만 바꿉니다. 1–3단어 구간이 유사도로
  경쟁하고 같으면 긴 구간을 고르므로, 「인셉숀 2」는 「인셉숀」만 고쳐 「인셉션 2」로 검색합니다.
  이미 이름·제목과 정확히 같은 단어는 교정 구간에 넣지 않아, 「인셉션 4DX」는 그대로 검색합니다.
  고친 질의로 임베딩과 키워드 순위를 모두 계산하고, 화면에는 「'드늬 뷜베브'을(를) '드니 빌뇌브'(으)로
  고쳐 검색했습니다」를 보여 줍니다. 교정 횟수는 `movielog.discover.corrected` counter로 남깁니다.

| 입력 | 교정 결과 | 상위 결과 |
|---|---|---|
| 드늬 뷜베브 | 드니 빌뇌브 | 듄(2021), 듄: 파트 2, 블레이드 러너 2049 |
| 봉준오 | 봉준호 | 살인의 추억, 괴물, 옥자 |
| 크리스토퍼 놀랜 | 크리스토퍼 놀런 | 오펜하이머, 인터스텔라, 다크 나이트 |
| 티모시 살라메 | 티모시 샬라메 | 콜 미 바이 유어 네임, 웡카, 듄: 파트 2 |

기준을 정할 때 서술형 질의 16개와 정확한 이름·제목 질의 5개를 함께 넣어 보았고, 어느 것도 바뀌지
않았습니다. 영어 이름 오타(「christopher nolen」)는 이 기준에서 교정되지 않았습니다.
사전은 10분마다, 그리고 새 영화를 색인한 직후 다시 읽습니다.

## 그래프 화면: 포스터 노드 · 관계 필터 · 인물 펼치기 { #graph-ui }

그래프 화면은 Cytoscape.js(Canvas)와 fCoSE 레이아웃으로 그리며, 한 화면에 노드 수십 개를 두고
누르고 펼치며 탐색하는 데 맞췄습니다. 처음 화면은 노드가 모두 같은 점과 사각형이라 영화를 구분하기
어렵고, 장르가 거의 모든 결과를 이어 선이 겹쳤습니다. 2026-11-15에 다음처럼 바꿨습니다.

| 기능 | 동작 | 구현 |
|---|---|---|
| 포스터 노드 | 영화 노드를 TMDB 포스터(w92)로 그리고, 페이지·결과 영화는 크게 테두리를 둡니다. | API가 `public.movies.poster_path`로 `posterUrl`을 붙입니다. 그래프에는 포스터를 저장하지 않습니다. |
| 관계 필터 | 범례 칩이 감독·출연, 장르, 비슷한 영화 관계를 켜고 끕니다. 의미 검색 화면은 장르를 끈 채 시작합니다. | 꺼진 관계와 그 관계로만 이어진 노드를 숨기고 보이는 요소만 다시 배치합니다. |
| 정보 패널 | 노드를 누르면 이웃만 강조하고, 아래 패널에 영화 정보·관계 그래프 링크나 그 인물·장르와 이어진 영화 목록을 보여 줍니다. | 일반 DOM이라 키보드와 스크린 리더로 읽을 수 있습니다. |
| 인물 펼치기 | 인물의 다른 작품(최대 30편)을 현재 위치 옆에 더하고 그 인물 주변으로 확대합니다. | `GET /api/discover/graph/people/{qid}`가 `MATCH (a:Person {qid})-[r]->(b:Movie)`를 실행합니다. qid는 `Q숫자` 또는 `tmdb:숫자`만 받습니다. |
| 배치 | 영화 그래프는 페이지 영화를 가운데에 고정하고, 간선을 짧게 해 같은 캔버스에서 1.3–1.4배 크게 보이게 했습니다. | fCoSE `fixedNodeConstraint`, `idealEdgeLength` 80·110 |

![의미 검색 결과 그래프에서 티모시 샬라메를 펼친 화면. 티모시 샬라메 노드가 강조되고 듄(2021), 듄: 파트 2(2024)와 펼치기로 더해진 웡카(2023), 인터스텔라(2014), 콜 미 바이 유어 네임(2017) 포스터 노드가 주황 선으로 이어지며, 나머지 노드는 흐리게 보임. 아래 정보 패널에 '그래프의 연결된 영화 5편'과 '3편을 더했습니다'가 표시됨](../images/movie-graph.png)

- **포스터 selector** — Cytoscape.js에서 `node[posterUrl]`은 값이 `null`이어도 일치해 포스터가 없는
  노드가 `null`이라는 상대 URL을 요청했습니다(`/graph/movies/null` 400). 참으로 평가되는 값만 고르는
  `node[?posterUrl]`을 씁니다.
- **CORS** — TMDB 이미지 서버는 `Access-Control-Allow-Origin: *`를 돌려주므로 캔버스에
  `crossorigin=anonymous`로 그릴 수 있습니다.

2026-11-15에 검토한 시각화 라이브러리와 도구는 다음과 같습니다. 영화 주변·검색 결과처럼 노드 수십 개를
누르고 펼치는 화면에는 레이아웃 확장과 스타일 선택자가 풍부한 Cytoscape.js가 맞고, 영화 480여 편과
인물 1,800여 명 전체를 한 번에 보는 지도를 만든다면 WebGL로 그리는 Sigma.js가 적합합니다.

| 종류 | 이름 | 그리기 | 맞는 용도 |
|---|---|---|---|
| 웹 라이브러리 | Cytoscape.js | Canvas | 수백~수천 노드의 탐색, 분석 알고리즘과 다양한 레이아웃 확장 |
| 웹 라이브러리 | Sigma.js + graphology | WebGL | 수천 노드 이상의 전체 지도, ForceAtlas2 배치 |
| 웹 라이브러리 | AntV G6, vis-network, force-graph | Canvas·WebGL | 미니맵·툴팁 내장(G6), 물리 시뮬레이션(vis-network), 3D(force-graph) |
| 상용 엔진 | KeyLines, Ogma, yFiles | Canvas·WebGL | 수사·사기 탐지용 타임라인, 대규모 그래프, 정교한 계층 레이아웃 |
| AGE 조회 도구 | VS Code PostgreSQL 확장, Apache AGE for VS Code(커뮤니티), Apache AGE Viewer | — | 개발자가 Cypher 결과를 그래프로 확인. 앱 화면 대신 운영·디버깅에 씁니다. |

## 관측: `movielog.discover.*` Timer와 Grafana 대시보드 { #observe }

의미 검색의 각 단계는 Micrometer Timer(`movielog.discover.embedding`·`search`·`similar`·`graph`, `model` tag)로
기록되고, AKS 자동 계측이 Application Insights `customMetrics`로 보냅니다. HorizonDB 쿼리와
임베딩 호출은 agent의 dependency로도 수집되어, 대시보드에서 쿼리 종류별(벡터 `<=>`,
AGE cypher, 일반 SQL) 시간을 나눠 볼 수 있습니다.

다음은 Azure OpenAI 단일 모델로 운영한 2026-11-13의 대시보드입니다.

![MovieLog HorizonDB 의미 검색 대시보드. 의미 검색 4.68K, 평균 질의 임베딩 93.8 ms, 평균 벡터 검색 5.28 ms, 평균 그래프 조회 4.45 ms, 실패 0 stat과 단계별 지연·호출 수, HorizonDB SQL 호출 수와 평균 시간, Azure OpenAI 임베딩 호출 시간, 쿼리 유형별 시간 표, 엔드포인트별 p95와 실패율이 보임](../images/grafana-discover-dashboard.png)

## 공개 구성: HTTPS · Microsoft Entra ID · 요청률 한도 { #public-access }

- **AGFC와 NSG** — AKS 관리형 VNet을 쓰면 add-on이 `aks-appgateway` 서브넷을 만듭니다.
  실습에서는 이 서브넷 NSG에 Internet에서 TCP 80·443을 허용하는 규칙을 넣어야 frontend에
  접속됐습니다. 실습 구독에서는 Internet의 모든 포트를 여는 규칙을 만든 지 약 25분 뒤 조직 보안
  자동화가 규칙을 지워 접속이 끊겼고, 포트를 지정한 규칙은 유지됐습니다.
- **HTTPS와 커스텀 도메인** — 회원 가입과 form login이 있어 HTTP로는 비밀번호와 session cookie가
  평문으로 전달됩니다. 그래서 커스텀 도메인의 CNAME을 Gateway 주소로 향하게 하고,
  [cert-manager와 Let's Encrypt](https://learn.microsoft.com/azure/application-gateway/for-containers/how-to-cert-manager-lets-encrypt-gateway-api)로
  HTTPS listener의 인증서를 발급했습니다. HTTP listener는 HTTP-01 challenge만 응답하고 나머지는
  HTTPS로 301 redirect합니다. 실측에서 인증서 발급은 약 45초 걸렸고, AGFC가 넘기는
  `x-forwarded-proto` 덕분에 앱의 로그인 redirect는 `https://` 주소로, `JSESSIONID`는 `Secure`로
  나왔습니다. listener에 hostname을 지정해 AGFC 기본 FQDN으로 들어온 요청은 404가 됩니다.
- **공개 범위** — AKS 배포(`aks` profile)는 `app.security.require-login=true`로 로그인·회원가입 화면을
  뺀 모든 화면과 API에 로그인을 요구합니다. 로그인하지 않은 요청은 화면이면 `/login`으로, API면 401을
  받습니다. 다만 회원 가입이 열려 있어 누구나 계정을 만들 수 있으므로, 유료 임베딩 호출과 quota를
  지키도록 앱이 임베딩 호출 전에 클라이언트 주소당 분당 30건, 전체 분당 300건으로 제한하고 넘으면
  429를 돌려줍니다. 한도는 Pod마다 따로 세므로 Pod 2개에서는 배포 전체가 분당 최대 600건까지 허용합니다. 실습이 끝나면 NSG 규칙, DNS 레코드와 resource group을 지웁니다.
- **클러스터 자동 중지** — 실습 구독에서는 조직 자동화가 자정 무렵 AKS 클러스터를 중지했습니다.
  다음 날 다시 볼 때는 `az aks start`로 시작합니다. 인증서와 Gateway 구성은 재시작 뒤에도
  유지됐습니다.

## 정리 { #cleanup }

```bash
azd down --purge
```

`predown` hook이 resource group 밖에 만든 DNS 레코드와 Entra ID 앱 등록을 지운 뒤 azd가 resource group을 지우고,
`--purge`가 soft-delete된 Key Vault와 Azure OpenAI 계정을 영구 삭제합니다.
