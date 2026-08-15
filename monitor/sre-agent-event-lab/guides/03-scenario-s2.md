# 03. S2 — 응답 지연 장애

주문 API가 느려지게 만들고, p95 지연 경고를 받은 Agent가 오류 없는 장애를 설명하는지 봅니다. 500이 하나도 없기 때문에 S1보다 근거를 고르기 어렵습니다.

## 시작 조건

- [02-scenario-s1.md](02-scenario-s1.md)의 S1이 복구되고 캡처가 `conclusion`으로 끝났습니다.
- `evidence/state.json`에 `s1_recovered`와 `s1_captured`가 있습니다.
- 다른 시나리오의 실행이 `running`이나 `failed`로 남아 있지 않습니다. 하나라도 남아 있으면 S2도 거부되고, 거부 메시지가 막고 있는 시나리오와 해결 명령을 알려 줍니다.
- 워크로드가 정상이고 S1 경고가 해제되어 있습니다.

## 수동 실행

S1과 같은 구조이며, 바뀌는 것은 주입 값과 부하 조건뿐입니다.

Codespaces에서 이 저장소를 열었다면 `az login`을 마친 뒤 아래 한 줄로 이번 실습에 필요한 값이 모두 셸에 준비됩니다. 여기서부터 마지막 `record-capture`까지는 같은 셸에서 실행합니다.

```bash
cd monitor/sre-agent-event-lab
source ./scripts/lab-env.sh
```

`lab-env.sh`는 `azd`가 게시한 배포 출력만 읽어 `RESOURCE_GROUP`, `SUBSCRIPTION_ID`, `APP_NAME`, `APP_FQDN`, `WORKLOAD_PRINCIPAL_ID`, `STORAGE_CONTAINER_SCOPE`, `BLOB_ROLE_ASSIGNMENT_NAME`을 export하고, 하나라도 읽지 못하면 `LAB_READY=0`으로 알려 줍니다. 비밀 값은 읽지도 출력하지도 않습니다.

이번 시나리오에서만 쓰는 값을 정하고 시도를 기록합니다.

```bash
ALERT_RULE_NAME="alert-sre-lab-s2-latency"
EVIDENCE_DIR="${PWD}/evidence/s2-$(date -u +%Y%m%dT%H%M%SZ)"

if (( LAB_READY )); then
  mkdir -p "${EVIDENCE_DIR}"
  python3 scripts/lab_state.py begin-run s2 "${EVIDENCE_DIR}" || LAB_READY=0
fi
(( LAB_READY )) || echo "준비되지 않았습니다. 아래 단계는 모두 건너뜁니다." >&2
```

`begin-run`은 이번 시도를 기록하면서 순서·중복 실행 게이트도 함께 적용하고, 거부되면 `LAB_READY`가 0이 되어 이후 단계가 모두 건너뜁니다.

### 1. 지연 주입

```bash
INJECTED=0
INJECTED_AT=""
if (( LAB_READY )); then
  OLD_REVISION="$(az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --query properties.latestRevisionName -o tsv)"

  az containerapp update \
    --subscription "${SUBSCRIPTION_ID}" \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --set-env-vars ORDER_DELAY_MS=4000 \
    --output none \
    && INJECTED=1 && INJECTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
```

부하를 넣기 전에 **새** revision이 활성·정상이 될 때까지 최대 10분 기다립니다. 이 확인을 건너뛰면 이전 revision에 부하가 들어가 경고가 발생하지 않습니다.

