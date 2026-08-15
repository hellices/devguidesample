#!/usr/bin/env bash
set -euo pipefail

# Prepares `app/.venv` with every package the lab's local Python tooling
# needs: the app's own runtime dependencies (`requirements.txt`, pulled in
# by `-r requirements.txt` at the top of `requirements-dev.txt`), Pillow for
# `render_capture.py`'s PNG/GIF rendering, and pytest/httpx for `app/tests`.
# `capture-scenario.sh` and `guides/05-results.md`'s notification step both
# run under this interpreter.
#
# `uv` is mandatory here, not merely preferred: this lab runs behind a
# corporate proxy that is configured for `uv` (its own index/proxy/keyring
# settings), and a bare `pip install` would bypass that configuration and
# resolve packages straight from the public PyPI -- exactly the network
# path the proxy exists to prevent. So there is no pip fallback: if `uv` is
# missing, this script fails with an actionable install pointer instead of
# silently reaching the public index.
#
# Idempotency matters because this script is the whole job of the
# `postprovision` hook (`azd-postprovision-local.sh`): the Container App
# image build and the image switch live in the deploy phase
# (`azd-deploy-app.sh`), behind its AcrPull gate. So a failure here is a
# purely local failure -- re-running this script directly is a complete
# fix, and `uv venv --allow-existing` plus `uv pip install` make that safe
# even when a previous attempt got partway through. What a failure here
# does mean is that `azd up` stopped before its deploy phase, so the
# application deployment still has to be finished with `azd deploy` --
# which every failure message below says.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SCRIPT_DIR
LAB_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd -P)"
readonly LAB_ROOT
readonly APP_DIR="${LAB_ROOT}/app"
readonly VENV_DIR="${APP_DIR}/.venv"
readonly VENV_PYTHON="${VENV_DIR}/bin/python"
readonly REQUIREMENTS_FILE="${APP_DIR}/requirements-dev.txt"
# `requirements.txt` pins `opentelemetry-instrumentation-fastapi~=0.64b0`,
# which requires Python>=3.10 (matching the app's own container image,
# `app/Dockerfile`: `python:3.12-slim`). Requesting a version range here --
# rather than one exact minor version -- lets `uv` pick any interpreter it
# already manages that clears that floor, while still protecting
# `--allow-existing` from silently reusing an older, incompatible
# interpreter left behind by a pre-uv `python3 -m venv` (uv recreates the
# venv in place when the existing interpreter doesn't satisfy the request).
readonly VENV_PYTHON_VERSION=">=3.10"
# What a failure here does and does not mean: `azd provision` has created
# the infrastructure and left the Container App on its public placeholder
# image, and the deploy phase -- the ACR build and the image switch -- has
# not run yet, because a failing `postprovision` hook stops `azd up`
# before it. Re-running this script fixes the local half; `azd deploy`
# still has to finish the cloud half. `cd` pins both commands to this
# lab's project directory regardless of the operator's shell.
readonly RERUN_HINT="Only the local Python environment failed: infrastructure from 'azd provision' is up, and the lab image is built and switched in separately by the deploy phase. Fix this step with: cd ${LAB_ROOT} && ./scripts/setup-venv.sh -- then finish the application deployment with: cd ${LAB_ROOT} && azd deploy"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to set up ${VENV_DIR} but was not found on PATH." >&2
  echo "This lab does not fall back to a bare 'pip install': install uv first (https://docs.astral.sh/uv/getting-started/installation/), configured for this network's proxy, then re-run." >&2
  echo "${RERUN_HINT}" >&2
  exit 1
fi

if ! UV_VENV_OUTPUT="$(uv venv --python "${VENV_PYTHON_VERSION}" --allow-existing "${VENV_DIR}" 2>&1)"; then
  printf '%s\n' "${UV_VENV_OUTPUT}" >&2
  echo "Failed to create the virtual environment at ${VENV_DIR}." >&2
  if grep -qi "no interpreter found" <<<"${UV_VENV_OUTPUT}"; then
    # uv's own message ("No interpreter found for Python >=3.10 ...") means
    # no installed Python clears the floor yet -- not a proxy or install
    # failure -- so the fix is installing one, and `uv python install` is
    # the one installer that reuses this network's corporate proxy/mirror
    # already configured for `uv`; a public `pip`/`pip install` bypasses
    # that configuration entirely and must never be suggested here.
    echo "No installed Python satisfies ${VENV_PYTHON_VERSION} yet. Install one through uv itself -- it uses the corporate proxy/mirror already configured for uv, not the public PyPI index: uv python install 3.12" >&2
  fi
  echo "${RERUN_HINT}" >&2
  exit 1
fi
printf '%s\n' "${UV_VENV_OUTPUT}"

if ! uv pip install --python "${VENV_PYTHON}" -r "${REQUIREMENTS_FILE}"; then
  echo "Failed to install ${REQUIREMENTS_FILE} into ${VENV_DIR}." >&2
  echo "A misconfigured or unreachable corporate proxy is the most common cause of a uv install failure here." >&2
  echo "${RERUN_HINT}" >&2
  exit 1
fi

if ! "${VENV_PYTHON}" -c "import PIL" >/dev/null 2>&1; then
  echo "${REQUIREMENTS_FILE} installed, but Pillow (PIL) is still not importable from ${VENV_PYTHON}." >&2
  echo "${RERUN_HINT}" >&2
  exit 1
fi

echo "Python environment ready: ${VENV_PYTHON} (${REQUIREMENTS_FILE} installed, Pillow importable)."
