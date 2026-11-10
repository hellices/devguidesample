import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

from compare_azure_monitor import DIAGNOSTIC, LOOKAHEAD_SECONDS, REQUIRED, compare  # noqa: E402

START = int(datetime(2026, 11, 9, 21, 25, tzinfo=timezone.utc).timestamp())
END = START + 180


API = 'source_path="azure_monitor_api"'


def _values(name):
    # Distinct per metric, so reading another metric's series cannot accidentally match.
    offset = REQUIRED.index(name) if name in REQUIRED else 0
    return [float(10 * i + offset) for i in range(3)]


def _raw(names=REQUIRED, drop=None):
    value = []
    for name in names:
        data = [
            {"timeStamp": f"2026-11-09T21:{25 + i}:00Z", "total": None if drop == (name, i) else total}
            for i, total in enumerate(_values(name))
        ]
        value.append({"name": {"value": name}, "timeseries": [{"data": data}]})
    return {"value": value}


def _fetch(remote_override=None, stamp_offset_ms=0, names=REQUIRED, extra=None, later=None):
    """VictoriaMetrics export stub that answers only the exact selectors compare() must send.

    remote_write stores one sample per Azure minute; scrape repeats each bin twice, 30 s apart.
    extra maps a selector kind to additional (timestamp ms, value) samples. later maps a metric
    name to remote write samples stored after the window (the lookahead query).
    """
    exports = {}
    for name in names:
        lower = name.lower()
        for delivery in ("remote_write", "scrape"):
            exports[f'azure_{lower}_total_Count{{{API},delivery_path="{delivery}"}}'] = (name, delivery)
        exports[f'{lower}_total{{{DIAGNOSTIC}}}'] = (name, "diagnostic")

    def fetch(path, params):
        assert path == "/api/v1/export", path  # totals must come from the same filtered samples
        name, kind = exports[params["match[]"]]  # KeyError for any unexpected selector
        if (params["start"], params["end"]) == (END, END + LOOKAHEAD_SECONDS):
            assert kind == "remote_write", kind  # only remote write proves a skipped bin
            points = (later or {}).get(name, [])
            return json.dumps({"values": [v for _, v in points], "timestamps": [t for t, _ in points]})
        assert (params["start"], params["end"]) == (START, END)
        if kind == "diagnostic":
            return ""
        values = _values(name)
        if kind == "remote_write" and remote_override:
            values = remote_override(params["match[]"], values)
        if kind == "remote_write":
            # None marks a minute the receiver skipped, so nothing is stored for it.
            points = [((START + 60 * i) * 1000 + stamp_offset_ms, v) for i, v in enumerate(values) if v is not None]
        else:
            points = [((START + 60 * i + 30 * r) * 1000, v) for i, v in enumerate(values) for r in (0, 1)]
        points += (extra or {}).get(kind, [])
        return json.dumps({"values": [v for _, v in points], "timestamps": [t for t, _ in points]})

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


def test_a_skipped_bin_followed_by_later_bins_is_a_gap_not_a_failure():
    def skip_middle(selector, values):
        return [values[0], None, values[2]] if "throttledrequests" in selector else values

    report = compare(_raw(), START, END, _fetch(skip_middle))

    throttled = report["metrics"]["ThrottledRequests"]
    assert throttled["remote_write_gaps"] == ["2026-11-09T21:26"]
    assert throttled["minutes_matching_remote_write"] == 2
    assert report["remote_write_gaps"] == 1
    assert report["complete"] is True


def test_a_missing_last_bin_is_a_gap_only_when_a_later_bin_was_stored():
    def late(selector, values):
        return values[:2] if "incomingrequests" in selector else values

    after = {"IncomingRequests": [(END * 1000, 1.0)]}
    report = compare(_raw(), START, END, _fetch(late, later=after))

    assert report["metrics"]["IncomingRequests"]["remote_write_gaps"] == ["2026-11-09T21:27"]
    assert report["complete"] is True


def test_an_off_minute_sample_after_the_window_does_not_prove_a_gap():
    def late(selector, values):
        return values[:2] if "incomingrequests" in selector else values

    after = {"IncomingRequests": [(END * 1000 + 30_000, 1.0)]}
    report = compare(_raw(), START, END, _fetch(late, later=after))

    assert report["metrics"]["IncomingRequests"]["remote_write_gaps"] == []
    assert report["complete"] is False


def test_a_mismatched_value_is_never_excused_as_a_gap():
    def wrong(selector, values):
        return [values[0], values[1] + 1, values[2]] if "incomingmessages" in selector else values

    report = compare(_raw(), START, END, _fetch(wrong))

    assert report["metrics"]["IncomingMessages"]["remote_write_gaps"] == []
    assert report["complete"] is False


def test_incomplete_when_remote_write_is_not_stamped_on_the_azure_minute():
    report = compare(_raw(), START, END, _fetch(stamp_offset_ms=30_000))

    assert report["complete"] is False
    assert report["metrics"]["IncomingMessages"]["remote_write_off_bin_samples"] == 3
    assert report["metrics"]["IncomingMessages"]["minutes_matching_remote_write"] == 0


def test_scrape_is_reported_as_a_repeated_sample_sum_not_a_total():
    metric = compare(_raw(), START, END, _fetch())["metrics"]["IncomingMessages"]

    assert metric["remote_write_total"] == 30.0
    assert metric["scrape_repeated_sample_sum"] == 60.0


def test_stub_rejects_a_selector_compare_does_not_own():
    with pytest.raises(KeyError):
        _fetch()("/api/v1/export", {"match[]": "azure_other_total_Count{}", "start": START, "end": END})


def test_window_is_half_open_in_milliseconds():
    # The server returns samples just outside [START, END); compare must drop them itself.
    edges = {"remote_write": [(START * 1000 - 1, 1000.0), (END * 1000, 1000.0), (END * 1000 - 1, 7.0)]}
    metric = compare(_raw(), START, END, _fetch(extra=edges))["metrics"]["IncomingMessages"]

    assert metric["remote_write_total"] == 30.0 + 7.0  # the last-millisecond sample is inside
    assert metric["remote_write_off_bin_samples"] == 1


@pytest.mark.parametrize("from_ms, to_ms", [
    (START * 1000 + 500, END * 1000),   # starts mid-minute
    (START * 1000, END * 1000 - 1),     # ends mid-minute
    (END * 1000, START * 1000),         # reversed
])
def test_cli_rejects_windows_that_are_not_whole_minutes(tmp_path, from_ms, to_ms):
    import subprocess

    raw = tmp_path / "raw.json"
    raw.write_text("{}")
    result = subprocess.run(
        [sys.executable, str(LAB_ROOT / "agent" / "compare_azure_monitor.py"), "--azure-monitor", str(raw),
         "--from-ms", str(from_ms), "--to-ms", str(to_ms), "--vm-url", "http://127.0.0.1:9", "--output",
         str(tmp_path / "out.json")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert "whole minutes" in result.stderr
