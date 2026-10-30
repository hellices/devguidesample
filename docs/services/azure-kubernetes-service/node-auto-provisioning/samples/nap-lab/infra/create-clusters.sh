#!/usr/bin/env bash
# aks-cas(VMSS + Cluster Autoscaler)와 aks-nap(NAP)을 같은 네트워크 구성으로 생성합니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab}
LOC=${LOC:-eastus2}
SYS_SKU=${SYS_SKU:-Standard_D4ds_v6}
USER_SKU=${USER_SKU:-Standard_D4ds_v6}

az group create -n "$RG" -l "$LOC" -o none

common=(--resource-group "$RG" --location "$LOC"
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium
  --nodepool-name system --node-vm-size "$SYS_SKU" --node-count 2
  --nodepool-taints CriticalAddonsOnly=true:NoSchedule
  --enable-managed-identity --generate-ssh-keys -o none)

az aks create -n aks-cas "${common[@]}" &
az aks create -n aks-nap "${common[@]}" --node-provisioning-mode Auto &
wait

az aks nodepool add -g "$RG" --cluster-name aks-cas -n user --mode User \
  --node-vm-size "$USER_SKU" --node-count 0 \
  --enable-cluster-autoscaler --min-count 0 --max-count 10 -o none

for c in aks-cas aks-nap; do
  az aks get-credentials -g "$RG" -n "$c" --context "$c" --overwrite-existing
done
