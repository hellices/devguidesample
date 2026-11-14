# MovieLog on Azure HorizonDB: vector search and an Apache AGE graph

아키텍처와 측정 결과는 상위 topic 문서에 있습니다.

영화 리뷰 앱 MovieLog(Spring Boot 4.1.2, Java 25)의 DB를 Azure HorizonDB(PostgreSQL 17)로
바꾸고, Wikidata·Wikipedia에서 만든 영화 카탈로그를 임베딩해 의미 검색을 붙이고,
같은 데이터를 Apache AGE 그래프로 만들어 시각화하는 실습 sample입니다. 앱은 AKS
autoinstrumentation(Application Insights Java agent)으로 계측하고 Managed Grafana
대시보드로 봅니다.

## 구성

이 sample은 [MovieLog sample](../../../../azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app/README.md)
위에 바꾸거나 더한 파일만 담습니다. 앱 전체 소스는 `scripts/assemble-app.sh`가 기존 sample의 git 추적
파일만 `out/app/`에 복사하고(로컬 `.env`나 DB 파일은 제외) 이 sample의 `src/`, `build.gradle.kts`, `.env.sample`을 덮어써서 만듭니다.
Gradle Wrapper, `Dockerfile`, `agent-init/`, `k8s/10-instrumentation.yaml`,
`k8s/21-agent-3.7.10.patch.yaml`은 기존 sample의 파일을 그대로 씁니다.

| 경로 | 용도 |
|---|---|
| `data/build_catalog.py` | Wikidata(감독·배우·장르·TMDB id)와 Wikipedia 요약으로 영화 약 480편의 `catalog.json`·`catalog.sql`을 만듭니다. 표준 라이브러리만 씁니다. |
| `data/enrich_tmdb.py` | `catalog.json`의 TMDB id로 TMDB 상세 API를 호출해 비어 있는 포스터·상영 시간·IMDb id만 채우는 `tmdb.sql`을 만듭니다. Wikipedia 제목과 요약은 바꾸지 않습니다. |
| `data/embed_catalog.py` | `catalog.movie_docs.doc`을 Azure OpenAI `text-embedding-3-large`(1,536차원)로 임베딩해 저장합니다. Azure CLI의 Entra token을 씁니다. |
| `db/00-database.sql` | `movielog` DB와 앱 role을 만듭니다. |
| `db/10-schema.sql` | `vector`, `pg_diskann`, `age` 확장과 `catalog` schema를 만듭니다. |
| `db/20-vector-index.sql` | `embedding`에 DiskANN 코사인 index를 만듭니다. |
| `db/30-graph.sql` | 관계형 카탈로그에서 AGE 그래프 `movie_graph`를 다시 만듭니다. 영화마다 임베딩 최근접 3편을 `SIMILAR_TO`로 잇습니다. |
| `src/main/java/.../discover/` | 의미 검색(`EmbeddingClient`, 벡터·키워드 순위를 RRF로 합치는 `VectorSearchRepository`), 카탈로그 밖 영화 색인(`CatalogIndexer`, `TmdbCreditsClient`), 그래프 조회(`MovieGraphRepository`), `movielog.discover.*` Timer를 기록하는 `DiscoverService`, 웹·API controller입니다. |
| `src/main/resources/templates/discover/`, `static/js/graph.js` | `/discover` 의미 검색 화면과 `/graph/movies/{tmdbId}` 그래프 화면입니다. Cytoscape.js와 라벨 크기까지 계산해 겹침을 피하는 fCoSE 레이아웃으로 그리고, 키보드·스크린 리더용 관계 텍스트 목록과 영화 링크를 함께 렌더링합니다. |
| `k8s/00-namespace.yaml` | namespace와 workload identity ServiceAccount입니다. |
| `scripts/assemble-app.sh` | 기존 MovieLog sample과 이 sample의 변경 파일을 합쳐 `out/app/`에 앱 소스를 만듭니다. |
| `k8s/20-movielog.yaml` | HorizonDB 연결(secret)과 Azure OpenAI endpoint를 받는 앱 Deployment입니다. |
| `k8s/24-keyvault-secrets.yaml` | Secrets Store CSI driver가 Key Vault의 TMDB·OMDb 키와 Entra ID client secret을 앱 workload identity로 읽어 `movielog-keyvault` secret으로 동기화하는 SecretProviderClass입니다. |
| `src/main/java/.../member/`, `config/SecurityConfig.java`, `templates/auth/login.html`, `application-entra.properties` | 아이디·비밀번호 로그인 옆에 Microsoft Entra ID(OpenID Connect) 로그인을 더하고, 첫 로그인 때 `tid`·`oid`로 회원을 만듭니다. `entra` profile에서만 켜집니다. |
| `k8s/26-agfc.yaml` | Application Gateway for Containers(AKS add-on)로 앱을 커스텀 도메인 HTTPS로 공개하는 ApplicationLoadBalancer, HTTP·HTTPS listener Gateway, 앱 HTTPRoute, HTTP→HTTPS redirect HTTPRoute와 session affinity·health check policy입니다. |
| `k8s/27-tls.yaml` | cert-manager가 Let's Encrypt에서 HTTP-01 challenge로 인증서를 받아 `movielog-tls` secret에 넣는 ClusterIssuer와 Certificate입니다. |
| `loadgen/loadgen.py` | 가입·조회·리뷰와 의미 검색·그래프 조회를 반복하는 합성 사용자입니다. 작성한 합성 리뷰는 조회한 뒤 항상 삭제해 리뷰 목록에 쌓이지 않습니다. Deployment는 기존 sample의 `k8s/30-loadgen.yaml`을 씁니다. |
| `grafana/movielog-horizondb-dashboard.json` | discover Timer, HorizonDB·Azure OpenAI dependency, discover 요청을 보는 dashboard입니다. resource ID 변수는 비어 있습니다. |

