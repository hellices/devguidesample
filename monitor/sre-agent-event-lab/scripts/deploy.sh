#!/usr/bin/env bash
# Compatibility wrapper. The lab is an azd project now: azure.yaml owns the
# Bicep entry point, the preprovision/postprovision hooks register providers,
# build the image in ACR, and move the Container App onto it. This script only
# forwards to `azd up` so the previously documented command keeps working.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT

command -v azd >/dev/null 2>&1 || {
  echo "Required command not found: azd (https://aka.ms/azd-install)" >&2
  exit 1
}

echo "deploy.sh now runs 'azd up' in ${LAB_ROOT}." >&2
cd "${LAB_ROOT}"
exec azd up "$@"
