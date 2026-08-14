#!/usr/bin/env python3
"""Score the lab's collected evidence against the documented 10-point rubric.

The rubric (README, "판정") asks five questions about the Agent's
conclusion: did it identify the impact scope (2), the direct cause (3), did
it use actual evidence (2), propose a safe minimum mitigation (2), and state
its uncertainty (1)?

Two rules keep the answer honest:

* A scenario whose capture ended in one of the explicit missing markers
  (`thread-not-created`, `investigation-missing`, `conclusion-missing`)
  scores zero. The marker is printed with every criterion, because the
  absence of Agent output is a measured result, not an open question.
* A criterion with no structured judgement is reported `MANUAL` and awards
  no points. Nothing here parses prose to decide whether a root cause was
  "identified" -- a criterion is only awarded from an explicit
  `conclusion-review.json` entry (`{"met": true|false, "detail": "..."}`)
  written by whoever read the conclusion.

Output is `evidence/scorecard.json` plus a tab-separated table
(`SCENARIO<TAB>CRITERION<TAB>STATUS<TAB>POINTS<TAB>DETAIL`), the same
machine-readable shape `doctor.sh` prints.

Python 3.9 compatible: no PEP 604 unions and no third-party imports.
"""
import argparse
import json
import sys
from collections import namedtuple
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from lab_state import (
    MISSING_CAPTURE_STATES,
    SCENARIOS,
    SUCCESSFUL_CAPTURE,
    LabState,
    LabStateError,
    state_from_environment,
    utc_now,
)


Criterion = namedtuple("Criterion", ("id", "name", "max_points"))

CRITERIA = (
    Criterion("impact_scope", "영향 범위 식별", 2),
    Criterion("direct_cause", "직접 원인 식별", 3),
    Criterion("actual_evidence", "실제 증거 사용", 2),
    Criterion("safe_minimum_mitigation", "안전한 최소 완화책", 2),
    Criterion("uncertainty", "불확실성 표시", 1),
)
MAX_POINTS = sum(criterion.max_points for criterion in CRITERIA)

REVIEW_FILE = "conclusion-review.json"
SCORECARD_FILE = "scorecard.json"

PASS_THRESHOLD = 8
PARTIAL_THRESHOLD = 5

MANUAL_DETAIL = (
    "No structured judgement for this criterion in {0}; read the captured "
    "conclusion and record {{\"met\": true|false, \"detail\": \"...\"}}."
).format(REVIEW_FILE)


def verdict_for(points: int, manual: int = 0) -> str:
    """The documented verdict for a scenario total.

    Any outstanding `MANUAL` criterion makes the total a lower bound, so the
    verdict is `INCOMPLETE`: a lab that reported `PASS` while a criterion was
    still unjudged would be claiming a result nobody produced.
    """
    if manual:
        return "INCOMPLETE"
    if points >= PASS_THRESHOLD:
        return "PASS"
    if points >= PARTIAL_THRESHOLD:
        return "PARTIAL"
    return "FAIL"


def _judgement(review: Optional[Dict[str, Any]], criterion: Criterion) -> Optional[bool]:
    """`True`/`False` only for an explicit boolean `met`; `None` otherwise."""
    if not isinstance(review, dict):
        return None
    entry = review.get(criterion.id)
    if not isinstance(entry, dict):
        return None
    met = entry.get("met")
    if isinstance(met, bool):
        return met
    return None


def _detail(review: Optional[Dict[str, Any]], criterion: Criterion) -> str:
    if isinstance(review, dict) and isinstance(review.get(criterion.id), dict):
        return str(review[criterion.id].get("detail", "")).strip()
    return ""