## 화면과 API

| 경로 | 내용 |
|---|---|
| `/discover?q=` | 질의를 임베딩해 가까운 영화 12편과, 그 영화들을 잇는 인물·장르·`SIMILAR_TO` 그래프를 보여 줍니다. |
| `/graph/movies/{tmdbId}` | 영화의 감독·배우·장르·`SIMILAR_TO` 이웃과 같은 인물의 다른 영화를 그립니다. 영화 노드를 두 번 누르면 이동합니다. |
| `/movies/{tmdbId}` | 기존 상세 화면에 임베딩이 비슷한 영화 6편과 그래프 링크를 더했습니다. |
| `GET /api/discover/search?q=&limit=` | 의미 검색 결과(코사인 유사도 포함). 요청률 한도를 넘으면 429 |
| `GET /api/discover/movies/{tmdbId}/similar` | 임베딩 최근접 영화 |
| `GET /api/discover/graph/movies/{tmdbId}` | 영화 주변 그래프(Cytoscape 형식 node·edge) |
| `GET /api/discover/graph?ids=` | 주어진 영화들 사이의 연결 그래프 |

## 설계 메모

- **Microsoft Entra ID 로그인은 기존 회원 구조에 붙입니다.** `entra` profile이 single-tenant 앱
  등록을 OpenID Connect client로 등록하면 로그인 화면에 Entra ID 버튼이 생깁니다. 첫 로그인 때 ID token의
  변하지 않는 `tid`·`oid`로 `members.external_id`(`entra:<tid>:<oid>`)를 만들고, 아이디는
  `preferred_username` 앞부분과 hash로 `<이름>-<6자리>` 형태를 씁니다. 회원가입 아이디는 `-`를 쓸 수 없어
  둘이 겹치지 않습니다. 닉네임은 `name` claim에서 가져오며 이후 이름이 바뀌어도 회원은 그대로입니다.
  principal이 `UserDetails`이기도 해서 리뷰·댓글 코드는 두 로그인 방식을 구분하지 않습니다. 필요한 claim이
  ID token에 있으므로 Microsoft Graph user info는 호출하지 않으며, 로그아웃은 앱 session만 끝냅니다.
- **앱 비밀값은 Key Vault에서 받습니다.** TMDB·OMDb 키와 Entra ID client secret은 Key Vault에 두고,
  AKS Secrets Store CSI driver가 앱과 같은 workload identity로 읽어 환경 변수로 넘깁니다. 실습 구독에서는
  Azure Policy(`modify`)가 Key Vault의 공용 네트워크 접근을 끄므로, AKS VNet에 private endpoint와
  `privatelink.vaultcore.azure.net` private DNS zone을 둡니다. 운영자는 Key Vault data plane 대신 ARM
  `Microsoft.KeyVault/vaults/secrets`로 값을 넣습니다.

- **AKS 배포는 모든 화면에 로그인을 요구합니다.** 기존 MovieLog sample은 목록·상세를 익명으로 읽게
  열어 두지만, 이 sample의 `aks` profile은 `app.security.require-login=true`로 로그인·회원가입·정적
  파일·health를 뺀 모든 화면과 API를 막습니다. 로그인하지 않으면 화면은 `/login`으로 redirect되고 API는
  401을 받습니다. 기본값은 `false`라 로컬과 기존 sample 테스트는 그대로입니다.
