"""Behavioural tests for `lab.sh`, the guided single-command entry point.

`lab.sh` itself contains no Azure logic -- it only dispatches to
`doctor.sh`, `baseline.sh`, `run-scenario.sh`, `capture-scenario.sh`, and
(once a later task adds them) `lab_state.py`/`score.py`. These tests drive
it as a real program: dispatch to the scripts that already exist is proven
by observing their actual (faked) side effects, not by grepping `lab.sh`'s
source for a case label. The one text-based exception is
`test_lab_cli_dispatches_known_commands`, which is a brief-mandated
regression guard for the dispatcher's own case statement.
"""
import json
from pathlib import Path

import pytest

from doctor_harness import FakeAz, lab_dir_for, run_lab_cli, state_path_for
from lab_script_harness import make_lab


COMMANDS = ("doctor", "baseline", "acknowledge", "run", "capture", "score")

# Bounded recovery waits: `run-scenario.sh` polls the workload health and the
# fired alert's condition before it records a recovery.
BOUNDED_WAITS = {
    "LAB_ALERT_RESOLVE_TIMEOUT_SECONDS": "5",
    "LAB_ALERT_RESOLVE_POLL_INTERVAL_SECONDS": "1",
    "LAB_RECOVERY_HEALTH_TIMEOUT_SECONDS": "5",
}

CONCLUSION_TIMELINE = [
    {"state": "alert-fired"},
    {"state": "thread-created"},
    {"state": "investigating"},
    {"state": "conclusion"},
]
FULL_REVIEW = {
    "impact_scope": {"met": True, "detail": "Named both routes."},
    "direct_cause": {"met": True, "detail": "Named the injected failure mode."},
    "actual_evidence": {"met": True, "detail": "Quoted AppRequests rows."},
    "safe_minimum_mitigation": {"met": True, "detail": "Proposed the revert."},
    "uncertainty": {"met": True, "detail": "Flagged what it could not verify."},
}


@pytest.fixture
def fake_az(tmp_path):
    return FakeAz(workdir=tmp_path)


def test_lab_cli_dispatches_known_commands():
    lab_cli = Path(__file__).parents[1].joinpath("lab.sh").read_text()
    for command in COMMANDS:
        assert f"{command})" in lab_cli, f"lab.sh has no dispatch case for {command}"


