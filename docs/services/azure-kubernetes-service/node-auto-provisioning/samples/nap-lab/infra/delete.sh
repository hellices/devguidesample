#!/usr/bin/env bash
set -euo pipefail
az group delete -n "${RG:-rg-aks-autoscale-lab}" --yes --no-wait
