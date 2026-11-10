import http.client
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
    exprs = [t["expr"] for p in _panels(build_dashboard({"processing_units": 1})) for t in p.get("targets", [])]
    # Any spacing or matching modifier (or on() vector (0)) still turns "no data" into 0.
    # Parentheses around vector(0) are still a zero fill.
    zero_fill = re.compile(r"\bor\b(?:\s+(?:on|ignoring)\s*\([^)]*\))?[\s(]*vector\s*\(\s*0(?:\.0*)?\s*\)")
    assert not [e for e in exprs if zero_fill.search(e)]
    assert zero_fill.search("x or on() vector (0)") and zero_fill.search("x or vector(0.0)")
    assert zero_fill.search("x or on() (vector(0))") and zero_fill.search("x or ( vector(0) )")
    assert zero_fill.search("x or ignoring(job) vector(0)")


def _azure_total_targets():
    # Every target that references a request total, however it is spelled, is checked.
    targets = [
        target["expr"]
        for panel in _panels(build_dashboard({"processing_units": 1}))
        for target in panel.get("targets", [])
        if any(re.match(r"azure_\w*requests_total", name) for name, _ in AZURE_REFERENCE.findall(target["expr"]))
    ]
    # Each request stat must keep its total; an empty match would make the checks vacuous.
    references = [name for expr in targets for name, _ in _azure_selectors(expr)]
    for metric in ("incomingrequests", "successfulrequests", "throttledrequests"):
        # Exactly one reference per total, so an added duplicate term would double the stat.
        assert sum(name.startswith(f"azure_{metric}_total") for name in references) == 1, metric
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
    assert "(refused|failed)" in exprs[0] and "+" not in exprs[0]


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


@pytest.mark.parametrize("pu", [0, -1, 1.5, True, "2"])
def test_processing_units_must_be_positive(pu):
    with pytest.raises(ValueError):
        build_dashboard({"processing_units": pu})


def test_panel_plan_describes_the_window_peak_it_shows():
    lag_rows = [row for row in PANEL_PLAN if row[1] == "eventhubs_consumer_lag_messages"]
    assert lag_rows and all("지금" not in row[0] for row in lag_rows)


def _verify_with(monkeypatch, expr, variables, query_error=None, target_extra=None, response=None):
    import verify_panels

    dashboard = {
        "templating": {"list": [{"name": n, "current": {"value": v}} for n, v in variables]},
        "panels": [{"type": "stat", "title": "P", "description": "[optional] x",
                    "targets": [{"refId": "A", "expr": expr, **(target_extra or {})}]}],
    }
    calls = []

    def fake_request(url, user, password, path, payload=None):
        calls.append((url, path))
        if path == "/api/dashboards/uid/uid":
            return {"dashboard": dashboard}
        # Only the dashboard of the requested uid and Grafana's query endpoint are valid.
        assert path == "/api/ds/query", path
        calls.append(payload["queries"][0])
        if query_error:
            raise query_error
        return response if response is not None else {
            "results": {"A": {"frames": [{"data": {"values": [[1], [2.0]]}}]}}}

    monkeypatch.setattr(verify_panels, "grafana_request", fake_request)
    report = verify_panels.verify("https://g.example", "u", "p", "uid", "0", "1")
    assert calls[0] == ("https://g.example", "/api/dashboards/uid/uid")
    assert all(c[0] == "https://g.example" for c in calls if isinstance(c, tuple))
    sent = [c for c in calls if isinstance(c, dict)]
    return report, sent


def test_variables_are_substituted_as_whole_tokens(monkeypatch):
    report, sent = _verify_with(
        monkeypatch, "x{c=\"$cluster_name\",d=\"${cluster}\"} / $pu [$__range]",
        [("cluster", "one"), ("cluster_name", "two"), ("pu", "2")],
    )
    assert [q["expr"] for q in sent] == ['x{c="two",d="one"} / 2 [$__range]']
    assert report[0]["status"] == "pass"


