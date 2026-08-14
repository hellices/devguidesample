#!/usr/bin/env bash
set -euo pipefail

for command_name in az azd jq curl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

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

if [[ -z "$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null || true)" ]]; then
  azd env set AZURE_RESOURCE_GROUP "rg-$(azd env get-value AZURE_ENV_NAME)"
fi

if [[ -z "$(azd env get-value SRE_LAB_EXPIRES_ON 2>/dev/null || true)" ]]; then
  expires_on="$(python3 -c 'from datetime import date,timedelta; print(date.today()+timedelta(days=1))')"
  azd env set SRE_LAB_EXPIRES_ON "${expires_on}"
fi
