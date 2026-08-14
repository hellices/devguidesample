#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

# Overridable only for tests: production runs always use the 600s/20s
# defaults. Bounding the poll (rather than querying once) tolerates
# Application Insights ingestion lag without hanging forever.
readonly TELEMETRY_TIMEOUT_SECONDS="${LAB_BASELINE_TELEMETRY_TIMEOUT_SECONDS:-600}"
readonly TELEMETRY_POLL_INTERVAL_SECONDS="${LAB_BASELINE_TELEMETRY_POLL_INTERVAL_SECONDS:-20}"

require_lab_config
verify_subscription
verify_lab_resource_group

APP_FQDN="$(deployment_output containerAppFqdn)"
WORKSPACE_CUSTOMER_ID="$(deployment_output workspaceCustomerId)"
TELEMETRY_SERVICE_NAME="$(deployment_output telemetryServiceName)"
readonly APP_FQDN WORKSPACE_CUSTOMER_ID TELEMETRY_SERVICE_NAME

if [[ -z "${APP_FQDN}" || -z "${WORKSPACE_CUSTOMER_ID}" || -z "${TELEMETRY_SERVICE_NAME}" ]]; then
  echo "Deployment outputs are missing. Run: azd provision" >&2
  exit 1
fi

EVIDENCE_DIR="$(create_evidence_dir baseline)"
readonly EVIDENCE_DIR

if ! python3 "${SCRIPT_DIR}/loadgen.py" \
  "https://${APP_FQDN}/api/orders" \
  --requests 30 \
  --concurrency 4 \
  --expect-status 200 \
  --output "${EVIDENCE_DIR}/orders.json"; then
  echo "Baseline /api/orders requests did not all succeed: ${EVIDENCE_DIR}/orders.json" >&2
  exit 1
fi

if ! python3 "${SCRIPT_DIR}/loadgen.py" \
  "https://${APP_FQDN}/api/documents" \
  --requests 10 \
  --concurrency 2 \
  --expect-status 200 \
  --output "${EVIDENCE_DIR}/documents.json"; then
  echo "Baseline /api/documents requests did not all succeed: ${EVIDENCE_DIR}/documents.json" >&2
  exit 1
fi

# telemetry_row_count QUERY -- number of rows the workspace returns for
# QUERY, or 0 when the query errors or returns nothing. Never fails the
# caller: an ingestion-lag miss is expected mid-poll, not this function's
# error to report.
telemetry_row_count() {
  local query="$1"
  az monitor log-analytics query \
    --workspace "${WORKSPACE_CUSTOMER_ID}" \
    --analytics-query "${query}" \
    --timespan PT30M \
    -o json 2>/dev/null |
    jq '(.tables[0].rows // []) | length' 2>/dev/null || echo 0
}

ORDERS_SEEN=0
DOCUMENTS_SEEN=0
started="${SECONDS}"
while (( SECONDS - started < TELEMETRY_TIMEOUT_SECONDS )); do
  if [[ "${ORDERS_SEEN}" -eq 0 ]]; then
    orders_rows="$(telemetry_row_count "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | where Name has '/api/orders' | take 1")"
    [[ "${orders_rows:-0}" -gt 0 ]] && ORDERS_SEEN=1
  fi
  if [[ "${DOCUMENTS_SEEN}" -eq 0 ]]; then
    documents_rows="$(telemetry_row_count "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | where Name has '/api/documents' | take 1")"
    [[ "${documents_rows:-0}" -gt 0 ]] && DOCUMENTS_SEEN=1
  fi
  if [[ "${ORDERS_SEEN}" -eq 1 && "${DOCUMENTS_SEEN}" -eq 1 ]]; then
    break
  fi
  sleep "${TELEMETRY_POLL_INTERVAL_SECONDS}"
done

jq -n \
  --argjson ordersSeen "${ORDERS_SEEN}" \
  --argjson documentsSeen "${DOCUMENTS_SEEN}" \
  --arg checkedAt "$(utc_now)" \
  '{orders_telemetry_seen: ($ordersSeen == 1), documents_telemetry_seen: ($documentsSeen == 1), checked_at: $checkedAt}' \
  >"${EVIDENCE_DIR}/telemetry-check.json"

if [[ "${ORDERS_SEEN}" -ne 1 || "${DOCUMENTS_SEEN}" -ne 1 ]]; then
  echo "Application Insights did not show both request types within ${TELEMETRY_TIMEOUT_SECONDS}s (orders=${ORDERS_SEEN} documents=${DOCUMENTS_SEEN})." >&2
  echo "Evidence directory: ${EVIDENCE_DIR}" >&2
  exit 1
fi

echo "Evidence directory: ${EVIDENCE_DIR}"
