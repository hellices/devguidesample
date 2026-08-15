#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
source "${SCRIPT_DIR}/common.sh"

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

Commands run in this order: doctor, baseline, acknowledge agent-setup,
then run/capture for s1, s2 and s3 in turn, then score. Each step refuses
to start until `evidence/state.json` records the previous one.
USAGE
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
    # Reads the operator's typed answer from this process's stdin; the
    # configuration is loaded first so the acknowledgement is recorded
    # against the azd environment it was given for.
    require_lab_config
    lab_state acknowledge-agent
    ;;
  run)
    [[ "${2:-}" =~ ^s[123]$ ]] || { usage >&2; exit 2; }
    exec bash "${SCRIPT_DIR}/run-scenario.sh" "${2}"
    ;;
  capture)
    [[ "${2:-}" =~ ^s[123]$ ]] || { usage >&2; exit 2; }
    # capture-scenario.sh resolves the evidence directory this scenario's
    # recorded run wrote, so the public command needs no timestamp.
    exec bash "${SCRIPT_DIR}/capture-scenario.sh" "${2}"
    ;;
  score)
    require_lab_config
    lab_tool score.py --evidence-root "${EVIDENCE_ROOT}"
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
