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

require_commands
verify_subscription

if ! resource_group_exists; then
  echo "Resource group ${RESOURCE_GROUP} is already absent."
  exit 0
fi
verify_lab_resource_group

ROLE_ASSIGNMENT_ID=""
if [[ -f "${AGENT_SETUP_FILE}" ]]; then
  ROLE_ASSIGNMENT_ID="$(jq -r '.monitoring_contributor_assignment_id // empty' \
    "${AGENT_SETUP_FILE}")"
fi

echo "Planned cleanup:"
if [[ -n "${ROLE_ASSIGNMENT_ID}" ]]; then
  echo "  Remove recorded role assignment: ${ROLE_ASSIGNMENT_ID}"
else
  echo "  No recorded subscription role assignment found."
fi
echo "  Delete tagged resource group: ${RESOURCE_GROUP}"

if [[ "${CONFIRMED}" -ne 1 ]]; then
  echo "Dry run only. Re-run with --yes to execute."
  exit 0
fi

if [[ -n "${ROLE_ASSIGNMENT_ID}" ]]; then
  az role assignment delete --ids "${ROLE_ASSIGNMENT_ID}"
fi

az group delete \
  --name "${RESOURCE_GROUP}" \
  --yes \
  --no-wait

echo "Deletion started for ${RESOURCE_GROUP}."
