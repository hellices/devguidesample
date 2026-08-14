#!/usr/bin/env bash
# Compatibility wrapper for the documented cleanup command.
#
# The lab is provisioned with azd, so `azd down --purge` is what tears it
# down: azd deletes the resource group it created, and its predown/postdown
# hooks run `cleanup-external.sh` for the two things azd cannot see (the
# recorded subscription-scoped role assignments, and the image values the
# postprovision hook stored). This script therefore only forwards to
# `cleanup-external.sh` -- it never deletes a resource group of its own,
# because a broad deletion here would also take resources azd did not
# create and knows nothing about.
#
# `--legacy-delete-resource-group` keeps the pre-azd recovery path
# available: a lab whose azd environment was lost still has to be
# deletable by hand. It runs the same subscription and tag checks the old
# script ran, so it can only ever delete a resource group tagged
# `purpose=sre-agent-event-lab` for the current azd environment.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

CONFIRMED=0
LEGACY_RESOURCE_GROUP=0
EXTERNAL_ARGS=()
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --yes)
      CONFIRMED=1
      EXTERNAL_ARGS+=("--yes")
      ;;
    --legacy-delete-resource-group) LEGACY_RESOURCE_GROUP=1 ;;
    *)
      echo "Usage: $0 [--yes] [--legacy-delete-resource-group]" >&2
      exit 2
      ;;
  esac
  shift
done
readonly CONFIRMED LEGACY_RESOURCE_GROUP

echo "Use 'azd down --purge' for complete cleanup."

external_cleanup() {
  # Bash 3.2 aborts on "${ARRAY[@]}" for an empty array under `set -u`.
  if (( ${#EXTERNAL_ARGS[@]} > 0 )); then
    "${SCRIPT_DIR}/cleanup-external.sh" "${EXTERNAL_ARGS[@]}"
  else
    "${SCRIPT_DIR}/cleanup-external.sh"
  fi
}

if [[ "${LEGACY_RESOURCE_GROUP}" -ne 1 ]]; then
  external_cleanup
  exit 0
fi

require_lab_config
verify_subscription

if ! resource_group_exists; then
  echo "Resource group ${RESOURCE_GROUP} is already absent."
  external_cleanup
  exit 0
fi
verify_lab_resource_group

external_cleanup

echo "Planned legacy cleanup:"
echo "  Delete tagged resource group: ${RESOURCE_GROUP}"

if [[ "${CONFIRMED}" -ne 1 ]]; then
  echo "Dry run only. Re-run with --yes to execute."
  exit 0
fi

az group delete \
  --name "${RESOURCE_GROUP}" \
  --yes \
  --no-wait

echo "Deletion started for ${RESOURCE_GROUP}."
