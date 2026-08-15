#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

if [[ "$#" -ne 4 ]]; then
  echo "Usage: $0 SCENARIO EVIDENCE_DIR START_UTC END_UTC" >&2
  exit 2
fi

readonly SCENARIO="$1"
readonly EVIDENCE_DIR="$2"
readonly START_UTC="$3"
readonly END_UTC="$4"

require_lab_config
verify_subscription
verify_lab_resource_group
mkdir -p "${EVIDENCE_DIR}"

APP_NAME="$(deployment_output containerAppName)"
WORKSPACE_CUSTOMER_ID="$(deployment_output workspaceCustomerId)"
WORKLOAD_PRINCIPAL_ID="$(deployment_output containerAppPrincipalId)"
STORAGE_CONTAINER_SCOPE="$(deployment_output storageContainerScope)"
TELEMETRY_SERVICE_NAME="$(deployment_output telemetryServiceName)"
readonly APP_NAME WORKSPACE_CUSTOMER_ID WORKLOAD_PRINCIPAL_ID
readonly STORAGE_CONTAINER_SCOPE TELEMETRY_SERVICE_NAME

query_workspace() {
  local query="$1"
  local output_file="$2"
  az monitor log-analytics query \
    --workspace "${WORKSPACE_CUSTOMER_ID}" \
    --analytics-query "${query}" \
    --timespan "${START_UTC}/${END_UTC}" \
    -o json >"${output_file}"
}

query_workspace \
  "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | project TimeGenerated, Name, ResultCode, Success, DurationMs, OperationId | order by TimeGenerated asc" \
  "${EVIDENCE_DIR}/app-requests.json"
query_workspace \
  "AppDependencies | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | project TimeGenerated, Name, Target, ResultCode, Success, DurationMs, OperationId | order by TimeGenerated asc" \
  "${EVIDENCE_DIR}/app-dependencies.json"
query_workspace \
  "AppExceptions | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | project TimeGenerated, ExceptionType, OuterMessage, OperationId | order by TimeGenerated asc" \
  "${EVIDENCE_DIR}/app-exceptions.json"

az monitor activity-log list \
  --resource-group "${RESOURCE_GROUP}" \
  --start-time "${START_UTC}" \
  --end-time "${END_UTC}" \
  -o json |
  jq 'map({
    eventTimestamp: .eventTimestamp,
    operationName: .operationName.value,
    status: .status.value,
    subStatus: .subStatus.value,
    resourceId: .resourceId,
    correlationId: .correlationId
  })' >"${EVIDENCE_DIR}/activity-log.json"

az rest \
  --method get \
  --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.AlertsManagement/alerts?api-version=2019-03-01&targetResourceGroup=${RESOURCE_GROUP}" \
  >"${EVIDENCE_DIR}/alerts.json"

az containerapp revision list \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${APP_NAME}" \
  -o json |
  jq 'map(
    .properties.template.containers |= map(
      .env |= map(
        if has("secretRef") then
          {name: .name, secretRef: "<redacted-secret-reference>"}
        else
          .
        end
      )
    )
  )' >"${EVIDENCE_DIR}/revisions-redacted.json"

az role assignment list \
  --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
  --scope "${STORAGE_CONTAINER_SCOPE}" \
  -o json >"${EVIDENCE_DIR}/storage-role-assignments.json"

jq -n \
  --arg scenario "${SCENARIO}" \
  --arg start "${START_UTC}" \
  --arg end "${END_UTC}" \
  '{scenario: $scenario, start_utc: $start, end_utc: $end}' \
  >"${EVIDENCE_DIR}/query-window.json"
