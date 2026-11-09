#!/usr/bin/env bash
# predown: removes state Bicep does not own. Idempotent; succeeds when nothing exists.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

[[ "${1:-}" == "--yes" ]] || die "pass --yes to confirm cleanup"
require_commands az azd
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
STATE="$(state_dir)"
# azd down clears provision outputs before postdown runs; keep the target for verify-cleanup.sh.
[[ -n "$AZURE_RESOURCE_GROUP" ]] && printf '%s\n' "$AZURE_RESOURCE_GROUP" >"$STATE/down-resource-group"

"$LAB_ROOT/scripts/vm-query.sh" stop >/dev/null 2>&1 || true

if [[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]] \
  && [[ "$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" == "true" ]]; then
  for identity in $(az identity list --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" --query "[].name" -o tsv); do
    for credential in $(az identity federated-credential list --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
      --identity-name "$identity" --query "[].name" -o tsv); do
      az identity federated-credential delete --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
        --identity-name "$identity" --name "$credential" --yes --output none
      log "deleted federated credential $credential"
    done
  done
fi

rm -f "$STATE/kubeconfig" "$STATE/gateway-bootstrap.log" "$STATE/port-forward.log"
log "external state removed. Local evidence/ is kept for review; delete it manually when done."
