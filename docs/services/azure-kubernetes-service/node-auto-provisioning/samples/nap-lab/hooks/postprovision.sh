#!/usr/bin/env bash
# azd provision 뒤 실행: 두 클러스터의 kubeconfig context(이름 = 클러스터 이름)와 NAP NodePool을 준비합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_RESOURCE_GROUP:?}" "${CAS_CLUSTER_NAME:?}" "${NAP_CLUSTER_NAME:?}" "${AZURE_LOCATION:?}"

for c in "$CAS_CLUSTER_NAME" "$NAP_CLUSTER_NAME"; do
  az aks get-credentials -g "$AZURE_RESOURCE_GROUP" -n "$c" --context "$c" --overwrite-existing -o none
done

# 모든 실측 NodePool은 on-demand만 허용합니다. bench-fixed는 CAS user 풀과 같은 VM 크기(AKS_VM_SIZE)로
# 고정하고, CAS user 풀 최대 10대와 같은 vCPU 상한을 둡니다.
VM_SIZE=${AKS_VM_SIZE:-Standard_D4ds_v7}
vcpu=$(az vm list-skus -l "$AZURE_LOCATION" --size "$VM_SIZE" --resource-type virtualMachines \
  --query "[?name=='$VM_SIZE'] | [0].capabilities[?name=='vCPUs'].value | [0]" -o tsv)
[[ $vcpu =~ ^[0-9]+$ ]] || { echo "$VM_SIZE의 vCPU 수를 확인할 수 없습니다" >&2; exit 1; }
sed -e "s/Standard_D4ds_v7/$VM_SIZE/" -e "s/cpu: \"40\"/cpu: \"$((vcpu * 10))\"/" manifests/nodepool-fixed.yaml |
  kubectl --context "$NAP_CLUSTER_NAME" apply -f - >/dev/null
kubectl --context "$NAP_CLUSTER_NAME" apply -f manifests/nodepool-flex.yaml >/dev/null

prices="results/prices-$AZURE_LOCATION.json"
[[ -f $prices ]] || python3 bench/prices.py "$AZURE_LOCATION" "$prices" _v7

echo "준비 완료: kubectl context $CAS_CLUSTER_NAME, $NAP_CLUSTER_NAME"
echo "실험 실행: azd env set EXPERIMENT scale-out && azd hooks run postdeploy"
