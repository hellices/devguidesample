#!/usr/bin/env bash
# 2026-04-23 이후 만든 AGC association은 서브넷 NSG를 그대로 적용합니다.
# 이 실습에서 aks-appgateway 서브넷 NSG에는 기본 규칙(AllowVNetInBound, AllowAzureLoadBalancerInBound, DenyAllInBound)만 있어
# Internet에서 오는 frontend 포트(80·443)를 허용해야 했습니다. AllowAzureLoadBalancerInBound는 그대로 둡니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab} CLUSTER=${CLUSTER:-aks-nap}
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
NSG=$(az network nsg list -g "$MC" --query "[?contains(name,'appgateway')].name" -o tsv)
az network nsg rule create -g "$MC" --nsg-name "$NSG" -n allow-agc-frontend-http \
  --priority 200 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes Internet --destination-port-ranges 80 443 -o none