- **의미 검색에 요청률 한도를 둡니다.** 회원 가입이 열려 있어 누구나 계정을 만들어 `/discover`와
  `/api/discover/search`로 Azure OpenAI를 호출할 수 있으므로, 앱이 Azure OpenAI를 부르기 전에 Pod마다 클라이언트 주소당 분당
  30건(`DISCOVER_RATE_LIMIT_PER_CLIENT`)과 전체 분당 300건(`DISCOVER_RATE_LIMIT_TOTAL`)으로
  제한합니다. 넘으면 API는 429, 화면은 안내 문구를 돌려줍니다. 클라이언트 주소는 AGFC가 넘기는
  `x-forwarded-for`에서 Tomcat이 얻습니다. 카운터는 분마다 비우고 한 분에 주소 1만 개까지만
  추적해 그 이상 새 주소는 다음 분까지 거부합니다. 한도는 Pod 메모리에 있어 replica 수만큼 늘어나며,
  Azure OpenAI deployment의 용량(실습은 GlobalStandard 150K TPM)이 마지막 상한입니다.

- **질의 임베딩은 앱에서 합니다.** HorizonDB `azure_ai` 2.5.6은 `azure_ai.set_setting`을
  막고 `model_registry`에 등록한 alias로 모델을 호출합니다. 실습에서 확인한 제약은
  다음과 같습니다.
  - 관리자가 쓰는 alias 기반 `model_registry.model_add`는 PUBLIC에 열려 있고 BYOM으로
    등록합니다. UUID와 `registry_type`을 받는 `model_add_with_registry_type` 등 UUID
    overload는 EXECUTE가 `azuresu`에만 있어 관리자도 `permission denied`를 받습니다.
    이 함수들은 AI Model Management가 `default-embedding` 같은 managed model을 등록하는
    서비스 경로입니다.
  - BYOM에 `managed-identity`를 지정하면 "managed identity authentication is not
    supported for bring-your-own (BYOM) models"로 거부됩니다. Learn 문서의 등록 예는
    `managed-identity`를 허용한다고 적고 있어 동작과 다릅니다.
  - AI Model Management는 limited preview라 참여 신청 승인이 필요합니다. 승인 전에는
    cluster `aiModelManagement`를 `Enabled`로 바꿀 수 없습니다(`AiModelManagementAfecNotRegistered`).
  - `azure_openai.create_embeddings()`·`ai.embed()`는 `{endpoint}/openai/deployments/{deployment}/embeddings`
    형식으로만 호출하고 `text-embedding-3-small`, `text-embedding-3-large`, `text-embedding-ada-002`를
    지원합니다. `*.inference.ml.azure.com/score` 같은 Azure ML endpoint는 "Endpoint is not valid"로
    거부되므로 BGE-M3 같은 오픈 모델은 DB 안에서 임베딩할 수 없습니다.

  key 인증을 끈 Azure OpenAI에서는 앱이 workload identity로 embedding을 받아 벡터를 SQL
  parameter로 넘깁니다. 같은 이유로 앱 쪽 client만 바꾸면 다른 embedding 모델도 쓸 수 있습니다.
- **모델은 `text-embedding-3-large`를 1,536차원으로 줄여 씁니다.** 한국어 질의로
  비교했을 때 `text-embedding-3-small`보다 관련 영화가 상위에 왔습니다. 앱과
  `embed_catalog.py`는 같은 deployment와 차원을 써야 합니다.
- **임베딩 문서에는 한국어 요약과 영어 요약을 함께 넣습니다.** 한국어 Wikipedia
  도입부는 제작 정보 위주라 줄거리 질의와 잘 맞지 않았습니다. 화면에는 한국어
  요약만 보입니다.
- **카탈로그 밖의 영화는 앱이 색인합니다.** 회원이 TMDB 검색으로 처음 연 영화는
  `public.movies`에만 저장되므로, `aks` profile의 `CatalogIndexer`가 30초마다 문서가 없는
  영화를 찾아 TMDB credits를 더한 문서를 임베딩해 `catalog.movie_docs`에 넣습니다. 앱 role에
  `catalog.movie_docs` `INSERT` 권한이 필요하며(`db/10-schema.sql`), 그래프에는 `db/30-graph.sql`을
  다시 실행해야 들어갑니다.
- **의미 검색은 벡터 순위와 키워드 순위를 합칩니다.** 「듄」, 「드니 빌뇌브」 같은 짧은 제목·이름
  질의는 문서 전체 임베딩만으로는 순위가 낮아, 질의 단어의 절반 이상이 문서 머리(제목·장르·감독·
  출연)에 있는 영화의 순위를 Reciprocal Rank Fusion으로 더합니다. 서술형 질의 결과는 그대로입니다.
