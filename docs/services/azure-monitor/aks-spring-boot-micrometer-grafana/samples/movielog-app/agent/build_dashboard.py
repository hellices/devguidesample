"""Builds the MovieLog Grafana dashboard from the decisions recorded by the probe queries.

Every panel states which aggregation the probe justified:
- counters (value = increment per 60 s step)       -> sum(value)
- DistributionSummary (valueSum + valueCount)      -> sum(valueSum) / sum(valueCount)
- DB-wide gauges (same value on every Pod)         -> max(value) across instances, never sum

Usage:
  python build_dashboard.py > ../grafana/movielog-dashboard.json
  python build_dashboard.py --appinsights-id <resource-id> > /tmp/live.json   # default for a live push
"""
import argparse
import json

DS = {"type": "grafana-azure-monitor-datasource", "uid": "${datasource}"}
STEP = "max_of($__interval, 1m)"
PER_MIN = f"({STEP} / 1m)"


def base(metric):
    return (
        "customMetrics\n"
        "| where $__timeFilter(timestamp)\n"
        '| where cloud_RoleName == "$role"\n'
        f'| where name == "{metric}"\n'
    )


def target(query, fmt, ref="A"):
    return {
        "refId": ref,
        "datasource": DS,
        "queryType": "Azure Log Analytics",
        "azureLogAnalytics": {"query": query, "resources": ["$appinsights"], "resultFormat": fmt},
    }


class Layout:
    def __init__(self):
        self.next_id = 1
        self.y = 0
        self.panels = []

    def row(self, title):
        self.panels.append({"id": self._id(), "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def add(self, kind, title, desc, query, unit, x, w, h, fmt, defaults=None, options=None, label=None):
        field_defaults = {"unit": unit, **(defaults or {})}
        if kind == "stat":
            field_defaults["color"] = {"mode": "fixed", "fixedColor": "blue"}
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


STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "colorMode": "value", "graphMode": "none", "textMode": "auto", "justifyMode": "center"}
LINES = {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}}
BARS = {"drawStyle": "bars", "fillOpacity": 70, "stacking": {"mode": "normal", "group": "A"},
        "lineWidth": 1}


