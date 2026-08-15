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

# The workspace answers with a flat JSON array of row objects (see
# `log_analytics_row_count` in common.sh), so the poll asks for real rows --
# projected and bounded with `take 1` -- rather than a `| count`, whose
# single row would look like data even for an empty workspace. `contains`
# (substring) is used rather than `has` (term match) so a path like
# `/api/orders` matches inside `GET /api/orders` regardless of tokenization.
telemetry_seen() {
  local path_fragment="$1"
  local rows
  rows="$(log_analytics_row_count "${WORKSPACE_CUSTOMER_ID}" PT30M \
    "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | where Name contains '${path_fragment}' | project TimeGenerated, Name | take 1")"
  [[ "${rows:-0}" -gt 0 ]]
}

ORDERS_SEEN=0
DOCUMENTS_SEEN=0
# Bounded poll: always at least one honest attempt (even with a zero
# timeout), and never a sleep that would run past the deadline.
TELEMETRY_DEADLINE=$(( SECONDS + TELEMETRY_TIMEOUT_SECONDS ))
while :; do
  if [[ "${ORDERS_SEEN}" -eq 0 ]] && telemetry_seen "/api/orders"; then
    ORDERS_SEEN=1
  fi
  if [[ "${DOCUMENTS_SEEN}" -eq 0 ]] && telemetry_seen "/api/documents"; then
    DOCUMENTS_SEEN=1
  fi
  if [[ "${ORDERS_SEEN}" -eq 1 && "${DOCUMENTS_SEEN}" -eq 1 ]]; then
    break
  fi
  if (( SECONDS + TELEMETRY_POLL_INTERVAL_SECONDS > TELEMETRY_DEADLINE )); then
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

# Only a baseline that really produced both request types unlocks S1: a
# scenario run against a workload whose telemetry never arrived cannot be
# told apart from the failure it is supposed to inject.
lab_state mark baseline_passed --evidence-dir "${EVIDENCE_DIR}"

echo "Evidence directory: ${EVIDENCE_DIR}"