- **AGE 다중 시작점 조회는 `UNWIND`로 씁니다.** `MATCH (a:Movie)-[r]-(b) WHERE
  a.tmdb_id IN [...]`는 모든 edge를 훑어 영화 8편에 약 27초가 걸렸고,
  `UNWIND [...] AS t MATCH (a:Movie {tmdb_id: t})-[r]-(b)`는 같은 결과를 약 0.1초에
  돌려줬습니다. 그래프 생성 스크립트는 label table에 GIN index를 만듭니다.
- **Cypher 문자열에는 숫자 id만 넣습니다.** Cypher에는 JDBC parameter를 쓸 수 없고,
  `(a:Movie)`를 Spring의 named parameter로 오인하지 않도록 `JdbcTemplate`을 씁니다.
- 영화 약 480편 규모에서는 planner가 DiskANN 대신 seq scan을 고릅니다.
  `SET enable_seqscan = off`로 index 경로를 확인할 수 있습니다.

## 로컬 test

```bash
scripts/assemble-app.sh
(cd out/app && ./gradlew test)
```

JDK 25가 필요합니다.

## 배포

HorizonDB API `2026-10-01-preview`(Azure CLI `horizondb` 확장 1.0.0b9) 기준입니다.
cluster를 만든 뒤 pool, parameter group, 관리자 인증, 방화벽을 따로 만듭니다.

```bash
RG=rg-movielog-horizondb; LOC=koreacentral
HZ="<horizondb-cluster>"; ACR="<acr-name>"; AOAI="<openai-name>"; GRAFANA="<grafana-name>"
SID="$(az account show --query id -o tsv)"
RID="/subscriptions/$SID/resourceGroups/$RG/providers/Microsoft.HorizonDb"
API=api-version=2026-10-01-preview

az extension add --name horizondb
az group create -n $RG -l $LOC
az horizondb cluster create -g $RG -n "$HZ" -l $LOC --version 17 \
  --public-access Enabled --geo-redundancy Disabled

# Parameter group: extensions allowlist and AGE preload.
az rest --method put --uri "https://management.azure.com$RID/parameterGroups/pg-movielog-age?$API" --body \
  "{\"location\":\"$LOC\",\"properties\":{\"postgreSqlVersion\":\"17\",\"parameters\":[
    {\"name\":\"azure.extensions\",\"value\":\"vector,pg_diskann,age\"},
    {\"name\":\"shared_preload_libraries\",\"value\":\"age\"}]}}"

# Pool creation accepts only the default parameter group; assign the custom one afterwards.
az horizondb cluster pool create -g $RG --cluster-name "$HZ" -n pool-01 \
  --compute-processor Intel --compute-generation 1 --v-cores 4 --node-count 1 --high-availability-mode Disabled
az rest --method patch --uri "https://management.azure.com$RID/clusters/$HZ/pools/pool-01?$API" --body \
  "{\"properties\":{\"parameterGroup\":{\"parameterGroupResourceId\":\"$RID/parameterGroups/pg-movielog-age\",\"applyMethod\":\"Immediate\"}}}"

# Administrator (password authentication) and firewall rules for the operator and AKS egress.
# jq escapes quotes and backslashes in the password.
az rest --method put --uri "https://management.azure.com$RID/clusters/$HZ/authentications/passwordMethod?$API" \
  --body "$(jq -nc --arg password "$HZ_ADMIN_PASSWORD" \
    '{properties: {state: "Enabled", administratorLogin: "movielogadmin", administratorLoginPassword: $password}}')"
az rest --method put --uri "https://management.azure.com$RID/clusters/$HZ/pools/pool-01/firewallRules/client?$API" \
  --body "{\"properties\":{\"startIpAddress\":\"$MY_IP\",\"endIpAddress\":\"$MY_IP\"}}"
HZ_HOST="$(az rest --method get --uri "https://management.azure.com$RID/clusters/$HZ/endpoints?$API" \
  --query "value[?properties.role=='ReadWrite'].properties.fullyQualifiedDomainName | [0]" -o tsv)"
```

`passwordMethod`와 cluster 응답에는 `provisioningState`가 없을 수 있으므로
`administratorLogin`이 응답에 나타나는지로 완료를 확인합니다.

Azure OpenAI, AKS(workload identity·app monitoring), 모니터링 리소스를 만듭니다.

