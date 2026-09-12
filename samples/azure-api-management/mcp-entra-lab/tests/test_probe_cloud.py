def test_inventory_evidence_requires_correlated_real_backend_shape():
    from probe_cloud import inventory_matches

    body = {
        "source": "inventory-rest",
        "widgets": [{"sku": "WID-100"}, {"sku": "WID-200"}, {"sku": "WID-300"}],
        "invocation_id": "a" * 32,
        "probe_id": "b" * 16,
        "authorization_present": False,
    }
    assert inventory_matches(body, "b" * 16)
    assert not inventory_matches({**body, "source": "mock-response"}, "b" * 16)
    assert not inventory_matches({**body, "probe_id": "c" * 16}, "b" * 16)
    assert not inventory_matches({**body, "invocation_id": ""}, "b" * 16)
    assert not inventory_matches({**body, "authorization_present": True}, "b" * 16)


def test_inventory_evidence_does_not_accept_an_error_body():
    from probe_cloud import inventory_matches

    assert not inventory_matches({"error": "backend failed"}, "b" * 16)


def test_control_plane_requests_json_for_policy_content_negotiation():
    from probe_cloud import control_plane

    requested = []

    class Stage:
        group_id = "/subscriptions/example/resourceGroups/lab"
        state = {"suffix": "example"}

        def azure(self, arguments):
            url = arguments[arguments.index("--url") + 1]
            requested.append(url)
            if "/policies/policy" in url:
                assert "Accept=application/json" in arguments
                properties = {
                    "value": '<policies><inbound><set-header name="Authorization" exists-action="delete"/></inbound></policies>'
                }
            elif "/tools/" in url:
                properties = {"operationId": "/apis/lab-rest/operations/get-inventory"}
            elif "/learn-mcp" in url:
                properties = {
                    "type": "mcp", "backendId": "learn-backend",
                    "mcpProperties": {"endpoints": {"message": {"uriTemplate": "/mcp"}}},
                }
            else:
                properties = {"type": "mcp"}
            return {"properties": properties}

    class Results:
        def add(self, name, passed, **observed):
            assert passed

    control_plane(Results(), Stage())
    assert any("/apis/lab-rest/policies/policy" in url for url in requested)


def test_advertised_scope_accepts_both_verified_entra_resource_aliases():
    from probe_cloud import advertised_scope

    identity = {
        "client_id": "client-example",
        "identifier_uri": "api://client-example",
        "scope_name": "Mcp.Access",
    }
    assert advertised_scope(identity, ["api://client-example/Mcp.Access"]) == "api://client-example/Mcp.Access"
    assert advertised_scope(identity, ["client-example/Mcp.Access"]) == "client-example/Mcp.Access"


def test_advertised_scope_never_accepts_bare_or_other_resource_scopes():
    import pytest
    from probe_cloud import advertised_scope
    from probe_utils import ProbeFailure

    identity = {
        "client_id": "client-example",
        "identifier_uri": "api://client-example",
        "scope_name": "Mcp.Access",
    }
    with pytest.raises(ProbeFailure):
        advertised_scope(identity, ["Mcp.Access", "api://other-example/Mcp.Access"])
