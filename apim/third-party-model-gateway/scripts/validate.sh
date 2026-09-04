#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$root"

az bicep build --file infra/main.bicep --stdout >/dev/null
az bicep build-params --file infra/main.bicepparam --stdout >/dev/null
python3 -m unittest tests/test_gateway_artifacts.py -v
