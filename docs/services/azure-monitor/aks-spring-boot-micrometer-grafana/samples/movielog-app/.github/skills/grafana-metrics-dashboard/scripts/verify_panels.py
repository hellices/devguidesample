"""Runs every panel query of a dashboard through Grafana's /api/ds/query and reports empty panels.

GitHub Copilot runs this before it says a dashboard is done: a panel that renders "No data"
is a failed panel, not a finished one.

The token audience is https://dashboard.azure.com, as documented in "Authenticate to Azure Managed
Grafana data plane APIs with Microsoft Entra ID" (learn.microsoft.com/azure/managed-grafana/
how-to-authenticate-data-plane-api). A token for https://grafana.azure.com is rejected with 401.

Usage:
  GRAFANA_URL=https://<grafana-endpoint> GRAFANA_TOKEN=$(az account get-access-token \
    --resource https://dashboard.azure.com --query accessToken -o tsv) \
  python verify_panels.py <dashboard.json> --appinsights-id <resource-id> [--role movielog] [--hours 1]
  python verify_panels.py <dashboard.json> --appinsights-id <resource-id> \
    --from 2026-11-07T23:05:00Z --to 2026-11-07T23:35:00Z   # a fixed past window
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone


def frames_summary(result):
    """Counts rows that carry at least one non-null number; a row of nulls is not data, a 0 is."""
    frames = result.get("frames", [])
    rows = 0
    for frame in frames:
        fields = frame.get("schema", {}).get("fields", [])
        values = frame.get("data", {}).get("values", [])
        numeric = [i for i, f in enumerate(fields) if f.get("type") == "number" and i < len(values)]
        columns = [values[i] for i in numeric] if numeric else values
        length = max((len(c) for c in columns), default=0)
        rows += sum(1 for r in range(length) if any(r < len(c) and c[r] is not None for c in columns))
    return len(frames), rows


def kql_string(value):
    """Quotes a value like Grafana's ${var:singlequote} format, so the query sent here matches the dashboard."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def epoch_ms(value):
    """Converts an ISO 8601 time (UTC when no offset is given) to the epoch milliseconds Grafana expects."""
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return str(int(moment.timestamp() * 1000))


def query_panels(panels):
    """Yields query panels, including those nested in collapsed rows."""
    for panel in panels:
        if panel.get("type") == "row":
            yield from query_panels(panel.get("panels", []))
        elif any(not t.get("hide") for t in panel.get("targets", [])):
            yield panel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("dashboard")
    parser.add_argument("--appinsights-id", required=True)
    parser.add_argument("--role", default="movielog")
    parser.add_argument("--hours", type=int, default=1, help="relative range now-<hours>h..now")
    parser.add_argument("--from", dest="time_from", help="absolute start, ISO 8601 (use with --to)")
    parser.add_argument("--to", dest="time_to", help="absolute end, ISO 8601 (use with --from)")
    parser.add_argument("--datasource-uid", default="azure-monitor-oob")
    args = parser.parse_args()
    if (args.time_from is None) != (args.time_to is None):
        parser.error("--from and --to must be given together")
    if args.time_from:
        time_range = {"from": epoch_ms(args.time_from), "to": epoch_ms(args.time_to)}
    else:
        time_range = {"from": f"now-{args.hours}h", "to": "now"}

    url = os.environ["GRAFANA_URL"].rstrip("/") + "/api/ds/query"
    token = os.environ["GRAFANA_TOKEN"]
    dashboard = json.load(open(args.dashboard, encoding="utf-8"))

    failed = 0
    for panel in query_panels(dashboard["panels"]):
        queries = []
        for t in panel["targets"]:
            if t.get("hide"):
                continue
            q = json.loads(json.dumps(t))
            q["datasource"] = {"type": "grafana-azure-monitor-datasource", "uid": args.datasource_uid}
            la = q["azureLogAnalytics"]
            la["resources"] = [args.appinsights_id]
            la["query"] = la["query"].replace("${role:singlequote}", kql_string(args.role))
            q["intervalMs"] = 60000
            q["maxDataPoints"] = 500
            queries.append(q)
        body = json.dumps({"queries": queries, **time_range}).encode()
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        expected = [q["refId"] for q in queries]
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                results = json.load(response)["results"]
        except urllib.error.HTTPError as error:
            # A request-level failure belongs to every query in the request, whatever its refId.
            message = f"HTTP {error.code}: {error.read().decode()[:200]}"
            results = {ref: {"error": message} for ref in expected}
        for ref in expected:
            # A query the response leaves out is a failure, not a silent pass.
            result = results.get(ref, {"error": "no result returned for this refId"})
            frames, rows = frames_summary(result)
            ok = "error" not in result and rows > 0
            failed += 0 if ok else 1
            status = "OK  " if ok else "FAIL"
            detail = result.get("error", "")[:120]
            print(f"{status} {panel['title']:<40} frames={frames:<3} rows={rows:<5} {detail}")
    print(f"\n{failed} panel query(ies) returned no data or an error.")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
