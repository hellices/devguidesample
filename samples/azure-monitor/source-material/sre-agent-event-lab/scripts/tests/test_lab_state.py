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
import pathlib
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


def test_every_scenario_has_a_guide_to_send_an_operator_to():
    """A refusal names the document that walks the step. If the two lists
    drift, the message degrades to "the matching guide under guides/" --
    which is a direction, not an answer -- so they are pinned together.
    """
    import lab_state

    assert set(lab_state.SCENARIO_GUIDES) == set(lab_state.SCENARIOS)
    lab_root = pathlib.Path(__file__).parents[2]
    for scenario, guide in lab_state.SCENARIO_GUIDES.items():
        assert (lab_root / guide).is_file(), (scenario, guide)


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
    """A `conclusion` next to a run that never recovered can only come from
    a hand-edited or half-written state file -- `record_capture` refuses to
    write one -- so it is stated as a file here. Reading it must still
    refuse S2: the ordered rule asks for `s1_recovered`, and a capture can
    never stand in for it.
    """
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "stages": {
                    "baseline_passed": {"at": "2026-08-14T00:00:00Z"},
                    "agent_setup_acknowledged": {"at": "2026-08-14T00:01:00Z"},
                },
                "scenarios": {"s1": {"capture_status": "conclusion"}},
            }
        )
    )
    state = LabState(path)
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

    assert state.run_status("s1") == "failed"
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


# --- Re-runs never let a stale capture_status linger -----------------------


def test_rerunning_a_recovered_scenario_clears_the_stale_capture_status(tmp_path):
    """A scenario that already produced a real conclusion, then gets
    re-run (e.g. an operator re-injects the same fault to collect a second
    capture), must not let the *previous* run's conclusion satisfy the next
    scenario's gate before the *new* run has actually been captured."""
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1-first"))
    state.record_capture("s1", "conclusion")
    assert state.is_successful_capture("s1")

    state.mark_recovered("s1", str(tmp_path / "s1-second"))

    assert state.capture_status("s1") is None
    assert not state.is_successful_capture("s1")
    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.require_run("s2")


def test_rerunning_a_failed_scenario_clears_the_stale_capture_status(tmp_path):
    """The same guarantee applies when the re-run ends in failure: a
    conclusion captured on an earlier, since-superseded run must not let a
    failed re-run's scenario entry keep reporting yesterday's success."""
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1-first"))
    state.record_capture("s1", "conclusion")
    assert state.is_successful_capture("s1")

    state.mark_failed("s1", str(tmp_path / "s1-second"), reason="alert never resolved")

    assert state.capture_status("s1") is None
    assert not state.is_successful_capture("s1")
    assert state.run_status("s1") == "failed"
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


def test_reloading_after_a_rerun_still_shows_the_cleared_capture_status(tmp_path):
    """The cleared status must be what is actually persisted, not just an
    in-memory artifact of the same `LabState` instance."""
    path = tmp_path / "state.json"
    state = ready_for_s1(path)
    state.mark_recovered("s1", str(tmp_path / "s1-first"))
    state.record_capture("s1", "conclusion")
    state.mark_recovered("s1", str(tmp_path / "s1-second"))

    reloaded = LabState(path)

    assert reloaded.capture_status("s1") is None
    assert not reloaded.is_successful_capture("s1")


# --- Starting an attempt clears the previous one, before anything breaks ---


def finished_run(path, scenario="s1", evidence_dir="/lab/evidence/s1-first"):
    """A scenario entry as a *finished*, fully successful run leaves it.

    Written as JSON rather than through the API so the precondition holds
    every field a completed attempt can carry -- including the terminal
    capture metadata (`alert_resolved_at`, `captured_at`) that a future
    field addition would put here -- instead of only the ones today's
    `mark_recovered`/`record_capture` happen to write.
    """
    path.write_text(
        json.dumps(
            {
                "environment": "",
                "subscription_id": "",
                "resource_group": "",
                "stages": {
                    "baseline_passed": {"at": "2026-08-14T00:00:00Z"},
                    "agent_setup_acknowledged": {"at": "2026-08-14T00:01:00Z"},
                },
                "scenarios": {
                    scenario: {
                        "run_status": "recovered",
                        "capture_status": "conclusion",
                        "failure_reason": "an earlier attempt timed out",
                        "alert_resolved_at": "2026-08-14T00:20:00Z",
                        "captured_at": "2026-08-14T00:30:00Z",
                        "evidence_dir": evidence_dir,
                    }
                },
            }
        )
    )
    return LabState(path)


