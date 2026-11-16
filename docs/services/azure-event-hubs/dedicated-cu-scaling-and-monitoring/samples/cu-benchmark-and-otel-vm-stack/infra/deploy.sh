#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-eh-cu-bench-kr}"
LOCATION="${LOCATION:-koreacentral}"
EH_TIER="${EH_TIER:-both}" # standard | premium | both | dedicated
INCLUDE_DEDICATED="${INCLUDE_DEDICATED:-false}"
ACTION="${1:-deploy}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [deploy|cleanup] [options]

Environment variables / flags:
  RESOURCE_GROUP              Target resource group (default: rg-eh-cu-bench-kr)
  LOCATION                    Azure region (default: koreacentral)
  EH_TIER                     standard | premium | both | dedicated (default: both)
  --include-dedicated         Also provision an Event Hubs Dedicated cluster (1 CU)
  CONFIRM_DEDICATED_4H_BILLING Must be 'yes' when deploying Dedicated cluster

Examples:
  # Track 1: Deploy Standard (TU) + Premium (PU) namespaces
  ./deploy.sh deploy

  # Track 2: Include Dedicated cluster (requires explicit 4-hour billing confirmation)
  CONFIRM_DEDICATED_4H_BILLING=yes ./deploy.sh deploy --include-dedicated

  # Delete temporary benchmark resource group
  ./deploy.sh cleanup
EOF
}

for arg in "$@"; do
  case "$arg" in
    --include-dedicated)
      INCLUDE_DEDICATED="true"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
  esac
done

if [[ "$ACTION" == "cleanup" ]]; then
  echo "[cleanup] Deleting resource group '${RESOURCE_GROUP}'..."
  az group delete --name "${RESOURCE_GROUP}" --yes --no-wait
  echo "[cleanup] Deletion initiated (--no-wait)."
  exit 0
fi

DEPLOY_STANDARD="true"
DEPLOY_PREMIUM="true"
DEPLOY_DEDICATED="false"

case "$EH_TIER" in
  standard)
    DEPLOY_STANDARD="true"
    DEPLOY_PREMIUM="false"
    ;;
  premium)
    DEPLOY_STANDARD="false"
    DEPLOY_PREMIUM="true"
    ;;
  both)
    DEPLOY_STANDARD="true"
    DEPLOY_PREMIUM="true"
    ;;
  dedicated)
    DEPLOY_STANDARD="true"
    DEPLOY_PREMIUM="true"
    DEPLOY_DEDICATED="true"
    ;;
  *)
    echo "Unknown EH_TIER=${EH_TIER}. Expected standard|premium|both|dedicated." >&2
    exit 1
    ;;
esac

if [[ "$INCLUDE_DEDICATED" == "true" ]]; then
  DEPLOY_DEDICATED="true"
fi

if [[ "$DEPLOY_DEDICATED" == "true" ]]; then
  echo "========================================================================"
  echo "[WARNING] Event Hubs Dedicated Cluster (Microsoft.EventHub/clusters)"
  echo "  - Enforces a MINIMUM 4-HOUR usage charge and deletion lock after creation."
  echo "  - Verify region availability via ARM API 2024-01-01 (do not use"
  echo "    'az eventhubs cluster available-region' which calls unsupported 2026-07-01-preview)."
  echo "========================================================================"
  if [[ "${CONFIRM_DEDICATED_4H_BILLING:-no}" != "yes" ]]; then
    echo "Refusing to provision Dedicated cluster without CONFIRM_DEDICATED_4H_BILLING=yes" >&2
    exit 2
  fi
fi

echo "[deploy] Ensuring resource group '${RESOURCE_GROUP}' in '${LOCATION}'..."
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" -o none

USER_OID="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
SUB_ID="$(az account show --query id -o tsv 2>/dev/null || true)"
if [[ -n "${USER_OID}" && -n "${SUB_ID}" ]]; then
  az role assignment create \
    --assignee-object-id "${USER_OID}" \
    --assignee-principal-type User \
    --role "Azure Event Hubs Data Owner" \
    --scope "/subscriptions/${SUB_ID}/resourceGroups/${RESOURCE_GROUP}" \
    -o none 2>/dev/null || true
fi

echo "[deploy] Deploying Bicep template (standard=${DEPLOY_STANDARD}, premium=${DEPLOY_PREMIUM}, dedicated=${DEPLOY_DEDICATED})..."
az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${SCRIPT_DIR}/main.bicep" \
  --parameters \
    location="${LOCATION}" \
    deployStandard="${DEPLOY_STANDARD}" \
    deployPremium="${DEPLOY_PREMIUM}" \
    deployDedicated="${DEPLOY_DEDICATED}" \
  --query "properties.outputs" \
  -o json
