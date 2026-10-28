#!/usr/bin/env bash
# Deletes the lab resource group (VM, agent, Key Vault, Azure Monitor workspace,
# Managed Grafana) and purges the soft-deleted Key Vault so the lab can be
# redeployed with the same names.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

KEY_VAULT_NAME="$(state keyVaultName)"
LOCATION="$(state location)"
WORKSPACE_NAME="$(basename "$MONITOR_WORKSPACE_ID")"
# The workspace's default data collection rule and endpoint live in this
# Azure-managed resource group.
MANAGED_RG="MA_${WORKSPACE_NAME}_${LOCATION}_managed"

echo "==> Deleting resource group ${RG}"
az group delete -n "$RG" --yes

echo "==> Purging soft-deleted Key Vault ${KEY_VAULT_NAME}"
az keyvault purge -n "$KEY_VAULT_NAME" -l "$LOCATION" 2>/dev/null || true

if [[ "$(az group exists -n "$MANAGED_RG")" == "true" ]]; then
  echo "    note: ${MANAGED_RG} still exists; delete it after the workspace deletion finishes"
fi

rm -f "$STATE_FILE"
echo "==> Cleanup complete"