def test_lab_cli_doctor_dispatches_to_doctor_sh(fake_az):
    result = run_lab_cli(fake_az, ["doctor"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Required commands\tPASS" in result.stdout
    assert "Repository connection\tMANUAL" in result.stdout


def test_lab_cli_doctor_surfaces_doctor_sh_failure(fake_az):
    fake_az.container_app_health = "Unhealthy"

    result = run_lab_cli(fake_az, ["doctor"])

    assert result.returncode == 1
    assert "Container App health\tFAIL" in result.stdout


def test_lab_cli_baseline_dispatches_to_baseline_sh(fake_az):
    result = run_lab_cli(
        fake_az,
        ["baseline"],
        lab_baseline_telemetry_timeout_seconds="5",
        lab_baseline_telemetry_poll_interval_seconds="1",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    evidence_dirs = sorted((lab_dir_for(fake_az) / "evidence").glob("baseline-*"))
    assert evidence_dirs, "lab.sh baseline never invoked baseline.sh"
    assert (evidence_dirs[-1] / "telemetry-check.json").is_file()
    assert (evidence_dirs[-1] / "orders.json").is_file()
    assert (evidence_dirs[-1] / "documents.json").is_file()


def test_lab_cli_baseline_surfaces_baseline_sh_failure(fake_az):
    fake_az.baseline_orders_succeed = False

    result = run_lab_cli(
        fake_az,
        ["baseline"],
        lab_baseline_telemetry_timeout_seconds="5",
        lab_baseline_telemetry_poll_interval_seconds="1",
    )

    assert result.returncode != 0


def test_lab_cli_run_dispatches_to_run_scenario_sh(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.seed_state()

    result = lab_run.run("lab.sh", ["run", "s1"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stderr
    evidence_dirs = sorted((lab_run.lab / "evidence").glob("s1-*"))
    assert evidence_dirs, "lab.sh run never invoked run-scenario.sh"
    timeline = json.loads((evidence_dirs[-1] / "timeline.json").read_text())
    assert timeline["scenario"] == "s1"


def test_lab_cli_run_rejects_an_unknown_scenario(tmp_path):
    lab_run = make_lab(tmp_path)

    result = lab_run.run("lab.sh", ["run", "s9"])

    assert result.returncode == 2
    assert "Usage" in result.stderr


def test_lab_cli_capture_resolves_the_evidence_directory_from_the_state(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("lab.sh", ["run", "s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]

    result = lab_run.run("lab.sh", ["capture", "s1"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert (evidence_dir / "normalized-timeline.json").is_file()
    assert (lab_run.lab / "assets" / "captures" / "s1" / "investigation.gif").is_file()
    assert lab_run.scenario_state("s1")["capture_status"] == "conclusion"


def test_lab_cli_capture_fails_clearly_when_no_evidence_exists(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()

    result = lab_run.run("lab.sh", ["capture", "s1"])

    assert result.returncode != 0
    assert "No such file or directory" not in result.stderr
    assert "s1" in result.stderr
    assert "lab.sh run s1" in result.stderr


def test_lab_cli_capture_works_even_when_capture_scenario_is_not_executable(tmp_path):
    """Dispatch must not depend on a sub-script's executable bit -- `lab.sh`
    always invokes it through `bash`, never a bare `exec path`."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("lab.sh", ["run", "s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr
    (lab_run.lab / "scripts" / "capture-scenario.sh").chmod(0o644)

    result = lab_run.run("lab.sh", ["capture", "s1"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_lab_cli_acknowledge_prints_the_settings_and_records_the_answer(fake_az):
    result = run_lab_cli(
        fake_az,
        ["acknowledge", "agent-setup"],
        stdin="acknowledge\n",
        sre_agent_name="sre-agent-lab",
        sre_repository_url="https://github.com/example/devguidesample",
        sre_repository_branch="feature/sre-agent-azd-lab",
        sre_knowledge_path="runbooks/incident-response.md",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "https://github.com/example/devguidesample" in result.stdout
    assert "feature/sre-agent-azd-lab" in result.stdout
    assert "runbooks/incident-response.md" in result.stdout
    assert "Review" in result.stdout
    assert "alert-sre-lab-s1-http500" in result.stdout
    state = json.loads(state_path_for(fake_az).read_text())
    assert "agent_setup_acknowledged" in state["stages"]
    assert state["environment"] == "sre-lab-exec"


def test_lab_cli_acknowledge_records_nothing_without_the_exact_word(fake_az):
    result = run_lab_cli(fake_az, ["acknowledge", "agent-setup"], stdin="yes\n")

    assert result.returncode != 0
    assert not state_path_for(fake_az).exists()


def test_lab_cli_score_without_evidence_explains_what_to_run(fake_az):
    result = run_lab_cli(fake_az, ["score"])

    assert result.returncode == 1
    assert "lab.sh run" in result.stderr
    assert "No such file or directory" not in result.stderr


def test_lab_cli_score_scores_the_collected_evidence(fake_az):
    run_lab_cli(fake_az, ["score"])  # materializes the lab
    evidence_root = lab_dir_for(fake_az) / "evidence"
    scenarios = {}
    for scenario in ("s1", "s2", "s3"):
        evidence_dir = evidence_root / f"{scenario}-20260814T000000Z"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "normalized-timeline.json").write_text(json.dumps(CONCLUSION_TIMELINE))
        (evidence_dir / "conclusion-review.json").write_text(json.dumps(FULL_REVIEW))
        scenarios[scenario] = {
            "run_status": "recovered",
            "capture_status": "conclusion",
            "evidence_dir": str(evidence_dir),
        }
    state_path_for(fake_az).write_text(
        json.dumps(
            {
                "environment": "sre-lab-exec",
                "subscription_id": "11111111-2222-3333-4444-555555555555",
                "resource_group": "rg-sre-lab-exec",
                "stages": {"baseline_passed": {"at": "2026-08-14T00:00:00Z"}},
                "scenarios": scenarios,
            }
        )
    )

    result = run_lab_cli(fake_az, ["score"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert "OVERALL\tTOTAL\tPASS\t30/30" in result.stdout
    scorecard = json.loads((evidence_root / "scorecard.json").read_text())
    assert scorecard["overall"]["verdict"] == "PASS"


def test_lab_cli_acknowledge_rejects_an_unknown_subcommand(fake_az):
    result = run_lab_cli(fake_az, ["acknowledge", "not-a-setup"])

    assert result.returncode == 2
    assert "Usage" in result.stderr


def test_lab_cli_rejects_an_unknown_command(fake_az):
    result = run_lab_cli(fake_az, ["bogus"])

    assert result.returncode == 2
    assert "Usage" in result.stderr


def test_lab_cli_with_no_arguments_prints_usage(fake_az):
    result = run_lab_cli(fake_az, [])

    assert result.returncode == 2
    assert "Usage" in result.stderr
