# Azure Monitor Dynamic Thresholds 실습: S2 latency

이 실습은 기존 S2의 `/api/orders` 지연을 재사용해 Dynamic Threshold가 실제
baseline을 학습한 뒤 p95 latency anomaly를 탐지하는 과정을 확인합니다.
정적 S2 rule은 당일 재현용으로 그대로 두고, Dynamic rule은 Action Group을 연결하지 않은 shadow mode로 병렬 운영합니다.

> 이 실습은 최소 3일 동안 Azure 리소스를 유지하므로 비용이 발생합니다.
> 끝나면 반드시 README의 `azd down --purge` 절차로 정리하세요.

## 전체 흐름

```mermaid
flowchart LR
    T[Application Insights<br/>Standard availability test]
    A[Container App<br/>GET /api/orders]
    I[Application Insights]
    W[Log Analytics<br/>AppRequests]
    D[Dynamic Threshold<br/>Log Search alert]
    P[Azure Monitor<br/>learned band]
    F[S2 fault<br/>ORDER_DELAY_MS=4000]

    T -->|5분마다 request| A
    A -->|OpenTelemetry duration| I
    I --> W
    W -->|5분 p95| D
    D --> P
    F --> A
```

## 공식 Preview Chart

[![Azure Monitor Dynamic Threshold preview chart에서 파란 선은 측정값, 파란 영역은 허용 범위, 빨간 점은 범위를 벗어난 값을 보여 줍니다.](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/alerts-dynamic-thresholds/threshold-picture-8bit.png)](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/alerts-dynamic-thresholds/threshold-picture-8bit.png)

*Source: [Create a Log Search alert rule with dynamic threshold](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-dynamic-thresholds).*

## 배포되는 설정

| 항목 | 설정 |
|---|---|
| Baseline | Standard availability test가 한 location에서 `/api/orders`를 5분마다 호출 |
| Signal | `P95DurationMs=percentile(DurationMs, 95)`의 5분 bin |
| Dynamic rule | 5분 evaluation, 20분 window, Medium sensitivity |
| Alert 조건 | 최근 4회 중 2회가 learned upper bound 초과 |
| Action | 없음(shadow mode) |
| Static safety net | 기존 S2 `p95 > 2000ms` rule 유지 |

## Phase 1 — 당일: 배포와 baseline 확인

README의 `azd up`을 완료한 뒤 환경을 읽습니다.

```bash
cd monitor/sre-agent-event-lab
source ./scripts/lab-env.sh

CONTAINER_APP_FQDN="${APP_FQDN}"
BASELINE_WEB_TEST_NAME="$(azd env get-value AZURE_BASELINE_WEB_TEST_NAME)"
DYNAMIC_ALERT_NAME="$(azd env get-value AZURE_DYNAMIC_THRESHOLD_ALERT_NAME)"
```

두 리소스가 활성화되었고 Dynamic rule에 Action Group이 없는지 확인합니다.

```bash
az resource show \
  --resource-group "${RESOURCE_GROUP}" \
  --resource-type Microsoft.Insights/webtests \
  --name "${BASELINE_WEB_TEST_NAME}" \
  --api-version 2022-06-15 \
  --query "{enabled:properties.Enabled,frequency:properties.Frequency,url:properties.Request.RequestUrl}" \
  --output table

az resource show \
  --resource-group "${RESOURCE_GROUP}" \
  --resource-type Microsoft.Insights/scheduledQueryRules \
  --name "${DYNAMIC_ALERT_NAME}" \
  --api-version 2025-01-01-preview \
  --query "{enabled:properties.enabled,frequency:properties.evaluationFrequency,actions:properties.actions.actionGroups}" \
  --output json
```

몇 차례 호출된 뒤 numeric series가 생성되는지 확인합니다.

```bash
az monitor log-analytics query \
  --workspace "${WORKSPACE_CUSTOMER_ID}" \
  --analytics-query "AppRequests
| where AppRoleName == '${TELEMETRY_SERVICE_NAME}'
| where Name has '/api/orders'
| where TimeGenerated > ago(2h)
| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)
| order by TimeGenerated desc" \
  --output table
```

