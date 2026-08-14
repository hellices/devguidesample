"""Execution tests for the lab's four shell entry points.

Each script is run as a program against fake `az`/`azd`/`python`
executables, from a working directory that is not the lab. Running them
proves what reading their text cannot: that configuration actually loads,
that no variable a script assigns collides with a `readonly` name
`common.sh` already declared, and that the safety checks run before any
Azure operation.
"""
import json

import pytest

from lab_script_harness import (
    ENV_NAME,
    MISSING_CONCLUSION_TIMELINE,
    RESOURCE_GROUP,
    SUBSCRIPTION_ID,
    make_lab,
)


CALLERS = ("run-scenario.sh", "query-evidence.sh", "capture-scenario.sh", "cleanup.sh")

# Short enough that a genuinely unbounded wait fails the test instead of
# hanging the suite, long enough for several poll rounds.
BOUNDED_WAITS = {
    "LAB_ALERT_RESOLVE_TIMEOUT_SECONDS": "5",
    "LAB_ALERT_RESOLVE_POLL_INTERVAL_SECONDS": "1",
    "LAB_RECOVERY_HEALTH_TIMEOUT_SECONDS": "5",
    "LAB_REVISION_READY_TIMEOUT_SECONDS": "5",
    "LAB_REVISION_READY_POLL_INTERVAL_SECONDS": "1",
}

NO_ALERT_WAITS = dict(
    BOUNDED_WAITS,
    LAB_ALERT_FIRE_TIMEOUT_SECONDS="3",
    LAB_ALERT_FIRE_POLL_INTERVAL_SECONDS="1",
)


def captured(scenario, evidence_dir):
    """The state entry of a scenario that already ran and captured cleanly."""
    return {
        scenario: {
            "run_status": "recovered",
            "capture_status": "conclusion",
            "evidence_dir": str(evidence_dir),
        }
    }


def _assert_loaded_config(result, lab_run):
    """Every caller must get past `require_lab_config` + the safety checks."""
    assert "readonly variable" not in result.stderr, (
        "a script assigned a name common.sh already made readonly: "
        f"{result.stderr!r}"
    )
    assert "azd env set" not in result.stderr, (
        f"configuration failed to load: {result.stderr!r}"
    )
    az_calls = lab_run.az_calls()
    assert "account show" in az_calls, (
        f"verify_subscription never ran: {az_calls!r} / {result.stderr!r}"
    )
    assert 'tags."azd-env-name"' in az_calls, (
        f"verify_lab_resource_group never ran: {az_calls!r}"
    )
    assert f"cwd={lab_run.lab}" in lab_run.azd_calls(), (
        "azd lookups must be pinned to the lab project root: "
        f"{lab_run.azd_calls()!r}"
    )


def test_run_scenario_s1_runs_to_completion_from_another_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stderr
    evidence_dirs = sorted((lab_run.lab / "evidence").glob("s1-*"))
    assert evidence_dirs, "no evidence directory was created"
    timeline = json.loads((evidence_dirs[-1] / "timeline.json").read_text())
    assert timeline["scenario"] == "s1"
    assert timeline["injected_at"]
    assert timeline["alert_id"]
    assert timeline["recovered_at"]
    assert "FAILURE_MODE=none" in lab_run.az_calls(), "the scenario never recovered"

    # The evidence is only usable if the recorded moments really bracket the
    # Azure operations they claim to describe.
    update_times = [
        line.split("\t")[1]
        for line in lab_run.az_calls().splitlines()
        if "containerapp update" in line
    ]
    assert update_times, "the failure was never injected"
    assert timeline["injected_at"] <= update_times[0], (
        "injected_at must be recorded before the Container App is updated"
    )
    assert update_times[0] <= timeline["revision_ready_at"]
    assert timeline["revision_ready_at"] <= timeline["recovered_at"]


def test_query_evidence_collects_every_artifact_from_another_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "evidence-out"

    result = lab_run.run(
        "query-evidence.sh",
        ["s1", str(evidence_dir), "2026-08-14T00:00:00Z", "2026-08-14T01:00:00Z"],
    )

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stderr
    for artifact in (
        "app-requests.json",
        "app-dependencies.json",
        "app-exceptions.json",
        "activity-log.json",
        "alerts.json",
        "revisions-redacted.json",
        "storage-role-assignments.json",
        "query-window.json",
    ):
        assert (evidence_dir / artifact).is_file(), f"missing {artifact}"
    window = json.loads((evidence_dir / "query-window.json").read_text())
    assert window["scenario"] == "s1"


