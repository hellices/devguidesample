#!/usr/bin/env bash
# KEDA HTTP Add-on은 AKS KEDA add-on에 포함되지 않으므로 Helm으로 별도 설치합니다.
# AKS add-on의 KEDA core는 kube-system에 있으므로 같은 namespace에 설치합니다.
# 실측과 같은 chart 버전(0.16.0)을 고정합니다.
set -euo pipefail
CTX=${CTX:?} CHART_VERSION=0.16.0
helm repo add kedacore https://kedacore.github.io/charts >/dev/null
helm repo update kedacore >/dev/null
helm upgrade --install http-add-on kedacore/keda-add-ons-http --kube-context "$CTX" \
  --namespace kube-system --version "$CHART_VERSION" \
  -f "$(dirname "$0")/values.yaml" --wait --timeout 5m
kubectl --context "$CTX" --request-timeout=30s -n kube-system get pods -l app.kubernetes.io/part-of=keda-add-ons-http
