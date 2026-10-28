#!/usr/bin/env bash
# Installs windows_exporter, sql_exporter, and a Prometheus agent on the SQL
# Server VM, and lets the VM's metrics identity remote-write to the Azure
# Monitor workspace. Safe to re-run.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ADMIN_USER="${LAB_ADMIN_USER:-azureadmin}"
ONE_TIME_PASSWORD="$(printf '%s%s' "$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 20)" 'aZ9!')"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Resolving the Azure Monitor workspace ingestion endpoint"
WORKSPACE="$(az rest --method get --url "https://management.azure.com${MONITOR_WORKSPACE_ID}?api-version=2023-04-03" -o json)"
DCR_ID="$(jq -r .properties.defaultIngestionSettings.dataCollectionRuleResourceId <<<"$WORKSPACE")"
DCE_ID="$(jq -r .properties.defaultIngestionSettings.dataCollectionEndpointResourceId <<<"$WORKSPACE")"
DCR_IMMUTABLE_ID="$(az rest --method get --url "https://management.azure.com${DCR_ID}?api-version=2023-03-11" --query properties.immutableId -o tsv)"
INGESTION_ENDPOINT="$(az rest --method get --url "https://management.azure.com${DCE_ID}?api-version=2023-03-11" --query properties.metricsIngestion.endpoint -o tsv)"
REMOTE_WRITE_URL="${INGESTION_ENDPOINT}/dataCollectionRules/${DCR_IMMUTABLE_ID}/streams/Microsoft-PrometheusMetrics/api/v1/write?api-version=2023-04-24"

echo "==> Granting Monitoring Metrics Publisher on the workspace data collection rule"
if [[ -z "$(az role assignment list --assignee "$VM_METRICS_PRINCIPAL_ID" --scope "$DCR_ID" --role "Monitoring Metrics Publisher" --query "[0].id" -o tsv)" ]]; then
  az role assignment create --assignee-object-id "$VM_METRICS_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
    --role "Monitoring Metrics Publisher" --scope "$DCR_ID" -o none
fi

python3 "$SAMPLE_DIR/scripts/render_monitoring_script.py" "$STATE_FILE" "$REMOTE_WRITE_URL" > "$TMP/configure-monitoring.ps1"

# Installing software needs only local administrator rights, so it runs as
# LocalSystem. Only the SQL Server login step needs sysadmin and runs as the
# local administrator. With RunAs, a script failure is reported only as
# "Incorrect function" (exit code 1) without the script's error output.
echo "==> Installing windows_exporter, sql_exporter, and Prometheus agent on ${VM_NAME}"
run_on_vm configure-monitoring "$TMP/configure-monitoring.ps1" 1800

echo "==> Resetting ${ADMIN_USER} to a one-time password (VMAccess extension)"
az vm user update -g "$RG" -n "$VM_NAME" -u "$ADMIN_USER" -p "$ONE_TIME_PASSWORD" -o none

echo "==> Creating the SQL Server login for NT SERVICE\\SqlExporterSvc and checking remote_write"
run_on_vm grant-exporter-login "$SAMPLE_DIR/scripts/vm/grant-exporter-login.ps1" 1800 \
  --run-as-user "$ADMIN_USER" --run-as-password "$ONE_TIME_PASSWORD"
