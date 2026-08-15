# 04. S3 — Blob 권한 제거 장애

워크로드의 Blob 읽기 권한을 지우고, 애플리케이션 코드가 아니라 권한이 원인임을 Agent가 구분해 내는지 봅니다.

## 시작 조건

- [03-scenario-s2.md](03-scenario-s2.md)의 S2가 복구되고 캡처가 `conclusion`으로 끝났습니다.
- `evidence/state.json`에 `s2_recovered`와 `s2_captured`가 있습니다.
- 다른 시나리오의 실행이 `running`이나 `failed`로 남아 있지 않습니다. S1을 다시 돌리다 실패한 채로 두면 S2 기록이 멀쩡해도 S3는 거부됩니다.
- 역할 할당을 만들고 지울 권한이 그대로 있습니다.

## 수동 실행

이 시나리오만 환경 변수가 아니라 RBAC를 건드립니다. 삭제·복구 대상은 출력에 기록된 Blob 컨테이너 범위의 단일 역할 하나뿐입니다.

```bash
cd monitor/sre-agent-event-lab
LAB_READY=1

RESOURCE_GROUP="$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null)" || LAB_READY=0
SUBSCRIPTION_ID="$(azd env get-value AZURE_SUBSCRIPTION_ID 2>/dev/null)" || LAB_READY=0
APP_FQDN="$(azd env get-value AZURE_CONTAINER_APP_FQDN 2>/dev/null)" || LAB_READY=0
WORKLOAD_PRINCIPAL_ID="$(azd env get-value AZURE_CONTAINER_APP_PRINCIPAL_ID 2>/dev/null)" || LAB_READY=0
STORAGE_CONTAINER_SCOPE="$(azd env get-value AZURE_STORAGE_CONTAINER_SCOPE 2>/dev/null)" || LAB_READY=0
BLOB_ROLE_ASSIGNMENT_NAME="$(azd env get-value AZURE_BLOB_ROLE_ASSIGNMENT_NAME 2>/dev/null)" || LAB_READY=0

ALERT_RULE_NAME="alert-sre-lab-s3-storage-rbac"
EVIDENCE_DIR="${PWD}/evidence/s3-$(date -u +%Y%m%dT%H%M%SZ)"

for value in "${RESOURCE_GROUP}" "${SUBSCRIPTION_ID}" "${APP_FQDN}" "${WORKLOAD_PRINCIPAL_ID}" "${STORAGE_CONTAINER_SCOPE}" "${BLOB_ROLE_ASSIGNMENT_NAME}"; do
  [[ -n "${value// /}" ]] || LAB_READY=0
done

if (( LAB_READY )); then
  mkdir -p "${EVIDENCE_DIR}"
  python3 scripts/lab_state.py begin-run s3 "${EVIDENCE_DIR}" || LAB_READY=0
else
  echo "azd 환경 값을 읽지 못했습니다. 먼저 azd provision을 실행하세요." >&2
fi
(( LAB_READY )) || echo "준비되지 않았습니다. 아래 단계는 모두 건너뜁니다." >&2
```

`azd env get-value`는 실패해도 오류 문장을 표준 출력으로 내보내므로 위 검사가 필요합니다. `begin-run`은 이번 시도를 기록하면서 순서·중복 실행 게이트도 함께 적용하고, 거부되면 `LAB_READY`가 0이 되어 이후 단계가 모두 건너뜁니다. 근거 디렉터리를 절대 경로로 두는 이유는 채점기와 캡처 도구가 기록된 경로를 실행 위치와 무관하게 다시 열기 때문입니다.

복구에 필요한 세 값이 비어 있으면 권한을 지운 뒤 되돌릴 수 없고, 빈 범위로 역할을 만들면 구독 전체에 권한이 부여됩니다. 그래서 위 검사를 통과하지 못하면 삭제 자체가 실행되지 않습니다.

### 1. 권한 삭제

```bash
INJECTED=0
if (( LAB_READY )); then
  ROLE_ASSIGNMENT_ID="${STORAGE_CONTAINER_SCOPE}/providers/Microsoft.Authorization/roleAssignments/${BLOB_ROLE_ASSIGNMENT_NAME}"
  INJECTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  ROLE_DELETED_AT=""
  az role assignment delete --ids "${ROLE_ASSIGNMENT_ID}" \
    && INJECTED=1 && ROLE_DELETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi
```

### 2. 전파 대기

데이터 평면에 반영될 때까지 몇 분 걸립니다. 503이 나올 때까지 최대 5분 기다립니다.

```bash
PROPAGATED=0
if (( INJECTED )); then
  DEADLINE=$(( SECONDS + 300 ))
  while (( SECONDS < DEADLINE )); do
    STATUS="$(curl -s --max-time 15 -o /dev/null -w '%{http_code}' "https://${APP_FQDN}/api/documents")"
    echo "${STATUS}"
    if [[ "${STATUS}" == "503" ]]; then
      PROPAGATED=1
      break
    fi
    sleep 10
  done
fi
```

