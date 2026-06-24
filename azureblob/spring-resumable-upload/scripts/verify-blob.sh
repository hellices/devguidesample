#!/usr/bin/env bash
# Verify that the committed blob matches the local file byte-for-byte.
# Requires: az CLI logged in, AZURE_STORAGE_ACCOUNT + AZURE_STORAGE_CONTAINER env.
set -euo pipefail
LOCAL="${1:?usage: verify-blob.sh <local_file> <blob_name>}"
BLOB="${2:?usage: verify-blob.sh <local_file> <blob_name>}"
ACCT="${AZURE_STORAGE_ACCOUNT:?set AZURE_STORAGE_ACCOUNT}"
CONT="${AZURE_STORAGE_CONTAINER:-uploads}"

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

az storage blob download \
    --account-name "$ACCT" \
    --container-name "$CONT" \
    --name "$BLOB" \
    --file "$TMP" \
    --auth-mode login \
    --no-progress -o none

if cmp -s "$LOCAL" "$TMP"; then
    echo "OK: blob matches local file ($(wc -c <"$LOCAL") bytes)"
else
    echo "FAIL: blob differs from local file" >&2
    exit 1
fi
