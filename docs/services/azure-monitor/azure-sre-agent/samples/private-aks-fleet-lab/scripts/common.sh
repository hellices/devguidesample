#!/usr/bin/env bash
set -euo pipefail

SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_FILE="${SAMPLE_DIR}/.lab-state.json"

if [[ -f "$STATE_FILE" ]]; then
  RESOURCE_GROUP="$(jq -r '.resourceGroup // "rg-private-aks-fleet"' "$STATE_FILE")"
  AGENT_ID="$(jq -r '.agentId // empty' "$STATE_FILE")"
  AGENT_NAME="$(jq -r '.agentName // empty' "$STATE_FILE")"
else
  RESOURCE_GROUP="${RESOURCE_GROUP:-rg-private-aks-fleet}"
  AGENT_ID="${AGENT_ID:-}"
  AGENT_NAME="${AGENT_NAME:-}"
fi
