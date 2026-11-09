"""Compare Azure Monitor PT1M bins with what VictoriaMetrics stored for the same window.

remote write keeps the Azure Monitor minute-bin timestamp, so each bin must match one remote
write sample exactly. The scrape path re-stamps and repeats values, so only its window total is
reported. Diagnostic Settings exports only non-zero minutes, so its presence is counted.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("IncomingMessages", "OutgoingMessages", "IncomingRequests", "ThrottledRequests")
Fetch = Callable[[str, dict], str]


def _minute(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _per_minute(fetch: Fetch, selector: str, start: int, end: int) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in fetch("/api/v1/export", {"match[]": selector, "start": start, "end": end - 1}).splitlines():
        series = json.loads(line)
        for value, ts in zip(series["values"], series["timestamps"]):
            minute = _minute(ts / 1000)
            values[minute] = values.get(minute, 0) + value
    return values


def compare(raw: dict, start: int, end: int, fetch: Fetch) -> dict:
    expected = [_minute(ts) for ts in range(start, end, 60)]
    report: dict = {"window": {"from": start, "to": end}, "expected_minutes": len(expected), "metrics": {}}
    for metric in raw.get("value", []):
        name = metric["name"]["value"]
        direct: dict[str, float] = {}
        for series in metric["timeseries"]:
            for point in series["data"]:
                if point.get("total") is None:
                    continue  # a bin Azure Monitor has not filled yet is missing, not zero
                minute = point["timeStamp"][:16]
                if minute in expected:
                    direct[minute] = direct.get(minute, 0) + point["total"]
        api = 'source_path="azure_monitor_api"'
        remote = _per_minute(fetch, f'azure_{name.lower()}_total_Count{{{api},delivery_path="remote_write"}}', start, end)
        totals = {}
        for delivery in ("remote_write", "scrape"):
            query = f'sum(sum_over_time(azure_{name.lower()}_total_Count{{{api},delivery_path="{delivery}"}}[{end - start}s]))'
            result = json.loads(fetch("/api/v1/query", {"query": query, "time": end - 1}))["data"]["result"]
            totals[delivery] = float(result[0]["value"][1]) if result else None
        diagnostic = _per_minute(
            fetch, f'{name.lower()}_total{{source_path="diagnostic_eventhub",delivery_path="remote_write"}}', start, end
        )
        minutes = sorted(direct)
        report["metrics"][name] = {
            "azure_monitor_total": sum(direct.values()),
            "victoriametrics_total": totals,
            "minutes": len(minutes),
            "minutes_matching_remote_write": sum(1 for m in minutes if remote.get(m) == direct[m]),
            "minutes_missing_in_azure_monitor": [m for m in expected if m not in direct],
            "minutes_missing_in_remote_write": [m for m in minutes if m not in remote],
            "diagnostic_eventhub_total": sum(diagnostic.values()) if diagnostic else None,
            "minutes_matching_diagnostic_eventhub": sum(1 for m in minutes if diagnostic.get(m) == direct[m]),
            "minutes_present_in_diagnostic_eventhub": sum(1 for m in minutes if m in diagnostic),
        }
    # Complete means every requested metric has every minute of [from, to) in Azure Monitor and
    # the same value in remote write.
    report["complete"] = bool(expected) and all(
        name in report["metrics"]
        and report["metrics"][name]["minutes"] == len(expected)
        and report["metrics"][name]["minutes_matching_remote_write"] == len(expected)
        for name in REQUIRED
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--azure-monitor", type=Path, required=True)
    parser.add_argument("--from-ms", type=int, required=True)
    parser.add_argument("--to-ms", type=int, required=True)
    parser.add_argument("--vm-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def fetch(path: str, params: dict) -> str:
        body = urllib.parse.urlencode(params).encode()
        return urllib.request.urlopen(f"{args.vm_url.rstrip('/')}{path}", body, timeout=30).read().decode()

    report = compare(json.loads(args.azure_monitor.read_text()), args.from_ms // 1000, args.to_ms // 1000, fetch)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["complete"] else 1)


if __name__ == "__main__":
    main()
