#!/bin/bash
# Azure Load Testing + Locust: Full private infrastructure deployment
#
# Architecture (cross-region, fully private):
#   [Japan East]                         [Korea Central]
#   VNet-ALT (10.1.0.0/16)  ←peering→   VNet-Infra (10.0.0.0/16)
#     └─ snet-loadtest                    ├─ snet-appgw  (Private AppGW)
#        (ALT engine injection)           └─ snet-aks    (AKS nodes)
#
# Prerequisites: az cli (2.60+), az load extension, kubectl

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ========== Configuration ==========
RESOURCE_GROUP="rg-loadtest-sample"

# Infra region (AppGW + AKS)
INFRA_LOCATION="koreacentral"
VNET_INFRA_NAME="vnet-infra"
VNET_INFRA_CIDR="10.0.0.0/16"
SUBNET_APPGW_NAME="snet-appgw"
SUBNET_APPGW_CIDR="10.0.1.0/24"
SUBNET_AKS_NAME="snet-aks"
SUBNET_AKS_CIDR="10.0.4.0/22"

# ALT region (Azure Load Testing)
ALT_LOCATION="japaneast"
VNET_ALT_NAME="vnet-alt"
VNET_ALT_CIDR="10.1.0.0/16"
SUBNET_ALT_NAME="snet-loadtest"
SUBNET_ALT_CIDR="10.1.0.0/24"

# Resources
AKS_NAME="aks-loadtest"
APPGW_NAME="appgw-loadtest"
ALT_NAME="alt-loadtest"
TEST_ID="appgw-aks-locust"

# AppGW private frontend IP (within snet-appgw range)
APPGW_PRIVATE_IP="10.0.1.10"

# ========== Extensions & Provider Registration ==========
echo "▶ Installing extensions and registering providers..."
az extension add --name load --upgrade 2>/dev/null || true
az provider register --namespace Microsoft.Batch -o none 2>/dev/null || true

# ========== Resource Group ==========
echo "▶ Creating resource group: $RESOURCE_GROUP ($INFRA_LOCATION)"
az group create --name "$RESOURCE_GROUP" --location "$INFRA_LOCATION" -o none

# ==========================================================
# Phase 1: VNets + Subnets (both regions)
# ==========================================================
echo ""
echo "═══ Phase 1: Network Infrastructure ═══"

# Infra VNet (koreacentral)
echo "▶ Creating VNet: $VNET_INFRA_NAME ($VNET_INFRA_CIDR) in $INFRA_LOCATION"
az network vnet create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VNET_INFRA_NAME" \
  --address-prefix "$VNET_INFRA_CIDR" \
  --location "$INFRA_LOCATION" \
  -o none

az network vnet subnet create \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_INFRA_NAME" \
  --name "$SUBNET_APPGW_NAME" \
  --address-prefix "$SUBNET_APPGW_CIDR" \
  -o none

az network vnet subnet create \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_INFRA_NAME" \
  --name "$SUBNET_AKS_NAME" \
  --address-prefix "$SUBNET_AKS_CIDR" \
  -o none

# ALT VNet (japaneast)
echo "▶ Creating VNet: $VNET_ALT_NAME ($VNET_ALT_CIDR) in $ALT_LOCATION"
az network vnet create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VNET_ALT_NAME" \
  --address-prefix "$VNET_ALT_CIDR" \
  --location "$ALT_LOCATION" \
  -o none

az network vnet subnet create \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_ALT_NAME" \
  --name "$SUBNET_ALT_NAME" \
  --address-prefix "$SUBNET_ALT_CIDR" \
  -o none

echo "✓ VNets and subnets created (2 regions)"

# ==========================================================
# Phase 2: VNet Peering (cross-region)
# ==========================================================
echo ""
echo "═══ Phase 2: VNet Peering ═══"

