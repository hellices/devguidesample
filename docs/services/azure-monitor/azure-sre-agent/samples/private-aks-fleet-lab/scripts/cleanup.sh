#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

echo "==> Deleting resource group ${RESOURCE_GROUP}"
az group delete --name "$RESOURCE_GROUP" --yes --no-wait
rm -f "$STATE_FILE"
