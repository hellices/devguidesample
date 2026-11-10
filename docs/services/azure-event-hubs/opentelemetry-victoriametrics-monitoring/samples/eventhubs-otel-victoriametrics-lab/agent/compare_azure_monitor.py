"""Compare Azure Monitor PT1M bins with what VictoriaMetrics stored for the same window.

remote write keeps the Azure Monitor minute-bin timestamp, so each bin must match remote write
samples stamped exactly on that minute. The scrape path re-stamps and repeats values, so it is
reported only as a repeated-sample sum, never as a total. Diagnostic Settings exports only
non-zero minutes, so its presence is counted.

azuremonitorreceiver reads one PT1M bin per collection cycle and never re-reads it, so a bin it
missed stays missing. A missing minute followed by a later remote write bin is reported as a gap;
a missing tail with nothing after it may still be in flight and keeps the report incomplete.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

REQUIRED = ("IncomingMessages", "OutgoingMessages", "IncomingRequests", "ThrottledRequests")
# Namespace records only: a Dedicated cluster streams its own totals to the same hub.
DIAGNOSTIC = ('source_path="diagnostic_eventhub",delivery_path="remote_write",'
              'azure_resource_id=~"(?i).*/providers/microsoft\\\\.eventhub/namespaces/.*"')
Fetch = Callable[[str, dict], str]
# How far past the window to look for a later bin that proves an earlier one was skipped.
LOOKAHEAD_SECONDS = 300


def _resource_matcher(metric: dict) -> str:
    """Exact, case-insensitive azuremonitor_resource_id matcher for the resource Azure Monitor answered for."""
    metric_id = metric.get("id") or ""
    cut = metric_id.lower().find("/providers/microsoft.insights/")
    if cut <= 0:
        raise ValueError(f"Azure Monitor metric {metric.get('name')} has no resource id")
    pattern = "(?i)" + re.escape(metric_id[:cut])
    # A PromQL string literal needs its backslashes and quotes escaped once more.
    return 'azuremonitor_resource_id=~"' + pattern.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
    expected_set = set(expected)
    report: dict = {"window": {"from": start, "to": end}, "expected_minutes": len(expected), "metrics": {}}
    for metric in raw.get("value", []):
        name = metric["name"]["value"]
        direct: dict[str, float] = {}
        for series in metric["timeseries"]:
            for point in series["data"]:
                if point.get("total") is None:
                    continue  # a bin Azure Monitor has not filled yet is missing, not zero
                minute = point["timeStamp"][:16]
                if minute in expected_set:
                    direct[minute] = direct.get(minute, 0) + point["total"]
        # Only the series of the resource Azure Monitor answered for; another namespace with the same
        # metric name must not be summed into the comparison.
        api = f'source_path="azure_monitor_api",{_resource_matcher(metric)}'
        off_bin: list[int] = []
        stored = {
            delivery: _samples(
                fetch, f'azure_{name.lower()}_total_Count{{{api},delivery_path="{delivery}"}}', start, end
            )
            for delivery in ("remote_write", "scrape")
        }
        remote = _per_minute(stored["remote_write"], off_bin)
        later = _samples(
            fetch, f'azure_{name.lower()}_total_Count{{{api},delivery_path="remote_write"}}', end, end + LOOKAHEAD_SECONDS
        )
        # Only a bin stamped exactly on a minute proves the receiver moved past a missing one.
        last_stored = max([ts // 1000 for ts, _ in stored["remote_write"] + later if ts % 60000 == 0], default=None)
        # Totals come from the same ms-filtered samples, so they share the [start, end) window exactly.
        totals = {
            delivery: sum(value for _, value in samples) if samples else None
            for delivery, samples in stored.items()
        }
        diagnostic = _per_minute(_samples(
            fetch, f'{name.lower()}_total{{{DIAGNOSTIC}}}', start, end
        ))
        minutes = sorted(direct)
        missing = [m for m in minutes if m not in remote]
        # A missing minute is a permanent receiver gap only if a later bin was stored after it.
        gaps = [m for m in missing if last_stored is not None and _minute(last_stored) > m]
        report["metrics"][name] = {
            "azure_monitor_total": sum(direct.values()),
            "remote_write_total": totals["remote_write"],
            # Each bin is stored once per scrape, so this is a multiple of the real total.
            "scrape_repeated_sample_sum": totals["scrape"],
            "remote_write_off_bin_samples": len(off_bin),
            "minutes": len(minutes),
            "minutes_matching_remote_write": sum(1 for m in minutes if remote.get(m) == direct[m]),
            "minutes_missing_in_azure_monitor": [m for m in expected if m not in direct],
            "minutes_missing_in_remote_write": missing,
            "remote_write_gaps": gaps,
            "diagnostic_eventhub_total": sum(diagnostic.values()) if diagnostic else None,
            "minutes_matching_diagnostic_eventhub": sum(1 for m in minutes if diagnostic.get(m) == direct[m]),
            "minutes_present_in_diagnostic_eventhub": sum(1 for m in minutes if m in diagnostic),
        }
    # Complete means every requested metric has every minute of [from, to) in Azure Monitor, and
    # remote write holds the same value stamped exactly on that minute for every minute except
    # receiver gaps that a later stored bin proves will never arrive.
    report["complete"] = bool(expected) and all(
        name in report["metrics"]
        and report["metrics"][name]["minutes"] == len(expected)
        and report["metrics"][name]["minutes_matching_remote_write"]
        == len(expected) - len(report["metrics"][name]["remote_write_gaps"])
        and report["metrics"][name]["remote_write_off_bin_samples"] == 0
        for name in REQUIRED
    )
    report["remote_write_gaps"] = sum(len(m.get("remote_write_gaps", [])) for m in report["metrics"].values())
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