### 3. 부하 발생

```bash
if (( PROPAGATED )); then
  python3 scripts/loadgen.py \
    "https://${APP_FQDN}/api/documents" \
    --requests 60 \
    --concurrency 4 \
    --expect-status 503 \
    --output "${EVIDENCE_DIR}/load.json"
else
  echo "503이 확인되지 않아 부하를 넣지 않습니다. 5단계 복구로 넘어가세요." >&2
fi
```

### 4. 경고 확인

```bash
ALERT_ID=""
ALERT_FIRED_AT=""
if (( PROPAGATED )); then
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

경고가 발생하지 않아도 5단계 복구는 반드시 실행합니다.

### 5. 권한 복구

같은 이름·같은 범위로 최소 권한만 되돌립니다. 이미 존재하면 다시 만들지 않습니다.

```bash
RECOVERY_OK=0
RECOVERED_AT=""
if (( INJECTED )); then
  EXISTING="$(az role assignment list \
    --scope "${STORAGE_CONTAINER_SCOPE}" \
    --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
    --query "[?roleDefinitionName=='Storage Blob Data Reader'].id | [0]" -o tsv)"

  if [[ -n "${EXISTING}" ]]; then
    RECOVERY_OK=1
  else
    az role assignment create \
      --name "${BLOB_ROLE_ASSIGNMENT_NAME}" \
      --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
      --assignee-principal-type ServicePrincipal \
      --role "Storage Blob Data Reader" \
      --scope "${STORAGE_CONTAINER_SCOPE}" \
      --output none && RECOVERY_OK=1
  fi
  (( RECOVERY_OK )) && RECOVERED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  curl -s --max-time 15 -o /dev/null -w '%{http_code}\n' "https://${APP_FQDN}/api/documents"
else
  echo "삭제된 권한이 없어 복구를 건너뜁니다." >&2
  RECOVERY_OK=1
fi
```

`RECOVERY_OK`가 0이면 워크로드에 Blob 권한이 없는 상태입니다. 값을 확인해 같은 범위로 직접 다시 만들어야 합니다.

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

### 6. 실행 결과 기록

```bash
if (( LAB_READY )); then
ALERT_RESOLVED_AT=""
[[ "${ALERT_CONDITION}" == "Resolved" ]] && ALERT_RESOLVED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

jq -n \
  --arg scenario s3 \
  --arg injectedAt "${INJECTED_AT}" \
  --arg roleDeletedAt "${ROLE_DELETED_AT}" \
  --arg alertRule "${ALERT_RULE_NAME}" \
  --arg alertId "${ALERT_ID}" \
  --arg alertFiredAt "${ALERT_FIRED_AT}" \
  --arg recoveredAt "${RECOVERED_AT}" \
  --arg alertResolvedAt "${ALERT_RESOLVED_AT}" \
  '{scenario: $scenario, injected_at: $injectedAt, role_deleted_at: (if $roleDeletedAt == "" then null else $roleDeletedAt end), alert_rule: $alertRule,
    alert_id: $alertId, alert_fired_at: $alertFiredAt, recovered_at: (if $recoveredAt == "" then null else $recoveredAt end),
    alert_resolved_at: (if $alertResolvedAt == "" then null else $alertResolvedAt end)}' \
  > "${EVIDENCE_DIR}/timeline.json"

if (( RECOVERY_OK )) && [[ "${ALERT_CONDITION}" == "Resolved" ]]; then
  python3 scripts/lab_state.py mark-recovered s3 "${EVIDENCE_DIR}"
else
  python3 scripts/lab_state.py mark-failed s3 "${EVIDENCE_DIR}" \
    --reason "recovery_ok=${RECOVERY_OK} alert=${ALERT_CONDITION:-unknown}"
fi
fi
```

복구는 워크로드 정상화(`RECOVERY_OK`)와 경고 해제가 모두 확인될 때만 인정합니다. 둘 중 하나라도 어긋나면 실패로 기록되므로, 장애가 남아 있는 실행이 성공으로 채점되지 않습니다.

### 7. 조사 근거 수집

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
    --scenario s3 \
    --alert-id "${ALERT_ID}" \
    --endpoint "${AGENT_ENDPOINT}" \
    --output-dir "${EVIDENCE_DIR}" \
    --timeout 1200 \
    --interval 15 || true

  if [[ -f "${EVIDENCE_DIR}/normalized-timeline.json" ]]; then
    python3 scripts/lab_state.py record-capture s3 \
      --timeline "${EVIDENCE_DIR}/normalized-timeline.json" \
      --evidence-dir "${EVIDENCE_DIR}"

    app/.venv/bin/python scripts/render_capture.py \
      "${EVIDENCE_DIR}/normalized-timeline.json" \
      assets/captures/s3 \
      --scenario s3
  else
    echo "정규화된 타임라인이 없어 캡처를 기록하지 않았습니다." >&2
  fi
fi
```

