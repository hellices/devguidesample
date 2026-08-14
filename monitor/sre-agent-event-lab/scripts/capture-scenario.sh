#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

if [[ "$#" -ne 2 ]] || [[ ! "$1" =~ ^s[123]$ ]]; then
  echo "Usage: $0 s1|s2|s3 EVIDENCE_DIR" >&2
  exit 2
fi

readonly SCENARIO="$1"
readonly EVIDENCE_DIR="$2"
readonly TIMELINE_FILE="${EVIDENCE_DIR}/timeline.json"
readonly NORMALIZED_FILE="${EVIDENCE_DIR}/normalized-timeline.json"
readonly ASSET_DIR="${LAB_ROOT}/assets/captures/${SCENARIO}"
readonly PYTHON="${LAB_ROOT}/app/.venv/bin/python"

require_lab_config
verify_subscription
verify_lab_resource_group

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
if [[ "${capture_status}" -eq 3 ]]; then
  echo "Capture ended at the deadline; missing states are explicit in the output."
fi