@pytest.mark.parametrize("failure", ["url", "read_timeout", "reset", "incomplete"])
def test_connection_failures_are_reported_not_raised(monkeypatch, failure):
    import urllib.error

    error = {"url": urllib.error.URLError("timed out"),
             "read_timeout": TimeoutError("timed out"),
             "reset": ConnectionResetError("connection reset"),
             "incomplete": http.client.IncompleteRead(b"{", 10)}[failure]
    report, _ = _verify_with(monkeypatch, "up", [], query_error=error)
    assert report[0]["status"] == "error"
    expected = {"reset": "reset", "incomplete": "IncompleteRead"}.get(failure, "timed out")
    assert expected in report[0]["error"]


@pytest.mark.parametrize("target, expected", [
    ({}, (False, True)),
    ({"instant": True}, (True, False)),
    ({"instant": True, "range": True}, (True, True)),  # Grafana's "Both" query type
])
def test_query_type_flags_are_sent_as_configured(monkeypatch, target, expected):
    _, sent = _verify_with(monkeypatch, "up", [], target_extra=target)
    assert (sent[0]["instant"], sent[0]["range"]) == expected


@pytest.mark.parametrize("failure", ["not_json", "no_results"])
def test_malformed_query_responses_are_reported_not_raised(monkeypatch, failure):
    import json

    error = json.JSONDecodeError("Expecting value", "<html>", 0) if failure == "not_json" else None
    report, _ = _verify_with(monkeypatch, "up", [], query_error=error, response={} if not error else None)
    assert report[0]["status"] == "error"


def test_diagnostic_series_stat_counts_one_delivery_path():
    panel = next(p for p in _panels(build_dashboard({"processing_units": 1})) if p.get("title") == "DS Event Hub series")
    from build_dashboard import DIAG

    # Exactly the one counting expression over the filtered selector; nothing can be added to it.
    assert [t["expr"] for t in panel["targets"]] == [f"count(last_over_time({{{DIAG}}}[$__range]))"]
    matchers = _matchers("{" + DIAG + "}")
    assert matchers.pop("azure_resource_id")[0] == "=~"  # namespace records only, not the cluster's
    assert matchers == {"source_path": ("=", "diagnostic_eventhub"), "delivery_path": ("=", "remote_write")}


def test_dedicated_tier_shows_cluster_capacity_instead_of_premium_namespace():
    dashboard = build_dashboard({"processing_units": 1, "tier": "dedicated"})
    titles = [p["title"] for p in _panels(dashboard)]

    assert "Dedicated CPU" in titles and "Dedicated available memory" in titles
    assert not any(t.startswith("Premium CPU") or t == "Premium Memory" for t in titles)
    assert "Messages per CU / min" in titles
    assert titles.count("Dedicated CPU") == 1  # not repeated by the existing-cluster row
    rows = [p["title"] for p in dashboard["panels"] if p["type"] == "row"]
    assert rows[0].startswith("Dedicated cluster 용량 상태 (1 CU")


def test_premium_tier_with_an_existing_cluster_keeps_both():
    titles = [p["title"] for p in _panels(build_dashboard(
        {"processing_units": 1, "tier": "premium", "dedicated_enabled": True}))]
    assert "Premium CPU" in titles and "Dedicated CPU" in titles


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError):
        build_dashboard({"processing_units": 1, "tier": "standard"})


def test_dedicated_compares_cluster_cpu_across_api_and_diagnostic_settings():
    panels = {p["title"]: p for p in _panels(build_dashboard({"processing_units": 1, "tier": "dedicated"}))}

    assert "NamespaceCpuUsage maximum: API vs Diagnostic Settings" not in panels
    exprs = [t["expr"] for t in panels["Cluster CPU maximum: API vs Diagnostic Settings"]["targets"]]
    assert "azure_cpu_maximum_Percent" in exprs[0]
    # Cluster records only; namespace records share the same hub and metric names.
    assert "cpu_maximum" in exprs[1] and "eventhub/clusters/" in exprs[1]


