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
# Idempotency matters because this script is invoked from the `postprovision`
# hook *before* that hook's ACR build and Container App update -- see
# `azd-postprovision.sh` -- so a failure here happens before the cloud app
# deployment for this run has even started, not after it. Re-running only
# this script would leave that deployment never attempted, so every failure
# message below points at re-running the *whole* hook (`azd hooks run
# postprovision`), never at running this script directly -- and `uv venv
# --allow-existing` plus `uv pip install` make that safe to re-run even when
# a previous attempt got partway through. (Running this script directly is
# still the right move for a purely local `app/.venv` problem noticed well
# after a deployment already succeeded -- see `doctor.sh` and
# `capture-scenario.sh`'s own remediation text -- just never as the response
# to a failure reported by *this* script.)

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
# Cloud resources from `azd provision` are already deployed by the time this
# hook (and so this script) runs, but this hook's own ACR build and Container
# App update -- the cloud *app* deployment -- run after this script, not
# before it, so a failure here must not be answered by re-running only this
# script: that would leave the app deployment never attempted. `cd` pins the
# rerun to this lab's project directory regardless of the operator's shell.
readonly RERUN_HINT="Cloud infrastructure from 'azd provision' is already deployed, but this hook's Container App image build and deployment run *after* this step and have not happened yet -- re-running only this script would silently skip them. Re-run the whole hook instead: cd ${LAB_ROOT} && azd hooks run postprovision"

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
