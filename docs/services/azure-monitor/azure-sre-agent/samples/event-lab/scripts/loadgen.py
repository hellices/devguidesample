#!/usr/bin/env python3
import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, Tuple


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded HTTP load generator")
    parser.add_argument("url")
    parser.add_argument("--requests", type=int, default=1)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--expect-status", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.requests <= 10_000:
        parser.error("--requests must be between 1 and 10000")
    if not 1 <= args.concurrency <= 50:
        parser.error("--concurrency must be between 1 and 50")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def request_once(url: str, timeout: float) -> Tuple[Optional[int], float, bool]:
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "sre-event-lab/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read()
            status = response.status
        return status, (time.perf_counter() - started) * 1000, False
    except urllib.error.HTTPError as exc:
        exc.read()
        return exc.code, (time.perf_counter() - started) * 1000, False
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, (time.perf_counter() - started) * 1000, True


def percentile_95(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return round(ordered[index], 2)


def write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    started_at = utc_now()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(
            executor.map(
                lambda _: request_once(args.url, args.timeout),
                range(args.requests),
            )
        )
    ended_at = utc_now()

    statuses = Counter(str(status) for status, _, _ in results if status is not None)
    durations = [duration for _, duration, _ in results]
    errors = sum(1 for _, _, failed in results if failed)
    summary = {
        "url": args.url,
        "started_at": started_at,
        "ended_at": ended_at,
        "total": args.requests,
        "concurrency": args.concurrency,
        "expected_status": args.expect_status,
        "status_counts": dict(sorted(statuses.items())),
        "errors": errors,
        "average_ms": round(sum(durations) / len(durations), 2),
        "p95_ms": percentile_95(durations),
    }
    write_summary(args.output, summary)

    expected_count = statuses.get(str(args.expect_status), 0)
    return 0 if errors == 0 and expected_count == args.requests else 2


if __name__ == "__main__":
    raise SystemExit(main())
