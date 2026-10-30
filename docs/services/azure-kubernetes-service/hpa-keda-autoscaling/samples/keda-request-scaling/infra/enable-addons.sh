#!/usr/bin/env bash
# aks-nap 클러스터에 Workload Identity → KEDA → Managed Prometheus → Gateway API·AGC 순서로 기능을 켭니다.
# KEDA add-on보다 Workload Identity를 먼저 켜야 keda-operator가 federated token을 받습니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab} CLUSTER=${CLUSTER:-aks-nap} LOC=${LOC:-eastus2}

az aks update -g "$RG" -n "$CLUSTER" --enable-oidc-issuer --enable-workload-identity -o none
az aks update -g "$RG" -n "$CLUSTER" --enable-keda -o none

AMW_ID=$(az monitor account create -g "$RG" -n amw-autoscale-lab -l "$LOC" --query id -o tsv)
az aks update -g "$RG" -n "$CLUSTER" --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id "$AMW_ID" -o none

az aks update -g "$RG" -n "$CLUSTER" --enable-gateway-api --enable-application-load-balancer -o none
