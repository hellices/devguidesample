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
# A Dedicated cluster streams to the same hub; keep namespace records only.
DIAG = ('source_path="diagnostic_eventhub",delivery_path="remote_write",'
        'azure_resource_id=~"(?i).*/providers/microsoft\\\\.eventhub/namespaces/.*"')
DEDICATED = 'source_path="azure_monitor_dedicated",delivery_path="remote_write"'
DIAG_CLUSTER = ('source_path="diagnostic_eventhub",delivery_path="remote_write",'
                'azure_resource_id=~"(?i).*/providers/microsoft\\\\.eventhub/clusters/.*"')
LAG = 'source_path="lag_exporter",delivery_path="remote_write"'
LOGS = 'source_path="diagnostic_logs",delivery_path="remote_write"'
LOGS_OFF = "로그 꺼짐·수신 없음"
SELF = 'source_path="collector_self",delivery_path="remote_write"'
LEARN_METRICS = "https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference"

# question, metric, MetricsQL summary, visualization
PANEL_PLAN = [
    ("Premium replica CPU가 위험 구간인가", "NamespaceCpuUsage Maximum", "max(last_over_time)", "gauge"),
    ("Premium memory가 위험 구간인가", "NamespaceMemoryUsage Maximum", "max(last_over_time)", "gauge"),
    ("Dedicated cluster CPU가 위험 구간인가", "clusters CPU Maximum (Role)", "max(last_over_time)", "gauge"),
    ("Dedicated cluster 가용 memory가 부족한가", "clusters AvailableMemory Maximum (Role)", "min(last_over_time)", "gauge"),
    ("Dedicated cluster 전체 사용률은 얼마인가", "clusters ClusterUtilization Average (preview)", "last_over_time", "gauge"),
    ("CPU·memory가 부하와 함께 어떻게 움직였나", "Namespace*Usage Average/Maximum", "raw", "time series"),
    ("구간 동안 요청·성공·throttle은 몇 건인가", "Incoming/Successful/ThrottledRequests Total", "sum_over_time[$__range]", "stat"),
    ("송신 방향 request 수를 볼 수 있나", "OutgoingRequests 없음", "계산하지 않음", "text"),
    ("PU·CU당 분당 처리량은 얼마인가", "Incoming/OutgoingMessages·Bytes Total / capacity", "sum by minute / $capacity", "bars"),
    ("조회 구간에서 가장 크게 밀린 partition은 얼마나 밀렸나", "eventhubs_consumer_lag_messages", "max / max by partition", "stat, bar gauge"),
    ("lag가 언제 쌓이고 언제 회복됐나", "eventhubs_consumer_lag_messages", "max by partition", "time series"),
    ("모든 partition에 checkpoint가 있나", "eventhubs_checkpoint_present", "min by partition", "table"),
    ("수집·전달 경로별로 데이터가 들어오나", "{source_path,delivery_path}", "count_over_time, tlast_over_time", "table"),
    ("scrape와 remote write의 값 형태가 같은가", "IncomingMessages Total", "by delivery_path", "time series"),
    ("API와 Diagnostic Settings 값이 같은가", "IncomingMessages Total, NamespaceCpuUsage·cluster CPU Maximum", "by source_path", "time series"),
    ("리소스 로그가 들어오나 (켰을 때와 껐을 때의 차이)", "eventhubs_log_records", "increase[$__range]", "stat"),
    ("Event Hubs가 본 delivery lag는 checkpoint lag와 어떻게 다른가", "ApplicationMetricsLogs ConsumerLag", "max", "time series"),
    ("어떤 data plane 작업이 얼마나 일어났나", "RuntimeAuditLogs Count", "increase by operation", "bars"),
    ("어떤 인증·protocol·network로 접근했나", "RuntimeAuditLogs Count", "increase[$__range] by auth, protocol", "table"),
    ("리소스 로그는 얼마나 늦게 도착하나", "log time → Collector 처리 시각", "max by category", "time series"),
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


def dedicated_capacity_panels(layout: "Layout", panels: list[dict], usage: dict) -> None:
    """Cluster CPU, available memory and utilization for a Dedicated cluster (Role dimension)."""
    panels.append(layout.panel(
        "gauge", "Dedicated CPU", 4, 7,
        [{"expr": f"max(last_over_time(azure_cpu_maximum_Percent{{{DEDICATED}}}[10m]))",
          "instant": True}],
        description="Role 최댓값의 최신 1분 값. 70%·85%에서 색이 바뀝니다.",
        fieldConfig=field("percent", usage, decimals=1, min=0, max=100),
    ))
    panels.append(layout.panel(
        "gauge", "Dedicated available memory", 4, 7,
        [{"expr": f"min(last_over_time(azure_availablememory_maximum_Percent{{{DEDICATED}}}[10m]))",
          "instant": True}],
        description="가용 메모리 비율의 Role 최솟값입니다. 낮을수록 위험하므로 threshold 방향이 CPU와 반대입니다.",
        fieldConfig=field("percent", thresholds(("red", None), ("orange", 15), ("green", 30)),
                          decimals=1, min=0, max=100),
    ))
    panels.append(layout.panel(
        "timeseries", "Dedicated CPU·available memory by role", 16, 7,
        [
            {"expr": f"max by (metadata_role) (azure_cpu_maximum_Percent{{{DEDICATED}}})",
             "legendFormat": "CPU {{metadata_role}}"},
            {"expr": f"min by (metadata_role) (azure_availablememory_maximum_Percent{{{DEDICATED}}})",
             "legendFormat": "available memory {{metadata_role}}"},
            {"expr": f"max(azure_clusterutilization_average_Percent{{{DEDICATED}}})",
             "legendFormat": "cluster utilization"},
        ],
        description="[optional] ClusterUtilization은 preview 지표라 값이 없을 수 있습니다.",
        fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, fillOpacity=5, spanNulls=120000),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))


