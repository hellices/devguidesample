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

env_value() {
  # Prefer the process environment azd injects, then the azd env file.
  local name="$1" value="${!1:-}"
  if [[ -z "$value" ]]; then
    # azd prints its "key not found" error on stdout, so trust only the exit code.
    value="$(azd env get-value "$name" 2>/dev/null)" || value=""
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
  local dir="$LAB_ROOT/.azure/$(env_value AZURE_ENV_NAME)"
  mkdir -p "$dir"
  chmod 700 "$dir"
  printf '%s' "$dir"
}

evidence_dir() {
  local dir="$LAB_ROOT/evidence"
  mkdir -p "$dir"
  printf '%s' "$dir"
}

assert_active_subscription() {
  local active
  active="$(az account show --query id -o tsv)"
  [[ "$active" == "$AZURE_SUBSCRIPTION_ID" ]] || die "active Azure CLI subscription does not match AZURE_SUBSCRIPTION_ID"
}

kube() {
  kubectl --kubeconfig "$(state_dir)/kubeconfig" "$@"
}

# Runs a bash script on the gateway VM through Run Command and prints stdout.
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
