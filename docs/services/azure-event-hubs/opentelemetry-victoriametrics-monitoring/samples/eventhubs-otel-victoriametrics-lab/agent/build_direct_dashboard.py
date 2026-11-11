"""Build the dashboard for PLATFORM_METRICS=AzureMonitor: Azure Monitor direct query plus resource logs.

Platform metrics (CPU, memory, requests, throttling, throughput) are queried straight from Azure
Monitor through the Grafana Azure Monitor data source, so no Collector or VictoriaMetrics copy is
involved and no minute bin can be skipped. VictoriaMetrics holds only what Azure Monitor metrics do
not have: the Event Hubs resource logs (ApplicationMetricsLogs ConsumerLag, RuntimeAuditLogs) that
the Collector's azureeventhubreceiver reads from the telemetry Event Hub and turns into metrics.

Every Azure Monitor target names exactly one resource. Grafana then calls that resource's metrics
endpoint, so Monitoring Reader on the namespace or cluster is enough; a multi-resource target is
sent to the subscription-level endpoint and needs a subscription-scope role.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_dashboard import SELF, Layout, field, thresholds

UID = "eventhubs-azure-monitor-direct"
# The built-in Azure Monitor data source of Azure Managed Grafana; the Gateway Grafana provisions the same uid.
AZMON = {"type": "grafana-azure-monitor-datasource", "uid": "azure-monitor-oob"}
LOGS = 'source_path="diagnostic_logs",delivery_path="remote_write"'
NO_RECORD = "레코드 없음"
NAMESPACES = "microsoft.eventhub/namespaces"
CLUSTERS = "microsoft.eventhub/clusters"
LEGEND = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}


class Resource:
    def __init__(self, subscription: str, resource_group: str, name: str, namespace: str) -> None:
        if not all((subscription, resource_group, name)):
            raise ValueError("subscription, resource group and resource name are required")
        self.subscription = subscription
        self.resource_group = resource_group
        self.name = name
        self.namespace = namespace

    def metric(self, metric: str, aggregation: str, alias: str, split: str | None = None) -> dict:
        """One Azure Monitor metrics target at PT1M, optionally split by a dimension."""
        return {
            "datasource": AZMON,
            "queryType": "Azure Monitor",
            "subscription": self.subscription,
            "azureMonitor": {
                "resources": [{
                    "subscription": self.subscription,
                    "resourceGroup": self.resource_group,
                    "resourceName": self.name,
                    "metricNamespace": self.namespace,
                }],
                "metricNamespace": self.namespace,
                "metricName": metric,
                "aggregation": aggregation,
                "timeGrain": "PT1M",
                "alias": alias,
                # An empty filter list on a dimension means "split by every value" ('<dimension> eq *').
                "dimensionFilters": [{"dimension": split, "operator": "eq", "filters": []}] if split else [],
                "top": "10",
            },
        }


def capacity_panels(layout: Layout, panels: list[dict], tier: str, namespace: Resource,
                    cluster: Resource | None, usage: dict) -> None:
    gauge_opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                  "showThresholdMarkers": True}
    if tier == "dedicated":
        if cluster is None:
            raise ValueError("a Dedicated dashboard needs the cluster resource")
        panels.append(layout.panel(
            "gauge", "Dedicated CPU by role", 5, 7,
            [cluster.metric("CPU", "Maximum", "{{ dimensionvalue }}", split="Role")],
            datasource=AZMON,
            description="Role별 CPU Maximum의 최신 1분 값. Learn은 70%에 가까워지면 CU 확장을 검토하라고 안내합니다.",
            fieldConfig=field("percent", usage, decimals=1, min=0, max=100),
            options=gauge_opts,
        ))
        panels.append(layout.panel(
            "gauge", "Dedicated available memory by role", 5, 7,
            [cluster.metric("AvailableMemory", "Maximum", "{{ dimensionvalue }}", split="Role")],
            datasource=AZMON,
            description="Role별 가용 memory 비율. 낮을수록 위험하므로 threshold 방향이 CPU와 반대입니다.",
            fieldConfig=field("percent", thresholds(("red", None), ("orange", 15), ("green", 30)),
                              decimals=1, min=0, max=100),
            options=gauge_opts,
        ))
        panels.append(layout.panel(
            "timeseries", "Dedicated CPU·available memory by role", 14, 7,
            [cluster.metric("CPU", "Maximum", "CPU {{ dimensionvalue }}", split="Role"),
             cluster.metric("AvailableMemory", "Maximum", "available memory {{ dimensionvalue }}", split="Role")],
            datasource=AZMON,
            fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, fillOpacity=5),
            options=LEGEND,
        ))
        return
    for title, metric in (("Premium CPU", "NamespaceCpuUsage"), ("Premium memory", "NamespaceMemoryUsage")):
        panels.append(layout.panel(
            "gauge", title, 4, 7,
            [namespace.metric(metric, "Maximum", "maximum")],
            datasource=AZMON,
            description="Replica 최댓값의 최신 1분 값. 70%·85%에서 색이 바뀝니다.",
            fieldConfig=field("percent", usage, decimals=1, min=0, max=100),
            options=gauge_opts,
        ))
    panels.append(layout.panel(
        "timeseries", "Premium CPU·memory 추이", 16, 7,
        [namespace.metric("NamespaceCpuUsage", "Maximum", "CPU max"),
         namespace.metric("NamespaceCpuUsage", "Average", "CPU avg"),
         namespace.metric("NamespaceMemoryUsage", "Maximum", "memory max"),
         namespace.metric("NamespaceMemoryUsage", "Average", "memory avg")],
        datasource=AZMON,
        # The Metrics API rejects a Replica split of these metrics: "include hidden dimensions: Replica".
        description="1분 Maximum·Average입니다. Replica dimension은 Metrics API에서 숨겨진 dimension이라 나눠 조회할 수 없습니다.",
        fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, fillOpacity=5) | {"overrides": [{
            "matcher": {"id": "byRegexp", "options": ".*avg"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}}]}]},
        options=LEGEND,
    ))


def build_dashboard(settings: dict) -> dict:
    tier = settings.get("tier", "premium")
    if tier not in ("premium", "dedicated"):
        raise ValueError(f"tier must be premium or dedicated, got {tier!r}")
    capacity = settings.get("capacity_units", 1)
    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0:
        raise ValueError(f"capacity_units must be a positive integer, got {capacity!r}")
    unit = "CU" if tier == "dedicated" else "PU"
    namespace = Resource(settings["subscription"], settings["resource_group"], settings["namespace"], NAMESPACES)
    cluster = None
    if settings.get("cluster"):
        cluster = Resource(settings["subscription"], settings.get("cluster_resource_group") or settings["resource_group"],
                           settings["cluster"], CLUSTERS)

    layout = Layout()
    panels: list[dict] = []
    usage = thresholds(("green", None), ("orange", 70), ("red", 85))
    green_only = thresholds(("green", None))
    stat_opts = {"reduceOptions": {"calcs": ["sum"], "fields": "", "values": False},
                 "colorMode": "value", "graphMode": "none", "textMode": "value"}

    panels.append(layout.row(f"플랫폼 지표: Azure Monitor 직접 조회 ({capacity} {unit}, Collector·VictoriaMetrics 거치지 않음)"))
    capacity_panels(layout, panels, tier, namespace, cluster, usage)

    for title, metric, steps, note in (
        ("Incoming requests", "IncomingRequests", green_only, "1분 Total을 조회 구간 동안 더한 값"),
        ("Successful requests", "SuccessfulRequests", green_only, "1분 Total을 조회 구간 동안 더한 값"),
        # Without a dimension split Azure Monitor returns an explicit 0 while nothing is throttled.
        ("Throttled requests", "ThrottledRequests", thresholds(("green", None), ("red", 1)),
         "dimension을 나누지 않아 throttle이 없을 때도 0 값이 옵니다. 데이터가 없으면 'No data'입니다."),
    ):
        panels.append(layout.panel(
            "stat", title, 5, 6,
            [namespace.metric(metric, "Total", title)],
            datasource=AZMON,
            description=note,
            fieldConfig=field("locale", steps, decimals=0),
            options=stat_opts,
        ))
    panels.append(layout.panel(
        "text", "데이터 소스 구분", 9, 6, [],
        options={"mode": "markdown", "content": (
            "**플랫폼 지표는 Azure Monitor 데이터 소스**로 Metrics API를 바로 조회합니다. "
            "Collector의 `azuremonitorreceiver`와 VictoriaMetrics 사본이 없어 분 bin이 빠지지 않습니다.\n\n"
            "**consumer lag와 data plane 접근은 VictoriaMetrics**에서 읽습니다. Event Hubs 리소스 로그"
            "(`ApplicationMetricsLogs`·`RuntimeAuditLogs`)를 Collector의 `azureeventhubreceiver`가 "
            "telemetry Event Hub에서 읽어 지표로 바꿉니다."
        )},
    ))

    panels.append(layout.row(f"처리량 (namespace 합계, 분당 Total, capacity = {capacity} {unit})"))
    for title, incoming, outgoing, value_unit in (
        ("Messages / min", "IncomingMessages", "OutgoingMessages", "short"),
        ("Bytes / min", "IncomingBytes", "OutgoingBytes", "decbytes"),
    ):
        panels.append(layout.panel(
            "timeseries", title, 12, 8,
            [namespace.metric(incoming, "Total", "incoming"), namespace.metric(outgoing, "Total", "outgoing")],
            datasource=AZMON,
            fieldConfig=field(value_unit, None, decimals=0, drawStyle="bars", fillOpacity=60,
                              lineWidth=1, barAlignment=0),
            options=LEGEND,
        ))

    log_note = ("Event Hubs 리소스 로그 → Diagnostic Settings → telemetry Event Hub → azureeventhubreceiver → "
                "VictoriaMetrics. 레코드는 약 100초 늦게 오고, Collector가 처리한 시각으로 기록됩니다.")
    panels.append(layout.row("Consumer lag·data plane 접근: 리소스 로그 → azureeventhubreceiver → VictoriaMetrics"))
    panels.append(layout.panel(
        "stat", "Peak ConsumerLag (window)", 4, 8,
        [{"expr": f"max(max_over_time(eventhubs_log_consumer_lag{{{LOGS}}}[$__range]))", "instant": True,
          "legendFormat": "peak"}],
        description=log_note + " AMQP receiver에 마지막으로 전달된 sequence와 마지막 enqueue sequence의 차이입니다.",
        fieldConfig=field("locale", thresholds(("green", None), ("orange", 1000), ("red", 20000)), decimals=0,
                          no_value=NO_RECORD),
        options=stat_opts | {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    ))
    panels.append(layout.panel(
        "timeseries", "ConsumerLag by partition (stacked)", 10, 8,
        [{"expr": f"max by (messaging_destination_partition_id) (eventhubs_log_consumer_lag{{{LOGS}}})",
          "legendFormat": "partition {{messaging_destination_partition_id}}"}],
        description=(log_note + " 받을 event가 없으면 Event Hubs가 레코드를 쓰지 않으므로, 회복 뒤에는 0이 아니라 "
                     "선이 끊깁니다."),
        fieldConfig=field("locale", None, min=0, lineWidth=1, fillOpacity=35, showPoints="always", pointSize=3,
                          stacking={"mode": "normal", "group": "A"}, no_value=NO_RECORD),
        options=LEGEND,
    ))
    panels.append(layout.panel(
        "stat", "Resource log records", 4, 8,
        [{"expr": f"sum(increase(eventhubs_log_records_total{{{LOGS}}}[$__range]))", "instant": True,
          "legendFormat": "records"}],
        description="조회 구간에 받은 ApplicationMetricsLogs·RuntimeAuditLogs 레코드 수입니다.",
        fieldConfig={"defaults": {"unit": "locale", "decimals": 0, "noValue": NO_RECORD,
                                  "color": {"mode": "fixed", "fixedColor": "text"}}, "overrides": []},
        options=stat_opts | {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    ))
    panels.append(layout.panel(
        "timeseries", "Resource log arrival delay", 6, 8,
        [{"expr": f"max by (azure_category) (eventhubs_log_arrival_delay_seconds{{{LOGS}}})",
          "legendFormat": "{{azure_category}}"}],
        description="레코드 시각부터 Collector가 처리할 때까지의 초입니다.",
        fieldConfig=field("s", None, decimals=0, min=0, lineWidth=2, showPoints="always", pointSize=3,
                          no_value=NO_RECORD),
        options=LEGEND,
    ))
    panels.append(layout.panel(
        "timeseries", "Runtime audit operations / min", 12, 8,
        [{"expr": f"sum by (azure_operation_name) (increase(eventhubs_log_runtime_operations_total{{{LOGS}}}[1m]))",
          "legendFormat": "{{azure_operation_name}}"}],
        description="RuntimeAuditLogs의 1분 집계 Count를 작업별로 더한 값입니다.",
        fieldConfig=field("locale", None, decimals=0, drawStyle="bars", fillOpacity=60, stacking={"mode": "normal"},
                          no_value=NO_RECORD),
        options=LEGEND,
    ))
    panels.append(layout.panel(
        "table", "Data plane access by auth · protocol · network", 12, 8,
        [{"expr": ("sum by (azure_operation_name, azure_auth_type, network_protocol_name, network_connection_type, "
                   f"error_type) (increase(eventhubs_log_runtime_operations_total{{{LOGS}}}[$__range]))"),
          "instant": True, "format": "table"}],
        description="RuntimeAuditLogs를 인증 방식·protocol·network별로 합친 값입니다. client IP와 인증 ID는 label로 만들지 않습니다.",
        transformations=[{"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "renameByName": {"azure_operation_name": "Operation", "azure_auth_type": "Auth",
                             "network_protocol_name": "Protocol", "network_connection_type": "Network",
                             "error_type": "Error", "Value": "Count"}}}],
        fieldConfig={"defaults": {"unit": "locale", "decimals": 0, "noValue": NO_RECORD}, "overrides": []},
    ))

    panels.append(layout.row("VictoriaMetrics에 저장되는 것과 Collector 상태"))
    panels.append(layout.panel(
        "table", "Series stored in VictoriaMetrics", 12, 7,
        [{"expr": 'count by (source_path, delivery_path) (last_over_time({source_path!=""}[$__range]))',
          "instant": True, "format": "table"},
         {"expr": 'time() - max by (source_path, delivery_path) (tlast_over_time({source_path!=""}[$__range]))',
          "instant": True, "format": "table"}],
        description=("이 구성에서 VictoriaMetrics에는 플랫폼 지표가 없습니다. 리소스 로그 지표(diagnostic_logs)와 "
                     "Collector 자체 지표(collector_self)만 scrape·remote write 두 경로로 저장됩니다."),
        fieldConfig={"defaults": {"unit": "short", "decimals": 0},
                     "overrides": [{"matcher": {"id": "byName", "options": "Last sample age"},
                                    "properties": [{"id": "unit", "value": "s"}]}]},
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True},
                "renameByName": {"source_path": "Source", "delivery_path": "Delivery",
                                 "Value #A": "Series", "Value #B": "Last sample age"}}},
        ],
    ))
    for title, expr, description in (
        ("Receiver refused·failed points",
         f'sum(increase({{__name__=~"otelcol_receiver_(refused|failed)_metric_points_total",{SELF}}}[$__range]))'
         f" or (0 * sum(increase(otelcol_receiver_accepted_metric_points_total{{{SELF}}}[$__range])))",
         "receiver가 pipeline에 넘기지 못한 data point 수. 수락 counter가 있을 때만 0으로 해석합니다."),
        ("Exporter send failures",
         f"sum(increase(otelcol_exporter_send_failed_metric_points_total{{{SELF}}}[$__range]))"
         f" or (0 * sum(increase(otelcol_exporter_sent_metric_points_total{{{SELF}}}[$__range])))",
         "실패 counter는 첫 실패 때 생성됩니다. 전송 성공 counter가 있을 때만 0으로 해석합니다."),
    ):
        panels.append(layout.panel(
            "stat", title, 6, 7, [{"expr": expr, "instant": True, "legendFormat": title}],
            description=description,
            fieldConfig=field("short", thresholds(("green", None), ("red", 1)), decimals=0),
            options=stat_opts | {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
        ))

    # The Azure Monitor data source sets its own unit on every returned field, which wins over the panel
    # default; an override wins over both, so the panel unit is applied that way.
    for panel in panels:
        if panel.get("datasource") == AZMON and "fieldConfig" in panel:
            unit = panel["fieldConfig"]["defaults"].get("unit")
            panel["fieldConfig"].setdefault("overrides", []).append(
                {"matcher": {"id": "byType", "options": "number"}, "properties": [{"id": "unit", "value": unit}]})

    return {
        "uid": UID,
        "title": "Event Hubs: Azure Monitor direct + resource logs",
        "tags": ["event-hubs", "azure-monitor", "victoriametrics"],
        "timezone": "utc",
        "schemaVersion": 41,
        "editable": False,
        "graphTooltip": 1,
        "refresh": "",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {"list": []},
        "panels": panels,
    }


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("premium", "dedicated"), default="premium")
    parser.add_argument("--capacity-units", type=positive_int, default=1)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--namespace", required=True, help="workload Event Hubs namespace name")
    parser.add_argument("--cluster", default="", help="Dedicated cluster name (Dedicated tier)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dashboard = build_dashboard({
        "tier": args.tier,
        "capacity_units": args.capacity_units,
        "subscription": args.subscription,
        "resource_group": args.resource_group,
        "namespace": args.namespace,
        "cluster": args.cluster,
    })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
    print(f"{len(dashboard['panels'])} panels -> {args.output}")


if __name__ == "__main__":
    main()
