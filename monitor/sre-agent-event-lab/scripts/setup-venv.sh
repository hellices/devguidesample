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
# hook, which runs after `azd provision` has already created every cloud
# resource: by the time this step can fail, the Azure spend for this run has
# already started. So every failure message below states the exact command
# to re-run -- re-running never repeats the (already-succeeded) cloud
# provisioning, only this local step -- and `uv venv --allow-existing` plus
# `uv pip install` make re-running safe even when a previous attempt got
# partway through.

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
readonly RERUN_HINT="Cloud resources from 'azd provision' are already deployed; only this local step needs to be retried. Re-run: azd hooks run postprovision (or directly: ./scripts/setup-venv.sh)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to set up ${VENV_DIR} but was not found on PATH." >&2
  echo "This lab does not fall back to a bare 'pip install': install uv first (https://docs.astral.sh/uv/getting-started/installation/), configured for this network's proxy, then re-run." >&2
  echo "${RERUN_HINT}" >&2
  exit 1
fi

if ! uv venv --python "${VENV_PYTHON_VERSION}" --allow-existing "${VENV_DIR}"; then
  echo "Failed to create the virtual environment at ${VENV_DIR}." >&2
  echo "${RERUN_HINT}" >&2
  exit 1
fi

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
