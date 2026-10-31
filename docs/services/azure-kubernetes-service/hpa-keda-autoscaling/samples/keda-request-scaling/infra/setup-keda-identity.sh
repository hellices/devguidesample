#!/usr/bin/env bash
# azd postprovision에서 호출: Bicep이 만든 KEDA용 관리 ID(federated credential 포함)를 keda-operator에 연결합니다.
#   CTX(kube context), KEDA_CLIENT_ID  필수
set -euo pipefail
CTX=${CTX:?} CLIENT_ID=${KEDA_CLIENT_ID:?}
current=$(kubectl --context "$CTX" -n kube-system get serviceaccount keda-operator \
  -o jsonpath='{.metadata.annotations.azure\.workload\.identity/client-id}')
[[ $current == "$CLIENT_ID" ]] && exit 0
kubectl --context "$CTX" -n kube-system annotate serviceaccount keda-operator \
  azure.workload.identity/client-id="$CLIENT_ID" --overwrite
# annotation은 새 Pod부터 적용되므로 keda-operator를 다시 시작합니다.
kubectl --context "$CTX" -n kube-system rollout restart deploy keda-operator
kubectl --context "$CTX" -n kube-system rollout status deploy keda-operator --timeout=5m
