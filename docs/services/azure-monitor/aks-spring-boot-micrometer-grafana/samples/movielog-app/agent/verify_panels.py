"""Runs every panel query of a dashboard through Grafana's /api/ds/query and reports empty panels.

The agent uses this before it says a dashboard is done: a panel that renders "No data"
is a failed panel, not a finished one.

The token audience is https://dashboard.azure.com, as documented in "Authenticate to Azure Managed
Grafana data plane APIs with Microsoft Entra ID" (learn.microsoft.com/azure/managed-grafana/
how-to-authenticate-data-plane-api). A token for https://grafana.azure.com is rejected with 401.

Usage:
  GRAFANA_URL=https://<grafana-endpoint> GRAFANA_TOKEN=$(az account get-access-token \
    --resource https://dashboard.azure.com --query accessToken -o tsv) \
  python verify_panels.py <dashboard.json> --appinsights-id <resource-id> [--role movielog] [--hours 1]
"""
import argparse
import json
import os
import sys
import urllib.request


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
    parser.add_argument("--hours", type=int, default=1)
    parser.add_argument("--datasource-uid", default="azure-monitor-oob")
    args = parser.parse_args()

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
            la["query"] = la["query"].replace("$role", args.role)
            q["intervalMs"] = 60000
            q["maxDataPoints"] = 500
            queries.append(q)
        body = json.dumps({"queries": queries, "from": f"now-{args.hours}h", "to": "now"}).encode()
        request = urllib.request.Request(url, data=body, method="POST", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                results = json.load(response)["results"]
        except urllib.error.HTTPError as error:
            results = {"A": {"error": f"HTTP {error.code}: {error.read().decode()[:200]}"}}
        expected = [q["refId"] for q in queries]
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
