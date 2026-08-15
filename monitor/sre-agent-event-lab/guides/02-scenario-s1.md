# 02. S1 — HTTP 500 장애

주문 API가 500을 반환하도록 바꾸고, Azure Monitor Sev2 경고가 발생한 뒤 Agent가 원인을 짚어내는지 봅니다.

## 시작 조건

- [01-agent-setup.md](01-agent-setup.md)를 마쳤고 `evidence/state.json`에 `baseline_passed`와 `agent_setup_acknowledged`가 기록되어 있습니다.
- 현재 활성 구독이 azd 환경의 구독과 같습니다.

이 두 가지는 `evidence/state.json`을 통해 강제됩니다. 아래 "수동 실행"도 첫 단계에서 `lab_state.py begin-run`을 호출하므로 같은 순서·중복 실행 게이트를 그대로 적용받습니다. 차이는 실패했을 때입니다. 지름길은 종료 트랩이 장애를 자동으로 되돌리지만, 수동 실행에서는 복구 명령을 운영자가 직접 실행해야 합니다.

조건이 하나라도 없으면 실행이 시작 전에 거부되고 무엇을 먼저 하라는 안내가 출력됩니다.

## 수동 실행

이 절의 명령을 순서대로 실행하면 스크립트 없이 시나리오 하나를 끝까지 진행할 수 있습니다. 무엇이 Azure에 적용되는지 명령 그대로 보이는 것이 목적입니다. 각 블록은 앞 단계가 성공했는지 플래그로 확인하고 진행합니다.

Codespaces에서 이 저장소를 열었다면 `az login`을 마친 뒤 아래 한 줄로 이번 실습에 필요한 값이 모두 셸에 준비됩니다. 여기서부터 마지막 `record-capture`까지는 같은 셸에서 실행합니다.

```bash
cd monitor/sre-agent-event-lab
source ./scripts/lab-env.sh
```

`lab-env.sh`는 `azd`가 게시한 배포 출력만 읽어 `RESOURCE_GROUP`, `SUBSCRIPTION_ID`, `APP_NAME`, `APP_FQDN`, `WORKLOAD_PRINCIPAL_ID`, `STORAGE_CONTAINER_SCOPE`, `BLOB_ROLE_ASSIGNMENT_NAME`을 export하고, 하나라도 읽지 못하면 `LAB_READY=0`으로 알려 줍니다. 비밀 값은 읽지도 출력하지도 않습니다.

이번 시나리오에서만 쓰는 값을 정하고 시도를 기록합니다.

```bash
ALERT_RULE_NAME="alert-sre-lab-s1-http500"
EVIDENCE_DIR="${PWD}/evidence/s1-$(date -u +%Y%m%dT%H%M%SZ)"

if (( LAB_READY )); then
  mkdir -p "${EVIDENCE_DIR}"
  python3 scripts/lab_state.py begin-run s1 "${EVIDENCE_DIR}" || LAB_READY=0
fi
(( LAB_READY )) || echo "준비되지 않았습니다. 아래 단계는 모두 건너뜁니다." >&2
```

`begin-run`은 이번 시도를 기록하면서 순서·중복 실행 게이트도 함께 적용하고, 거부되면 `LAB_READY`가 0이 되어 이후 단계가 모두 건너뜁니다. 근거 디렉터리를 절대 경로로 두는 이유는 채점기와 캡처 도구가 기록된 경로를 실행 위치와 무관하게 다시 열기 때문입니다.

### 1. 장애 주입

`FAILURE_MODE=http500`을 설정하면 새 revision이 배포되고 `/api/orders`가 500을 반환합니다.

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
    --set-env-vars FAILURE_MODE=http500 \
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

경고 임계값을 넘길 만큼의 500 응답을 만듭니다. `loadgen.py`는 요청을 보내고 상태 코드를 집계하는 것 외에는 하지 않습니다.

```bash
if (( REVISION_OK )); then
  python3 scripts/loadgen.py \
    "https://${APP_FQDN}/api/orders" \
    --requests 120 \
    --concurrency 4 \
    --expect-status 500 \
    --output "${EVIDENCE_DIR}/load.json"
else
  echo "장애가 적용되지 않아 부하를 넣지 않습니다. 4단계 복구로 넘어가세요." >&2
fi
```

### 3. 경고 확인

Sev2 경고가 발생할 때까지 최대 12분 기다립니다. 보통 1~3분 걸립니다.

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

경고가 끝내 발생하지 않아도 4단계 복구는 반드시 실행합니다. 5단계의 조건 분기가 실패로 기록합니다.

### 4. 복구

장애를 되돌립니다. 이 명령을 잊으면 워크로드는 계속 500을 반환합니다.

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
  --set-env-vars FAILURE_MODE=none \
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
curl -s --max-time 15 -o /dev/null -w '%{http_code}\n' "https://${APP_FQDN}/api/orders"
else
  echo "주입된 장애가 없어 복구를 건너뜁니다." >&2
  RECOVERY_OK=1
