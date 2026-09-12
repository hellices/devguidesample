import pytest


def test_denial_list_removes_only_the_chosen_client():
    from probe_native_gate import denial_clients

    assert denial_clients(["cli", "desktop", "ide"], "cli") == ["desktop", "ide"]


def test_denial_exercise_cannot_install_an_empty_or_unrelated_list():
    from probe_native_gate import denial_clients

    with pytest.raises(ValueError):
        denial_clients(["cli"], "cli")
    with pytest.raises(ValueError):
        denial_clients(["desktop"], "cli")
