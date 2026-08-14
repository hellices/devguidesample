#!/usr/bin/env bash
# Teardown hook for `azd down`. Two modes, one per hook:
#
#   predown  (default)          Remove the lab resources that live *outside*
#                               the azd-owned resource group, so azd can
#                               delete everything else itself.
#   postdown --reset-image-env  Clear the azd environment values
#                               `azd-postprovision.sh` recorded, once the
#                               resources they point at are really gone.
#
# The only external resources are the subscription-scoped Monitoring
# Contributor assignments the Azure SRE Agent setup recorded in
# `evidence/agent-setup.json`. Nothing else is ever deleted here: no
# resource groups, no resources, no unrecorded role assignment. When the
# evidence file is missing the lab never configured the Agent, so the hook
# reports that and succeeds -- `azd down` must not fail because an optional
# step was skipped.
#
# Before deleting anything, every recorded record has to survive four
# checks, because the evidence file is a plain JSON file an operator can
# edit:
#
#   1. the assignment ID names a role assignment in the subscription this
#      run resolved (`AZURE_SUBSCRIPTION_ID` > the current azd environment);
#   2. the Azure CLI is signed in to exactly that subscription;
#   3. the record carries the Agent principal the assignment was created
#      for;
#   4. the live assignment really holds that principal, the Monitoring
#      Contributor role definition, and subscription scope.
#
# A record that fails any of them stops the hook before *any* deletion. A
# recorded assignment that is empty or already gone is a safe no-op, so
# re-running `azd down` works.
#
# Why the image values are cleared in `postdown` and not here: `predown`
# runs before azd asks the operator to confirm the deletion. An operator who
# answers "no" keeps every resource, so clearing SRE_CONTAINER_IMAGE /
# SRE_IMAGE_TAG at that point would break an environment nothing happened
# to. `postdown` is the documented counterpart hook (azd command hooks:
# pre/post for restore, provision, package, deploy, publish, up and down),
# and azd runs a post hook only after the action itself succeeded --
# `HooksRunner.Invoke` returns early when the action fails
# (cli/azd/pkg/ext/hooks_runner.go), so a cancelled or failed `azd down`
# leaves the recorded image values alone.
set -euo pipefail

CLEANUP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck source=./common.sh
source "${CLEANUP_SCRIPT_DIR}/common.sh"

# `SRE_LAB_EVIDENCE_ROOT` lets a test point the hook at a scratch evidence
# directory; every real run reads the lab's own `evidence/`.
readonly CLEANUP_EVIDENCE_ROOT="${SRE_LAB_EVIDENCE_ROOT:-${EVIDENCE_ROOT}}"
readonly CLEANUP_SETUP_FILE="${CLEANUP_EVIDENCE_ROOT}/agent-setup.json"
readonly MONITORING_CONTRIBUTOR_ROLE_ID="749f88d5-cbae-40b8-bcfc-e573ddc772fa"

usage() {
  cat <<'USAGE'
Usage: cleanup-external.sh [--reset-image-env] [--yes]

  (default)          Remove the recorded subscription-scoped Monitoring
                     Contributor assignments that live outside the azd
                     resource group. Run by `azd down` as its predown hook.
  --reset-image-env  Clear the azd environment values azd-postprovision.sh
                     recorded (SRE_CONTAINER_IMAGE, SRE_IMAGE_TAG) instead.
                     Run by `azd down` as its postdown hook.
  --yes              Execute. Without it, both modes only print their plan.
USAGE
}

MODE="roles"
CONFIRMED=0
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --yes) CONFIRMED=1 ;;
    --reset-image-env) MODE="image-env" ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  shift
done
readonly MODE CONFIRMED

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

if [[ "${MODE}" == "image-env" ]]; then
  require_command azd
  if [[ "${CONFIRMED}" -ne 1 ]]; then
    echo "Planned azd environment reset:"
    echo "  Clear hook-set SRE_CONTAINER_IMAGE and SRE_IMAGE_TAG."
    echo "Dry run only. Re-run with --yes to execute."
    exit 0
  fi
  # `--cwd` pins the write to this lab's azd project, so running the hook
  # by hand from the repository root does not resolve another project.
  azd env set SRE_CONTAINER_IMAGE "" --cwd "${LAB_ROOT}"
  azd env set SRE_IMAGE_TAG "" --cwd "${LAB_ROOT}"
  echo "Cleared hook-set SRE_CONTAINER_IMAGE and SRE_IMAGE_TAG."
  exit 0
fi

if [[ ! -f "${CLEANUP_SETUP_FILE}" ]]; then
  echo "No Azure SRE Agent setup evidence at ${CLEANUP_SETUP_FILE}."
  echo "Nothing outside the azd resource group to clean up."
  exit 0
fi

require_command az
require_command jq