def test_query_evidence_queries_the_resolved_workspace_and_principal(tmp_path):
    """The values that used to collide with `common.sh`'s readonly names
    (the workspace customer ID and the workload principal ID) must reach the
    Azure CLI calls that consume them."""
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "evidence-out"

    result = lab_run.run(
        "query-evidence.sh",
        ["s1", str(evidence_dir), "2026-08-14T00:00:00Z", "2026-08-14T01:00:00Z"],
    )

    assert result.returncode == 0, result.stderr
    az_calls = lab_run.az_calls()
    assert "--workspace 9d1a0b2c-3d4e-5f60-7182-93a4b5c6d7e8" in az_calls
    assert "--assignee-object-id 8c8a4f0e-0000-4000-8000-2b1f9a0c1234" in az_calls


def test_run_scenario_refuses_a_scenario_the_state_does_not_allow(tmp_path):
    """No baseline and no acknowledgement recorded: the failure must be
    injected into nothing at all."""
    lab_run = make_lab(tmp_path)

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "baseline_passed" in result.stderr
    assert "agent_setup_acknowledged" in result.stderr
    assert "containerapp update" not in lab_run.az_calls(), (
        "run-scenario.sh injected a failure before checking the run order"
    )
    assert not sorted((lab_run.lab / "evidence").glob("s1-*"))


def test_run_scenario_s2_refuses_to_start_before_s1_was_captured(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.seed_state(
        scenarios={"s1": {"run_status": "recovered", "evidence_dir": str(tmp_path / "s1")}}
    )

    result = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "s1_captured" in result.stderr
    assert "containerapp update" not in lab_run.az_calls()


def test_run_scenario_s2_starts_once_s1_recovered_and_was_captured(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.seed_state(scenarios=captured("s1", tmp_path / "s1"))

    result = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ORDER_DELAY_MS=4000" in lab_run.az_calls()
    assert lab_run.scenario_state("s2")["run_status"] == "recovered"


def test_run_scenario_records_recovery_only_after_the_alert_resolved(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stdout + result.stderr
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]
    scenario_state = lab_run.scenario_state("s1")
    assert scenario_state["run_status"] == "recovered"
    assert scenario_state["evidence_dir"] == str(evidence_dir)
    timeline = json.loads((evidence_dir / "timeline.json").read_text())
    assert timeline["alert_resolved_at"], "the resolved moment was never recorded"
    assert timeline["recovered_at"] <= timeline["alert_resolved_at"]


def test_run_scenario_fails_when_the_alert_never_resolves(tmp_path):
    """An alert Azure Monitor never closed means the workload is not proven
    healthy again: the run stays failed, so the next scenario cannot start
    on top of an unresolved incident."""
    lab_run = make_lab(tmp_path, alert_resolves=False)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "Resolved" in result.stderr
    assert "FAILURE_MODE=none" in lab_run.az_calls(), (
        "the injected failure must still be reverted before the run gives up"
    )
    assert lab_run.scenario_state("s1")["run_status"] == "failed"
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]
    timeline = json.loads((evidence_dir / "timeline.json").read_text())
    assert timeline["alert_resolved_at"] is None


def test_run_scenario_marks_failed_when_the_alert_never_fires(tmp_path):
    """No alert ever firing is a different failure than one that fires and
    never resolves: nothing to recover from Azure Monitor's point of view,
    but the run is still unusable evidence. It must be recorded as failed
    -- with the evidence directory and a reason -- exactly like every other
    failed run, and the fault that was injected must still be reverted by
    the same recovery trap that protects every other exit path."""
    lab_run = make_lab(tmp_path, alert_fires=False)
    lab_run.seed_state()

    result = lab_run.run(
        "run-scenario.sh",
        ["s1"],
        env=NO_ALERT_WAITS,
    )

    assert result.returncode != 0
    assert "did not fire" in result.stderr
    assert "FAILURE_MODE=none" in lab_run.az_calls(), (
        "the injected failure must still be reverted even though no alert ever fired"
    )
    scenario_state = lab_run.scenario_state("s1")
    assert scenario_state["run_status"] == "failed"
    assert "did not fire" in scenario_state.get("failure_reason", "")
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]
    assert scenario_state["evidence_dir"] == str(evidence_dir)


