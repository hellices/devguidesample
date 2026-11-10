---
title: "MovieLog 실습: AKS 자동 계측 지표 수집과 GitHub Copilot 검증 Grafana 대시보드"
description: MovieLog(Spring Boot 4.1) 앱을 AKS에 배포해 Micrometer 지표를 Application Insights customMetrics로 수집하고, GitHub Copilot이 skill 지침에 따라 probe → build → verify → look 순서로 Azure Managed Grafana 대시보드를 만드는 과정을 명령, 실측값, 캡처와 함께 재현합니다. 관리형 agent 3.7.7-aks에서 3.7.10으로 바꾸는 절차와 비용, 정리 방법을 포함합니다.
document_type: lab
services: [azure-monitor, azure-kubernetes-service, azure-managed-grafana]
technologies: [java, spring-boot, micrometer, kubernetes, grafana]
tags: [build, operate]
status: verified
verification_status: verified
sources_checked_at: 2026-11-07
official_sources:
  - title: Autoinstrument AKS apps with Azure Monitor Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless
  - title: Configure Azure Monitor Application Insights for Java
    url: https://learn.microsoft.com/azure/azure-monitor/app/java-standalone-config
  - title: Add and modify OpenTelemetry for .NET, Java, Node.js, and Python applications
    url: https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify
  - title: Metrics in Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/app/metrics-overview
  - title: Azure Monitor and Prometheus
    url: https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-overview
  - title: Grant Azure Monitor access to Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-permissions
  - title: How to manage data sources in Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-data-source-plugins-managed-identity
  - title: Authenticate to Azure Managed Grafana data plane APIs with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-authenticate-data-plane-api
  - title: Configure an Azure Managed Grafana remote MCP server
    url: https://learn.microsoft.com/azure/managed-grafana/grafana-mcp-server
  - title: Dashboards with Grafana in Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/app/grafana-dashboards
  - title: Create a dashboard in Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-create-dashboard
  - title: Migrate to Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-migrate
  - title: Application Insights Java 3.7.10 Azure Monitor registry source
    url: https://github.com/microsoft/ApplicationInsights-Java/blob/3.7.10/agent/instrumentation/micrometer-1.0/src/main/java/io/opentelemetry/javaagent/instrumentation/micrometer/ai/AzureMonitorMeterRegistry.java
  - title: Application Insights Java 3.7.10 Azure Monitor naming convention source
    url: https://github.com/microsoft/ApplicationInsights-Java/blob/3.7.10/agent/instrumentation/micrometer-1.0/src/main/java/io/opentelemetry/javaagent/instrumentation/micrometer/ai/AzureMonitorNamingConvention.java
  - title: Fix Spring Boot 4 Micrometer auto-configuration and add actuator metrics smoke coverage
    url: https://github.com/microsoft/ApplicationInsights-Java/pull/4672
  - title: Application Insights Java 3.7.10
    url: https://github.com/microsoft/ApplicationInsights-Java/releases/tag/3.7.10
last_verified: 2026-11-07
review_cycle_days: 30
estimated_time: 90m
cost: paid
cleanup_required: true
topic_order: 1
related_guides:
  - ../../aks-java-micrometer-custom-metrics/index.md
---

# MovieLog 실습: AKS 자동 계측 지표 수집과 GitHub Copilot 검증 Grafana 대시보드

## 실습 범위: 수집 경로부터 GitHub Copilot 검증 대시보드까지 { #summary }

