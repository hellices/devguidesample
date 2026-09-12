import asyncio
import json
from types import SimpleNamespace

import pytest


def response(value, *, error=False):
    return SimpleNamespace(
        is_error=error, structured_content=None,
        content=[SimpleNamespace(type="text", text=json.dumps(value))],
    )


def test_http_success_does_not_override_mcp_tool_error():
    from probe_utils import ProbeFailure, json_result

    with pytest.raises(ProbeFailure):
        json_result(response({"status": 200}, error=True))


def test_malformed_json_is_not_reported_as_a_result():
    from probe_utils import ProbeFailure, json_result

    value = response({})
    value.content[0].text = "not JSON"
    with pytest.raises(ProbeFailure):
        json_result(value)


def test_azure_wrapper_failure_is_not_a_success():
    from probe_utils import ProbeFailure, azure_resource_count

    with pytest.raises(ProbeFailure):
        azure_resource_count(
            response({"status": 403, "results": {"resources": []}}),
            "/subscriptions/example/resourceGroups/lab",
        )


def test_azure_results_must_belong_to_the_requested_group():
    from probe_utils import ProbeFailure, azure_resource_count

    value = response({
        "status": 200, "results": {"resources": [
            {"id": "/subscriptions/example/resourceGroups/unrelated/providers/Test/items/a"}
        ]},
    })
    with pytest.raises(ProbeFailure):
        azure_resource_count(value, "/subscriptions/example/resourceGroups/lab")


def test_scoped_azure_results_return_an_actual_count():
    from probe_utils import azure_resource_count

    prefix = "/subscriptions/example/resourceGroups/lab"
    value = response({
        "status": 200, "results": {"resources": [
            {"id": prefix + "/providers/Test/items/a"},
            {"id": prefix + "/providers/Test/items/b"},
        ]},
    })
    assert azure_resource_count(value, prefix) == 2


def test_tool_discovery_follows_pagination():
    from probe_utils import all_tools

    class Client:
        async def list_tools(self, *, cursor=None):
            if cursor is None:
                return SimpleNamespace(tools=["first"], next_cursor="next")
            assert cursor == "next"
            return SimpleNamespace(tools=["second"], next_cursor=None)

    assert asyncio.run(all_tools(Client())) == ["first", "second"]


def test_repeated_pagination_cursor_is_rejected():
    from probe_utils import ProbeFailure, all_tools

    class Client:
        async def list_tools(self, *, cursor=None):
            return SimpleNamespace(tools=["item"], next_cursor="same")

    with pytest.raises(ProbeFailure):
        asyncio.run(all_tools(Client()))


def test_starting_a_new_run_retires_old_success_evidence(tmp_path):
    from probe_utils import Results

    path = tmp_path / "results.json"
    path.write_text('{"checks":[{"id":"old-suite-complete","status":"passed"}]}')
    Results(path)
    assert json.loads(path.read_text())["checks"] == []