def test_run_scenario_s1_reports_a_rejected_recovery_update_as_critical(tmp_path):
    """`recover` runs both directly and from the EXIT trap, and the trap
    calls it as `if ! recover`, which turns `set -e` off for the whole
    function body. A recovery whose `az containerapp update` was rejected
    must therefore report the failure by return value: otherwise the fault
    is still injected in a live Container App while the script exits
    claiming it recovered."""
    lab_run = make_lab(tmp_path, recovery_update_fails=True)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "CRITICAL" in result.stderr, (
        "a failed recovery must be reported as CRITICAL, not swallowed: "
        f"{result.stderr!r}"
    )
    assert lab_run.scenario_state("s1").get("run_status") != "recovered", (
        "a run whose recovery failed must never be recorded as recovered"
    )
    attempts = [
        line
        for line in lab_run.az_calls().splitlines()
        if "containerapp update" in line and "FAILURE_MODE=none" in line
    ]
    assert len(attempts) >= 2, (
        "a failed recovery must not mark itself recovered, so the EXIT trap "
        f"has to try again: {attempts!r}"
    )


def test_run_scenario_s2_reports_a_stalled_recovery_revision_as_critical(tmp_path):
    """The recovery update is accepted but no new healthy revision ever
    becomes active: the workload is still slow, so the wait timing out has
    to fail the recovery instead of falling through to success."""
    lab_run = make_lab(tmp_path, recovery_revision_stalls=True)
    lab_run.seed_state(scenarios=captured("s1", tmp_path / "s1"))

    result = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "CRITICAL" in result.stderr, (
        f"a timed-out recovery wait must be reported as CRITICAL: {result.stderr!r}"
    )
    assert lab_run.scenario_state("s2").get("run_status") != "recovered"
    assert "ORDER_DELAY_MS=0" in lab_run.az_calls(), "recovery was never attempted"


def test_run_scenario_s3_reports_a_failed_role_restore_from_the_exit_trap(tmp_path):
    """The S3 fault is a deleted role assignment and the alert never fires,
    so recovery only ever runs from the EXIT trap -- the exact path where
    `if ! recover` disables `set -e`. A refused `az role assignment create`
    must still surface: the workload is left without its blob permission
    until an operator restores it."""
    lab_run = make_lab(tmp_path, alert_fires=False, role_create_fails=True)
    lab_run.seed_state(
        scenarios=dict(
            captured("s1", tmp_path / "s1"), **captured("s2", tmp_path / "s2")
        )
    )

    result = lab_run.run("run-scenario.sh", ["s3"], env=NO_ALERT_WAITS)

    assert result.returncode != 0
    assert "role assignment create" in lab_run.az_calls(), (
        "the exit trap never tried to restore the deleted role assignment"
    )
    assert "CRITICAL" in result.stderr, (
        "a refused role restore must be reported as CRITICAL, not swallowed: "
        f"{result.stderr!r}"
    )
    assert lab_run.scenario_state("s3").get("run_status") != "recovered"


