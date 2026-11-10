#!/usr/bin/env bash
# postdown: proves the lab resource group recorded by predown no longer exists.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
STATE="$(state_dir)"
if [[ -z "$AZURE_RESOURCE_GROUP" && -f "$STATE/down-resource-group" ]]; then
  AZURE_RESOURCE_GROUP="$(<"$STATE/down-resource-group")"
fi
[[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]] || die "no resource group recorded to verify"

for _ in $(seq 1 60); do
  # A failed lookup is an error, not "still exists".
  exists="$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" \
    || die "could not query resource group $AZURE_RESOURCE_GROUP"
  if [[ "$exists" == "false" ]]; then
    log "resource group $AZURE_RESOURCE_GROUP no longer exists"
    rm -f "$STATE/down-resource-group"
    exit 0
  fi
  sleep 20
done
die "resource group $AZURE_RESOURCE_GROUP still exists"