```bash
REVISION_OK=0
if (( INJECTED )); then
  DEADLINE=$(( SECONDS + 600 ))
  while (( SECONDS < DEADLINE )); do
    NEW_REVISION="$(az containerapp show \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${APP_NAME}" \
      --query properties.latestRevisionName -o tsv)"
    STATE="$(az containerapp revision list \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${APP_NAME}" \
      --query "[?name=='${NEW_REVISION}'].{health:properties.healthState, active:properties.active} | [0]" -o json)"
    echo "${NEW_REVISION} ${STATE}"
    if [[ -n "${NEW_REVISION}" && "${NEW_REVISION}" != "${OLD_REVISION}" ]] \
      && [[ "$(jq -r '.health // empty' <<<"${STATE}")" == "Healthy" ]] \
      && [[ "$(jq -r '.active // empty' <<<"${STATE}")" == "true" ]]; then
      REVISION_OK=1
      break
    fi
    sleep 10
  done
  (( REVISION_OK )) || echo "새 revision이 시간 안에 정상이 되지 않았습니다." >&2
fi
```

### 2. 부하 발생

응답은 200이고 지연만 올라가는 것이 이 시나리오의 핵심입니다.

```bash
if (( REVISION_OK )); then
  python3 scripts/loadgen.py \
    "https://${APP_FQDN}/api/orders" \
    --requests 90 \
    --concurrency 8 \
    --expect-status 200 \
    --timeout 15 \
    --output "${EVIDENCE_DIR}/load.json"
else
  echo "지연이 적용되지 않아 부하를 넣지 않습니다. 4단계 복구로 넘어가세요." >&2
fi
```

### 3. 경고 확인

```bash
ALERT_ID=""
ALERT_FIRED_AT=""
if (( REVISION_OK )); then
  DEADLINE=$(( SECONDS + 720 ))
  while (( SECONDS < DEADLINE )); do
    ALERT_JSON="$(az rest \
      --method get \
      --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.AlertsManagement/alerts?api-version=2019-03-01&targetResourceGroup=${RESOURCE_GROUP}&monitorCondition=Fired" \
      --query "value[?contains(properties.essentials.alertRule, '${ALERT_RULE_NAME}')] | [0].{id:id, started:properties.essentials.startDateTime}" \
      -o json)"
    ALERT_ID="$(jq -r '.id // empty' <<<"${ALERT_JSON}")"
    ALERT_FIRED_AT="$(jq -r '.started // empty' <<<"${ALERT_JSON}")"
    [[ -n "${ALERT_ID}" ]] && break
    sleep 20
  done
fi
echo "${ALERT_ID:-경고가 아직 없습니다}"
```

경고가 끝내 발생하지 않아도 4단계 복구는 실행합니다.

### 4. 복구

```bash
RECOVERY_OK=0
if (( INJECTED )); then
RECOVERY_OLD_REVISION="$(az containerapp show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${APP_NAME}" \
  --query properties.latestRevisionName -o tsv)"

az containerapp update \
  --subscription "${SUBSCRIPTION_ID}" \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${APP_NAME}" \
  --set-env-vars ORDER_DELAY_MS=0 \
  --output none

REVISION_OK=0
DEADLINE=$(( SECONDS + 600 ))
while (( SECONDS < DEADLINE )); do
  NEW_REVISION="$(az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --query properties.latestRevisionName -o tsv)"
  STATE="$(az containerapp revision list \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --query "[?name=='${NEW_REVISION}'].{health:properties.healthState, active:properties.active} | [0]" -o json)"
  echo "${NEW_REVISION} ${STATE}"
  if [[ -n "${NEW_REVISION}" && "${NEW_REVISION}" != "${RECOVERY_OLD_REVISION}" ]] \
    && [[ "$(jq -r '.health // empty' <<<"${STATE}")" == "Healthy" ]] \
    && [[ "$(jq -r '.active // empty' <<<"${STATE}")" == "true" ]]; then
    REVISION_OK=1
    break
  fi
  sleep 10
done
(( REVISION_OK )) || echo "새 revision이 시간 안에 정상이 되지 않았습니다." >&2
RECOVERY_OK=${REVISION_OK}
RECOVERED_AT=""
(( RECOVERY_OK )) && RECOVERED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
curl -s --max-time 15 -o /dev/null -w '%{time_total}s %{http_code}\n' "https://${APP_FQDN}/api/orders"
else
  echo "주입된 장애가 없어 복구를 건너뜁니다." >&2
  RECOVERY_OK=1
fi
```