```bash
az cognitiveservices account create -g $RG -n "$AOAI" -l $LOC --kind OpenAI --sku S0 --custom-domain "$AOAI"
# Keyless: only Microsoft Entra tokens (workload identity, az login) can call the account.
az resource update --ids "$(az cognitiveservices account show -g $RG -n "$AOAI" --query id -o tsv)" \
  --set properties.disableLocalAuth=true
az cognitiveservices account deployment create -g $RG -n "$AOAI" --deployment-name text-embedding-3-large \
  --model-name text-embedding-3-large --model-version 1 --model-format OpenAI --sku-name GlobalStandard --sku-capacity 150
az monitor log-analytics workspace create -g $RG -n law-movielog-hz
az monitor app-insights component create -g $RG -a appi-movielog-hz -l $LOC \
  --workspace "$(az monitor log-analytics workspace show -g $RG -n law-movielog-hz --query id -o tsv)"
az acr create -g $RG -n "$ACR" --sku Basic
az aks create -g $RG -n aks-movielog-hz --node-count 2 --node-vm-size Standard_D4s_v5 \
  --enable-azure-monitor-app-monitoring --enable-oidc-issuer --enable-workload-identity \
  --attach-acr "$ACR" --generate-ssh-keys
az grafana create -g $RG -n "$GRAFANA" --sku-tier Standard

# Workload identity for query embeddings; the operator also needs the role for embed_catalog.py.
AOAI_ID="$(az cognitiveservices account show -g $RG -n "$AOAI" --query id -o tsv)"
az identity create -g $RG -n id-movielog-app
az role assignment create --assignee-object-id "$(az identity show -g $RG -n id-movielog-app --query principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal --role "Cognitive Services OpenAI User" --scope "$AOAI_ID"
az role assignment create --assignee-object-id "$(az ad signed-in-user show --query id -o tsv)" \
  --assignee-principal-type User --role "Cognitive Services OpenAI User" --scope "$AOAI_ID"
az identity federated-credential create -g $RG --identity-name id-movielog-app -n movielog-sa \
  --issuer "$(az aks show -g $RG -n aks-movielog-hz --query oidcIssuerProfile.issuerUrl -o tsv)" \
  --subject system:serviceaccount:movielog:movielog --audiences api://AzureADTokenExchange
```

AKS outbound IP를 HorizonDB 방화벽에 더하고 DB를 준비합니다.

```bash
NRG="$(az aks show -g $RG -n aks-movielog-hz --query nodeResourceGroup -o tsv)"
EGRESS="$(az network public-ip list -g "$NRG" \
  --query "[?tags.\"aks-managed-type\"=='aks-slb-managed-outbound-ip'].ipAddress | [0]" -o tsv)"
az rest --method put --uri "https://management.azure.com$RID/clusters/$HZ/pools/pool-01/firewallRules/aks-egress?$API" \
  --body "{\"properties\":{\"startIpAddress\":\"$EGRESS\",\"endIpAddress\":\"$EGRESS\"}}"

export PGHOST="$HZ_HOST" PGUSER=movielogadmin PGPASSWORD="$HZ_ADMIN_PASSWORD" PGSSLMODE=require
# 00-database.sql reads APP_DB_PASSWORD from the environment (psql 15+), not from the command line.
APP_DB_PASSWORD="$APP_DB_PASSWORD" psql -d postgres -f db/00-database.sql
PGDATABASE=movielog psql -f db/10-schema.sql
```

앱 비밀값을 Key Vault에 넣고 Microsoft Entra ID 앱을 등록합니다. 공개 주소(`APP_HOST`)를 먼저 정하면
redirect URI를 미리 등록할 수 있습니다. 값은 파일 권한 600인 임시 파일로만 다루고 명령줄에 쓰지 않습니다.

