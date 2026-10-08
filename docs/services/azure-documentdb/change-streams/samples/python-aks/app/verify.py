"""Compare the generator's expected events with what the consumer committed."""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Optional

from common import RUN_COLLECTION, SINK_COLLECTION, env, get_client, get_database

def percentile(values: list, pct: float):
    if not values:
        return None
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(pct / 100 * (len(values) - 1))))
    return round(values[k], 1)


def summarize(values: list) -> dict:
    return {"p50": percentile(values, 50), "p95": percentile(values, 95), "p99": percentile(values, 99),
            "max": percentile(values, 100), "n": len(values)}


def event_identity(doc_id: str, op: str, version: Optional[int]) -> tuple:
    """Identity that distinguishes the ordinary update from a replacement."""
    return doc_id, op, version if op in ("insert", "update") else None


def event_rank(op: str, version: Optional[int]) -> int:
    """Expected per-document order for the deterministic generator."""
    if op == "insert":
        return 0
    if op == "update" and version == 2:
        return 1
    if op == "update" and version == 3:
        return 2
    if op == "delete":
        return 3
    return 99


def expected_events(run_id: str, docs: int) -> Counter:
    """Expected (doc_id, operationType, version) identities."""
    expected = Counter()
    for i in range(docs):
        doc_id = f"{run_id}:{i:07d}"
        expected[event_identity(doc_id, "insert", 1)] += 1
        expected[event_identity(doc_id, "update", 2)] += 1
        if i % 10 == 0:
            # DocumentDB reports replace_one as operationType: update.
            expected[event_identity(doc_id, "update", 3)] += 1
        if i % 5 == 0:
            expected[event_identity(doc_id, "delete", None)] += 1
    return expected


def main() -> None:
    run_id = env("RUN_ID")
    client = get_client(f"cs-verify-{run_id}")
    db = get_database(client)
    run = db[RUN_COLLECTION].find_one({"_id": run_id})
    if not run or run.get("state") != "done":
        print(json.dumps({"run_id": run_id, "error": "generator run not finished", "run": run}, default=str))
        sys.exit(2)

    sink = os.getenv("SINK") or SINK_COLLECTION
    events = list(db[sink].find(
        {"doc_id": {"$regex": f"^{re.escape(run_id)}:"}},
        {"doc_id": 1, "op": 1, "recv_ns": 1, "pod": 1, "has_full_document": 1,
         "has_update_description": 1, "deliveries": 1, "lag_ms": 1, "version": 1},
    ))
    # The sink is keyed by resume token, so each row is one distinct event and
    # replays show up as deliveries > 1 instead of extra rows.
    got = Counter(event_identity(e["doc_id"], e["op"], e.get("version")) for e in events)
    expected = expected_events(run_id, run["docs"])
    missing = sorted((expected - got).elements())
    unexpected = sorted((got - expected).elements())

    # Per-document order: insert(v1) -> update(v2) -> replacement(v3) -> delete.
    per_doc = defaultdict(list)
    for e in events:
        per_doc[e["doc_id"]].append(
            (e["recv_ns"], event_rank(e["op"], e.get("version")))
        )
    out_of_order = [d for d, seq in per_doc.items()
                    if [o for _, o in sorted(seq)] != sorted(o for _, o in seq)]

    lag_by_op = defaultdict(list)
    for e in events:
        if e.get("lag_ms") is not None:
            lag_by_op[e["op"]].append(e["lag_ms"])

    result = {
        "run_id": run_id,
        "sink": sink,
        "docs": run["docs"],
        "workers": run["workers"],
        "generator_ops_per_s": round(run["ops_per_s"], 1),
        "generator_elapsed_s": round(run["elapsed_s"], 1),
        "generator_ops": run["expected"],
        "expected_events": sum(expected.values()),
        "received_events": len(events),
        "received_by_op": dict(Counter(e["op"] for e in events)),
        "pods": dict(Counter(e["pod"] for e in events)),
        "missing": len(missing),
        "missing_sample": missing[:10],
        "unexpected": len(unexpected),
        "unexpected_sample": unexpected[:10],
        "redelivered_events": sum(1 for e in events if e.get("deliveries", 1) > 1),
        "redeliveries_total": sum(e.get("deliveries", 1) - 1 for e in events),
        "per_doc_out_of_order": len(out_of_order),
        "update_without_update_description": sum(1 for e in events if e["op"] == "update"
                                                 and not e["has_update_description"]),
        "lag_ms": {op: summarize(v) for op, v in lag_by_op.items()},
    }
    print(json.dumps(result, default=str, indent=None if os.getenv("COMPACT") else 2))
    client.close()
    sys.exit(0 if not missing and not unexpected and not out_of_order else 1)


if __name__ == "__main__":
    main()
