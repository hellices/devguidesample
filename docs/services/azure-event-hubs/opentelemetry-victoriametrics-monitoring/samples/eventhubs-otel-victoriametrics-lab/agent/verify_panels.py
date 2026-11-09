"""Execute every Grafana panel query through /api/ds/query and fail on unusable panels.

A panel fails when any target returns an HTTP/query error, no frame rows, or no finite
value. Text panels are skipped. Panels whose description starts with "[optional]" are
reported but never fail the run.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def grafana_request(url: str, user: str, password: str, path: str, body: dict | None = None) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Basic {token}", "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def iter_panels(panels: list[dict]):
    for panel in panels:
        if panel.get("type") == "row":
            yield from iter_panels(panel.get("panels", []))
        else:
            yield panel


def inspect_frames(result: dict) -> tuple[int, int, int | None]:
    rows = finite = 0
    newest = None
    for frame in result.get("frames", []):
        values = frame.get("data", {}).get("values", [])
        if not values:
            continue
        rows += len(values[0])
        for column_index, column in enumerate(values):
            for value in column:
                if column_index == 0 and isinstance(value, (int, float)):
                    newest = max(newest or value, value)
                elif isinstance(value, (int, float)) and math.isfinite(value):
                    finite += 1
    return rows, finite, newest


def verify(url: str, user: str, password: str, uid: str, time_from: str, time_to: str) -> list[dict]:
    dashboard = grafana_request(url, user, password, f"/api/dashboards/uid/{uid}")["dashboard"]
    variables = {
        item["name"]: item.get("current", {}).get("value") or item.get("query")
        for item in dashboard.get("templating", {}).get("list", [])
    }
    report = []
    for panel in iter_panels(dashboard.get("panels", [])):
        if panel.get("type") == "text":
            continue
        optional = str(panel.get("description", "")).startswith("[optional]")
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            for name, value in variables.items():
                expr = expr.replace(f"${name}", str(value)).replace(f"${{{name}}}", str(value))
            query = {
                "refId": target.get("refId", "A"),
                "datasource": {"type": "prometheus", "uid": "victoriametrics"},
                "expr": expr,
                "instant": target.get("instant", False),
                "range": not target.get("instant", False),
                "intervalMs": 60000,
                "maxDataPoints": 500,
            }
            entry = {"panel": panel["title"], "refId": query["refId"], "optional": optional, "expr": expr}
            try:
                body = grafana_request(
                    url, user, password, "/api/ds/query",
                    {"queries": [query], "from": time_from, "to": time_to},
                )
                result = body["results"][query["refId"]]
                if result.get("error"):
                    entry.update(status="error", error=result["error"])
                else:
                    rows, finite, newest = inspect_frames(result)
                    entry.update(rows=rows, finite_values=finite, newest_ms=newest)
                    entry["status"] = "pass" if rows and finite else "empty"
            except urllib.error.HTTPError as error:
                entry.update(status="error", error=f"HTTP {error.code}: {error.read()[:300]!r}")
            report.append(entry)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uid", default="eventhubs-otel-victoriametrics")
    parser.add_argument("--from", dest="time_from", required=True, help="epoch ms or Grafana relative time")
    parser.add_argument("--to", dest="time_to", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(
        os.environ["GRAFANA_URL"].rstrip("/"),
        os.environ.get("GRAFANA_USER", "admin"),
        os.environ["GRAFANA_PASSWORD"],
        args.uid,
        args.time_from,
        args.time_to,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    failed = [r for r in report if r["status"] != "pass" and not r["optional"]]
    for row in report:
        mark = "PASS" if row["status"] == "pass" else ("WARN" if row["optional"] else "FAIL")
        print(f"{mark} {row['panel']} [{row['refId']}] rows={row.get('rows')} finite={row.get('finite_values')} {row.get('error', '')}")
    print(f"{len(report) - len(failed)}/{len(report)} queries usable")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
