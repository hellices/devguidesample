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
#
# azd reports failure only through its exit status: azd 1.29 answers an
# unknown key -- or a working directory outside the project -- with an
# `ERROR: ...` sentence on *stdout* and exit 1. Keeping stdout regardless of
# the exit status would adopt that sentence as a configuration value, so the
# output is used only when the lookup succeeded. `--cwd` pins the lookup to
# this lab's azd project (the directory holding azure.yaml) so the scripts
# work when they are invoked from the repository root or any other cwd.
# Never fails the caller: a missing value is not this function's error to
# report, `setting`/`require_setting` decide what to do about it.
azd_value() {
  local name="$1"
  local stored_value
  if ! stored_value="$(azd env get-value "${name}" --cwd "${LAB_ROOT}" 2>/dev/null)"; then
    return 0
  fi
  printf '%s\n' "${stored_value}"
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
  # Set by the deploy phase (`postdeploy` hook, scripts/azd-deploy-app.sh)
  # once it has built the lab image and switched the Container App onto it;
  # empty until then, which is the reliable "has azd deploy run yet?" signal
  # doctor.sh needs to tell the intermediate placeholder state (expected)
  # apart from a real post-deploy health regression (not expected).
  SRE_CONTAINER_IMAGE="$(setting SRE_CONTAINER_IMAGE "${SRE_CONTAINER_IMAGE:-}" "")"
  # Deployment outputs without an AZURE_-prefixed duplicate (see
  # infra/main.bicep): read straight from their own azd output name. They
  # are stored under LAB_-prefixed names because `load_lab_config` makes
  # every resolved value readonly for the rest of the process, and the
  # calling scripts already use the unprefixed names for their own
  # variables -- an assignment to a readonly name aborts the caller under
  # `set -e` before it reaches its first Azure call.
  LAB_CONTAINER_APP_PRINCIPAL_ID="$(setting containerAppPrincipalId "${CONTAINER_APP_PRINCIPAL_ID:-}" "")"
  LAB_WORKSPACE_CUSTOMER_ID="$(setting workspaceCustomerId "${WORKSPACE_CUSTOMER_ID:-}" "")"
  readonly AZURE_CONTAINER_APP_NAME AZURE_CONTAINER_APP_FQDN AZURE_STORAGE_CONTAINER_SCOPE
  readonly AZURE_BLOB_ROLE_ASSIGNMENT_NAME AZURE_WORKSPACE_ID AZURE_APP_INSIGHTS_NAME
  readonly AZURE_TELEMETRY_SERVICE_NAME LAB_CONTAINER_APP_PRINCIPAL_ID LAB_WORKSPACE_CUSTOMER_ID
  readonly SRE_CONTAINER_IMAGE

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

# The `log-analytics` Azure CLI extension provides
# `az monitor log-analytics query`; it is not part of the core CLI.
readonly LOG_ANALYTICS_EXTENSION_NAME="log-analytics"

# log_analytics_extension_installed -- true when the extension that provides
# `az monitor log-analytics query` is installed. `az extension show --name`
# is the stable read for this: exit 0 when installed, exit 1 with
# "ERROR: The extension ... is not installed" otherwise.
log_analytics_extension_installed() {
  az extension show --name "${LOG_ANALYTICS_EXTENSION_NAME}" -o none >/dev/null 2>&1
}

# log_analytics_row_count WORKSPACE TIMESPAN QUERY -- how many rows QUERY
# returned, or 0 when the CLI call or the parse failed. Never fails the
# caller: an ingestion-lag miss mid-poll is an expected answer, not an error
# to report.
#
# Output contract (verified against azure-cli 2.86.0 with the log-analytics
# 1.0.0b1 extension): `az monitor log-analytics query -o json` does **not**
# print the REST envelope `{"tables": [...]}`. The extension's own `_output`
# transform flattens every table into a single JSON array holding one object
# per row -- `TableName` plus one stringified value per column -- so an empty
# result set prints exactly `[]`. Parsing `.tables[0].rows` against that
# always yields nothing, which reads as "no telemetry" forever.
#
# Row *presence* is therefore the reliable "is there data?" signal, and only
# for a query that returns one row per matching record: KQL's `count`
# operator always returns exactly one row (`Count: 0` when nothing matched),
# so counting the rows of a `| count` result answers 1 either way. Callers
# pass a projecting query bounded with `take`, never `| count`.
log_analytics_row_count() {
  local workspace="$1"
  local timespan="$2"
  local query="$3"
  local output rows
  if ! output="$(az monitor log-analytics query \
    --workspace "${workspace}" \
    --analytics-query "${query}" \
    --timespan "${timespan}" \
    -o json 2>/dev/null)"; then
    printf '0\n'
    return 0
  fi
  if ! rows="$(jq 'if type == "array" then length else 0 end' <<<"${output:-[]}" 2>/dev/null)"; then
    printf '0\n'
    return 0
  fi
  printf '%s\n' "${rows:-0}"
}

# azd_auth_status -- azd's own word for the current login state: `success`,
# `unauthenticated`, or empty when this azd could not report one.
#
# `azd auth login --check-status` is the only non-interactive login read azd
# offers, and it deliberately "always return[s] a zero exit code"
# (cli/azd/cmd/auth_login.go), printing the answer instead. Reading its exit
# status would report every signed-out operator as signed in, so the
# machine-readable `--output json` status field is parsed instead of the
# human sentence it prints without that flag.
azd_auth_status() {
  local status
  status="$(azd auth login --check-status --output json --cwd "${LAB_ROOT}" 2>/dev/null |
    jq -r '.status // empty' 2>/dev/null)" || true
  printf '%s\n' "${status:-}"
}

