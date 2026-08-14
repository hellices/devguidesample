#!/usr/bin/env bash
set -euo pipefail

for command_name in az azd jq curl python3; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

az account show --output none
azd auth login --check-status

for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
  Microsoft.Storage Microsoft.ContainerRegistry Microsoft.ManagedIdentity \
  Microsoft.Network; do
  az provider register --namespace "${provider}" --wait
done

if [[ -z "$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null || true)" ]]; then
  azd env set AZURE_RESOURCE_GROUP "rg-$(azd env get-value AZURE_ENV_NAME)"
fi

if [[ -z "$(azd env get-value SRE_LAB_EXPIRES_ON 2>/dev/null || true)" ]]; then
  expires_on="$(python3 -c 'from datetime import date,timedelta; print(date.today()+timedelta(days=1))')"
  azd env set SRE_LAB_EXPIRES_ON "${expires_on}"
fi