SETTLE_CASES = {
    # content height per measurement; a layout that keeps growing is refused, not captured
    "grows_forever": "let h = 1000; const measure = async () => (h += 500);",
    # height: 100% layouts report the viewport itself and must count as settled
    "full_height": "let v = 1000; const measure = async () => v;",
    # lazy panels appear once, then the content fits the grown viewport
    "grows_then_fits": "let v = 1000; const sizes = [2400, 2400]; const measure = async () => sizes.shift() ?? v;",
    # content fits only after the last allowed resize; that final size must be re-measured, not refused
    "fits_after_last_resize": ("let v = 1000; let n = 0; "
                               "const measure = async () => (++n <= 12 ? 1000 + n * 100 : 2200);"),
}


@pytest.mark.parametrize("case, expected", [
    ("grows_forever", "rejected"), ("full_height", "1000"), ("grows_then_fits", "2400"),
    ("fits_after_last_resize", "2200"),
])
def test_capture_waits_until_the_dashboard_fits_and_refuses_one_that_never_does(case, expected):
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    module = (LAB_ROOT / "agent" / "settle.mjs").as_uri()
    script = (
        f"import {{ settleViewport }} from '{module}';\n{SETTLE_CASES[case]}\n"
        "const resize = async (height) => { if (typeof v !== 'undefined') v = height; };\n"
        "settleViewport({ measure, resize, initialHeight: 1000 })"
        ".then((h) => console.log(h), () => console.log('rejected'));\n"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)

    assert result.stdout.strip() == expected, result.stderr


def test_capture_uses_the_settle_helper():
    # Strip comments so a commented-out call cannot satisfy the check.
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", (LAB_ROOT / "agent" / "capture.mjs").read_text(), flags=re.S)
    assert re.search(r"^import \{ settleViewport \} from '\./settle\.mjs';$", text, re.M)
    assert re.search(r"^\s*const height = await settleViewport\(\{", text, re.M)
    # Panel query failures are checked before, not after, the screenshot.
    assert re.search(r"^import \{ queryFailure \} from '\./query-failure\.mjs';$", text, re.M)
    assert text.index("queryFailures.length") < text.index("page.screenshot(")


QUERY_CASES = {
    "ok": ("true", "200", '{"results": {"A": {"frames": []}}}', "null"),
    "http_error": ("false", "500", "{}", "HTTP 500"),
    "partial_error": ("true", "207", '{"results": {"A": {}, "B": {"error": "bad_data"}}}', "B: bad_data"),
    "not_json": ("true", "200", None, "response is not JSON"),
}


@pytest.mark.parametrize("case", sorted(QUERY_CASES))
def test_capture_rejects_failed_panel_queries(case):
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    ok, status, body, expected = QUERY_CASES[case]
    json_impl = "() => Promise.reject(new Error('html'))" if body is None else f"async () => ({body})"
    module = (LAB_ROOT / "agent" / "query-failure.mjs").as_uri()
    script = (
        f"import {{ queryFailure }} from '{module}';\n"
        f"const response = {{ ok: () => {ok}, status: () => {status}, json: {json_impl} }};\n"
        "queryFailure(response).then((v) => console.log(String(v)));\n"
    )
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)

    assert result.stdout.strip() == expected, result.stderr


def test_hidden_targets_are_not_queried(monkeypatch):
    # Grafana skips a hidden target, so an invalid hidden expr must not fail the panel.
    report, sent = _verify_with(monkeypatch, "broken(", [], target_extra={"hide": True})

    assert sent == [] and report == []


@pytest.mark.parametrize("url, ok", [
    ("https://203.0.113.10:3000", True), ("https://203.0.113.10:3000/", True),
    ("https://203.0.113.10:3000/grafana", False), ("https://203.0.113.10:3000/?x=1", False),
    ("http://203.0.113.10:3000", False),
])
def test_capture_accepts_only_a_root_https_grafana_url(url, ok):
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    module = (LAB_ROOT / "agent" / "grafana-url.mjs").as_uri()
    script = (f"import {{ grafanaBase }} from '{module}';\n"
              f"try {{ grafanaBase({json.dumps(url)}, 'ca.crt'); console.log('ok'); }} catch {{ console.log('rejected'); }}\n")
    result = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, timeout=30)

    assert result.stdout.strip() == ("ok" if ok else "rejected"), result.stderr
