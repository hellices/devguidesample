"""Execution tests for `query-evidence.sh`.

The lab is walked by hand: the guides run `az` and the Python tools
directly. `query-evidence.sh` is the one shell entry point an operator
still invokes, because collecting a scenario's evidence means running eight
queries whose results have to land in files `score.py` can read.

It is run here as a program against fake `az`/`azd` executables, from a
working directory that is not the lab. Running it proves what reading its
text cannot: that configuration actually loads, that no variable it assigns
collides with a `readonly` name `common.sh` already declared, and that the
subscription and resource-group checks run before any Azure call.
"""
import json

from lab_script_harness import (
    AZD_VALUES,
    ENV_NAME,
    SUBSCRIPTION_ID,
    make_lab,
)


WINDOW = ["2026-08-14T00:00:00Z", "2026-08-14T01:00:00Z"]


def query_arguments(evidence_dir):
    return ["s1", str(evidence_dir), *WINDOW]


def _assert_loaded_config(result, lab_run):
    """The script must get past `require_lab_config` + the safety checks."""
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


def test_query_evidence_collects_every_artifact_from_another_directory(tmp_path):
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "evidence-out"

    result = lab_run.run("query-evidence.sh", query_arguments(evidence_dir))

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

    result = lab_run.run("query-evidence.sh", query_arguments(evidence_dir))

    assert result.returncode == 0, result.stderr
    az_calls = lab_run.az_calls()
    assert "--workspace 9d1a0b2c-3d4e-5f60-7182-93a4b5c6d7e8" in az_calls
    assert "--assignee-object-id 8c8a4f0e-0000-4000-8000-2b1f9a0c1234" in az_calls


def test_query_evidence_refuses_missing_outputs_before_writing_artifacts(tmp_path):
    values = dict(AZD_VALUES)
    values["containerAppPrincipalId"] = ""
    values["AZURE_STORAGE_CONTAINER_SCOPE"] = ""
    lab_run = make_lab(tmp_path, azd_values=values)
    evidence_dir = tmp_path / "evidence-out"

    result = lab_run.run("query-evidence.sh", query_arguments(evidence_dir))

    assert result.returncode != 0
    assert "containerAppPrincipalId" in result.stderr
    assert "storageContainerScope" in result.stderr
    assert "azd provision" in result.stderr
    assert not evidence_dir.exists()


def test_query_evidence_fails_closed_when_configuration_is_missing(tmp_path):
    """No azd value and no explicit environment: the entry point must stop
    with the actionable `azd env set` message before touching Azure."""
    lab_run = make_lab(tmp_path, azd_values={})
    evidence_dir = tmp_path / "out"

    result = lab_run.run("query-evidence.sh", query_arguments(evidence_dir))

    assert result.returncode != 0
    assert "azd env set AZURE_SUBSCRIPTION_ID" in result.stderr
    assert "monitor log-analytics" not in lab_run.az_calls()


def test_query_evidence_refuses_a_foreign_subscription(tmp_path):
    """The subscription-equality boundary must hold before any query runs."""
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "out"

    result = lab_run.run(
        "query-evidence.sh",
        query_arguments(evidence_dir),
        env={"AZURE_SUBSCRIPTION_ID": "99999999-9999-9999-9999-999999999999"},
    )

    assert result.returncode != 0
    assert "Refusing to continue in subscription" in result.stderr
    assert "Expected 99999999" in result.stderr
    assert "monitor log-analytics" not in lab_run.az_calls()


def test_a_resource_group_tagged_for_another_environment_is_refused(tmp_path):
    """The purpose tag alone is not enough: a group belonging to a different
    azd environment is someone else's lab."""
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "out"

    result = lab_run.run(
        "query-evidence.sh",
        query_arguments(evidence_dir),
        env={"AZURE_ENV_NAME": f"{ENV_NAME}-other"},
    )

    assert result.returncode != 0
    assert "Refusing to operate on untagged resource group" in result.stderr
    assert "monitor log-analytics" not in lab_run.az_calls()


def test_subscription_id_is_read_from_the_azd_environment(tmp_path):
    """Nothing in the lab may pin a subscription of its own."""
    lab_run = make_lab(tmp_path)
    evidence_dir = tmp_path / "out"

    result = lab_run.run("query-evidence.sh", query_arguments(evidence_dir))

    assert result.returncode == 0, result.stderr
    assert SUBSCRIPTION_ID in lab_run.az_calls()
