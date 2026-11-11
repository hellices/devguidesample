"""Compare Grafana Azure Monitor panel totals with a direct ``az monitor metrics list`` query.

``verify_panels.py`` records the sum of every Azure Monitor target over the verified window. For
each metric that ``az monitor metrics list`` returned with the Total aggregation, the matching
Grafana target (same metric name, Total) must report the same sum. Both read the same Azure
Monitor minute bins, so any difference means the dashboard query is not what it claims to be.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def azure_totals(raw: dict) -> dict[str, float]:
    totals: dict[str, float] = {}
    for metric in raw.get("value", []):
        name = metric["name"]["value"]
        total = 0.0
        for series in metric.get("timeseries", []):
            for point in series.get("data", []):
                value = point.get("total")
                if isinstance(value, (int, float)) and math.isfinite(value):
                    total += value
        totals[name] = total
    return totals


def compare(report: list[dict], raw: dict) -> dict:
    expected = azure_totals(raw)
    rows = []
    for metric, total in sorted(expected.items()):
        entries = [entry for entry in report
                   if entry.get("metric") == metric and entry.get("aggregation") == "Total"]
        if not entries:
            rows.append({"metric": metric, "azure_monitor": total, "grafana": None, "match": False})
            continue
        for entry in entries:
            grafana = entry.get("value_sum") if entry.get("status") == "pass" else None
            rows.append({"metric": metric, "panel": entry["panel"], "azure_monitor": total, "grafana": grafana,
                         # Absolute tolerance only: the default rel_tol would accept large absolute gaps.
                         "match": grafana is not None and math.isclose(grafana, total, rel_tol=0.0, abs_tol=0.5)})
    # An empty Azure Monitor result compares nothing and must not read as a match.
    return {"metrics": rows, "all_match": bool(rows) and all(row["match"] for row in rows)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel-verification", type=Path, required=True)
    parser.add_argument("--azure-monitor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.panel_verification.read_text()), json.loads(args.azure_monitor.read_text()))
    args.output.write_text(json.dumps(result, indent=2))
    for row in result["metrics"]:
        mark = "OK" if row["match"] else "MISMATCH"
        print(f"{mark} {row['metric']}: azure_monitor={row['azure_monitor']} grafana={row['grafana']}")
    sys.exit(0 if result["all_match"] else 1)


if __name__ == "__main__":
    main()
