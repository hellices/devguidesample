import json
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

from build_dashboard import PANEL_PLAN, build_dashboard  # noqa: E402


def _panels(dashboard):
    return [p for p in dashboard["panels"] if p["type"] != "row"]


def test_dashboard_answers_required_questions():
    titles = {p["title"] for p in _panels(build_dashboard({"processing_units": 1}))}

    for title in (
        "Premium CPU",
        "Premium Memory",
        "Throttled requests",
        "Outgoing Requests support boundary",
        "Messages per PU / min",
        "Consumer lag by partition (stacked)",
        "Peak lag (window)",
        "Checkpoint presence",
        "Receiver and delivery path comparison",
        "DS Event Hub series",
        "Exporter send failures",
    ):
        assert title in titles
    assert len(PANEL_PLAN) >= 10


def test_no_query_hides_missing_series_as_zero():
    text = json.dumps(build_dashboard({"processing_units": 1}))
    assert "or vector(0)" not in text


def test_platform_totals_use_remote_write_only():
    for panel in _panels(build_dashboard({"processing_units": 1})):
        for target in panel.get("targets", []):
            if "sum_over_time(azure_" in target["expr"]:
                assert 'delivery_path="remote_write"' in target["expr"]


def test_dedicated_panels_exist_only_with_profile():
    default = build_dashboard({"processing_units": 1})
    dedicated = build_dashboard({"processing_units": 1, "dedicated_enabled": True})

    assert all("Dedicated" not in p["title"] for p in default["panels"])
    memory = next(p for p in dedicated["panels"] if p["title"] == "Dedicated available memory")
    steps = memory["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert steps[0]["color"] == "red"


def test_committable_dashboard_has_no_environment_identifiers():
    text = json.dumps(build_dashboard({"processing_units": 2}))

    assert "/subscriptions/" not in text
    assert "10.42." not in text
    assert "servicebus.windows.net" not in text
    assert '"query": "2"' in text


def test_panels_do_not_overlap():
    occupied = set()
    for panel in build_dashboard({"processing_units": 1})["panels"]:
        pos = panel["gridPos"]
        cells = {(x, y) for x in range(pos["x"], pos["x"] + pos["w"]) for y in range(pos["y"], pos["y"] + pos["h"])}
        assert not occupied & cells, panel["title"]
        assert pos["x"] + pos["w"] <= 24
        occupied |= cells
