#!/usr/bin/env bash
# postprovision: wires AKS, VictoriaMetrics, workload identity, images, and the gateway VM.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az azd kubectl kubelogin helm python3 tar base64
load_env AZURE_SUBSCRIPTION_ID AZURE_ENV_NAME AZURE_RESOURCE_GROUP AKS_CLUSTER_NAME AKS_OIDC_ISSUER \
  ACR_NAME ACR_LOGIN_SERVER GATEWAY_VM_NAME GATEWAY_PUBLIC_IP GATEWAY_PRIVATE_IP GATEWAY_CLIENT_ID \
  PREMIUM_NAMESPACE_NAME WORKLOAD_EVENTHUB_NAME WORKLOAD_CONSUMER_GROUP \
  CHECKPOINT_ACCOUNT_URL KEY_VAULT_NAME PRODUCER_CLIENT_ID CONSUMER_CLIENT_ID \
  VMSINGLE_PRIVATE_IP
assert_active_subscription
STATE="$(state_dir)"
NS=eventhubs-observability
AZURE_TENANT_ID="$(az account show --subscription "$AZURE_SUBSCRIPTION_ID" --query tenantId -o tsv)"
# Collector (default): the Collector pulls the Metrics API and the lag exporter into VictoriaMetrics.
# AzureMonitor: Grafana reads platform metrics from Azure Monitor directly. The Collector keeps only
# azureeventhubreceiver, which turns the Event Hubs resource logs (ConsumerLag, RuntimeAuditLogs) into
# metrics; the Metrics API receiver and the lag exporter do not run.
PLATFORM_METRICS="$(env_value PLATFORM_METRICS)"
PLATFORM_METRICS="${PLATFORM_METRICS:-Collector}"
[[ "$PLATFORM_METRICS" == "Collector" || "$PLATFORM_METRICS" == "AzureMonitor" ]] \
  || die "PLATFORM_METRICS must be Collector or AzureMonitor, got $PLATFORM_METRICS"
if [[ "$PLATFORM_METRICS" == "AzureMonitor" ]]; then
  [[ -n "$(env_value TELEMETRY_LOGS_EVENTHUB_NAME)" ]] \
    || die "PLATFORM_METRICS=AzureMonitor reads lag from resource logs; set EVENTHUBS_LOGS=Enabled and rerun azd provision"
  # The fallback exporter is another platform metrics copy; this mode promises logs and self metrics only.
  [[ "${ENABLE_FALLBACK_EXPORTER:-false}" != "true" ]] \
    || die "PLATFORM_METRICS=AzureMonitor does not collect platform metrics; unset ENABLE_FALLBACK_EXPORTER"
  ENABLE_API_RECEIVER=false
  ENABLE_LAG_RECEIVER=false
  LAG_EXPORTER_SCALE=0
  # A metrics Diagnostic Settings hub (EVENTHUBS_DIAGNOSTIC_METRICS=Enabled) stays deployed, but the
  # Collector does not read it in this mode.
  METRICS_HUB=""
else
  ENABLE_LAG_RECEIVER=true
  LAG_EXPORTER_SCALE=1
  METRICS_HUB="$(env_value TELEMETRY_EVENTHUB_NAME)"
fi

# The stamp is written only after a successful install, so a failed or outdated venv is rebuilt.
# Command substitution does not inherit errexit, hence the explicit || die.
python_env() {
  local stamp="$STATE/venv/.lab-requirements.txt"
  if ! cmp -s "$LAB_ROOT/agent/requirements.txt" "$stamp"; then
    rm -rf "$STATE/venv"
    python3 -m venv "$STATE/venv" >&2 || die "could not create the agent virtual environment"
    "$STATE/venv/bin/pip" install --quiet --requirement "$LAB_ROOT/agent/requirements.txt" >&2 \
      || die "could not install agent/requirements.txt"
    cp "$LAB_ROOT/agent/requirements.txt" "$stamp"
  fi
  printf '%s' "$STATE/venv/bin/python"
}

# GATEWAY_ONLY=true re-renders and restarts only the gateway bundle (for example to switch to the fallback exporter).
# It needs the AKS and VictoriaMetrics side that only a full run that reached its last health check proves.
COMPLETED_STAMP="$STATE/postprovision.completed"
if [[ "${GATEWAY_ONLY:-false}" != "true" ]]; then
rm -f "$COMPLETED_STAMP"
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
# The operator creates the VMAgent Deployment asynchronously; wait for it before rollout status.
for _ in $(seq 1 30); do
  kube get deploy/vmagent-lab -n "$NS" >/dev/null 2>&1 && break
  sleep 5
