"""Behavioural tests for `score.py`, the lab's rubric scorer.

Scoring is where an unproven claim would do the most damage: awarding
"actual evidence used" because a conclusion merely exists would turn the
lab into a rubber stamp. So the two properties pinned here are that a real
failure marker (`thread-not-created` / `investigation-missing` /
`conclusion-missing`) scores zero and stays visible, and that a criterion
with no structured judgement is reported `MANUAL` with no points awarded.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "score.py"
STATE_MODULE_PATH = Path(__file__).parents[1] / "lab_state.py"


def load_module(path, name):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


score = load_module(MODULE_PATH, "score")
lab_state = load_module(STATE_MODULE_PATH, "lab_state")


CONCLUSION_TIMELINE = [
    {"state": "alert-fired"},
    {"state": "thread-created"},
    {"state": "investigating"},
    {"state": "conclusion"},
]
MISSING_CONCLUSION_TIMELINE = [
    {"state": "alert-fired"},
    {"state": "thread-created"},
    {"state": "investigating"},
    {"state": "conclusion-missing"},
]
FULL_REVIEW = {
    "impact_scope": {"met": True, "detail": "Named the Container App and both routes."},
    "direct_cause": {"met": True, "detail": "Named FAILURE_MODE=http500."},
    "actual_evidence": {"met": True, "detail": "Quoted AppRequests rows."},
    "safe_minimum_mitigation": {"met": True, "detail": "Proposed reverting the env var."},
    "uncertainty": {"met": True, "detail": "Flagged the unverified dependency."},
}


def write_evidence(root, scenario, timeline, review=None, name=None):
    evidence_dir = root / (name or f"{scenario}-20260814T000000Z")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "normalized-timeline.json").write_text(json.dumps(timeline))
    if review is not None:
        (evidence_dir / "conclusion-review.json").write_text(json.dumps(review))
    return evidence_dir


def make_state(evidence_root, scenarios):
    """A state file recording one recovered+captured run per scenario."""
    state = lab_state.LabState(evidence_root / "state.json")
    state.mark("baseline_passed")
    state.mark("agent_setup_acknowledged")
    for scenario, evidence_dir in scenarios.items():
        timeline = json.loads((evidence_dir / "normalized-timeline.json").read_text())
        state.mark_recovered(scenario, str(evidence_dir))
        state.record_capture(scenario, lab_state.terminal_state(timeline), str(evidence_dir))
    return state


def criteria_by_id(scenario_result):
    return {item["id"]: item for item in scenario_result["criteria"]}


# --- Rubric -----------------------------------------------------------------


def test_the_rubric_is_the_documented_ten_point_one():
    assert [(item.id, item.max_points) for item in score.CRITERIA] == [
        ("impact_scope", 2),
        ("direct_cause", 3),
        ("actual_evidence", 2),
        ("safe_minimum_mitigation", 2),
        ("uncertainty", 1),
    ]
    assert sum(item.max_points for item in score.CRITERIA) == 10


def test_a_fully_reviewed_conclusion_earns_every_point():
    result = score.score_scenario("s1", "conclusion", CONCLUSION_TIMELINE, FULL_REVIEW)

    assert result["points"] == 10
    assert result["max_points"] == 10
    assert result["verdict"] == "PASS"
    assert {item["status"] for item in result["criteria"]} == {"PASS"}


def test_an_unmet_criterion_costs_exactly_its_points():
    review = dict(FULL_REVIEW)
    review["direct_cause"] = {"met": False, "detail": "Named a symptom, not the cause."}

    result = score.score_scenario("s1", "conclusion", CONCLUSION_TIMELINE, review)

    assert criteria_by_id(result)["direct_cause"]["status"] == "FAIL"
    assert criteria_by_id(result)["direct_cause"]["points"] == 0
    assert "symptom" in criteria_by_id(result)["direct_cause"]["detail"]
    assert result["points"] == 7
    assert result["verdict"] == "PARTIAL"


@pytest.mark.parametrize(
    "points, verdict",
    ((10, "PASS"), (8, "PASS"), (7, "PARTIAL"), (5, "PARTIAL"), (4, "FAIL"), (0, "FAIL")),
)
def test_the_documented_thresholds_decide_the_verdict(points, verdict):
    assert score.verdict_for(points, manual=0) == verdict


def test_any_manual_criterion_keeps_the_verdict_incomplete():
    assert score.verdict_for(9, manual=1) == "INCOMPLETE"


# --- Unavailable structured evidence ---------------------------------------


def test_a_missing_review_is_manual_and_awards_nothing():
    result = score.score_scenario("s1", "conclusion", CONCLUSION_TIMELINE, None)

    assert result["points"] == 0
    assert result["manual_points"] == 10
    assert result["verdict"] == "INCOMPLETE"
    assert {item["status"] for item in result["criteria"]} == {"MANUAL"}
    for item in result["criteria"]:
        assert item["points"] == 0


def test_one_unavailable_field_is_manual_while_the_rest_score():
    review = {key: value for key, value in FULL_REVIEW.items() if key != "uncertainty"}

    result = score.score_scenario("s1", "conclusion", CONCLUSION_TIMELINE, review)

    assert criteria_by_id(result)["uncertainty"]["status"] == "MANUAL"
    assert criteria_by_id(result)["uncertainty"]["points"] == 0
    assert result["points"] == 9
    assert result["manual_points"] == 1
    assert result["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("unusable", ({"detail": "no verdict"}, {"met": "yes"}, "PASS", None))
def test_an_unusable_judgement_is_manual_never_a_pass(unusable):
    review = dict(FULL_REVIEW)
    review["impact_scope"] = unusable

    result = score.score_scenario("s1", "conclusion", CONCLUSION_TIMELINE, review)

    assert criteria_by_id(result)["impact_scope"]["status"] == "MANUAL"
    assert criteria_by_id(result)["impact_scope"]["points"] == 0


# --- Real failure markers ---------------------------------------------------


@pytest.mark.parametrize(
    "capture_status", ("thread-not-created", "investigation-missing", "conclusion-missing")
)
def test_a_missing_agent_output_scores_zero_and_stays_visible(capture_status):
    result = score.score_scenario("s1", capture_status, MISSING_CONCLUSION_TIMELINE, FULL_REVIEW)

    assert result["points"] == 0
    assert result["manual_points"] == 0
    assert result["capture_status"] == capture_status
    assert result["verdict"] == "FAIL"
    for item in result["criteria"]:
        assert item["status"] == "FAIL"
        assert capture_status in item["detail"]


def test_a_scenario_that_was_never_captured_is_not_manual():
    """No capture at all is a known failure, not an unknown: reporting it
    `MANUAL` would let an unrun scenario wait forever for a human instead of
    failing the lab."""
    result = score.score_scenario("s3", None, [], None)

    assert result["verdict"] == "FAIL"
    assert result["points"] == 0
    assert result["manual_points"] == 0


# --- Scorecard --------------------------------------------------------------


def test_scorecard_covers_every_scenario_and_totals_them(tmp_path):
    directories = {
        scenario: write_evidence(tmp_path, scenario, CONCLUSION_TIMELINE, FULL_REVIEW)
        for scenario in ("s1", "s2", "s3")
    }
    state = make_state(tmp_path, directories)

    scorecard = score.build_scorecard(state, tmp_path)

    assert sorted(scorecard["scenarios"]) == ["s1", "s2", "s3"]
    assert scorecard["overall"]["points"] == 30
    assert scorecard["overall"]["max_points"] == 30
    assert scorecard["overall"]["verdict"] == "PASS"
    assert scorecard["scenarios"]["s1"]["evidence_dir"] == str(directories["s1"])


def test_overall_success_requires_every_scenario_to_be_scored(tmp_path):
    directories = {
        "s1": write_evidence(tmp_path, "s1", CONCLUSION_TIMELINE, FULL_REVIEW),
        "s2": write_evidence(tmp_path, "s2", MISSING_CONCLUSION_TIMELINE, FULL_REVIEW),
    }
    state = make_state(tmp_path, directories)

    scorecard = score.build_scorecard(state, tmp_path)

    assert scorecard["scenarios"]["s2"]["verdict"] == "FAIL"
    assert scorecard["scenarios"]["s3"]["verdict"] == "FAIL"
    assert scorecard["overall"]["verdict"] == "FAIL"


def test_manual_criteria_hold_the_overall_verdict_at_incomplete(tmp_path):
    directories = {
        scenario: write_evidence(tmp_path, scenario, CONCLUSION_TIMELINE, None)
        for scenario in ("s1", "s2", "s3")
    }
    state = make_state(tmp_path, directories)

    scorecard = score.build_scorecard(state, tmp_path)

    assert scorecard["overall"]["verdict"] == "INCOMPLETE"
    assert scorecard["overall"]["manual_points"] == 30
    assert scorecard["overall"]["points"] == 0


def test_the_table_shows_every_criterion_with_its_status(tmp_path):
    directories = {
        scenario: write_evidence(tmp_path, scenario, CONCLUSION_TIMELINE, FULL_REVIEW)
        for scenario in ("s1", "s2", "s3")
    }
    state = make_state(tmp_path, directories)

    table = score.render_table(score.build_scorecard(state, tmp_path))

    assert table.splitlines()[0].split("\t") == [
        "SCENARIO",
        "CRITERION",
        "STATUS",
        "POINTS",
        "DETAIL",
    ]
    for scenario in ("s1", "s2", "s3"):
        for item in score.CRITERIA:
            assert f"{scenario}\t{item.id}\tPASS\t{item.max_points}/{item.max_points}" in table
        assert f"{scenario}\tTOTAL\tPASS\t10/10" in table
    assert "OVERALL\tTOTAL\tPASS\t30/30" in table


# --- Command line -----------------------------------------------------------


def run_cli(evidence_root, args=()):
    process_env = dict(os.environ)
    process_env.update(
        {
            "AZURE_ENV_NAME": "sre-lab-score",
            "AZURE_SUBSCRIPTION_ID": "11111111-2222-3333-4444-555555555555",
            "AZURE_RESOURCE_GROUP": "rg-sre-lab-score",
        }
    )
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), "--evidence-root", str(evidence_root), *args],
        capture_output=True,
        text=True,
        env=process_env,
    )


def test_cli_writes_the_scorecard_next_to_the_evidence(tmp_path):
    directories = {
        scenario: write_evidence(tmp_path, scenario, CONCLUSION_TIMELINE, FULL_REVIEW)
        for scenario in ("s1", "s2", "s3")
    }
    make_state(tmp_path, directories)

    result = run_cli(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    scorecard = json.loads((tmp_path / "scorecard.json").read_text())
    assert scorecard["overall"]["verdict"] == "PASS"
    assert "OVERALL\tTOTAL\tPASS\t30/30" in result.stdout
    assert lab_state.LabState(tmp_path / "state.json").has("scored")


def test_cli_fails_when_a_scenario_never_produced_a_conclusion(tmp_path):
    directories = {
        "s1": write_evidence(tmp_path, "s1", CONCLUSION_TIMELINE, FULL_REVIEW),
        "s2": write_evidence(tmp_path, "s2", MISSING_CONCLUSION_TIMELINE, FULL_REVIEW),
        "s3": write_evidence(tmp_path, "s3", CONCLUSION_TIMELINE, FULL_REVIEW),
    }
    make_state(tmp_path, directories)

    result = run_cli(tmp_path)

    assert result.returncode == 1
    assert "conclusion-missing" in result.stdout
    assert json.loads((tmp_path / "scorecard.json").read_text())["scenarios"]["s2"]["verdict"] == "FAIL"


def test_cli_reports_manual_criteria_without_awarding_points(tmp_path):
    directories = {
        scenario: write_evidence(tmp_path, scenario, CONCLUSION_TIMELINE, None)
        for scenario in ("s1", "s2", "s3")
    }
    make_state(tmp_path, directories)

    result = run_cli(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "MANUAL" in result.stdout
    assert "OVERALL\tTOTAL\tINCOMPLETE\t0/30" in result.stdout


def test_cli_without_any_state_explains_what_to_run_first(tmp_path):
    result = run_cli(tmp_path)

    assert result.returncode == 1
    assert "lab.sh run" in result.stderr
    assert "Traceback" not in result.stderr
