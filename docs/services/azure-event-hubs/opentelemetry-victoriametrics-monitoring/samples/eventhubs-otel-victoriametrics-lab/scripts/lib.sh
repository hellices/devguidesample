# Shared helpers for azd hooks. Source from bash only.
set -euo pipefail

LAB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LAB_ROOT

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_commands() {
  local command
  for command in "$@"; do
    command -v "$command" >/dev/null 2>&1 || die "missing command: $command"
  done
}

# Pin azd env reads and writes to the environment azd is running the hook for (azd up -e <env>).
azd_env() {
  local subcommand="$1"
  shift
  if [[ -n "${AZURE_ENV_NAME:-}" ]]; then
    azd env "$subcommand" -e "$AZURE_ENV_NAME" "$@"
  else
    azd env "$subcommand" "$@"
  fi
}

env_value() {
  # Prefer the process environment azd injects, then the azd env file.
  local name="$1" value="${!1:-}"
  if [[ -z "$value" ]]; then
    # azd prints its "key not found" error on stdout, so trust only the exit code.
    value="$(azd_env get-value "$name" 2>/dev/null)" || value=""
  fi
  printf '%s' "$value"
}

load_env() {
  local name
  for name in "$@"; do
    local value
    value="$(env_value "$name")"
    [[ -n "$value" ]] || die "azd environment value is empty: $name"
    export "$name=$value"
  done
}

state_dir() {
  local dir="${LAB_STATE_ROOT:-$LAB_ROOT/.azure}/$(env_value AZURE_ENV_NAME)"
  # Called inside $(...), where errexit does not apply: fail explicitly before printing a path.
  mkdir -p "$dir" || return 1
  chmod 700 "$dir" || return 1
  printf '%s' "$dir"
}

# Each azd environment gets its own default local port, so a port-forward left open for one
# environment is never mistaken for another environment's VMSingle.
vm_local_port() {
  if [[ -n "${VM_LOCAL_PORT:-}" ]]; then
    printf '%s' "$VM_LOCAL_PORT"
    return
  fi
  local checksum
  checksum="$(printf '%s' "$(env_value AZURE_ENV_NAME)" | cksum | cut -d' ' -f1)"
  printf '%s' "$(( 18428 + checksum % 500 ))"
}

evidence_dir() {
  # Per environment, so one environment's scenario window is never reused for another.
  local dir="${LAB_EVIDENCE_ROOT:-$LAB_ROOT/evidence}/$(env_value AZURE_ENV_NAME)"
  mkdir -p "$dir" || return 1
  printf '%s' "$dir"
}

assert_active_subscription() {
  local active
  active="$(az account show --query id -o tsv)"
  [[ "$active" == "$AZURE_SUBSCRIPTION_ID" ]] || die "active Azure CLI subscription does not match AZURE_SUBSCRIPTION_ID"
}

# The cluster this lab created (EVENTHUBS_SKU=Dedicated) wins over an existing one to observe.
dedicated_cluster_id() {
  local created
  created="$(env_value DEDICATED_CLUSTER_RESOURCE_ID)"
  printf '%s' "${created:-$(env_value EXISTING_DEDICATED_CLUSTER_RESOURCE_ID)}"
}

kube() {
  # A separate assignment, so a state directory that could not be prepared stops kubectl.
  local dir
  dir="$(state_dir)" || die "could not prepare the lab state directory"
  kubectl --kubeconfig "$dir/kubeconfig" "$@"
}

# Runs a bash script on the gateway VM through Run Command and prints the Run Command message,
# which holds both the [stdout] and [stderr] sections. Callers read only explicit markers from
# it (GATEWAY_READY, GRAFANA_CERT_BEGIN/END), never the whole message as data.
# No inbound SSH is opened; the script and its parameters travel through the ARM control plane.
gateway_run() {
  local script_file="$1"
  shift
  local args=(
    --subscription "$AZURE_SUBSCRIPTION_ID"
    --resource-group "$AZURE_RESOURCE_GROUP"
    --name "$GATEWAY_VM_NAME"
    --command-id RunShellScript
    --scripts "@$script_file"
    --query 'value[0].message' -o tsv
  )
  [[ $# -gt 0 ]] && args+=(--parameters "$@")
  az vm run-command invoke "${args[@]}"
}
