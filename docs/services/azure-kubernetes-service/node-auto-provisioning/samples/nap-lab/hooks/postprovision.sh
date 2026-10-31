#!/usr/bin/env bash
# azd provision 뒤 실행: 두 클러스터의 kubeconfig context(이름 = 클러스터 이름)와 NAP NodePool을 준비합니다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${AZURE_RESOURCE_GROUP:?}" "${CAS_CLUSTER_NAME:?}" "${NAP_CLUSTER_NAME:?}" "${AZURE_LOCATION:?}"

for c in "$CAS_CLUSTER_NAME" "$NAP_CLUSTER_NAME"; do
  az aks get-credentials -g "$AZURE_RESOURCE_GROUP" -n "$c" --context "$c" --overwrite-existing -o none
done

# 모든 실측 NodePool은 on-demand만 허용합니다.
kubectl --context "$NAP_CLUSTER_NAME" apply -f manifests/nodepool-fixed.yaml -f manifests/nodepool-flex.yaml >/dev/null

prices="results/prices-$AZURE_LOCATION.json"
[[ -f $prices ]] || python3 bench/prices.py "$AZURE_LOCATION" "$prices" _v7

echo "준비 완료: kubectl context $CAS_CLUSTER_NAME, $NAP_CLUSTER_NAME"
echo "실험 실행: azd env set EXPERIMENT scale-out && azd hooks run postdeploy"
