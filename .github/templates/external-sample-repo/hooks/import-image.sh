#!/usr/bin/env bash
# azd hook: copy the released image from GHCR into the lab's Azure Container Registry by digest, so the cluster pulls
# from ACR and no local Docker is needed. Needs the "Container Registry Data Importer and Data Reader" role on the
# registry. IMAGE is the sample.yml image value (ghcr.io/<owner>/<name>:<tag>@sha256:<digest>). No credentials are
# passed, so the GHCR package must allow anonymous pulls (public).
set -euo pipefail
: "${AZURE_CONTAINER_REGISTRY_NAME:?set by azd from the Bicep output}"
: "${IMAGE:?ghcr.io/<owner>/<name>:<tag>@sha256:<digest>}"
repository="${IMAGE#ghcr.io/*/}"
repository="${repository%%[:@]*}"
tag="${IMAGE#*:}"
tag="${tag%%@*}"
az acr import --name "$AZURE_CONTAINER_REGISTRY_NAME" --source "${IMAGE%%:*}@${IMAGE#*@}" \
  --image "${repository}:${tag}" --force
