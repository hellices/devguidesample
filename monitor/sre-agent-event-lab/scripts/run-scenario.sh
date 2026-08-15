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

# The run order is a safety boundary, not a convenience: a scenario started
# before the previous one recovered and was captured overlaps two incidents
# in one workload, and neither capture can then be read. The same applies
# to any scenario left `running` or `failed` -- its fault may still be live
# -- so an unfinished run anywhere refuses every scenario, not just the
# next one. Checked before the first Azure call that breaks anything.
lab_state require-run "${SCENARIO}"

# Overridable only for tests; production runs use the defaults.
readonly ALERT_RESOLVE_TIMEOUT_SECONDS="${LAB_ALERT_RESOLVE_TIMEOUT_SECONDS:-1500}"
readonly ALERT_RESOLVE_POLL_INTERVAL_SECONDS="${LAB_ALERT_RESOLVE_POLL_INTERVAL_SECONDS:-20}"
readonly RECOVERY_HEALTH_TIMEOUT_SECONDS="${LAB_RECOVERY_HEALTH_TIMEOUT_SECONDS:-600}"
readonly ALERT_FIRE_TIMEOUT_SECONDS="${LAB_ALERT_FIRE_TIMEOUT_SECONDS:-720}"
readonly ALERT_FIRE_POLL_INTERVAL_SECONDS="${LAB_ALERT_FIRE_POLL_INTERVAL_SECONDS:-20}"
readonly REVISION_READY_TIMEOUT_SECONDS="${LAB_REVISION_READY_TIMEOUT_SECONDS:-600}"
readonly REVISION_READY_POLL_INTERVAL_SECONDS="${LAB_REVISION_READY_POLL_INTERVAL_SECONDS:-10}"
readonly S3_PROPAGATION_TIMEOUT_SECONDS="${LAB_S3_PROPAGATION_TIMEOUT_SECONDS:-300}"
readonly S3_PROPAGATION_POLL_INTERVAL_SECONDS="${LAB_S3_PROPAGATION_POLL_INTERVAL_SECONDS:-10}"

APP_NAME="$(deployment_output containerAppName)"
APP_FQDN="$(deployment_output containerAppFqdn)"
WORKLOAD_PRINCIPAL_ID="$(deployment_output containerAppPrincipalId)"
STORAGE_CONTAINER_SCOPE="$(deployment_output storageContainerScope)"
BLOB_ROLE_ASSIGNMENT_NAME="$(deployment_output blobRoleAssignmentName)"
readonly APP_NAME APP_FQDN WORKLOAD_PRINCIPAL_ID STORAGE_CONTAINER_SCOPE
readonly BLOB_ROLE_ASSIGNMENT_NAME

MISSING_OUTPUTS=""
[[ -n "${APP_NAME}" ]] || MISSING_OUTPUTS="${MISSING_OUTPUTS} containerAppName"
[[ -n "${APP_FQDN}" ]] || MISSING_OUTPUTS="${MISSING_OUTPUTS} containerAppFqdn"
if [[ "${SCENARIO}" == "s3" ]]; then
  [[ -n "${WORKLOAD_PRINCIPAL_ID}" ]] || MISSING_OUTPUTS="${MISSING_OUTPUTS} containerAppPrincipalId"
  [[ -n "${STORAGE_CONTAINER_SCOPE}" ]] || MISSING_OUTPUTS="${MISSING_OUTPUTS} storageContainerScope"
  [[ -n "${BLOB_ROLE_ASSIGNMENT_NAME}" ]] || MISSING_OUTPUTS="${MISSING_OUTPUTS} blobRoleAssignmentName"
fi
if [[ -n "${MISSING_OUTPUTS}" ]]; then
  echo "Missing deployment outputs:${MISSING_OUTPUTS}. Run: azd provision" >&2
  exit 1
fi

EVIDENCE_DIR="$(evidence_dir_path "${SCENARIO}")"
readonly EVIDENCE_DIR

