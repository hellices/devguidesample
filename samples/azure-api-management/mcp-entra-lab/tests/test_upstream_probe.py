import shlex


STATE = {
    "subscription_id": "subscription-example",
    "resource_group": "rg-example",
    "foundation_outputs": {"aksName": "aks-example"},
}


def test_aks_command_uses_recorded_subscription_and_returns_identity():
    from probe_upstreams import aks_azure_command

    command = shlex.split(aks_azure_command(STATE))
    assert command[command.index("--subscription") + 1] == "subscription-example"
    assert command[command.index("--query") + 1] == "{id:id,provisioningState:provisioningState}"


def test_same_named_cluster_in_another_subscription_is_not_a_pass():
    from probe_upstreams import aks_cluster_matches

    correct = {
        "id": "/subscriptions/subscription-example/resourceGroups/rg-example/providers/Microsoft.ContainerService/managedClusters/aks-example",
        "provisioningState": "Succeeded",
    }
    assert aks_cluster_matches(STATE, correct)
    assert not aks_cluster_matches(STATE, {
        **correct, "id": correct["id"].replace("subscription-example", "another-subscription")
    })
