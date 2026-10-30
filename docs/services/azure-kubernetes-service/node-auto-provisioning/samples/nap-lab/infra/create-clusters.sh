#!/usr/bin/env bash
# aks-cas(VMSS + Cluster Autoscaler)와 aks-nap(NAP)을 같은 네트워크·VM 크기로 생성합니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab}
LOC=${LOC:-eastus2}
SYS_SKU=${SYS_SKU:-Standard_D4ds_v7}
USER_SKU=${USER_SKU:-Standard_D4ds_v7}

az group create -n "$RG" -l "$LOC" -o none

common=(--resource-group "$RG" --location "$LOC"
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium
  --nodepool-name system --node-vm-size "$SYS_SKU" --node-count 2
  --nodepool-taints CriticalAddonsOnly=true:NoSchedule
  --enable-managed-identity --generate-ssh-keys -o none)

az aks create -n aks-cas "${common[@]}" \
  --cluster-autoscaler-profile scan-interval=10s scale-down-delay-after-add=0m \
    scale-down-unneeded-time=1m scale-down-unready-time=1m &
az aks create -n aks-nap "${common[@]}" --node-provisioning-mode Auto &
wait

# on-demand(Regular) 고정 크기 VMSS 풀. 축소 비교를 위해 unneeded-time을 1분으로 줄였습니다.
az aks nodepool add -g "$RG" --cluster-name aks-cas -n user --mode User \
  --node-vm-size "$USER_SKU" --priority Regular --node-count 0 \
  --enable-cluster-autoscaler --min-count 0 --max-count 10 -o none

for c in aks-cas aks-nap; do
  az aks get-credentials -g "$RG" -n "$c" --context "$c" --overwrite-existing
done