# deployment_output NAME -- returns an azd deployment output already
# resolved by load_lab_config. Callers must call load_lab_config first.
deployment_output() {
  local output_name="$1"
  case "${output_name}" in
    containerAppName) printf '%s\n' "${AZURE_CONTAINER_APP_NAME}" ;;
    containerAppFqdn) printf '%s\n' "${AZURE_CONTAINER_APP_FQDN}" ;;
    containerAppPrincipalId) printf '%s\n' "${LAB_CONTAINER_APP_PRINCIPAL_ID}" ;;
    storageContainerScope) printf '%s\n' "${AZURE_STORAGE_CONTAINER_SCOPE}" ;;
    blobRoleAssignmentName) printf '%s\n' "${AZURE_BLOB_ROLE_ASSIGNMENT_NAME}" ;;
    workspaceId) printf '%s\n' "${AZURE_WORKSPACE_ID}" ;;
    workspaceCustomerId) printf '%s\n' "${LAB_WORKSPACE_CUSTOMER_ID}" ;;
    appInsightsName) printf '%s\n' "${AZURE_APP_INSIGHTS_NAME}" ;;
    telemetryServiceName) printf '%s\n' "${AZURE_TELEMETRY_SERVICE_NAME}" ;;
    *) echo "Unknown deployment output: ${output_name}" >&2; return 2 ;;
  esac
}

# evidence_dir_path SCENARIO -- the name of this attempt's evidence
# directory, without creating anything.
#
# A run has to register its evidence path with `lab_state.py begin-run`
# *before* it starts, so the path has to exist as a string first. Creating
# the directory at that point left an empty `<scenario>-<timestamp>/`
# behind every time the run was then refused -- litter that reads exactly
# like an attempt that ran and produced nothing. Naming and creating are
# therefore separate steps, and the caller creates only once its run was
# admitted.
evidence_dir_path() {
  local scenario="$1"
  local timestamp
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  printf '%s\n' "${EVIDENCE_ROOT}/${scenario}-${timestamp}"
}

# create_evidence_dir SCENARIO -- name it and create it in one step, for
# callers that write into it immediately and have nothing left to refuse
# them (`baseline.sh`).
create_evidence_dir() {
  local directory
  directory="$(evidence_dir_path "$1")"
  mkdir -p "${directory}"
  printf '%s\n' "${directory}"
}

