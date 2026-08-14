"""Behavioural tests for `lab_state.py`, the lab's ordered-run state.

The state file is the only thing standing between an operator and a
scenario run whose evidence cannot mean anything: an S2 run started before
S1's capture landed produces two overlapping incidents, and a "successful"
capture recorded for a thread the Agent never created turns a real failure
into a passing lab. Both properties are exercised here through the real
API and the real command line (including the interactive acknowledgement,
driven through stdin), never by reading the module's source.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).parents[1] / "lab_state.py"


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("lab_state", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lab_state = load_module()
LabState = lab_state.LabState
InvalidTransition = lab_state.InvalidTransition
EnvironmentMismatch = lab_state.EnvironmentMismatch


ENVIRONMENT = {
    "AZURE_ENV_NAME": "sre-lab-state",
    "AZURE_SUBSCRIPTION_ID": "11111111-2222-3333-4444-555555555555",
    "AZURE_RESOURCE_GROUP": "rg-sre-lab-state",
}


def run_cli(state_path, args, stdin="", env=None):
    process_env = dict(os.environ)
    process_env.update(ENVIRONMENT)
    process_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), "--state", str(state_path), *args],
        capture_output=True,
        text=True,
        input=stdin,
        env=process_env,
    )


def ready_for_s1(path):
    state = LabState(path)
    state.mark("baseline_passed")
    state.mark("agent_setup_acknowledged")
    return state


# --- Brief-mandated state-transition tests ---------------------------------


def test_s2_requires_s1_capture(tmp_path):
    state = LabState(tmp_path / "state.json")
    state.mark("baseline_passed")
    state.mark("s1_recovered")
    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.require_run("s2")


def test_s1_requires_manual_agent_setup_acknowledgement(tmp_path):
    state = LabState(tmp_path / "state.json")
    state.mark("baseline_passed")
    with pytest.raises(InvalidTransition, match="agent_setup_acknowledged"):
        state.require_run("s1")


def test_missing_thread_is_recorded_not_promoted_to_success(tmp_path):
    state = LabState(tmp_path / "state.json")
    state.record_capture("s1", "thread-not-created")
    assert state.capture_status("s1") == "thread-not-created"
    assert not state.is_successful_capture("s1")


# --- Ordering ---------------------------------------------------------------


def test_s1_requires_a_passing_baseline(tmp_path):
    state = LabState(tmp_path / "state.json")
    state.mark("agent_setup_acknowledged")
    with pytest.raises(InvalidTransition, match="baseline_passed"):
        state.require_run("s1")


def test_s1_runs_once_baseline_and_acknowledgement_are_recorded(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")

    state.require_run("s1")  # must not raise


def test_s2_requires_s1_recovery_even_when_s1_was_captured(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.record_capture("s1", "conclusion")
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


def test_s3_requires_s2_not_only_s1(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1"))
    state.record_capture("s1", "conclusion")
    with pytest.raises(InvalidTransition, match="s2_recovered"):
        state.require_run("s3")


def test_the_full_ordered_sequence_is_allowed(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    for scenario in ("s1", "s2", "s3"):
        state.require_run(scenario)
        state.mark_recovered(scenario, str(tmp_path / scenario))
        state.record_capture(scenario, "conclusion")

    assert [state.capture_status(name) for name in ("s1", "s2", "s3")] == [
        "conclusion",
        "conclusion",
        "conclusion",
    ]


def test_a_failed_run_does_not_satisfy_the_next_scenario(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_failed("s1", str(tmp_path / "s1"), reason="alert never resolved")
    state.record_capture("s1", "conclusion")

    assert state.run_status("s1") == "failed"
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


def test_require_run_rejects_an_unknown_scenario(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    with pytest.raises(ValueError):
        state.require_run("s9")


# --- Never promoting missing Agent output to success ------------------------


@pytest.mark.parametrize(
    "missing_status", ("thread-not-created", "investigation-missing", "conclusion-missing")
)
def test_every_missing_marker_blocks_the_next_scenario(tmp_path, missing_status):
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1"))
    state.record_capture("s1", missing_status)

    assert state.capture_status("s1") == missing_status
    assert not state.is_successful_capture("s1")
    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.require_run("s2")


def test_marking_a_capture_stage_by_hand_cannot_invent_success(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1"))
    state.record_capture("s1", "conclusion-missing")

    with pytest.raises(InvalidTransition, match="conclusion-missing"):
        state.mark("s1_captured")
    assert not state.is_successful_capture("s1")


def test_record_capture_rejects_an_unknown_terminal_state(tmp_path):
    state = LabState(tmp_path / "state.json")
    with pytest.raises(ValueError):
        state.record_capture("s1", "looks-fine")


@pytest.mark.parametrize(
    "events, expected",
    (
        ([{"state": "alert-fired"}, {"state": "thread-created"}, {"state": "conclusion"}], "conclusion"),
        (
            [
                {"state": "alert-fired"},
                {"state": "thread-not-created"},
                {"state": "investigation-missing"},
                {"state": "conclusion-missing"},
            ],
            "thread-not-created",
        ),
        (
            [
                {"state": "alert-fired"},
                {"state": "thread-created"},
                {"state": "investigation-missing"},
                {"state": "conclusion-missing"},
            ],
            "investigation-missing",
        ),
        (
            [
                {"state": "alert-fired"},
                {"state": "thread-created"},
                {"state": "investigating"},
                {"state": "conclusion-missing"},
            ],
            "conclusion-missing",
        ),
        ([], "thread-not-created"),
    ),
)
def test_terminal_state_reads_the_normalized_timeline(events, expected):
    assert lab_state.terminal_state(events) == expected


# --- Storage ----------------------------------------------------------------


def test_state_survives_a_reload(tmp_path):
    path = tmp_path / "state.json"
    state = ready_for_s1(path)
    state.mark_recovered("s1", str(tmp_path / "s1-20260814T000000Z"))
    state.record_capture("s1", "conclusion")

    reloaded = LabState(path)

    assert reloaded.has("agent_setup_acknowledged")
    assert reloaded.run_status("s1") == "recovered"
    assert reloaded.evidence_dir("s1") == str(tmp_path / "s1-20260814T000000Z")
    reloaded.require_run("s2")


def test_state_is_written_through_a_sibling_temporary_file(tmp_path, monkeypatch):
    """Only a rename within the same directory is atomic, so the complete
    JSON must be written to a sibling temporary file first and renamed into
    place -- never streamed into `state.json` itself."""
    path = tmp_path / "state.json"
    state = LabState(path)
    replaced = {}
    real_replace = os.replace

    def spy_replace(source, target):
        replaced["source"] = str(source)
        replaced["target"] = str(target)
        replaced["source_is_sibling"] = Path(source).parent == Path(target).parent
        replaced["content"] = Path(source).read_text()
        return real_replace(source, target)

    monkeypatch.setattr(lab_state.os, "replace", spy_replace)
    state.mark("baseline_passed")
    monkeypatch.undo()

    assert replaced["target"] == str(path)
    assert replaced["source"] != str(path)
    assert replaced["source_is_sibling"]
    assert json.loads(replaced["content"])["stages"]["baseline_passed"]["at"]
    assert [item.name for item in tmp_path.iterdir()] == ["state.json"]


def test_an_interrupted_write_leaves_the_previous_state_readable(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    state = LabState(path)
    state.mark("baseline_passed")
    before = path.read_text()

    def failing_replace(source, target):
        raise OSError("interrupted")

    monkeypatch.setattr(lab_state.os, "replace", failing_replace)
    with pytest.raises(OSError):
        state.mark("agent_setup_acknowledged")
    monkeypatch.undo()

    assert path.read_text() == before
    assert LabState(path).has("baseline_passed")
    assert not LabState(path).has("agent_setup_acknowledged")


def test_state_records_the_environment_it_belongs_to(tmp_path):
    path = tmp_path / "state.json"
    LabState(
        path,
        environment="sre-lab-one",
        subscription_id="sub-one",
        resource_group="rg-one",
    ).mark("baseline_passed")

    stored = json.loads(path.read_text())

    assert stored["environment"] == "sre-lab-one"
    assert stored["subscription_id"] == "sub-one"
    assert stored["resource_group"] == "rg-one"
    assert stored["stages"]["baseline_passed"]["at"].endswith("Z")


@pytest.mark.parametrize(
    "override",
    (
        {"environment": "sre-lab-two"},
        {"subscription_id": "sub-two"},
        {"resource_group": "rg-two"},
    ),
)
def test_state_from_another_environment_is_refused(tmp_path, override):
    path = tmp_path / "state.json"
    binding = {
        "environment": "sre-lab-one",
        "subscription_id": "sub-one",
        "resource_group": "rg-one",
    }
    LabState(path, **binding).mark("baseline_passed")

    with pytest.raises(EnvironmentMismatch):
        LabState(path, **dict(binding, **override))


def test_evidence_directory_is_recorded_per_stage_and_scenario(tmp_path):
    path = tmp_path / "state.json"
    state = LabState(path)
    state.mark("baseline_passed", evidence_dir=str(tmp_path / "baseline-1"))
    state.mark("agent_setup_acknowledged")
    state.mark_recovered("s1", str(tmp_path / "s1-1"))
    state.record_capture("s1", "conclusion")

    stored = json.loads(path.read_text())

    assert stored["stages"]["baseline_passed"]["evidence_dir"] == str(tmp_path / "baseline-1")
    assert stored["scenarios"]["s1"] == {
        "run_status": "recovered",
        "capture_status": "conclusion",
        "evidence_dir": str(tmp_path / "s1-1"),
    }


def test_unknown_stage_names_are_refused(tmp_path):
    state = LabState(tmp_path / "state.json")
    with pytest.raises(ValueError):
        state.mark("almost_done")


def test_a_corrupt_state_file_is_reported_not_silently_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json")

    with pytest.raises(lab_state.LabStateError):
        LabState(path)


# --- Command line -----------------------------------------------------------


def test_cli_require_run_fails_with_the_missing_state_named(tmp_path):
    path = tmp_path / "state.json"

    result = run_cli(path, ["require-run", "s1"])

    assert result.returncode == 1
    assert "baseline_passed" in result.stderr
    assert "agent_setup_acknowledged" in result.stderr


def test_cli_require_run_succeeds_once_the_prerequisites_are_recorded(tmp_path):
    path = tmp_path / "state.json"
    assert run_cli(path, ["mark", "baseline_passed"]).returncode == 0
    assert run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n").returncode == 0

    result = run_cli(path, ["require-run", "s1"])

    assert result.returncode == 0, result.stderr


def test_cli_marks_recovery_and_capture_and_resolves_the_evidence_directory(tmp_path):
    path = tmp_path / "state.json"
    evidence_dir = tmp_path / "s1-20260814T000000Z"
    evidence_dir.mkdir()
    (evidence_dir / "normalized-timeline.json").write_text(
        json.dumps([{"state": "alert-fired"}, {"state": "thread-created"}, {"state": "conclusion"}])
    )
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")

    assert run_cli(path, ["mark-recovered", "s1", str(evidence_dir)]).returncode == 0
    resolved = run_cli(path, ["evidence-dir", "s1"])
    assert resolved.returncode == 0, resolved.stderr
    assert resolved.stdout.strip() == str(evidence_dir)

    recorded = run_cli(
        path,
        [
            "record-capture",
            "s1",
            "--timeline",
            str(evidence_dir / "normalized-timeline.json"),
            "--evidence-dir",
            str(evidence_dir),
        ],
    )
    assert recorded.returncode == 0, recorded.stderr
    assert "conclusion" in recorded.stdout
    assert run_cli(path, ["require-run", "s2"]).returncode == 0


def test_cli_record_capture_keeps_a_missing_conclusion_visible(tmp_path):
    path = tmp_path / "state.json"
    evidence_dir = tmp_path / "s1-20260814T000000Z"
    evidence_dir.mkdir()
    (evidence_dir / "normalized-timeline.json").write_text(
        json.dumps(
            [
                {"state": "alert-fired"},
                {"state": "thread-created"},
                {"state": "investigating"},
                {"state": "conclusion-missing"},
            ]
        )
    )
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")
    run_cli(path, ["mark-recovered", "s1", str(evidence_dir)])

    recorded = run_cli(
        path,
        ["record-capture", "s1", "--timeline", str(evidence_dir / "normalized-timeline.json")],
    )

    assert recorded.returncode == 0, recorded.stderr
    assert "conclusion-missing" in recorded.stdout
    blocked = run_cli(path, ["require-run", "s2"])
    assert blocked.returncode == 1
    assert "s1_captured" in blocked.stderr


def test_cli_evidence_dir_without_a_run_names_the_command_to_run(tmp_path):
    result = run_cli(tmp_path / "state.json", ["evidence-dir", "s1"])

    assert result.returncode == 1
    assert "lab.sh run s1" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_refuses_a_state_file_bound_to_another_environment(tmp_path):
    path = tmp_path / "state.json"
    assert run_cli(path, ["mark", "baseline_passed"]).returncode == 0

    result = run_cli(
        path,
        ["require-run", "s1"],
        env={"AZURE_RESOURCE_GROUP": "rg-somewhere-else"},
    )

    assert result.returncode == 1
    assert "rg-somewhere-else" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_binds_new_state_to_the_current_configuration(tmp_path):
    path = tmp_path / "state.json"

    run_cli(path, ["mark", "deployed"])

    stored = json.loads(path.read_text())
    assert stored["environment"] == ENVIRONMENT["AZURE_ENV_NAME"]
    assert stored["subscription_id"] == ENVIRONMENT["AZURE_SUBSCRIPTION_ID"]
    assert stored["resource_group"] == ENVIRONMENT["AZURE_RESOURCE_GROUP"]


# --- Interactive acknowledgement -------------------------------------------


ACKNOWLEDGE_ENV = {
    "SRE_AGENT_NAME": "sre-agent-lab",
    "SRE_AGENT_RESOURCE_ID": (
        "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups"
        "/rg-sre-lab-state/providers/Microsoft.App/agents/sre-agent-lab"
    ),
    "SRE_REPOSITORY_URL": "https://github.com/example/devguidesample",
    "SRE_REPOSITORY_BRANCH": "feature/sre-agent-azd-lab",
    "SRE_KNOWLEDGE_PATH": "runbooks/incident-response.md",
}


def test_acknowledge_prints_every_setting_the_operator_must_verify(tmp_path):
    path = tmp_path / "state.json"

    result = run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n", env=ACKNOWLEDGE_ENV)

    assert result.returncode == 0, result.stderr
    for value in ACKNOWLEDGE_ENV.values():
        assert value in result.stdout
    assert "Review" in result.stdout
    for alert_name in (
        "alert-sre-lab-s1-http500",
        "alert-sre-lab-s2-latency",
        "alert-sre-lab-s3-storage-rbac",
    ):
        assert alert_name in result.stdout


def test_acknowledge_records_the_stage_only_after_the_exact_word(tmp_path):
    path = tmp_path / "state.json"

    result = run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n", env=ACKNOWLEDGE_ENV)

    assert result.returncode == 0, result.stderr
    assert LabState(path).has("agent_setup_acknowledged")


@pytest.mark.parametrize("answer", ("", "y\n", "yes\n", "ACKNOWLEDGE\n", "acknowledged\n", "ok\n"))
def test_acknowledge_refuses_anything_but_the_exact_word(tmp_path, answer):
    path = tmp_path / "state.json"

    result = run_cli(path, ["acknowledge-agent"], stdin=answer, env=ACKNOWLEDGE_ENV)

    assert result.returncode != 0
    assert not path.exists() or not LabState(path).has("agent_setup_acknowledged")


def test_acknowledge_is_never_inferred_from_the_environment(tmp_path):
    """Configured environment variables describe intent, not a portal state:
    the Agent's repository/knowledge/response-plan wiring has no official
    stable API, so only a human who looked at the portal may record it."""
    path = tmp_path / "state.json"
    env = dict(ACKNOWLEDGE_ENV)
    env.update(
        {
            "SRE_AGENT_SETUP_ACKNOWLEDGED": "true",
            "SRE_AGENT_SETUP_COMPLETE": "1",
            "CI": "true",
        }
    )

    result = run_cli(path, ["acknowledge-agent"], stdin="", env=env)

    assert result.returncode != 0
    assert not path.exists() or not LabState(path).has("agent_setup_acknowledged")


def test_acknowledge_reports_settings_that_are_not_configured(tmp_path):
    path = tmp_path / "state.json"
    env = {key: "" for key in ACKNOWLEDGE_ENV}

    result = run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n", env=env)

    assert result.returncode == 0, result.stderr
    assert "(not configured)" in result.stdout


def test_acknowledge_stores_what_was_shown_without_any_secret(tmp_path):
    path = tmp_path / "state.json"
    env = dict(ACKNOWLEDGE_ENV)
    env["SRE_AGENT_CLIENT_SECRET"] = "super-secret-value"

    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n", env=env)

    stored = path.read_text()
    assert "super-secret-value" not in stored
    details = json.loads(stored)["stages"]["agent_setup_acknowledged"]["details"]
    assert details["repository_url"] == ACKNOWLEDGE_ENV["SRE_REPOSITORY_URL"]
    assert details["repository_branch"] == ACKNOWLEDGE_ENV["SRE_REPOSITORY_BRANCH"]
    assert details["knowledge_path"] == ACKNOWLEDGE_ENV["SRE_KNOWLEDGE_PATH"]
    assert details["response_plan_mode"] == "Review"
    assert details["alert_rules"] == [
        "alert-sre-lab-s1-http500",
        "alert-sre-lab-s2-latency",
        "alert-sre-lab-s3-storage-rbac",
    ]
