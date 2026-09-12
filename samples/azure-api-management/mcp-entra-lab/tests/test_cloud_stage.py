import pytest


def test_scoped_preview_rejects_changes_outside_owned_group():
    from cloud_stage import verify_scoped_preview

    with pytest.raises(ValueError, match="outside"):
        verify_scoped_preview(
            {"changes": [{
                "changeType": "Create",
                "resourceId": "/subscriptions/example/resourceGroups/another/providers/Test/items/a",
            }]},
            "/subscriptions/example/resourceGroups/lab",
        )


def test_scoped_preview_rejects_deletion_even_in_lab():
    from cloud_stage import verify_scoped_preview

    with pytest.raises(ValueError, match="unsafe"):
        verify_scoped_preview(
            {"changes": [{
                "changeType": "Delete",
                "resourceId": "/subscriptions/example/resourceGroups/lab/providers/Test/items/a",
            }]},
            "/subscriptions/example/resourceGroups/lab",
        )


def test_scoped_preview_accepts_owned_incremental_changes():
    from cloud_stage import verify_scoped_preview

    verify_scoped_preview(
        {"changes": [{
            "changeType": "Modify",
            "resourceId": "/subscriptions/example/resourceGroups/lab/providers/Test/items/a",
        }]},
        "/subscriptions/example/resourceGroups/lab",
    )


def test_similarly_named_group_is_not_the_same_scope():
    from cloud_stage import verify_scoped_preview

    with pytest.raises(ValueError, match="outside"):
        verify_scoped_preview(
            {"changes": [{
                "changeType": "Create",
                "resourceId": "/subscriptions/example/resourceGroups/lab-extra/providers/Test/items/a",
            }]},
            "/subscriptions/example/resourceGroups/lab",
        )


def test_build_resolves_dockerfile_when_invoked_from_repository_root(tmp_path):
    from cloud_stage import ApplicationStage, SAMPLE_ROOT

    stage = ApplicationStage.__new__(ApplicationStage)
    stage.path = tmp_path / "private" / "state.json"
    stage.state = {"subscription_id": "example"}
    stage.common = []
    stage.registry = lambda: {
        "name": "registry-example", "loginServer": "example.azurecr.io"
    }
    commands = []

    def azure(arguments, timeout=180):
        commands.append(arguments)
        if arguments[:2] == ["acr", "build"]:
            return {"status": "Succeeded"}
        return "sha256:" + "a" * 64

    stage.azure = azure
    stage.build()
    build = commands[0]
    assert build[build.index("--file") + 1] == str(SAMPLE_ROOT / "Dockerfile")