# lab_python -- the interpreter the lab's own Python helpers run under: the
# app virtualenv when it exists (the capture pipeline needs its packages),
# otherwise the system python3. `lab_state.py` and `score.py` import
# nothing outside the standard library, so either interpreter runs them.
lab_python() {
  local venv_python="${LAB_ROOT}/app/.venv/bin/python"
  if [[ -x "${venv_python}" ]]; then
    printf '%s\n' "${venv_python}"
  else
    printf '%s\n' "python3"
  fi
}

# lab_tool SCRIPT [ARGS...] -- runs one of the lab's Python helpers with the
# configuration `load_lab_config` resolved passed through the process
# environment. Nothing in Python re-resolves the lab's identity: the caller
# has already verified the subscription and the resource-group tags, and
# passing the verified values on is what lets `lab_state.py` refuse a state
# file that belongs to a different environment.
lab_tool() {
  local script_name="$1"
  shift
  env \
    AZURE_ENV_NAME="${AZURE_ENV_NAME}" \
    AZURE_SUBSCRIPTION_ID="${SUBSCRIPTION_ID}" \
    AZURE_RESOURCE_GROUP="${RESOURCE_GROUP}" \
    SRE_AGENT_NAME="${SRE_AGENT_NAME}" \
    SRE_AGENT_RESOURCE_ID="${SRE_AGENT_RESOURCE_ID}" \
    SRE_REPOSITORY_URL="${SRE_REPOSITORY_URL}" \
    SRE_REPOSITORY_BRANCH="${SRE_REPOSITORY_BRANCH}" \
    SRE_KNOWLEDGE_PATH="${SRE_KNOWLEDGE_PATH}" \
    "$(lab_python)" "${SCRIPT_DIR}/${script_name}" "$@"
}

# lab_state COMMAND [ARGS...] -- the lab's ordered-run state (see
# lab_state.py). Requires load_lab_config to have run.
lab_state() {
  lab_tool lab_state.py --state "${EVIDENCE_ROOT}/state.json" "$@"
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
  local interval_seconds="${4:-10}"
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
    sleep "${interval_seconds}"
  done

  echo "A new healthy revision did not become active within ${timeout_seconds}s." >&2
  return 1
}

# alert_monitor_condition ALERT_ID -- Azure Monitor's own word for the
# alert's current state: `Fired`, `Resolved`, or empty when the read failed.
# ALERT_ID is the alert's full ARM resource ID, exactly as
# `run-scenario.sh` recorded it from the Alerts Management list.
alert_monitor_condition() {
  local alert_id="$1"
  az rest \
    --method get \
    --url "https://management.azure.com${alert_id}?api-version=2019-03-01" 2>/dev/null |
    jq -r '.properties.essentials.monitorCondition // empty' 2>/dev/null || true
}

# wait_for_alert_resolved ALERT_ID [TIMEOUT] [INTERVAL] -- waits until Azure
# Monitor reports the fired alert as `Resolved` and prints the UTC moment
# that was observed. Fails (without printing a moment) when the alert is
# still firing at the deadline.
#
# This is the only external confirmation that the injected failure is really
# gone: the recovery command returning 0 proves the *change* was applied,
# not that the signal it broke recovered. A run that recorded a recovery
# here on a still-firing alert would let the next scenario start on top of
# an open incident, and both incidents' evidence would be unreadable.
wait_for_alert_resolved() {
  local alert_id="$1"
  local timeout_seconds="${2:-900}"
  local interval_seconds="${3:-20}"
  local deadline=$(( SECONDS + timeout_seconds ))
  local condition=""

  while :; do
    condition="$(alert_monitor_condition "${alert_id}")"
    if [[ "${condition}" == "Resolved" ]]; then
      utc_now
      return 0
    fi
    if (( SECONDS + interval_seconds > deadline )); then
      break
    fi
    sleep "${interval_seconds}"
  done

  echo "Alert ${alert_id} was not Resolved within ${timeout_seconds}s (last condition: ${condition:-unknown})." >&2
  return 1
}
