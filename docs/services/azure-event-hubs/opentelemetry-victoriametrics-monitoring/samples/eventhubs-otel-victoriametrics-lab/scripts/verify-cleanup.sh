#!/usr/bin/env bash
# postdown: proves the lab resource group recorded by predown no longer exists.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
STATE="$(state_dir)"
# Verify exactly the group and subscription predown recorded; the current environment values may
# already point elsewhere, so they never stand in for a missing record.
[[ -f "$STATE/down-resource-group" && -f "$STATE/down-subscription" ]] \
  || die "predown did not record the resource group and subscription to verify"
recorded="$(<"$STATE/down-resource-group")"
recorded_subscription="$(<"$STATE/down-subscription")"
[[ -z "$AZURE_RESOURCE_GROUP" || "$AZURE_RESOURCE_GROUP" == "$recorded" ]] \
  || die "predown recorded $recorded but the environment now targets $AZURE_RESOURCE_GROUP"
[[ -z "$AZURE_SUBSCRIPTION_ID" || "$AZURE_SUBSCRIPTION_ID" == "$recorded_subscription" ]] \
  || die "predown recorded subscription $recorded_subscription but the environment now uses $AZURE_SUBSCRIPTION_ID"
AZURE_RESOURCE_GROUP="$recorded"
AZURE_SUBSCRIPTION_ID="$recorded_subscription"
[[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]] || die "predown recorded an empty resource group or subscription"

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