def build(appinsights_id):
    lay = Layout()

    lay.row("사용자 행동 (Counter: 구간 증가량 합계)")
    lay.add("stat", "영화 조회", "movielog_movie_views 증가량 합계. 웹 상세 화면과 API 조회를 모두 셉니다.",
            base("movielog_movie_views") + "| summarize movieViews = sum(value)", "short", 0, 5, 4, "table", options=STAT)
    lay.add("stat", "새 리뷰", "movielog_reviews_posted 증가량 합계. 커밋된 리뷰만 집계됩니다.",
            base("movielog_reviews_posted") + "| summarize reviews = sum(value)", "short", 5, 5, 4, "table",
            options=STAT)
    lay.add("stat", "신규 회원", "movielog_members_signups 증가량 합계.",
            base("movielog_members_signups") + "| summarize signups = sum(value)", "short", 10, 4, 4, "table",
            options=STAT)
    lay.add("stat", "평균 별점", "DistributionSummary라 sum(valueSum) / sum(valueCount)로 계산합니다. 행 평균을 쓰면 왜곡됩니다.",
            base("movielog_review_rating") + "| summarize stars = sum(valueSum) / sum(valueCount)",
            "none", 14, 5, 4, "table", defaults={"decimals": 2, "min": 0, "max": 5}, options=STAT)
    lay.add("stat", "Fresh 비율", "verdict=fresh(별 3.5개 이상) 리뷰 비율입니다.",
            base("movielog_reviews_posted")
            + '| extend verdict = tostring(customDimensions.verdict)\n'
              '| summarize fresh = sumif(value, verdict == "fresh"), total = sum(value)\n'
              "| project freshRatio = iff(total == 0, 0.0, 100.0 * fresh / total)",
            "percent", 19, 5, 4, "table", options=STAT)
    lay.newline(4)

    lay.add("timeseries", "분당 영화 조회 (채널별)", "bin마다 증가량을 더한 뒤 분당 값으로 환산합니다.",
            base("movielog_movie_views")
            + "| extend channel = tostring(customDimensions.channel)\n"
              f"| summarize perMin = sum(value) / {PER_MIN} by bin(timestamp, {STEP}), channel\n"
              "| order by timestamp asc",
            "short", 0, 12, 8, "time_series", options=LINES, label="channel")
    lay.add("timeseries", "분당 새 리뷰 (fresh / rotten)", "verdict dimension으로 나눈 리뷰 작성량입니다.",
            base("movielog_reviews_posted")
            + "| extend verdict = tostring(customDimensions.verdict)\n"
              f"| summarize perMin = sum(value) / {PER_MIN} by bin(timestamp, {STEP}), verdict\n"
              "| order by timestamp asc",
            "short", 12, 12, 8, "time_series", defaults={"custom": BARS}, options=LINES, label="verdict")
    lay.newline(8)

    lay.add("timeseries", "분당 리뷰 조회·댓글 (채널별)", "두 counter를 한 panel에 그리고 metric·channel을 series 이름으로 씁니다.",
            "customMetrics\n"
            "| where $__timeFilter(timestamp)\n"
            '| where cloud_RoleName == "$role"\n'
            '| where name in ("movielog_review_views", "movielog_comments_posted")\n'
            '| extend series = strcat(iff(name == "movielog_review_views", "리뷰 조회", "댓글"), " · ",\n'
            "                         tostring(customDimensions.channel))\n"
            f"| summarize perMin = sum(value) / {PER_MIN} by bin(timestamp, {STEP}), series\n"
            "| order by timestamp asc",
            "short", 0, 12, 8, "time_series", options=LINES, label="series")
    lay.add("timeseries", "평균 별점 추이", "bin마다 sum(valueSum) / sum(valueCount)로 가중 평균을 계산합니다.",
            base("movielog_review_rating")
            + f"| summarize stars = sum(valueSum) / sum(valueCount) by bin(timestamp, {STEP})\n"
              "| order by timestamp asc",
            "none", 12, 12, 8, "time_series", defaults={"decimals": 2, "min": 0, "max": 5, "displayName": "평균 별점"},
            options=LINES)
    lay.newline(8)

    lay.row("누적 현황 (Gauge: DB 기준이라 Pod 간 max)")
    lay.add("stat", "카탈로그 영화 수", "movielog_movies_stored. 모든 Pod가 같은 DB 값을 보고하므로 합산하지 않습니다.",
            base("movielog_movies_stored") + "| summarize arg_max(timestamp, value) | project movies = value",
            "short", 0, 4, 8, "table", options=STAT)
    lay.add("timeseries", "저장된 리뷰·댓글·회원 수",
            "Pod 수만큼 같은 값이 들어오므로 bin마다 max(value)를 씁니다. sum을 쓰면 Pod 수배로 부풀려집니다.",
            "customMetrics\n"
            "| where $__timeFilter(timestamp)\n"
            '| where cloud_RoleName == "$role"\n'
            '| where name in ("movielog_reviews_stored", "movielog_comments_stored", "movielog_members_stored")\n'
            '| extend series = case(name == "movielog_reviews_stored", "리뷰",\n'
            '                       name == "movielog_comments_stored", "댓글", "회원")\n'
            f"| summarize stored = max(value) by bin(timestamp, {STEP}), series\n"
            "| order by timestamp asc",
            "short", 4, 20, 8, "time_series", options=LINES, label="series")
    lay.newline(8)

    lay.row("운영 (Pod 분포와 수신 상태)")
    lay.add("timeseries", "Pod별 분당 영화 조회", "cloud_RoleInstance로 나눠 트래픽이 한 Pod에 몰리는지 봅니다.",
            base("movielog_movie_views")
            + f"| summarize perMin = sum(value) / {PER_MIN} by bin(timestamp, {STEP}), cloud_RoleInstance\n"
              "| order by timestamp asc",
            "short", 0, 12, 8, "time_series", options=LINES, label="cloud_RoleInstance")
    lay.add("timeseries", "분당 카탈로그 조회 (출처별)", "TMDB 키 없이 seed 데이터만 쓰면 cache_hit만 나타납니다.",
            base("movielog_movie_catalog_lookups")
            + "| extend outcome = tostring(customDimensions.outcome)\n"
              f"| summarize perMin = sum(value) / {PER_MIN} by bin(timestamp, {STEP}), outcome\n"
              "| order by timestamp asc",
            "short", 12, 12, 8, "time_series", options=LINES, label="outcome")
    lay.newline(8)
    lay.add("table", "metric 수신 상태 (최근 10분)",
            "Pod별로 metric이 1분에 한 행씩 오는지와 마지막 수신 시각을 봅니다. 행이 멈추면 agent나 allowlist를 확인합니다.",
            "customMetrics\n"
            "| where timestamp > ago(10m)\n"
            '| where cloud_RoleName == "$role"\n'
            '| where name startswith "movielog_"\n'
            "| summarize rows = count(), lastSeen = max(timestamp) by name, cloud_RoleInstance\n"
            "| extend secondsAgo = datetime_diff('second', now(), lastSeen)\n"
            "| project name, cloud_RoleInstance, rows, secondsAgo\n"
            "| order by name asc, cloud_RoleInstance asc",
            "short", 0, 24, 9, "table", options={"showHeader": True, "cellHeight": "sm"})
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