done
kube rollout status deploy/vmagent-lab -n "$NS" --timeout 300s
if [[ -n "$(env_value MANAGED_GRAFANA_NAME)" ]]; then
  "$LAB_ROOT/scripts/managed-grafana.sh" || die "could not connect Managed Grafana to VMSingle"
fi
else
  WORKLOAD_IMAGE="$(env_value WORKLOAD_IMAGE)"
  [[ -f "$COMPLETED_STAMP" && -n "$WORKLOAD_IMAGE" ]] || die "GATEWAY_ONLY requires a previous full postprovision run"
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
TELEMETRY_NAMESPACE=$(telemetry_namespace="$(env_value TELEMETRY_NAMESPACE_NAME)"; printf '%s' "${telemetry_namespace:+$telemetry_namespace.servicebus.windows.net}")
TELEMETRY_EVENTHUB_NAME=$METRICS_HUB
TELEMETRY_LOGS_EVENTHUB_NAME=$(env_value TELEMETRY_LOGS_EVENTHUB_NAME)
CHECKPOINT_ACCOUNT_URL=$CHECKPOINT_ACCOUNT_URL
GATEWAY_CLIENT_ID=$GATEWAY_CLIENT_ID
VMSINGLE_URL=http://$VMSINGLE_PRIVATE_IP:8428
EXISTING_DEDICATED_CLUSTER_RESOURCE_ID=$(dedicated_cluster_id)
ENABLE_API_RECEIVER=${ENABLE_API_RECEIVER:-true}
ENABLE_LAG_RECEIVER=$ENABLE_LAG_RECEIVER
ENABLE_FALLBACK_EXPORTER=${ENABLE_FALLBACK_EXPORTER:-false}
ENV
PY="$(python_env)"
"$PY" "$LAB_ROOT/gateway/render_collector.py" --env-file "$BUNDLE/collector.env" --output "$BUNDLE/collector.yaml"
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
AZURE_SUBSCRIPTION_ID=$AZURE_SUBSCRIPTION_ID
VMSINGLE_PRIVATE_IP=$VMSINGLE_PRIVATE_IP
LAG_EXPORTER_SCALE=$LAG_EXPORTER_SCALE
KEY_VAULT_NAME=$KEY_VAULT_NAME
ACR_NAME=$ACR_NAME
GATEWAY_PUBLIC_IP=$GATEWAY_PUBLIC_IP
COMPOSE_PROFILE=$([[ "${ENABLE_FALLBACK_EXPORTER:-false}" == "true" ]] && echo fallback || echo default)
ENV
# bsdtar pads -z output to its block size, so compress separately to keep the payload small.
BUNDLE_B64="$(COPYFILE_DISABLE=1 tar -C "$BUNDLE" -cf - . | gzip -9c | base64 | tr -d '\n')"
# Run Command splits unnamed values on '=', which base64 padding contains; always pass name=value.
gateway_run "$LAB_ROOT/gateway/bootstrap.sh" "BUNDLE_B64=$BUNDLE_B64" >"$STATE/gateway-bootstrap.log"
# Run Command succeeds even when the remote script fails; its own exit code line is the verdict.
grep -qx "GATEWAY_EXIT_CODE=0" "$STATE/gateway-bootstrap.log" && grep -q GATEWAY_READY "$STATE/gateway-bootstrap.log" \
  || die "gateway bootstrap failed; see $STATE/gateway-bootstrap.log"
sed -n '/GATEWAY_READY/,/GRAFANA_CERT_BEGIN/p' "$STATE/gateway-bootstrap.log" | grep -v GRAFANA_CERT_BEGIN >&2
sed -n '/GRAFANA_CERT_BEGIN/,/GRAFANA_CERT_END/p' "$STATE/gateway-bootstrap.log" | sed '1d;$d' >"$STATE/grafana.crt"
grep -q "BEGIN CERTIFICATE" "$STATE/grafana.crt" || die "gateway did not return the Grafana certificate"

log "6/6 operator-facing health checks"
curl -fsS --max-time 10 --cacert "$STATE/grafana.crt" "https://$GATEWAY_PUBLIC_IP:3000/api/health" >/dev/null \
  || die "Grafana is not reachable over pinned HTTPS from the operator egress IP"
[[ "${GATEWAY_ONLY:-false}" == "true" ]] || touch "$COMPLETED_STAMP"
log "postprovision completed."
