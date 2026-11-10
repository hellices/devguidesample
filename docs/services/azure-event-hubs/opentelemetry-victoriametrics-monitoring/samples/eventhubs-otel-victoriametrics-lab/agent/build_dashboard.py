"""Build the Event Hubs observability dashboard from a probe inventory.

Each panel answers one operator question. The planning table lives in ``PANEL_PLAN`` so that
reviewers can compare question, metric, MetricsQL and visualization without reading JSON.

Platform totals are read from the remote write path only: remote write keeps the Azure
Monitor minute timestamp and stores one sample per minute, while the scrape path re-exposes
the same minute value on every scrape, so ``sum_over_time`` over scrape samples double counts.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

UID = "eventhubs-otel-victoriametrics"
DS = {"type": "prometheus", "uid": "victoriametrics"}
API = 'source_path="azure_monitor_api",delivery_path="remote_write"'
DIAG = 'source_path="diagnostic_eventhub",delivery_path="remote_write"'
DEDICATED = 'source_path="azure_monitor_dedicated",delivery_path="remote_write"'
LAG = 'source_path="lag_exporter",delivery_path="remote_write"'
SELF = 'source_path="collector_self",delivery_path="remote_write"'
LEARN_METRICS = "https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference"

# question, metric, MetricsQL summary, visualization
PANEL_PLAN = [
    ("Premium replica CPU가 위험 구간인가", "NamespaceCpuUsage Maximum", "max(last_over_time)", "gauge"),
    ("Premium memory가 위험 구간인가", "NamespaceMemoryUsage Maximum", "max(last_over_time)", "gauge"),
    ("CPU·memory가 부하와 함께 어떻게 움직였나", "Namespace*Usage Average/Maximum", "raw", "time series"),
    ("구간 동안 요청·성공·throttle은 몇 건인가", "Incoming/Successful/ThrottledRequests Total", "sum_over_time[$__range]", "stat"),
    ("송신 방향 request 수를 볼 수 있나", "OutgoingRequests 없음", "계산하지 않음", "text"),
    ("PU당 분당 처리량은 얼마인가", "Incoming/OutgoingMessages·Bytes Total / PU", "sum by minute / $pu", "bars"),
    ("조회 구간에서 가장 크게 밀린 partition은 얼마나 밀렸나", "eventhubs_consumer_lag_messages", "max / max by partition", "stat, bar gauge"),
    ("lag가 언제 쌓이고 언제 회복됐나", "eventhubs_consumer_lag_messages", "max by partition", "time series"),
    ("모든 partition에 checkpoint가 있나", "eventhubs_checkpoint_present", "min by partition", "table"),
    ("수집·전달 경로별로 데이터가 들어오나", "{source_path,delivery_path}", "count_over_time, tlast_over_time", "table"),
    ("scrape와 remote write의 값 형태가 같은가", "IncomingMessages Total", "by delivery_path", "time series"),
    ("API와 Diagnostic Settings 값이 같은가", "IncomingMessages Total, NamespaceCpuUsage Maximum", "by source_path", "time series"),
    ("Collector가 데이터를 거부·전송 실패했나", "otelcol_receiver_refused_*, otelcol_exporter_send_failed_*", "increase", "stat"),
]


class Layout:
    def __init__(self) -> None:
        self.y = 0
        self.x = 0
        self.row_height = 0
        self.next_id = 1

    def place(self, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.y += self.row_height
            self.x = 0
            self.row_height = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_height = max(self.row_height, h)
        return pos

    def row(self, title: str) -> dict:
        self.y += self.row_height
        self.x = 0
        self.row_height = 1
        panel = {
            "type": "row",
            "title": title,
            "collapsed": False,
            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1},
            "id": self.next_id,
            "panels": [],
        }
        self.next_id += 1
        self.y += 1
        self.row_height = 0
        return panel

    def panel(self, kind: str, title: str, w: int, h: int, targets: list[dict], **extra) -> dict:
        panel = {
            "type": kind,
            "title": title,
            "id": self.next_id,
            "datasource": DS,
            "gridPos": self.place(w, h),
            "targets": [
                {"refId": chr(65 + i), "datasource": DS, **target} for i, target in enumerate(targets)
            ],
        }
        self.next_id += 1
        panel.update(extra)
        return panel


def thresholds(*steps: tuple[str, float | None]) -> dict:
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def field(unit: str = "short", steps=None, decimals=None, no_value=None, **custom) -> dict:
    defaults: dict = {"unit": unit}
    if steps:
        defaults["thresholds"] = steps
        defaults["color"] = {"mode": "thresholds"}
    else:
        # Time series need one colour per series; threshold colouring paints every line alike.
        defaults["color"] = {"mode": "palette-classic"}
    if decimals is not None:
        defaults["decimals"] = decimals
    if no_value is not None:
        defaults["noValue"] = no_value
    # min and max are standard field options; everything else is a visualization-specific option.
    for key in ("min", "max"):
        if key in custom:
            defaults[key] = custom.pop(key)
    if custom:
        defaults["custom"] = custom
    return {"defaults": defaults, "overrides": []}


def build_dashboard(probe: dict) -> dict:
    pu = int(probe.get("processing_units", 1))
    if pu <= 0:
        raise ValueError(f"processing_units must be a positive integer, got {pu}")
    layout = Layout()
    panels: list[dict] = []
    green_only = thresholds(("green", None))
    usage = thresholds(("green", None), ("orange", 70), ("red", 85))
    stat_opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "colorMode": "value", "graphMode": "none", "textMode": "value_and_name"}

    panels.append(layout.row(f"Premium 용량 상태 ({pu} PU, Azure Monitor API → remote write)"))
    for title, metric in (("Premium CPU", "namespacecpuusage"), ("Premium Memory", "namespacememoryusage")):
        panels.append(layout.panel(
            "gauge", title, 4, 7,
            [{"expr": f"max(last_over_time(azure_{metric}_maximum_Percent{{{API}}}[10m]))",
              "instant": True, "legendFormat": "maximum"}],
            description="Replica 최댓값의 최신 1분 값. 70%·85%에서 색이 바뀝니다.",
            fieldConfig=field("percent", usage, decimals=1, min=0, max=100),
            options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                     "showThresholdMarkers": True},
        ))
    panels.append(layout.panel(
        "timeseries", "Premium CPU·Memory 추이", 16, 7,
        [
            {"expr": f"azure_namespacecpuusage_maximum_Percent{{{API}}}", "legendFormat": "CPU max"},
            {"expr": f"azure_namespacecpuusage_average_Percent{{{API}}}", "legendFormat": "CPU avg"},
            {"expr": f"azure_namespacememoryusage_maximum_Percent{{{API}}}", "legendFormat": "Memory max"},
            {"expr": f"azure_namespacememoryusage_average_Percent{{{API}}}", "legendFormat": "Memory avg"},
        ],
        fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, fillOpacity=5,
                          spanNulls=120000) | {"overrides": [{
            "matcher": {"id": "byRegexp", "options": ".*avg"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [6, 4]}}]}]},
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))

    panels.append(layout.row("요청과 throttle (조회 구간 합계)"))
    for title, metric, steps in (
        ("Incoming requests", "incomingrequests", green_only),
        ("Successful requests", "successfulrequests", green_only),
        ("Throttled requests", "throttledrequests", thresholds(("green", None), ("red", 1))),
    ):
        panels.append(layout.panel(
            "stat", title, 5, 6,
            # Azure Monitor stamps each sample with its minute-bin start. Shifting by 1s turns the
            # (from, to] lookback into [from, to), the window az monitor metrics list uses.
            [{"expr": f"sum(sum_over_time(azure_{metric}_total_Count{{{API}}}[$__range] offset 1s))",
              "instant": True, "legendFormat": title}],
            description=("0은 series가 존재하고 값이 0이라는 뜻입니다. 데이터가 없으면 'No data'로 표시합니다."
                         if metric == "throttledrequests" else "remote write의 1분 Total을 조회 구간 동안 더한 값"),
            fieldConfig=field("locale", steps, decimals=0),
            options=stat_opts | {"textMode": "value"},
        ))
    panels.append(layout.panel(
        "text", "Outgoing Requests support boundary", 9, 6, [],
        options={"mode": "markdown", "content": (
            "**Outgoing Requests는 Azure Monitor 지표가 아닙니다.**\n\n"
            "`Microsoft.EventHub/namespaces` 지표표에는 `IncomingRequests`, `SuccessfulRequests`, "
            "`ThrottledRequests`만 있습니다. 송신 방향은 아래 *Outgoing messages·bytes*로 판단하고 "
            "request 수는 추정하지 않습니다.\n\n"
            f"[Event Hubs monitoring data reference]({LEARN_METRICS})"
        )},
    ))

    panels.append(layout.row(f"PU당 처리량 (processing_units = {pu}, 분당 Total)"))
    for title, metric, unit in (
        ("Messages per PU / min", "messages", "short"),
        ("Bytes per PU / min", "bytes", "decbytes"),
    ):
        suffix = "Count" if metric == "messages" else "Bytes"
        panels.append(layout.panel(
            "timeseries", title, 12, 8,
            [
                {"expr": f"sum(azure_incoming{metric}_total_{suffix}{{{API}}}) / $pu", "legendFormat": "incoming"},
                {"expr": f"sum(azure_outgoing{metric}_total_{suffix}{{{API}}}) / $pu", "legendFormat": "outgoing"},
            ],
            interval="1m",
            fieldConfig=field(unit, None, decimals=0, drawStyle="bars", fillOpacity=60,
                              lineWidth=1, barAlignment=0),
            options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
        ))

    panels.append(layout.row("Consumer lag (마지막 enqueue sequence − checkpoint sequence)"))
    panels.append(layout.panel(
        "stat", "Peak lag (window)", 4, 8,
        [{"expr": f"max(max_over_time(eventhubs_consumer_lag_messages{{{LAG}}}[$__range]))", "instant": True,
          "legendFormat": "peak lag"}],
        description="조회 구간에서 checkpoint가 있는 partition 중 가장 컸던 미처리 event 수",
        fieldConfig=field("locale", thresholds(("green", None), ("orange", 1000), ("red", 20000)), decimals=0),
        options=stat_opts | {"textMode": "value"},
    ))
    panels.append(layout.panel(
        "bargauge", "Peak lag by partition (window)", 6, 8,
        [{"expr": f"max by (partition) (max_over_time(eventhubs_consumer_lag_messages{{{LAG}}}[$__range]))",
          "instant": True,
          "legendFormat": "partition {{partition}}"}],
        # Reduce to one numeric field so every partition shares the same 0..max scale.
        transformations=[{"id": "reduce", "options": {"reducers": ["max"], "labelsToFields": False}}],
        fieldConfig={"defaults": {"unit": "locale", "decimals": 0, "min": 0, "color": {"mode": "thresholds"},
                                  "thresholds": thresholds(("green", None), ("orange", 1000), ("red", 20000))},
                     "overrides": []},
        options={"orientation": "horizontal", "displayMode": "gradient",
                 "reduceOptions": {"calcs": [], "fields": "/^Max$/", "values": True}},
    ))
    panels.append(layout.panel(
        "timeseries", "Consumer lag by partition (stacked)", 6, 8,
        [{"expr": f"max by (partition) (eventhubs_consumer_lag_messages{{{LAG}}})",
          "legendFormat": "partition {{partition}}"}],
        description="partition별 lag를 쌓아 위쪽 경계가 전체 backlog가 되도록 표시합니다.",
        fieldConfig=field("locale", None, min=0, lineWidth=1, fillOpacity=35,
                          stacking={"mode": "normal", "group": "A"}),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    panels.append(layout.panel(
        "stat", "Lag collection", 3, 8,
        [{"expr": f"min(min_over_time(eventhubs_lag_collection_success{{{LAG}}}[$__range]))", "instant": True,
          "legendFormat": "collection"}],
        description="조회 구간에서 lag exporter의 수집이 한 번이라도 실패했으면 Failed로 표시합니다. 실패하면 lag 값을 지워 오래된 값이 정상처럼 보이지 않게 합니다.",
        fieldConfig={"defaults": {"unit": "short", "decimals": 0, "noValue": "No data",
                                  "color": {"mode": "thresholds"},
                                  "thresholds": thresholds(("red", None), ("green", 1)),
                                  "mappings": [{"type": "value", "options": {
                                      "0": {"text": "Failed"}, "1": {"text": "OK"}}}]},
                     "overrides": []},
        options=stat_opts | {"textMode": "value"},
    ))
    panels.append(layout.panel(
        "table", "Checkpoint presence", 5, 8,
        [{"expr": f"min by (partition) (eventhubs_checkpoint_present{{{LAG}}})", "instant": True,
          "format": "table"}],
        description="1 = checkpoint blob 존재. checkpoint가 없으면 lag 값을 만들지 않습니다.",
        fieldConfig={"defaults": {"unit": "short", "decimals": 0}, "overrides": [{
            "matcher": {"id": "byName", "options": "Checkpoint"},
            "properties": [
                {"id": "thresholds", "value": thresholds(("red", None), ("green", 1))},
                {"id": "color", "value": {"mode": "thresholds"}},
                {"id": "custom.cellOptions", "value": {"type": "color-text"}},
            ]}]},
        transformations=[{"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "renameByName": {"partition": "Partition", "Value": "Checkpoint"}}}],
    ))

    panels.append(layout.row("수집·전달 경로 비교 (source_path × delivery_path)"))
    panels.append(layout.panel(
        "table", "Receiver and delivery path comparison", 11, 11,
        [
            {"expr": 'count by (source_path, delivery_path) (count_over_time({source_path!=""}[$__range]))',
             "instant": True, "format": "table"},
            {"expr": ('sum by (source_path, delivery_path) (count_over_time({source_path!=""}[$__range]))'
                      ' / count by (source_path, delivery_path) (count_over_time({source_path!=""}[$__range]))'
                      ' / ($__range_s / 60)'),
             "instant": True, "format": "table"},
            {"expr": 'time() - max by (source_path, delivery_path) (tlast_over_time({source_path!=""}[$__range]))',
             "instant": True, "format": "table"},
        ],
        description=("같은 receiver 출력을 두 exporter로 fan-out했습니다. scrape 경로는 Collector가 노출한 "
                     "마지막 값을 scrape마다 다시 저장하므로 series당 분당 sample 수가 scrape 주기를 따릅니다. "
                     "Last sample age가 커지면 해당 경로의 수집이 구간 중간에 멈춘 것입니다."),
        fieldConfig={"defaults": {"unit": "short", "decimals": 0},
                     "overrides": [{"matcher": {"id": "byName", "options": "Samples/series/min"},
                                    "properties": [{"id": "decimals", "value": 2}]},
                                   {"matcher": {"id": "byName", "options": "Last sample age"},
                                    "properties": [{"id": "unit", "value": "s"}]}]},
        transformations=[
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {
                "excludeByName": {"Time": True},
                "renameByName": {"source_path": "Source", "delivery_path": "Delivery",
                                 "Value #A": "Series", "Value #B": "Samples/series/min",
                                 "Value #C": "Last sample age"}}},
        ],
    ))
    panels.append(layout.panel(
        "stat", "DS Event Hub series", 4, 11,
        [{"expr": 'count(last_over_time({source_path="diagnostic_eventhub"}[$__range]))', "instant": True,
          "legendFormat": "series"}],
        description=("[optional] Diagnostic Settings가 telemetry Event Hub로 보낸 지표 수. "
                     "series가 없으면 0으로 바꾸지 않고 '수신 없음'으로 표시합니다."),
        fieldConfig={"defaults": {"unit": "short", "decimals": 0, "noValue": "수신 없음",
                                  "color": {"mode": "fixed", "fixedColor": "text"}}, "overrides": []},
        options=stat_opts | {"textMode": "value"},
    ))
    panels.append(layout.panel(
        "timeseries", "Same metric, two delivery paths (IncomingMessages)", 9, 11,
        [{"expr": 'sum by (delivery_path) (azure_incomingmessages_total_Count{source_path="azure_monitor_api"})',
          "legendFormat": "{{delivery_path}}"}],
        description="remote write는 Azure Monitor의 분 단위 timestamp를 유지하고, scrape는 수집 시각으로 다시 찍혀 1–3분 늦게 보입니다.",
        fieldConfig=field("locale", None, lineWidth=2, showPoints="always", pointSize=4),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))

    panels.append(layout.row("Azure Monitor API vs Diagnostic Settings (remote write)"))
    panels.append(layout.panel(
        "timeseries", "IncomingMessages: API vs Diagnostic Settings", 12, 8,
        [
            {"expr": f"sum(azure_incomingmessages_total_Count{{{API}}})", "legendFormat": "azure_monitor_api"},
            {"expr": f"sum(incomingmessages_total{{{DIAG}}})", "legendFormat": "diagnostic_eventhub"},
        ],
        description=("[optional] Diagnostic Settings 경로는 설정 후 데이터가 흐르기까지 시간이 걸릴 수 있습니다. "
                     "Diagnostic Settings는 dimension을 합친 단일 값으로 내보내므로 EntityName별 API 값의 합과 비교합니다."),
        fieldConfig=field("locale", None, lineWidth=2, showPoints="always", pointSize=4) | {"overrides": [{
            "matcher": {"id": "byName", "options": "diagnostic_eventhub"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
                           {"id": "custom.lineWidth", "value": 3}]}]},
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    panels.append(layout.panel(
        "timeseries", "NamespaceCpuUsage maximum: API vs Diagnostic Settings", 12, 8,
        [
            {"expr": f"max(azure_namespacecpuusage_maximum_Percent{{{API}}})", "legendFormat": "azure_monitor_api"},
            {"expr": f"max(namespacecpuusage_maximum{{{DIAG}}})", "legendFormat": "diagnostic_eventhub"},
        ],
        description=("[optional] 지표표의 DS Export 값은 No지만 이 실습에서는 Diagnostic Settings 스트림에도 "
                     "레코드가 도착했습니다. 두 경로를 겹쳐 그 차이를 확인합니다."),
        fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, showPoints="always", pointSize=4) | {"overrides": [{
            "matcher": {"id": "byName", "options": "diagnostic_eventhub"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
                           {"id": "custom.lineWidth", "value": 3}]}]},
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))

    panels.append(layout.row("Collector 상태"))
    for title, expr, description in (
        ("Receiver refused·failed points",
         # One selector so a missing refused or failed series cannot empty the whole sum.
         f'sum(increase({{__name__=~"otelcol_receiver_(refused|failed)_metric_points_total",{SELF}}}[$__range]))'
         f" or (0 * sum(increase(otelcol_receiver_accepted_metric_points_total{{{SELF}}}[$__range])))",
         "receiver가 pipeline에 넘기지 못한 data point 수. 수락 counter가 있을 때만 0으로 해석합니다."),
        # The failure counter is created on the first failure. Read 0 only while the matching
        # success counter proves the exporter is reporting; otherwise the panel shows No data.
        ("Exporter send failures",
         f"sum(increase(otelcol_exporter_send_failed_metric_points_total{{{SELF}}}[$__range]))"
         f" or (0 * sum(increase(otelcol_exporter_sent_metric_points_total{{{SELF}}}[$__range])))",
         "실패 counter는 첫 실패 때 생성됩니다. 전송 성공 counter가 있을 때만 0으로 해석합니다."),
    ):
        panels.append(layout.panel(
            "stat", title, 6, 5, [{"expr": expr, "instant": True, "legendFormat": title}],
            description=description,
            fieldConfig=field("short", thresholds(("green", None), ("red", 1)), decimals=0),
            options=stat_opts | {"textMode": "value"},
        ))
    panels.append(layout.panel(
        "bargauge", "Accepted points by receiver", 12, 5,
        [{"expr": f'sum by (receiver) (increase(otelcol_receiver_accepted_metric_points_total{{{SELF}}}[$__range]))',
          "instant": True, "legendFormat": "{{receiver}}"}],
        description="[optional] Diagnostic Event Hub receiver는 이벤트를 받기 전까지 counter가 없을 수 있습니다.",
        fieldConfig=field("short", green_only, decimals=0, min=0),
        options={"orientation": "horizontal", "displayMode": "basic",
                 "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}},
    ))

    if probe.get("dedicated_enabled"):
        panels.append(layout.row("Dedicated cluster (문서 기반 profile, 이 실습에서 runtime 미검증)"))
        panels.append(layout.panel(
            "gauge", "Dedicated CPU", 6, 7,
            [{"expr": f"max(last_over_time(azure_cpu_maximum_Percent{{{DEDICATED}}}[10m]))",
              "instant": True}],
            fieldConfig=field("percent", usage, decimals=1, min=0, max=100),
        ))
        panels.append(layout.panel(
            "gauge", "Dedicated available memory", 6, 7,
            [{"expr": f"min(last_over_time(azure_availablememory_maximum_Percent{{{DEDICATED}}}[10m]))",
              "instant": True}],
            description="가용 메모리 비율입니다. 낮을수록 위험하므로 threshold 방향이 CPU와 반대입니다.",
            fieldConfig=field("percent", thresholds(("red", None), ("orange", 15), ("green", 30)),
                              decimals=1, min=0, max=100),
        ))

    return {
        "uid": UID,
        "title": "Event Hubs observability (OTel → VictoriaMetrics)",
        "tags": ["event-hubs", "opentelemetry", "victoriametrics"],
        "timezone": "utc",
        "schemaVersion": 41,
        "editable": False,
        "graphTooltip": 1,
        "refresh": "",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {"list": [
            {"name": "pu", "type": "constant", "query": str(pu), "hide": 2,
             "label": "Premium processing units"},
        ]},
        "panels": panels,
    }


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--processing-units", type=positive_int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe = json.loads(args.probe.read_text())
    probe.setdefault("processing_units", args.processing_units)
    probe.setdefault("dedicated_enabled", any(
        name.startswith(("azure_cpu_", "azure_availablememory_")) for name in probe.get("metrics", {})))
    dashboard = build_dashboard(probe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
    print(f"{len(dashboard['panels'])} panels -> {args.output}")


if __name__ == "__main__":
    main()
