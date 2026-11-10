#!/usr/bin/env bash
# postdown: proves the lab resource group recorded by predown no longer exists.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
STATE="$(state_dir)"
# The group predown recorded is the one being deleted; a different current value is a mismatch.
if [[ -f "$STATE/down-resource-group" ]]; then
  recorded="$(<"$STATE/down-resource-group")"
  [[ -z "$AZURE_RESOURCE_GROUP" || "$AZURE_RESOURCE_GROUP" == "$recorded" ]] \
    || die "predown recorded $recorded but the environment now targets $AZURE_RESOURCE_GROUP"
  AZURE_RESOURCE_GROUP="$recorded"
fi
if [[ -f "$STATE/down-subscription" ]]; then
  recorded_subscription="$(<"$STATE/down-subscription")"
  [[ -z "$AZURE_SUBSCRIPTION_ID" || "$AZURE_SUBSCRIPTION_ID" == "$recorded_subscription" ]] \
    || die "predown recorded subscription $recorded_subscription but the environment now uses $AZURE_SUBSCRIPTION_ID"
  AZURE_SUBSCRIPTION_ID="$recorded_subscription"
fi
[[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]] || die "no resource group recorded to verify"

for attempt in $(seq 1 60); do
  # A failed lookup is an error, not "still exists".
  exists="$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" \
    || die "could not query resource group $AZURE_RESOURCE_GROUP"
  if [[ "$exists" == "false" ]]; then
    log "resource group $AZURE_RESOURCE_GROUP no longer exists"
    rm -f "$STATE/down-resource-group" "$STATE/down-subscription"
    exit 0
  fi
  if [[ "$attempt" -lt 60 ]]; then sleep 20; fi
done
die "resource group $AZURE_RESOURCE_GROUP still exists"
