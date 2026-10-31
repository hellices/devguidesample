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
SUBNET_ID=$(az network vnet list -g "$MC" --query "[0].subnets[?name=='aks-appgateway'].id | [0]" -o tsv)
[[ -n $SUBNET_ID ]] || { echo "aks-appgateway 서브넷이 없습니다. AGC add-on 상태를 확인하세요." >&2; exit 1; }
sed "s|<alb-subnet-id>|$SUBNET_ID|" agc/gateway.yaml | kubectl --context "$CTX" apply -f - >/dev/null
log "AGC Gateway 준비 대기"
kubectl --context "$CTX" -n demo wait gateway/web --for=condition=Programmed --timeout=20m >/dev/null
./agc/allow-frontend.sh
# AGC(trafficController)는 ALB Controller가 node resource group에 만듭니다. KEDA ID에 지표 읽기 권한을 줍니다.
ALB_ID=$(az resource list -g "$MC" --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[0].id" -o tsv)
az role assignment create --assignee-object-id "$KEDA_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" --scope "$ALB_ID" -o none
log "준비 완료. 실행: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"
