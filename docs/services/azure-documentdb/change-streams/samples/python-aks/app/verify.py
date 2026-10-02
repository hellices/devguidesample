"""Compare the generator's expected events with what the consumer committed."""

import json
import os
import sys
from collections import Counter, defaultdict

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


def expected_events(run_id: str, docs: int) -> Counter:
    """Expected (doc_id, op) counts.

    ``replace_one`` is counted under ``update`` because the cluster under test
    emits replacements as ``operationType: update``.
    """
    expected = Counter()
    for i in range(docs):
        doc_id = f"{run_id}:{i:07d}"
        expected[(doc_id, "insert")] += 1
        expected[(doc_id, "update")] += 2 if i % 10 == 0 else 1
        if i % 5 == 0:
            expected[(doc_id, "delete")] += 1
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
        {"doc_id": {"$regex": f"^{run_id}:"}},
        {"doc_id": 1, "op": 1, "recv_ns": 1, "pod": 1, "has_full_document": 1,
         "has_update_description": 1, "deliveries": 1, "lag_ms": 1},
    ))
    # The sink is keyed by resume token, so each row is one distinct event and
    # replays show up as deliveries > 1 instead of extra rows.
    got = Counter((e["doc_id"], e["op"]) for e in events)
    expected = expected_events(run_id, run["docs"])
    missing = sorted((expected - got).elements())
    unexpected = sorted((got - expected).elements())

    # Per-document order: insert -> update(s) -> delete.
    order = {"insert": 0, "update": 1, "replace": 1, "delete": 2}
    per_doc = defaultdict(list)
    for e in events:
        per_doc[e["doc_id"]].append((e["recv_ns"], order[e["op"]]))
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
    sys.exit(0 if not missing and not unexpected else 1)


if __name__ == "__main__":
    main()
