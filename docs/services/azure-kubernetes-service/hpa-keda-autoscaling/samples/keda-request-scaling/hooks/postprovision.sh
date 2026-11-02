#!/usr/bin/env bash
# azd provision 뒤 실행: Managed Prometheus·AGC add-on, keda-operator 관리 ID, podinfo 앱, HTTP Add-on, AGC Gateway를 준비합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_RESOURCE_GROUP:?}" "${AKS_CLUSTER_NAME:?}" "${KEDA_CLIENT_ID:?}" "${KEDA_PRINCIPAL_ID:?}"
RG=$AZURE_RESOURCE_GROUP CLUSTER=$AKS_CLUSTER_NAME
export CTX=$CLUSTER
log() { echo "[$(date -u +%T)] $*" >&2; }

az aks get-credentials -g "$RG" -n "$CLUSTER" --context "$CTX" --overwrite-existing -o none
./infra/setup-keda-identity.sh
log "Managed Prometheus·AGC add-on 활성화"
./infra/enable-addons.sh

kubectl --context "$CTX" apply -f app/podinfo.yaml -f prometheus/podmonitor.yaml >/dev/null
log "KEDA HTTP Add-on 설치"
./http-add-on/install.sh >/dev/null

[[ ${ENABLE_AGC:-true} == true ]] || exit 0
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
# 노드 리소스 그룹의 모든 VNet에서 aks-appgateway 서브넷을 찾고, 정확히 하나일 때만 진행합니다.
SUBNET_ID=$(az network vnet list -g "$MC" --query "[].subnets[?name=='aks-appgateway'][].id" -o tsv)
COUNT=$(grep -c . <<<"$SUBNET_ID" || true)
if (( COUNT != 1 )); then
  echo "노드 리소스 그룹 ${MC}에서 aks-appgateway 서브넷을 ${COUNT}개 찾았습니다. 정확히 1개여야 합니다. AGC add-on 상태를 확인하세요." >&2
  exit 1
fi
sed "s|<alb-subnet-id>|$SUBNET_ID|" agc/gateway.yaml | kubectl --context "$CTX" apply -f - >/dev/null
log "AGC Gateway 준비 대기"
kubectl --context "$CTX" -n demo wait gateway/web --for=condition=Programmed --timeout=20m >/dev/null
./agc/allow-frontend.sh
# AGC(trafficController)는 ALB Controller가 node resource group에 만듭니다. KEDA ID에 지표 읽기 권한을 줍니다.
# 여러 개가 있으면 어느 AGC에 권한을 줄지 정할 수 없으므로 정확히 하나일 때만 진행합니다.
ALB_ID=$(az resource list -g "$MC" --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[].id" -o tsv)
ALB_COUNT=$(grep -c . <<<"$ALB_ID" || true)
if (( ALB_COUNT != 1 )); then
  echo "노드 리소스 그룹 ${MC}에서 AGC(trafficController)를 ${ALB_COUNT}개 찾았습니다. 정확히 1개여야 합니다." >&2
  exit 1
fi
# 다시 실행해도 실패하지 않도록 같은 역할 할당이 없을 때만 만듭니다. 조회가 실패하면 중단합니다.
ASSIGNED=$(az role assignment list --assignee "$KEDA_PRINCIPAL_ID" --role "Monitoring Reader" --scope "$ALB_ID" --query "length(@)" -o tsv)
if [[ $ASSIGNED == 0 ]]; then
  az role assignment create --assignee-object-id "$KEDA_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
    --role "Monitoring Reader" --scope "$ALB_ID" -o none
fi
log "준비 완료. 실행: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"
