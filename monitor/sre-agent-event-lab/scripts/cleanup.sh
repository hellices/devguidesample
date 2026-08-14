#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

CONFIRMED=0
if [[ "${1:-}" == "--yes" ]]; then
  CONFIRMED=1
elif [[ "$#" -gt 0 ]]; then
  echo "Usage: $0 [--yes]" >&2
  exit 2
fi

require_lab_config
verify_subscription

if ! resource_group_exists; then
  echo "Resource group ${RESOURCE_GROUP} is already absent."
  exit 0
fi
verify_lab_resource_group

readonly MONITORING_CONTRIBUTOR_ROLE_ID="749f88d5-cbae-40b8-bcfc-e573ddc772fa"
readonly SUBSCRIPTION_SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
ROLE_ASSIGNMENT_IDS=()

validate_recorded_assignment() {
  local assignment_id="$1"
  local expected_principal_id="$2"
  local assignment_json
  local assignment_id_lower subscription_scope_lower
  assignment_id_lower="$(printf '%s' "${assignment_id}" | tr '[:upper:]' '[:lower:]')"
  subscription_scope_lower="$(printf '%s' "${SUBSCRIPTION_SCOPE}" | tr '[:upper:]' '[:lower:]')"

  if [[ "${assignment_id_lower}" != "${subscription_scope_lower}/providers/microsoft.authorization/roleassignments/"* ]]; then
    echo "Refusing non-subscription role assignment: ${assignment_id}" >&2
    return 1
  fi

  if ! assignment_json="$(az rest --method get \
    --url "https://management.azure.com${assignment_id}?api-version=2022-04-01" \
    2>&1)"; then
    if [[ "${assignment_json}" == *"RoleAssignmentDoesNotExist"* \
      || "${assignment_json}" == *"ResourceNotFound"* ]]; then
      echo "Recorded role assignment is already absent: ${assignment_id}"
      return 2
    fi
    echo "Unable to verify recorded role assignment: ${assignment_id}" >&2
    echo "${assignment_json}" >&2
    return 1
  fi

  local actual_principal_id actual_role_id actual_scope
  actual_principal_id="$(jq -r '.properties.principalId // empty' <<<"${assignment_json}")"
  actual_role_id="$(jq -r '.properties.roleDefinitionId // empty' <<<"${assignment_json}")"
  actual_scope="$(jq -r '.properties.scope // empty' <<<"${assignment_json}")"
  local expected_role_id="${SUBSCRIPTION_SCOPE}/providers/Microsoft.Authorization/roleDefinitions/${MONITORING_CONTRIBUTOR_ROLE_ID}"
  local actual_principal_lower expected_principal_lower actual_role_lower
  local expected_role_lower actual_scope_lower
  actual_principal_lower="$(printf '%s' "${actual_principal_id}" | tr '[:upper:]' '[:lower:]')"
  expected_principal_lower="$(printf '%s' "${expected_principal_id}" | tr '[:upper:]' '[:lower:]')"
  actual_role_lower="$(printf '%s' "${actual_role_id}" | tr '[:upper:]' '[:lower:]')"
  expected_role_lower="$(printf '%s' "${expected_role_id}" | tr '[:upper:]' '[:lower:]')"
  actual_scope_lower="$(printf '%s' "${actual_scope}" | tr '[:upper:]' '[:lower:]')"

  if [[ "${actual_principal_lower}" != "${expected_principal_lower}" \
    || "${actual_role_lower}" != "${expected_role_lower}" \
    || "${actual_scope_lower}" != "${subscription_scope_lower}" ]]; then
    echo "Refusing mismatched role assignment: ${assignment_id}" >&2
    return 1
  fi
}

if [[ ! -f "${AGENT_SETUP_FILE}" ]]; then
  echo "Agent setup evidence is required for cleanup: ${AGENT_SETUP_FILE}" >&2
  exit 1
fi

required_setup_values=(
  "$(jq -r '.monitoring_contributor_assignment_id // empty' "${AGENT_SETUP_FILE}")"
  "$(jq -r '.agent_principal_id // empty' "${AGENT_SETUP_FILE}")"
  "$(jq -r '.uami_monitoring_contributor_assignment_id // empty' "${AGENT_SETUP_FILE}")"
  "$(jq -r '.agent_user_assigned_principal_id // empty' "${AGENT_SETUP_FILE}")"
)
for required_value in "${required_setup_values[@]}"; do
  if [[ -z "${required_value}" ]]; then
    echo "Incomplete Agent setup evidence; refusing cleanup." >&2
    exit 1
  fi
done

while IFS=$'\t' read -r assignment_id expected_principal_id; do
  if validate_recorded_assignment "${assignment_id}" "${expected_principal_id}"; then
    ROLE_ASSIGNMENT_IDS+=("${assignment_id}")
  else
    validation_status="$?"
    [[ "${validation_status}" -eq 2 ]] || exit "${validation_status}"
  fi
done < <(jq -r '
  [
    {
      assignment: .monitoring_contributor_assignment_id,
      principal: .agent_principal_id
    },
    {
      assignment: .uami_monitoring_contributor_assignment_id,
      principal: .agent_user_assigned_principal_id
    }
  ]
  | .[]
  | [.assignment, .principal]
  | @tsv
' "${AGENT_SETUP_FILE}")

echo "Planned cleanup:"
if (( ${#ROLE_ASSIGNMENT_IDS[@]} > 0 )); then
  for assignment_id in "${ROLE_ASSIGNMENT_IDS[@]}"; do
    echo "  Remove recorded role assignment: ${assignment_id}"
  done
else
  echo "  No recorded subscription role assignment found."
fi
echo "  Delete tagged resource group: ${RESOURCE_GROUP}"

if [[ "${CONFIRMED}" -ne 1 ]]; then
  echo "Dry run only. Re-run with --yes to execute."
  exit 0
fi

if (( ${#ROLE_ASSIGNMENT_IDS[@]} > 0 )); then
  for assignment_id in "${ROLE_ASSIGNMENT_IDS[@]}"; do
    az role assignment delete --ids "${assignment_id}"
  done
fi

az group delete \
  --name "${RESOURCE_GROUP}" \
  --yes \
  --no-wait

echo "Deletion started for ${RESOURCE_GROUP}."
