import json
import re
import sys
from pathlib import Path

import pytest

LAB_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(LAB_ROOT / "agent"))

from build_direct_dashboard import AZMON, LOGS, build_dashboard  # noqa: E402
from compare_grafana_azure_monitor import compare  # noqa: E402
import verify_panels  # noqa: E402

SETTINGS = {"subscription": "00000000-0000-0000-0000-000000000000", "resource_group": "rg-example",
            "namespace": "ehp-example"}


def _panels(dashboard):
    return [p for p in dashboard["panels"] if p["type"] != "row"]


def _targets(dashboard):
    return [(p, t) for p in _panels(dashboard) for t in p.get("targets", [])]


@pytest.mark.parametrize("settings", [
    SETTINGS,
    {**SETTINGS, "tier": "dedicated", "cluster": "ehc-example"},
])
def test_platform_metrics_come_only_from_azure_monitor_and_lag_only_from_resource_logs(settings):
    dashboard = build_dashboard(settings)
    for panel, target in _targets(dashboard):
        if "azureMonitor" in target:
            assert target["datasource"] == AZMON and panel["datasource"] == AZMON
            query = target["azureMonitor"]
            # One resource per target: Grafana then calls that resource's metrics endpoint, which a
            # resource-scoped Monitoring Reader can read. Several resources go to the subscription endpoint.
            assert len(query["resources"]) == 1 and query["timeGrain"] == "PT1M"
            assert query["resources"][0]["resourceName"] in ("ehp-example", "ehc-example")
        else:
            expr = target["expr"]
            # Collector platform series are named azure_<metric>_<aggregation>_<unit>.
            assert not re.search(r"\bazure_[a-z0-9_]+_(?:total|maximum|average)_[a-z0-9_]+\b", expr, re.IGNORECASE), \
                "platform metrics must not be read from VictoriaMetrics"
            # No lag exporter in this mode: no checkpoint lag series may be queried.
            assert "eventhubs_consumer_lag_messages" not in expr and "eventhubs_checkpoint" not in expr
            assert "eventhubs_log_" in expr or "otelcol_" in expr or "source_path!=" in expr
    lag_exprs = [t["expr"] for _, t in _targets(dashboard) if "eventhubs_log_consumer_lag" in t.get("expr", "")]
    assert lag_exprs and all(LOGS in expr for expr in lag_exprs)
    assert LOGS == 'source_path="diagnostic_logs",delivery_path="remote_write"'


def test_dedicated_dashboard_splits_cluster_cpu_by_role():
    dashboard = build_dashboard({**SETTINGS, "tier": "dedicated", "cluster": "ehc-example"})
    cpu = [t["azureMonitor"] for _, t in _targets(dashboard)
           if t.get("azureMonitor", {}).get("metricName") == "CPU"]
    assert cpu and all(q["metricNamespace"] == "microsoft.eventhub/clusters" for q in cpu)
    assert all(q["dimensionFilters"] == [{"dimension": "Role", "operator": "eq", "filters": []}] for q in cpu)
    with pytest.raises(ValueError):
        build_dashboard({**SETTINGS, "tier": "dedicated"})


def test_throttled_requests_are_not_split_so_zero_is_explicit():
    dashboard = build_dashboard(SETTINGS)
    throttled = [t["azureMonitor"] for _, t in _targets(dashboard)
                 if t.get("azureMonitor", {}).get("metricName") == "ThrottledRequests"]
    assert throttled == [throttled[0]] and throttled[0]["dimensionFilters"] == []
    assert throttled[0]["aggregation"] == "Total"


def test_verify_runs_azure_monitor_targets_as_is(monkeypatch):
    dashboard = build_dashboard(SETTINGS)
    sent = []

    def fake_request(url, user, password, path, body=None):
        if body is None:
            assert path == "/api/dashboards/uid/uid"
            return {"dashboard": dashboard}
        assert path == "/api/ds/query"
        query = body["queries"][0]
        sent.append(query)
        frame = {"data": {"values": [[1, 2], [3.0, 4.0]]}}
        return {"results": {query["refId"]: {"frames": [frame]}}}

    monkeypatch.setattr(verify_panels, "grafana_request", fake_request)
    report = verify_panels.verify("https://grafana.example", "admin", "", "uid", "0", "1")
    azure = [q for q in sent if q["datasource"] == AZMON]
    prometheus = [q for q in sent if q["datasource"]["type"] == "prometheus"]
    assert azure and prometheus
    # Every Azure Monitor target reaches Grafana unchanged except for the request-only fields.
    expected = [t for _, t in _targets(dashboard) if "azureMonitor" in t]
    added = {"intervalMs", "maxDataPoints"}
    assert [{k: v for k, v in q.items() if k not in added} for q in azure] == expected
    # Prometheus targets keep their expression and instant/range flags exactly (this dashboard has no variables).
    expected_prom = [{"refId": t["refId"], "datasource": t["datasource"], "expr": t["expr"],
                      "instant": bool(t.get("instant", False)),
                      "range": bool(t.get("range", not t.get("instant", False)))}
                     for p, t in _targets(dashboard) if "expr" in t and not t.get("hide")]
    assert [{k: v for k, v in q.items() if k not in added} for q in prometheus] == expected_prom
    assert all(q["datasource"] == {"type": "prometheus", "uid": "victoriametrics"} for q in prometheus)
    incoming = [r for r in report if r.get("metric") == "IncomingRequests"]
    assert incoming[0]["value_sum"] == 7.0 and incoming[0]["aggregation"] == "Total"


