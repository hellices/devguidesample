# MovieLog on AKS: Micrometer → Application Insights → Grafana

영화 리뷰 앱 MovieLog(Spring Boot 4.1.2, Java 25)의 `movielog.*` Micrometer
지표를 AKS autoinstrumentation agent로 `customMetrics`에 보내고, agent가 실제
데이터를 조회해 Grafana 대시보드를 만들고 검증하는 실습 sample입니다.

## 구성

| 경로 | 용도 |
|---|---|
| `src/main/java/.../metrics/` | 도메인 이벤트를 `movielog.*` Counter·DistributionSummary·Gauge로 기록합니다. |
| `src/main/resources/application-aks.properties` | PostgreSQL 연결, seed, Actuator `health`만 노출, `movielog` allowlist입니다. |
| `src/main/resources/db/aks-seed.sql` | TMDB API key 없이 영화 상세가 동작하도록 영화 12편을 넣습니다. |
| `Dockerfile` | jlink + distroless 실행 image입니다. ACR Tasks용 layer marker를 포함합니다. |
| `agent-init/Dockerfile` | checksum을 고정한 Application Insights Java 3.7.10 init image입니다. |
| `k8s/00-postgres.yaml` | 실습용 PostgreSQL입니다. 데이터는 `emptyDir`라 container 재시작에는 유지되고 Pod가 삭제·교체되면 사라집니다. 두 Pod가 겹치지 않게 `Recreate`로 교체합니다. |
| `k8s/10-instrumentation.yaml` | per-deployment `Instrumentation` CR입니다. |
| `k8s/20-movielog.yaml` | `inject-java` annotation을 단 앱 Deployment와 Service입니다. |
| `k8s/21-agent-3.7.10.patch.yaml` | managed agent가 3.7.9 미만일 때 쓰는 3.7.10 init image patch입니다. |
| `k8s/30-loadgen.yaml`, `loadgen/loadgen.py` | 가입·조회·리뷰·댓글을 반복하는 합성 사용자 6개입니다. |
| `agent/*.kql`, `agent/kql.sh` | inventory, dimensions, value shape probe query입니다. |
| `agent/build_dashboard.py` | probe에서 정한 집계식으로 dashboard JSON을 만듭니다. |
| `agent/verify_panels.py` | 모든 panel query를 Grafana `/api/ds/query`로 실행해 빈 panel을 찾습니다. |
| `agent/capture.mjs` | Entra access token으로 Managed Grafana 화면을 headless 캡처합니다. |
| `agent/prompt.md` | agent에게 probe → build → verify → look 순서를 시키는 prompt입니다. |
| `grafana/movielog-dashboard.json` | import용 dashboard입니다. |

## 로컬 test

```bash
./gradlew test
```

JDK 25가 필요합니다.

## 배포

상위 문서의 순서를 따릅니다. 핵심 명령은 다음과 같습니다.

```bash
RG="<resource-group>"; ACR="<acr-name>"; AI="<app-insights-name>"; GRAFANA="<grafana-name>"
ACR_SERVER="$(az acr show -n "$ACR" --query loginServer -o tsv)"

az acr build -r "$ACR" -t movielog:1.0.0 --platform linux/amd64 .
az acr build -r "$ACR" -t observability/applicationinsights-agent:3.7.10 \
  --platform linux/amd64 agent-init

kubectl apply -f k8s/00-postgres.yaml
kubectl create secret generic movielog-db -n movielog \
  --from-literal=username=movielog --from-literal=password="$(openssl rand -base64 24)"

export APPLICATIONINSIGHTS_CONNECTION_STRING="$(az monitor app-insights component show \
  -g "$RG" -a "$AI" --query connectionString -o tsv)"
export APP_IMAGE="$ACR_SERVER/movielog:1.0.0"
envsubst < k8s/10-instrumentation.yaml | kubectl apply -f -
envsubst < k8s/20-movielog.yaml | kubectl apply -f -
kubectl rollout status deploy/movielog -n movielog
kubectl scale deploy/movielog -n movielog --replicas=2

kubectl create configmap loadgen -n movielog --from-file=loadgen/loadgen.py
kubectl apply -f k8s/30-loadgen.yaml
```

