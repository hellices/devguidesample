#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

# `lab_state.py`/`score.py` do not exist yet (a later task adds them). Every
# dispatch case below that needs one checks for the file first so an
# operator gets one clear "not yet available" line instead of a raw
# "No such file or directory" from `exec`.
PYTHON="${LAB_ROOT}/app/.venv/bin/python"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python3"
fi
readonly PYTHON

usage() {
  cat <<'USAGE'
Usage: lab.sh <command> [args]

Commands:
  doctor                    Diagnose the lab environment
  baseline                  Run baseline load and verify telemetry
  acknowledge agent-setup   Record manually-verified Agent setup evidence
  run s1|s2|s3              Run a failure scenario
  capture s1|s2|s3          Capture Azure SRE Agent evidence for a scenario
  score                     Score the collected evidence
USAGE
}

not_yet_available() {
  local component="$1"
  echo "${component} is not yet available in this lab checkout (planned for a later task)." >&2
  exit 3
}

latest_evidence_dir() {
  local scenario="$1"
  local candidate
  candidate="$(ls -dt "${EVIDENCE_ROOT}/${scenario}-"*/ 2>/dev/null | head -n1 || true)"
  if [[ -n "${candidate}" ]]; then
    printf '%s\n' "${candidate%/}"
  fi
}

# Sub-scripts are run through `bash` explicitly (not a bare `exec path`) so
# dispatch never depends on that file's executable bit.
case "${1:-}" in
  doctor)
    exec bash "${SCRIPT_DIR}/doctor.sh"
    ;;
  baseline)
    exec bash "${SCRIPT_DIR}/baseline.sh"
    ;;
  acknowledge)
    [[ "${2:-}" == "agent-setup" ]] || { usage >&2; exit 2; }
    if [[ ! -f "${SCRIPT_DIR}/lab_state.py" ]]; then
      not_yet_available "lab.sh acknowledge agent-setup"
    fi
    exec "${PYTHON}" "${SCRIPT_DIR}/lab_state.py" acknowledge-agent
    ;;
  run)
    [[ "${2:-}" =~ ^s[123]$ ]] || { usage >&2; exit 2; }
    exec bash "${SCRIPT_DIR}/run-scenario.sh" "${2}"
    ;;
  capture)
    [[ "${2:-}" =~ ^s[123]$ ]] || { usage >&2; exit 2; }
    EVIDENCE_DIR="$(latest_evidence_dir "${2}")"
    if [[ -z "${EVIDENCE_DIR}" ]]; then
      echo "No evidence directory found for ${2}. Run: lab.sh run ${2}" >&2
      exit 1
    fi
    exec bash "${SCRIPT_DIR}/capture-scenario.sh" "${2}" "${EVIDENCE_DIR}"
    ;;
  score)
    if [[ ! -f "${SCRIPT_DIR}/score.py" ]]; then
      not_yet_available "lab.sh score"
    fi
    exec "${PYTHON}" "${SCRIPT_DIR}/score.py"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
