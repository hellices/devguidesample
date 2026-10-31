#!/usr/bin/env bash
# aks-nap 클러스터에 Workload Identity → KEDA → Managed Prometheus → Gateway API·AGC 순서로 기능을 켭니다.
# KEDA add-on보다 Workload Identity를 먼저 켜는 것을 권장합니다. 순서가 바뀌면 keda-operator를 재시작해야 하며,
# setup-keda-identity.sh가 annotation 뒤 keda-operator를 재시작합니다. AGC add-on은 Workload Identity가 필수입니다.
set -euo pipefail
RG=${RG:-rg-aks-autoscale-lab} CLUSTER=${CLUSTER:-aks-nap} LOC=${LOC:-eastus2}

az aks update -g "$RG" -n "$CLUSTER" --enable-oidc-issuer --enable-workload-identity -o none
az aks update -g "$RG" -n "$CLUSTER" --enable-keda -o none

AMW_ID=$(az monitor account create -g "$RG" -n amw-autoscale-lab -l "$LOC" --query id -o tsv)
az aks update -g "$RG" -n "$CLUSTER" --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id "$AMW_ID" -o none

# AGC add-on은 preview입니다. Learn quickstart와 같이 CLI extension, provider, preview feature를 준비합니다.
az extension add --name alb --upgrade -o none
az extension add --name aks-preview --upgrade -o none
for ns in Microsoft.ContainerService Microsoft.Network Microsoft.NetworkFunction Microsoft.ServiceNetworking; do
  az provider register --namespace "$ns" -o none
done
for f in ManagedGatewayAPIPreview ApplicationLoadBalancerPreview; do
  az feature register --namespace Microsoft.ContainerService --name "$f" -o none
  until [[ $(az feature show --namespace Microsoft.ContainerService --name "$f" --query properties.state -o tsv) == Registered ]]; do sleep 30; done
done
az provider register --namespace Microsoft.ContainerService -o none

az aks update -g "$RG" -n "$CLUSTER" --enable-gateway-api --enable-application-load-balancer -o none
