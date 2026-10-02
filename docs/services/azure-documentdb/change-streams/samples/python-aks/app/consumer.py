"""Change stream consumer for AKS.

The consumer stores processed events in a sink collection and saves the
resume token in a checkpoint collection, so a replacement pod continues from
the last committed event instead of a local file.
"""

import json
import os
import signal
import socket
import time
from typing import Any, Optional

from pymongo import UpdateOne
from pymongo.errors import OperationFailure, PyMongoError

from common import (
    CHECKPOINT_COLLECTION,
    SINK_COLLECTION,
    env,
    get_client,
    get_database,
    get_source,
    log_json,
    setup_logging,
    utcnow,
)

logger = setup_logging()
stopping = False


def handle_sigterm(signum: int, _frame: Any) -> None:
    global stopping
    stopping = True
    log_json(logger, "signal", signum=signum)


def load_checkpoint(db, consumer_id: str) -> Optional[dict]:
    doc = db[CHECKPOINT_COLLECTION].find_one({"_id": consumer_id})
    return doc["token"] if doc else None


def save_checkpoint(db, consumer_id: str, token: dict, events: int) -> None:
    db[CHECKPOINT_COLLECTION].update_one(
        {"_id": consumer_id},
        {
            "$set": {"token": token, "updated_at": utcnow(), "pod": socket.gethostname()},
            "$inc": {"events": events},
        },
        upsert=True,
    )


def to_sink(change: dict, pod: str) -> UpdateOne:
    received = utcnow()
    full = change.get("fullDocument") or {}
    key = change.get("documentKey", {}).get("_id")
    written = full.get("updated_at") or full.get("created_at")
    lag_ms = (received - written).total_seconds() * 1000 if written else None
    doc = {
        "op": change["operationType"],
        "doc_id": key,
        "run_id": full.get("run_id") or (key.split(":")[0] if isinstance(key, str) else None),
        "seq": full.get("seq"),
        "version": full.get("version"),
        "has_full_document": "fullDocument" in change and change["fullDocument"] is not None,
        "has_update_description": "updateDescription" in change,
        "received_at": received,
        "recv_ns": time.time_ns(),
        "lag_ms": lag_ms,
        "pod": pod,
    }
    # Keyed by resume token: a replayed event updates the same row and bumps deliveries.
    return UpdateOne({"_id": change["_id"]["_data"]},
                     {"$setOnInsert": doc, "$inc": {"deliveries": 1}, "$set": {"last_pod": pod}},
                     upsert=True)


def build_watch_kwargs(token: Optional[dict]) -> dict:
    kwargs: dict = {"max_await_time_ms": int(os.getenv("MAX_AWAIT_MS", "1000"))}
    full_document = os.getenv("FULL_DOCUMENT", "updateLookup")
    if full_document != "default":
        kwargs["full_document"] = full_document
    batch_size = os.getenv("CS_BATCH_SIZE")
    if batch_size:
        kwargs["batch_size"] = int(batch_size)
    if token:
        kwargs["resume_after"] = token
    return kwargs


def main() -> None:
    signal.signal(signal.SIGTERM, handle_sigterm)
    consumer_id = env("CONSUMER_ID", "orders-consumer")
    batch_limit = int(os.getenv("SINK_BATCH", "200"))
    pipeline = json.loads(os.getenv("PIPELINE_JSON", "[]"))
    pod = socket.gethostname()

    client = get_client(f"cs-consumer-{pod}")
    db = get_database(client)
    source = get_source(db)
    sink = db[SINK_COLLECTION]

    token = load_checkpoint(db, consumer_id)
    log_json(logger, "start", consumer_id=consumer_id, pod=pod, resume=bool(token),
             namespace=source.full_name, pipeline=pipeline)

    # Test-only fault injection: exit hard after a sink write but before the
    # checkpoint, so the next pod replays events that are already in the sink.
    fault_every = int(os.getenv("FAULT_EXIT_AFTER_WRITE", "0"))

    backoff = 1.0
    total = 0
    while not stopping:
        try:
            with source.watch(pipeline, **build_watch_kwargs(token)) as stream:
                log_json(logger, "stream_open", resume=bool(token))
                backoff = 1.0
                pending: list = []
                last_token = None
                while True:
                    change = None if stopping else stream.try_next()
                    if change is not None:
                        pending.append(to_sink(change, pod))
                        last_token = change["_id"]
                        if len(pending) < batch_limit:
                            continue
                    if pending:
                        sink.bulk_write(pending, ordered=False)
                        if fault_every and total + len(pending) >= fault_every:
                            log_json(logger, "fault_exit", total=total + len(pending))
                            os._exit(137)
                        save_checkpoint(db, consumer_id, last_token, len(pending))
                        token = last_token
                        total += len(pending)
                        log_json(logger, "commit", batch=len(pending), total=total)
                        pending = []
                    elif stopping:
                        break
                    elif stream.resume_token and stream.resume_token != token:
                        # Idle: advance the checkpoint to the post-batch resume token.
                        token = stream.resume_token
                        save_checkpoint(db, consumer_id, token, 0)
        except OperationFailure as error:
            log_json(logger, "operation_failure", code=error.code, error=str(error)[:500])
            if error.code in (280, 286):  # ChangeStreamFatalError, ChangeStreamHistoryLost
                raise
            # 26 NamespaceNotFound: the watched collection is missing (not created
            # yet, dropped or renamed). Observed instead of drop/invalidate events.
        except PyMongoError as error:
            log_json(logger, "stream_error", type=type(error).__name__, error=str(error)[:500])
        if not stopping:
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    log_json(logger, "stopped", total=total)
    client.close()


if __name__ == "__main__":
    main()
