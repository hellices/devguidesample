#!/usr/bin/env bash
# Prepares SQL Server through a managed Run Command that runs as the VM local
# administrator (a sysadmin on the SQL Server marketplace image), and stores
# the monitoring login password in Key Vault. Safe to re-run: each run rotates
# both the one-time administrator password and the monitoring password.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ADMIN_USER="${LAB_ADMIN_USER:-azureadmin}"
gen_password() { printf '%s%s' "$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 20)" 'aZ9!'; }
ONE_TIME_PASSWORD="$(gen_password)"
MONITOR_PASSWORD="$(gen_password)"

echo "==> Waiting for SQL IaaS Agent registration"
az resource wait --created -g "$RG" -n "$VM_NAME" \
  --resource-type Microsoft.SqlVirtualMachine/sqlVirtualMachines --interval 15 --timeout 900

echo "==> Resetting ${ADMIN_USER} to a one-time password (VMAccess extension)"
az vm user update -g "$RG" -n "$VM_NAME" -u "$ADMIN_USER" -p "$ONE_TIME_PASSWORD" -o none

echo "==> Creating ${SQL_LOGIN} and the SreDemo database on ${VM_NAME}"
run_on_vm configure-sql "$SAMPLE_DIR/scripts/vm/configure-sql.ps1" 1200 \
  --parameters MonitorLogin="$SQL_LOGIN" \
  --protected-parameters MonitorPassword="$MONITOR_PASSWORD" \
  --run-as-user "$ADMIN_USER" --run-as-password "$ONE_TIME_PASSWORD"

echo "==> Creating the login audit session, demo logins, and demo SQL Agent jobs"
run_on_vm configure-checks "$SAMPLE_DIR/scripts/vm/configure-checks.ps1" 600 \
  --run-as-user "$ADMIN_USER" --run-as-password "$ONE_TIME_PASSWORD"

# The vault has no public data-plane access. Writing the secret through Azure
# Resource Manager (control plane) does not need network access to the vault.
echo "==> Storing the ${SQL_LOGIN} password as Key Vault secret ${SECRET_NAME}"
BODY="$(jq -n --arg v "$MONITOR_PASSWORD" '{properties:{value:$v, contentType:"SQL login password"}}')"
az rest --method put \
  --url "https://management.azure.com${KEY_VAULT_ID}/secrets/${SECRET_NAME}?api-version=2024-11-01" \
  --body "$BODY" --query "properties.secretUriWithVersion" -o tsv >/dev/null
echo "    stored"
