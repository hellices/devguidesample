#!/usr/bin/env bash
# First-time GCP Workload Identity Federation (WIF) setup for the private
# Vertex AI broker described in ../third-party-model-integration.md (section
# 5). This script only prepares the GCP-side trust between Microsoft Entra ID
# and a Google Cloud project; it does not touch APIM, Key Vault, or any Azure
# resource, and it contains no credentials, API keys, or service-account key
# material.
#
# Design recommendation: this script is an idempotency-unsafe, first-time
# bootstrap template. `gcloud iam workload-identity-pools create` and
# `gcloud iam workload-identity-pools providers create-oidc` fail if the pool
# or provider already exists. For repeated or automated deployments, manage
# these resources through the organization's GCP IaC tool (for example
# Terraform google_iam_workload_identity_pool /
# google_iam_workload_identity_pool_provider resources) instead of re-running
# this script, or wrap each gcloud call with an existence check.
#
# Documented fact: the OIDC issuer/audience/attribute-mapping values below
# follow Google's "Workload identity federation with other clouds" guidance
# for a Microsoft Entra ID (Azure AD) identity provider:
# https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds
set -euo pipefail

# --- Required inputs (fail fast, before any gcloud call) -------------------
: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_PROJECT_NUMBER:?Set GCP_PROJECT_NUMBER}"
: "${GCP_WIF_POOL_ID:?Set GCP_WIF_POOL_ID}"
: "${GCP_WIF_PROVIDER_ID:?Set GCP_WIF_PROVIDER_ID}"
: "${ENTRA_TENANT_ID:?Set ENTRA_TENANT_ID}"
: "${ENTRA_APPLICATION_ID_URI:?Set ENTRA_APPLICATION_ID_URI}"
: "${VERTEX_BROKER_PRINCIPAL_OBJECT_ID:?Set VERTEX_BROKER_PRINCIPAL_OBJECT_ID}"

# Fail fast if the gcloud CLI itself is not available, before attempting any
# gcloud invocation below.
if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI not found on PATH. Install the Google Cloud SDK before running this script." >&2
  exit 1
fi

# --- 1. Enable the GCP APIs the broker and WIF trust require ---------------
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  aiplatform.googleapis.com \
  --project "$GCP_PROJECT_ID"

# --- 2. Create the Workload Identity Pool -----------------------------------
gcloud iam workload-identity-pools create "$GCP_WIF_POOL_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global \
  --display-name "Azure Vertex broker"

# --- 3. Create the OIDC provider trusting the broker's Entra managed identity
#
# Documented fact (Google WIF with Microsoft Entra ID):
#   issuer-uri        = https://sts.windows.net/$ENTRA_TENANT_ID
#   allowed-audiences = the broker's Entra application ID URI
#   attribute-mapping = google.subject=assertion.sub (the Entra token's
#                       "sub" claim becomes the WIF principal subject)
gcloud iam workload-identity-pools providers create-oidc "$GCP_WIF_PROVIDER_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global \
  --workload-identity-pool "$GCP_WIF_POOL_ID" \
  --issuer-uri "https://sts.windows.net/$ENTRA_TENANT_ID" \
  --allowed-audiences "$ENTRA_APPLICATION_ID_URI" \
  --attribute-mapping "google.subject=assertion.sub"

# --- 4. Grant the broker's Entra managed-identity principal Vertex AI access
#
# Design recommendation: roles/aiplatform.user is the minimum predefined role
# that allows calling Vertex AI prediction/generation endpoints. Review
# against the organization's least-privilege policy before granting it in a
# shared project.
gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
  --member "principal://iam.googleapis.com/projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/$GCP_WIF_POOL_ID/subject/$VERTEX_BROKER_PRINCIPAL_OBJECT_ID" \
  --role roles/aiplatform.user

echo "GCP WIF pool '$GCP_WIF_POOL_ID' and provider '$GCP_WIF_PROVIDER_ID' configured for project $GCP_PROJECT_ID."
echo "Re-running this script against an existing pool/provider will fail; use the organization's GCP IaC for repeated deployments."
