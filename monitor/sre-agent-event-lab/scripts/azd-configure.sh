#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT

for command_name in az azd jq curl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

# azd_value NAME -- the current azd environment's value for NAME, or empty.
# azd 1.29 answers an unknown key with an `ERROR: ...` sentence on *stdout*
# and a non-zero exit status, so only a successful lookup may contribute a
# value; otherwise the defaults below would never be applied. `--cwd` pins
# every lookup to this lab's azd project so the hook also works when it is
# run by hand from another directory.
azd_value() {
  local name="$1"
  local stored_value
  if ! stored_value="$(azd env get-value "${name}" --cwd "${LAB_ROOT}" 2>/dev/null)"; then
    return 0
  fi
  printf '%s\n' "${stored_value}"
}

: "${AZURE_SUBSCRIPTION_ID:?AZURE_SUBSCRIPTION_ID must be set by azd before running this hook}"

# The Azure CLI's active account is whatever the operator selected last, which
# is not necessarily the subscription azd provisions into. Report the mismatch
# and pin every operation below to the azd subscription explicitly.
#
# `az account show` fails with a raw Azure CLI error when no one is signed
# in; guard it so the hook fails fast with one clear, actionable message
# instead of that raw stderr or an unexplained `set -e` abort.
if ! ACTIVE_SUBSCRIPTION_ID="$(az account show --query id -o tsv 2>/dev/null)"; then
  echo "Azure CLI is not signed in. Run 'az login', then re-run this command." >&2
  exit 1
fi
readonly ACTIVE_SUBSCRIPTION_ID
if [[ "${ACTIVE_SUBSCRIPTION_ID}" != "${AZURE_SUBSCRIPTION_ID}" ]]; then
  echo "Azure CLI is signed in to ${ACTIVE_SUBSCRIPTION_ID}." >&2
  echo "Every lab operation is pinned to ${AZURE_SUBSCRIPTION_ID} instead." >&2
fi

az account show --subscription "${AZURE_SUBSCRIPTION_ID}" --output none
azd auth login --check-status

for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
  Microsoft.Storage Microsoft.ContainerRegistry Microsoft.ManagedIdentity \
  Microsoft.Network; do
  az provider register --namespace "${provider}" --wait \
    --subscription "${AZURE_SUBSCRIPTION_ID}"
done

if [[ -z "$(azd_value AZURE_RESOURCE_GROUP)" ]]; then
  environment_name="$(azd_value AZURE_ENV_NAME)"
  if [[ -z "${environment_name}" ]]; then
    echo "The azd environment name is unavailable, so the lab resource group" >&2
    echo "cannot be derived. Run 'azd env new' or 'azd env select' first." >&2
    exit 1
  fi
  azd env set AZURE_RESOURCE_GROUP "rg-${environment_name}" --cwd "${LAB_ROOT}"
fi

if [[ -z "$(azd_value SRE_LAB_EXPIRES_ON)" ]]; then
  expires_on="$(python3 -c 'from datetime import date,timedelta; print(date.today()+timedelta(days=1))')"
  azd env set SRE_LAB_EXPIRES_ON "${expires_on}" --cwd "${LAB_ROOT}"
fi
