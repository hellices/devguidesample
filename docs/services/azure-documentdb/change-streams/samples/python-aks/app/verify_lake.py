"""Compare the generator's expected events with the Parquet files in ADLS Gen2."""

import io
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import timezone

import pyarrow.parquet as pq
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient

from common import RUN_COLLECTION, env, get_client, get_database
from lake_export import window_start
from verify import expected_events, percentile, summarize

logging.getLogger("azure").setLevel(logging.WARNING)


def main() -> None:
    run_id = env("RUN_ID")
    client = get_client(f"cs-verify-lake-{run_id}")
    run = get_database(client)[RUN_COLLECTION].find_one({"_id": run_id})
    if not run or run.get("state") != "done":
        print(json.dumps({"run_id": run_id, "error": "generator run not finished", "run": run}, default=str))
        sys.exit(2)

    service = DataLakeServiceClient(env("LAKE_URL"), credential=DefaultAzureCredential())
    fs = service.get_file_system_client(env("LAKE_FILESYSTEM", "cdc"))
    prefix = env("LAKE_PREFIX", "orders")
    window_minutes = int(os.getenv("WINDOW_MINUTES", "10"))
    chunk_bytes = int(os.getenv("CHUNK_BYTES", str(50_000_000)))
    columns = ["resume_token", "op", "doc_id", "wall_time", "read_at"]

    rows = []
    files = []
    for path in fs.get_paths(path=prefix, recursive=True):
        if path.is_directory or not path.name.endswith(".parquet"):
            continue
        data = fs.get_file_client(path.name).download_file().readall()
        table = pq.read_table(io.BytesIO(data), columns=columns)
        mine = [r for r in table.to_pylist() if r["doc_id"].startswith(f"{run_id}:")]
        if not mine:
            continue
        # A file holds one window, so every row with wallTime maps to it.
        windows = {window_start(t, window_minutes) for t in table.column("wall_time").to_pylist()
                   if t is not None}
        files.append({"rows": len(mine), "file_rows": table.num_rows, "bytes": path.content_length,
                      "windows": len(windows)})
        # The listing returns last-modified as a naive UTC datetime.
        committed_at = path.last_modified.replace(tzinfo=timezone.utc)
        for i, r in enumerate(mine):
            r["committed_at"] = committed_at
            r["idx"] = i
            rows.append(r)

    # Every event has a unique resume token, so extra rows with the same token
    # are duplicates written by a retried or overlapping export.
    by_token = Counter(r["resume_token"] for r in rows)
    duplicates = sum(c - 1 for c in by_token.values() if c > 1)
    seen = set()
    events = []
    for r in sorted(rows, key=lambda r: (r["read_at"], r["committed_at"], r["idx"])):
        if r["resume_token"] not in seen:
            seen.add(r["resume_token"])
            events.append(r)

    got = Counter((e["doc_id"], e["op"]) for e in events)
    expected = expected_events(run_id, run["docs"])
    missing = sorted((expected - got).elements())
    unexpected = sorted((got - expected).elements())

    order = {"insert": 0, "update": 1, "replace": 1, "delete": 2}
    per_doc = defaultdict(list)
    for e in events:
        per_doc[e["doc_id"]].append(order[e["op"]])
    out_of_order = [d for d, seq in per_doc.items() if seq != sorted(seq)]

    read_lag_ms = [(e["read_at"] - e["wall_time"]).total_seconds() * 1000 for e in events if e["wall_time"]]
    commit_lag_s = [(e["committed_at"] - e["wall_time"]).total_seconds() for e in events if e["wall_time"]]
    file_rows = [f["file_rows"] for f in files]
    file_bytes = [f["bytes"] for f in files]
    mixed_windows = sum(1 for f in files if f["windows"] > 1)
    oversize = sum(1 for b in file_bytes if b > chunk_bytes)

    result = {
        "run_id": run_id,
        "docs": run["docs"],
        "generator_ops_per_s": round(run["ops_per_s"], 1),
        "generator_elapsed_s": round(run["elapsed_s"], 1),
        "expected_events": sum(expected.values()),
        "received_events": len(events),
        "duplicate_rows": duplicates,
        "missing": len(missing),
        "missing_sample": missing[:10],
        "unexpected": len(unexpected),
        "unexpected_sample": unexpected[:10],
        "per_doc_out_of_order": len(out_of_order),
        "read_lag_ms": summarize(read_lag_ms),
        # Storage last-modified has one-second resolution.
        "commit_lag_s": summarize(commit_lag_s),
        "files": len(files),
        "file_rows": {"min": min(file_rows, default=None), "p50": percentile(file_rows, 50),
                      "max": max(file_rows, default=None)},
        "file_bytes": {"min": min(file_bytes, default=None), "p50": percentile(file_bytes, 50),
                       "max": max(file_bytes, default=None), "total": sum(file_bytes)},
        "files_with_mixed_windows": mixed_windows,
        "files_over_chunk_bytes": oversize,
    }
    print(json.dumps(result, default=str, indent=None if os.getenv("COMPACT") else 2))
    client.close()
    ok = not (missing or unexpected or duplicates or out_of_order or mixed_windows or oversize)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