당일에는 alert 발화를 기대하지 않습니다. Microsoft가 명시한 최소 조건은
3일과 30 samples이며, weekly seasonality 학습에는 최소 3주가 필요합니다.

## Phase 2 — 3일 이후: learned band와 anomaly 검증

먼저 72시간 이상의 실제 범위와 30개 이상의 samples가 있는지 확인합니다.

```bash
az monitor log-analytics query \
  --workspace "${WORKSPACE_CUSTOMER_ID}" \
  --analytics-query "AppRequests
| where AppRoleName == '${TELEMETRY_SERVICE_NAME}'
| where Name has '/api/orders'
| where TimeGenerated > ago(4d)
| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)
| summarize Samples=count(), FirstSample=min(TimeGenerated), LastSample=max(TimeGenerated)
| extend AgeHours=datetime_diff('hour', LastSample, FirstSample)" \
  --output table
```

`AgeHours >= 72`와 `Samples >= 30`을 모두 확인한 뒤 지연을 주입합니다. 아래
trap은 명령 실패나 Ctrl+C에도 `ORDER_DELAY_MS=0` 복구를 시도합니다.

```bash
mkdir -p evidence

restore_delay() {
  az containerapp update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --set-env-vars ORDER_DELAY_MS=0 \
    --output none
}
trap restore_delay EXIT INT TERM

az containerapp update \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${APP_NAME}" \
  --set-env-vars ORDER_DELAY_MS=4000 \
  --output none

for RUN in 1 2 3 4; do
  python3 scripts/loadgen.py \
    "https://${CONTAINER_APP_FQDN}/api/orders" \
    --requests 20 \
    --concurrency 5 \
    --expect-status 200 \
    --output "evidence/dynamic-threshold-s2-${RUN}.json"
  if [[ "${RUN}" -lt 4 ]]; then
    sleep 300
  fi
done

restore_delay
trap - EXIT INT TERM
```

Azure Portal에서 해당 Dynamic rule의 **Preview chart**와 alert history를
확인합니다. 실제 alert가 없으면 성공으로 간주하지 말고 다음을 구분합니다.

- `AgeHours < 72` 또는 `Samples < 30`: 학습 조건 미충족
- p95 points 없음: availability test 또는 telemetry 수집 실패
- points는 있으나 band 안쪽: anomaly 크기·지속 시간이 현재 모델에 부족
- band 밖 points가 2-of-4를 충족했지만 alert 없음: rule state와 query 오류 확인

복구 후 아래 쿼리로 p95가 정상 범위로 돌아오는지 확인합니다.

```bash
az monitor log-analytics query \
  --workspace "${WORKSPACE_CUSTOMER_ID}" \
  --analytics-query "AppRequests
| where AppRoleName == '${TELEMETRY_SERVICE_NAME}'
| where Name has '/api/orders'
| where TimeGenerated > ago(45m)
| summarize P95DurationMs=percentile(DurationMs, 95) by bin(TimeGenerated, 5m)
| order by TimeGenerated desc" \
  --output table
```

## 완료 기준

- 실제 3일·30 samples 조건을 충족한 telemetry를 확인했습니다.
- Preview chart에서 learned allowed range와 주입 구간을 확인했습니다.
- alert fired 또는 미발화 원인을 evidence로 기록했습니다.
- `ORDER_DELAY_MS=0`인 healthy revision으로 복구했습니다.
- 운영 연결은 false-positive/negative 검토 후에만 Action Group을 추가합니다.

## 공식 자료

- [Create a Log Search alert rule with dynamic threshold](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds)
- [Application Insights availability tests](https://learn.microsoft.com/azure/azure-monitor/app/availability)
- [ARM templates for log alerts](https://learn.microsoft.com/azure/azure-monitor/alerts/resource-manager-alerts-log)
