"""Builds the MovieLog Grafana dashboard from the decisions recorded by the probe queries.

Every panel states which aggregation the probe justified:
- counters (value = increment per 60 s step)       -> sum(value)
- DistributionSummary (valueSum + valueCount)      -> sum(valueSum) / sum(valueCount)
- DB-wide gauges (same value on every Pod)         -> max(value) across instances, never sum

The visualization follows the question each panel answers, not a default line chart:
- "how many in this range"            -> stat with a sparkline of the same bins
- "is this value healthy"             -> gauge with thresholds that carry domain meaning
- "what share does each part have"    -> pie (donut) or bar gauge
- "how does it move over time"        -> time series (stacked area, bars or line)
- "is any Pod missing a metric"       -> status history

Usage:
  python3 grafana/build_dashboard.py > grafana/movielog-dashboard.json
  python3 grafana/build_dashboard.py --appinsights-id <resource-id> > /tmp/live.json   # default for a live push
"""
import argparse
import json

DS = {"type": "grafana-azure-monitor-datasource", "uid": "${datasource}"}
STEP = "max_of($__interval, 1m)"
PER_MIN = f"({STEP} / 1m)"
# The current bin is still filling. Every panel drops it, so time series do not dip at the right edge
# and totals in stats, gauges, pies and bar gauges agree with each other.
COMPLETE = f"| where timestamp < bin(now(), {STEP})\n"
# Reviews at or above 3.5 stars count as fresh, so the rating gauge turns green at the same line.
RATING_STEPS = [{"color": "red", "value": None}, {"color": "orange", "value": 2.5},
                {"color": "green", "value": 3.5}]
BLUE = {"mode": "fixed", "fixedColor": "blue"}
# Meters BusinessMetrics exports from startup in every interval: the counters it pre-registers at 0 and the
# DB gauges. Lazily created counters and the rating distribution can be legitimately absent, so they stay out.
STEADY_METRICS = [
    "movielog_movie_views", "movielog_review_views", "movielog_reviews_posted", "movielog_reviews_deleted",
    "movielog_comments_posted", "movielog_comments_deleted", "movielog_members_signups",
    "movielog_movies_stored", "movielog_reviews_stored", "movielog_comments_stored", "movielog_members_stored",
]


def base(metric):
    return (
        "customMetrics\n"
        "| where $__timeFilter(timestamp)\n"
        "| where cloud_RoleName == ${role:singlequote}\n"
        f'| where name == "{metric}"\n'
    )


def names(*metrics):
    quoted = ", ".join(f'"{m}"' for m in metrics)
    return (
        "customMetrics\n"
        "| where $__timeFilter(timestamp)\n"
        "| where cloud_RoleName == ${role:singlequote}\n"
        f"| where name in ({quoted})\n"
    )


def per_bin(expr, by=""):
    by = f", {by}" if by else ""
    return COMPLETE + f"| summarize {expr} by bin(timestamp, {STEP}){by}\n| order by timestamp asc"


def target(query, fmt, ref="A"):
    return {
        "refId": ref,
        "datasource": DS,
        "queryType": "Azure Log Analytics",
        "azureLogAnalytics": {"query": query, "resources": ["$appinsights"], "resultFormat": fmt},
    }


def thresholds(steps):
    return {"mode": "absolute", "steps": steps}


