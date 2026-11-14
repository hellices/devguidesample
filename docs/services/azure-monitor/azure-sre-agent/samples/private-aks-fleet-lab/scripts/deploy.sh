#!/usr/bin/env bash
# Deploys the Multi-Hub Private AKS fleet lab infrastructure, links Private DNS
# zones to the SRE Agent VNet, grants AKS data-plane RBAC, and applies the
# fast-execution tools and skill.
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOURCE_GROUP="${1:-rg-private-aks-fleet}"
AGENT_LOCATION="${2:-koreacentral}"
AKS_LOCATION="${3:-australiaeast}"

ADMIN_OID="$(az ad signed-in-user show --query id -o tsv)"
echo "==> Deploying infrastructure to ${RESOURCE_GROUP} (${AGENT_LOCATION} / ${AKS_LOCATION})"

OUT="$(az deployment sub create \
  --location "$AGENT_LOCATION" \
  --template-file "$SAMPLE_DIR/infra/main.bicep" \
  --parameters resourceGroupName="$RESOURCE_GROUP" agentLocation="$AGENT_LOCATION" aksLocation="$AKS_LOCATION" adminPrincipalId="$ADMIN_OID" \
  --query properties.outputs -o json)"

AGENT_ID="$(echo "$OUT" | jq -r '.agentId.value')"
AGENT_NAME="$(echo "$OUT" | jq -r '.agentName.value')"
UAMI_OID="$(echo "$OUT" | jq -r '.agentUamiPrincipalId.value')"

jq -n \
  --arg rg "$RESOURCE_GROUP" \
  --arg id "$AGENT_ID" \
  --arg name "$AGENT_NAME" \
  --arg uami "$UAMI_OID" \
  '{resourceGroup: $rg, agentId: $id, agentName: $name, agentUamiPrincipalId: $uami}' \
  > "$SAMPLE_DIR/.lab-state.json"

echo "==> Granting AKS read-only data-plane RBAC to ${UAMI_OID}"
SUB_ID="$(az account show --query id -o tsv)"
for ROLE in "Azure Kubernetes Service Cluster User Role" "Azure Kubernetes Service RBAC Reader"; do
  az role assignment create \
    --assignee-object-id "$UAMI_OID" \
    --assignee-principal-type ServicePrincipal \
    --role "$ROLE" \
    --scope "/subscriptions/${SUB_ID}/resourceGroups/${RESOURCE_GROUP}" >/dev/null
done

"$SAMPLE_DIR/scripts/apply-agent-config.sh"
echo "==> Done. State saved to ${SAMPLE_DIR}/.lab-state.json"
