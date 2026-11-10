"""Probe VictoriaMetrics for the metric inventory the dashboard agent will build on.

The output keeps metric names, label keys, safe label values, sample counts and
freshness only. Resource IDs, hostnames and subscription identifiers never leave
this script because only allowlisted label values are copied.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

SAFE_LABEL_VALUES = {
    "source_path",
    "delivery_path",
    "partition",
    "metadata_Replica",
    "metadata_EntityName",
    "metadata_Role",
    "aggregation",
    "metric",
    "unit",
}
WINDOW = "30m"


def _quote(value: str) -> str:
    """PromQL/MetricsQL string literal for a label value returned by the server."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def query(base_url: str, path: str, params: dict[str, str] | list[tuple[str, str]]) -> dict:
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"{base_url}{path}", data=data, timeout=30) as response:
        body = json.load(response)
    if body.get("status") != "success":
        raise RuntimeError(f"query failed: {path} {body}")
    return body["data"]


DURATION = re.compile(r"(\d+)([smhd])")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def window_seconds(window: str) -> int:
    match = DURATION.fullmatch(window)
    if not match or int(match.group(1)) <= 0:
        raise ValueError(f"window must be a positive duration such as 30m, 6h or 1d: {window!r}")
    return int(match.group(1)) * UNIT_SECONDS[match.group(2)]


def build_inventory(base_url: str, window: str = WINDOW) -> dict:
    now = int(time.time())
    # Discover series over at least the aggregation window so no path inside it is missed.
    start = now - max(6 * 3600, window_seconds(window))
    series = query(
        base_url,
        "/api/v1/series",
        [("match[]", '{source_path!=""}'), ("start", str(start)), ("end", str(now))],
    )
    inventory: dict[str, dict] = {}
    combos: dict[tuple[str, str], set[str]] = defaultdict(set)
    for labels in series:
        name = labels["__name__"]
        entry = inventory.setdefault(
            name, {"label_keys": set(), "values": defaultdict(set), "paths": set()}
        )
        for key, value in labels.items():
            if key == "__name__":
                continue
            entry["label_keys"].add(key)
            if key in SAFE_LABEL_VALUES:
                entry["values"][key].add(value)
        # An absent label stays "" so the matcher below (label="") selects exactly those series.
        path = (labels.get("source_path", ""), labels.get("delivery_path", ""))
        entry["paths"].add(path)
        combos[path].add(name)

    path_stats = []
    for source, delivery in sorted(combos):
        selector = f"{{source_path={_quote(source)},delivery_path={_quote(delivery)}}}"
        # Evaluate at the same snapshot time as the series lookup so freshness is never negative.
        count = query(base_url, "/api/v1/query",
                      {"query": f"sum(count_over_time({selector}[{window}]))", "time": str(now)})
        newest = query(base_url, "/api/v1/query",
                       {"query": f"max(tlast_over_time({selector}[{window}]))", "time": str(now)})
        newest_ts = float(newest["result"][0]["value"][1]) if newest["result"] else None
        path_stats.append(
            {
                "source_path": source or "(missing)",
                "delivery_path": delivery or "(missing)",
                "metric_names": len(combos[(source, delivery)]),
                "samples_in_window": int(float(count["result"][0]["value"][1])) if count["result"] else 0,
                "freshness_seconds": round(now - newest_ts, 1) if newest_ts is not None else None,
            }
        )

    return {
        "generated_at_unix": now,
        "window": window,
        "metrics": {
            name: {
                "label_keys": sorted(entry["label_keys"]),
                "safe_label_values": {k: sorted(v) for k, v in sorted(entry["values"].items())},
                "paths": sorted(["/".join(part or "(missing)" for part in p) for p in entry["paths"]]),
            }
            for name, entry in sorted(inventory.items())
        },
        "paths": path_stats,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-url", required=True, help="for example http://127.0.0.1:$(scripts/vm-query.sh port)")
    parser.add_argument("--window", default=WINDOW)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = build_inventory(args.vm_url.rstrip("/"), args.window)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, ensure_ascii=False))
    for row in inventory["paths"]:
        print(
            f"{row['source_path']:>20} {row['delivery_path']:>12} metrics={row['metric_names']:>3} "
            f"samples={row['samples_in_window']:>6} freshness={row['freshness_seconds']}s"
        )


if __name__ == "__main__":
    main()
