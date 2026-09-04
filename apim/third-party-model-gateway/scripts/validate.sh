#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

az bicep build --file "$root/infra/main.bicep" --stdout >/dev/null
az bicep build-params --file "$root/infra/main.bicepparam" --stdout >/dev/null
python3 -m unittest "$root/tests/test_gateway_artifacts.py" -v