# The attempt is recorded before anything can break, and clears whatever
# the previous attempt left behind. Everything below this line can exit
# without reaching `mark-recovered`/`mark-failed` -- a rejected injection,
# a recovery the EXIT trap cannot complete, a Ctrl-C -- and the state file
# must never keep describing the run this one replaces: a re-run of an
# already-captured scenario would otherwise leave `recovered` +
# `conclusion` in place and admit the next scenario on evidence from a run
# that no longer exists.
#
# `begin-run` is also the last gate: it re-reads `state.json` and refuses
# while any scenario is still `running` or `failed`, which covers the
# window between the `require-run` above and here. The directory is only
# created afterwards, so a refusal leaves nothing behind in `evidence/`.
lab_state begin-run "${SCENARIO}" "${EVIDENCE_DIR}"
mkdir -p "${EVIDENCE_DIR}"
readonly ALERT_LIST_RESPONSE_FILE="${EVIDENCE_DIR}/alert-list-response.json"
readonly ALERT_LIST_ERROR_FILE="${EVIDENCE_DIR}/alert-list-error.log"
readonly ALERT_LIST_ATTEMPT_ERROR_FILE="${EVIDENCE_DIR}/.alert-list-error.tmp"

RECOVERED=0
OUTCOME_RECORDED=0
ALERT_LIST_FAILURES=0
ALERT_LIST_VALID_RESPONSES=0
ALERT_LIST_POLLS=0
INJECTED_AT=""
REVISION_READY_AT=""
ROLE_DELETED_AT=""
ALERT_RULE_NAME=""
ALERT_ID=""
ALERT_FIRED_AT=""

record_failed_run() {
  local reason="$1"
  if ! lab_state mark-failed "${SCENARIO}" "${EVIDENCE_DIR}" --reason "${reason}"; then
    return 1
  fi
  OUTCOME_RECORDED=1
}

wait_for_s3_fault() {
  local started="${SECONDS}"
  local probe_file="${EVIDENCE_DIR}/rbac-probe.json"

  while (( SECONDS - started < S3_PROPAGATION_TIMEOUT_SECONDS )); do
    if python3 "${SCRIPT_DIR}/loadgen.py" \
      "https://${APP_FQDN}/api/documents" \
      --requests 1 \
      --concurrency 1 \
      --expect-status 503 \
      --output "${probe_file}"; then
      return 0
    fi
    echo "Waiting for the Storage RBAC deletion to reach the data plane..." >&2
    sleep "${S3_PROPAGATION_POLL_INTERVAL_SECONDS}"
  done

  echo "Storage RBAC deletion did not produce HTTP 503 within ${S3_PROPAGATION_TIMEOUT_SECONDS}s." >&2
  return 1
}

# restore_container_app_env SETTING -- reverts one injected Container App
# setting and waits for the revision that carries it to become active.
#
# Every step is checked explicitly. `recover` is also called as
# `if ! recover` from the EXIT trap, and bash disables `set -e` inside a
# function invoked in a condition: an unchecked `az` failure or a timed-out
# wait would fall through to `RECOVERED=1` and report a recovery that never
# happened, leaving the fault live in the Container App.
restore_container_app_env() {
  local setting="$1"
  local old_revision

  if ! old_revision="$(latest_revision_name "${APP_NAME}")"; then
    echo "Recovery failed: could not read the current revision of ${APP_NAME}." >&2
    return 1
  fi
  if ! az containerapp update \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${APP_NAME}" \
    --set-env-vars "${setting}" \
    --output none; then
    echo "Recovery failed: az containerapp update ${setting} was rejected." >&2
    return 1
  fi
  if ! wait_for_new_revision_ready \
    "${APP_NAME}" \
    "${old_revision}" \
    "${REVISION_READY_TIMEOUT_SECONDS}" \
    "${REVISION_READY_POLL_INTERVAL_SECONDS}" >/dev/null; then
    echo "Recovery failed: no new healthy revision carrying ${setting}." >&2
    return 1
  fi
}

