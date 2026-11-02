#!/usr/bin/env bash
# azd provision 뒤 실행: Managed Prometheus·AGC add-on, keda-operator 관리 ID, podinfo 앱, HTTP Add-on, AGC Gateway를 준비합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_SUBSCRIPTION_ID:?}" "${AZURE_RESOURCE_GROUP:?}" "${AKS_CLUSTER_NAME:?}" "${KEDA_CLIENT_ID:?}" "${KEDA_PRINCIPAL_ID:?}"
die() { echo "$*" >&2; exit 1; }
GUID_RE='^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$'
# 변경 작업 전에 입력 형식과 az 현재 구독을 확인합니다.
[[ $AKS_CLUSTER_NAME =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ ]] || die "AKS_CLUSTER_NAME 형식이 올바르지 않습니다: '${AKS_CLUSTER_NAME}'"
[[ $AZURE_SUBSCRIPTION_ID =~ $GUID_RE ]] || die "AZURE_SUBSCRIPTION_ID는 GUID여야 합니다: '${AZURE_SUBSCRIPTION_ID}'"
[[ $KEDA_CLIENT_ID =~ $GUID_RE ]] || die "KEDA_CLIENT_ID는 GUID여야 합니다: '${KEDA_CLIENT_ID}'"
[[ $KEDA_PRINCIPAL_ID =~ $GUID_RE ]] || die "KEDA_PRINCIPAL_ID는 GUID여야 합니다: '${KEDA_PRINCIPAL_ID}'"
ENABLE_AGC=${ENABLE_AGC:-true}
[[ $ENABLE_AGC == true || $ENABLE_AGC == false ]] || die "ENABLE_AGC는 true 또는 false여야 합니다: '${ENABLE_AGC}'"
export ENABLE_AGC
# az의 현재 구독이 azd 환경과 다르면 다른 구독의 리소스를 읽거나 바꾸므로 중단합니다.
CUR_SUB=$(az account show --query id -o tsv | tr 'A-F' 'a-f')
WANT_SUB=$(tr 'A-F' 'a-f' <<<"$AZURE_SUBSCRIPTION_ID")
[[ $CUR_SUB == "$WANT_SUB" ]] || die "az 현재 구독(${CUR_SUB})이 AZURE_SUBSCRIPTION_ID와 다릅니다. az account set --subscription으로 맞추세요."
RG=$AZURE_RESOURCE_GROUP CLUSTER=$AKS_CLUSTER_NAME
export CTX=$CLUSTER
log() { echo "[$(date -u +%T)] $*" >&2; }
# 빈 줄을 뺀 줄 수. grep의 "일치 없음"(1)만 0으로 보고 그 밖의 오류는 실패로 돌려줍니다.
count_lines() { grep -c . <<<"$1" || [[ $? == 1 ]]; }

az aks get-credentials -g "$RG" -n "$CLUSTER" --context "$CTX" --overwrite-existing -o none
./infra/setup-keda-identity.sh
log "Managed Prometheus·AGC add-on 활성화"
./infra/enable-addons.sh

kubectl --context "$CTX" --request-timeout=60s apply -f app/podinfo.yaml -f prometheus/podmonitor.yaml >/dev/null
log "KEDA HTTP Add-on 설치"
./http-add-on/install.sh >/dev/null

if [[ $ENABLE_AGC != true ]]; then
  log "준비 완료(AGC 제외). 실행: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"
  exit 0
fi
MC=$(az aks show -g "$RG" -n "$CLUSTER" --query nodeResourceGroup -o tsv)
# 빈 값이면 az가 구독 전체를 조회하므로 이름을 확인합니다.
[[ $MC =~ ^[A-Za-z0-9._()-]+$ ]] || die "노드 리소스 그룹 이름이 올바르지 않습니다: '${MC}'"
# 노드 리소스 그룹의 모든 VNet에서 aks-appgateway 서브넷을 찾고, 정확히 하나일 때만 진행합니다.
SUBNET_ID=$(az network vnet list -g "$MC" --query "[].subnets[?name=='aks-appgateway'][].id" -o tsv)
COUNT=$(count_lines "$SUBNET_ID")
if (( COUNT != 1 )); then
  die "노드 리소스 그룹 ${MC}에서 aks-appgateway 서브넷을 ${COUNT}개 찾았습니다. 정확히 1개여야 합니다. AGC add-on 상태를 확인하세요."
fi
[[ $SUBNET_ID =~ ^/subscriptions/[^/|[:space:]]+(/[^/|[:space:]]+)+/subnets/aks-appgateway$ ]] ||
  die "서브넷 ID 형식이 올바르지 않습니다: '${SUBNET_ID}'"
MANIFEST=$(sed "s|<alb-subnet-id>|$SUBNET_ID|" agc/gateway.yaml)
kubectl --context "$CTX" --request-timeout=60s apply -f - <<<"$MANIFEST" >/dev/null
log "AGC Gateway 준비 대기"
# --request-timeout은 watch 요청도 끊으므로 대기 시간(20분)보다 길게 둡니다.
kubectl --context "$CTX" --request-timeout=21m -n demo wait gateway/web --for=condition=Programmed --timeout=20m >/dev/null
./agc/allow-frontend.sh
# AGC(trafficController)는 ALB Controller가 node resource group에 만듭니다. KEDA ID에 지표 읽기 권한을 줍니다.
# 여러 개가 있으면 어느 AGC에 권한을 줄지 정할 수 없으므로 정확히 하나일 때만 진행합니다.
ALB_ID=$(az resource list -g "$MC" --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[].id" -o tsv)
ALB_COUNT=$(count_lines "$ALB_ID")
if (( ALB_COUNT != 1 )); then
  die "노드 리소스 그룹 ${MC}에서 AGC(trafficController)를 ${ALB_COUNT}개 찾았습니다. 정확히 1개여야 합니다."
fi
# 다시 실행해도 실패하지 않도록 같은 역할 할당이 없을 때만 만듭니다. 조회가 실패하면 중단합니다.
ASSIGNED=$(az role assignment list --assignee "$KEDA_PRINCIPAL_ID" --role "Monitoring Reader" --scope "$ALB_ID" --query "length(@)" -o tsv)
[[ $ASSIGNED =~ ^[0-9]+$ ]] || die "역할 할당 조회 결과가 숫자가 아닙니다: '${ASSIGNED}'"
if (( ASSIGNED == 0 )); then
  # 조회와 생성 사이에 같은 할당이 생겼으면(RoleAssignmentExists) 이미 부여된 것으로 봅니다.
  if ! ERR=$(az role assignment create --assignee-object-id "$KEDA_PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
      --role "Monitoring Reader" --scope "$ALB_ID" -o none 2>&1); then
    [[ $ERR == *RoleAssignmentExists* ]] || die "$ERR"
    log "Monitoring Reader 역할 할당이 이미 있습니다"
  fi
fi
log "준비 완료. 실행: azd env set PATTERN prometheus-rps && azd hooks run postdeploy"
