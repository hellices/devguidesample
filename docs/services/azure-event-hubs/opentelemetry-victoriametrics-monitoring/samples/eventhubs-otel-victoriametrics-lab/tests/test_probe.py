import sys
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

import probe  # noqa: E402

NOW = 1_000_000


def _fake(calls):
    def fake_query(base_url, path, params):
        calls.append((base_url, path, params))
        if path == "/api/v1/series":
            return [{"__name__": "m", "source_path": "a"}]
        assert path == "/api/v1/query", path  # any other endpoint is a bug
        if params["query"].startswith("max(tlast_over_time("):
            # A sample newer than the snapshot would make freshness negative if time were omitted.
            return {"result": [{"value": [0, "999990"]}]}
        assert params["query"].startswith("sum(count_over_time("), params["query"]
        return {"result": [{"value": [0, "3"]}]}

    return fake_query


@pytest.mark.parametrize("window, start", [("30m", NOW - 6 * 3600), ("24h", NOW - 24 * 3600)])
def test_path_queries_use_the_series_snapshot_time(monkeypatch, window, start):
    monkeypatch.setattr(probe.time, "time", lambda: float(NOW))
    calls = []
    monkeypatch.setattr(probe, "query", _fake(calls))

    inventory = probe.build_inventory("http://vm.example", window)

    selector = '{source_path="a",delivery_path=""}'  # a missing label stays ""
    vm = "http://vm.example"  # every request must go to the VictoriaMetrics the caller chose
    assert calls == [
        (vm, "/api/v1/series", [("match[]", '{source_path!=""}'), ("start", str(start)), ("end", str(NOW))]),
        (vm, "/api/v1/query", {"query": f"sum(count_over_time({selector}[{window}]))", "time": str(NOW)}),
        (vm, "/api/v1/query", {"query": f"max(tlast_over_time({selector}[{window}]))", "time": str(NOW)}),
    ]
    [stats] = inventory["paths"]
    assert stats["delivery_path"] == "(missing)"
    assert stats["samples_in_window"] == 3
    assert stats["freshness_seconds"] == 10.0


@pytest.mark.parametrize("window", ["0m", "30", "1w", "-5m", "5 m"])
def test_window_must_be_a_supported_positive_duration(window):
    with pytest.raises(ValueError):
        probe.window_seconds(window)


@pytest.mark.parametrize("value, kept", [
    ("workload", True), ("Backend", True), ("remote_write", True),
    ("ns.servicebus.windows.net", False), ("/subscriptions/s/resourceGroups/g", False),
    ("00000000-0000-0000-0000-000000000000", False), ("x" * 65, False),
])
def test_allowlisted_values_are_copied_only_when_they_are_plain_tokens(value, kept):
    from probe import _safe_value

    assert (_safe_value(value) == value) is kept
