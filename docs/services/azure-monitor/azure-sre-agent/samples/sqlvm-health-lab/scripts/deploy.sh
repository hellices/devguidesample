#!/usr/bin/env bash
# Deploys the lab infrastructure, prepares SQL Server, registers the SRE Agent
# tool and skill, installs the SQL Server metrics pipeline, and imports the
# Grafana dashboard.
#
# Usage: scripts/deploy.sh [resource-group] [location]
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RG="${1:-${LAB_RESOURCE_GROUP:-rg-sqlvm-sre-lab}}"
LOCATION="${2:-${LAB_LOCATION:-koreacentral}}"
DEPLOYMENT="sqlvm-sre-lab-$(date +%Y%m%d%H%M%S)"

for cmd in az jq openssl curl python3; do
  command -v "$cmd" >/dev/null || { echo "missing command: $cmd" >&2; exit 1; }
done

gen_password() {
  # 24 chars with upper, lower, digit, and symbol classes for the Windows policy.
  # The value is discarded: the VM has no RDP path, and configure-sql.sh
  # resets it to a new one-time value when it needs to run as the local admin.
  printf '%s%s' "$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 20)" 'aZ9!'
}

DEPLOYER_OID="$(az ad signed-in-user show --query id -o tsv)"

echo "==> Deploying infrastructure to ${RG} (${LOCATION})"
az deployment sub create \
  --name "$DEPLOYMENT" \
  --location "$LOCATION" \
  --template-file "$SAMPLE_DIR/infra/main.bicep" \
  --parameters resourceGroupName="$RG" location="$LOCATION" \
               deployerObjectId="$DEPLOYER_OID" \
               adminPassword="$(gen_password)" \
  --no-wait
# Long-running SQL IaaS registration can outlive a single CLI request, so wait explicitly.
az deployment sub wait --name "$DEPLOYMENT" --custom "properties.provisioningState!='Running' && properties.provisioningState!='Accepted'" --interval 30 --timeout 3600
STATE="$(az deployment sub show --name "$DEPLOYMENT" --query properties.provisioningState -o tsv)"
if [[ "$STATE" != "Succeeded" ]]; then
  echo "deployment ${DEPLOYMENT} finished with state ${STATE}" >&2
  az deployment operation sub list --name "$DEPLOYMENT" \
    --query "[?properties.provisioningState=='Failed'].properties.statusMessage" -o json >&2
  exit 1
fi

OUTPUTS="$(az deployment sub show --name "$DEPLOYMENT" --query properties.outputs -o json)"

STATE_FILE="$SAMPLE_DIR/.lab-state.json"
jq --arg location "$LOCATION" '{
    resourceGroup: .resourceGroupName.value, location: $location,
    vmName: .vmName.value, vmId: .vmId.value,
    sqlHost: .sqlHost.value, sqlPort: .sqlPort.value,
    sqlLogin: "sre_monitor", secretName: "sql-monitor-password",
    keyVaultName: .keyVaultName.value, keyVaultId: .keyVaultId.value,
    agentName: .agentName.value, agentId: .agentId.value,
    agentIdentityClientId: .agentIdentityClientId.value,
    vmMetricsClientId: .vmMetricsClientId.value, vmMetricsPrincipalId: .vmMetricsPrincipalId.value,
    monitorWorkspaceId: .monitorWorkspaceId.value, prometheusQueryEndpoint: .prometheusQueryEndpoint.value,
    grafanaName: .grafanaName.value, grafanaEndpoint: .grafanaEndpoint.value
  }' <<<"$OUTPUTS" > "$STATE_FILE"
echo "==> Wrote $STATE_FILE"

"$SAMPLE_DIR/scripts/configure-sql.sh"
"$SAMPLE_DIR/scripts/apply-agent-config.sh"
"$SAMPLE_DIR/scripts/configure-monitoring.sh"
"$SAMPLE_DIR/scripts/import-dashboard.sh"

echo "==> Done."
echo "    Agent:   https://sre.azure.com  (ask: 'SQL Server VM 상태를 점검해줘')"
echo "    Grafana: $(jq -r .grafanaEndpoint "$STATE_FILE")"
