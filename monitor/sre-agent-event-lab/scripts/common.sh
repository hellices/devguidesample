#!/usr/bin/env bash
set -euo pipefail

readonly SUBSCRIPTION_ID="95933ae5-0201-4a21-a1fc-8051a7437982"
readonly SUBSCRIPTION_NAME="ME-MngEnvMCAP310512-inhwanhwang-3"
readonly RESOURCE_GROUP="rg-sre-agent-event-lab-krc"
readonly LOCATION="koreacentral"
readonly FINAL_DEPLOYMENT_NAME="sre-agent-event-lab-app"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
readonly EVIDENCE_ROOT="${LAB_ROOT}/evidence"
readonly AGENT_SETUP_FILE="${EVIDENCE_ROOT}/agent-setup.json"

require_commands() {
  local command_name
  for command_name in az jq curl python3; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      echo "Required command not found: ${command_name}" >&2
      return 1
    fi
  done
}

verify_subscription() {
  local current_subscription
  current_subscription="$(az account show --query id -o tsv)"
  if [[ "${current_subscription}" != "${SUBSCRIPTION_ID}" ]]; then
    echo "Refusing to continue in subscription ${current_subscription}." >&2
    echo "Expected ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})." >&2
    return 1
  fi
}

resource_group_exists() {
  [[ "$(az group exists --name "${RESOURCE_GROUP}" -o tsv)" == "true" ]]
}

verify_lab_resource_group() {
  if ! resource_group_exists; then
    echo "Lab resource group does not exist: ${RESOURCE_GROUP}" >&2
    return 1
  fi

  local purpose
  purpose="$(az group show --name "${RESOURCE_GROUP}" --query "tags.purpose" -o tsv)"
  if [[ "${purpose}" != "sre-agent-event-lab" ]]; then
    echo "Refusing to operate on untagged resource group ${RESOURCE_GROUP}." >&2
    return 1
  fi
}

deployment_output() {
  local output_name="$1"
  az deployment group show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${FINAL_DEPLOYMENT_NAME}" \
    --query "properties.outputs.${output_name}.value" \
    -o tsv
}

create_evidence_dir() {
  local scenario="$1"
  local timestamp
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local directory="${EVIDENCE_ROOT}/${scenario}-${timestamp}"
  mkdir -p "${directory}"
  printf '%s\n' "${directory}"
}

utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

wait_for_app_ready() {
  local app_name="$1"
  local timeout_seconds="${2:-600}"
  local started="${SECONDS}"

  while (( SECONDS - started < timeout_seconds )); do
    local state
    state="$(az containerapp revision list \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${app_name}" \
      --query "[?properties.active].properties.healthState | [0]" \
      -o tsv 2>/dev/null || true)"
    if [[ "${state}" == "Healthy" ]]; then
      return 0
    fi
    sleep 10
  done

  echo "Container App did not become healthy within ${timeout_seconds}s." >&2
  return 1
}