VNET_INFRA_ID=$(az network vnet show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VNET_INFRA_NAME" \
  --query id -o tsv)

VNET_ALT_ID=$(az network vnet show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VNET_ALT_NAME" \
  --query id -o tsv)

echo "▶ Peering: $VNET_INFRA_NAME → $VNET_ALT_NAME"
az network vnet peering create \
  --resource-group "$RESOURCE_GROUP" \
  --name "peer-infra-to-alt" \
  --vnet-name "$VNET_INFRA_NAME" \
  --remote-vnet "$VNET_ALT_ID" \
  --allow-vnet-access \
  -o none

echo "▶ Peering: $VNET_ALT_NAME → $VNET_INFRA_NAME"
az network vnet peering create \
  --resource-group "$RESOURCE_GROUP" \
  --name "peer-alt-to-infra" \
  --vnet-name "$VNET_ALT_NAME" \
  --remote-vnet "$VNET_INFRA_ID" \
  --allow-vnet-access \
  -o none

echo "✓ VNet peering established (koreacentral ↔ japaneast)"

# ==========================================================
# Phase 3: AKS with AGIC (private AppGW)
# ==========================================================
echo ""
echo "═══ Phase 3: AKS + Private AppGW (AGIC) ═══"

AKS_SUBNET_ID=$(az network vnet subnet show \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_INFRA_NAME" \
  --name "$SUBNET_AKS_NAME" \
  --query id -o tsv)

APPGW_SUBNET_ID=$(az network vnet subnet show \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_INFRA_NAME" \
  --name "$SUBNET_APPGW_NAME" \
  --query id -o tsv)

echo "▶ Creating AKS cluster: $AKS_NAME (this takes ~5 min)"
az aks create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --location "$INFRA_LOCATION" \
  --node-count 2 \
  --node-vm-size standard_b4ms \
  --network-plugin azure \
  --vnet-subnet-id "$AKS_SUBNET_ID" \
  --service-cidr 172.16.0.0/16 \
  --dns-service-ip 172.16.0.10 \
  --enable-managed-identity \
  --enable-addons ingress-appgw \
  --appgw-name "$APPGW_NAME" \
  --appgw-subnet-id "$APPGW_SUBNET_ID" \
  --generate-ssh-keys \
  -o none

echo "✓ AKS cluster created with AGIC addon"

# Grant AGIC identity Network Contributor on VNet (required for cross-RG subnet)
AGIC_OBJECT_ID=$(az aks show -g "$RESOURCE_GROUP" -n "$AKS_NAME" \
  --query "addonProfiles.ingressApplicationGateway.identity.objectId" -o tsv)

az role assignment create \
  --assignee-object-id "$AGIC_OBJECT_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Network Contributor" \
  --scope "$VNET_INFRA_ID" \
  -o none

echo "✓ AGIC identity granted Network Contributor on VNet"

# Wait for AGIC to create AppGW (restart pod to pick up new permissions)
echo "▶ Restarting AGIC pod and waiting for AppGW creation..."
kubectl delete pod -n kube-system -l app=ingress-appgw 2>/dev/null || true

# Get the node resource group where AppGW lives
NODE_RG=$(az aks show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --query nodeResourceGroup -o tsv)

# Wait for AppGW to reach Succeeded state
for i in $(seq 1 60); do
  state=$(az network application-gateway show \
    -g "$NODE_RG" -n "$APPGW_NAME" \
    --query provisioningState -o tsv 2>/dev/null || echo "NotFound")
  if [[ "$state" == "Succeeded" ]]; then
    echo "✓ AppGW ready (attempt $i)"
    break
  fi
  echo "  [$i] AppGW: $state"
  sleep 10
done

# Configure AppGW private frontend IP
echo "▶ Configuring AppGW private frontend..."

# Add private frontend IP to AppGW
az network application-gateway frontend-ip create \
  --resource-group "$NODE_RG" \
  --gateway-name "$APPGW_NAME" \
  --name "appGwPrivateFrontendIp" \
  --private-ip-address "$APPGW_PRIVATE_IP" \
  --subnet "$APPGW_SUBNET_ID" \
  -o none

echo "✓ AppGW private frontend IP: $APPGW_PRIVATE_IP"

# ========== Get AKS Credentials ==========
az aks get-credentials \
  --resource-group "$RESOURCE_GROUP" \
  --name "$AKS_NAME" \
  --overwrite-existing

# ========== Deploy Backend App to AKS ==========
echo "▶ Deploying backend app to AKS..."
kubectl apply -f "$SCRIPT_DIR/../k8s/deployment.yaml"
kubectl rollout status deployment/backend-app --timeout=120s

echo "✓ Backend app deployed (Ingress uses private AppGW IP)"

# ==========================================================
# Phase 4: Azure Load Testing (japaneast, VNet injection)
# ==========================================================
echo ""
echo "═══ Phase 4: Azure Load Testing ═══"

echo "▶ Creating Azure Load Testing resource: $ALT_NAME ($ALT_LOCATION)"
az load create \
  --name "$ALT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$ALT_LOCATION" \
  -o none

ALT_SUBNET_ID=$(az network vnet subnet show \
  --resource-group "$RESOURCE_GROUP" \
  --vnet-name "$VNET_ALT_NAME" \
  --name "$SUBNET_ALT_NAME" \
  --query id -o tsv)

echo "▶ Creating Locust test with VNet injection: $TEST_ID"
az load test create \
  --load-test-resource "$ALT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --test-id "$TEST_ID" \
  --test-type Locust \
  --test-plan locustfile.py \
  --engine-instances 4 \
  --subnet-id "$ALT_SUBNET_ID" \
  -o none

# Upload test files
az load test file upload \
  --load-test-resource "$ALT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --test-id "$TEST_ID" \
  --path "$SCRIPT_DIR/locustfile.py" \
  -o none

az load test file upload \
  --load-test-resource "$ALT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --test-id "$TEST_ID" \
  --path "$SCRIPT_DIR/requirements.txt" \
  --file-type ADDITIONAL_ARTIFACTS \
  -o none

echo "✓ Test created with VNet injection (japaneast → peering → koreacentral)"

# ==========================================================
# Phase 5: Run Test
# ==========================================================
echo ""
echo "═══ Phase 5: Execute Load Test ═══"

RUN_ID="run-$(date +%Y%m%d-%H%M%S)"
echo "▶ Starting test run: $RUN_ID"
echo "  Target: http://$APPGW_PRIVATE_IP (private AppGW via VNet peering)"

az load test-run create \
  --load-test-resource "$ALT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --test-id "$TEST_ID" \
  --test-run-id "$RUN_ID" \
  --env TARGET_HOST="http://$APPGW_PRIVATE_IP" USERS=100 SPAWN_RATE=10 RUN_TIME=3m \
  -o none

echo "✓ Test run started: $RUN_ID"

echo ""
echo "=========================================="
echo " Deployment Complete (Private Architecture)"
echo "=========================================="
echo ""
echo " ┌─────────────────────────────────────────────────────────┐"
echo " │ Japan East              │ Korea Central                  │"
echo " │                         │                                │"
echo " │ ALT (Locust engines)    │  AppGW (private: $APPGW_PRIVATE_IP) │"
echo " │   └─ snet-loadtest      │    └─ AKS (backend pods)      │"
echo " │      10.1.0.0/24        │       10.0.2.0/22              │"
echo " │                         │                                │"
echo " │   VNet: 10.1.0.0/16 ←──peering──→ VNet: 10.0.0.0/16    │"
echo " └─────────────────────────────────────────────────────────┘"
echo ""
echo " Resource Group : $RESOURCE_GROUP"
echo " AKS            : $AKS_NAME ($INFRA_LOCATION)"
echo " AppGW (private): $APPGW_PRIVATE_IP ($INFRA_LOCATION)"
echo " Load Testing   : $ALT_NAME ($ALT_LOCATION)"
echo " Test ID        : $TEST_ID"
echo " Test Run       : $RUN_ID"
echo ""
echo " View results: Azure Portal → Load Testing → $ALT_NAME → Test runs"
echo "=========================================="
