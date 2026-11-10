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

# stop succeeds when no forward is recorded, so any failure here is real.
"$LAB_ROOT/scripts/vm-query.sh" stop || die "could not stop the VMSingle port-forward"

# Every lookup must succeed: a failed az call must fail cleanup, not look like "nothing to delete".
if [[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]]; then
  group_exists="$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" \
    || die "could not check resource group $AZURE_RESOURCE_GROUP"
  if [[ "$group_exists" == "true" ]]; then
    # Only the (identity, credential) pairs azd-postprovision.sh federate() creates: the identity is
    # resolved by the producer/consumer client ID output, never by scanning the whole group.
    for pair in "$(env_value PRODUCER_CLIENT_ID) eventhubs-producer" "$(env_value CONSUMER_CLIENT_ID) eventhubs-slow-consumer"; do
      read -r client_id service_account <<<"$pair"
      [[ -n "$client_id" && "$service_account" != "$client_id" ]] || continue
      identity="$(az identity list --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
        --query "[?clientId=='$client_id'].name | [0]" -o tsv)" || die "could not look up the $service_account identity"
      [[ -n "$identity" ]] || continue
      credential="aks-$service_account"
      present="$(az identity federated-credential list --subscription "$AZURE_SUBSCRIPTION_ID" \
        -g "$AZURE_RESOURCE_GROUP" --identity-name "$identity" --query "[?name=='$credential'].name" -o tsv)" \
        || die "could not list federated credentials of $identity"
      [[ "$present" == "$credential" ]] || continue
      az identity federated-credential delete --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
        --identity-name "$identity" --name "$credential" --yes --output none
      log "deleted federated credential $credential from $identity"
    done
  fi
fi

rm -f "$STATE/kubeconfig" "$STATE/gateway-bootstrap.log" "$STATE/port-forward.log"
log "external state removed. Local evidence/ is kept for review; delete it manually when done."
