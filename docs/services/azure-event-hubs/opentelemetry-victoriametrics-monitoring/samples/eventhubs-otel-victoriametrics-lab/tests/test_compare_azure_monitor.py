import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

from compare_azure_monitor import REQUIRED, compare  # noqa: E402

START = int(datetime(2026, 11, 9, 21, 25, tzinfo=timezone.utc).timestamp())
END = START + 180


def _raw(names=REQUIRED, drop=None):
    value = []
    for name in names:
        data = [
            {"timeStamp": f"2026-11-09T21:{25 + i}:00Z", "total": None if drop == (name, i) else float(10 * i)}
            for i in range(3)
        ]
        value.append({"name": {"value": name}, "timeseries": [{"data": data}]})
    return {"value": value}


def _fetch(remote_override=None):
    def fetch(path, params):
        if path == "/api/v1/export":
            assert (params["start"], params["end"]) == (START, END - 1)
            if "diagnostic_eventhub" in params["match[]"]:
                return ""
            values = [float(10 * i) for i in range(3)]
            if remote_override:
                values = remote_override(params["match[]"], values)
            stamps = [(START + 60 * i) * 1000 for i in range(3)]
            return json.dumps({"values": values, "timestamps": stamps})
        assert path == "/api/v1/query", path
        assert params["time"] == END - 1
        assert f"[{END - START}s]" in params["query"]
        return json.dumps({"data": {"result": [{"value": [END, "30"]}]}})

    return fetch


def test_complete_when_every_metric_and_minute_matches():
    report = compare(_raw(), START, END, _fetch())

    assert report["expected_minutes"] == 3
    assert report["complete"] is True


def test_incomplete_when_azure_monitor_has_not_filled_a_minute():
    report = compare(_raw(drop=("OutgoingMessages", 2)), START, END, _fetch())

    assert report["complete"] is False
    assert report["metrics"]["OutgoingMessages"]["minutes_missing_in_azure_monitor"] == ["2026-11-09T21:27"]


def test_incomplete_when_a_required_metric_is_missing():
    assert compare(_raw(names=REQUIRED[:3]), START, END, _fetch())["complete"] is False
    assert compare({"value": []}, START, END, _fetch())["complete"] is False


def test_incomplete_when_remote_write_differs():
    def late(selector, values):
        return values[:2] if "incomingrequests" in selector else values

    report = compare(_raw(), START, END, _fetch(late))

    assert report["complete"] is False
    assert report["metrics"]["IncomingRequests"]["minutes_missing_in_remote_write"] == ["2026-11-09T21:27"]
