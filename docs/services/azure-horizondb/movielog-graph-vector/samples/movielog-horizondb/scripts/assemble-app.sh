#!/usr/bin/env bash
# Assembles the full MovieLog HorizonDB app source (default: out/app).
# The base is the MovieLog sample of the aks-spring-boot-micrometer-grafana topic; this sample keeps only
# the files it changes or adds (src/, build.gradle.kts, .env.sample) and copies them on top.
#   scripts/assemble-app.sh [output-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$(cd "$HERE/../../../../azure-monitor/aks-spring-boot-micrometer-grafana/samples/movielog-app" && pwd)"
OUT="${1:-$HERE/out/app}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"
SAMPLE="$(cd "$HERE" && pwd -P)"
BASE_REAL="$(cd "$BASE" && pwd -P)"
# OUT is wiped first, so it must not hold or sit inside the sources; inside this sample only out/ is allowed.
case "${OUT%/}/" in
  "$SAMPLE"/out/?*) ;;
  "$SAMPLE"/* | "$BASE_REAL"/*) echo "refusing to use $OUT as output: it is inside a source directory" >&2; exit 1 ;;
esac
for source in "$SAMPLE" "$BASE_REAL"; do
  case "$source/" in
    "${OUT%/}"/*) echo "refusing to use $OUT as output: it contains $source" >&2; exit 1 ;;
  esac
done

rm -rf "$OUT"
mkdir -p "$OUT"
# Base app: source, Gradle wrapper, Dockerfile and the agent init image.
# That topic's Copilot skill, dashboard, manifests, load generator and docs are not part of the app.
# Only committed files are copied, so a local .env, database files or build output of the base sample never
# reach the app source or the ACR build context.
if git -C "$BASE" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  (cd "$BASE" && git ls-files -z -- . ':(exclude).github' ':(exclude).vscode' ':(exclude)grafana' ':(exclude)k8s' \
      ':(exclude)loadgen' ':(exclude)README.md' ':(exclude)sample.yml' | tar --null -T - -cf -) | (cd "$OUT" && tar -xf -)
else
  (cd "$BASE" && tar -cf - \
    --exclude ./.github --exclude ./.vscode --exclude ./grafana --exclude ./k8s --exclude ./loadgen \
    --exclude ./README.md --exclude ./sample.yml --exclude ./build --exclude ./.gradle \
    --exclude './.env' --exclude './.env.*' --exclude '*.db' --exclude './data' .) | (cd "$OUT" && tar -xf -)
fi
# Overlay: changed and new files of this sample.
(cd "$HERE" && tar -cf - src build.gradle.kts .env.sample) | (cd "$OUT" && tar -xf -)
echo "assembled $OUT"
