#!/usr/bin/env bash
# Shared helpers. Reads values written by scripts/deploy.sh.
SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="$SAMPLE_DIR/.lab-state.json"

[[ -f "$STATE_FILE" ]] || { echo "missing $STATE_FILE; run scripts/deploy.sh first" >&2; exit 1; }

state() { jq -r --arg k "$1" '.[$k]' "$STATE_FILE"; }

RG="$(state resourceGroup)"
VM_NAME="$(state vmName)"
VM_ID="$(state vmId)"
KEY_VAULT_ID="$(state keyVaultId)"
SQL_LOGIN="$(state sqlLogin)"
SECRET_NAME="$(state secretName)"
AGENT_NAME="$(state agentName)"
AGENT_ID="$(state agentId)"
AGENT_CLIENT_ID="$(state agentIdentityClientId)"
VM_METRICS_CLIENT_ID="$(state vmMetricsClientId)"
VM_METRICS_PRINCIPAL_ID="$(state vmMetricsPrincipalId)"
MONITOR_WORKSPACE_ID="$(state monitorWorkspaceId)"
GRAFANA_NAME="$(state grafanaName)"

# Runs a managed Run Command synchronously, prints its result, deletes it, and
# exits on failure. Any leftover command with the same name is deleted first,
# so a failed create can never report the result of an earlier run.
# Usage: run_on_vm <name> <script> <timeout-seconds> [extra az vm run-command create args]
run_on_vm() {
  local name="$1" script="$2" timeout="$3"; shift 3
  az vm run-command delete -g "$RG" --vm-name "$VM_NAME" --name "$name" --yes -o none 2>/dev/null || true
  # A script failure also makes create return non-zero; the result is read below.
  az vm run-command create -g "$RG" --vm-name "$VM_NAME" --name "$name" --script @"$script" \
    --timeout-in-seconds "$timeout" --async-execution false -o none "$@" || true
  local view
  view="$(az vm run-command show -g "$RG" --vm-name "$VM_NAME" --name "$name" --instance-view \
    --query "instanceView.{state:executionState, exitCode:exitCode, output:output, error:error}" -o json)"
  echo "$view"
  az vm run-command delete -g "$RG" --vm-name "$VM_NAME" --name "$name" --yes -o none
  [[ "$(jq -r .exitCode <<<"$view")" == "0" ]] || { echo "${name} failed" >&2; exit 1; }
}