fi
```

`RECOVERY_OK`가 0이면 장애가 아직 살아 있다는 뜻입니다. 다음 시나리오로 넘어가기 전에 `FAILURE_MODE=none`을 직접 다시 적용하고 revision 상태를 확인하세요.

경고가 `Resolved`로 바뀔 때까지 기다립니다. 1분 주기 stateful log alert는 조건이 10분간 불충족이어야 해제되므로 최대 25분까지 걸립니다.

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

채점기가 읽는 상태와 타임라인을 남깁니다.

```bash
if (( LAB_READY )); then
ALERT_RESOLVED_AT=""
[[ "${ALERT_CONDITION}" == "Resolved" ]] && ALERT_RESOLVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n \
  --arg scenario s1 \
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
  python3 scripts/lab_state.py mark-recovered s1 "${EVIDENCE_DIR}"
else
  python3 scripts/lab_state.py mark-failed s1 "${EVIDENCE_DIR}" \
    --reason "recovery_ok=${RECOVERY_OK} alert=${ALERT_CONDITION:-unknown}"
fi
fi
```

복구는 워크로드 정상화(`RECOVERY_OK`)와 경고 해제가 모두 확인될 때만 인정합니다. 둘 중 하나라도 어긋나면 실패로 기록되므로, 장애가 남아 있는 실행이 성공으로 채점되지 않습니다.

`timeline.json`은 캡처 도구가 대상 경고를 찾는 파일이며, 이 파일이 없으면 지름길의 `lab.sh capture`도 진행하지 못합니다.

### 6. 조사 근거 수집

Agent 스레드를 내려받아 정규화하고, 관측 결과를 먼저 기록한 뒤 그림을 만듭니다.

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
    --scenario s1 \
    --alert-id "${ALERT_ID}" \
    --endpoint "${AGENT_ENDPOINT}" \
    --output-dir "${EVIDENCE_DIR}" \
    --timeout 1200 \
    --interval 15 || true

  if [[ -f "${EVIDENCE_DIR}/normalized-timeline.json" ]]; then
    python3 scripts/lab_state.py record-capture s1 \
      --timeline "${EVIDENCE_DIR}/normalized-timeline.json" \
      --evidence-dir "${EVIDENCE_DIR}"

    app/.venv/bin/python scripts/render_capture.py \
      "${EVIDENCE_DIR}/normalized-timeline.json" \
      assets/captures/s1 \
      --scenario s1
  else
    echo "정규화된 타임라인이 없어 캡처를 기록하지 않았습니다." >&2
  fi
fi
```

`agent_endpoint`는 `https://`로 시작하고 자리표시자 괄호가 없어야 합니다. `http://`를 쓰면 데이터 평면 토큰이 평문으로 나갑니다. `capture_agent.py`는 제한 시간까지 결론을 받지 못하면 종료 코드 3으로 끝나며, 이는 "결론 없음"을 그대로 기록하는 정상 경로입니다. 결과 기록을 렌더링보다 먼저 하는 이유는 이미지 생성이 실패해도 관측한 결과를 잃지 않기 위해서입니다.

같은 UTC 구간의 KQL 근거가 필요하면 다음을 실행합니다.

```bash
if (( LAB_READY )) && [[ -n "${INJECTED_AT}" ]]; then
  ./scripts/query-evidence.sh s1 "${EVIDENCE_DIR}" \
    "${INJECTED_AT}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
```

## 지름길

위 여섯 단계를 그대로 자동화한 것이 아래 두 명령입니다. 같은 Azure 호출을 같은 순서로 실행하고, 추가로 실행 상태 기록과 종료 시 자동 복구를 처리합니다. 무엇이 실행되는지 이미 알고 반복할 때만 쓰세요.

```bash
./scripts/lab.sh run s1
./scripts/lab.sh capture s1
```

`run`은 장애 주입 → 부하 → 경고 대기 → 복구 → 타임라인 저장까지 진행하고, 경고가 발생하지 않으면 12분 뒤 실패로 기록합니다. 중간에 끊어도 종료 트랩이 복구를 시도합니다. `capture`는 대상 디렉터리를 `evidence/state.json`에서 찾으므로 경로를 입력하지 않습니다.