SUBSCRIPTION_ID="$(require_setting AZURE_SUBSCRIPTION_ID "${AZURE_SUBSCRIPTION_ID:-}")"
readonly SUBSCRIPTION_ID
readonly SUBSCRIPTION_SCOPE="/subscriptions/${SUBSCRIPTION_ID}"

# The Azure CLI's active subscription is whatever the operator last
# selected, so it is read (the one deliberately unpinned call) and compared
# before anything is verified or deleted. A signed-out CLI is reported as
# itself instead of as a raw CLI error.
if ! ACTIVE_SUBSCRIPTION_ID="$(az account show --query id -o tsv 2>/dev/null)"; then
  echo "Azure CLI is not signed in, so recorded role assignments cannot be removed." >&2
  echo "Run: az login" >&2
  exit 1
fi
readonly ACTIVE_SUBSCRIPTION_ID
if [[ "${ACTIVE_SUBSCRIPTION_ID}" != "${SUBSCRIPTION_ID}" ]]; then
  echo "Refusing to continue in subscription ${ACTIVE_SUBSCRIPTION_ID}." >&2
  echo "Expected ${SUBSCRIPTION_ID}." >&2
  echo "Run: az account set --subscription ${SUBSCRIPTION_ID}" >&2
  exit 1
fi

# Only these two keys are ever read, each with the Agent principal it was
# created for. Any other content of the evidence file is ignored.
if ! RECORDED_ASSIGNMENTS="$(jq -r '
  [
    {
      assignment: (.monitoring_contributor_assignment_id // ""),
      principal: (.agent_principal_id // "")
    },
    {
      assignment: (.uami_monitoring_contributor_assignment_id // ""),
      principal: (.agent_user_assigned_principal_id // "")
    }
  ]
  | .[]
  | [.assignment, .principal]
  | @tsv
' "${CLEANUP_SETUP_FILE}" 2>/dev/null)"; then
  echo "Agent setup evidence is not valid JSON: ${CLEANUP_SETUP_FILE}" >&2
  echo "Recreate it: lab.sh acknowledge agent-setup" >&2
  exit 1
fi
readonly RECORDED_ASSIGNMENTS

# verify_recorded_assignment ID PRINCIPAL -- 0 when the live assignment is
# the recorded Agent one, 2 when it is already gone, 1 when the record
# cannot be trusted.
verify_recorded_assignment() {
  local assignment_id="$1"
  local expected_principal_id="$2"
  local expected_prefix
  expected_prefix="$(lowercase "${SUBSCRIPTION_SCOPE}")/providers/microsoft.authorization/roleassignments/"
  if [[ "$(lowercase "${assignment_id}")" != "${expected_prefix}"* ]]; then
    echo "Recorded role assignment does not belong to current subscription ${SUBSCRIPTION_ID}: ${assignment_id}" >&2
    return 1
  fi

  # `az rest`'s stdout is the ARM document this function parses with jq;
  # its stderr is diagnostics only -- an azure-cli warning (a preview
  # notice, an extension-update nag) on a *successful* call, or the real
  # error body on a failed one. A plain `2>&1` would merge the two: a
  # warning on an otherwise-healthy read corrupts the JSON and makes a live
  # assignment look unreadable, and a failure's real error can end up
  # interleaved with unrelated output. The two streams are therefore kept
  # apart with separate capture files (no array, no process substitution,
  # portable to Bash 3.2) and read back into their own variables.
  # `--only-show-errors` additionally asks azure-cli itself to drop most
  # warnings before they are ever written.
  local rest_stdout_file rest_stderr_file rest_status=0
  rest_stdout_file="$(mktemp)"
  rest_stderr_file="$(mktemp)"
  if ! az rest --only-show-errors --method get \
    --url "https://management.azure.com${assignment_id}?api-version=2022-04-01" \
    --subscription "${SUBSCRIPTION_ID}" \
    >"${rest_stdout_file}" 2>"${rest_stderr_file}"; then
    rest_status=1
  fi
  local assignment_json assignment_stderr
  assignment_json="$(cat "${rest_stdout_file}")"
  assignment_stderr="$(cat "${rest_stderr_file}")"
  rm -f "${rest_stdout_file}" "${rest_stderr_file}"

  if [[ "${rest_status}" -ne 0 ]]; then
    # A role assignment that no longer exists answers, verbatim (recorded
    # from azure-cli against a live subscription on 2026-08-14):
    #   ERROR: Not Found({"error":{"code":"RoleAssignmentNotFound", ...}})
    # which is an expected state during teardown, not a failure. Only
    # stderr is inspected for it -- never stdout, which a failing call must
    # not be trusted to have left empty.
    case "${assignment_stderr}" in
      *RoleAssignmentNotFound* | *RoleAssignmentDoesNotExist* | *ResourceNotFound*)
        echo "Recorded role assignment is already absent: ${assignment_id}"
        return 2
        ;;
    esac
    echo "Unable to verify recorded role assignment: ${assignment_id}" >&2
    echo "${assignment_stderr}" >&2
    return 1
  fi

  local actual_principal_id actual_role_id actual_scope
  actual_principal_id="$(jq -r '.properties.principalId // empty' <<<"${assignment_json}" 2>/dev/null || true)"
  actual_role_id="$(jq -r '.properties.roleDefinitionId // empty' <<<"${assignment_json}" 2>/dev/null || true)"
  actual_scope="$(jq -r '.properties.scope // empty' <<<"${assignment_json}" 2>/dev/null || true)"
  local expected_role_id="${SUBSCRIPTION_SCOPE}/providers/Microsoft.Authorization/roleDefinitions/${MONITORING_CONTRIBUTOR_ROLE_ID}"

  if [[ "$(lowercase "${actual_principal_id}")" != "$(lowercase "${expected_principal_id}")" ]]; then
    echo "Refusing role assignment held by another principal: ${assignment_id}" >&2
    echo "Recorded principal ${expected_principal_id}, assigned principal ${actual_principal_id:-unknown}." >&2
    return 1
  fi
  if [[ "$(lowercase "${actual_role_id}")" != "$(lowercase "${expected_role_id}")" ]]; then
    echo "Refusing role assignment of another role definition: ${assignment_id}" >&2
    return 1
  fi
  if [[ "$(lowercase "${actual_scope}")" != "$(lowercase "${SUBSCRIPTION_SCOPE}")" ]]; then
    echo "Refusing role assignment scoped to ${actual_scope:-unknown}, not ${SUBSCRIPTION_SCOPE}: ${assignment_id}" >&2
    return 1
  fi
}

# Every record is verified before the first deletion, so a single untrusted
# record leaves the whole subscription untouched. Held as a newline-joined
# string bounded by a leading newline as well as a trailing one, so the
# "already verified" check below can require a full `\n<id>\n` match --
# matching bare `<id>\n` (no leading boundary) would also accept any
# recorded ID that merely *ends with* the same characters as an
# already-verified one, silently treating a distinct, unverified record as
# a duplicate. Bash 3.2 (macOS) aborts under `set -u` when an empty array
# is expanded, which is why this stays a string instead of an array.
VERIFIED_ASSIGNMENT_IDS=$'\n'
while IFS=$'\t' read -r assignment_id expected_principal_id; do
  if [[ -z "${assignment_id}" ]]; then
    continue
  fi
  if [[ -z "${expected_principal_id}" ]]; then
    echo "Incomplete Agent setup evidence: ${assignment_id} was recorded without its Agent principal ID." >&2
    echo "Recreate it: lab.sh acknowledge agent-setup" >&2
    exit 1
  fi
  case "${VERIFIED_ASSIGNMENT_IDS}" in
    *$'\n'"${assignment_id}"$'\n'*) continue ;;
  esac

  verification_status=0
  verify_recorded_assignment "${assignment_id}" "${expected_principal_id}" || verification_status="$?"
  case "${verification_status}" in
    0) VERIFIED_ASSIGNMENT_IDS="${VERIFIED_ASSIGNMENT_IDS}${assignment_id}"$'\n' ;;
    2) ;;
    *) exit 1 ;;
  esac
