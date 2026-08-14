#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
readonly EVIDENCE_ROOT="${LAB_ROOT}/evidence"
readonly AGENT_SETUP_FILE="${EVIDENCE_ROOT}/agent-setup.json"

require_commands() {
  local command_name
  for command_name in az azd jq curl python3; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
      echo "Required command not found: ${command_name}" >&2
      return 1
    fi
  done
}

# azd_value NAME -- the current azd environment's value for NAME, or empty
# when azd has no such value (e.g. before the environment was provisioned).
# Never fails the caller: a missing value is not this function's error to
# report, `setting`/`require_setting` decide what to do about it.
azd_value() {
  local name="$1"
  azd env get-value "${name}" 2>/dev/null || true
}

# setting NAME EXPLICIT_VALUE [DEFAULT]
# Resolves a configuration value in this order: EXPLICIT_VALUE (the caller's
# already-expanded process environment, e.g. "${AZURE_LOCATION:-}") > the
# current azd environment's value for NAME > DEFAULT. Every call site passes
# an explicit, already-expanded value -- there is no dynamic re-execution or
# indirect variable-name expansion here, only plain parameters.
setting() {
  local name="$1"
  local explicit_value="$2"
  local default_value="${3:-}"
  if [[ -n "${explicit_value}" ]]; then
    printf '%s\n' "${explicit_value}"
    return
  fi
  local stored_value
  stored_value="$(azd_value "${name}")"
  printf '%s\n' "${stored_value:-${default_value}}"
}

# require_setting NAME EXPLICIT_VALUE [DEFAULT] -- like `setting`, but fails
# with an actionable message (the exact `azd env set` command to run) when
# nothing resolves instead of silently returning an empty string.
require_setting() {
  local name="$1"
  local explicit_value="$2"
  local default_value="${3:-}"
  local resolved
  resolved="$(setting "${name}" "${explicit_value}" "${default_value}")"
  if [[ -z "${resolved}" ]]; then
    echo "Missing required setting ${name}." >&2
    echo "Run: azd env set ${name} <value>" >&2
    return 1
  fi
  printf '%s\n' "${resolved}"
}

