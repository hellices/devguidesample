import json
import re
import sys
from pathlib import Path

import pytest

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
        "Lag collection",
        "Receiver and delivery path comparison",
        "DS Event Hub series",
        "IncomingMessages: API vs Diagnostic Settings",
        "Exporter send failures",
    ):
        assert title in titles
    assert len(PANEL_PLAN) >= 10


def test_no_query_hides_missing_series_as_zero():
    text = json.dumps(build_dashboard({"processing_units": 1}))
    assert "or vector(0)" not in text


def _azure_total_targets():
    targets = [
        target["expr"]
        for panel in _panels(build_dashboard({"processing_units": 1}))
        for target in panel.get("targets", [])
        if "sum_over_time(azure_" in target["expr"]
    ]
    # Each request stat must keep its total; an empty match would make the checks vacuous.
    for metric in ("incomingrequests", "successfulrequests", "throttledrequests"):
        assert sum(f"azure_{metric}_total" in expr for expr in targets) == 1, metric
    return targets


AZURE_REFERENCE = re.compile(r"\b(azure_\w+)(\{[^}]*\})?")


MATCHER = re.compile(r'\s*(\w+)\s*(=~|!~|!=|=)\s*"((?:[^"\\]|\\.)*)"\s*(?:,|$)')


def _matchers(selector):
    """{label: (operator, value)} parsed matcher by matcher; unparsable text fails the test."""
    body = selector[1:-1] if selector else ""
    parsed, position = {}, 0
    while position < len(body):
        match = MATCHER.match(body, position)
        assert match, f"unparsable selector {selector}"
        parsed[match.group(1)] = (match.group(2), match.group(3))
        position = match.end()
    return parsed


def _azure_selectors(expr):
    """Parsed matchers of every azure_* metric reference; a bare name (no selector) yields {}."""
    return [(name, _matchers(selector)) for name, selector in AZURE_REFERENCE.findall(expr)]


def test_platform_totals_use_remote_write_only():
    for expr in _azure_total_targets():
        selectors = _azure_selectors(expr)
        assert selectors
        for name, matchers in selectors:
            # Every reference, not just one of them, must be the API source over remote write.
            assert matchers.get("source_path") == ("=", "azure_monitor_api"), (name, expr)
            assert matchers.get("delivery_path") == ("=", "remote_write"), (name, expr)


def test_selector_check_catches_an_added_unfiltered_branch():
    expr = ('sum(sum_over_time(azure_x_total_Count{source_path="azure_monitor_api",delivery_path="remote_write"}'
            '[$__range] offset 1s)) or sum_over_time(azure_x_total_Count[$__range])')
    assert ("azure_x_total_Count", {}) in _azure_selectors(expr)
    lookalike = _matchers('{source_path_backup="azure_monitor_api",delivery_path_backup="remote_write"}')
    assert "source_path" not in lookalike and "delivery_path" not in lookalike


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


SUM_OVER_TIME = re.compile(r"sum_over_time\(\s*azure_\w+(?:\{[^}]*\})?\s*(\[[^\]]*\](?:\s*offset\s+\w+)?)")


def test_request_totals_use_the_azure_monitor_window():
    for expr in _azure_total_targets():
        windows = SUM_OVER_TIME.findall(expr)
        # Every call, not just one, must use the [from, to) window; count all references too.
        assert windows and windows == ["[$__range] offset 1s"] * len(windows), expr
        assert len(windows) == len(_azure_selectors(expr)), expr


def test_window_check_catches_a_second_differently_windowed_call():
    expr = ('sum_over_time(azure_x_total_Count{a="b"}[$__range] offset 1s)'
            ' + sum_over_time(azure_x_total_Count{a="b"}[5m])')
    assert SUM_OVER_TIME.findall(expr) == ["[$__range] offset 1s", "[5m]"]


def test_receiver_failures_survive_a_missing_counter():
    exprs = [t["expr"] for p in _panels(build_dashboard({"processing_units": 1}))
             if p.get("title") == "Receiver refused·failed points" for t in p["targets"]]
    assert len(exprs) == 1
    assert "(refused|failed)" in exprs[0] and " + " not in exprs[0]


def test_path_comparison_shows_last_sample_age():
    panel = next(p for p in _panels(build_dashboard({"processing_units": 1}))
                 if p.get("title") == "Receiver and delivery path comparison")
    assert any("tlast_over_time" in t["expr"] for t in panel["targets"])