def test_begin_run_requires_the_same_prerequisites_as_require_run(tmp_path):
    """`begin_run` is what a scenario calls just before it breaks something,
    so it must refuse exactly what `require_run` refuses -- and record
    nothing when it does."""
    path = tmp_path / "state.json"
    state = LabState(path)

    with pytest.raises(InvalidTransition) as refusal:
        state.begin_run("s1", str(tmp_path / "s1-first"))

    assert "baseline_passed" in str(refusal.value)
    assert "agent_setup_acknowledged" in str(refusal.value)
    assert state.run_status("s1") is None
    assert not path.exists() or LabState(path).run_status("s1") is None


def test_begin_run_for_s2_is_refused_until_s1_recovered_and_was_captured(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1"))

    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.begin_run("s2", str(tmp_path / "s2"))

    assert state.run_status("s2") is None


def test_begin_run_clears_every_trace_of_the_finished_attempt(tmp_path):
    """The gap this closes: a scenario that already recovered and captured,
    re-run, and then failing *before* `mark_recovered`/`mark_failed` could
    run (a rejected injection, an early trap exit) left the previous
    attempt's `recovered`/`conclusion` in place -- so the next scenario was
    admitted on evidence from a run that no longer exists. Starting the
    attempt is what clears it, before the first destructive call."""
    path = tmp_path / "state.json"
    state = finished_run(path, evidence_dir=str(tmp_path / "s1-first"))

    state.begin_run("s1", str(tmp_path / "s1-second"))

    entry = state.document["scenarios"]["s1"]
    assert entry["run_status"] == "running"
    assert entry["evidence_dir"] == str(tmp_path / "s1-second")
    assert entry["started_at"].endswith("Z")
    for stale in ("capture_status", "failure_reason", "alert_resolved_at", "captured_at"):
        assert stale not in entry, stale


def test_begin_run_blocks_the_next_scenario_and_the_capture_gate(tmp_path):
    """A started-but-unfinished attempt satisfies nothing: neither the
    `sX_recovered`/`sX_captured` stages, nor the next scenario's gate."""
    path = tmp_path / "state.json"
    state = finished_run(path, evidence_dir=str(tmp_path / "s1-first"))
    assert state.has("s1_recovered") and state.has("s1_captured")

    state.begin_run("s1", str(tmp_path / "s1-second"))

    assert not state.has("s1_recovered")
    assert not state.has("s1_captured")
    assert not state.is_successful_capture("s1")
    assert state.capture_status("s1") is None
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


def test_begin_run_without_an_evidence_directory_drops_the_previous_one(tmp_path):
    """The capture step uses whatever directory the state names.
    Keeping the finished attempt's directory across a new attempt would let
    a capture of the *old* timeline be recorded as this attempt's outcome."""
    path = tmp_path / "state.json"
    state = finished_run(path, evidence_dir=str(tmp_path / "s1-first"))

    state.begin_run("s1")

    assert state.evidence_dir("s1") is None


def test_begin_run_is_persisted_not_only_held_in_memory(tmp_path):
    """The attempt starts before the injection, and the process that
    injected it may never get another chance to write: what a *later*
    command reads from disk is the only thing that blocks the next
    scenario."""
    path = tmp_path / "state.json"
    finished_run(path, evidence_dir=str(tmp_path / "s1-first")).begin_run(
        "s1", str(tmp_path / "s1-second")
    )

    reloaded = LabState(path)

    assert reloaded.run_status("s1") == "running"
    assert reloaded.capture_status("s1") is None
    assert reloaded.evidence_dir("s1") == str(tmp_path / "s1-second")
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        reloaded.require_run("s2")


def test_a_started_run_scores_as_no_capture_at_all(tmp_path):
    """`score.py` reads `capture_status`; a started attempt must leave it
    empty so a re-run that died early can never be scored on the previous
    attempt's conclusion."""
    path = tmp_path / "state.json"
    state = finished_run(path, evidence_dir=str(tmp_path / "s1-first"))

    state.begin_run("s1", str(tmp_path / "s1-second"))

    assert state.capture_status("s1") is None


def test_a_started_run_completes_through_mark_recovered(tmp_path):
    path = tmp_path / "state.json"
    state = ready_for_s1(path)
    state.begin_run("s1", str(tmp_path / "s1"))

    state.mark_recovered("s1", str(tmp_path / "s1"))

    assert state.run_status("s1") == "recovered"
    assert state.evidence_dir("s1") == str(tmp_path / "s1")
    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.require_run("s2")

    state.record_capture("s1", "conclusion", str(tmp_path / "s1"))

    state.require_run("s2")  # must not raise


def test_a_started_run_completes_through_mark_failed(tmp_path):
    path = tmp_path / "state.json"
    state = ready_for_s1(path)
    state.begin_run("s1", str(tmp_path / "s1"))

    state.mark_failed("s1", str(tmp_path / "s1"), reason="alert never resolved")

    assert state.run_status("s1") == "failed"
    assert state.document["scenarios"]["s1"]["failure_reason"] == "alert never resolved"
    with pytest.raises(InvalidTransition, match="s1_recovered"):
        state.require_run("s2")


def test_begin_run_rejects_an_unknown_scenario(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    with pytest.raises(ValueError):
        state.begin_run("s9")


def test_require_run_rejects_an_unknown_scenario(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    with pytest.raises(ValueError):
        state.require_run("s9")


# --- One unfinished run blocks the whole lab, not just the next scenario ---


def completed_lab(path, evidence_root):
    """A lab whose three scenarios all ran, recovered and captured.

    Built through the real API, in order, so the precondition is a state
    the lab can actually reach -- the state an operator holds the moment
    every scenario has produced a conclusion.
    """
    state = ready_for_s1(path)
    for scenario in lab_state.SCENARIOS:
        directory = str(evidence_root / "{0}-first".format(scenario))
        state.begin_run(scenario, directory)
        state.mark_recovered(scenario, directory)
        state.record_capture(scenario, "conclusion", directory)
    return state


def break_rerun(state, scenario, evidence_dir, run_status):
    """Re-run `scenario` and leave it unfinished, `running` or `failed`."""
    state.begin_run(scenario, str(evidence_dir))
    if run_status == "failed":
        state.mark_failed(scenario, str(evidence_dir), reason="injection rejected")
    assert state.run_status(scenario) == run_status
    return state


@pytest.mark.parametrize("run_status", ("running", "failed"))
def test_a_broken_rerun_of_s1_blocks_s3_although_s2_is_still_captured(
    tmp_path, run_status
):
    """The residual gap: the ordered rules only look *backwards* one step.

    A finished lab re-runs S1; the re-run dies before it can record an
    outcome, or records a failure. S1 is then `running`/`failed` -- its
    fault may still be live in the shared workload -- but S3's own
    prerequisites (`s2_recovered`, `s2_captured`) are untouched, so S3 was
    admitted and injected a third fault on top of an incident nobody
    resolved. Every scenario shares one Container App, so an unfinished
    run has to block *every* other scenario, not only the next one.
    """
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s1", tmp_path / "s1-second", run_status)

    with pytest.raises(InvalidTransition) as refusal:
        state.require_run("s3")

    message = str(refusal.value)
    assert "s1" in message
    assert run_status in message


@pytest.mark.parametrize("run_status", ("running", "failed"))
@pytest.mark.parametrize("blocked", ("s2", "s3"))
def test_an_unfinished_s1_blocks_s2_and_s3(tmp_path, run_status, blocked):
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s1", tmp_path / "s1-second", run_status)

    with pytest.raises(InvalidTransition, match="s1"):
        state.require_run(blocked)


@pytest.mark.parametrize("run_status", ("running", "failed"))
@pytest.mark.parametrize("blocked", ("s1", "s3"))
def test_an_unfinished_s2_blocks_s1_and_s3(tmp_path, run_status, blocked):
    """S1 is *earlier* than S2 and no ordered rule mentions it, so nothing
    but the global gate can stop an operator from re-running S1 while S2's
    fault is still injected."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s2", tmp_path / "s2-second", run_status)

    with pytest.raises(InvalidTransition, match="s2"):
        state.require_run(blocked)


@pytest.mark.parametrize("run_status", ("running", "failed"))
@pytest.mark.parametrize("blocked", ("s1", "s2"))
def test_an_unfinished_s3_blocks_s1_and_s2(tmp_path, run_status, blocked):
    """The case no ordered rule can reach at all: S3 is the last scenario,
    so its unfinished run is invisible to every prerequisite list."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s3", tmp_path / "s3-second", run_status)

    with pytest.raises(InvalidTransition) as refusal:
        state.require_run(blocked)

    message = str(refusal.value)
    assert "s3" in message
    assert run_status in message


def test_a_running_scenario_cannot_be_started_again(tmp_path):
    """Two concurrent runs of one scenario overlap two injections of the
    same fault in one workload; the second one's evidence cannot be read."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    state.begin_run("s1", str(tmp_path / "s1-second"))

    with pytest.raises(InvalidTransition, match="running"):
        state.require_run("s1")


def test_a_failed_scenario_may_be_rerun_to_fix_itself(tmp_path):
    """Re-running the failed scenario is the documented remedy, so the gate
    must never block the one command that clears it."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s1", tmp_path / "s1-second", "failed")

    state.require_run("s1")  # must not raise
    state.begin_run("s1", str(tmp_path / "s1-third"))

    assert state.run_status("s1") == "running"


def test_two_failed_runs_at_once_still_leave_a_way_out(tmp_path):
    """The gate must not be able to lock the lab.

    Two scenarios `failed` at the same time is unreachable through the API
    -- S2 cannot start until S1 recovered and was captured, and re-running
    S1 is refused while S2 is failed -- but `state.json` is an editable
    file, and a rule that has no exit in *any* state it can be put into is
    a rule that eventually needs the file deleted. Repairing the earliest
    unfinished scenario is therefore always allowed, so working the list
    from the top always terminates.
    """
    path = tmp_path / "state.json"
    completed_lab(path, tmp_path)
    document = json.loads(path.read_text())
    for scenario in ("s1", "s2"):
        document["scenarios"][scenario]["run_status"] = "failed"
        document["scenarios"][scenario].pop("capture_status", None)
    path.write_text(json.dumps(document))
    state = lab_state.LabState(path)

    state.require_run("s1")  # the earliest failure may always be repaired

    with pytest.raises(lab_state.InvalidTransition, match="s1"):
        state.require_run("s2")
    with pytest.raises(lab_state.InvalidTransition, match="s1"):
        state.require_run("s3")


def test_the_refusal_lists_every_blocker_earliest_first(tmp_path):
    """One name is not enough when two runs are unfinished: an operator who
    clears only the one they were told about hits the next refusal blind.
    The list is ordered, so the first entry is the one to deal with.

    S1 has no ordered prerequisite naming S2 or S3, so this refusal can
    only come from the gate.
    """
    path = tmp_path / "state.json"
    completed_lab(path, tmp_path)
    document = json.loads(path.read_text())
    document["scenarios"]["s2"]["run_status"] = "running"
    document["scenarios"]["s3"]["run_status"] = "failed"
    path.write_text(json.dumps(document))
    state = lab_state.LabState(path)

    with pytest.raises(lab_state.InvalidTransition) as error:
        state.require_run("s1")

    message = str(error.value)
    assert message.index("s2") < message.index("s3"), message
    assert "running" in message and "failed" in message
    assert "mark-failed s2" in message
    assert "guides/04-scenario-s3.md" in message


def test_a_repair_is_refused_while_an_earlier_run_is_still_running(tmp_path):
    """`running` is not a repairable state -- nobody knows whether that run
    is still working -- so it blocks the later failure's repair too, and the
    remedy named is the one that ends it."""
    path = tmp_path / "state.json"
    completed_lab(path, tmp_path)
    document = json.loads(path.read_text())
    document["scenarios"]["s1"]["run_status"] = "running"
    document["scenarios"]["s2"]["run_status"] = "failed"
    path.write_text(json.dumps(document))
    state = lab_state.LabState(path)

    with pytest.raises(lab_state.InvalidTransition, match="mark-failed s1"):
        state.require_run("s2")


def test_the_refusal_names_the_blocking_scenario_its_status_and_a_remedy(tmp_path):
    """S1 has no ordered prerequisite that mentions S2, so this refusal can
    only come from the global gate: it has to carry everything the ordered
    message would have carried."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s2", tmp_path / "s2-second", "failed")

    with pytest.raises(InvalidTransition) as refusal:
        state.require_run("s1")

    message = str(refusal.value)
    assert "s2" in message
    assert "failed" in message
    assert "guides/03-scenario-s2.md" in message, message


def test_the_refusal_for_a_running_scenario_names_how_to_end_it(tmp_path):
    """A run that died leaves `running` behind for ever unless the operator
    is told the one command that records how it ended."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    state.begin_run("s1", str(tmp_path / "s1-second"))

    with pytest.raises(InvalidTransition) as refusal:
        state.require_run("s3")

    message = str(refusal.value)
    assert "s1" in message
    assert "running" in message
    assert "mark-failed s1" in message, message


def test_the_ordered_remedy_never_tells_an_operator_to_restart_a_running_run(tmp_path):
    """S2's ordered refusal names `s1_recovered`, whose remedy is normally
    "run S1 again". While S1 is still running that command is refused too,
    so the remedy has to change with the run's status instead of sending
    the operator into a second refusal.
    """
    state = completed_lab(tmp_path / "state.json", tmp_path)
    state.begin_run("s1", str(tmp_path / "s1-second"))

    with pytest.raises(InvalidTransition) as refusal:
        state.require_run("s2")

    message = str(refusal.value)
    assert "s1_recovered" in message
    assert "guides/02-scenario-s1.md" not in message, message
    assert "mark-failed s1" in message, message


def test_a_finished_lab_still_allows_a_normal_rerun_of_every_scenario(tmp_path):
    """`recovered` is a finished run: the gate must not turn the ordinary
    "run it again to collect a second capture" flow into a refusal."""
    state = completed_lab(tmp_path / "state.json", tmp_path)

    for scenario in lab_state.SCENARIOS:
        state.require_run(scenario)  # must not raise


def test_a_rerun_that_recovers_again_reopens_every_other_scenario(tmp_path):
    """The gate has to *clear*: once the unfinished run recovers, the lab
    goes back to being governed by the ordered rules alone."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s1", tmp_path / "s1-second", "failed")
    with pytest.raises(InvalidTransition):
        state.require_run("s3")

    state.begin_run("s1", str(tmp_path / "s1-third"))
    state.mark_recovered("s1", str(tmp_path / "s1-third"))

    state.require_run("s3")  # must not raise


def test_a_recovered_but_uncaptured_run_blocks_only_the_ordered_rules(tmp_path):
    """The rule this pins down, deliberately unchanged: `recovered` is a
    *finished* run -- the fault is reverted and the alert closed -- so it
    never trips the unfinished-run gate. A re-run of S1 that recovered but
    has not been captured yet therefore blocks S2 through the existing
    ordered rule (`s1_captured`) and leaves S3, whose own prerequisites
    (`s2_recovered`, `s2_captured`) are untouched, admitted. The ordered
    rules keep looking exactly one scenario back; the new gate adds nothing
    here because nothing is still running or failed.
    """
    state = completed_lab(tmp_path / "state.json", tmp_path)
    state.begin_run("s1", str(tmp_path / "s1-second"))
    state.mark_recovered("s1", str(tmp_path / "s1-second"))
    assert state.capture_status("s1") is None

    with pytest.raises(InvalidTransition, match="s1_captured"):
        state.require_run("s2")
    state.require_run("s3")  # must not raise
    state.require_run("s1")  # must not raise


def test_begin_run_is_refused_while_another_scenario_is_unfinished(tmp_path):
    """`begin_run` is what runs just before the injection, so it must refuse
    exactly what `require_run` refuses -- and record nothing when it does."""
    state = completed_lab(tmp_path / "state.json", tmp_path)
    break_rerun(state, "s1", tmp_path / "s1-second", "failed")

    with pytest.raises(InvalidTransition, match="s1"):
        state.begin_run("s3", str(tmp_path / "s3-second"))

    assert state.run_status("s3") == "recovered"
    assert state.capture_status("s3") == "conclusion"
    assert state.evidence_dir("s3") == str(tmp_path / "s3-first")


def test_the_gate_reads_what_is_on_disk_not_this_process_memory(tmp_path):
    path = tmp_path / "state.json"
    state = completed_lab(path, tmp_path)
    break_rerun(state, "s2", tmp_path / "s2-second", "failed")

    with pytest.raises(InvalidTransition) as refusal:
        LabState(path).require_run("s1")

    assert "s2" in str(refusal.value)
    assert "failed" in str(refusal.value)


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


# --- Only a recovered run may be credited with a conclusion -----------------


@pytest.mark.parametrize(
    "run_status", (None, "running", "failed"), ids=("none", "running", "failed")
)
def test_a_conclusion_cannot_be_recorded_against_a_run_that_never_recovered(
    tmp_path, run_status
):
    """`conclusion` is the one capture outcome that unblocks the next
    scenario and earns points, so it may only ever describe a run that
    actually recovered. A conclusion recorded while the scenario is
    `running`, `failed`, or has no recorded run at all belongs to an
    incident nobody resolved -- and the state file is the only place that
    can refuse it, because the timeline it came from looks identical.
    """
    state = ready_for_s1(tmp_path / "state.json")
    if run_status == "running":
        state.begin_run("s1", str(tmp_path / "s1"))
    elif run_status == "failed":
        state.mark_failed("s1", str(tmp_path / "s1"), reason="alert never resolved")

    with pytest.raises(InvalidTransition) as refusal:
        state.record_capture("s1", "conclusion", str(tmp_path / "s1"))

    assert "conclusion" in str(refusal.value)
    assert (run_status or "none") in str(refusal.value)
    assert state.capture_status("s1") is None
    assert not state.is_successful_capture("s1")


@pytest.mark.parametrize(
    "run_status, expected, forbidden",
    (
        ("running", "mark-failed s1", "guides/02-scenario-s1.md"),
        ("failed", "guides/02-scenario-s1.md", "mark-failed s1"),
        (None, "guides/02-scenario-s1.md", "mark-failed s1"),
    ),
    ids=("running", "failed", "none"),
)
def test_the_capture_refusal_names_a_command_that_is_not_itself_refused(
    tmp_path, run_status, expected, forbidden
):
    """Telling an operator to re-run a scenario that is still `running`
    sends them straight into the unfinished-run gate. The remedy has to be
    the one command the state actually admits."""
    state = ready_for_s1(tmp_path / "state.json")
    if run_status == "running":
        state.begin_run("s1", str(tmp_path / "s1"))
    elif run_status == "failed":
        state.mark_failed("s1", str(tmp_path / "s1"), reason="alert never resolved")

    with pytest.raises(InvalidTransition) as refusal:
        state.record_capture("s1", "conclusion", str(tmp_path / "s1"))

    assert expected in str(refusal.value)
    assert forbidden not in str(refusal.value)


@pytest.mark.parametrize(
    "missing_status",
    ("thread-not-created", "investigation-missing", "conclusion-missing"),
)
@pytest.mark.parametrize(
    "run_status", (None, "running", "failed"), ids=("none", "running", "failed")
)
def test_a_missing_marker_is_still_recorded_for_any_run_status(
    tmp_path, missing_status, run_status
):
    """Diagnostic honesty runs the other way: what the Agent failed to
    produce is worth recording whatever the run did, because it is the
    measurement an operator has to read. None of these markers can unblock
    anything or earn a point, so recording them is free of risk.
    """
    state = ready_for_s1(tmp_path / "state.json")
    if run_status == "running":
        state.begin_run("s1", str(tmp_path / "s1"))
    elif run_status == "failed":
        state.mark_failed("s1", str(tmp_path / "s1"), reason="alert never resolved")

    state.record_capture("s1", missing_status, str(tmp_path / "s1"))

    assert state.capture_status("s1") == missing_status
    assert not state.is_successful_capture("s1")
    assert not state.has("s1_captured")


def test_a_conclusion_is_recorded_once_the_run_recovered(tmp_path):
    state = ready_for_s1(tmp_path / "state.json")
    state.begin_run("s1", str(tmp_path / "s1"))
    state.mark_recovered("s1", str(tmp_path / "s1"))

    state.record_capture("s1", "conclusion", str(tmp_path / "s1"))

    assert state.is_successful_capture("s1")


def test_record_capture_refuses_to_downgrade_a_conclusion(tmp_path):
    state = lab_state.LabState(tmp_path / "state.json")
    state.mark_recovered("s1", str(tmp_path / "s1"))
    state.record_capture("s1", "conclusion")

    with pytest.raises(lab_state.InvalidTransition, match="already has a conclusion"):
        state.record_capture("s1", "thread-not-created")

    assert state.capture_status("s1") == "conclusion"


def test_cli_record_capture_refuses_a_conclusion_for_a_failed_run(tmp_path):
    path = tmp_path / "state.json"
    evidence_dir = tmp_path / "s1-20260814T000000Z"
    evidence_dir.mkdir()
    (evidence_dir / "normalized-timeline.json").write_text(
        json.dumps(
            [{"state": "alert-fired"}, {"state": "thread-created"}, {"state": "conclusion"}]
        )
    )
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")
    run_cli(path, ["mark-failed", "s1", str(evidence_dir), "--reason", "no alert"])

    result = run_cli(
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

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "failed" in result.stderr
    assert "capture_status" not in json.loads(path.read_text())["scenarios"]["s1"]


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


# --- Decoded JSON with the wrong shape is refused, never silently reset ----


@pytest.mark.parametrize(
    "document",
    (
        {"stages": []},
        {"stages": "baseline_passed"},
        {"stages": 1},
        {"stages": None},
        {"stages": {"baseline_passed": "yesterday"}},
        {"stages": {"baseline_passed": ["yesterday"]}},
        {"scenarios": []},
        {"scenarios": "s1"},
        {"scenarios": {"s1": "conclusion"}},
        {"scenarios": {"s1": ["conclusion"]}},
    ),
    ids=(
        "stages-list",
        "stages-string",
        "stages-int",
        "stages-null",
        "stage-entry-string",
        "stage-entry-list",
        "scenarios-list",
        "scenarios-string",
        "scenario-entry-string",
        "scenario-entry-list",
    ),
)
def test_a_state_file_with_the_wrong_json_shape_is_refused_not_reset(tmp_path, document):
    """Every field the module treats as a container (`stages`, `scenarios`,
    and each entry inside them) must actually be a JSON object once decoded.
    A wrong type here must become the same clean `LabStateError` a corrupt
    file produces -- never a raw `TypeError`/`AttributeError` traceback, and
    never a silent reset back to `{}` that would erase whatever an operator
    had already recorded."""
    path = tmp_path / "state.json"
    path.write_text(json.dumps(document))

    with pytest.raises(lab_state.LabStateError):
        LabState(path)

    # The refusal must not have rewritten the file with a fresh default.
    assert json.loads(path.read_text()) == document


def test_cli_reports_a_malformed_state_file_without_a_python_traceback(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"scenarios": "not-an-object"}))

    result = run_cli(path, ["show"])

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "scenarios" in result.stderr


# --- Concurrency is documented, not silently assumed away -------------------


def test_module_documents_that_concurrent_operators_are_unsupported():
    """No file locking guards `state.json` against two processes mutating
    it at once; that is a deliberate simplicity choice for a lab one person
    drives at a time, but it must be written down rather than left for
    someone to discover by racing two runs together."""
    assert lab_state.__doc__ is not None
    assert "concurrent" in lab_state.__doc__.lower()


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
    assert "guides/02-scenario-s1.md" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_begin_run_starts_a_new_attempt_and_blocks_the_next_scenario(tmp_path):
    """The command an operator runs between `require-run` and the
    first destructive Azure call: it must clear the finished attempt and
    leave the scenario `running`, which satisfies no gate."""
    path = tmp_path / "state.json"
    first = tmp_path / "s1-first"
    second = tmp_path / "s1-second"
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")
    run_cli(path, ["mark-recovered", "s1", str(first)])
    run_cli(path, ["record-capture", "s1", "--status", "conclusion", "--evidence-dir", str(first)])
    assert run_cli(path, ["require-run", "s2"]).returncode == 0

    started = run_cli(path, ["begin-run", "s1", str(second)])

    assert started.returncode == 0, started.stderr
    entry = json.loads(path.read_text())["scenarios"]["s1"]
    assert entry["run_status"] == "running"
    assert entry["evidence_dir"] == str(second)
    assert "capture_status" not in entry
    blocked = run_cli(path, ["require-run", "s2"])
    assert blocked.returncode == 1
    assert "s1_recovered" in blocked.stderr


def test_cli_begin_run_without_the_prerequisites_records_nothing(tmp_path):
    path = tmp_path / "state.json"

    result = run_cli(path, ["begin-run", "s1", str(tmp_path / "s1")])

    assert result.returncode == 1
    assert "baseline_passed" in result.stderr
    assert "agent_setup_acknowledged" in result.stderr
    assert "Traceback" not in result.stderr
    assert not path.exists() or "s1" not in json.loads(path.read_text())["scenarios"]


def seed_completed_lab(path, evidence_root):
    """Drive the CLI through a whole lab: three recovered, captured runs."""
    assert run_cli(path, ["mark", "baseline_passed"]).returncode == 0
    assert run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n").returncode == 0
    for scenario in lab_state.SCENARIOS:
        directory = str(evidence_root / "{0}-first".format(scenario))
        assert run_cli(path, ["begin-run", scenario, directory]).returncode == 0
        assert run_cli(path, ["mark-recovered", scenario, directory]).returncode == 0
        recorded = run_cli(
            path,
            ["record-capture", scenario, "--status", "conclusion", "--evidence-dir", directory],
        )
        assert recorded.returncode == 0, recorded.stderr
    return path


def test_cli_require_run_refuses_every_scenario_while_one_run_is_unfinished(tmp_path):
    """S3 is the last scenario, so no ordered rule mentions it: only the
    global gate can refuse S1 and S2 while its run is unfinished."""
    path = seed_completed_lab(tmp_path / "state.json", tmp_path)
    assert run_cli(path, ["begin-run", "s3", str(tmp_path / "s3-second")]).returncode == 0
    assert (
        run_cli(
            path, ["mark-failed", "s3", str(tmp_path / "s3-second"), "--reason", "rejected"]
        ).returncode
        == 0
    )

    for scenario in ("s1", "s2"):
        refused = run_cli(path, ["require-run", scenario])
        assert refused.returncode == 1, refused.stdout
        assert "s3" in refused.stderr
        assert "failed" in refused.stderr
        assert "guides/04-scenario-s3.md" in refused.stderr
        assert "Traceback" not in refused.stderr

    assert run_cli(path, ["require-run", "s3"]).returncode == 0


def test_cli_begin_run_refuses_while_another_scenario_is_still_running(tmp_path):
    path = seed_completed_lab(tmp_path / "state.json", tmp_path)
    assert run_cli(path, ["begin-run", "s3", str(tmp_path / "s3-second")]).returncode == 0
    before = path.read_text()

    refused = run_cli(path, ["begin-run", "s1", str(tmp_path / "s1-second")])

    assert refused.returncode == 1, refused.stdout
    assert "s3" in refused.stderr
    assert "running" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert path.read_text() == before


def test_cli_begin_run_refuses_a_state_file_from_another_environment(tmp_path):
    """A run must never start against a state file another lab wrote: the
    binding check has to fail before the attempt is recorded, so the file
    keeps describing the lab it belongs to."""
    path = tmp_path / "state.json"
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")
    before = path.read_text()

    result = run_cli(
        path,
        ["begin-run", "s1", str(tmp_path / "s1")],
        env={"AZURE_RESOURCE_GROUP": "rg-somewhere-else"},
    )

    assert result.returncode == 1
    assert "rg-somewhere-else" in result.stderr
    assert "Traceback" not in result.stderr
    assert path.read_text() == before


def test_cli_marks_a_started_run_recovered_and_then_captured(tmp_path):
    path = tmp_path / "state.json"
    evidence_dir = tmp_path / "s1-20260814T000000Z"
    evidence_dir.mkdir()
    run_cli(path, ["mark", "baseline_passed"])
    run_cli(path, ["acknowledge-agent"], stdin="acknowledge\n")
    assert run_cli(path, ["begin-run", "s1", str(evidence_dir)]).returncode == 0

    assert run_cli(path, ["mark-recovered", "s1", str(evidence_dir)]).returncode == 0
    recorded = run_cli(
        path,
        ["record-capture", "s1", "--status", "conclusion", "--evidence-dir", str(evidence_dir)],
    )

    assert recorded.returncode == 0, recorded.stderr
    assert run_cli(path, ["require-run", "s2"]).returncode == 0


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