def test_run_scenario_s3_recovers_and_records_a_successful_run(tmp_path):
    """The unchanged happy path: the blob role is restored, the alert
    resolves, and the run is recorded as recovered."""
    lab_run = make_lab(tmp_path)
    lab_run.seed_state(
        scenarios=dict(
            captured("s1", tmp_path / "s1"), **captured("s2", tmp_path / "s2")
        )
    )

    result = lab_run.run("run-scenario.sh", ["s3"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CRITICAL" not in result.stderr
    assert "role assignment delete" in lab_run.az_calls()
    assert "role assignment create" in lab_run.az_calls()
    assert lab_run.scenario_state("s3")["run_status"] == "recovered"


def test_a_failed_run_blocks_the_next_scenario(tmp_path):
    lab_run = make_lab(tmp_path, alert_resolves=False)
    lab_run.seed_state()
    first = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert first.returncode != 0

    result = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "s1_recovered" in result.stderr


# --- A re-run that dies early never leaves the previous success standing ---


@pytest.mark.parametrize("break_the_rerun", ("injection", "recovery"))
def test_a_rerun_that_dies_early_retires_the_previous_success(tmp_path, break_the_rerun):
    """S1 recovers and captures a real conclusion, then is re-run and the
    re-run fails *before* it can record any outcome of its own -- the
    injecting `az containerapp update` is rejected, or the recovery is and
    the EXIT trap gives up.

    Without an attempt recorded before the first destructive call, the
    scenario entry still read `recovered` + `conclusion` from the run that
    was just superseded, so `run-scenario.sh s2` was admitted and injected
    a second fault into a workload whose first incident had not been
    reproduced. The started attempt has to clear that, so every later gate
    -- the next scenario and the scorer -- refuses.
    """
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    first_run = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert first_run.returncode == 0, first_run.stderr
    first_capture = lab_run.run("capture-scenario.sh", ["s1"])
    assert first_capture.returncode == 0, first_capture.stderr
    finished = lab_run.scenario_state("s1")
    assert set(finished) == {
        "run_status",
        "started_at",
        "capture_status",
        "evidence_dir",
    }, finished
    assert finished["run_status"] == "recovered"
    assert finished["capture_status"] == "conclusion"
    first_evidence_dir = finished["evidence_dir"]

    if break_the_rerun == "injection":
        lab_run.break_injection()
    else:
        lab_run.break_recovery()
    rerun = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert rerun.returncode != 0, rerun.stdout
    entry = lab_run.scenario_state("s1")
    assert entry.get("run_status") in ("running", "failed"), entry
    assert "capture_status" not in entry, (
        "a conclusion captured against the superseded run must not survive "
        f"the re-run: {entry!r}"
    )
    assert entry.get("evidence_dir") != first_evidence_dir, (
        "the re-run must not keep pointing at the previous attempt's evidence"
    )

    blocked = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)

    assert blocked.returncode != 0, blocked.stdout
    assert "s1_recovered" in blocked.stderr
    assert "ORDER_DELAY_MS=4000" not in lab_run.az_calls(), (
        "S2 injected its fault although S1's re-run never recovered"
    )
    scored = lab_run.run("lab.sh", ["score"])
    assert scored.returncode != 0, scored.stdout
    assert "lab.sh run" in scored.stderr


def test_a_started_run_is_recorded_before_the_fault_is_injected(tmp_path):
    """Ordering is the whole point: the attempt must be persisted *before*
    the first destructive Azure call, because that call is what can fail
    and leave nothing else to write the state."""
    lab_run = make_lab(tmp_path, injection_update_fails=True)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    entry = lab_run.scenario_state("s1")
    assert entry.get("run_status") in ("running", "failed"), entry
    assert entry.get("started_at", "").endswith("Z"), entry
    evidence_dirs = sorted((lab_run.lab / "evidence").glob("s1-*"))
    assert entry.get("evidence_dir") == str(evidence_dirs[-1])


def test_a_started_run_is_completed_by_a_healthy_run(tmp_path):
    """The started attempt is a transition, not a terminal state: a run
    that recovers must end as `recovered`, with no `running` left behind."""
    lab_run = make_lab(tmp_path)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stdout + result.stderr
    assert lab_run.scenario_state("s1")["run_status"] == "recovered"


def test_run_scenario_refuses_a_state_file_from_another_environment(tmp_path):
    """A `state.json` left behind by another lab must never unlock a run
    here: the file records the environment, subscription and resource group
    it belongs to, and every command checks them."""
    lab_run = make_lab(tmp_path)
    lab_run.seed_state(environment="sre-lab-somewhere-else")

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode != 0
    assert "sre-lab-somewhere-else" in result.stderr
    assert "containerapp update" not in lab_run.az_calls()


def test_run_scenario_binds_new_state_to_the_current_environment(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.state_path.unlink(missing_ok=True)
    lab_run.seed_state()

    result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)

    assert result.returncode == 0, result.stdout + result.stderr
    state = lab_run.state()
    assert state["environment"] == ENV_NAME
    assert state["subscription_id"] == SUBSCRIPTION_ID
    assert state["resource_group"] == RESOURCE_GROUP


def test_capture_scenario_resolves_the_evidence_directory_from_the_state(tmp_path):
    """The public command is `lab.sh capture s1` -- no timestamped path --
    so `capture-scenario.sh` has to find the directory the recorded run
    wrote, not the newest directory that happens to be on disk."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr
    evidence_dir = sorted((lab_run.lab / "evidence").glob("s1-*"))[-1]

    result = lab_run.run("capture-scenario.sh", ["s1"])

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (evidence_dir / "normalized-timeline.json").is_file()
    assert (lab_run.lab / "assets" / "captures" / "s1" / "investigation.gif").is_file()
    assert lab_run.scenario_state("s1")["capture_status"] == "conclusion"


def test_capture_scenario_refuses_an_explicit_evidence_directory(tmp_path):
    """The legacy second argument let a capture of *any* directory be
    recorded as this environment's current capture status -- re-rendering an
    old run would unblock the next scenario on evidence that does not belong
    to the alert being captured. The public script takes the scenario only;
    regenerating artifacts from an archived directory is a `capture_agent.py`
    / `render_capture.py` job, which records no state."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    stale_dir = tmp_path / "evidence-out"
    stale_dir.mkdir()
    (stale_dir / "timeline.json").write_text(
        json.dumps({"scenario": "s1", "alert_id": "/alerts/aaaa0000"})
    )

    result = lab_run.run("capture-scenario.sh", ["s1", str(stale_dir)])

    assert result.returncode == 2, result.stdout + result.stderr
    assert "Usage:" in result.stderr
    assert str(stale_dir) not in result.stderr
    assert not (stale_dir / "normalized-timeline.json").exists(), (
        "an explicit directory must never be captured"
    )
    assert not lab_run.scenario_state("s1"), (
        "a rejected invocation must not record a capture status"
    )


def test_capture_scenario_usage_documents_only_the_scenario_argument(tmp_path):
    lab_run = make_lab(tmp_path)

    result = lab_run.run("capture-scenario.sh", [])

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert "EVIDENCE_DIR" not in result.stderr


def test_capture_scenario_records_a_missing_conclusion_as_itself(tmp_path):
    lab_run = make_lab(tmp_path, capture_timeline=MISSING_CONCLUSION_TIMELINE)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr

    result = lab_run.run("capture-scenario.sh", ["s1"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert lab_run.scenario_state("s1")["capture_status"] == "conclusion-missing"
    assert "conclusion-missing" in result.stdout
    blocked = lab_run.run("run-scenario.sh", ["s2"], env=BOUNDED_WAITS)
    assert blocked.returncode != 0
    assert "s1_captured" in blocked.stderr


def test_capture_scenario_without_a_recorded_run_names_the_command_to_run(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    lab_run.seed_state()

    result = lab_run.run("capture-scenario.sh", ["s1"])

    assert result.returncode != 0
    assert "No such file or directory" not in result.stderr
    assert "lab.sh run s1" in result.stderr


def test_capture_scenario_fails_actionably_when_venv_is_missing(tmp_path):
    """Finding #1: cloud resources (the alert rules, the app, etc.) may
    already be deployed by the time this local-only precondition fails, so
    the message must name the exact rerun command, not just what's wrong."""
    lab_run = make_lab(tmp_path, venv_present=False)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr

    result = lab_run.run("capture-scenario.sh", ["s1"])

    assert result.returncode != 0
    assert "Missing Python environment" in result.stderr
    assert "setup-venv.sh" in result.stderr


def test_capture_scenario_fails_actionably_when_pillow_is_not_importable(tmp_path):
    lab_run = make_lab(tmp_path, pillow_importable=False)
    lab_run.write_agent_setup()
    lab_run.seed_state()
    run_result = lab_run.run("run-scenario.sh", ["s1"], env=BOUNDED_WAITS)
    assert run_result.returncode == 0, run_result.stderr

    result = lab_run.run("capture-scenario.sh", ["s1"])

    assert result.returncode != 0
    assert "Pillow" in result.stderr
    assert "setup-venv.sh" in result.stderr


def test_cleanup_dry_run_plans_without_deleting_from_another_directory(tmp_path):
    """`cleanup.sh` is a compatibility wrapper around the external cleanup
    `azd down` runs: it plans the recorded role-assignment removal and never
    proposes a resource-group deletion of its own."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh")

    assert result.returncode == 0, result.stderr
    assert "azd down --purge" in result.stdout
    assert "Planned external cleanup" in result.stdout
    assert f"Delete tagged resource group: {RESOURCE_GROUP}" not in result.stdout
    assert "Dry run only" in result.stdout
    az_calls = lab_run.az_calls()
    assert "group delete" not in az_calls, "a dry run must delete nothing"
    assert "role assignment delete" not in az_calls


def test_cleanup_deletes_only_the_recorded_external_assignments(tmp_path):
    """Even with --yes, the wrapper must not delete a resource group: that
    is `azd down`'s job, and a broad deletion here would take resources azd
    never created with it."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh", ["--yes"])

    assert result.returncode == 0, result.stderr
    az_calls = lab_run.az_calls()
    assert "role assignment delete --ids /subscriptions/" in az_calls
    assert "group delete" not in az_calls


def test_cleanup_legacy_flag_deletes_the_tagged_resource_group(tmp_path):
    """The pre-azd resource groups still have to be recoverable by hand, so
    the broad deletion stays available behind an explicit flag -- after the
    same tag and subscription checks it always ran."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run(
        "cleanup.sh", ["--legacy-delete-resource-group", "--yes"]
    )

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stderr
    az_calls = lab_run.az_calls()
    assert f"group delete --name {RESOURCE_GROUP} --yes --no-wait" in az_calls
    assert "role assignment delete --ids /subscriptions/" in az_calls


def test_cleanup_legacy_dry_run_plans_the_resource_group_deletion(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh", ["--legacy-delete-resource-group"])

    assert result.returncode == 0, result.stderr
    assert f"Delete tagged resource group: {RESOURCE_GROUP}" in result.stdout
    assert "group delete" not in lab_run.az_calls()


@pytest.mark.parametrize("script_name", CALLERS)
def test_every_caller_fails_closed_when_configuration_is_missing(script_name, tmp_path):
    """No azd value and no explicit environment: every entry point must stop
    with the actionable `azd env set` message before touching Azure."""
    lab_run = make_lab(tmp_path, azd_values={})
    lab_run.write_agent_setup()
    arguments = {
        "run-scenario.sh": ["s1"],
        "query-evidence.sh": [
            "s1",
            str(tmp_path / "out"),
            "2026-08-14T00:00:00Z",
            "2026-08-14T01:00:00Z",
        ],
        "capture-scenario.sh": ["s1"],
        "cleanup.sh": [],
    }[script_name]

    result = lab_run.run(script_name, arguments)

    assert result.returncode != 0
    assert "azd env set AZURE_SUBSCRIPTION_ID" in result.stderr
    assert "group delete" not in lab_run.az_calls()
    assert "containerapp update" not in lab_run.az_calls()


@pytest.mark.parametrize("script_name", CALLERS)
def test_every_caller_refuses_a_foreign_subscription(script_name, tmp_path):
    """The subscription-equality boundary must hold for every entry point."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    arguments = {
        "run-scenario.sh": ["s1"],
        "query-evidence.sh": [
            "s1",
            str(tmp_path / "out"),
            "2026-08-14T00:00:00Z",
            "2026-08-14T01:00:00Z",
        ],
        "capture-scenario.sh": ["s1"],
        "cleanup.sh": ["--yes"],
    }[script_name]

    result = lab_run.run(
        script_name,
        arguments,
        env={"AZURE_SUBSCRIPTION_ID": "99999999-9999-9999-9999-999999999999"},
    )

    assert result.returncode != 0
    assert "Refusing to continue in subscription" in result.stderr
    assert "Expected 99999999" in result.stderr
    az_calls = lab_run.az_calls()
    assert "group delete" not in az_calls
    assert "containerapp update" not in az_calls
    assert "role assignment delete" not in az_calls


def test_environment_name_tag_mismatch_stops_every_caller(tmp_path):
    """A resource group tagged for another azd environment is refused even
    when its purpose tag matches -- including on the legacy recovery path,
    the only one that still deletes a resource group."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run(
        "cleanup.sh",
        ["--legacy-delete-resource-group", "--yes"],
        env={"AZURE_ENV_NAME": f"{ENV_NAME}-other"},
    )

    assert result.returncode != 0
    assert "Refusing to operate on untagged resource group" in result.stderr
    assert "group delete" not in lab_run.az_calls()


def test_subscription_id_is_read_from_the_azd_environment(tmp_path):
    """Nothing in the callers may pin a subscription of its own."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh")

    assert result.returncode == 0, result.stderr
    assert SUBSCRIPTION_ID in lab_run.az_calls()