def build_dashboard(probe: dict) -> dict:
    raw_pu = probe.get("processing_units", 1)
    # Reject 1.5 or True instead of silently truncating them into a different capacity.
    if isinstance(raw_pu, bool) or not isinstance(raw_pu, int) or raw_pu <= 0:
        raise ValueError(f"processing_units must be a positive integer, got {raw_pu!r}")
    pu = raw_pu
    tier = probe.get("tier", "premium")
    if tier not in ("premium", "dedicated"):
        raise ValueError(f"tier must be premium or dedicated, got {tier!r}")
    # Dedicated capacity is counted in CUs on the cluster; Premium in PUs on the namespace.
    unit = "CU" if tier == "dedicated" else "PU"
    layout = Layout()
    panels: list[dict] = []
    green_only = thresholds(("green", None))
    usage = thresholds(("green", None), ("orange", 70), ("red", 85))
    stat_opts = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                 "colorMode": "value", "graphMode": "none", "textMode": "value_and_name"}

    if tier == "dedicated":
        panels.append(layout.row(f"Dedicated cluster 용량 상태 ({pu} CU, Azure Monitor API → remote write)"))
        dedicated_capacity_panels(layout, panels, usage)
    else:
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

    panels.append(layout.row(f"{unit}당 처리량 (capacity = {pu} {unit}, 분당 Total)"))
    for title, metric, value_unit in (
        (f"Messages per {unit} / min", "messages", "short"),
        (f"Bytes per {unit} / min", "bytes", "decbytes"),
    ):
        suffix = "Count" if metric == "messages" else "Bytes"
        panels.append(layout.panel(
            "timeseries", title, 12, 8,
            [
                {"expr": f"sum(azure_incoming{metric}_total_{suffix}{{{API}}}) / $pu", "legendFormat": "incoming"},
                {"expr": f"sum(azure_outgoing{metric}_total_{suffix}{{{API}}}) / $pu", "legendFormat": "outgoing"},
            ],
            interval="1m",
            fieldConfig=field(value_unit, None, decimals=0, drawStyle="bars", fillOpacity=60,
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
        # One delivery path only: both exporters store the same receiver output, so counting
        # without delivery_path would count every series twice.
        [{"expr": f'count(last_over_time({{{DIAG}}}[$__range]))', "instant": True,
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
    incoming_targets = [
        {"expr": f"sum(azure_incomingmessages_total_Count{{{API}}})", "legendFormat": "azure_monitor_api"},
        {"expr": f"sum(incomingmessages_total{{{DIAG}}})", "legendFormat": "diagnostic_eventhub"},
    ]
    incoming_note = ("[optional] Diagnostic Settings 경로는 설정 후 데이터가 흐르기까지 시간이 걸릴 수 있습니다. "
                     "Diagnostic Settings는 dimension을 합친 단일 값으로 내보내므로 EntityName별 API 값의 합과 비교합니다.")
    if tier == "dedicated":
        incoming_targets.append({"expr": f"sum(incomingmessages_total{{{DIAG_CLUSTER}}})",
                                 "legendFormat": "diagnostic_eventhub (cluster)"})
        incoming_note += (" Dedicated에서는 cluster 설정의 같은 지표도 함께 그립니다. lab cluster에는 "
                          "부하 namespace 하나만 있으므로 namespace 값과 같아야 합니다.")
    panels.append(layout.panel(
        "timeseries", "IncomingMessages: API vs Diagnostic Settings", 12, 8,
        incoming_targets,
        description=incoming_note,
        fieldConfig=field("locale", None, lineWidth=2, showPoints="always", pointSize=4) | {"overrides": [{
            "matcher": {"id": "byRegexp", "options": "diagnostic_eventhub.*"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
                           {"id": "custom.lineWidth", "value": 3}]}]},
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    if tier == "dedicated":
        cpu_title, cpu_api, cpu_diag = (
            "Cluster CPU maximum: API vs Diagnostic Settings",
            f"max(azure_cpu_maximum_Percent{{{DEDICATED}}})",
            f"max(cpu_maximum{{{DIAG_CLUSTER}}})",
        )
        cpu_note = ("[optional] 지표표의 DS Export 값은 No지만 cluster Diagnostic Settings 스트림에도 레코드가 "
                    "도착했습니다. API는 Role별 값의 최댓값, Diagnostic Settings는 Role을 합친 maximum입니다.")
    else:
        cpu_title, cpu_api, cpu_diag = (
            "NamespaceCpuUsage maximum: API vs Diagnostic Settings",
            f"max(azure_namespacecpuusage_maximum_Percent{{{API}}})",
            f"max(namespacecpuusage_maximum{{{DIAG}}})",
        )
        cpu_note = ("[optional] 지표표의 DS Export 값은 No지만 이 실습에서는 Diagnostic Settings 스트림에도 "
                    "레코드가 도착했습니다. 두 경로를 겹쳐 그 차이를 확인합니다.")
    panels.append(layout.panel(
        "timeseries", cpu_title, 12, 8,
        [
            {"expr": cpu_api, "legendFormat": "azure_monitor_api"},
            {"expr": cpu_diag, "legendFormat": "diagnostic_eventhub"},
        ],
        description=cpu_note,
        fieldConfig=field("percent", None, decimals=1, min=0, lineWidth=2, showPoints="always", pointSize=4) | {"overrides": [{
            "matcher": {"id": "byName", "options": "diagnostic_eventhub"},
            "properties": [{"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [8, 6]}},
                           {"id": "custom.lineWidth", "value": 3}]}]},
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))

    panels.append(layout.row("Event Hubs 리소스 로그 → 지표 (ApplicationMetricsLogs·RuntimeAuditLogs, EVENTHUBS_LOGS=Enabled)"))
    off_note = (f"[optional] EVENTHUBS_LOGS=Disabled이거나 Diagnostic Settings 로그가 아직 도착하지 않으면 '{LOGS_OFF}'로 "
                "표시됩니다. 로그를 지표로 바꾼 값은 Collector가 처리한 시각으로 기록됩니다.")
    panels.append(layout.panel(
        "stat", "Resource log records", 4, 8,
        [{"expr": f"sum(increase(eventhubs_log_records_total{{{LOGS}}}[$__range]))", "instant": True,
          "legendFormat": "records"}],
        description=off_note + " 조회 구간에 받은 ApplicationMetricsLogs·RuntimeAuditLogs 레코드 수입니다.",
        fieldConfig={"defaults": {"unit": "locale", "decimals": 0, "noValue": LOGS_OFF,
                                  "color": {"mode": "fixed", "fixedColor": "text"}}, "overrides": []},
        options=stat_opts | {"textMode": "value"},
    ))
    panels.append(layout.panel(
        "timeseries", "Consumer lag: checkpoint vs ApplicationMetricsLogs", 10, 8,
        [
            {"expr": f"max(eventhubs_consumer_lag_messages{{{LAG}}})", "legendFormat": "checkpoint lag (lag exporter)"},
            {"expr": f"max(eventhubs_log_consumer_lag{{{LOGS}}})", "legendFormat": "ConsumerLag log (delivery lag)"},
        ],
        description=off_note + (" checkpoint lag는 마지막 enqueue sequence − 저장된 checkpoint, ConsumerLag 로그는 "
                                "AMQP receiver에 마지막으로 전달한 sequence와의 차이입니다. 받을 event가 없으면 로그가 없습니다."),
        fieldConfig=field("locale", None, min=0, lineWidth=2, showPoints="always", pointSize=3, no_value=LOGS_OFF),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    panels.append(layout.panel(
        "timeseries", "Runtime audit operations / min", 10, 8,
        [{"expr": f"sum by (azure_operation_name) (increase(eventhubs_log_runtime_operations_total{{{LOGS}}}[1m]))",
          "legendFormat": "{{azure_operation_name}}"}],
        description=off_note + " RuntimeAuditLogs의 1분 집계 Count를 작업별로 더한 값입니다.",
        fieldConfig=field("locale", None, decimals=0, drawStyle="bars", fillOpacity=60, stacking={"mode": "normal"},
                          no_value=LOGS_OFF),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    panels.append(layout.panel(
        "table", "Data plane access by auth · protocol · network", 9, 8,
        [{"expr": ("sum by (azure_operation_name, azure_auth_type, network_protocol_name, network_connection_type, "
                   f"error_type) (increase(eventhubs_log_runtime_operations_total{{{LOGS}}}[$__range]))"),
          "instant": True, "format": "table"}],
        description=off_note + " client IP와 인증 ID는 label로 만들지 않습니다.",
        transformations=[{"id": "organize", "options": {
            "excludeByName": {"Time": True},
            "renameByName": {"azure_operation_name": "Operation", "azure_auth_type": "Auth",
                             "network_protocol_name": "Protocol", "network_connection_type": "Network",
                             "error_type": "Error", "Value": "Count"}}}],
        fieldConfig={"defaults": {"unit": "locale", "decimals": 0, "noValue": LOGS_OFF}, "overrides": []},
    ))
    panels.append(layout.panel(
        "timeseries", "ApplicationMetricsLogs count / min", 8, 8,
        [{"expr": f"sum by (azure_operation_name) (increase(eventhubs_log_application_count_total{{{LOGS}}}[1m]))",
          "legendFormat": "{{azure_operation_name}}"}],
        description=off_note + " ConsumerLag를 뺀 작업별 Count입니다. 단위는 작업마다 다릅니다(message, byte, 호출 수).",
        fieldConfig=field("short", None, decimals=0, lineWidth=1, no_value=LOGS_OFF),
        options={"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
    ))
    panels.append(layout.panel(
        "timeseries", "Resource log arrival delay", 7, 8,
        [{"expr": f"max by (azure_category) (eventhubs_log_arrival_delay_seconds{{{LOGS}}})",
          "legendFormat": "{{azure_category}}"}],
        description=off_note + " 레코드 시각부터 Collector가 처리할 때까지의 초입니다.",
        fieldConfig=field("s", None, decimals=0, min=0, lineWidth=2, showPoints="always", pointSize=3, no_value=LOGS_OFF),
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

    if probe.get("dedicated_enabled") and tier != "dedicated":
        # A Premium lab that also observes an existing cluster shows it in its own row.
        panels.append(layout.row("기존 Dedicated cluster (EXISTING_DEDICATED_CLUSTER_RESOURCE_ID)"))
        dedicated_capacity_panels(layout, panels, usage)

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
             "label": f"capacity units ({unit})"},
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
    parser.add_argument("--processing-units", type=positive_int, default=1,
                        help="Premium PUs or Dedicated CUs of the workload")
    parser.add_argument("--tier", choices=("premium", "dedicated"), default="premium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe = json.loads(args.probe.read_text())
    probe.setdefault("processing_units", args.processing_units)
    probe.setdefault("dedicated_enabled", any(
        name.startswith(("azure_cpu_", "azure_availablememory_")) for name in probe.get("metrics", {})))
    probe.setdefault("tier", args.tier)
    dashboard = build_dashboard(probe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False))
    print(f"{len(dashboard['panels'])} panels -> {args.output}")


if __name__ == "__main__":
    main()
