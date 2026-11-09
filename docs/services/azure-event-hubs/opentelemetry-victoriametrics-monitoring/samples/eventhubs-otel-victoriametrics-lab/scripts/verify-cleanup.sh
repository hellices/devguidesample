#!/usr/bin/env bash
# postdown: proves the lab resource group is gone and that no Dedicated cluster was ever involved.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az
AZURE_SUBSCRIPTION_ID="$(env_value AZURE_SUBSCRIPTION_ID)"
AZURE_RESOURCE_GROUP="$(env_value AZURE_RESOURCE_GROUP)"
[[ -n "$AZURE_SUBSCRIPTION_ID" && -n "$AZURE_RESOURCE_GROUP" ]] || die "azd environment has no resource group to verify"

for _ in $(seq 1 60); do
  if [[ "$(az group exists --subscription "$AZURE_SUBSCRIPTION_ID" -n "$AZURE_RESOURCE_GROUP")" == "false" ]]; then
    log "resource group $AZURE_RESOURCE_GROUP no longer exists"
    exit 0
  fi
  sleep 20
done
die "resource group $AZURE_RESOURCE_GROUP still exists"
