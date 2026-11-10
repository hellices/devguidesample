#!/usr/bin/env bash
# Connects the optional Azure Managed Grafana (MANAGED_GRAFANA=Enabled) to the private VMSingle:
# Private Link Service on the AKS internal load balancer -> managed private endpoint -> data source.
# Called by azd-postprovision.sh; safe to rerun.
if [ -z "${BASH_VERSION:-}" ]; then exec bash "$0" "$@"; fi
source "$(dirname "$0")/lib.sh"

require_commands az kubectl
load_env AZURE_SUBSCRIPTION_ID AZURE_ENV_NAME AZURE_RESOURCE_GROUP AKS_CLUSTER_NAME MANAGED_GRAFANA_NAME
NS=eventhubs-observability
PLS_NAME="pls-vmsingle-lab"
MPE_NAME="mpe-vmsingle"
# Managed Grafana resolves this name to the managed private endpoint; it never leaves Grafana.
VMSINGLE_DOMAIN="vmsingle.eventhubs-lab.internal"
REQUEST_MESSAGE="eventhubs-lab ${AZURE_ENV_NAME} managed grafana"

# Pinned: amg 3.x renamed `az grafana mpe` to `az grafana managed-private-endpoint`.
AMG_EXTENSION_VERSION=3.1.1
az extension add --name amg --version "$AMG_EXTENSION_VERSION" --upgrade --only-show-errors >/dev/null \
  || die "could not install the amg Azure CLI extension $AMG_EXTENSION_VERSION"

log "Managed Grafana: Private Link Service for VMSingle"
sed -e "s|__PLS_NAME__|$PLS_NAME|g" "$LAB_ROOT/k8s/vmsingle-pls.yaml" | kube apply -f - >/dev/null
NODE_RG="$(az aks show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$AKS_CLUSTER_NAME" --query nodeResourceGroup -o tsv)" \
  || die "could not read the AKS node resource group"
PLS_ID=""
for _ in $(seq 1 60); do
  PLS_ID="$(az network private-link-service show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$NODE_RG" -n "$PLS_NAME" --query id -o tsv 2>/dev/null || true)"
  [[ -n "$PLS_ID" ]] && break
  sleep 10
done
[[ -n "$PLS_ID" ]] || die "the AKS cloud provider did not create Private Link Service $PLS_NAME"
PLS_LOCATION="$(az network private-link-service show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$NODE_RG" -n "$PLS_NAME" --query location -o tsv)"

log "Managed Grafana: managed private endpoint"
az grafana managed-private-endpoint create --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" --workspace-name "$MANAGED_GRAFANA_NAME" -n "$MPE_NAME" \
  --private-link-resource-id "$PLS_ID" --private-link-resource-region "$PLS_LOCATION" \
  --private-link-service-url "$VMSINGLE_DOMAIN" --request-message "$REQUEST_MESSAGE" -o none \
  || die "could not create managed private endpoint $MPE_NAME"
# The Private Link Service accepts requests from any subscription (Managed Grafana runs in its own),
# so approve only the pending connection that carries this environment's request message.
approved=false
for _ in $(seq 1 30); do
  pending="$(az network private-link-service show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$NODE_RG" -n "$PLS_NAME" \
    --query "privateEndpointConnections[?privateLinkServiceConnectionState.status=='Pending' && privateLinkServiceConnectionState.description=='$REQUEST_MESSAGE'].name" -o tsv)" \
    || die "could not list Private Link Service connections"
  for connection in $pending; do
    az network private-link-service connection update --subscription "$AZURE_SUBSCRIPTION_ID" -g "$NODE_RG" --service-name "$PLS_NAME" \
      -n "$connection" --connection-status Approved --description "approved by azd postprovision" -o none \
      || die "could not approve $connection"
  done
  state="$(az grafana managed-private-endpoint refresh --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" --workspace-name "$MANAGED_GRAFANA_NAME" -o none 2>/dev/null; \
    az grafana managed-private-endpoint show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" --workspace-name "$MANAGED_GRAFANA_NAME" -n "$MPE_NAME" \
      --query connectionState.status -o tsv 2>/dev/null || true)"
  if [[ "$state" == "Approved" ]]; then approved=true; break; fi
  sleep 10
done
[[ "$approved" == "true" ]] || die "managed private endpoint $MPE_NAME was not approved (state=$state)"

log "Managed Grafana: Grafana Admin for the deployer"
GRAFANA_ID="$(az grafana show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$MANAGED_GRAFANA_NAME" --query id -o tsv)" \
  || die "could not read $MANAGED_GRAFANA_NAME"
DEPLOYER_ID="$(env_value AZURE_PRINCIPAL_ID)"
DEPLOYER_TYPE="$(env_value AZURE_PRINCIPAL_TYPE)"
[[ -n "$DEPLOYER_ID" ]] || die "AZURE_PRINCIPAL_ID is not set; rerun azd provision so preprovision records it"
assigned="$(az role assignment list --subscription "$AZURE_SUBSCRIPTION_ID" --assignee "$DEPLOYER_ID" --role "Grafana Admin" \
  --scope "$GRAFANA_ID" --query "length(@)" -o tsv)" || die "could not list Grafana role assignments"
if [[ "$assigned" == "0" ]]; then
  az role assignment create --subscription "$AZURE_SUBSCRIPTION_ID" --assignee-object-id "$DEPLOYER_ID" \
    --assignee-principal-type "${DEPLOYER_TYPE:-User}" --role "Grafana Admin" --scope "$GRAFANA_ID" -o none \
    || die "could not grant Grafana Admin on $MANAGED_GRAFANA_NAME"
fi

log "Managed Grafana: VictoriaMetrics data source"
# Same uid as the Gateway Grafana, so the agent dashboard works unchanged in both.
DATA_SOURCE="$(python3 -c 'import json,sys; print(json.dumps({"name": "VictoriaMetrics", "type": "prometheus", "uid": "victoriametrics", "access": "proxy", "url": f"http://{sys.argv[1]}:8428", "isDefault": True, "jsonData": {"httpMethod": "POST", "timeInterval": "30s"}}))' "$VMSINGLE_DOMAIN")"
# Grafana Admin can take a few minutes to propagate after provisioning.
for attempt in $(seq 1 18); do
  if az grafana data-source show --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$MANAGED_GRAFANA_NAME" \
      --data-source victoriametrics -o none 2>/dev/null; then
    az grafana data-source update --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$MANAGED_GRAFANA_NAME" \
      --data-source victoriametrics --definition "$DATA_SOURCE" -o none && break
  elif az grafana data-source create --subscription "$AZURE_SUBSCRIPTION_ID" -g "$AZURE_RESOURCE_GROUP" -n "$MANAGED_GRAFANA_NAME" \
      --definition "$DATA_SOURCE" -o none; then
    break
  fi
  [[ "$attempt" -lt 18 ]] || die "could not create the VictoriaMetrics data source in $MANAGED_GRAFANA_NAME"
  sleep 20
done
log "Managed Grafana ready: $(env_value MANAGED_GRAFANA_ENDPOINT) (data source http://$VMSINGLE_DOMAIN:8428)"
