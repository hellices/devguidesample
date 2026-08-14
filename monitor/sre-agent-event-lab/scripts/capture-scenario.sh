#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

if [[ "$#" -lt 1 || "$#" -gt 2 ]] || [[ ! "$1" =~ ^s[123]$ ]]; then
  echo "Usage: $0 s1|s2|s3 [EVIDENCE_DIR]" >&2
  exit 2
fi

readonly SCENARIO="$1"
readonly EXPLICIT_EVIDENCE_DIR="${2:-}"
readonly ASSET_DIR="${LAB_ROOT}/assets/captures/${SCENARIO}"
readonly PYTHON="${LAB_ROOT}/app/.venv/bin/python"

require_lab_config
verify_subscription
verify_lab_resource_group

# The public command is `lab.sh capture s1`, with no timestamped path: the
# directory this scenario's run recorded in `evidence/state.json` is the
# only one whose timeline belongs to the alert being captured. An explicit
# directory still wins, so an operator can re-render an older run.
if [[ -n "${EXPLICIT_EVIDENCE_DIR}" ]]; then
  EVIDENCE_DIR="${EXPLICIT_EVIDENCE_DIR}"
elif ! EVIDENCE_DIR="$(lab_state evidence-dir "${SCENARIO}")"; then
  exit 1
fi
readonly EVIDENCE_DIR
readonly TIMELINE_FILE="${EVIDENCE_DIR}/timeline.json"
readonly NORMALIZED_FILE="${EVIDENCE_DIR}/normalized-timeline.json"

if [[ ! -f "${AGENT_SETUP_FILE}" ]]; then
  echo "Missing Agent setup evidence: ${AGENT_SETUP_FILE}" >&2
  exit 1
fi
if [[ ! -f "${TIMELINE_FILE}" ]]; then
  echo "Missing scenario timeline: ${TIMELINE_FILE}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON}" ]]; then
  echo "Missing Python environment: ${PYTHON}" >&2
  echo "Cloud resources are already deployed; only this local step needs to be retried. Re-run: ./scripts/setup-venv.sh" >&2
  exit 1
fi
if ! "${PYTHON}" -c "import PIL" >/dev/null 2>&1; then
  echo "Python environment at ${PYTHON} is missing Pillow (PIL), which render_capture.py needs." >&2
  echo "Cloud resources are already deployed; only this local step needs to be retried. Re-run: ./scripts/setup-venv.sh" >&2
  exit 1
fi

AGENT_ENDPOINT="$(jq -r '.agent_endpoint // empty' "${AGENT_SETUP_FILE}")"
ALERT_ID="$(jq -r '.alert_id // empty' "${TIMELINE_FILE}")"
if [[ -z "${AGENT_ENDPOINT}" || -z "${ALERT_ID}" ]]; then
  echo "Agent endpoint or alert ID is missing from evidence." >&2
  exit 1
fi
readonly AGENT_ENDPOINT ALERT_ID

set +e
"${PYTHON}" "${SCRIPT_DIR}/capture_agent.py" \
  --scenario "${SCENARIO}" \
  --alert-id "${ALERT_ID}" \
  --endpoint "${AGENT_ENDPOINT}" \
  --output-dir "${EVIDENCE_DIR}" \
  --timeout 1200 \
  --interval 15
capture_status="$?"
set -e
if [[ "${capture_status}" -ne 0 && "${capture_status}" -ne 3 ]]; then
  echo "Evidence collection failed with status ${capture_status}." >&2
  exit "${capture_status}"
fi

# Recorded before any further check can abort the script: the terminal
# state of the normalized timeline is the honest outcome of this capture,
# including `thread-not-created`, `investigation-missing` and
# `conclusion-missing`. Only a real `conclusion` counts as a successful
# capture and unblocks the next scenario.
CAPTURE_STATE="$(lab_state record-capture "${SCENARIO}" \
  --timeline "${NORMALIZED_FILE}" \
  --evidence-dir "${EVIDENCE_DIR}")"
readonly CAPTURE_STATE

event_count="$(jq 'length' "${NORMALIZED_FILE}")"
if (( event_count < 4 )); then
  echo "Capture has fewer than four explicit states: ${event_count}" >&2
  exit 1
fi

mkdir -p "${ASSET_DIR}"
find "${ASSET_DIR}" -maxdepth 1 -type f \
  \( -name '*.png' -o -name 'investigation.gif' -o -name 'timeline.mmd' \
  -o -name 'timeline.md' \) -delete

"${PYTHON}" "${SCRIPT_DIR}/render_capture.py" \
  "${NORMALIZED_FILE}" \
  "${ASSET_DIR}" \
  --scenario "${SCENARIO}"

echo "Raw evidence: ${EVIDENCE_DIR}"
echo "Rendered capture: ${ASSET_DIR}/investigation.gif"
echo "Capture status: ${CAPTURE_STATE}"
if [[ "${CAPTURE_STATE}" != "conclusion" ]]; then
  echo "The Agent produced no conclusion for ${SCENARIO} (${CAPTURE_STATE})."
  echo "Recorded as-is; the next scenario stays blocked until a capture ends in a conclusion."
fi
if [[ "${capture_status}" -eq 3 ]]; then
  echo "Capture ended at the deadline; missing states are explicit in the output."
fi
