#!/usr/bin/env bash
# Registers the SqlServerHealthCheck Python tool and the health-check skill on
# the SRE Agent through its data-plane API.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ENDPOINT="$(az rest --method get --url "https://management.azure.com${AGENT_ID}?api-version=2025-05-01-preview" \
  --query properties.agentEndpoint -o tsv)"
TOKEN="$(az account get-access-token --resource https://azuresre.dev --query accessToken -o tsv)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

dataplane() {
  local method="$1" path="$2" content_type="$3" body_file="$4" code
  code="$(curl -sS -o "$TMP/response" -w '%{http_code}' -X "$method" "${ENDPOINT}${path}" \
    -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: ${content_type}" --data-binary @"$body_file")"
  if [[ ! "$code" =~ ^2 ]]; then
    echo "FAILED ${method} ${path} -> HTTP ${code}" >&2
    head -c 1000 "$TMP/response" >&2; echo >&2
    return 1
  fi
  echo "ok ${method} ${path} (HTTP ${code})"
}

python3 "$SAMPLE_DIR/scripts/render_agent_config.py" tool "$STATE_FILE" > "$TMP/tool.json"
python3 "$SAMPLE_DIR/scripts/render_agent_config.py" skill "$STATE_FILE" > "$TMP/skill.json"

echo "==> Applying agent configuration to ${AGENT_NAME} (${ENDPOINT})"
# The runtime apply endpoint accepts a YAML ToolList; JSON is valid YAML.
dataplane PUT /api/v1/extendedAgent/apply application/x-yaml "$TMP/tool.json"
dataplane PUT /api/v2/extendedAgent/skills/sql-server-vm-health-check application/json "$TMP/skill.json"
