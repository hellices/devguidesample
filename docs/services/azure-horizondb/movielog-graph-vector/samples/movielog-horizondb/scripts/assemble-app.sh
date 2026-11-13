#!/usr/bin/env bash
# Assembles the full MovieLog HorizonDB app source (default: out/app).
# The base is the MovieLog sample of the aks-spring-boot-micrometer-grafana topic; this sample keeps only
# the files it changes or adds (src/, build.gradle.kts, .env.sample) and copies them on top.
#   scripts/assemble-app.sh [output-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$(cd "$HERE/../../../../azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app" && pwd)"
OUT="${1:-$HERE/out/app}"

rm -rf "$OUT"
mkdir -p "$OUT"
# Base app: source, Gradle wrapper, Dockerfile and the agent init image.
# That topic's Copilot skill, dashboard, manifests, load generator and docs are not part of the app.
(cd "$BASE" && tar -cf - \
  --exclude ./.github --exclude ./.vscode --exclude ./grafana --exclude ./k8s --exclude ./loadgen \
  --exclude ./README.md --exclude ./sample.yml --exclude ./build --exclude ./.gradle .) | (cd "$OUT" && tar -xf -)
# Overlay: changed and new files of this sample.
(cd "$HERE" && tar -cf - src build.gradle.kts .env.sample) | (cd "$OUT" && tar -xf -)
echo "assembled $OUT"
