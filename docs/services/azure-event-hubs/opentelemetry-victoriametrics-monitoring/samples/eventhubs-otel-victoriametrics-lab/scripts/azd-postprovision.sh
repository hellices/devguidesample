#!/usr/bin/env bash
# postprovision: wires AKS, VictoriaMetrics, workload identity, images, and the gateway VM.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az azd kubectl kubelogin helm python3 tar base64
load_env AZURE_SUBSCRIPTION_ID AZURE_ENV_NAME AZURE_RESOURCE_GROUP AKS_CLUSTER_NAME AKS_OIDC_ISSUER \
  ACR_NAME ACR_LOGIN_SERVER GATEWAY_VM_NAME GATEWAY_PUBLIC_IP GATEWAY_PRIVATE_IP GATEWAY_CLIENT_ID \
  PREMIUM_NAMESPACE_NAME WORKLOAD_EVENTHUB_NAME WORKLOAD_CONSUMER_GROUP TELEMETRY_NAMESPACE_NAME \
  TELEMETRY_EVENTHUB_NAME CHECKPOINT_ACCOUNT_URL KEY_VAULT_NAME PRODUCER_CLIENT_ID CONSUMER_CLIENT_ID \
  VMSINGLE_PRIVATE_IP
assert_active_subscription
STATE="$(state_dir)"
NS=eventhubs-observability
AZURE_TENANT_ID="$(az account show --subscription "$AZURE_SUBSCRIPTION_ID" --query tenantId -o tsv)"

python_env() {
  if [[ ! -x "$STATE/venv/bin/python" ]]; then
    python3 -m venv "$STATE/venv"
    "$STATE/venv/bin/pip" install --quiet --requirement "$LAB_ROOT/agent/requirements.txt"
  fi
  printf '%s' "$STATE/venv/bin/python"
}

# GATEWAY_ONLY=true re-renders and restarts only the gateway bundle (for example to switch to the fallback exporter).
if [[ "${GATEWAY_ONLY:-false}" != "true" ]]; then
log "1/6 AKS credentials in a lab-only kubeconfig"
az aks get-credentials --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" \
  --file "$STATE/kubeconfig" --overwrite-existing --output none
kubelogin convert-kubeconfig --kubeconfig "$STATE/kubeconfig" -l azurecli
chmod 600 "$STATE/kubeconfig"
for _ in $(seq 1 30); do
  kube auth can-i '*' '*' --all-namespaces >/dev/null 2>&1 && break
  log "waiting for Azure RBAC cluster-admin propagation"
  sleep 10
done
kube auth can-i '*' '*' --all-namespaces >/dev/null || die "deployer cannot administer the AKS cluster"

log "2/6 workload identity federation"
federate() {
  local client_id="$1" service_account="$2" identity
  identity="$(az identity list --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
    --query "[?clientId=='$client_id'].name | [0]" -o tsv)"
  [[ -n "$identity" ]] || die "managed identity not found for $service_account"
  az identity federated-credential create --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" \
    --identity-name "$identity" --name "aks-$service_account" --issuer "$AKS_OIDC_ISSUER" \
    --subject "system:serviceaccount:$NS:$service_account" --audiences api://AzureADTokenExchange --output none
}
federate "$PRODUCER_CLIENT_ID" eventhubs-producer
federate "$CONSUMER_CLIENT_ID" eventhubs-slow-consumer

log "3/6 workload image build in ACR"
IMAGE_TAG="$(git -C "$LAB_ROOT" rev-parse --short HEAD 2>/dev/null || date -u +%Y%m%d%H%M%S)"
az acr build --subscription "$AZURE_SUBSCRIPTION_ID" --registry "$ACR_NAME" --image "eventhubs-lab-workloads:$IMAGE_TAG" \
  --build-arg "$(<"$LAB_ROOT/workloads/images.lock")" "$LAB_ROOT/workloads" --no-logs --output none
IMAGE_DIGEST="$(az acr repository show --subscription "$AZURE_SUBSCRIPTION_ID" --name "$ACR_NAME" \
  --image "eventhubs-lab-workloads:$IMAGE_TAG" --query digest -o tsv)"
WORKLOAD_IMAGE="$ACR_LOGIN_SERVER/eventhubs-lab-workloads@$IMAGE_DIGEST"
azd_env set WORKLOAD_IMAGE "$WORKLOAD_IMAGE"

log "4/6 VictoriaMetrics Operator, VMSingle, VMAgent"
kube apply -f "$LAB_ROOT/k8s/namespace.yaml"
helm upgrade --install vm-operator victoria-metrics-operator \
  --repo https://victoriametrics.github.io/helm-charts --version 0.68.2 \
  --kubeconfig "$STATE/kubeconfig" --namespace "$NS" --values "$LAB_ROOT/k8s/victoria-values.yaml" \
  --wait --timeout 10m