# load_lab_config -- resolves every azd-backed setting the lab scripts read
# (explicit process environment > current `azd env get-value` > an allowed
# default) and makes the resolved, non-secret values readonly. Every
# scenario/query/capture/cleanup script must call this before reading
# SUBSCRIPTION_ID, RESOURCE_GROUP, or any deployment_output() value.
load_lab_config() {
  SUBSCRIPTION_ID="$(require_setting AZURE_SUBSCRIPTION_ID "${AZURE_SUBSCRIPTION_ID:-}")" || return 1
  RESOURCE_GROUP="$(require_setting AZURE_RESOURCE_GROUP "${AZURE_RESOURCE_GROUP:-}")" || return 1
  AZURE_ENV_NAME="$(require_setting AZURE_ENV_NAME "${AZURE_ENV_NAME:-}")" || return 1
  LOCATION="$(setting AZURE_LOCATION "${AZURE_LOCATION:-}" "koreacentral")"
  readonly SUBSCRIPTION_ID RESOURCE_GROUP AZURE_ENV_NAME LOCATION

  # Deployment outputs read by deployment_output(). Every azd environment
  # sets these once `azd up`/`azd provision` has run; empty until then.
  AZURE_CONTAINER_APP_NAME="$(setting AZURE_CONTAINER_APP_NAME "${AZURE_CONTAINER_APP_NAME:-}" "")"
  AZURE_CONTAINER_APP_FQDN="$(setting AZURE_CONTAINER_APP_FQDN "${AZURE_CONTAINER_APP_FQDN:-}" "")"
  AZURE_STORAGE_CONTAINER_SCOPE="$(setting AZURE_STORAGE_CONTAINER_SCOPE "${AZURE_STORAGE_CONTAINER_SCOPE:-}" "")"
  AZURE_BLOB_ROLE_ASSIGNMENT_NAME="$(setting AZURE_BLOB_ROLE_ASSIGNMENT_NAME "${AZURE_BLOB_ROLE_ASSIGNMENT_NAME:-}" "")"
  AZURE_WORKSPACE_ID="$(setting AZURE_WORKSPACE_ID "${AZURE_WORKSPACE_ID:-}" "")"
  AZURE_APP_INSIGHTS_NAME="$(setting AZURE_APP_INSIGHTS_NAME "${AZURE_APP_INSIGHTS_NAME:-}" "")"
  AZURE_TELEMETRY_SERVICE_NAME="$(setting AZURE_TELEMETRY_SERVICE_NAME "${AZURE_TELEMETRY_SERVICE_NAME:-}" "")"
  # Deployment outputs without an AZURE_-prefixed duplicate (see
  # infra/main.bicep): read straight from their own azd output name.
  CONTAINER_APP_PRINCIPAL_ID="$(setting containerAppPrincipalId "${CONTAINER_APP_PRINCIPAL_ID:-}" "")"
  WORKSPACE_CUSTOMER_ID="$(setting workspaceCustomerId "${WORKSPACE_CUSTOMER_ID:-}" "")"
  readonly AZURE_CONTAINER_APP_NAME AZURE_CONTAINER_APP_FQDN AZURE_STORAGE_CONTAINER_SCOPE
  readonly AZURE_BLOB_ROLE_ASSIGNMENT_NAME AZURE_WORKSPACE_ID AZURE_APP_INSIGHTS_NAME
  readonly AZURE_TELEMETRY_SERVICE_NAME CONTAINER_APP_PRINCIPAL_ID WORKSPACE_CUSTOMER_ID

  # Azure SRE Agent settings (.env.example documents these). None of the
  # current scripts read them yet, but they resolve through the same
  # explicit-env > azd-env > default rule so nothing here is ever fixed.
  SRE_LAB_EXPIRES_ON="$(setting SRE_LAB_EXPIRES_ON "${SRE_LAB_EXPIRES_ON:-}" "")"
  SRE_AGENT_RESOURCE_ID="$(setting SRE_AGENT_RESOURCE_ID "${SRE_AGENT_RESOURCE_ID:-}" "")"
  SRE_AGENT_NAME="$(setting SRE_AGENT_NAME "${SRE_AGENT_NAME:-}" "")"
  SRE_REPOSITORY_URL="$(setting SRE_REPOSITORY_URL "${SRE_REPOSITORY_URL:-}" "")"
  SRE_REPOSITORY_BRANCH="$(setting SRE_REPOSITORY_BRANCH "${SRE_REPOSITORY_BRANCH:-}" "main")"
  SRE_KNOWLEDGE_PATH="$(setting SRE_KNOWLEDGE_PATH "${SRE_KNOWLEDGE_PATH:-}" "runbooks/incident-response.md")"
  readonly SRE_LAB_EXPIRES_ON SRE_AGENT_RESOURCE_ID SRE_AGENT_NAME
  readonly SRE_REPOSITORY_URL SRE_REPOSITORY_BRANCH SRE_KNOWLEDGE_PATH
}

# require_lab_config -- the one-call preflight for scenario/query/capture/
# cleanup scripts: verifies the required CLIs are on PATH, then resolves the
# lab configuration via load_lab_config.
require_lab_config() {
  require_commands
  load_lab_config
}

verify_subscription() {
  local current_subscription
  current_subscription="$(az account show --query id -o tsv)"
  if [[ "${current_subscription}" != "${SUBSCRIPTION_ID}" ]]; then
    echo "Refusing to continue in subscription ${current_subscription}." >&2
    echo "Expected ${SUBSCRIPTION_ID}." >&2
    return 1
  fi
}

resource_group_exists() {
  [[ "$(az group exists --name "${RESOURCE_GROUP}" -o tsv)" == "true" ]]
}