# Restores S3's deleted `Storage Blob Data Reader` assignment. A read that
# fails is not "the assignment is missing": it is an unknown state, and
# creating on top of an unknown state is not a recovery either, so both
# propagate.
restore_blob_role() {
  local existing_assignment

  if ! existing_assignment="$(az role assignment list \
    --scope "${STORAGE_CONTAINER_SCOPE}" \
    --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
    --query "[?roleDefinitionName=='Storage Blob Data Reader'].id | [0]" \
    -o tsv)"; then
    echo "Recovery failed: could not read the blob role assignments of ${STORAGE_CONTAINER_SCOPE}." >&2
    return 1
  fi
  if [[ -n "${existing_assignment}" ]]; then
    return 0
  fi
  if ! az role assignment create \
    --name "${BLOB_ROLE_ASSIGNMENT_NAME}" \
    --assignee-object-id "${WORKLOAD_PRINCIPAL_ID}" \
    --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Reader" \
    --scope "${STORAGE_CONTAINER_SCOPE}" \
    --output none; then
    echo "Recovery failed: could not restore Storage Blob Data Reader for ${WORKLOAD_PRINCIPAL_ID}." >&2
    return 1
  fi
}

# `RECOVERED=1` is reached only when the whole branch succeeded, so a failed
# attempt is retried by the EXIT trap instead of being remembered as done.
recover() {
  if [[ "${RECOVERED}" -eq 1 ]]; then
    return 0
  fi

  case "${SCENARIO}" in
    s1) restore_container_app_env FAILURE_MODE=none || return 1 ;;
    s2) restore_container_app_env ORDER_DELAY_MS=0 || return 1 ;;
    s3) restore_blob_role || return 1 ;;
    *)
      echo "Recovery failed: no recovery is defined for ${SCENARIO}." >&2
      return 1
      ;;
  esac

  RECOVERED=1
  return 0
}