지름길은 순서 게이트도 적용합니다. 어떤 시나리오든 실행이 `running`이나 `failed`로 남아 있으면 세 시나리오 모두 새 실행이 거부됩니다. 세 시나리오는 같은 Container App 하나를 쓰고, 끝나지 않은 실행은 장애가 아직 살아 있을 수 있는 상태이기 때문입니다. `failed`는 그 시나리오를 다시 실행하면 풀리고, `running`은 실행이 끝나기를 기다리거나 `python3 scripts/lab_state.py mark-failed s1`처럼 끝난 방식을 기록해야 풀립니다. 수동 실행도 `begin-run`으로 같은 게이트를 적용받지만, 장애를 되돌리는 일은 운영자가 직접 해야 합니다.

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | Container App에 `FAILURE_MODE=http500` 환경 변수가 설정되어 새 revision이 만들어집니다 |
| 2 | `/api/orders`에 요청 120건(동시 4)이 들어가고 모두 HTTP 500을 받습니다 |
| 3 | Application Insights workspace 테이블 `AppRequests`에 `ResultCode == "500"` 레코드가 쌓입니다 |
| 4 | 5분 창의 500 응답이 10건을 넘으면 `alert-sre-lab-s1-http500`(Sev2)이 발생합니다 |
| 5 | 복구로 `FAILURE_MODE=none` revision이 다시 배포되고 경고가 자동 해제됩니다 |

## SRE Agent에서 확인할 항목

`https://sre.azure.com`에서 새 스레드를 열고 다음을 확인합니다.

- 경고 접수 시각과 스레드 생성 시각의 간격
- 조사 계획이 업로드한 운영 문서의 순서를 따르는지
- 영향 범위를 `/api/orders`로 좁혔는지, 앱 전체로 뭉뚱그리지 않았는지
- 직접 원인으로 최근 revision의 환경 변수 변경을 지목했는지
- 완화책을 제안만 하고 승인을 기다리는지(Review 모드)

`capture`가 만드는 `assets/captures/s1/`의 PNG·GIF·Markdown이 같은 내용을 담습니다.

## 성공·부분 성공·실패 판정

`capture`는 스레드의 마지막 상태를 그대로 기록합니다.

| 기록된 상태 | 의미 | 다음 시나리오 |
|---|---|---|
| `conclusion` | Agent가 구조화된 결론을 냈습니다 | 열립니다 |
| `investigation-missing` | 스레드는 열렸지만 조사 단계가 없습니다 | 막힙니다 |
| `conclusion-missing` | 조사는 했지만 결론에 도달하지 못했습니다 | 막힙니다 |
| `thread-not-created` | 경고가 Agent에 도달하지 못했습니다 | 막힙니다 |

성공은 `conclusion` 하나뿐입니다. 부분 성공은 결론이 나왔지만 내용이 얕은 경우이며, 이때도 상태는 `conclusion`이고 점수는 [05-results.md](05-results.md)의 채점에서 갈립니다. 빈 성공 화면을 만들지 않고 누락 상태와 마지막 확인 시각을 그대로 그림에 남깁니다.

`thread-not-created`가 나오면 [01-agent-setup.md](01-agent-setup.md)의 incident platform과 응답 계획부터 다시 확인합니다.

## 복구 확인

복구는 두 가지가 모두 확인된 뒤에만 기록됩니다.

1. Container App의 활성 revision이 다시 정상입니다.
2. 이 실행이 발생시킨 경고가 Azure Monitor에서 `Resolved`가 됩니다.

경고 해제는 최대 25분, 워크로드 정상화는 최대 10분까지 기다립니다. 1분 주기의 stateful log alert는 실패 요청이 5분 조회 창에서 빠진 뒤에도 조건이 10분간 불충족이어야 `Resolved`가 되므로 여유 시간을 포함합니다. 둘 중 하나라도 시간 안에 확인되지 않으면 실행은 실패로 기록되고 S2는 계속 막힙니다. 실패한 실행은 원인을 고친 뒤 `./scripts/lab.sh run s1`을 다시 실행하면 새 시도로 이어집니다. 다시 실행하는 순간 이전 시도의 `s1_recovered`와 `s1_captured` 기록은 장애를 주입하기 전에 지워지므로, 새 시도가 복구되고 `capture`까지 끝날 때까지 S2는 다시 막힙니다. 이미 성공한 시나리오를 한 번 더 돌릴 때도 같습니다.

되돌리기 자체가 실패하면(예: `az containerapp update` 거부, 새 revision이 준비되지 않음) 스크립트는 `CRITICAL:` 두 줄을 출력하고 0이 아닌 코드로 끝냅니다. 주입한 장애가 그대로 남아 있다는 뜻이므로, 다음 시나리오를 실행하기 전에 `FAILURE_MODE=none`을 수동으로 되돌리고 revision이 정상인지 확인하세요.

```bash
azd env get-value AZURE_CONTAINER_APP_FQDN
```

로 얻은 FQDN에 `/api/orders`를 호출해 200이 돌아오는지 직접 확인할 수도 있습니다.

## 다음 단계

지연 장애로 넘어갑니다: [03-scenario-s2.md](03-scenario-s2.md)
