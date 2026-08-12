#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

readonly TEMPLATE_FILE="${LAB_ROOT}/infra/main.bicep"
readonly PARAMETER_FILE="${LAB_ROOT}/infra/main.bicepparam"
readonly APP_DIR="${LAB_ROOT}/app"
readonly IMAGE_TAG="20260812.1"

require_commands
verify_subscription
mkdir -p "${EVIDENCE_ROOT}"

if resource_group_exists; then
  verify_lab_resource_group
else
  az group create \
    --name "${RESOURCE_GROUP}" \
    --location "${LOCATION}" \
    --tags purpose=sre-agent-event-lab expiresOn=2026-08-13 \
    --output none
fi

az deployment group validate \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=false \
  --output none

az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "sre-agent-event-lab-base" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=false \
  --output none

ACR_NAME="$(az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "sre-agent-event-lab-base" \
  --query "properties.outputs.acrName.value" \
  -o tsv)"
ACR_LOGIN_SERVER="$(az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "sre-agent-event-lab-base" \
  --query "properties.outputs.acrLoginServer.value" \
  -o tsv)"
readonly ACR_NAME ACR_LOGIN_SERVER
readonly CONTAINER_IMAGE="${ACR_LOGIN_SERVER}/sre-event-lab:${IMAGE_TAG}"

az acr build \
  --registry "${ACR_NAME}" \
  --image "sre-event-lab:${IMAGE_TAG}" \
  "${APP_DIR}"

az deployment group validate \
  --resource-group "${RESOURCE_GROUP}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=true containerImage="${CONTAINER_IMAGE}" \
  --output none

az deployment group create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${FINAL_DEPLOYMENT_NAME}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=true containerImage="${CONTAINER_IMAGE}" \
  --output none

APP_NAME="$(deployment_output containerAppName)"
APP_FQDN="$(deployment_output containerAppFqdn)"
readonly APP_NAME APP_FQDN

wait_for_app_ready "${APP_NAME}" 600

started="${SECONDS}"
until curl --fail --silent --show-error "https://${APP_FQDN}/healthz" >/dev/null; do
  if (( SECONDS - started >= 600 )); then
    echo "Health endpoint did not return HTTP 200 within 600s." >&2
    exit 1
  fi
  sleep 10
done

az deployment group show \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${FINAL_DEPLOYMENT_NAME}" \
  --query properties.outputs \
  -o json