def test_optional_marker_leads_every_description_that_uses_it():
    for panel in _panels(build_dashboard({"processing_units": 1, "dedicated_enabled": True})):
        description = panel.get("description", "")
        if "[optional]" in description:
            assert description.startswith("[optional]"), panel["title"]


def test_dedicated_panels_read_only_the_dedicated_source():
    dashboard = build_dashboard({"processing_units": 1, "dedicated_enabled": True})
    for panel in _panels(dashboard):
        exprs = " ".join(target["expr"] for target in panel.get("targets", []))
        if panel["title"].startswith("Dedicated"):
            selectors = _azure_selectors(exprs)
            assert selectors
            for name, matchers in selectors:
                assert matchers.get("source_path") == ("=", "azure_monitor_dedicated"), (name, exprs)
        else:
            assert "azure_monitor_dedicated" not in exprs


def test_min_and_max_are_standard_field_options():
    dashboard = build_dashboard({"processing_units": 1, "dedicated_enabled": True})
    cpu = next(p for p in _panels(dashboard) if p["title"] == "Premium CPU")
    assert cpu["fieldConfig"]["defaults"]["min"] == 0
    assert cpu["fieldConfig"]["defaults"]["max"] == 100
    for panel in _panels(dashboard):
        custom = panel.get("fieldConfig", {}).get("defaults", {}).get("custom", {})
        assert "min" not in custom and "max" not in custom, panel["title"]


def test_grafana_client_refuses_redirects_and_plain_http(monkeypatch):
    import http.server
    import threading
    import urllib.error

    import pytest
    from verify_panels import grafana_request

    class Redirect(http.server.BaseHTTPRequestHandler):
        seen_authorization = []

        def do_GET(self):
            Redirect.seen_authorization.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        monkeypatch.delenv("GRAFANA_ALLOW_HTTP", raising=False)
        with pytest.raises(SystemExit):
            grafana_request(url, "admin", "secret", "/api/health")
        assert Redirect.seen_authorization == []

        monkeypatch.setenv("GRAFANA_ALLOW_HTTP", "1")  # test-only switch to reach the local server
        with pytest.raises(urllib.error.HTTPError, match="refusing redirect"):
            grafana_request(url, "admin", "secret", "/api/health")
    finally:
        server.shutdown()


@pytest.mark.parametrize("pu", [0, -1])
def test_processing_units_must_be_positive(pu):
    with pytest.raises(ValueError):
        build_dashboard({"processing_units": pu})


def test_panel_plan_describes_the_window_peak_it_shows():
    lag_rows = [row for row in PANEL_PLAN if row[1] == "eventhubs_consumer_lag_messages"]
    assert lag_rows and all("지금" not in row[0] for row in lag_rows)


def _verify_with(monkeypatch, expr, variables, query_error=None):
    import verify_panels

    dashboard = {
        "templating": {"list": [{"name": n, "current": {"value": v}} for n, v in variables]},
        "panels": [{"type": "stat", "title": "P", "description": "[optional] x",
                    "targets": [{"refId": "A", "expr": expr}]}],
    }
    sent = []

    def fake_request(url, user, password, path, payload=None):
        if path.startswith("/api/dashboards/uid/"):
            return {"dashboard": dashboard}
        sent.append(payload["queries"][0]["expr"])
        if query_error:
            raise query_error
        return {"results": {"A": {"frames": [{"data": {"values": [[1], [2.0]]}}]}}}

    monkeypatch.setattr(verify_panels, "grafana_request", fake_request)
    report = verify_panels.verify("https://g.example", "u", "p", "uid", "0", "1")
    return report, sent


def test_variables_are_substituted_as_whole_tokens(monkeypatch):
    report, sent = _verify_with(
        monkeypatch, "x{c=\"$cluster_name\",d=\"${cluster}\"} / $pu [$__range]",
        [("cluster", "one"), ("cluster_name", "two"), ("pu", "2")],
    )
    assert sent == ['x{c="two",d="one"} / 2 [$__range]']
    assert report[0]["status"] == "pass"


@pytest.mark.parametrize("failure", ["url", "read_timeout", "reset"])
def test_connection_failures_are_reported_not_raised(monkeypatch, failure):
    import urllib.error

    error = {"url": urllib.error.URLError("timed out"),
             "read_timeout": TimeoutError("timed out"),
             "reset": ConnectionResetError("connection reset")}[failure]
    report, _ = _verify_with(monkeypatch, "up", [], query_error=error)
    assert report[0]["status"] == "error"
    assert ("timed out" if failure != "reset" else "reset") in report[0]["error"]
