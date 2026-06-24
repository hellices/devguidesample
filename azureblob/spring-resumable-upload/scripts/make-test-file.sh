#!/usr/bin/env bash
# Generate a 50 MiB test file with random content.
set -euo pipefail
OUT="${1:-test-50mb.bin}"
SIZE_MB="${2:-50}"
dd if=/dev/urandom of="$OUT" bs=1m count="$SIZE_MB" status=none
LOCAL_MD5=$(md5 -q "$OUT" 2>/dev/null || md5sum "$OUT" | awk '{print $1}')
echo "wrote $OUT ($(wc -c <"$OUT") bytes) md5=$LOCAL_MD5"
