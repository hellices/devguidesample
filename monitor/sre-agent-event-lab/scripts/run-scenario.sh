#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

if [[ "$#" -ne 1 ]] || [[ ! "$1" =~ ^s[123]$ ]]; then
  echo "Usage: $0 s1|s2|s3" >&2
  exit 2
fi

readonly SCENARIO="$1"
require_lab_config
verify_subscription
verify_lab_resource_group

APP_NAME="$(deployment_output containerAppName)"
APP_FQDN="$(deployment_output containerAppFqdn)"
WORKLOAD_PRINCIPAL_ID="$(deployment_output containerAppPrincipalId)"
STORAGE_CONTAINER_SCOPE="$(deployment_output storageContainerScope)"
BLOB_ROLE_ASSIGNMENT_NAME="$(deployment_output blobRoleAssignmentName)"
readonly APP_NAME APP_FQDN WORKLOAD_PRINCIPAL_ID STORAGE_CONTAINER_SCOPE
readonly BLOB_ROLE_ASSIGNMENT_NAME

EVIDENCE_DIR="$(create_evidence_dir "${SCENARIO}")"
readonly EVIDENCE_DIR
RECOVERED=0
INJECTED_AT=""
REVISION_READY_AT=""
ROLE_DELETED_AT=""
ALERT_RULE_NAME=""
ALERT_ID=""
ALERT_FIRED_AT=""

recover() {
  if [[ "${RECOVERED}" -eq 1 ]]; then
    return 0
  fi

  case "${SCENARIO}" in
    s1)
      OLD_REVISION="$(latest_revision_name "${APP_NAME}")"
      az containerapp update \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${APP_NAME}" \
        --set-env-vars FAILURE_MODE=none \
        --output none
      wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}" 600 >/dev/null
      ;;
    s2)
      OLD_REVISION="$(latest_revision_name "${APP_NAME}")"
      az containerapp update \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${APP_NAME}" \
        --set-env-vars ORDER_DELAY_MS=0 \
        --output none
      wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}" 600 >/dev/null
      ;;
    s3)
      if ! az role assignment list \
        --scope "${STORAGE_CONTAINER_SCOPE}" \
        --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
        --query "[?roleDefinitionName=='Storage Blob Data Reader'].id | [0]" \
        -o tsv | grep -q .; then
        az role assignment create \
          --name "${BLOB_ROLE_ASSIGNMENT_NAME}" \
          --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
          --assignee-principal-type ServicePrincipal \
          --role "Storage Blob Data Reader" \
          --scope "${STORAGE_CONTAINER_SCOPE}" \
          --output none
      fi
      ;;
  esac
  RECOVERED=1
}

recover_on_exit() {
  local original_status="$?"
  trap - EXIT
  if ! recover; then
    echo "CRITICAL: scenario recovery failed for ${SCENARIO}." >&2
    exit 1
  fi
  exit "${original_status}"
}
trap recover_on_exit EXIT

case "${SCENARIO}" in
  s1)
    ALERT_RULE_NAME="alert-sre-lab-s1-http500"
    OLD_REVISION="$(latest_revision_name "${APP_NAME}")"
    INJECTED_AT="$(utc_now)"
    az containerapp update \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${APP_NAME}" \
      --set-env-vars FAILURE_MODE=http500 \
      --output none
    wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}" 600 >/dev/null
    REVISION_READY_AT="$(utc_now)"
    python3 "${SCRIPT_DIR}/loadgen.py" \
      "https://${APP_FQDN}/api/orders" \
      --requests 120 \
      --concurrency 4 \
      --expect-status 500 \
      --output "${EVIDENCE_DIR}/load.json"
    ;;
  s2)
    ALERT_RULE_NAME="alert-sre-lab-s2-latency"
    OLD_REVISION="$(latest_revision_name "${APP_NAME}")"
    INJECTED_AT="$(utc_now)"
    az containerapp update \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${APP_NAME}" \
      --set-env-vars ORDER_DELAY_MS=4000 \
      --output none
    wait_for_new_revision_ready "${APP_NAME}" "${OLD_REVISION}" 600 >/dev/null
    REVISION_READY_AT="$(utc_now)"
    python3 "${SCRIPT_DIR}/loadgen.py" \
      "https://${APP_FQDN}/api/orders" \
      --requests 90 \
      --concurrency 8 \
      --expect-status 200 \
      --timeout 15 \
      --output "${EVIDENCE_DIR}/load.json"
    ;;
  s3)
    ALERT_RULE_NAME="alert-sre-lab-s3-storage-rbac"
    ROLE_ASSIGNMENT_ID="${STORAGE_CONTAINER_SCOPE}/providers/Microsoft.Authorization/roleAssignments/${BLOB_ROLE_ASSIGNMENT_NAME}"
    readonly ROLE_ASSIGNMENT_ID
    INJECTED_AT="$(utc_now)"
    az role assignment delete --ids "${ROLE_ASSIGNMENT_ID}"
    ROLE_DELETED_AT="$(utc_now)"
    python3 "${SCRIPT_DIR}/loadgen.py" \
      "https://${APP_FQDN}/api/documents" \
      --requests 60 \
      --concurrency 4 \
      --expect-status 503 \
      --output "${EVIDENCE_DIR}/load.json"
    ;;
esac
readonly ALERT_RULE_NAME

started="${SECONDS}"
while (( SECONDS - started < 720 )); do
  alerts_json="$(az rest \
    --method get \
    --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.AlertsManagement/alerts?api-version=2019-03-01&targetResourceGroup=${RESOURCE_GROUP}&monitorCondition=Fired")"
  ALERT_ID="$(jq -r \
    --arg rule "${ALERT_RULE_NAME}" \
    'first(.value[] | select(.properties.essentials.alertRule | endswith($rule)) | .id) // ""' \
    <<<"${alerts_json}")"
  if [[ -n "${ALERT_ID}" ]]; then
    ALERT_FIRED_AT="$(jq -r \
      --arg id "${ALERT_ID}" \
      '.value[] | select(.id == $id) | .properties.essentials.startDateTime' \
      <<<"${alerts_json}")"
    break
  fi
  sleep 20
done

if [[ -z "${ALERT_ID}" ]]; then
  echo "Alert ${ALERT_RULE_NAME} did not fire within 720s." >&2
  exit 1
fi

recover
RECOVERED_AT="$(utc_now)"
readonly RECOVERED_AT
trap - EXIT

jq -n \
  --arg scenario "${SCENARIO}" \
  --arg injectedAt "${INJECTED_AT}" \
  --arg revisionReadyAt "${REVISION_READY_AT}" \
  --arg roleDeletedAt "${ROLE_DELETED_AT}" \
  --arg alertRule "${ALERT_RULE_NAME}" \
  --arg alertId "${ALERT_ID}" \
  --arg alertFiredAt "${ALERT_FIRED_AT}" \
  --arg recoveredAt "${RECOVERED_AT}" \
  '{
    scenario: $scenario,
    injected_at: $injectedAt,
    revision_ready_at: (if $revisionReadyAt == "" then null else $revisionReadyAt end),
    role_deleted_at: (if $roleDeletedAt == "" then null else $roleDeletedAt end),
    alert_rule: $alertRule,
    alert_id: $alertId,
    alert_fired_at: $alertFiredAt,
    recovered_at: $recoveredAt
  }' | tee "${EVIDENCE_DIR}/timeline.json"

printf 'Evidence directory: %s\n' "${EVIDENCE_DIR}"
