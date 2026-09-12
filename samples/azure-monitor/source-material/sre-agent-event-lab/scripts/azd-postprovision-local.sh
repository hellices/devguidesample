#!/usr/bin/env bash
set -euo pipefail

# `postprovision` hook: the local half of the lab's two-phase deployment.
#
# Provisioning creates the registry, the workload identity, its `AcrPull`
# assignment and a Container App still running the *public placeholder*
# image -- the lab image does not exist yet, and the identity's `AcrPull`
# grant is not necessarily usable the instant the ARM deployment returns.
# Building and switching the image therefore belongs to the deploy phase
# (`scripts/azd-deploy-app.sh`, run by `azd deploy` and by `azd up`'s
# deploy phase), which waits for that grant before it touches anything.
#
# So this hook does exactly one thing: make the local Python environment
# ready, on the one step of the documented `azd up` flow that always runs
# right after provisioning succeeds. It makes no Azure calls at all, which
# is what keeps `azd provision` on the placeholder image.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR

# `setup-venv.sh` is its own idempotent script (uv-only, no pip fallback)
# so it can be re-run by hand -- see its own actionable error output --
# without repeating anything else.
"${SCRIPT_DIR}/setup-venv.sh"

cat <<'NEXT'

Provisioning finished and the local Python environment is ready.
The Container App is still running the public placeholder image: the lab
image is built in ACR and switched in during the deploy phase, once the
workload identity's AcrPull grant is visible at the registry.

Next: `azd deploy` (or `azd up`, which continues into the same phase).
NEXT