done <<<"${RECORDED_ASSIGNMENTS}"
readonly VERIFIED_ASSIGNMENT_IDS

if [[ "${VERIFIED_ASSIGNMENT_IDS}" == $'\n' ]]; then
  echo "Agent setup evidence records no subscription role assignment to remove."
  exit 0
fi

echo "Planned external cleanup in ${SUBSCRIPTION_SCOPE}:"
while IFS= read -r assignment_id; do
  [[ -n "${assignment_id}" ]] || continue
  echo "  Remove recorded role assignment: ${assignment_id}"
done <<<"${VERIFIED_ASSIGNMENT_IDS}"

if [[ "${CONFIRMED}" -ne 1 ]]; then
  echo "Dry run only. Re-run with --yes to execute."
  exit 0
fi

# A role assignment left behind is the one outcome this hook exists to
# prevent, so a failed deletion stops `azd down` before it destroys the
# resource group -- nothing is lost, and the run can be repeated.
DELETION_FAILED=0
while IFS= read -r assignment_id; do
  [[ -n "${assignment_id}" ]] || continue
  if ! az role assignment delete --ids "${assignment_id}" --subscription "${SUBSCRIPTION_ID}" --output none; then
    echo "Could not remove recorded role assignment: ${assignment_id}" >&2
    DELETION_FAILED=1
  fi
done <<<"${VERIFIED_ASSIGNMENT_IDS}"

if [[ "${DELETION_FAILED}" -ne 0 ]]; then
  echo "External cleanup incomplete; remove the assignment above and re-run." >&2
  exit 1
fi

echo "External cleanup complete."
