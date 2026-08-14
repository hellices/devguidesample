#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
readonly APP_DIR="${LAB_ROOT}/app"

for command_name in az azd jq curl; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "Required command not found: ${command_name}" >&2
    exit 1
  }
done

: "${AZURE_RESOURCE_GROUP:?AZURE_RESOURCE_GROUP must be set by azd before running this hook}"
: "${AZURE_ACR_NAME:?AZURE_ACR_NAME must be set by azd before running this hook}"
: "${AZURE_CONTAINER_APP_NAME:?AZURE_CONTAINER_APP_NAME must be set by azd before running this hook}"
: "${AZURE_CONTAINER_APP_FQDN:?AZURE_CONTAINER_APP_FQDN must be set by azd before running this hook}"

IMAGE_TAG="run-$(date -u +%Y%m%dT%H%M%SZ)"
readonly IMAGE_TAG

az acr build \
  --registry "${AZURE_ACR_NAME}" \
  --image "sre-event-lab:${IMAGE_TAG}" \
  "${APP_DIR}"

ACR_LOGIN_SERVER="$(az acr show \
  --name "${AZURE_ACR_NAME}" \
  --query loginServer \
  -o tsv)"
readonly ACR_LOGIN_SERVER
readonly CONTAINER_IMAGE="${ACR_LOGIN_SERVER}/sre-event-lab:${IMAGE_TAG}"

PREVIOUS_REVISION="$(az containerapp show \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --query properties.latestRevisionName \
  -o tsv)"
readonly PREVIOUS_REVISION

az containerapp update \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${AZURE_CONTAINER_APP_NAME}" \
  --image "${CONTAINER_IMAGE}" \
  --output none

wait_for_new_revision_ready() {
  local timeout_seconds="${1:-600}"
  local started="${SECONDS}"

  while (( SECONDS - started < timeout_seconds )); do
    local latest_revision
    latest_revision="$(az containerapp show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${AZURE_CONTAINER_APP_NAME}" \
      --query properties.latestRevisionName \
      -o tsv)"
    if [[ -n "${latest_revision}" && "${latest_revision}" != "${PREVIOUS_REVISION}" ]]; then
      local health active
      health="$(az containerapp revision list \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --name "${AZURE_CONTAINER_APP_NAME}" \
        --query "[?name=='${latest_revision}'].properties.healthState | [0]" \
        -o tsv 2>/dev/null || true)"
      active="$(az containerapp revision list \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --name "${AZURE_CONTAINER_APP_NAME}" \
        --query "[?name=='${latest_revision}'].properties.active | [0]" \
        -o tsv 2>/dev/null || true)"
      if [[ "${health}" == "Healthy" && "${active}" == "true" ]]; then
        return 0
      fi
    fi
    sleep 10
  done

  echo "A new healthy revision did not become active within ${timeout_seconds}s." >&2
  return 1
}

wait_for_new_revision_ready 600

started="${SECONDS}"
until curl --fail --silent --show-error "https://${AZURE_CONTAINER_APP_FQDN}/healthz" >/dev/null; do
  if (( SECONDS - started >= 600 )); then
    echo "Health endpoint did not return HTTP 200 within 600s." >&2
    exit 1
  fi
  sleep 10
done

azd env set SRE_IMAGE_TAG "${IMAGE_TAG}"
