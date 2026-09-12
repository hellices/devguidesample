import json
from pathlib import Path

import pytest


def test_new_state_is_bound_to_explicit_subscription():
    from cloud_lab import new_state

    state = new_state(
        {"id": "subscription-example", "tenantId": "tenant-example"},
        "operator-example",
        "koreacentral",
        "a1b2c3d4",
    )
    assert state["subscription_id"] == "subscription-example"
    assert state["resource_group"] == "rg-mcplab-a1b2c3d4"
    assert state["foundation_outputs"] == {}
    assert state["stage"] == "planned"


def test_refuses_cloud_state_inside_public_repository(tmp_path, monkeypatch):
    from cloud_lab import private_path

    monkeypatch.setattr("cloud_lab.REPO_ROOT", tmp_path)
    with pytest.raises(ValueError, match="outside"):
        private_path(tmp_path / "samples" / "state.json")


def test_saved_state_is_private_and_recoverable(tmp_path, monkeypatch):
    from cloud_lab import load_state, save_state

    monkeypatch.setattr("cloud_lab.REPO_ROOT", tmp_path / "repo")
    state = {"subscription_id": "example", "stage": "planned"}
    path = tmp_path / "private" / "state.json"
    save_state(path, state)
    assert load_state(path) == state
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("change_type", ["Modify", "Delete", "Deploy", "Unsupported"])
def test_validation_rejects_any_change_that_is_not_creation(change_type):
    from cloud_lab import verify_create_only

    with pytest.raises(ValueError, match="not create-only"):
        verify_create_only({"changes": [{"changeType": change_type}]})


def test_validation_accepts_create_and_ignored_existing_resources():
    from cloud_lab import verify_create_only

    verify_create_only(
        {"changes": [{"changeType": "Create"}, {"changeType": "Ignore"}]}
    )


def test_validation_rejects_empty_what_if():
    from cloud_lab import verify_create_only

    with pytest.raises(ValueError, match="no creates"):
        verify_create_only({"changes": []})


def test_parameters_are_arm_parameter_document():
    from cloud_lab import deployment_parameters, new_state

    state = new_state(
        {"id": "subscription-example", "tenantId": "tenant-example"},
        "operator-example", "koreacentral", "a1b2c3d4"
    )
    result = deployment_parameters(state)
    assert result["parameters"]["resourceGroupName"]["value"] == state["resource_group"]
    assert result["parameters"]["operatorObjectId"]["value"] == "operator-example"
    assert "subscription_id" not in json.dumps(result)


def test_state_suffix_cannot_be_a_shell_command():
    from cloud_lab import new_state

    with pytest.raises(ValueError, match="suffix"):
        new_state(
            {"id": "example", "tenantId": "example"},
            "operator", "koreacentral", "../not-a-lab"
        )
