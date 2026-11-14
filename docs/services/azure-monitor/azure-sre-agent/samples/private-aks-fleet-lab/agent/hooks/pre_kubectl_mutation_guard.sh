#!/bin/bash
set -euo pipefail
PAYLOAD="$(cat)"
if echo "$PAYLOAD" | grep -Eiq '(delete[[:space:]]+(node|namespace|ns|clusterrole)|drain[[:space:]]+|cordon[[:space:]]+)'; then
  echo '{"decision":"deny","reason":"Destructive cluster-level kubectl operation is blocked by pre-kubectl-mutation-safety-gate."}'
  exit 0
fi
echo '{"decision":"allow"}'