[주제 소개](../index.md)에서 설명한 흐름을 영화 리뷰 앱 MovieLog로 직접
재현합니다. 아래 명령과 수치, 캡처는 Korea Central에서 실제로 구성해 얻은
결과입니다. 수집과 첫 대시보드 작성은 2026-11-06에, 질문 유형별 시각화 개편과
[대시보드 반영](#publish)은 2026-11-07에 실행했습니다.

```text
[MovieLog, Spring Boot 4.1.2 / Java 25]
  BusinessMetrics ── movielog.* Counter · DistributionSummary · Gauge
        │  Spring MeterRegistry
        ▼
[Application Insights Java agent]  ← AKS 자동 계측(webhook)이 Deployment에 주입
        │  60초마다 export
        ▼
[Application Insights customMetrics] ── workspace 기반
        │  KQL
        ▼
[Azure Managed Grafana · Azure Monitor data source] → 대시보드
```

이 실습에서만 얻은 결과는 다음과 같습니다. 흐름과 방법론의 요약은
[주제 소개](../index.md#message)에 있습니다.

- 관리형 `3.7.7-aks`로는 `movielog_*`가 0건이었고, 3.7.10 init image로 바꾸자
  12개 지표가 두 Pod에서 도착했습니다([Java agent 버전 확인](#version-gate)).
- 이미 주입된 Deployment에서 custom agent로 바꾸려면 patch를 두 번에 나눠야
  했습니다([webhook 주입 해제](#webhook-revert)).
- GitHub Copilot이 만든 대시보드는 probe → build → verify → look 단계마다 정한 점검
  기준을 통과한 뒤 반영합니다([Copilot 대시보드 작업 단계](#agent-method)).

## 실습 자원: 단일 resource group 구성 { #resources }

실습 자원은 한 resource group에 만들고 끝나면 통째로 지웁니다.

| 자원 | 실습 구성 | 비고 |
|---|---|---|
| AKS | Kubernetes 1.36, `Standard_D4s_v5` 2 node, `--enable-azure-monitor-app-monitoring` | Linux node pool만 지원 |
| Application Insights | workspace 기반, Log Analytics workspace 연결 | 지표 저장소 |
| Azure Container Registry | Basic, `az acr build`로 image 빌드 | 로컬 Docker 불필요 |
| Azure Managed Grafana | Standard, Grafana 12.4 | Azure Monitor data source 기본 포함 |
| 클러스터 내부 | PostgreSQL 1개, MovieLog 2 replica, 합성 사용자 6개 | `movielog` namespace |

- 필요 권한: resource group Contributor, role assignment 생성 권한, Grafana Admin.
- Azure CLI 2.86.0 이상이 필요합니다. 실습은 2.89.1로 진행했습니다.
- AKS, Managed Grafana Standard와 수집 데이터에 비용이 발생합니다. 실습이 끝나면
  [정리](#cleanup)를 실행합니다.

이후 명령은 같은 shell에서 아래 변수를 그대로 이어 씁니다. 따옴표 안의 `<...>`만
자기 값으로 바꿉니다.

```bash
RG=rg-movielog-lab; LOC=koreacentral
ACR="<acr-name>"           # 전역에서 고유한 ACR 이름
GRAFANA="<grafana-name>"   # Managed Grafana 이름
az group create -n $RG -l $LOC
az monitor log-analytics workspace create -g $RG -n law-movielog-lab
az monitor app-insights component create -g $RG -a appi-movielog-lab -l $LOC \
  --workspace "$(az monitor log-analytics workspace show -g $RG -n law-movielog-lab --query id -o tsv)"
az acr create -g $RG -n "$ACR" --sku Basic
ACR_SERVER="$(az acr show -n "$ACR" --query loginServer -o tsv)"
az aks create -g $RG -n aks-movielog-lab --node-count 2 --node-vm-size Standard_D4s_v5 \
  --enable-azure-monitor-app-monitoring --attach-acr "$ACR" --generate-ssh-keys
az grafana create -g $RG -n "$GRAFANA" --sku-tier Standard
```

`az grafana create`는 Grafana Admin과 Monitoring Reader 역할을 자동으로
할당하려고 시도합니다. 실습에서는 이 단계가 CLI 오류로 실패해 직접
할당했습니다. 역할이 없으면 Grafana에 로그인하거나 데이터를 읽을 수 없으므로
생성 뒤 확인합니다.

```bash
az role assignment create --assignee-object-id "$(az grafana show -g $RG -n "$GRAFANA" --query identity.principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal --role "Monitoring Reader" \
  --scope "$(az group show -n $RG --query id -o tsv)"
az role assignment create --assignee-object-id "$(az ad signed-in-user show --query id -o tsv)" \
  --assignee-principal-type User --role "Grafana Admin" \
  --scope "$(az grafana show -g $RG -n "$GRAFANA" --query id -o tsv)"
```

## MovieLog meter: 도메인 이벤트와 집계 시점 { #meters }

MovieLog의 meter 기록은 `BusinessMetrics`와 `BusinessGauges` 두 class에 모여
있습니다. Micrometer API와 meter 종류, 코드 예시는
[주제 소개의 앱 코드 절](../index.md#record)에 있습니다. 서비스는 리뷰 작성 같은
도메인 이벤트를 발행하고, `BusinessMetrics`가 이를 받아 meter를 기록합니다.
트랜잭션 안에서 발행된 이벤트는 커밋 뒤에만 집계되므로 롤백된 작업은 빠집니다.
검색과 카탈로그 조회처럼 외부 API 호출이라 트랜잭션 밖에서 발행되는 이벤트는
`fallbackExecution = true`로 즉시 집계됩니다.

| Micrometer meter | 종류 | tag |
|---|---|---|
| `movielog.movie.views`, `movielog.review.views` | Counter | `channel` = `web`/`api` |
| `movielog.reviews.posted` | Counter | `channel`, `verdict` = `fresh`/`rotten` |
| `movielog.comments.posted`, `movielog.members.signups` 등 | Counter | `channel` |
| `movielog.movie.catalog.lookups` | Counter | `outcome` = `cache_hit` 등 |
| `movielog.review.rating` | DistributionSummary | 없음 |
| `movielog.movies.stored`, `movielog.reviews.stored` 등 | Gauge (DB `count(*)`, 1분 cache) | 없음 |

영화별 조회 수는 tag가 아니라 DB 컬럼에 둡니다.

AKS용 `aks` profile은 Actuator HTTP endpoint를 `health`만 열고, `movielog`
prefix meter만 만들도록 허용 목록을 둡니다.

```properties
management.endpoints.web.exposure.include=health
management.metrics.enable.all=false
management.metrics.enable.movielog=true
```

TMDB API key 없이 동작하도록 `aks` profile은 영화 12편을 seed로 넣습니다.
seed 영화는 local catalog에서 제공되므로 `catalog.lookups`의 `outcome`은
`cache_hit`만 나타납니다.

## 배포: Instrumentation CR과 Pod template annotation { #deploy }

앱은 `Instrumentation` CR과 Pod template annotation으로 배포합니다.

```bash
cd docs/services/azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app  # 저장소 루트 기준
az acr build -r "$ACR" -t movielog:1.0.0 --platform linux/amd64 .

az aks get-credentials -g $RG -n aks-movielog-lab
kubectl apply -f k8s/00-postgres.yaml
kubectl create secret generic movielog-db -n movielog \
  --from-literal=username=movielog --from-literal=password="$(openssl rand -base64 24)"

export APPLICATIONINSIGHTS_CONNECTION_STRING="$(az monitor app-insights component show \
  -g $RG -a appi-movielog-lab --query connectionString -o tsv)"
export APP_IMAGE="$ACR_SERVER/movielog:1.0.0"
envsubst < k8s/10-instrumentation.yaml | kubectl apply -f -
envsubst < k8s/20-movielog.yaml | kubectl apply -f -
kubectl rollout status deploy/movielog -n movielog
kubectl scale deploy/movielog -n movielog --replicas=2

kubectl create configmap loadgen -n movielog --from-file=loadgen/loadgen.py
kubectl apply -f k8s/30-loadgen.yaml
```

- `Instrumentation` CR과 annotation의 구성 방식은
  [주제 소개의 수집 절](../index.md#collect)에 있습니다. `k8s/10-instrumentation.yaml`과
  `k8s/20-movielog.yaml`이 per-deployment 방식으로 이를 구현합니다.
- connection string이 든 렌더링 결과는 저장소에 커밋하지 않습니다.
- 첫 배포는 replica 1개로 schema를 만든 뒤 2개로 늘립니다.

JVM flag는 Pod의 `JAVA_TOOL_OPTIONS`에 선언합니다. 실습에서 webhook은 Pod의
값 앞에 `-javaagent`를 붙였고, 원래 값을
`JAVA_TOOL_OPTIONS_BEFORE_AUTO_INSTRUMENTATION`에 보관했습니다.

```text
JAVA_TOOL_OPTIONS = -javaagent:/azure-monitor-auto-instrumentation-java/applicationinsights-agent-codeless.jar -XX:MaxRAMPercentage=75.0 -XX:+ExitOnOutOfMemoryError
```

## Java agent 버전 확인과 3.7.10 init image 적용 { #version-gate }

Spring Boot 4 앱은 주입된 agent가 3.7.9 이상이어야 Micrometer 지표가 수집됩니다.
원인과 대응 방식 비교는
[AKS Java Micrometer custom metric 누락 임시 대응](../../aks-java-micrometer-custom-metrics/index.md)에
있습니다. 이 절은 실습에서 쓴 방식, 즉 sample의 3.7.10 init image를 `kubectl patch`로
적용하는 절차만 다룹니다.

배포 직후 주입된 agent image를 확인합니다.

```bash
POD="$(kubectl get pod -n movielog -l app=movielog -o jsonpath='{.items[0].metadata.name}')"
kubectl get pod "$POD" -n movielog \
  -o jsonpath='{range .spec.initContainers[*]}{.name}{"\t"}{.image}{"\n"}{end}'
```

```text
azure-monitor-auto-instrumentation-java  mcr.microsoft.com/applicationinsights/auto-instrumentation/java:3.7.7-aks
```

tag가 3.7.9 미만이면 아래 절차를 적용합니다. 2026-11-06 실습에서는 `3.7.7-aks`가
주입됐고, inventory에 agent 기본 지표만 있고 `movielog_*`는 없었습니다.

![agent 3.7.7-aks 구간의 customMetrics inventory. JVM 기본 지표와 http.server.request.duration만 있고 movielog 지표가 없음](../images/probe-inventory-agent-3.7.7.png)

```bash
az acr build -r "$ACR" -t observability/applicationinsights-agent:3.7.10 \
  --platform linux/amd64 agent-init
export AGENT_IMAGE="$ACR_SERVER/observability/applicationinsights-agent@$(az acr repository show \
  -n "$ACR" --image observability/applicationinsights-agent:3.7.10 --query digest -o tsv)"
kubectl create secret generic appinsights -n movielog \
  --from-literal=connection-string="$APPLICATIONINSIGHTS_CONNECTION_STRING"

# 1) webhook이 이전 주입분을 걷어내도록 annotation만 먼저 끕니다.
kubectl patch deployment movielog -n movielog --type merge -p \
  '{"spec":{"template":{"metadata":{"annotations":{"instrumentation.opentelemetry.io/inject-java":"false"}}}}}'
kubectl rollout status deploy/movielog -n movielog
# 2) 정리된 Deployment에 3.7.10 init image와 agent 환경 변수를 넣습니다.
envsubst < k8s/21-agent-3.7.10.patch.yaml > /tmp/agent-patch.yaml
kubectl patch deployment movielog -n movielog --type strategic --patch-file /tmp/agent-patch.yaml
kubectl rollout status deploy/movielog -n movielog
# Pod마다 시작한 agent 버전을 확인합니다.
kubectl logs -n movielog -l app=movielog -c movielog --tail=-1 --prefix | grep "Agent .* started"
```

```text
[pod/movielog-54bb48b5b7-f6wzm/movielog] ... Application Insights Java Agent 3.7.10 started successfully
[pod/movielog-54bb48b5b7-k8jjm/movielog] ... Application Insights Java Agent 3.7.10 started successfully
```

모든 Pod에서 3.7.10이 시작되면 `movielog_*`가 도착합니다. 이때의 inventory 캡처는
[주제 소개의 수집 절](../index.md#collect)에 있습니다.

### webhook 주입 해제와 2단계 전환 { #webhook-revert }

이미 주입된 Deployment는 annotation 해제와 custom agent 설정을 두 번의 patch로
나눠 적용합니다.

- 실습 클러스터의 `app-monitoring-webhook`은 Pod가 아니라 Deployment의
  CREATE·UPDATE에 동작했습니다. annotation `"false"`와 custom agent 설정을 한 patch로
  넣으면 webhook이 주입 해제를 하면서 `APPLICATIONINSIGHTS_*` 변수를 지우고
  `JAVA_TOOL_OPTIONS`를 주입 전 값으로 되돌려, 새 Pod가 agent 없이 시작합니다.
- 처음부터 custom agent로 배포한다면 annotation `"false"`와 custom 설정을 함께 둔
  manifest로 생성해도 됩니다.
- 관리형 주입으로 돌아갈 때는 `kubectl apply` 대신 `kubectl replace`를 씁니다.
  patch로 넣은 init container와 volume이 `last-applied` 설정에 없어 남고, webhook이
  주입하는 volume mount와 겹쳐 `mountPath ... must be unique`로 거부되기 때문입니다.

이 동작은 공식 문서에 기술된 계약이 아니라 2026-11-06 실습에서 관측한 결과입니다.
적용 뒤에는 항상 Pod의 init container image와 agent 시작 로그를 확인합니다.

관리형 image가 3.7.9 이상이 되면 다음 명령으로 관리형 주입으로 돌아갑니다.

```bash
envsubst < k8s/20-movielog.yaml | kubectl replace -f -
# replace는 manifest의 replicas: 1로 되돌리므로 다시 늘립니다.
kubectl scale deploy/movielog -n movielog --replicas=2
```

## Copilot 대시보드 작업 단계: probe → build → verify → look { #agent-method }

이 절은 GitHub Copilot이 skill 지침에 따라 수행하는 probe → build → verify → look
각 단계의 query와 통과 기준입니다. 단계별 목적은
[주제 소개의 Copilot 절](../index.md#agent)에 있습니다.

[`samples/movielog-app`](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app)에는 [`grafana-metrics-dashboard`](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app/.github/skills/grafana-metrics-dashboard) skill이 들어
있습니다. 이 폴더를 VS Code workspace로 열거나 skill 폴더를 자기 저장소의
`.github/skills/`에 복사한 뒤, Copilot chat에서 다음처럼 요청합니다. skill 지침 전문은
[SKILL.md](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app/.github/skills/grafana-metrics-dashboard/SKILL.md)입니다.

```text
Use the /grafana-metrics-dashboard skill. Application Insights rg-movielog-lab/appi-movielog-lab의
movielog_ 지표로 Grafana <grafana-name>에 대시보드를 만들어 줘.
```

위 형태는 Copilot CLI 문서가 안내하는 skill 지정 방식이며, 실습의 Copilot CLI 테스트에서
이 형태를 썼습니다. VS Code chat에서는 `/grafana-metrics-dashboard`로 시작하는 slash command로
실행합니다.

Copilot은 둘 중 사용할 수 있는 도구로 작업합니다. 두 경로 모두 실습에서 동작을
확인했습니다.

| 도구 경로 | probe | 반영·확인 |
|---|---|---|
| Managed Grafana MCP (`https://<grafana-endpoint>/api/azure-mcp`) | `amgmcp_query_resource_log` | `amgmcp_dashboard_update`, `amgmcp_dashboard_inspect` |
| 터미널(`az` 로그인) | `az monitor app-insights query` | `az grafana dashboard create`, skill의 `scripts/verify_panels.py`, `scripts/capture.mjs` |

skill에는 무엇을 조회하고 어떻게 판단할지만 적혀 있고, 조회 KQL은 Copilot이 짭니다.
스크립트는 두 가지만 들어 있습니다.

- `verify_panels.py`: Grafana macro와 변수를 풀어 모든 panel query를 실행합니다. 올리기 전의
  JSON도 검사하고, 브라우저가 실행하지 않는 접힌 row 안의 panel도 검사합니다.
- `capture.mjs`: Entra token으로 이미 올린 dashboard 화면을 캡처하고, 화면에 보이는 오류와
  식별자를 검사합니다.

Managed Grafana MCP는 VS Code의 GitHub Copilot에서 Entra OAuth로 연결합니다. sample의
`.vscode/mcp.json`에서 `<grafana-endpoint>`만 바꿉니다.
`amgmcp_query_resource_log`는 시간 범위를 보내지 않고 `$__timeFilter`, `$__timeTo()` 같은
Grafana macro를 거부하므로 query 안에 `ago(...)`와 `now()`를 직접 씁니다.

아래 명령은 `samples/movielog-app` 폴더에서 Copilot이 터미널로 실행하는 것과 같은 형태입니다.
각 probe 절의 KQL은 실습에서 쓴 예시이며 `--analytics-query`에 넣습니다.

```bash
SKILL=.github/skills/grafana-metrics-dashboard/scripts
APP_ID="$(az monitor app-insights component show -g $RG -a appi-movielog-lab --query appId -o tsv)"
az monitor app-insights query --app "$APP_ID" --offset 1h --analytics-query '<KQL>' -o table
```

### probe 1: inventory와 지표 도착 여부 { #probe-inventory }

inventory로 지표가 실제로 오는지부터 확인합니다.

```kusto
customMetrics
| where timestamp > ago(30m)
| summarize rows = count(), firstSeen = min(timestamp), lastSeen = max(timestamp),
            instances = dcount(cloud_RoleInstance)
    by name, cloud_RoleName
| order by name asc
```

prefix 지표가 없으면 대시보드 작업을 멈추고 주입된 Java agent 버전, annotation,
allowlist를 먼저 확인합니다. 실습의 3.7.7-aks 구간이 이 경우였습니다.
inventory는 `cloud_RoleName`(`movielog`)도 알려 줍니다. dashboard의 `role` 변수에
이 값을 씁니다.

`az monitor app-insights query`는 query의 시간 조건과 별개로 `--offset`(기본 1시간) 안만
조회합니다. 지난 실습 구간을 다시 probe하려면 `--offset 3d`처럼 범위를 넓히고 query의
`ago(30m)`를 `between (datetime(<start>) .. datetime(<end>))`로 바꿉니다.

inventory의 이름 목록은 코드의 meter 목록과 비교합니다. 코드에는 있는데 inventory에
없는 meter는 대시보드에 넣기 전에 원인을 확인합니다.

- 그 meter를 만드는 이벤트가 구간 안에 실제로 일어났는지 확인합니다. 처음 사용할 때
  등록되는 meter는 트래픽이 없으면 행도 없습니다. 실습에서는 load generator가 검색,
  리뷰, 댓글, 가입을 모두 호출하도록 구성했습니다.
- 배포된 image가 그 meter를 포함한 코드로 빌드됐는지 확인합니다.
- 허용 목록(`management.metrics.enable.*`)에 meter prefix가 들어 있는지 확인합니다.

현재 sample 코드와 load generator로는 비즈니스 지표 14개가 모든 Pod에서 도착합니다.

### probe 2: dimension 값 개수와 사용 가능한 축 { #probe-dimensions }

dimension 값 개수로 panel에 쓸 수 있는 축을 고릅니다.

```kusto
customMetrics
| where timestamp > ago(30m)
| where name startswith "movielog_"
| mv-expand dim = bag_keys(customDimensions) to typeof(string)
| extend value = tostring(customDimensions[dim])
| summarize distinctValues = dcount(value), sampleValues = make_set(value, 8) by name, dim
```

```text
name                            dim          distinctValues  sampleValues
movielog_movie_views            channel      2               ["web","api"]
movielog_reviews_posted         verdict      2               ["rotten","fresh"]
movielog_movie_catalog_lookups  outcome      1               ["cache_hit"]
movielog_*                      application  1               ["spring-sample"]
```

`channel`, `verdict`, `outcome`은 값이 고정된 축이라 panel 분할에 씁니다.
`application`은 모든 meter에 붙은 공통 tag라 값이 하나뿐이므로 쓰지 않습니다.
값 개수가 계속 늘어나는 dimension이 보이면 대시보드가 아니라 코드를 고칠
대상입니다.

### probe 3: 값 모양과 metric별 집계식 { #probe-value-shape }

값 모양을 보고 metric마다 집계식을 정합니다.

```kusto
customMetrics
| where timestamp > ago(30m)
| where name startswith "movielog_"
| where isnotempty(cloud_RoleInstance)
| summarize rows = count(), instances = dcount(cloud_RoleInstance),
            maxValueCount = max(valueCount),
            minValue = min(value), maxValue = max(value),
            sumValueSum = sum(valueSum), sumValueCount = sum(valueCount)
    by name
| extend rowsPerInstancePerMin = round(rows * 1.0 / instances / 30, 2)
```

실습 30분 구간(09:50~10:20 UTC)의 결과 일부입니다. 이 구간에는 agent 전환으로
Pod가 교체되어 instance가 3개로 보입니다.

```text
name                     rows  instances  maxValueCount  minValue  maxValue  sumValueSum  sumValueCount
movielog_movie_views     112   3          1              0         210       12316        112
movielog_review_rating   55    2          71             21.5      255       7456.5       2124
movielog_members_stored  56    3          1              759       3948      123846       56
```

| 관측 | 의미 | 집계식 |
|---|---|---|
| 모든 행이 `valueCount` = 1, `value`가 0부터 증가량 크기 | Counter: export 간격(60초)의 증가량 | `sum(value)` |
| `maxValueCount` > 1, `valueSum`이 합계 | DistributionSummary: 간격 안 기록 수와 합계 | `sum(valueSum) / sum(valueCount)` |
| `*_stored`가 두 Pod에서 같은 값 | Gauge: 각 Pod가 같은 DB `count(*)`를 보고 | Pod 간 `max(value)`, sum 금지 |
| Pod·series별 1분에 1행 | export 간격 60초 | bin은 `max_of($__interval, 1m)` 이상 |

Counter도 `valueCount`가 비어 있지 않고 1로 들어옵니다. 따라서 `valueCount`가
있는지가 아니라 1보다 큰 값이 있는지로 분포 meter를 구분합니다. 기록이 드문
DistributionSummary·Timer는 모든 간격이 1일 수도 있으므로 `maxValueCount` = 1이면
코드의 meter 종류로 한 번 더 확인합니다.

`movielog.review.rating`은 별점을 `stars` 단위로 기록합니다. 위 결과의 평균은
7456.5 / 2124 ≈ 3.5개입니다. 행 단위 `avg(value)`를 쓰면 기록 수가 다른 간격이 같은
가중치를 받아 왜곡됩니다.

### build: panel별 질문·집계식과 dashboard JSON { #build }

panel마다 답할 질문과 집계식을 먼저 정한 뒤 JSON을 만듭니다.

MovieLog 대시보드(`grafana/movielog-dashboard.json`)의 panel별 집계식과 시각화는 다음과
같습니다.

| panel | 질문 | 집계식 | 시각화 |
|---|---|---|---|
| 영화 조회, 새 리뷰, 신규 회원 | 기간 동안 몇 건인가 | bin별 `sum(value)`의 구간 합계 | stat + sparkline |
| 평균 별점 | 리뷰 품질이 기준 이상인가 | `sum(valueSum) / sum(valueCount)` | gauge(3.5개부터 초록) |
| 리뷰 판정 비율 | 긍정 리뷰 비율은 | `verdict`별 `sum(value)` | donut |
| 분당 영화 조회, 분당 새 리뷰 | 채널·판정별 처리량은 | bin별 `sum(value) / (bin / 1m)` | 누적 area, 누적 bar |
| 활동별·채널별 합계 | 어느 활동·채널이 많은가 | 활동·`channel`별 `sum(value)` | bar gauge |
| 평균 별점 추이 | 리뷰 품질이 변했는가 | bin별 `sum(valueSum) / sum(valueCount)` | line + threshold 배경 |
| 카탈로그 영화, 저장된 리뷰·댓글, 가입 회원 | 누적 규모와 추이는 | bin별 Pod 간 `max(value)`의 마지막 값 | stat + sparkline |
| Pod별 영화 조회 분포 | 트래픽이 한 Pod에 몰리는가 | `cloud_RoleInstance`별 `sum(value)` | bar gauge |
| 외부 조회 결과 | 카탈로그·검색이 어떻게 끝나는가 | `outcome`별 `sum(value)` | bar gauge |
| Pod별 누락 metric 수 | Pod마다 빠진 지표가 없는가 | 상시 meter 목록 11개 − bin별 목록 내 `dcount(name)` | status history(0 초록, 1 이상 빨강) |
| metric 수신 상태 | 구간 끝에서 끊기지 않았는가 | 구간 끝 10분 행 수와 구간 끝 기준 마지막 수신 후 경과 초 | table |

```kusto
customMetrics
| where $__timeFilter(timestamp)
| where cloud_RoleName == ${role:singlequote}   // 입력값을 KQL 문자열로 안전하게 감쌈
| where name == "movielog_reviews_stored"
| where timestamp < bin(now(), max_of($__interval, 1m))   // 채워지는 중인 현재 bin 제외
| summarize stored = max(value) by bin(timestamp, max_of($__interval, 1m))   // Pod 간 sum 금지
| order by timestamp asc
```

stat panel은 같은 bin 시계열을 받아 마지막 값이나 합계로 줄이고, 배경에
sparkline을 그립니다. 숫자 하나와 추이를 한 칸에 담으므로 같은 지표의 꺾은선
panel을 따로 둘 필요가 없습니다.

누락 metric 수의 기대 목록은 수신 데이터에서 추론하지 않고 코드 기준으로 고정합니다.
`BusinessMetrics`가 시작 때 0으로 등록하는 Counter 7개와 DB Gauge 4개가 대상입니다.

- 받은 데이터에서 목록을 만들면 모든 Pod에서 빠진 meter는 목록에서도 빠져 0(초록)으로
  보입니다.
- `valueCount`로 Counter를 고르면 간격마다 한 번씩만 기록된 분포 meter가 섞입니다.
- 처음 사용할 때 생기는 Counter(검색, 카탈로그 조회)와 DistributionSummary는 목록에서
  뺍니다. 분포 meter는 기록이 없는 간격에 행을 보내지 않으므로, 목록에 넣으면 한산한
  시간에 빨간 칸이 생깁니다.
- meter를 추가하거나 등록 방식을 바꾸면 "Pod별 누락 metric 수" panel query의 기대 목록
  (`let steady = dynamic([...])`)도 함께 고칩니다.

칸이 비어 있으면 그 Pod가 그 bin에 아무 지표도 보내지 않은 것입니다. 교체된 Pod도
종료 뒤에는 빈 칸으로 남습니다.

### verify: Grafana 전체 panel query 실행 { #verify }

dashboard를 올리기 전에 모든 panel query를 Grafana에서 실행해 오류와 빈 결과가 없는지
확인합니다.

`verify_panels.py`는 dashboard의 모든 query를 Managed Grafana의
`/api/ds/query`로 실행합니다. Grafana data plane API는 audience
`https://dashboard.azure.com`의 Entra access token으로 호출합니다. 호출자에게는
Grafana Viewer 이상 역할이 필요합니다.

```bash
export GRAFANA_URL="$(az grafana show -g $RG -n "$GRAFANA" --query properties.endpoint -o tsv)"
export GRAFANA_TOKEN="$(az account get-access-token --resource https://dashboard.azure.com --query accessToken -o tsv)"
python3 $SKILL/verify_panels.py grafana/movielog-dashboard.json --appinsights-id "<app-insights-resource-id>"
# 클러스터를 멈춘 뒤 지난 구간을 검증할 때는 절대 범위를 줍니다.
python3 $SKILL/verify_panels.py grafana/movielog-dashboard.json --appinsights-id "<app-insights-resource-id>" \
  --from 2026-11-07T23:05:00Z --to 2026-11-07T23:35:00Z
```

통과 기준은 다음과 같습니다. 모든 panel이 `OK`일 때만
`az grafana dashboard create --overwrite true`로 올립니다.

- 접힌 row 안의 panel까지 모든 query를 실행합니다.
- HTTP 오류와 0행은 실패입니다. 숫자 field가 모두 null인 행도 데이터가 없는 것으로
  봅니다. 0은 정상 값입니다.
- 구간 끝만 보는 panel(예: metric 수신 상태)이 HTTP 오류 없이 0행을 돌려주면 query보다
  최근 수집 중단을 먼저 의심하고 inventory를 확인합니다. HTTP 오류라면 다른 panel과
  같이 query부터 고칩니다.
- KQL 예약어(`views`, `first` 등)를 column 이름으로 쓰면 parse 오류(HTTP 400)가 납니다.
  column 이름은 `movieViews`처럼 예약어가 아닌 이름으로 짓습니다.

### look: 렌더링 화면 캡처와 시각 점검 { #look }

query가 모두 성공해도 색, legend, panel 간 합계는 렌더링한 화면에서만 확인할 수
있습니다. Copilot이 대시보드를 캡처해 직접 보고 아래 기준을 점검하게 합니다.

`capture.mjs`는 같은 Entra token을 Grafana origin 요청에만 bearer header로 붙여
headless Chromium에서 dashboard를 캡처합니다.

- redirect는 따라가지 않고 브라우저에 돌려주므로 다른 origin(예:
  `js.monitor.azure.com`)으로 token이 넘어가지 않습니다.
- 대화형 로그인이나 service account가 필요 없습니다.
- Grafana 내부 scroll 높이를 재서 viewport를 늘리므로 아래쪽 panel까지 한 장에
  담깁니다. `fullPage` 옵션만으로는 내부 scroll 영역이 잘립니다.
- panel 로딩이 60초 안에 끝나지 않거나, 렌더링된 panel의 query가 실패하거나, 화면에
  `No data`·`Invalid date`나 subscription·resource 식별자가 보이면 실패로 종료합니다.
- 검사 범위는 브라우저가 렌더링한 panel뿐입니다. 접힌 row 안의 panel은 브라우저가 query를
  실행하지 않으므로, 접힌 row를 포함한 전체 query 검증은 [verify](#verify) 단계의
  `verify_panels.py`가 맡습니다.
- 오류 메시지는 token과 `authorization` header를 가린 첫 줄만 출력합니다.
- panel 간 합계를 비교하거나 문서에 남길 캡처는 분 단위로 맞춘 절대 범위
  (`from`·`to` epoch ms)로 찍습니다. `now-30m` 같은 상대 범위는 panel마다 조회
  시각이 달라 1분 bin 하나만큼 합계가 어긋날 수 있습니다.

캡처에서 점검할 항목과 대시보드 JSON에 미리 넣어 둘 설정은 다음과 같습니다.
`grafana/movielog-dashboard.json`은 이 설정을 모두 반영합니다.

| 점검 항목 | 대시보드 설정 |
|---|---|
| subscription ID 같은 식별자가 화면에 보이지 않는가 | Application Insights resource ID 변수는 값을 채운 배포용 JSON에서 숨김 |
| 정상 값이 경고색으로 보이지 않는가 | 건수 stat은 고정색, 크기만 비교하는 bar gauge는 중립 색 구간. 의미 있는 기준이 있는 값(평균 별점)에만 threshold 색 |
| legend와 이름이 읽히는가 | `displayName`에 dimension label 사용. bar gauge는 이름을 bar 위에 두고 행 높이를 32px 이상으로 고정 |
| 시계열 끝이 급락하지 않는가 | 모든 panel query에서 채워지는 중인 현재 bin 제외(`where timestamp < bin(now(), <bin>)`) |
| 같은 지표의 합계가 panel마다 같은가 | stat, donut, bar gauge 모두 같은 bin 범위와 집계식 사용 |
| 질문에 맞는 시각화인가 | [질문 유형별 panel 시각화](../index.md#visualization) 기준으로 선택 |

threshold 경계 근처 값은 표시 자릿수 때문에 숫자와 색이 어긋나 보일 수 있습니다(예:
3.4996이 3.50으로 표시되지만 3.5 기준 미만 색). 경계값은 tooltip이나 query로 실제
값을 확인합니다.

## 대시보드 반영 실습: 로컬 Copilot 직접 반영과 JSON import { #publish }

같은 dashboard를 로컬 Copilot이 직접 반영하는 방법과, JSON 파일로 추출해 import하는
방법을 모두 실행했습니다(2026-11-07). 두 방식의 선택 기준은
[주제 소개의 반영 방식](../index.md#publish)에 있습니다. 아래 명령은
`samples/movielog-app` 폴더에서 실행합니다.

### 로컬 Copilot 직접 반영 { #publish-direct }

CLI로 반영할 때는 Application Insights resource ID를 채운 JSON을 만들어 바로
올립니다. 이 JSON은 resource ID 변수를 숨기고 값을 채우므로 저장소에 커밋하지
않습니다.

```bash
AIID="$(az monitor app-insights component show -g $RG -a appi-movielog-lab --query id -o tsv)"
python3 - "$AIID" > /tmp/movielog-live.json <<'EOF'
import json, sys
d = json.load(open("grafana/movielog-dashboard.json", encoding="utf-8"))
for v in d["templating"]["list"]:
    if v["name"] == "appinsights":
        v.update(query=sys.argv[1], current={"text": sys.argv[1], "value": sys.argv[1]}, hide=2)
json.dump(d, sys.stdout, ensure_ascii=False)
EOF
az grafana dashboard create -g $RG -n "$GRAFANA" \
  --definition @/tmp/movielog-live.json --overwrite true
rm /tmp/movielog-live.json
```

Managed Grafana MCP를 쓰면 Copilot이 `amgmcp_dashboard_update`로 전체 JSON을
만들거나 바꾸고(`dashboard`), 일부만 고칠 때는 JSONPath patch(`dashboardUid` +
`operations`)를 보냅니다. 실습에서는 probe용 dashboard의 제목을 patch하고
`amgmcp_dashboard_inspect`(`jsonPath: "$.title"`)로 바뀐 값을 확인한 뒤 되돌렸습니다.

```json
{
  "dashboardUid": "movielog-agent-probe",
  "operations": [
    { "op": "replace", "path": "$.title", "value": "agent probe - customMetrics inventory (mcp update test)" }
  ]
}
```

### JSON 추출과 Grafana import { #publish-import }

1. **가져갈 JSON을 준비합니다.** 저장소의 [`grafana/movielog-dashboard.json`](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app/grafana/movielog-dashboard.json)은
   변수 값이 빈 범용 JSON입니다. 이미 검증한 dashboard를 가져가려면 Grafana의 공유 메뉴에서
   **Export > Save to file**을 쓰거나 CLI로 내보냅니다.

    ```bash
    az grafana dashboard show -g $RG -n "$GRAFANA" \
      --dashboard movielog-business-metrics --query dashboard -o json > movielog-export.json
    ```

2. **Export한 JSON에서 환경 값을 지웁니다.** 실습 Export에서는 `appinsights`
   변수에 이 환경의 resource ID가 세 군데 들어 있었습니다. 아래 명령으로 지운 뒤
   0건이 되는지 확인하고 커밋합니다.

    ```bash
    python3 - <<'EOF'
    import json
    d = json.load(open("movielog-export.json"))
    for v in d["templating"]["list"]:
        if v["name"] == "appinsights":
            v["query"] = ""
            v["current"] = {"text": "", "value": ""}
            v["hide"] = 0
    d.pop("id", None)
    json.dump(d, open("movielog-export.json", "w"), ensure_ascii=False, indent=2)
    EOF
    grep -c "/subscriptions/" movielog-export.json   # 0
    ```

3. **대상 Grafana로 import합니다.** 포털에서는 대상 Grafana의
   **Dashboards > New > Import**에서 JSON 파일을 올리거나 붙여 넣고, folder와 UID를
   확인한 뒤 **Import**를 누릅니다. CLI는 다음과 같습니다. import는 JSON의 UID를
   그대로 쓰므로, `--overwrite true`는 대상에 있는 같은 UID의 dashboard를 의도적으로
   바꿀 때만 붙입니다.

    ```bash
    TARGET_RG="<target-resource-group>"; TARGET_GRAFANA="<target-grafana-name>"
    az grafana dashboard import -g "$TARGET_RG" -n "$TARGET_GRAFANA" \
      --definition movielog-export.json
    ```

    Export한 Grafana와 같은 곳에 import하면 원본이 변수 값이 빈 사본으로 바뀝니다.
    같은 Grafana에서 시험하려면 UID와 제목을 먼저 바꿉니다. 입력은 Export해
    정리한 파일이나 저장소의 범용 JSON 중 어느 것이든 됩니다.

    ```bash
    python3 - <<'EOF'
    import json
    d = json.load(open("movielog-export.json"))
    d["uid"] = "movielog-import-test"
    d["title"] += " (import test)"
    json.dump(d, open("movielog-import-test.json", "w"), ensure_ascii=False)
    EOF
    az grafana dashboard import -g $RG -n "$GRAFANA" --definition movielog-import-test.json
    ```

4. **변수를 채우고 저장합니다.** import 직후에는 `appinsights`가 비어 있어 panel이
   비어 보입니다. 변수 막대에 Application Insights resource ID를 넣고 dashboard를
   저장해야 값이 유지됩니다. URL에 `?var-appinsights=<URL 인코딩한 resource ID>`를
   붙이는 방법은 그 화면에서만 적용되므로 확인용으로 씁니다. `role`은
   `customMetrics`의 `cloud_RoleName`입니다.
5. **결과를 확인합니다.** skill의 `verify_panels.py`로 query를 실행하고
   `capture.mjs`로 화면을 캡처합니다.

실습에서는 두 작업을 따로 실행했습니다. 먼저 live dashboard를 Export하고 2단계
명령으로 resource ID 3건이 0건이 되는 것을 확인했습니다. import는 저장소의 범용
JSON(`grafana/movielog-dashboard.json`)을 입력으로 위 명령처럼 UID와 제목을 바꿔
`--overwrite` 없이 같은 Grafana에 가져왔습니다. 질문 유형별 시각화로 바꾼 JSON으로
다시 실행한 결과는 `status: success`, panel 20개(row 3개와 query panel 17개)였고,
`var-appinsights`로 변수를 채우자 원본과 같은 값이 나왔습니다. 확인 뒤 테스트
dashboard는 삭제했습니다. 포털 import 절차는 Microsoft Learn 문서 기준이며
실습에서는 CLI로 실행했습니다. 아래 캡처는 resource ID가 보이는 변수 막대를
잘라냈습니다.

![JSON import 후 변수를 채운 대시보드 상단. 영화 조회 12.9K, 새 리뷰 2.30K, 신규 회원 3.24K stat과 sparkline, 평균 별점 3.52 gauge, fresh 67% donut, 채널별 누적 area와 판정별 막대](../images/json-import-result.png)

## 실습 결과: 판정 기준과 실측값 { #result }

실습 결과는 아래 기준과 실측값으로 판정합니다. 수정을 마친 대시보드 캡처는
[주제 소개](../index.md#message)에 있습니다. 이 캡처는 현재 sample 코드로 빌드한
`movielog:1.0.1` image의 2026-11-07 23:05~23:35 UTC 구간이며, 화면의 시각은
브라우저 시간대(KST)로 표시됩니다.

| 확인 항목 | 기대 | 실측 |
|---|---|---|
| 관리형 주입 agent | 3.7.9 미만이면 custom meter 없음 | `3.7.7-aks`, `movielog_*` 0건 |
| custom init agent | 3.7.10 시작, custom meter 도착 | 시작 로그 확인, 12개 이름 × 2 instance. 검색 수정 뒤 13개, 현재 코드 image에서 14개 |
| export 주기 | Pod·series별 1분 1행 | MCP 조회 15분 동안 `movie_views` 60행(2 series × 2 Pod × 15) |
| allowlist | `jvm_*`, `http_server_requests` Micrometer 지표 없음 | 없음. agent 기본 JVM 지표와 `http.server.request.duration`만 별도로 존재 |
| dashboard query | 17개 모두 데이터 반환 | `verify_panels.py` 17/17 OK |
| 화면 점검 | 식별자 없음, panel 간 합계 일치, 누락 metric 0 | 영화 조회 12,958 = 채널 6.51K + 6.45K = Pod 6.53K + 6.43K, 두 Pod 모든 bin 누락 0 |

- Pod별 영화 조회 분포는 Pod가 교체될 때마다 달라집니다. 로그인 세션 때문에 Service에
  `sessionAffinity: ClientIP`를 두어 합성 사용자 Pod마다 한 앱 Pod에 고정되기
  때문입니다. 합성 사용자를 앱 replica보다 충분히 많이 두어야 분포가 고르게 나옵니다.
- 활동별·채널별 합계에서 `리뷰 작성 · web`과 `댓글 · web`은 0입니다. 0으로 미리 등록한
  counter이고, 합성 사용자는 API로만 리뷰와 댓글을 씁니다.

## 수집 비용: meter × tag 조합 × Pod 수 { #cost }

수집 비용은 meter × tag 조합 × Pod 수에 비례해 늘어납니다.

workspace의 `AppMetrics` table에서 10분(09:50~10:00 UTC) 수집량을 측정했습니다.

| 지표 묶음 | 이름 수 | 분당 행 | 행당 과금 크기 |
|---|---|---|---|
| `movielog_*` (Micrometer) | 12 | 28.8 | 약 408 bytes |
| agent 기본 지표 | 8 | 19.1 | 약 403 bytes |

`movielog_*`는 Pod 2개 기준 하루 약 4만 1천 행, 약 17 MB입니다. Pod 수,
meter 수, tag 조합 수가 늘면 비례해 늘어납니다.

- Application Insights metric은 수집 데이터 크기로 과금됩니다.
- Metrics explorer에서 dimension을 유지하는 **With dimensions** 설정은 custom
  metrics 요금이 추가로 발생합니다. KQL dashboard만 쓴다면 켤 필요가 없습니다.
- 수집 간격은 agent의 `metricIntervalSeconds`로 바꿀 수 있지만 dashboard의 최소
  bin도 함께 늘려야 합니다.
- 같은 meter를 Actuator Prometheus endpoint와 Managed Prometheus로도 수집하면
  두 저장소에 각각 비용이 발생합니다. 한 경로만 기준으로 둡니다.

## 대표 오류와 대응 { #troubleshooting }

| 증상 | 원인 | 조치 |
|---|---|---|
| request는 보이지만 `movielog_*`가 없음 | 주입된 agent가 3.7.9 미만 | init container image 확인 후 [Java agent 버전 확인](#version-gate) 적용 |
| custom agent patch 뒤 agent가 시작하지 않음 | webhook이 주입 해제하며 `APPLICATIONINSIGHTS_*` 삭제 | annotation `"false"`를 먼저 적용한 뒤 custom patch |
| 관리형으로 되돌리는 `kubectl apply`가 `mountPath ... must be unique` | patch로 넣은 init container·volume이 남아 webhook 주입과 충돌 | `kubectl replace`로 manifest 전체 교체 |
| `az acr build`가 `layer does not exist`로 실패 | classic builder에서 빈 layer나 같은 내용의 layer가 연속 | sample Dockerfile처럼 layer마다 다른 marker 파일 추가 |
| `az grafana create` 뒤 Grafana 로그인·조회 실패 | 자동 role assignment 실패 | Grafana Admin, Monitoring Reader를 직접 할당 |
| panel 하나가 400 | KQL 예약어(`views`, `first` 등)를 column 이름으로 사용 | column 이름 변경 후 `verify_panels.py` 재실행 |
| Grafana API 401 | token audience나 Grafana 역할 누락 | `--resource https://dashboard.azure.com`, Grafana 역할 확인 |
| 누적 수치가 Pod 수배 | DB 기준 gauge를 Pod 간 sum | Pod 간 `max(value)` |

## 정리: resource group 삭제 { #cleanup }

resource group을 삭제하면 모든 실습 자원이 사라집니다.

```bash
az group delete -n $RG --yes --no-wait
```

AKS가 만든 node resource group(`MC_...`)도 함께 삭제됩니다. 삭제 완료 뒤
`az group exists -n $RG`가 `false`인지 확인합니다.

## 검증 범위 { #verification }

- 2026-11-06 Korea Central에서 AKS, Application Insights, ACR, Managed Grafana를
  만들고 수집과 대시보드 작성 절차를 실행했고, 2026-11-07에 같은 환경에서
  대시보드 반영 절차를 실행했습니다. 같은 날 클러스터를 다시 시작해 질문 유형별
  시각화로 바꾼 대시보드를 배포하고 query 실행과 캡처를 반복했습니다. 이어서 현재
  sample 코드로 빌드한 `movielog:1.0.1` image를 같은 Deployment에 배포하고
  (`kubectl set image`, custom agent 3.7.10 유지) 2026-11-07 23:05~23:35 UTC 구간을
  다시 캡처했습니다. 캡처는 모두 이 실습 환경에서 얻었습니다.
- Microsoft Learn에서 AKS 자동 계측, Java Micrometer 자동 수집과 이름 변환,
  export 간격, custom metric 저장과 비용, Managed Grafana data source 권한,
  data plane API 인증, MCP endpoint, dashboard import·export를 원문 전체로
  대조했습니다.
- meter 종류별 column 매핑은 Application Insights Java 3.7.10 source로
  확인했습니다.
- 2026-11-10에 `grafana-metrics-dashboard` skill을 GitHub Copilot CLI 1.0.95로 실 환경에서
  실행했습니다. 클러스터는 정지 상태였으므로 2026-11-07 23:05~23:35 UTC 구간의 수집
  데이터와 실습 Managed Grafana를 썼습니다. `grafana/` 폴더 없이 앱 코드와 skill만 둔
  작업 공간에서도 Copilot이 probe부터 look까지 수행해 17개 panel 대시보드를 올렸습니다.
  모든 query가 통과했고, 합계가 실습 결과(영화 조회 12,958, 평균 별점 3.50, 누락 metric 0)와
  같았습니다. 이 실행에서 드러난 `capture.mjs` 오류 출력의 token 노출과 fetch timeout,
  저장 시간 형식 지침을 고친 뒤, `verify_panels.py --from/--to`와 `capture.mjs`를 같은
  환경에서 다시 실행해 확인했습니다. 이어서 skill에서 조회 KQL 예시를 빼고 판단 기준만 남긴
  상태로 다시 실행했고, Copilot이 직접 짠 조회로 같은 집계식과 합계에 도달했습니다.
- 같은 날 일부러 고장 낸 dashboard로 두 스크립트를 비교했습니다. KQL 예약어 문법 오류는
  둘 다 잡았고, 접힌 row 안의 빈 panel은 `verify_panels.py`만 잡았습니다.
- Deployment webhook의 주입 해제 동작, `kubectl apply` 충돌, role assignment
  실패는 실습 관측이며 공식 동작 계약이 아닙니다. 문서의 두 단계 전환과
  `kubectl replace` 복귀는 관리형 → custom → 관리형 → custom 순서로 다시 실행해
  확인했습니다.
- MovieLog test suite는 JDK 25에서 통과했습니다.
- 대시보드 반영은 2026-11-07 실습 Grafana에서 `az grafana dashboard create`,
  MCP `amgmcp_dashboard_update` patch와 원복, `az grafana dashboard show` Export와
  환경 값 제거(resource ID 3건 → 0건), 저장소 범용 JSON의 UID·제목을 바꾼
  `az grafana dashboard import`를 실행해 확인했습니다.

## 관련 가이드

- [AKS Java Micrometer custom metric 누락 임시 대응](../../aks-java-micrometer-custom-metrics/index.md)

## 공식 참고 자료

- [Autoinstrument AKS apps with Azure Monitor Application Insights](https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless)
- [Configure Azure Monitor Application Insights for Java](https://learn.microsoft.com/azure/azure-monitor/app/java-standalone-config)
- [Add and modify OpenTelemetry for .NET, Java, Node.js, and Python applications](https://learn.microsoft.com/azure/azure-monitor/app/opentelemetry-add-modify)
- [Metrics in Application Insights](https://learn.microsoft.com/azure/azure-monitor/app/metrics-overview)
- [Azure Monitor and Prometheus](https://learn.microsoft.com/azure/azure-monitor/metrics/prometheus-metrics-overview)
- [Grant Azure Monitor access to Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-permissions)
- [How to manage data sources in Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-data-source-plugins-managed-identity)
- [Authenticate to Azure Managed Grafana data plane APIs with Microsoft Entra ID](https://learn.microsoft.com/azure/managed-grafana/how-to-authenticate-data-plane-api)
- [Configure an Azure Managed Grafana remote MCP server](https://learn.microsoft.com/azure/managed-grafana/grafana-mcp-server)
- [Dashboards with Grafana in Application Insights](https://learn.microsoft.com/azure/azure-monitor/app/grafana-dashboards)
- [Create a dashboard in Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-create-dashboard)
- [Migrate to Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-migrate)
- [Application Insights Java 3.7.10 AzureMonitorMeterRegistry source](https://github.com/microsoft/ApplicationInsights-Java/blob/3.7.10/agent/instrumentation/micrometer-1.0/src/main/java/io/opentelemetry/javaagent/instrumentation/micrometer/ai/AzureMonitorMeterRegistry.java)
- [Application Insights Java 3.7.10 AzureMonitorNamingConvention source](https://github.com/microsoft/ApplicationInsights-Java/blob/3.7.10/agent/instrumentation/micrometer-1.0/src/main/java/io/opentelemetry/javaagent/instrumentation/micrometer/ai/AzureMonitorNamingConvention.java)
- [Grafana Azure Monitor query editor](https://grafana.com/docs/grafana/latest/datasources/azure-monitor/query-editor/)