def test_compare_requires_every_cli_metric_to_match_a_grafana_total():
    raw = {"value": [
        {"name": {"value": "IncomingMessages"}, "timeseries": [{"data": [{"total": 10.0}, {"total": 5.0}, {}]}]},
        {"name": {"value": "ThrottledRequests"}, "timeseries": [{"data": [{"total": 0.0}]}]},
    ]}
    report = [
        {"panel": "Messages / min", "metric": "IncomingMessages", "aggregation": "Total", "status": "pass",
         "value_sum": 15.0},
        {"panel": "Throttled requests", "metric": "ThrottledRequests", "aggregation": "Total", "status": "pass",
         "value_sum": 0.0},
    ]
    assert compare(report, raw)["all_match"]
    report[0]["value_sum"] = 14.0
    assert not compare(report, raw)["all_match"]
    assert not compare(report[1:], raw)["all_match"]  # a metric without a Grafana panel is a failure
    assert json.dumps(compare(report, raw))


def test_azure_monitor_panels_force_their_unit_over_the_data_source_unit():
    for panel in _panels(build_dashboard(SETTINGS)):
        if panel.get("datasource") == AZMON and panel["type"] != "text":
            unit = panel["fieldConfig"]["defaults"]["unit"]
            assert {"matcher": {"id": "byType", "options": "number"},
                    "properties": [{"id": "unit", "value": unit}]} in panel["fieldConfig"]["overrides"]


def test_selector_regex_catches_platform_series_with_underscores():
    pattern = r"\bazure_[a-z0-9_]+_(?:total|maximum|average)_[a-z0-9_]+\b"
    for name in ("azure_incomingmessages_total_Count", "azure_incoming_messages_total_count",
                 "azure_cpu_maximum_Percent"):
        assert re.search(pattern, name, re.IGNORECASE), name
    assert not re.search(pattern, "max by (azure_category) (eventhubs_log_arrival_delay_seconds)", re.IGNORECASE)


def test_compare_uses_an_absolute_tolerance_and_rejects_an_empty_result():
    raw = {"value": [{"name": {"value": "IncomingMessages"},
                      "timeseries": [{"data": [{"total": 1_000_000_000.0}]}]}]}
    report = [{"panel": "Messages / min", "metric": "IncomingMessages", "aggregation": "Total",
               "status": "pass", "value_sum": 1_000_000_000.9}]
    assert not compare(report, raw)["all_match"]
    assert not compare(report, {"value": []})["all_match"]


def test_cluster_resource_group_can_differ_from_the_namespace():
    dashboard = build_dashboard({**SETTINGS, "tier": "dedicated", "cluster": "ehc-example",
                                 "cluster_resource_group": "rg-cluster"})
    groups = {t["azureMonitor"]["resources"][0]["resourceGroup"] for _, t in _targets(dashboard)
              if t.get("azureMonitor", {}).get("metricNamespace") == "microsoft.eventhub/clusters"}
    assert groups == {"rg-cluster"}



def test_cli_passes_the_cluster_resource_group(monkeypatch, tmp_path):
    import build_direct_dashboard

    seen = {}

    def fake_build(settings):
        seen.update(settings)
        return {"panels": []}

    monkeypatch.setattr(build_direct_dashboard, "build_dashboard", fake_build)
    base = ["build_direct_dashboard.py", "--tier", "dedicated", "--subscription", "sub", "--resource-group", "rg-ns",
            "--namespace", "ehp-example", "--cluster", "ehc-example", "--output", str(tmp_path / "d.json")]
    monkeypatch.setattr(sys, "argv", [*base, "--cluster-resource-group", "rg-cluster"])
    build_direct_dashboard.main()
    assert seen["cluster_resource_group"] == "rg-cluster" and seen["resource_group"] == "rg-ns"
    monkeypatch.setattr(sys, "argv", base)
    build_direct_dashboard.main()
    assert seen["cluster_resource_group"] == ""  # empty falls back to the namespace group in build_dashboard



@pytest.mark.parametrize("timeseries", [[], [{"data": [{"total": None}, {}]}]])
def test_compare_rejects_a_metric_azure_monitor_never_observed(timeseries):
    raw = {"value": [{"name": {"value": "ThrottledRequests"}, "timeseries": timeseries}]}
    report = [{"panel": "Throttled requests", "metric": "ThrottledRequests", "aggregation": "Total",
               "status": "pass", "value_sum": 0.0}]
    assert not compare(report, raw)["all_match"]