```bash
ALERT_CONDITION=""
if [[ -n "${ALERT_ID}" ]]; then
  DEADLINE=$(( SECONDS + 1500 ))
  while (( SECONDS < DEADLINE )); do
    ALERT_CONDITION="$(az rest \
      --method get \
      --url "https://management.azure.com${ALERT_ID}?api-version=2019-03-01" \
      --query "properties.essentials.monitorCondition" -o tsv)"
    echo "${ALERT_CONDITION}"
    [[ "${ALERT_CONDITION}" == "Resolved" ]] && break
    sleep 20
  done
fi
```

### 5. 실행 결과 기록

```bash
if (( LAB_READY )); then
ALERT_RESOLVED_AT=""
[[ "${ALERT_CONDITION}" == "Resolved" ]] && ALERT_RESOLVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n \
  --arg scenario s2 \
  --arg injectedAt "${INJECTED_AT}" \
  --arg alertRule "${ALERT_RULE_NAME}" \
  --arg alertId "${ALERT_ID}" \
  --arg alertFiredAt "${ALERT_FIRED_AT}" \
  --arg recoveredAt "${RECOVERED_AT}" \
  --arg alertResolvedAt "${ALERT_RESOLVED_AT}" \
  '{scenario: $scenario, injected_at: $injectedAt, alert_rule: $alertRule,
    alert_id: $alertId, alert_fired_at: $alertFiredAt, recovered_at: (if $recoveredAt == "" then null else $recoveredAt end),
    alert_resolved_at: (if $alertResolvedAt == "" then null else $alertResolvedAt end)}' \
  > "${EVIDENCE_DIR}/timeline.json"

if (( RECOVERY_OK )) && [[ "${ALERT_CONDITION}" == "Resolved" ]]; then
  python3 scripts/lab_state.py mark-recovered s2 "${EVIDENCE_DIR}"
else
  python3 scripts/lab_state.py mark-failed s2 "${EVIDENCE_DIR}" \
    --reason "recovery_ok=${RECOVERY_OK} alert=${ALERT_CONDITION:-unknown}"
fi
fi
```

복구는 워크로드 정상화(`RECOVERY_OK`)와 경고 해제가 모두 확인될 때만 인정합니다. 둘 중 하나라도 어긋나면 실패로 기록되므로, 장애가 남아 있는 실행이 성공으로 채점되지 않습니다.

### 6. 조사 근거 수집

```bash
AGENT_ENDPOINT="$(jq -r '.agent_endpoint // empty' evidence/agent-setup.json)"
case "${AGENT_ENDPOINT}" in
  https://*"<"* | https://*">"* | "https://") AGENT_ENDPOINT="" ;;
  https://*) ;;
  *) AGENT_ENDPOINT="" ;;
esac

if [[ -z "${ALERT_ID}" || -z "${AGENT_ENDPOINT}" ]]; then
  echo "ALERT_ID가 없거나 agent_endpoint가 https URL이 아니어서 캡처를 건너뜁니다." >&2
else
  app/.venv/bin/python scripts/capture_agent.py \
    --scenario s2 \
    --alert-id "${ALERT_ID}" \
    --endpoint "${AGENT_ENDPOINT}" \
    --output-dir "${EVIDENCE_DIR}" \
    --timeout 1200 \
    --interval 15 || true

  if [[ -f "${EVIDENCE_DIR}/normalized-timeline.json" ]]; then
    python3 scripts/lab_state.py record-capture s2 \
      --timeline "${EVIDENCE_DIR}/normalized-timeline.json" \
      --evidence-dir "${EVIDENCE_DIR}"

    app/.venv/bin/python scripts/render_capture.py \
      "${EVIDENCE_DIR}/normalized-timeline.json" \
      assets/captures/s2 \
      --scenario s2
  else
    echo "정규화된 타임라인이 없어 캡처를 기록하지 않았습니다." >&2
  fi
fi
```

