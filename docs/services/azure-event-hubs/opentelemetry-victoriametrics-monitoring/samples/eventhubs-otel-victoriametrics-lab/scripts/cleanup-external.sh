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

# Every lookup must succeed: a failed az call must fail cleanup, not look like "nothing to delete".
if [[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]]; then
  group_exists="$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" \
    || die "could not check resource group $AZURE_RESOURCE_GROUP"
  if [[ "$group_exists" == "true" ]]; then
    identities="$(az identity list --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
      --query "[].name" -o tsv)" || die "could not list managed identities"
    while IFS= read -r identity; do
      [[ -n "$identity" ]] || continue
      # Only the credentials azd-postprovision.sh creates; anything else in the group is left alone.
      credentials="$(az identity federated-credential list --subscription "$AZURE_SUBSCRIPTION_ID" \
        -g "$AZURE_RESOURCE_GROUP" --identity-name "$identity" \
        --query "[?name=='aks-eventhubs-producer' || name=='aks-eventhubs-slow-consumer'].name" -o tsv)" \
        || die "could not list federated credentials of $identity"
      while IFS= read -r credential; do
        [[ -n "$credential" ]] || continue
        az identity federated-credential delete --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
          --identity-name "$identity" --name "$credential" --yes --output none
        log "deleted federated credential $credential"
      done <<<"$credentials"
    done <<<"$identities"
  fi
fi

rm -f "$STATE/kubeconfig" "$STATE/gateway-bootstrap.log" "$STATE/port-forward.log"
log "external state removed. Local evidence/ is kept for review; delete it manually when done."
