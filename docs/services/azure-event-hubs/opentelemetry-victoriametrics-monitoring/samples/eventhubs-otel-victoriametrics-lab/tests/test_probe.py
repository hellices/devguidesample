import sys
from pathlib import Path

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

import probe  # noqa: E402


def test_path_queries_use_the_series_snapshot_time(monkeypatch):
    monkeypatch.setattr(probe.time, "time", lambda: 1_000_000.0)
    calls = []

    def fake_query(base_url, path, params):
        calls.append((path, params))
        if path == "/api/v1/series":
            return [{"__name__": "m", "source_path": "a"}]
        if "tlast_over_time" in params["query"]:
            # A sample newer than the snapshot would make freshness negative if time were omitted.
            return {"result": [{"value": [0, "999990"]}]}
        return {"result": [{"value": [0, "3"]}]}

    monkeypatch.setattr(probe, "query", fake_query)
    inventory = probe.build_inventory("http://vm.example")

    instant = [params for path, params in calls if path == "/api/v1/query"]
    assert instant and all(params["time"] == "1000000" for params in instant)
    assert all('delivery_path=""' in params["query"] for params in instant)  # a missing label stays ""
    [stats] = inventory["paths"]
    assert stats["delivery_path"] == "(missing)"
    assert stats["samples_in_window"] == 3
    assert stats["freshness_seconds"] == 10.0