class Layout:
    def __init__(self):
        self.next_id = 1
        self.y = 0
        self.panels = []

    def row(self, title):
        self.panels.append({"id": self._id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def add(self, kind, title, desc, query, x, w, h, fmt, unit="short", defaults=None, options=None, label=None):
        field_defaults = {"unit": unit, **(defaults or {})}
        if label:
            # Legend shows the dimension value instead of "<column> <value>".
            field_defaults["displayName"] = "${__field.labels.%s}" % label
        panel = {
            "id": self._id(),
            "type": kind,
            "title": title,
            "description": desc,
            "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": x, "y": self.y},
            "targets": [target(query, fmt)],
            "fieldConfig": {"defaults": field_defaults, "overrides": []},
            "options": options or {},
        }
        self.panels.append(panel)
        return panel

    def newline(self, h):
        self.y += h

    def _id(self):
        self.next_id += 1
        return self.next_id - 1


def reduce(calc, values=False):
    return {"calcs": [calc], "fields": "", "values": values}


def stat(calc, sparkline=True):
    return {"reduceOptions": reduce(calc), "colorMode": "value", "graphMode": "area" if sparkline else "none",
            "textMode": "value", "justifyMode": "center", "orientation": "auto"}


def bar_gauge():
    # One bar per row of a table result; the string column names the bar.
    # Names above fixed-height bars (the height includes the name): long Pod names are not truncated
    # and panels with few rows do not blow up.
    return {"reduceOptions": reduce("lastNotNull", values=True), "orientation": "horizontal",
            "displayMode": "gradient", "valueMode": "color", "showUnfilled": True,
            "namePlacement": "top", "sizing": "manual", "minVizHeight": 32, "maxVizHeight": 32,
            "text": {"titleSize": 12, "valueSize": 14}}


LEGEND = {"displayMode": "list", "placement": "bottom"}
LINES = {"legend": LEGEND, "tooltip": {"mode": "multi"}}
AREA = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 35, "stacking": {"mode": "normal", "group": "A"}}
BARS = {"drawStyle": "bars", "fillOpacity": 70, "stacking": {"mode": "normal", "group": "A"},
        "lineWidth": 1}