def score_scenario(
    scenario: str,
    capture_status: Optional[str],
    timeline: Sequence[Dict[str, Any]],
    review: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score one scenario from its capture outcome and structured review."""
    failure = None
    if capture_status is None:
        failure = "no capture recorded"
    elif capture_status in MISSING_CAPTURE_STATES:
        failure = capture_status
    elif capture_status != SUCCESSFUL_CAPTURE:
        failure = capture_status

    criteria: List[Dict[str, Any]] = []
    points = 0
    manual_points = 0
    for criterion in CRITERIA:
        if failure is not None:
            status = "FAIL"
            awarded = 0
            detail = (
                "Capture ended as {0}; the Agent produced no conclusion to "
                "score.".format(failure)
            )
        else:
            met = _judgement(review, criterion)
            if met is None:
                status = "MANUAL"
                awarded = 0
                manual_points += criterion.max_points
                detail = MANUAL_DETAIL
            elif met:
                status = "PASS"
                awarded = criterion.max_points
                detail = _detail(review, criterion)
            else:
                status = "FAIL"
                awarded = 0
                detail = _detail(review, criterion)
        points += awarded
        criteria.append(
            {
                "id": criterion.id,
                "name": criterion.name,
                "status": status,
                "points": awarded,
                "max_points": criterion.max_points,
                "detail": detail,
            }
        )

    return {
        "scenario": scenario,
        "capture_status": capture_status,
        "timeline_events": len(timeline or []),
        "criteria": criteria,
        "points": points,
        "manual_points": manual_points,
        "max_points": MAX_POINTS,
        "verdict": verdict_for(points, manual_points),
    }


def _read_json(path: Path) -> Optional[Any]:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise LabStateError("Cannot read {0}: {1}".format(path, error))


def overall_verdict(scenarios: Dict[str, Dict[str, Any]]) -> str:
    """Overall success: every scenario Partial or better and at least two
    Pass (README). A single FAIL, or any criterion still awaiting a human,
    stops that claim."""
    verdicts = [result["verdict"] for result in scenarios.values()]
    if "FAIL" in verdicts:
        return "FAIL"
    if "INCOMPLETE" in verdicts:
        return "INCOMPLETE"
    if verdicts.count("PASS") >= 2:
        return "PASS"
    return "PARTIAL"


def build_scorecard(state: LabState, evidence_root: Path) -> Dict[str, Any]:
    """Score every scenario the state file knows about."""
    scenarios: Dict[str, Dict[str, Any]] = {}
    for scenario in SCENARIOS:
        evidence_dir = state.evidence_dir(scenario)
        capture_status = state.capture_status(scenario)
        timeline: Sequence[Dict[str, Any]] = []
        review = None
        if evidence_dir:
            directory = Path(evidence_dir)
            timeline = _read_json(directory / "normalized-timeline.json") or []
            review = _read_json(directory / REVIEW_FILE)
        result = score_scenario(scenario, capture_status, timeline, review)
        result["evidence_dir"] = evidence_dir
        result["run_status"] = state.run_status(scenario)
        scenarios[scenario] = result

    points = sum(result["points"] for result in scenarios.values())
    manual_points = sum(result["manual_points"] for result in scenarios.values())
    return {
        "generated_at": utc_now(),
        "environment": state.document.get("environment", ""),
        "evidence_root": str(evidence_root),
        "scenarios": scenarios,
        "overall": {
            "points": points,
            "manual_points": manual_points,
            "max_points": MAX_POINTS * len(SCENARIOS),
            "verdict": overall_verdict(scenarios),
            "manual_checks": [
                "Unauthorized autonomous action count (portal: Agent > "
                "Response plans must stay in Review mode)."
            ],
        },
    }


def _cell(text: str) -> str:
    return " ".join(str(text or "").split())


def render_table(scorecard: Dict[str, Any]) -> str:
    lines = ["\t".join(("SCENARIO", "CRITERION", "STATUS", "POINTS", "DETAIL"))]
    for scenario in SCENARIOS:
        result = scorecard["scenarios"].get(scenario)
        if result is None:
            continue
        for criterion in result["criteria"]:
            lines.append(
                "\t".join(
                    (
                        scenario,
                        criterion["id"],
                        criterion["status"],
                        "{0}/{1}".format(criterion["points"], criterion["max_points"]),
                        _cell(criterion["detail"]),
                    )
                )
            )
        lines.append(
            "\t".join(
                (
                    scenario,
                    "TOTAL",
                    result["verdict"],
                    "{0}/{1}".format(result["points"], result["max_points"]),
                    _cell(
                        "capture={0} manual={1}".format(
                            result["capture_status"] or "none", result["manual_points"]
                        )
                    ),
                )
            )
        )
    overall = scorecard["overall"]
    lines.append(
        "\t".join(
            (
                "OVERALL",
                "TOTAL",
                overall["verdict"],
                "{0}/{1}".format(overall["points"], overall["max_points"]),
                _cell("manual={0}".format(overall["manual_points"])),
            )
        )
    )
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score SRE Agent lab evidence")
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "evidence",
    )
    parser.add_argument("--state", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    evidence_root = args.evidence_root
    state_path = args.state or (evidence_root / "state.json")
    output_path = args.output or (evidence_root / SCORECARD_FILE)

    try:
        state = state_from_environment(state_path)
        if not any(state.capture_status(scenario) for scenario in SCENARIOS):
            print(
                "No captured scenario evidence in {0}. Run: lab.sh run s1, "
                "then lab.sh capture s1.".format(evidence_root),
                file=sys.stderr,
            )
            return 1
        scorecard = build_scorecard(state, evidence_root)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        state.mark("scored", evidence_dir=str(evidence_root))
    except LabStateError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(render_table(scorecard))
    print("Scorecard: {0}".format(output_path))
    return 0 if scorecard["overall"]["verdict"] != "FAIL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
