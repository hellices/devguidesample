"""Compare Azure Monitor PT1M bins with what VictoriaMetrics stored for the same window.

remote write keeps the Azure Monitor minute-bin timestamp, so each bin must match remote write
samples stamped exactly on that minute. The scrape path re-stamps and repeats values, so it is
reported only as a repeated-sample sum, never as a total. Diagnostic Settings exports only
non-zero minutes, so its presence is counted.
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


def _samples(fetch: Fetch, selector: str, start: int, end: int) -> list[tuple[int, float]]:
    """Every stored (timestamp ms, value) of the selector inside [start, end), filtered in ms."""
    samples = []
    for line in fetch("/api/v1/export", {"match[]": selector, "start": start, "end": end}).splitlines():
        series = json.loads(line)
        samples.extend(
            (ts, value)
            for value, ts in zip(series["values"], series["timestamps"])
            if start * 1000 <= ts < end * 1000
        )
    return samples


def _per_minute(samples: list[tuple[int, float]], off_bin: list[int] | None = None) -> dict[str, float]:
    """Sum samples per UTC minute; with off_bin, record samples not stamped exactly on a minute."""
    values: dict[str, float] = {}
    for ts, value in samples:
        if off_bin is not None and ts % 60000:
            off_bin.append(ts)
            continue
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
        off_bin: list[int] = []
        stored = {
            delivery: _samples(
                fetch, f'azure_{name.lower()}_total_Count{{{api},delivery_path="{delivery}"}}', start, end
            )
            for delivery in ("remote_write", "scrape")
        }
        remote = _per_minute(stored["remote_write"], off_bin)
        # Totals come from the same ms-filtered samples, so they share the [start, end) window exactly.
        totals = {
            delivery: sum(value for _, value in samples) if samples else None
            for delivery, samples in stored.items()
        }
        diagnostic = _per_minute(_samples(
            fetch, f'{name.lower()}_total{{source_path="diagnostic_eventhub",delivery_path="remote_write"}}', start, end
        ))
        minutes = sorted(direct)
        report["metrics"][name] = {
            "azure_monitor_total": sum(direct.values()),
            "remote_write_total": totals["remote_write"],
            # Each bin is stored once per scrape, so this is a multiple of the real total.
            "scrape_repeated_sample_sum": totals["scrape"],
            "remote_write_off_bin_samples": len(off_bin),
            "minutes": len(minutes),
            "minutes_matching_remote_write": sum(1 for m in minutes if remote.get(m) == direct[m]),
            "minutes_missing_in_azure_monitor": [m for m in expected if m not in direct],
            "minutes_missing_in_remote_write": [m for m in minutes if m not in remote],
            "diagnostic_eventhub_total": sum(diagnostic.values()) if diagnostic else None,
            "minutes_matching_diagnostic_eventhub": sum(1 for m in minutes if diagnostic.get(m) == direct[m]),
            "minutes_present_in_diagnostic_eventhub": sum(1 for m in minutes if m in diagnostic),
        }
    # Complete means every requested metric has every minute of [from, to) in Azure Monitor and
    # the same value in remote write, stamped exactly on the Azure Monitor minute.
    report["complete"] = bool(expected) and all(
        name in report["metrics"]
        and report["metrics"][name]["minutes"] == len(expected)
        and report["metrics"][name]["minutes_matching_remote_write"] == len(expected)
        and report["metrics"][name]["remote_write_off_bin_samples"] == 0
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
    # The comparison is per PT1M bin, so both ends must be whole UTC minutes.
    if args.from_ms >= args.to_ms or args.from_ms % 60000 or args.to_ms % 60000:
        parser.error("--from-ms and --to-ms must be whole minutes (multiples of 60000) with from < to")

    def fetch(path: str, params: dict) -> str:
        body = urllib.parse.urlencode(params).encode()
        return urllib.request.urlopen(f"{args.vm_url.rstrip('/')}{path}", body, timeout=30).read().decode()

    report = compare(json.loads(args.azure_monitor.read_text()), args.from_ms // 1000, args.to_ms // 1000, fetch)
    args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["complete"] else 1)


if __name__ == "__main__":
    main()