verify_lab_resource_group() {
  if ! resource_group_exists; then
    echo "Lab resource group does not exist: ${RESOURCE_GROUP}" >&2
    return 1
  fi

  local purpose tagged_env_name
  purpose="$(az group show --name "${RESOURCE_GROUP}" --query "tags.purpose" -o tsv)"
  tagged_env_name="$(az group show --name "${RESOURCE_GROUP}" --query 'tags."azd-env-name"' -o tsv)"
  if [[ "${purpose}" != "sre-agent-event-lab" || "${tagged_env_name}" != "${AZURE_ENV_NAME}" ]]; then
    echo "Refusing to operate on untagged resource group ${RESOURCE_GROUP}." >&2
    return 1
  fi
}

# deployment_output NAME -- returns an azd deployment output already
# resolved by load_lab_config. Callers must call load_lab_config first.
deployment_output() {
  local output_name="$1"
  case "${output_name}" in
    containerAppName) printf '%s\n' "${AZURE_CONTAINER_APP_NAME}" ;;
    containerAppFqdn) printf '%s\n' "${AZURE_CONTAINER_APP_FQDN}" ;;
    containerAppPrincipalId) printf '%s\n' "${CONTAINER_APP_PRINCIPAL_ID}" ;;
    storageContainerScope) printf '%s\n' "${AZURE_STORAGE_CONTAINER_SCOPE}" ;;
    blobRoleAssignmentName) printf '%s\n' "${AZURE_BLOB_ROLE_ASSIGNMENT_NAME}" ;;
    workspaceId) printf '%s\n' "${AZURE_WORKSPACE_ID}" ;;
    workspaceCustomerId) printf '%s\n' "${WORKSPACE_CUSTOMER_ID}" ;;
    appInsightsName) printf '%s\n' "${AZURE_APP_INSIGHTS_NAME}" ;;
    telemetryServiceName) printf '%s\n' "${AZURE_TELEMETRY_SERVICE_NAME}" ;;
    *) echo "Unknown deployment output: ${output_name}" >&2; return 2 ;;
  esac
}

create_evidence_dir() {
  local scenario="$1"
  local timestamp
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local directory="${EVIDENCE_ROOT}/${scenario}-${timestamp}"
  mkdir -p "${directory}"
  printf '%s\n' "${directory}"
}

utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

wait_for_app_ready() {
  local app_name="$1"
  local timeout_seconds="${2:-600}"
  local started="${SECONDS}"

  while (( SECONDS - started < timeout_seconds )); do
    local state
    state="$(az containerapp revision list \
      --resource-group "${RESOURCE_GROUP}" \
      --name "${app_name}" \
      --query "[?properties.active].properties.healthState | [0]" \
      -o tsv 2>/dev/null || true)"
    if [[ "${state}" == "Healthy" ]]; then
      return 0
    fi
    sleep 10
  done

  echo "Container App did not become healthy within ${timeout_seconds}s." >&2
  return 1
}

latest_revision_name() {
  local app_name="$1"
  az containerapp show \
    --resource-group "${RESOURCE_GROUP}" \
    --name "${app_name}" \
    --query properties.latestRevisionName \
    -o tsv
}

wait_for_new_revision_ready() {
  local app_name="$1"
  local previous_revision="$2"
  local timeout_seconds="${3:-600}"
  local started="${SECONDS}"

  while (( SECONDS - started < timeout_seconds )); do
    local latest_revision
    latest_revision="$(latest_revision_name "${app_name}")"
    if [[ -n "${latest_revision}" && "${latest_revision}" != "${previous_revision}" ]]; then
      local health active
      health="$(az containerapp revision list \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${app_name}" \
        --query "[?name=='${latest_revision}'].properties.healthState | [0]" \
        -o tsv 2>/dev/null || true)"
      active="$(az containerapp revision list \
        --resource-group "${RESOURCE_GROUP}" \
        --name "${app_name}" \
        --query "[?name=='${latest_revision}'].properties.active | [0]" \
        -o tsv 2>/dev/null || true)"
      if [[ "${health}" == "Healthy" && "${active}" == "true" ]]; then
        printf '%s\n' "${latest_revision}"
        return 0
      fi
    fi
    sleep 10
  done

  echo "A new healthy revision did not become active within ${timeout_seconds}s." >&2
  return 1
}
