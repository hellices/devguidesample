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

from doctor_harness import FakeAz, lab_dir_for, run_lab_cli
from lab_script_harness import make_lab


COMMANDS = ("doctor", "baseline", "acknowledge", "run", "capture", "score")


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

    result = lab_run.run("lab.sh", ["run", "s1"])

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


def test_lab_cli_capture_auto_discovers_the_latest_evidence_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    run_result = lab_run.run("lab.sh", ["run", "s1"])
    assert run_result.returncode == 0, run_result.stderr
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]

    result = lab_run.run("lab.sh", ["capture", "s1"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert (evidence_dir / "normalized-timeline.json").is_file()
    assert (lab_run.lab / "assets" / "captures" / "s1" / "investigation.gif").is_file()


def test_lab_cli_capture_fails_clearly_when_no_evidence_exists(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

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
    run_result = lab_run.run("lab.sh", ["run", "s1"])
    assert run_result.returncode == 0, run_result.stderr
    (lab_run.lab / "scripts" / "capture-scenario.sh").chmod(0o644)

    result = lab_run.run("lab.sh", ["capture", "s1"])

    assert result.returncode == 0, result.stdout + result.stderr


def test_lab_cli_acknowledge_agent_setup_is_not_yet_available(fake_az):
    result = run_lab_cli(fake_az, ["acknowledge", "agent-setup"])

    assert result.returncode == 3
    assert "not yet available" in result.stderr
    assert "No such file or directory" not in result.stderr


def test_lab_cli_score_is_not_yet_available(fake_az):
    result = run_lab_cli(fake_az, ["score"])

    assert result.returncode == 3
    assert "not yet available" in result.stderr
    assert "No such file or directory" not in result.stderr


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