```bash
# APP_HOST: a new name in a DNS zone you own, for example movielog.example.com.
export APP_HOST=movielog.example.com
export KEYVAULT_NAME="<keyvault-name>" KEYVAULT_TENANT_ID="$(az account show --query tenantId -o tsv)"
az keyvault create -g $RG -n "$KEYVAULT_NAME" -l $LOC --enable-rbac-authorization true
KV_ID="$(az keyvault show -n "$KEYVAULT_NAME" --query id -o tsv)"
az role assignment create --assignee-object-id "$(az identity show -g $RG -n id-movielog-app --query principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope "$KV_ID"

# Private endpoint in the AKS VNet (public network access was disabled by policy in the lab subscription).
NRG="$(az aks show -g $RG -n aks-movielog-hz --query nodeResourceGroup -o tsv)"
VNET_ID="$(az network vnet list -g "$NRG" --query "[0].id" -o tsv)"
az network private-dns zone create -g $RG -n privatelink.vaultcore.azure.net
az network private-dns link vnet create -g $RG -z privatelink.vaultcore.azure.net -n aks-vnet-link -v "$VNET_ID" -e false
az network private-endpoint create -g $RG -n "pe-$KEYVAULT_NAME" -l $LOC --subnet "$VNET_ID/subnets/aks-subnet" \
  --private-connection-resource-id "$KV_ID" --group-ids vault --connection-name kv-conn
az network private-endpoint dns-zone-group create -g $RG --endpoint-name "pe-$KEYVAULT_NAME" -n default \
  --private-dns-zone privatelink.vaultcore.azure.net --zone-name vault
az aks enable-addons -g $RG -n aks-movielog-hz --addons azure-keyvault-secrets-provider

# Single-tenant Entra ID app; the client secret goes straight to a 600 file.
export ENTRA_TENANT_ID="$KEYVAULT_TENANT_ID"
export ENTRA_CLIENT_ID="$(az ad app create --display-name movielog-horizondb-lab --sign-in-audience AzureADMyOrg \
  --web-redirect-uris "https://$APP_HOST/login/oauth2/code/entra" --query appId -o tsv)"
az ad sp create --id "$ENTRA_CLIENT_ID"
umask 077; SECRETS="$(mktemp -d)"
az ad app credential reset --id "$ENTRA_CLIENT_ID" --display-name aks-movielog \
  --end-date "$(date -u -d '+180 days' +%Y-%m-%d)" --query password -o tsv | tr -d '\n' > "$SECRETS/entra-client-secret"
# Put the TMDB API Read Access Token and the OMDb key into $SECRETS/tmdb-api-key and $SECRETS/omdb-api-key.
for name in tmdb-api-key omdb-api-key entra-client-secret; do
  jq -nc --rawfile v "$SECRETS/$name" '{properties: {value: $v, contentType: "text/plain"}}' > "$SECRETS/body.json"
  az rest --method put --uri "https://management.azure.com$KV_ID/secrets/$name?api-version=2023-07-01" \
    --body @"$SECRETS/body.json" --query name -o tsv
done
rm -rf "$SECRETS"
```

앱을 배포합니다. 첫 배포는 replica 1개로 Hibernate가 schema를 만들게 합니다.

```bash
BASE=../../../../azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app
ACR_SERVER="$(az acr show -n "$ACR" --query loginServer -o tsv)"
scripts/assemble-app.sh
az acr build -r "$ACR" -t movielog:2.3.2 --platform linux/amd64 out/app
az acr build -r "$ACR" -t observability/applicationinsights-agent:3.7.10 --platform linux/amd64 out/app/agent-init
az aks get-credentials -g $RG -n aks-movielog-hz

export MI_CLIENT_ID="$(az identity show -g $RG -n id-movielog-app --query clientId -o tsv)"
export AZURE_OPENAI_ENDPOINT="https://$AOAI.openai.azure.com/"
export APP_IMAGE="$ACR_SERVER/movielog:2.3.2"
export APPLICATIONINSIGHTS_CONNECTION_STRING="$(az monitor app-insights component show \
  -g $RG -a appi-movielog-hz --query connectionString -o tsv)"
envsubst < k8s/00-namespace.yaml | kubectl apply -f -
envsubst < k8s/24-keyvault-secrets.yaml | kubectl apply -f -
kubectl create secret generic movielog-db -n movielog \
  --from-literal=url="jdbc:postgresql://$HZ_HOST:5432/movielog?sslmode=require" \
  --from-literal=username=movielog --from-literal=password="$APP_DB_PASSWORD"
envsubst < $BASE/k8s/10-instrumentation.yaml | kubectl apply -f -
envsubst < k8s/20-movielog.yaml | kubectl apply -f -
kubectl rollout status deploy/movielog -n movielog
```

주입된 agent가 3.7.9 미만이면 기존 sample의 `k8s/21-agent-3.7.10.patch.yaml` 주석의 두 단계로
3.7.10 init image로 바꿉니다. 이후 이미지만 바꿀 때는 patch가 유지되도록
`kubectl set image`를 씁니다.

카탈로그를 적재하고 임베딩·index·그래프를 만듭니다. 영화 약 480편 기준으로
`build_catalog.py`는 약 8–11분, `catalog.sql` 적재와 임베딩은 각각 약 3–4분,
TMDB 보강은 약 2분, 그래프 생성은 약 6초 걸렸습니다. Wikidata·Wikipedia에는 포스터가 없으므로
`enrich_tmdb.py`가 TMDB API Read Access Token(`TMDB_API_TOKEN`)으로 포스터 경로를 채웁니다.
토큰은 셸 history에 남지 않도록 `read -rs`로 입력합니다.

```bash
python3 data/build_catalog.py
export PGDATABASE=movielog
psql -q -f data/out/catalog.sql
read -rs TMDB_API_TOKEN && export TMDB_API_TOKEN
python3 data/enrich_tmdb.py
psql -q -f data/out/tmdb.sql
AZURE_OPENAI_ENDPOINT="https://$AOAI.openai.azure.com/" python3 data/embed_catalog.py
psql -f db/20-vector-index.sql
psql -f db/30-graph.sql
```

