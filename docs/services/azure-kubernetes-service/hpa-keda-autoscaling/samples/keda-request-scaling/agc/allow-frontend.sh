#!/usr/bin/env bash
# 2026-04-23 이후 만든 AGC association은 서브넷 NSG를 그대로 적용합니다.
# aks-appgateway 서브넷에 NSG가 연결되어 있고 기본 규칙(AllowVNetInBound, AllowAzureLoadBalancerInBound,
# DenyAllInBound)만 있으면 Internet에서 오는 frontend 포트(80·443)가 막히므로 허용 규칙을 추가합니다.
# NSG가 연결되어 있지 않으면 할 일이 없습니다. AllowAzureLoadBalancerInBound는 그대로 둡니다.
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?} CLUSTER=${AKS_CLUSTER_NAME:?}
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
NSG_ID=$(az network vnet list -g "$MC" --query "[0].subnets[?name=='aks-appgateway'].networkSecurityGroup.id | [0]" -o tsv)
if [[ -z $NSG_ID ]]; then
  echo "aks-appgateway 서브넷에 NSG가 없어 frontend 허용 규칙이 필요하지 않습니다."
  exit 0
fi
NSG_RG=$(cut -d/ -f5 <<<"$NSG_ID") NSG=${NSG_ID##*/}
if az network nsg rule show -g "$NSG_RG" --nsg-name "$NSG" -n allow-agc-frontend-http -o none 2>/dev/null; then exit 0; fi
az network nsg rule create -g "$NSG_RG" --nsg-name "$NSG" -n allow-agc-frontend-http \
  --priority 200 --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes Internet --destination-port-ranges 80 443 -o none
