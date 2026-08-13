#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

readonly TEMPLATE_FILE="${LAB_ROOT}/infra/subscription.bicep"
readonly PARAMETER_FILE="${LAB_ROOT}/infra/subscription.bicepparam"
readonly APP_DIR="${LAB_ROOT}/app"
IMAGE_TAG="${SRE_IMAGE_TAG:-run-$(date -u +%Y%m%dT%H%M%SZ)}"
readonly IMAGE_TAG

require_commands
verify_subscription
mkdir -p "${EVIDENCE_ROOT}"

if resource_group_exists; then
  verify_lab_resource_group
fi

az deployment sub validate \
  --location "${LOCATION}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=false \
  --output none

az deployment sub create \
  --location "${LOCATION}" \
  --name "sre-agent-event-lab-base" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=false \
  --output none

ACR_NAME="$(az deployment sub show \
  --name "sre-agent-event-lab-base" \
  --query "properties.outputs.acrName.value" \
  -o tsv)"
ACR_LOGIN_SERVER="$(az deployment sub show \
  --name "sre-agent-event-lab-base" \
  --query "properties.outputs.acrLoginServer.value" \
  -o tsv)"
readonly ACR_NAME ACR_LOGIN_SERVER
readonly CONTAINER_IMAGE="${ACR_LOGIN_SERVER}/sre-event-lab:${IMAGE_TAG}"

az acr build \
  --registry "${ACR_NAME}" \
  --image "sre-event-lab:${IMAGE_TAG}" \
  "${APP_DIR}"

az deployment sub validate \
  --location "${LOCATION}" \
  --template-file "${TEMPLATE_FILE}" \
  --parameters "${PARAMETER_FILE}" \
  --parameters deployContainerApp=true containerImage="${CONTAINER_IMAGE}" \
  --output none

az deployment sub create \
  --location "${LOCATION}" \
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

az deployment sub show \
  --name "${FINAL_DEPLOYMENT_NAME}" \
  --query properties.outputs \
  -o json
