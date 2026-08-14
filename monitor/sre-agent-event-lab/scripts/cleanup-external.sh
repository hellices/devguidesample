#!/usr/bin/env bash
# Removes only the lab resources that live outside the azd-owned resource
# group, so `azd down` can delete everything else itself, and clears the
# azd environment values that `azd-postprovision.sh` set for this run.
#
# Today the external resources are the subscription-scoped Monitoring
# Contributor assignments recorded by the Azure SRE Agent setup. Nothing
# else is ever deleted here: no resource groups, no resources, no
# unrecorded role assignments. When the evidence file is missing the lab
# never configured the Agent, so the hook reports that and succeeds --
# `azd down` must not fail because an optional step was skipped.
#
# `azd down` may delete the resource group (and the ACR inside it) that
# `azd-postprovision.sh` recorded in SRE_CONTAINER_IMAGE/SRE_IMAGE_TAG. If
# those azd environment values survive, reusing the same environment would
# make a later `azd provision` try to redeploy an immutable image tag that
# no longer exists instead of falling back to the placeholder image. So
# this hook always clears both values -- independent of whether the Agent
# was ever configured -- before doing anything else.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
EVIDENCE_ROOT="${SRE_LAB_EVIDENCE_ROOT:-${LAB_ROOT}/evidence}"
readonly EVIDENCE_ROOT
readonly AGENT_SETUP_FILE="${EVIDENCE_ROOT}/agent-setup.json"

CONFIRMED=0
case "${1:-}" in
  "") ;;
  --yes) CONFIRMED=1 ;;
  *)
    echo "Usage: $0 [--yes]" >&2
    exit 2
    ;;
esac

command -v azd >/dev/null 2>&1 || {
  echo "Required command not found: azd" >&2
  exit 1
}

if [[ "${CONFIRMED}" -eq 1 ]]; then
  azd env set SRE_CONTAINER_IMAGE ""
  azd env set SRE_IMAGE_TAG ""
  echo "Cleared hook-set SRE_CONTAINER_IMAGE and SRE_IMAGE_TAG."
else
  echo "Dry run: would clear hook-set SRE_CONTAINER_IMAGE and SRE_IMAGE_TAG."
fi

if [[ ! -f "${AGENT_SETUP_FILE}" ]]; then
  echo "No Azure SRE Agent setup evidence at ${AGENT_SETUP_FILE}."
  echo "Nothing outside the azd resource group to clean up."
  exit 0
fi

for command_name in az jq; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

: "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID must be set to clean up recorded role assignments}"
readonly SUBSCRIPTION_SCOPE="/subscriptions/${AZURE_SUBSCRIPTION_ID}"

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

# Guards against a hand-edited evidence file pointing cleanup at a role
# assignment in another subscription or at a different resource type.
validate_recorded_assignment() {
  local assignment_id="$1"
  local assignment_id_lower expected_prefix

  assignment_id_lower="$(lowercase "${assignment_id}")"
  expected_prefix="$(lowercase "${SUBSCRIPTION_SCOPE}")/providers/microsoft.authorization/roleassignments/"

  if [[ "${assignment_id_lower}" != "${expected_prefix}"* ]]; then
    echo "Refusing role assignment outside ${SUBSCRIPTION_SCOPE}: ${assignment_id}" >&2
    return 1
  fi
}

RECORDED_ASSIGNMENT_IDS=""
while IFS= read -r assignment_id; do
  [[ -n "${assignment_id}" ]] || continue
  validate_recorded_assignment "${assignment_id}"
  case "${RECORDED_ASSIGNMENT_IDS}" in
    *"${assignment_id}"$'\n'*) continue ;;
  esac
  RECORDED_ASSIGNMENT_IDS="${RECORDED_ASSIGNMENT_IDS}${assignment_id}"$'\n'
done < <(jq -r '
  [
    .monitoring_contributor_assignment_id,
    .uami_monitoring_contributor_assignment_id
  ]
  | map(select(. != null and . != ""))
  | .[]
' "${AGENT_SETUP_FILE}")

if [[ -z "${RECORDED_ASSIGNMENT_IDS}" ]]; then
  echo "Agent setup evidence records no subscription role assignment."
  exit 0
fi

echo "Planned external cleanup in ${SUBSCRIPTION_SCOPE}:"
while IFS= read -r assignment_id; do
  [[ -n "${assignment_id}" ]] || continue
  echo "  Remove recorded role assignment: ${assignment_id}"
done <<<"${RECORDED_ASSIGNMENT_IDS}"

if [[ "${CONFIRMED}" -ne 1 ]]; then
  echo "Dry run only. Re-run with --yes to execute."
  exit 0
fi

while IFS= read -r assignment_id; do
  [[ -n "${assignment_id}" ]] || continue
  if ! az role assignment delete \
    --ids "${assignment_id}" \
    --subscription "${AZURE_SUBSCRIPTION_ID}" \
    --output none; then
    echo "Could not remove ${assignment_id}; remove it manually." >&2
  fi
done <<<"${RECORDED_ASSIGNMENT_IDS}"

echo "External cleanup complete."
