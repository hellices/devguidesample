#!/usr/bin/env bash
# azd postprovision에서 호출: Bicep으로 만든 클러스터에 Managed Prometheus와 Gateway API·AGC add-on을 켭니다.
# Workload Identity와 KEDA add-on은 Bicep이 클러스터 생성 시 함께 켭니다.
#   AZURE_RESOURCE_GROUP, AKS_CLUSTER_NAME, AZURE_MONITOR_WORKSPACE_ID  필수
#   ENABLE_AGC=false  AGC 실습을 하지 않으면 preview 등록과 add-on 활성화를 건너뜁니다(true 또는 false, 기본 true).
set -euo pipefail
RG=${AZURE_RESOURCE_GROUP:?} CLUSTER=${AKS_CLUSTER_NAME:?} AMW_ID=${AZURE_MONITOR_WORKSPACE_ID:?}
ENABLE_AGC=${ENABLE_AGC:-true}
[[ $ENABLE_AGC == true || $ENABLE_AGC == false ]] || { echo "ENABLE_AGC는 true 또는 false여야 합니다: '${ENABLE_AGC}'" >&2; exit 2; }

# Managed Prometheus가 이미 켜져 있어도 이 sample의 workspace로 Prometheus 지표를 보내는 DCR이 연결되어 있지 않으면 다시 연결합니다.
# DCR에 $AMW_ID를 가리키는 monitoringAccounts destination이 있고, Microsoft-PrometheusMetrics stream을
# 그 destination으로 보내는 dataFlow가 있을 때만 연결된 것으로 봅니다(ID는 대소문자 구분 없이 비교).
# 조회가 실패하면 연결되지 않은 것으로 넘기지 않고 중단합니다.
aks_id=$(az aks show -g "$RG" -n "$CLUSTER" --query id -o tsv)
metrics_enabled=$(az aks show -g "$RG" -n "$CLUSTER" --query "azureMonitorProfile.metrics.enabled" -o tsv)
linked=false
if [[ $metrics_enabled == true ]]; then
  dcrs=$(az monitor data-collection rule association list --resource "$aks_id" --query "[].dataCollectionRuleId" -o tsv)
  while IFS= read -r dcr; do
    [[ -n $dcr ]] || continue
    # 연결이 남아 있어도 DCR을 읽을 수 없으면(삭제됨·권한 없음) 오류를 보여 주고 연결되지 않은 것으로 봅니다.
    if ! dcr_json=$(az monitor data-collection rule show --ids "$dcr" -o json </dev/null); then
      echo "DCR ${dcr}을 읽지 못해 이 sample workspace 연결 여부를 확인할 수 없습니다. 다시 연결합니다." >&2
      continue
    fi
    if python3 -c '
import json, sys
r = json.loads(sys.stdin.read())
p = r.get("properties") or {}
dest = r.get("destinations") or p.get("destinations") or {}
names = {str(m.get("name", "")).lower() for m in dest.get("monitoringAccounts") or []
         if str(m.get("accountResourceId", "")).lower() == sys.argv[1].lower()}
ok = any("microsoft-prometheusmetrics" in {str(s).lower() for s in f.get("streams") or []}
         and names & {str(d).lower() for d in f.get("destinations") or []}
         for f in r.get("dataFlows") or p.get("dataFlows") or [])
sys.exit(0 if ok else 1)' "$AMW_ID" <<<"$dcr_json"; then linked=true; break; fi
  done <<<"$dcrs"
fi
if [[ $linked != true ]]; then
  az aks update -g "$RG" -n "$CLUSTER" --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id "$AMW_ID" -o none
fi

[[ $ENABLE_AGC == true ]] || exit 0

# AGC add-on은 preview입니다. Learn quickstart와 같이 CLI extension, provider, preview feature를 준비하고
# 모두 Registered가 된 뒤에 add-on을 켭니다.
az extension add --name alb --upgrade -o none
az extension add --name aks-preview --upgrade -o none
for f in ManagedGatewayAPIPreview ApplicationLoadBalancerPreview; do
  az feature register --namespace Microsoft.ContainerService --name "$f" -o none
done
# feature마다 60분 마감을 두고 조회 전후에 확인합니다. 마감을 넘겨 Registered가 되면 시간 초과로 봅니다.
for f in ManagedGatewayAPIPreview ApplicationLoadBalancerPreview; do
  deadline=$(( SECONDS + 3600 ))
  while :; do
    (( SECONDS < deadline )) || { echo "feature ${f}가 60분 안에 Registered가 되지 않았습니다" >&2; exit 1; }
    state=$(az feature show --namespace Microsoft.ContainerService --name "$f" --query properties.state -o tsv)
    if [[ $state == Registered ]]; then
      (( SECONDS < deadline )) || { echo "feature ${f}가 60분 안에 Registered가 되지 않았습니다" >&2; exit 1; }
      break
    fi
    rest=$(( deadline - SECONDS ))
    (( rest > 0 )) || continue
    echo "feature ${f} 등록 대기(현재 ${state:-알 수 없음})" >&2
    sleep $(( rest < 30 ? rest : 30 ))
  done
done
# feature 등록 뒤 provider를 다시 등록해야 반영됩니다. --wait로 완료까지 기다립니다.
for ns in Microsoft.ContainerService Microsoft.Network Microsoft.NetworkFunction Microsoft.ServiceNetworking; do
  az provider register --namespace "$ns" --wait -o none
done

# Gateway API와 ALB 상태를 따로 확인해 꺼져 있는 것만 켭니다. 조회가 실패하면 중단합니다.
gateway_api=$(az aks show -g "$RG" -n "$CLUSTER" --query "ingressProfile.gatewayApi.installation" -o tsv)
alb_enabled=$(az aks show -g "$RG" -n "$CLUSTER" --query "ingressProfile.applicationLoadBalancer.enabled" -o tsv)
flags=()
[[ $gateway_api == Standard ]] || flags+=(--enable-gateway-api)
[[ $alb_enabled == true ]] || flags+=(--enable-application-load-balancer)
if (( ${#flags[@]} > 0 )); then
  az aks update -g "$RG" -n "$CLUSTER" "${flags[@]}" -o none
fi
