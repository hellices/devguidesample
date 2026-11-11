#!/usr/bin/env bash
# predown: removes state Bicep does not own. Idempotent; succeeds when nothing exists.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

[[ "${1:-}" == "--yes" ]] || die "pass --yes to confirm cleanup"
require_commands az azd
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
# A provision that failed before writing outputs still created rg-<env> (main.bicep's naming contract);
# derive it so azd down can remove that partial, billed deployment instead of stopping here.
if [[ -z "$AZURE_RESOURCE_GROUP" && -n "$AZURE_SUBSCRIPTION_ID" ]]; then
  env_name="$(env_value AZURE_ENV_NAME)"
  [[ -n "$env_name" ]] || die "AZURE_ENV_NAME is empty; cannot derive the resource group"
  AZURE_RESOURCE_GROUP="rg-$env_name"
  log "AZURE_RESOURCE_GROUP is not recorded; using $AZURE_RESOURCE_GROUP from the template naming contract"
fi
STATE="$(state_dir)"
# azd down clears provision outputs before postdown runs; keep the target for verify-cleanup.sh.
# Records from an earlier run never survive: the target is either both values or explicitly none.
rm -f "$STATE/down-resource-group" "$STATE/down-subscription" "$STATE/down-none"
if [[ -n "$AZURE_RESOURCE_GROUP" && -n "$AZURE_SUBSCRIPTION_ID" ]]; then
  # A resource group is identified by subscription and name; record both.
  printf '%s\n' "$AZURE_RESOURCE_GROUP" >"$STATE/down-resource-group"
  printf '%s\n' "$AZURE_SUBSCRIPTION_ID" >"$STATE/down-subscription"
elif [[ -z "$AZURE_RESOURCE_GROUP" && -z "$AZURE_SUBSCRIPTION_ID" ]]; then
  : >"$STATE/down-none"
else
  die "the environment has only one of AZURE_RESOURCE_GROUP and AZURE_SUBSCRIPTION_ID; cannot record the cleanup target"
fi

# stop succeeds when no forward is recorded, so any failure here is real.
"$LAB_ROOT/scripts/vm-query.sh" stop || die "could not stop the VMSingle port-forward"

# Every lookup must succeed: a failed az call must fail cleanup, not look like "nothing to delete".
if [[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]]; then
  group_exists="$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP" -o tsv)" \
    || die "could not check resource group $AZURE_RESOURCE_GROUP"
  [[ "$group_exists" == "true" || "$group_exists" == "false" ]] \
    || die "unexpected answer to the resource group existence check for $AZURE_RESOURCE_GROUP: $group_exists"
  if [[ "$group_exists" == "true" ]]; then
    # Only the (identity, credential) pairs azd-postprovision.sh federate() creates: the identity is
    # resolved by the producer/consumer client ID output, never by scanning the whole group.
    for service_account in eventhubs-producer eventhubs-slow-consumer; do
      case "$service_account" in
        eventhubs-producer) client_id="$(env_value PRODUCER_CLIENT_ID)" ;;
        *) client_id="$(env_value CONSUMER_CLIENT_ID)" ;;
      esac
      [[ -n "$client_id" ]] || continue
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

# Premium with EXISTING_DEDICATED_CLUSTER_RESOURCE_ID: the lab granted the gateway Monitoring Reader on a
# cluster it does not own. Deleting the lab resource group leaves that assignment behind, so remove
# exactly the assignment the template created (its ID is a provision output) and nothing else there.
reader_assignment="$(env_value EXISTING_CLUSTER_READER_ASSIGNMENT_ID)"
if [[ -n "$reader_assignment" ]]; then
  # ARM may normalize segment casing, so the shape check ignores case and the parts used below come
  # from its capture groups rather than from case-sensitive string trimming.
  shopt -s nocasematch
  [[ "$reader_assignment" =~ ^(/subscriptions/([^/]+)/resourceGroups/[^/]+/providers/Microsoft\.EventHub/clusters/[^/]+)/providers/Microsoft\.Authorization/roleAssignments/([0-9a-f-]{36})$ ]] \
    || die "unexpected EXISTING_CLUSTER_READER_ASSIGNMENT_ID: $reader_assignment"
  shopt -u nocasematch
  reader_scope="${BASH_REMATCH[1]}"
  reader_subscription="${BASH_REMATCH[2]}"
  reader_name="${BASH_REMATCH[3]}"
  # Match the assignment GUID (its name) rather than the full ID, whose casing ARM may normalize.
  reader_count="$(az role assignment list --subscription "$reader_subscription" --scope "$reader_scope" \
    --query "[?name=='$reader_name'] | length(@)" -o tsv)" || die "could not look up $reader_assignment"
  if [[ "$reader_count" != "0" ]]; then
    az role assignment delete --subscription "$reader_subscription" --ids "$reader_assignment" --output none \
      || die "could not delete $reader_assignment"
    log "deleted the gateway Monitoring Reader assignment on the existing Dedicated cluster"
  fi
fi

rm -f "$STATE/kubeconfig" "$STATE/gateway-bootstrap.log" "$STATE/port-forward.log"
log "external state removed. Local evidence/ is kept for review; delete it manually when done."
