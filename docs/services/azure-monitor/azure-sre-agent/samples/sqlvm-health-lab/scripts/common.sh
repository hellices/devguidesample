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
