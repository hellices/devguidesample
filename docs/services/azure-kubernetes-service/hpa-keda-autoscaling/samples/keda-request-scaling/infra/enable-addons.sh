#!/usr/bin/env bash
# azd postprovision에서 호출: Bicep으로 만든 클러스터에 Managed Prometheus와 Gateway API·AGC add-on을 켭니다.
# Workload Identity와 KEDA add-on은 Bicep이 클러스터 생성 시 함께 켭니다.
#   AZURE_RESOURCE_GROUP, AKS_CLUSTER_NAME, AZURE_MONITOR_WORKSPACE_ID  필수
#   ENABLE_AGC=false  AGC 실습을 하지 않으면 preview 등록과 add-on 활성화를 건너뜁니다.
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?} CLUSTER=${AKS_CLUSTER_NAME:?} AMW_ID=${AZURE_MONITOR_WORKSPACE_ID:?}

if [[ $(az aks show -g "$RG" -n "$CLUSTER" --query "azureMonitorProfile.metrics.enabled" -o tsv) != true ]]; then
  az aks update -g "$RG" -n "$CLUSTER" --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id "$AMW_ID" -o none
fi

[[ ${ENABLE_AGC:-true} == true ]] || exit 0

# AGC add-on은 preview입니다. Learn quickstart와 같이 CLI extension, provider, preview feature를 준비하고
# 모두 Registered가 된 뒤에 add-on을 켭니다.
az extension add --name alb --upgrade -o none
az extension add --name aks-preview --upgrade -o none
for f in ManagedGatewayAPIPreview ApplicationLoadBalancerPreview; do
  az feature register --namespace Microsoft.ContainerService --name "$f" -o none
done
for f in ManagedGatewayAPIPreview ApplicationLoadBalancerPreview; do
  start=$(date +%s)
  until [[ $(az feature show --namespace Microsoft.ContainerService --name "$f" --query properties.state -o tsv) == Registered ]]; do
    (( $(date +%s) - start <= 3600 )) || { echo "feature $f가 60분 안에 Registered가 되지 않았습니다" >&2; exit 1; }
    echo "feature $f 등록 대기"; sleep 30
  done
done
# feature 등록 뒤 provider를 다시 등록해야 반영됩니다. --wait로 완료까지 기다립니다.
for ns in Microsoft.ContainerService Microsoft.Network Microsoft.NetworkFunction Microsoft.ServiceNetworking; do
  az provider register --namespace "$ns" --wait -o none
done

if [[ $(az aks show -g "$RG" -n "$CLUSTER" --query "ingressProfile.applicationLoadBalancer.enabled" -o tsv 2>/dev/null) != true ]]; then
  az aks update -g "$RG" -n "$CLUSTER" --enable-gateway-api --enable-application-load-balancer -o none
fi
