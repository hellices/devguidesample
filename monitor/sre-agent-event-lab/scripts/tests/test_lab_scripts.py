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

from lab_script_harness import ENV_NAME, RESOURCE_GROUP, SUBSCRIPTION_ID, make_lab


CALLERS = ("run-scenario.sh", "query-evidence.sh", "capture-scenario.sh", "cleanup.sh")


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

    result = lab_run.run("run-scenario.sh", ["s1"])

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


def test_capture_scenario_renders_from_another_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()
    evidence_dir = tmp_path / "evidence-out"
    evidence_dir.mkdir()
    (evidence_dir / "timeline.json").write_text(
        json.dumps({"scenario": "s1", "alert_id": "/alerts/aaaa0000"})
    )

    result = lab_run.run("capture-scenario.sh", ["s1", str(evidence_dir)])

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stderr
    assert (evidence_dir / "normalized-timeline.json").is_file()
    assert (lab_run.lab / "assets" / "captures" / "s1" / "investigation.gif").is_file()


def test_cleanup_dry_run_plans_without_deleting_from_another_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh")

    _assert_loaded_config(result, lab_run)
    assert result.returncode == 0, result.stderr
    assert "Planned cleanup:" in result.stdout
    assert f"Delete tagged resource group: {RESOURCE_GROUP}" in result.stdout
    assert "Dry run only" in result.stdout
    az_calls = lab_run.az_calls()
    assert "group delete" not in az_calls, "a dry run must delete nothing"
    assert "role assignment delete" not in az_calls


def test_cleanup_deletes_only_after_confirmation(tmp_path):
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run("cleanup.sh", ["--yes"])

    assert result.returncode == 0, result.stderr
    az_calls = lab_run.az_calls()
    assert f"group delete --name {RESOURCE_GROUP} --yes --no-wait" in az_calls
    assert "role assignment delete --ids /subscriptions/" in az_calls


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
        "capture-scenario.sh": ["s1", str(tmp_path / "out")],
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
        "capture-scenario.sh": ["s1", str(tmp_path / "out")],
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
    when its purpose tag matches."""
    lab_run = make_lab(tmp_path)
    lab_run.write_agent_setup()

    result = lab_run.run(
        "cleanup.sh",
        ["--yes"],
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