recover_on_exit() {
  local original_status="$?"
  local recovery_status=0
  local failure_reason
  trap - EXIT
  if ! recover; then
    recovery_status=1
    echo "CRITICAL: scenario recovery failed for ${SCENARIO}." >&2
    echo "CRITICAL: the injected fault is still active. Revert it by hand before running any other scenario." >&2
  fi
  if [[ "${OUTCOME_RECORDED}" -eq 0 ]]; then
    failure_reason="run aborted with status ${original_status}"
    if [[ "${recovery_status}" -ne 0 ]]; then
      failure_reason="${failure_reason}; automatic recovery failed"
    fi
    if ! record_failed_run "${failure_reason}"; then
      echo "CRITICAL: could not record the aborted ${SCENARIO} run as failed." >&2
    fi
  fi
  if [[ "${recovery_status}" -ne 0 ]]; then
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
    wait_for_new_revision_ready \
      "${APP_NAME}" \
      "${OLD_REVISION}" \
      "${REVISION_READY_TIMEOUT_SECONDS}" \
      "${REVISION_READY_POLL_INTERVAL_SECONDS}" >/dev/null
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
    wait_for_new_revision_ready \
      "${APP_NAME}" \
      "${OLD_REVISION}" \
      "${REVISION_READY_TIMEOUT_SECONDS}" \
      "${REVISION_READY_POLL_INTERVAL_SECONDS}" >/dev/null
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
    if ! wait_for_s3_fault; then
      S3_PROPAGATION_FAILURE="Storage RBAC deletion did not produce HTTP 503 within ${S3_PROPAGATION_TIMEOUT_SECONDS}s."
      record_failed_run "${S3_PROPAGATION_FAILURE}"
      exit 1
    fi
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
while (( SECONDS - started < ALERT_FIRE_TIMEOUT_SECONDS )); do
  ALERT_LIST_POLLS=$((ALERT_LIST_POLLS + 1))
  if ! az rest \
    --method get \
    --url "https://management.azure.com/subscriptions/${SUBSCRIPTION_ID}/providers/Microsoft.AlertsManagement/alerts?api-version=2019-03-01&targetResourceGroup=${RESOURCE_GROUP}&monitorCondition=Fired" \
    >"${ALERT_LIST_RESPONSE_FILE}" 2>"${ALERT_LIST_ATTEMPT_ERROR_FILE}"; then
    ALERT_LIST_FAILURES=$((ALERT_LIST_FAILURES + 1))
    mv "${ALERT_LIST_ATTEMPT_ERROR_FILE}" "${ALERT_LIST_ERROR_FILE}"
    echo "Azure Alerts list request failed; the last error is in ${ALERT_LIST_ERROR_FILE}. Retrying within the ${ALERT_FIRE_TIMEOUT_SECONDS}s budget." >&2
    sleep "${ALERT_FIRE_POLL_INTERVAL_SECONDS}"
    continue
  fi
  rm -f "${ALERT_LIST_ATTEMPT_ERROR_FILE}"
  if [[ ! -s "${ALERT_LIST_RESPONSE_FILE}" ]]; then
    ALERT_LIST_FAILURES=$((ALERT_LIST_FAILURES + 1))
    ALERT_ID=""
    echo "Azure Alerts list returned an empty response." >"${ALERT_LIST_ERROR_FILE}"
    echo "Azure Alerts list returned an empty response; details are in ${ALERT_LIST_ERROR_FILE}. Retrying within the ${ALERT_FIRE_TIMEOUT_SECONDS}s budget." >&2
    sleep "${ALERT_FIRE_POLL_INTERVAL_SECONDS}"
    continue
  fi
  alerts_json="$(cat "${ALERT_LIST_RESPONSE_FILE}")"
  candidate_alert_id=""
  if ! candidate_alert_id="$(jq -r \
    --arg rule "${ALERT_RULE_NAME}" \
    'first(.value[] | select(.properties.essentials.alertRule | endswith($rule)) | .id) // ""' \
    <<<"${alerts_json}" 2>/dev/null)"; then
    ALERT_LIST_FAILURES=$((ALERT_LIST_FAILURES + 1))
    ALERT_ID=""
    printf 'Azure Alerts list returned invalid JSON. Response: %s\n' "${alerts_json}" >"${ALERT_LIST_ERROR_FILE}"
    echo "Azure Alerts list returned invalid JSON; details are in ${ALERT_LIST_ERROR_FILE}. Retrying within the ${ALERT_FIRE_TIMEOUT_SECONDS}s budget." >&2
    sleep "${ALERT_FIRE_POLL_INTERVAL_SECONDS}"
    continue
  fi
  ALERT_LIST_VALID_RESPONSES=$((ALERT_LIST_VALID_RESPONSES + 1))
  ALERT_ID="${candidate_alert_id}"
  if [[ -n "${ALERT_ID}" ]]; then
    ALERT_FIRED_AT="$(jq -r \
      --arg id "${ALERT_ID}" \
      '.value[] | select(.id == $id) | .properties.essentials.startDateTime' \
      <<<"${alerts_json}")"
    break
  fi
  sleep "${ALERT_FIRE_POLL_INTERVAL_SECONDS}"
done

# No alert ever firing is a distinct failure from one that fires and never
# resolves, but it is just as unusable as evidence: recorded as a failed
# run -- with the evidence directory and a reason -- before this exits, so
# a later `lab.sh score` or the next scenario's gate can never read this
# attempt as anything but failed. The EXIT trap (still armed here) still
# reverts whatever was injected above.
if [[ -z "${ALERT_ID}" ]]; then
  if [[ "${ALERT_LIST_VALID_RESPONSES}" -eq 0 && "${ALERT_LIST_FAILURES}" -gt 0 ]]; then
    ALERT_NEVER_FIRED_REASON="could not query Azure Alerts after ${ALERT_LIST_FAILURES} failed attempts within ${ALERT_FIRE_TIMEOUT_SECONDS}s; last error: ${ALERT_LIST_ERROR_FILE}"
  else
    ALERT_NEVER_FIRED_REASON="alert ${ALERT_RULE_NAME} did not fire within ${ALERT_FIRE_TIMEOUT_SECONDS}s."
    if [[ "${ALERT_LIST_FAILURES}" -gt 0 ]]; then
      ALERT_NEVER_FIRED_REASON="${ALERT_NEVER_FIRED_REASON} ${ALERT_LIST_FAILURES} of ${ALERT_LIST_POLLS} polls failed; last error: ${ALERT_LIST_ERROR_FILE}"
    fi
  fi
  echo "${ALERT_NEVER_FIRED_REASON}" >&2
  echo "Evidence directory: ${EVIDENCE_DIR}" >&2
  record_failed_run "${ALERT_NEVER_FIRED_REASON}"
  exit 1
fi

recover
RECOVERED_AT="$(utc_now)"
readonly RECOVERED_AT

# Recovery is only real when the workload is healthy again *and* Azure
# Monitor closed the alert this run fired. Both are waited for before any
# state transition, so a timeout leaves the scenario failed and the next
# scenario blocked instead of recording a recovery nobody confirmed.
RECOVERY_CONFIRMED=1
RECOVERY_FAILURE=""
if ! wait_for_app_ready "${APP_NAME}" "${RECOVERY_HEALTH_TIMEOUT_SECONDS}"; then
  RECOVERY_CONFIRMED=0
  RECOVERY_FAILURE="workload did not become healthy within ${RECOVERY_HEALTH_TIMEOUT_SECONDS}s"
fi

ALERT_RESOLVED_AT=""
if [[ "${RECOVERY_CONFIRMED}" -eq 1 ]]; then
  if ALERT_RESOLVED_AT="$(wait_for_alert_resolved \
    "${ALERT_ID}" \
    "${ALERT_RESOLVE_TIMEOUT_SECONDS}" \
    "${ALERT_RESOLVE_POLL_INTERVAL_SECONDS}")"; then
    :
  else
    ALERT_RESOLVED_AT=""
    RECOVERY_CONFIRMED=0
    RECOVERY_FAILURE="alert ${ALERT_RULE_NAME} was not Resolved within ${ALERT_RESOLVE_TIMEOUT_SECONDS}s"
  fi
fi
readonly ALERT_RESOLVED_AT RECOVERY_CONFIRMED RECOVERY_FAILURE

jq -n \
  --arg scenario "${SCENARIO}" \
  --arg injectedAt "${INJECTED_AT}" \
  --arg revisionReadyAt "${REVISION_READY_AT}" \
  --arg roleDeletedAt "${ROLE_DELETED_AT}" \
  --arg alertRule "${ALERT_RULE_NAME}" \
  --arg alertId "${ALERT_ID}" \
  --arg alertFiredAt "${ALERT_FIRED_AT}" \
  --arg recoveredAt "${RECOVERED_AT}" \
  --arg alertResolvedAt "${ALERT_RESOLVED_AT}" \
  '{
    scenario: $scenario,
    injected_at: $injectedAt,
    revision_ready_at: (if $revisionReadyAt == "" then null else $revisionReadyAt end),
    role_deleted_at: (if $roleDeletedAt == "" then null else $roleDeletedAt end),
    alert_rule: $alertRule,
    alert_id: $alertId,
    alert_fired_at: $alertFiredAt,
    recovered_at: $recoveredAt,
    alert_resolved_at: (if $alertResolvedAt == "" then null else $alertResolvedAt end)
  }' | tee "${EVIDENCE_DIR}/timeline.json"

if [[ "${RECOVERY_CONFIRMED}" -ne 1 ]]; then
  echo "Scenario ${SCENARIO} is recorded as failed: ${RECOVERY_FAILURE}." >&2
  echo "Evidence directory: ${EVIDENCE_DIR}" >&2
  record_failed_run "${RECOVERY_FAILURE}"
  exit 1
fi

lab_state mark-recovered "${SCENARIO}" "${EVIDENCE_DIR}"
OUTCOME_RECORDED=1

printf 'Evidence directory: %s\n' "${EVIDENCE_DIR}"
