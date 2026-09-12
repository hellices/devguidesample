import pytest


def test_application_cleanup_requires_matching_client_and_ownership_tags():
    from cleanup import owned_application

    record = {"client_id": "client-example"}
    assert owned_application(record, {"appId": "client-example", "tags": ["mcp-entra-lab", "example"]}, "example")
    assert not owned_application(record, {"appId": "other-client", "tags": ["mcp-entra-lab", "example"]}, "example")
    assert not owned_application(record, {"appId": "client-example", "tags": []}, "example")


def test_deletion_requires_the_exact_lab_confirmation():
    from cleanup import confirm_deletion

    with pytest.raises(ValueError):
        confirm_deletion("example", "another")
    confirm_deletion("example", "example")