`agent_endpoint`는 `https://`로 시작하고 자리표시자 괄호가 없어야 합니다. `http://`를 쓰면 데이터 평면 토큰이 평문으로 나갑니다. `capture_agent.py`는 제한 시간까지 결론을 받지 못하면 종료 코드 3으로 끝나며, 이는 "결론 없음"을 그대로 기록하는 정상 경로입니다. 결과 기록을 렌더링보다 먼저 하는 이유는 이미지 생성이 실패해도 관측한 결과를 잃지 않기 위해서입니다.

## 지름길

```bash
./scripts/lab.sh run s3
./scripts/lab.sh capture s3
```

`run`은 위 순서에 더해 필요한 배포 출력이 비어 있지 않은지 삭제 전에 확인하고, 전파 대기를 최대 5분으로 제한하며, 종료 시 역할 복구를 보장합니다. 수동 실행에서는 이 확인들이 없으므로 삭제 후 복구 명령까지 반드시 직접 완료해야 합니다.

## Azure에서 발생하는 변화

| 순서 | 변화 |
|---|---|
| 1 | 워크로드 관리 ID의 `Storage Blob Data Reader` 할당이 Blob 컨테이너 범위에서 삭제됩니다 |
| 2 | 데이터 평면에 권한 삭제가 전파되어 단건 probe가 HTTP 503을 받을 때까지 최대 5분 기다립니다 |
| 3 | `/api/documents`에 요청 60건(동시 4)이 들어가고 모두 HTTP 503을 받습니다 |
| 4 | Application Insights workspace 테이블 `AppDependencies`에 Storage 대상 `ResultCode == "403"`이 쌓입니다 |
| 5 | 5분 창의 403 의존성 실패가 5건을 넘으면 `alert-sre-lab-s3-storage-rbac`(Sev2)이 발생합니다 |
| 6 | 복구로 같은 이름·같은 범위의 역할 할당이 다시 만들어집니다 |

삭제와 복구는 출력에 기록된 Blob 컨테이너 범위의 단일 역할에만 적용됩니다. 구독이나 리소스 그룹 범위의 다른 할당은 건드리지 않습니다.

단건 probe가 제한 시간 안에 503을 확인하지 못하면 `Storage RBAC deletion did not produce HTTP 503 within 300s`를 출력하고 본 부하를 시작하지 않은 채 역할을 복구합니다.

## SRE Agent에서 확인할 항목

- 앱이 돌려준 503과 실제 원인인 Storage 403을 구분하는지
- 호출한 관리 ID, 대상 범위, 필요한 데이터 평면 역할을 각각 지목하는지
- Activity Log의 역할 할당 삭제 기록을 근거로 인용하는지
- 복구책으로 구독 범위 권한이 아니라 원래 범위의 최소 역할을 제안하는지

마지막 항목은 운영 문서가 명시적으로 요구하는 내용이라, 실습에서 제품이 문서를 실제로 따르는지 가장 잘 드러나는 지점입니다.

## 성공·부분 성공·실패 판정

| 기록된 상태 | 판정 |
|---|---|
| `conclusion` | 성공. 권한 범위까지 짚었는지는 채점에서 확인합니다 |
| `conclusion-missing` | 실패. 결론에 도달하지 못했습니다 |
| `investigation-missing` | 실패. 조사 단계가 없습니다 |
| `thread-not-created` | 실패. 경고가 도달하지 않았습니다 |

권한 시나리오의 전형적인 부분 성공은 "Storage 접근 실패"까지만 말하고 어떤 역할이 어느 범위에서 사라졌는지 밝히지 못하는 결론입니다.

## 복구 확인

1. `Storage Blob Data Reader` 할당이 원래 Blob 컨테이너 범위에 다시 존재합니다.
2. `alert-sre-lab-s3-storage-rbac`가 `Resolved`입니다.

역할 전파에는 몇 분이 걸릴 수 있습니다. `/api/documents`가 200을 돌려주는지 직접 호출해 확인하고, 실패로 기록되었다면 `./scripts/lab.sh run s3`으로 새 시도를 시작합니다. 다시 실행하면 이전 시도의 `s3_recovered`와 `s3_captured` 기록이 주입 전에 지워지므로, 새 시도가 복구되고 `capture`될 때까지 채점은 막힙니다.

역할 복구 자체가 실패하면 스크립트는 `CRITICAL:` 두 줄을 출력하고 0이 아닌 코드로 끝냅니다. 워크로드에 Blob 권한이 없는 상태가 그대로 남으므로, 같은 이름·같은 범위의 `Storage Blob Data Reader` 할당을 수동으로 다시 만든 뒤 다음 단계로 넘어가세요.

```bash
az role assignment create \
  --name "$(azd env get-value AZURE_BLOB_ROLE_ASSIGNMENT_NAME)" \
  --assignee-object-id "$(azd env get-value AZURE_CONTAINER_APP_PRINCIPAL_ID)" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" \
  --scope "$(azd env get-value AZURE_STORAGE_CONTAINER_SCOPE)" \
  --output none
```

## 다음 단계

수집한 근거를 채점합니다: [05-results.md](05-results.md)
