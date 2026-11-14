#!/usr/bin/env bash
# Registers the compact Python tools, skill, safety hook, and fast-execution
# instructions on the Azure SRE Agent through its data-plane API.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -z "${AGENT_ID:-}" ]]; then
  echo "AGENT_ID is required (set in .lab-state.json or environment)." >&2
  exit 1
fi

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

python3 "$SAMPLE_DIR/scripts/render_agent_config.py" tools > "$TMP/tools.json"
python3 "$SAMPLE_DIR/scripts/render_agent_config.py" skill > "$TMP/skill.json"
python3 "$SAMPLE_DIR/scripts/render_agent_config.py" instructions > "$TMP/instructions.json"
python3 "$SAMPLE_DIR/scripts/render_agent_config.py" hook > "$TMP/hook.json"

echo "==> Applying fast-execution configuration to ${AGENT_NAME:-agent} (${ENDPOINT})"
for TNAME in evaluate-aks-upgrade-preflight verify-multihub-firewall-udr-route; do
  jq --arg n "$TNAME" '{name: $n, type: "ExtendedAgentTool", properties: (.tools[] | select(.name == $n) | {type, description, functionCode, timeoutSeconds, toolMode, parameters, dependencies: [], authEnabled: false, attributes: []})}' "$TMP/tools.json" > "$TMP/${TNAME}.json"
  dataplane PUT "/api/v2/extendedAgent/tools/${TNAME}" application/json "$TMP/${TNAME}.json"
done
dataplane PUT /api/v2/extendedAgent/skills/private-aks-upgrade-preflight application/json "$TMP/skill.json"
dataplane PUT /api/v2/agent/customInstructions application/json "$TMP/instructions.json"
dataplane PUT /api/v2/extendedAgent/hooks/pre-kubectl-mutation-safety-gate application/json "$TMP/hook.json"
