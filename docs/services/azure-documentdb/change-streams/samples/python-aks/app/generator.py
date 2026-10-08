"""Write a deterministic insert/update/replace/delete workload.

Each document id is ``<run_id>:<index>`` so the verifier can match every
change event, including deletes that carry only ``documentKey``.
"""

import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from pymongo import WriteConcern

from common import RUN_COLLECTION, env, get_client, get_database, get_source, log_json, setup_logging, utcnow

logger = setup_logging()


def pad(size: int) -> str:
    """Random hex so storage compression does not shrink the filler."""
    return secrets.token_hex(size // 2) if size else ""


def worker(source, run_id: str, indexes: range, rate: float, pad_bytes: int, counts: dict,
           lock: threading.Lock) -> None:
    interval = 1.0 / rate if rate > 0 else 0.0
    next_at = time.monotonic()
    local = {"insert": 0, "update": 0, "replace": 0, "delete": 0}

    def pace() -> None:
        nonlocal next_at
        if interval:
            next_at += interval
            delay = next_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    try:
        for i in indexes:
            doc_id = f"{run_id}:{i:07d}"
            source.insert_one({
                "_id": doc_id, "run_id": run_id, "seq": i, "version": 1,
                "status": "new", "qty": i % 100, "created_at": utcnow(), "pad": pad(pad_bytes),
            })
            local["insert"] += 1
            pace()
            source.update_one({"_id": doc_id}, {"$set": {"status": "paid", "updated_at": utcnow()},
                                                "$inc": {"version": 1}})
            local["update"] += 1
            pace()
            if i % 10 == 0:
                source.replace_one({"_id": doc_id}, {
                    "run_id": run_id, "seq": i, "version": 3, "status": "replaced", "updated_at": utcnow(),
                    "pad": pad(pad_bytes),
                })
                local["replace"] += 1
                pace()
            if i % 5 == 0:
                source.delete_one({"_id": doc_id})
                local["delete"] += 1
                pace()
    finally:
        # Keep the writes that succeeded before a failure in the run record.
        with lock:
            for key, value in local.items():
                counts[key] += value


def main() -> None:
    run_id = env("RUN_ID")
    docs = int(os.getenv("DOCS", "1000"))
    workers = int(os.getenv("WORKERS", "4"))
    rate = float(os.getenv("RATE", "0"))  # total ops/s, 0 = unthrottled
    # Filler on inserts and replaces so the change log grows like a real payload.
    pad_bytes = int(os.getenv("PAD_BYTES") or "0")  # envsubst leaves "" when unset

    client = get_client(f"cs-generator-{run_id}")
    db = get_database(client)
    source = get_source(db).with_options(write_concern=WriteConcern(w="majority"))
    runs = db[RUN_COLLECTION]

    counts = {"insert": 0, "update": 0, "replace": 0, "delete": 0}
    lock = threading.Lock()
    started = utcnow()
    runs.replace_one({"_id": run_id}, {"_id": run_id, "docs": docs, "workers": workers, "rate": rate,
                                      "pad_bytes": pad_bytes, "started_at": started, "state": "running"}, upsert=True)
    log_json(logger, "generator_start", run_id=run_id, docs=docs, workers=workers, rate=rate,
             pad_bytes=pad_bytes)

    per_worker_rate = rate / workers if rate else 0.0
    errors = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(worker, source, run_id, range(w, docs, workers), per_worker_rate,
                               pad_bytes, counts, lock) for w in range(workers)]
    for future in futures:
        if future.exception():
            errors.append(repr(future.exception())[:500])

    finished = utcnow()
    elapsed = (finished - started).total_seconds()
    total_ops = sum(counts.values())
    # A failed worker leaves the workload incomplete, so the verifiers refuse it.
    state = "failed" if errors else "done"
    runs.update_one({"_id": run_id}, {"$set": {"expected": counts, "finished_at": finished,
                                               "elapsed_s": elapsed, "ops_per_s": total_ops / elapsed,
                                               "state": state, "errors": errors}})
    log_json(logger, f"generator_{state}", run_id=run_id, expected=counts, elapsed_s=round(elapsed, 2),
             ops_per_s=round(total_ops / elapsed, 1), errors=errors)
    client.close()
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