`agent_endpoint`는 `https://`로 시작하고 자리표시자 괄호가 없어야 합니다. `http://`를 쓰면 데이터 평면 토큰이 평문으로 나갑니다. `capture_agent.py`는 제한 시간까지 결론을 받지 못하면 종료 코드 3으로 끝나며, 이는 "결론 없음"을 그대로 기록하는 정상 경로입니다. 결과 기록을 렌더링보다 먼저 하는 이유는 이미지 생성이 실패해도 관측한 결과를 잃지 않기 위해서입니다.

## 지름길

```bash
./scripts/lab.sh run s2
./scripts/lab.sh capture s2
```

같은 명령을 같은 순서로 실행하면서 종료 시 자동 복구까지 처리합니다. 순서 게이트는 수동 실행도 `begin-run`을 통해 동일하게 적용받으며, 차이는 실패 시 복구를 누가 하느냐입니다.

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | Container App에 `ORDER_DELAY_MS=4000`이 설정되어 새 revision이 만들어집니다 |
| 2 | `/api/orders`에 요청 90건(동시 8)이 들어가고 모두 200이지만 4초 안팎이 걸립니다 |
| 3 | Application Insights workspace 테이블 `AppRequests`의 `DurationMs`가 올라갑니다 |
| 4 | 5분 창의 p95 지연이 2000ms를 넘으면 `alert-sre-lab-s2-latency`(Sev2)가 발생합니다 |
| 5 | 복구로 `ORDER_DELAY_MS=0` revision이 배포되고 경고가 자동 해제됩니다 |

## SRE Agent에서 확인할 항목

- 성공 응답만 있는 상황에서 지연을 근거로 삼는지, 오류 로그가 없다는 이유로 "이상 없음"이라고 답하지 않는지
- p95 값과 정상 구간의 차이를 수치로 제시하는지
- 원인을 최근 revision의 설정 변경으로 좁히는지, 일반적인 "리소스 부족"으로 뭉개지 않는지
- 완화책이 되돌리기 가능한 최소 변경인지

## 성공·부분 성공·실패 판정

| 기록된 상태 | 판정 |
|---|---|
| `conclusion` | 성공. 결론 내용의 깊이는 채점에서 다시 나뉩니다 |
| `conclusion-missing` | 실패. 조사는 시작했지만 결론이 없습니다 |
| `investigation-missing` | 실패. 스레드만 열리고 조사 단계가 없습니다 |
| `thread-not-created` | 실패. 경고가 Agent에 도달하지 못했습니다 |

지연 시나리오에서 흔한 부분 성공은 "느려졌다"까지만 말하고 어떤 변경 때문인지 짚지 못하는 결론입니다. 이 경우도 상태는 `conclusion`이므로, 직접 원인 항목의 점수로 구분합니다.

## 복구 확인

1. 활성 revision이 정상이고 `/api/orders`가 다시 빠르게 응답합니다.
2. `alert-sre-lab-s2-latency`가 `Resolved`입니다.

경고가 해제되지 않으면 부하가 남아 있는지, 새 revision으로 트래픽이 100% 넘어갔는지 확인합니다. 실패로 기록된 실행은 `./scripts/lab.sh run s2`를 다시 실행해 새 시도로 이어 갑니다. 다시 실행하면 이전 시도의 `s2_recovered`와 `s2_captured` 기록이 주입 전에 지워지고, 새 시도가 복구되고 `capture`될 때까지 S3는 다시 막힙니다.

되돌리기 자체가 실패하면 스크립트는 `CRITICAL:` 두 줄을 출력하고 0이 아닌 코드로 끝냅니다. 지연이 그대로 남아 있다는 뜻이므로, 다음 시나리오를 실행하기 전에 `ORDER_DELAY_MS=0`을 수동으로 되돌리고 새 revision이 정상인지 확인하세요.

## 다음 단계

권한 장애로 넘어갑니다: [04-scenario-s3.md](04-scenario-s3.md)