def build(appinsights_id):
    lay = Layout()

    lay.row("핵심 지표 (선택 구간 합계와 평균)")
    for x, metric, title, desc in [
        (0, "movielog_movie_views", "영화 조회", "movielog_movie_views 증가량 합계. 웹 상세 화면과 API 조회를 모두 셉니다."),
        (5, "movielog_reviews_posted", "새 리뷰", "movielog_reviews_posted 증가량 합계. 커밋된 리뷰만 집계됩니다."),
        (10, "movielog_members_signups", "신규 회원", "movielog_members_signups 증가량 합계."),
    ]:
        lay.add("stat", title, desc + " 배경 곡선은 같은 값의 bin별 추이입니다.",
                base(metric) + per_bin("total = sum(value)"), x, 5, 6, "time_series",
                defaults={"color": BLUE}, options=stat("sum"))
    lay.add("gauge", "평균 별점",
            "DistributionSummary라 sum(valueSum) / sum(valueCount)로 계산합니다. fresh 기준인 3.5개부터 초록색입니다.",
            base("movielog_review_rating") + COMPLETE + "| summarize stars = sum(valueSum) / sum(valueCount)",
            15, 4, 6, "table", unit="none",
            defaults={"decimals": 2, "min": 0, "max": 5, "thresholds": thresholds(RATING_STEPS),
                      "color": {"mode": "thresholds"}},
            options={"reduceOptions": reduce("lastNotNull"), "showThresholdMarkers": True,
                     "showThresholdLabels": False, "orientation": "auto"})
    lay.add("piechart", "리뷰 판정 비율", "verdict=fresh(별 3.5개 이상)와 rotten 리뷰 수의 비율입니다.",
            base("movielog_reviews_posted")
            + "| extend verdict = tostring(customDimensions.verdict)\n"
              + COMPLETE + "| summarize reviews = sum(value) by verdict\n"
              "| order by verdict asc",
            19, 5, 6, "table",
            defaults={"color": {"mode": "palette-classic"}},
            options={"reduceOptions": reduce("lastNotNull", values=True), "pieType": "donut",
                     "displayLabels": ["percent"], "legend": {**LEGEND, "values": ["value"]},
                     "tooltip": {"mode": "single"}})
    lay.newline(6)

    lay.add("timeseries", "분당 영화 조회 (채널별 누적)", "bin마다 증가량을 더한 뒤 분당 값으로 환산하고 채널을 쌓아 전체 처리량을 함께 봅니다.",
            base("movielog_movie_views")
            + "| extend channel = tostring(customDimensions.channel)\n"
              + per_bin(f"perMin = sum(value) / {PER_MIN}", "channel"),
            0, 12, 8, "time_series", defaults={"custom": AREA}, options=LINES, label="channel")
    lay.add("timeseries", "분당 새 리뷰 (fresh / rotten)", "verdict dimension으로 나눈 리뷰 작성량입니다.",
            base("movielog_reviews_posted")
            + "| extend verdict = tostring(customDimensions.verdict)\n"
              + per_bin(f"perMin = sum(value) / {PER_MIN}", "verdict"),
            12, 12, 8, "time_series", defaults={"custom": BARS}, options=LINES, label="verdict")
    lay.newline(8)

    lay.add("bargauge", "활동별·채널별 합계", "Counter 네 개의 구간 합계를 활동과 채널로 나눠 어느 경로가 많은지 비교합니다.",
            names("movielog_movie_views", "movielog_review_views", "movielog_reviews_posted",
                  "movielog_comments_posted")
            + '| extend activity = case(name == "movielog_movie_views", "영화 조회",\n'
              '                         name == "movielog_review_views", "리뷰 조회",\n'
              '                         name == "movielog_reviews_posted", "리뷰 작성", "댓글")\n'
              '| extend series = strcat(activity, " · ", tostring(customDimensions.channel))\n'
              + COMPLETE + "| summarize total = sum(value) by series\n"
              "| order by total desc",
            0, 9, 11, "table", defaults={"color": {"mode": "continuous-BlPu"}, "min": 0}, options=bar_gauge())
    lay.add("timeseries", "평균 별점 추이", "bin마다 sum(valueSum) / sum(valueCount)로 가중 평균을 계산합니다. 배경색은 평균 별점 gauge와 같은 기준입니다.",
            base("movielog_review_rating") + per_bin("stars = sum(valueSum) / sum(valueCount)"),
            9, 15, 11, "time_series", unit="none",
            defaults={"decimals": 2, "min": 0, "max": 5, "displayName": "평균 별점",
                      "color": {"mode": "fixed", "fixedColor": "text"},
                      "thresholds": thresholds(RATING_STEPS),
                      "custom": {"lineWidth": 2, "thresholdsStyle": {"mode": "area"}}},
            options=LINES)
    lay.newline(11)

    lay.row("누적 현황 (Gauge: DB 기준이라 Pod 간 max)")
    for x, metric, title in [
        (0, "movielog_movies_stored", "카탈로그 영화"),
        (6, "movielog_reviews_stored", "저장된 리뷰"),
        (12, "movielog_comments_stored", "저장된 댓글"),
        (18, "movielog_members_stored", "가입 회원"),
    ]:
        lay.add("stat", title,
                f"{metric}. 모든 Pod가 같은 DB 값을 보고하므로 bin마다 max(value)를 씁니다. sum을 쓰면 Pod 수배로 부풀려집니다.",
                base(metric) + per_bin("stored = max(value)"), x, 6, 5, "time_series",
                defaults={"color": {"mode": "fixed", "fixedColor": "purple"}}, options=stat("lastNotNull"))
    lay.newline(5)

    lay.row("운영 (Pod 분포와 수신 상태)")
    lay.add("bargauge", "Pod별 영화 조회 분포", "cloud_RoleInstance별 구간 합계로 트래픽이 한 Pod에 몰리는지 봅니다.",
            base("movielog_movie_views")
            + COMPLETE + "| summarize total = sum(value) by cloud_RoleInstance\n"
              "| order by cloud_RoleInstance asc",
            0, 12, 5, "table", defaults={"color": {"mode": "continuous-BlPu"}, "min": 0}, options=bar_gauge())
    lay.add("bargauge", "외부 조회 결과 (outcome별)",
            "카탈로그 조회와 검색의 outcome별 구간 합계입니다. TMDB 키 없이 seed 데이터만 쓰면 cache_hit와 disabled만 나타납니다.",
            names("movielog_movie_catalog_lookups", "movielog_movie_searches")
            + '| extend series = strcat(iff(name == "movielog_movie_searches", "검색", "카탈로그"), " · ",\n'
              "                         tostring(customDimensions.outcome))\n"
              + COMPLETE + "| summarize total = sum(value) by series\n"
              "| order by total desc",
            12, 12, 5, "table", defaults={"color": {"mode": "continuous-BlPu"}, "min": 0}, options=bar_gauge())
    lay.newline(5)
    lay.add("status-history", "Pod별 누락 metric 수",
            "bin마다 Pod가 보내지 않은 상시 meter 수입니다. 기대 목록은 앱이 시작 때 0으로 등록하는 Counter와 DB "
            "Gauge 11개로 고정하며, 처음 사용할 때 생기는 Counter와 기록이 없으면 행이 없는 DistributionSummary는 뺍니다. "
            "0이면 초록, 1 이상이면 빨강입니다. 칸이 비어 있으면 그 Pod가 그 bin에 아무 지표도 보내지 않은 것입니다"
            "(교체된 Pod도 종료 뒤 빈 칸).",
            "let steady = dynamic([" + ", ".join(f'"{m}"' for m in STEADY_METRICS) + "]);\n"
            "customMetrics\n"
            "| where $__timeFilter(timestamp)\n"
            "| where cloud_RoleName == ${role:singlequote}\n"
            "| where name in (steady)\n"
            + COMPLETE + f"| summarize got = dcount(name) by bin(timestamp, {STEP}), cloud_RoleInstance\n"
            "| project timestamp, cloud_RoleInstance, absent = array_length(steady) - got\n"
            "| order by timestamp asc",
            0, 24, 6, "time_series",
            defaults={"color": {"mode": "thresholds"}, "min": 0,
                      "thresholds": thresholds([{"color": "green", "value": None}, {"color": "red", "value": 1}])},
            options={"showValue": "auto", "rowHeight": 0.8, "colWidth": 0.9, "legend": {**LEGEND, "showLegend": False},
                     "tooltip": {"mode": "single"}},
            label="cloud_RoleInstance")
    lay.newline(6)
    lay.add("table", "metric 수신 상태 (구간 끝 10분)",
            "선택 구간 끝 10분 동안 Pod별로 metric이 1분에 한 행씩 오는지와 구간 끝 기준 마지막 수신 후 경과 초를 봅니다. "
            "구간 끝이 지금이면 현재 수신 상태입니다. 행이 멈추면 agent나 allowlist를 확인합니다.",
            "customMetrics\n"
            "| where timestamp > $__timeTo() - 10m and timestamp <= $__timeTo()\n"
            "| where cloud_RoleName == ${role:singlequote}\n"
            '| where name startswith "movielog_"\n'
            "| summarize rows = count(), lastSeen = max(timestamp) by name, cloud_RoleInstance\n"
            "| extend secondsAgo = datetime_diff('second', $__timeTo(), lastSeen)\n"
            "| project name, cloud_RoleInstance, rows, secondsAgo\n"
            "| order by name asc, cloud_RoleInstance asc",
            0, 24, 9, "table", options={"showHeader": True, "cellHeight": "sm"})
    lay.newline(9)

    return {
        "title": "MovieLog 비즈니스 지표 (Micrometer → Application Insights)",
        "uid": "movielog-business-metrics",
        "tags": ["spring-boot", "micrometer", "application-insights", "movielog"],
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "refresh": "1m",
        "time": {"from": "now-1h", "to": "now"},
        "schemaVersion": 39,
        "templating": {"list": [
            {"name": "datasource", "label": "Azure Monitor", "type": "datasource",
             "query": "grafana-azure-monitor-datasource", "current": {}, "hide": 0},
            {"name": "appinsights", "label": "Application Insights resource ID", "type": "textbox",
             "query": appinsights_id, "current": {"text": appinsights_id, "value": appinsights_id},
             # Pre-filled builds hide it: the resource ID contains the subscription ID.
             "hide": 2 if appinsights_id else 0},
            {"name": "role", "label": "cloud_RoleName", "type": "textbox",
             "query": "movielog", "current": {"text": "movielog", "value": "movielog"}, "hide": 0},
        ]},
        "panels": lay.panels,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--appinsights-id", default="",
                        help="Application Insights resource ID used as the textbox default")
    args = parser.parse_args()
    print(json.dumps(build(args.appinsights_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