부하를 켭니다.

```bash
kubectl scale deploy/movielog -n movielog --replicas=2
kubectl create configmap loadgen -n movielog --from-file=loadgen/loadgen.py
kubectl apply -f $BASE/k8s/30-loadgen.yaml
```

Application Gateway for Containers로 앱을 커스텀 도메인의 HTTPS로 공개합니다. 회원 가입과
form login이 있어 HTTP만 열면 비밀번호와 session cookie가 평문으로 전달되므로, HTTP listener는
Let's Encrypt HTTP-01 challenge에만 응답하고 나머지 요청은 HTTPS로 301 redirect합니다.

- **DNS** — 소유한 DNS zone에 이미 쓰는 이름과 겹치지 않는 host를 정하고, CNAME을 Gateway 주소로
  향하게 합니다. 실습은 Azure DNS zone의 새 하위 이름 하나를 썼습니다.
- **NSG** — AKS 관리형 VNet의 `aks-appgateway` 서브넷 NSG가 association에 적용되므로 frontend
  포트(TCP 80, 443)를 Internet에서 허용하는 규칙이 필요합니다. AGFC에서 Pod로 가는 트래픽은
  VNet 내부라 노드 NSG는 바꾸지 않습니다.
- **조직 보안 자동화** — 실습 구독에서는 모든 포트를 여는 Internet 허용 규칙을 만든 지 약 25분 뒤
  조직 보안 자동화(다른 tenant의 app)가 NSG를 다시 써서 규칙을 지웠고, 그 뒤 frontend 접속이
  시간 초과됐습니다. 포트를 지정한 규칙은 유지됐습니다.

```bash
# Requires the ManagedGatewayAPIPreview and ApplicationLoadBalancerPreview features (Microsoft.ContainerService).
az aks update -g $RG -n aks-movielog-hz --enable-gateway-api --enable-application-load-balancer
NRG="$(az aks show -g $RG -n aks-movielog-hz --query nodeResourceGroup -o tsv)"
export ALB_SUBNET_ID="$(az network vnet list -g "$NRG" \
  --query "[].subnets[?name=='aks-appgateway'][].id | [0]" -o tsv)"
ALB_NSG="$(az network vnet subnet show --ids "$ALB_SUBNET_ID" --query networkSecurityGroup.id -o tsv)"
for rule in http:200:80 https:210:443; do
  IFS=: read -r name priority port <<< "$rule"
  az network nsg rule create -g "$NRG" --nsg-name "${ALB_NSG##*/}" -n "allow-agfc-frontend-$name" \
    --priority "$priority" --direction Inbound --access Allow --protocol Tcp \
    --source-address-prefixes Internet --source-port-ranges '*' \
    --destination-address-prefixes '*' --destination-port-ranges "$port"
done

# cert-manager with Gateway API support (Learn: Cert-manager and Let's Encrypt with AGFC - Gateway API).
helm install cert-manager oci://quay.io/jetstack/charts/cert-manager --version v1.19.3 \
  --namespace cert-manager --create-namespace \
  --set config.enableGatewayAPI=true --set crds.enabled=true --wait

# APP_HOST was set with the Entra ID redirect URI above.
envsubst '$APP_HOST $ALB_SUBNET_ID' < k8s/26-agfc.yaml | kubectl apply -f -
GATEWAY_FQDN="$(kubectl get gateway movielog -n movielog -o jsonpath='{.status.addresses[0].value}')"
# Azure DNS example; DNS_ZONE_RG and DNS_ZONE are the resource group and name of your zone.
az network dns record-set list -g "$DNS_ZONE_RG" -z "$DNS_ZONE" --query "[].name" -o tsv  # pick an unused name
az network dns record-set cname set-record -g "$DNS_ZONE_RG" -z "$DNS_ZONE" \
  -n "${APP_HOST%%.$DNS_ZONE}" -c "$GATEWAY_FQDN" --ttl 300
envsubst '$APP_HOST' < k8s/27-tls.yaml | kubectl apply -f -
kubectl wait certificate/movielog-tls -n movielog --for=condition=Ready --timeout=5m
```

실습에서는 `Certificate` 적용 후 약 45초 만에 Let's Encrypt 인증서가 발급됐고, 두 listener가
모두 `Programmed`가 됐습니다. 확인은 다음처럼 합니다.

```bash
curl -sI "http://$APP_HOST/" | grep -iE '^HTTP|^location'     # 301 -> https://$APP_HOST/
curl -sv -o /dev/null "https://$APP_HOST/" 2>&1 | grep issuer # O=Let's Encrypt
curl -sI "https://$APP_HOST/reviews/new" | grep -i location   # https://$APP_HOST/login
```