kube wait --for condition=Established crd/vmsingles.operator.victoriametrics.com --timeout 120s
sed -e "s|__VMSINGLE_PRIVATE_IP__|$VMSINGLE_PRIVATE_IP|g" "$LAB_ROOT/k8s/victoria.yaml" | kube apply -f -
sed -e "s|__GATEWAY_PRIVATE_IP__|$GATEWAY_PRIVATE_IP|g" "$LAB_ROOT/k8s/scrape.yaml" | kube apply -f -
for _ in $(seq 1 60); do
  status="$(kube get vmsingle lab -n "$NS" -o jsonpath='{.status.updateStatus}' 2>/dev/null || true)"
  lb="$(kube get svc vmsingle-internal -n "$NS" -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)"
  [[ "$status" == "operational" && "$lb" == "$VMSINGLE_PRIVATE_IP" ]] && break
  sleep 10
done
[[ "$status" == "operational" ]] || die "VMSingle is not operational (status=$status)"
[[ "$lb" == "$VMSINGLE_PRIVATE_IP" ]] || die "VMSingle internal load balancer did not receive $VMSINGLE_PRIVATE_IP"
kube rollout status deploy/vmagent-lab -n "$NS" --timeout 300s
else
  WORKLOAD_IMAGE="$(env_value WORKLOAD_IMAGE)"
  [[ -n "$WORKLOAD_IMAGE" ]] || die "GATEWAY_ONLY requires a previous full postprovision run"
fi

log "5/6 gateway bundle: Collector, lag exporter, Grafana"
BUNDLE="$(mktemp -d)"
trap 'rm -rf "$BUNDLE"' EXIT
cp "$LAB_ROOT/gateway/compose.yaml" "$BUNDLE/"
cp -R "$LAB_ROOT/gateway/grafana" "$BUNDLE/"
cat > "$BUNDLE/collector.env" <<ENV
AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID
AZURE_RESOURCE_GROUP=$AZURE_RESOURCE_GROUP
PREMIUM_NAMESPACE_NAME=$PREMIUM_NAMESPACE_NAME
TELEMETRY_NAMESPACE=$TELEMETRY_NAMESPACE_NAME.servicebus.windows.net
TELEMETRY_EVENTHUB_NAME=$TELEMETRY_EVENTHUB_NAME
CHECKPOINT_ACCOUNT_URL=$CHECKPOINT_ACCOUNT_URL
GATEWAY_CLIENT_ID=$GATEWAY_CLIENT_ID
VMSINGLE_URL=http://$VMSINGLE_PRIVATE_IP:8428
EXISTING_DEDICATED_CLUSTER_RESOURCE_ID=$(env_value EXISTING_DEDICATED_CLUSTER_RESOURCE_ID)
ENABLE_API_RECEIVER=${ENABLE_API_RECEIVER:-true}
ENABLE_FALLBACK_EXPORTER=${ENABLE_FALLBACK_EXPORTER:-false}
ENV
"$(python_env)" "$LAB_ROOT/gateway/render_collector.py" --env-file "$BUNDLE/collector.env" --output "$BUNDLE/collector.yaml"
rm "$BUNDLE/collector.env"
cat > "$BUNDLE/lag-exporter.env" <<ENV
AZURE_CLIENT_ID=$GATEWAY_CLIENT_ID
EVENT_HUB_NAMESPACE=$PREMIUM_NAMESPACE_NAME.servicebus.windows.net
EVENT_HUB_NAME=$WORKLOAD_EVENTHUB_NAME
EVENT_HUB_CONSUMER_GROUP=$WORKLOAD_CONSUMER_GROUP
CHECKPOINT_STORAGE_URL=$CHECKPOINT_ACCOUNT_URL
CHECKPOINT_CONTAINER=workload-checkpoints
LAG_POLL_SECONDS=15
ENV
cat > "$BUNDLE/.env" <<ENV
LAG_EXPORTER_IMAGE=$WORKLOAD_IMAGE
GATEWAY_CLIENT_ID=$GATEWAY_CLIENT_ID
AZURE_TENANT_ID=$AZURE_TENANT_ID
VMSINGLE_PRIVATE_IP=$VMSINGLE_PRIVATE_IP
KEY_VAULT_NAME=$KEY_VAULT_NAME
ACR_NAME=$ACR_NAME
COMPOSE_PROFILE=$([[ "${ENABLE_FALLBACK_EXPORTER:-false}" == "true" ]] && echo fallback || echo default)
ENV
# bsdtar pads -z output to its block size, so compress separately to keep the payload small.
BUNDLE_B64="$(COPYFILE_DISABLE=1 tar -C "$BUNDLE" -cf - . | gzip -9c | base64 | tr -d '\n')"
# Run Command splits unnamed values on '=', which base64 padding contains; always pass name=value.
gateway_run "$LAB_ROOT/gateway/bootstrap.sh" "BUNDLE_B64=$BUNDLE_B64" >"$STATE/gateway-bootstrap.log"
grep -q GATEWAY_READY "$STATE/gateway-bootstrap.log" || die "gateway bootstrap failed; see $STATE/gateway-bootstrap.log"
sed -n '/GATEWAY_READY/,/^\[stderr\]/p' "$STATE/gateway-bootstrap.log" >&2

log "6/6 operator-facing health checks"
curl -fsS --max-time 10 "http://$GATEWAY_PUBLIC_IP:3000/api/health" >/dev/null || die "Grafana is not reachable from the operator egress IP"
log "postprovision completed."
