"""Execute every Grafana panel query through /api/ds/query and fail on unusable panels.

A panel fails when any target returns an HTTP/query error, no frame rows, or no finite
value. Text panels are skipped. Panels whose description starts with "[optional]" are
reported but never fail the run.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import math
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _tls_context() -> ssl.SSLContext | None:
    # GRAFANA_CA_FILE pins the gateway's self-signed certificate; hostname (IP SAN) checks stay on.
    ca_file = os.environ.get("GRAFANA_CA_FILE")
    return ssl.create_default_context(cafile=ca_file) if ca_file else None


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    # urllib would replay the Authorization header to the redirect target; Grafana's API never
    # needs a redirect, so treat one as an error instead of following it.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refusing redirect to {newurl}", headers, fp)


def grafana_request(url: str, user: str, password: str, path: str, body: dict | None = None) -> dict:
    if not url.startswith("https://") and os.environ.get("GRAFANA_ALLOW_HTTP") != "1":
        raise SystemExit("refusing to send Grafana credentials over plain HTTP")
    # Azure Managed Grafana takes a Microsoft Entra access token (audience https://dashboard.azure.com);
    # the Gateway Grafana takes the admin password.
    bearer = os.environ.get("GRAFANA_TOKEN")
    if bearer:
        authorization = f"Bearer {bearer}"
    else:
        authorization = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": authorization, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_tls_context()), _RefuseRedirect)
    with opener.open(request, timeout=60) as response:
        return json.load(response)


def iter_panels(panels: list[dict]):
    for panel in panels:
        if panel.get("type") == "row":
            yield from iter_panels(panel.get("panels", []))
        else:
            yield panel


def inspect_frames(result: dict) -> tuple[int, int, int | None, float]:
    rows = finite = 0
    total = 0.0
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
                    total += value
    return rows, finite, newest, total


PROMETHEUS = {"type": "prometheus", "uid": "victoriametrics"}
VARIABLE = re.compile(r"\$\{(\w+)\}|\$(\w+)")


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
            # Grafana does not run a hidden target, so neither does the verification.
            if target.get("hide"):
                continue
            datasource = target.get("datasource") or panel.get("datasource") or PROMETHEUS
            if datasource.get("type", "prometheus") == "prometheus":
                # One pass over whole $name / ${name} tokens, so $cluster never rewrites $cluster_name.
                expr = VARIABLE.sub(
                    lambda match: str(variables.get(match.group(1) or match.group(2), match.group(0))),
                    target.get("expr", ""),
                )
                instant = bool(target.get("instant", False))
                query = {
                    "refId": target.get("refId", "A"),
                    "datasource": datasource,
                    "expr": expr,
                    # Keep both flags as configured: a "Both" target runs an instant and a range query.
                    "instant": instant,
                    "range": bool(target.get("range", not instant)),
                    "intervalMs": 60000,
                    "maxDataPoints": 500,
                }
                entry = {"panel": panel["title"], "refId": query["refId"], "optional": optional, "expr": expr}
            else:
                # Other data sources (Azure Monitor) take the panel target model as is.
                query = {**target, "refId": target.get("refId", "A"), "datasource": datasource,
                         "intervalMs": 60000, "maxDataPoints": 500}
                metric = target.get("azureMonitor", {})
                entry = {"panel": panel["title"], "refId": query["refId"], "optional": optional,
                         "datasource": datasource.get("type"), "metric": metric.get("metricName"),
                         "aggregation": metric.get("aggregation")}
            try:
                body = grafana_request(
                    url, user, password, "/api/ds/query",
                    {"queries": [query], "from": time_from, "to": time_to},
                )
                result = body["results"][query["refId"]]
                if result.get("error"):
                    entry.update(status="error", error=result["error"])
                else:
                    rows, finite, newest, total = inspect_frames(result)
                    entry.update(rows=rows, finite_values=finite, newest_ms=newest, value_sum=total)
                    entry["status"] = "pass" if rows and finite else "empty"
            except urllib.error.HTTPError as error:
                try:
                    detail = repr(error.read()[:300])
                except (OSError, http.client.HTTPException) as read_error:
                    detail = f"body unreadable: {read_error!r}"
                entry.update(status="error", error=f"HTTP {error.code}: {detail}")
            except http.client.HTTPException as error:
                # A truncated body (IncompleteRead) is not an OSError; record it like transport errors.
                entry.update(status="error", error=f"incomplete response: {error!r}")
            except (ValueError, KeyError, TypeError) as error:
                # A non-JSON body (JSONDecodeError is a ValueError) or a response without the
                # expected results is recorded, never raised, like transport errors below.
                entry.update(status="error", error=f"unexpected response: {error!r}")
            except OSError as error:
                # URLError (connection, DNS, TLS) and a timeout or reset while reading the body are all
                # OSError; record them so optional panels still never fail the run.
                entry.update(status="error", error=f"request failed: {getattr(error, 'reason', None) or error!r}")
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
        os.environ.get("GRAFANA_PASSWORD", ""),
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
    usable = sum(row["status"] == "pass" for row in report)
    print(f"{usable}/{len(report)} queries usable ({len(failed)} required failing)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