주입된 agent가 3.7.9 미만이면(`kubectl get pod ... -o jsonpath='{.spec.initContainers[*].image}'`)
두 단계로 3.7.10 init image로 바꿉니다. 한 번에 patch하면 webhook이 agent 환경
변수를 지웁니다.

```bash
export AGENT_IMAGE="$ACR_SERVER/observability/applicationinsights-agent@$(az acr repository show \
  -n "$ACR" --image observability/applicationinsights-agent:3.7.10 --query digest -o tsv)"
kubectl create secret generic appinsights -n movielog \
  --from-literal=connection-string="$APPLICATIONINSIGHTS_CONNECTION_STRING"
kubectl patch deployment movielog -n movielog --type merge -p \
  '{"spec":{"template":{"metadata":{"annotations":{"instrumentation.opentelemetry.io/inject-java":"false"}}}}}'
kubectl rollout status deploy/movielog -n movielog
envsubst < k8s/21-agent-3.7.10.patch.yaml > /tmp/agent-patch.yaml
kubectl patch deployment movielog -n movielog --type strategic --patch-file /tmp/agent-patch.yaml
kubectl rollout status deploy/movielog -n movielog
kubectl logs -n movielog -l app=movielog -c movielog --tail=-1 --prefix | grep "Agent .* started"
```

처음 배포는 replica 1개로 시작합니다. `ddl-auto=update`가 schema를 만들 때 두
Pod가 동시에 같은 table을 만들려고 경쟁하지 않게 하기 위해서입니다.

## agent toolkit

```bash
cd agent
export APPINSIGHTS_APP_ID="$(az monitor app-insights component show -g "$RG" -a "$AI" --query appId -o tsv)"
./kql.sh 01-inventory.kql
./kql.sh 02-dimensions.kql
./kql.sh 03-value-shape.kql

AIID="$(az monitor app-insights component show -g "$RG" -a "$AI" --query id -o tsv)"
export GRAFANA_URL="$(az grafana show -g "$RG" -n "$GRAFANA" --query properties.endpoint -o tsv)"
export GRAFANA_TOKEN="$(az account get-access-token \
  --resource https://dashboard.azure.com --query accessToken -o tsv)"

python3 build_dashboard.py > ../grafana/movielog-dashboard.json
python3 verify_panels.py ../grafana/movielog-dashboard.json --appinsights-id "$AIID"
python3 build_dashboard.py --appinsights-id "$AIID" > /tmp/live.json
az grafana dashboard create -g "$RG" -n "$GRAFANA" --definition @/tmp/live.json --overwrite true

npm i playwright && npx playwright install chromium-headless-shell
node capture.mjs "/d/movielog-business-metrics/x?orgId=1&from=now-30m&to=now&kiosk" dashboard.png
```

`kql.sh`는 `az monitor app-insights query`의 기본 범위인 최근 1시간만 조회합니다.
지난 구간을 볼 때는 `KQL_OFFSET=12h ./kql.sh ...`처럼 늘립니다. `capture.mjs`는
token을 Grafana origin에만 보내고, 내부 scroll 높이에 맞춰 viewport를 늘리며,
panel 로딩이 60초를 넘으면 실패로 종료합니다.

Grafana token의 audience는 Microsoft Learn의
[Managed Grafana data plane 인증 문서](https://learn.microsoft.com/azure/managed-grafana/how-to-authenticate-data-plane-api)대로
`https://dashboard.azure.com`입니다. 실습 Grafana에서 이 token은 `/api/org`에 200을 받았고,
`https://grafana.azure.com` token은 401로 거부됐습니다.

`--appinsights-id`로 만든 JSON은 resource ID 변수를 숨기므로 저장소에 커밋하지
않습니다.

## 정리

```bash
az group delete -n "$RG" --yes --no-wait
```