AGFC는 백엔드에 `x-forwarded-proto`를 넘기고 Spring Boot는 Kubernetes에서 이 헤더를 따르므로,
앱이 만드는 redirect는 `https://` 주소가 되고 `JSESSIONID`·`XSRF-TOKEN` cookie에는 `Secure`가
붙었습니다. listener에 hostname을 지정했으므로 AGFC 기본 FQDN으로 들어온 요청은 404를 받습니다.
cert-manager는 만료 전에 인증서를 자동으로 갱신합니다.

HTTPS가 준비되면 Microsoft Entra ID 로그인을 확인합니다. 로그인 화면의 **Microsoft Entra ID로 로그인**은
`/oauth2/authorization/entra`에서 Entra ID authorize endpoint로 넘어갑니다. 실습에서는 redirect의
`client_id`, `redirect_uri`(`https://$APP_HOST/login/oauth2/code/entra`), `scope=openid profile`, `state`·`nonce`와
Entra ID 로그인 화면(이메일 입력)까지 브라우저로 확인했고, 기존 아이디·비밀번호 가입과 로그인도 그대로
동작했습니다.

```bash
curl -s -o /dev/null -w '%{redirect_url}\n' "https://$APP_HOST/oauth2/authorization/entra"
```

이미 실행 중인 앱을 Entra ID 로그인이 있는 이미지로 바꾸면 Hibernate `ddl-auto=update`가 `members`에
`external_id` 열을 더합니다. 실습에서는 이 순간 아직 남아 있던 이전 Pod의 회원가입 INSERT 7건이 약 1초 동안
`cached plan must not change result type`으로 실패했고, 이전 Pod가 내려간 뒤에는 다시 나지 않았습니다.

`RoutePolicy`의 `managed-cookie`는 gateway가 `AGCAffinity` cookie를 첫 응답에 붙여
로그인 session이 한 Pod에 머물게 합니다. 실습에서 가입·로그인 뒤 인증이 필요한 리뷰 작성
10건이 모두 성공했고, HTTPS 전환 뒤에도 가입·로그인이 정상 동작했습니다.

## Grafana dashboard

`appinsights` 변수에 Application Insights resource ID를 채운 사본을 만들어 올립니다.
채운 JSON은 커밋하지 않습니다.

```bash
AIID="$(az monitor app-insights component show -g $RG -a appi-movielog-hz --query id -o tsv)"
python3 - "$AIID" > /tmp/live.json <<'PY'
import json, sys
d = json.load(open("grafana/movielog-horizondb-dashboard.json", encoding="utf-8"))
for v in d["templating"]["list"]:
    if v["name"] == "appinsights":
        v.update(query=sys.argv[1], current={"text": sys.argv[1], "value": sys.argv[1]}, hide=2)
json.dump(d, sys.stdout, ensure_ascii=False)
PY
az grafana dashboard create -g $RG -n "$GRAFANA" --definition @/tmp/live.json --overwrite true
rm /tmp/live.json
```

| Micrometer meter | 종류 | tag |
|---|---|---|
| `movielog.discover.embedding` | Timer | `kind=query`, `outcome` |
| `movielog.discover.search`, `movielog.discover.similar` | Timer | `kind=vector`, `outcome` = `found`/`empty`/`error` |
| `movielog.discover.graph` | Timer | `kind` = `movie`/`results`, `outcome` |
| `movielog.discover.rejected` | Counter | 요청률 한도로 Azure OpenAI 호출 전에 거부한 의미 검색 |

## 데이터 출처

카탈로그 구조는 [Wikidata](https://www.wikidata.org/)(CC0), 요약은
[Wikipedia](https://www.wikipedia.org/)([CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/))에서
가져옵니다. 화면에 보이는 요약은 출처 URL과 함께 `catalog.movie_docs.overview`에도 저장하고,
검색 결과와 영화 상세 화면은 그 요약 아래에 원문 Wikipedia 문서 링크와 라이선스를 표시합니다.
TMDB 키를 설정해 앱이 `public.movies.overview`를 TMDB 줄거리로 갱신해도 출처 표시는 저장한 요약에만 붙습니다. 임베딩 문서에만 쓰는 영어 요약의 출처는 `catalog.movie_docs.summary_en_source`에 기록합니다.
생성된 `data/out/`은 커밋하지 않습니다.

## 정리

DNS 레코드는 실습 resource group 밖의 zone에 있으므로 따로 지웁니다.

```bash
az network dns record-set cname delete -g "$DNS_ZONE_RG" -z "$DNS_ZONE" -n "${APP_HOST%%.$DNS_ZONE}" --yes
az group delete -n "$RG" --yes --no-wait
```
