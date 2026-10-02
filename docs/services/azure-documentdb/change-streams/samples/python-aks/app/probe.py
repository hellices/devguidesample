"""Probe which change stream options Azure DocumentDB accepts through PyMongo.

Each check runs against its own collection and reports PASS, FAIL or an
observed value. Nothing here asserts documented behavior; it records what the
cluster under test actually returned.
"""

import json
import time
from datetime import timedelta
from typing import Any, Callable, Optional

import pymongo
from bson import Timestamp
from pymongo.errors import OperationFailure, PyMongoError

from common import get_client, get_database, utcnow

client = get_client("cs-probe")
db = get_database(client)
results: list = []
WAIT_S = 15


def record(name: str, status: str, **detail: Any) -> None:
    item = {"check": name, "status": status, **detail}
    results.append(item)
    print(json.dumps(item, default=str), flush=True)


def fresh(name: str):
    coll = db[f"probe_{name}"]
    coll.drop()
    db.create_collection(coll.name)
    return coll


def next_event(stream, timeout: float = WAIT_S) -> Optional[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        change = stream.try_next()
        if change is not None:
            return change
    return None


def check(name: str) -> Callable:
    def wrap(fn: Callable) -> Callable:
        try:
            fn()
        except OperationFailure as error:
            record(name, "FAIL", code=error.code, codeName=error.details.get("codeName") if error.details else None,
                   error=str(error)[:300])
        except PyMongoError as error:
            record(name, "FAIL", type=type(error).__name__, error=str(error)[:300])
        except Exception as error:  # noqa: BLE001 - probe must keep going
            record(name, "ERROR", type=type(error).__name__, error=str(error)[:300])
        return fn
    return wrap


@check("server_info")
def _server_info():
    info = client.admin.command("buildInfo")
    hello = client.admin.command("hello")
    record("server_info", "INFO", version=info.get("version"), pymongo=pymongo.version,
           maxWireVersion=hello.get("maxWireVersion"), setName=hello.get("setName"),
           msg=hello.get("msg"))


@check("event_shapes")
def _event_shapes():
    coll = fresh("shapes")
    with coll.watch(max_await_time_ms=500) as s:
        coll.insert_one({"_id": 1, "a": 1, "arr": [1, 2, 3]})
        coll.update_one({"_id": 1}, {"$set": {"a": 2}, "$unset": {"arr": ""}})
        coll.replace_one({"_id": 1}, {"a": 3})
        coll.delete_one({"_id": 1})
        shapes = {}
        for _ in range(4):
            e = next_event(s)
            if e is None:
                break
            shapes[e["operationType"]] = {
                "keys": sorted(e.keys()),
                "updateDescription": e.get("updateDescription"),
                "clusterTime_type": type(e.get("clusterTime")).__name__,
                "wallTime": e.get("wallTime"),
            }
    status = "PASS" if set(shapes) == {"insert", "update", "replace", "delete"} else "FAIL"
    record("event_shapes", status, shapes=shapes)


@check("update_full_document_default")
def _update_default():
    coll = fresh("upd_default")
    coll.insert_one({"_id": 1, "a": 1})
    with coll.watch(max_await_time_ms=500) as s:
        coll.update_one({"_id": 1}, {"$set": {"a": 2}})
        e = next_event(s)
    record("update_full_document_default", "INFO", has_fullDocument="fullDocument" in e,
           fullDocument=e.get("fullDocument"), updateDescription=e.get("updateDescription"))


for mode in ("updateLookup", "whenAvailable", "required"):
    @check(f"full_document={mode}")
    def _full_doc(mode=mode):
        coll = fresh(f"fd_{mode}")
        coll.insert_one({"_id": 1, "a": 1})
        with coll.watch(full_document=mode, max_await_time_ms=500) as s:
            coll.update_one({"_id": 1}, {"$set": {"a": 2}})
            e = next_event(s)
        record(f"full_document={mode}", "PASS" if e and e.get("fullDocument") else "FAIL",
               fullDocument=e.get("fullDocument") if e else None)


@check("pre_image_collmod")
def _pre_image_collmod():
    coll = fresh("preimage")
    db.command({"collMod": coll.name, "changeStreamPreAndPostImages": {"enabled": True}})
    record("pre_image_collmod", "PASS")


for mode in ("whenAvailable", "required"):
    @check(f"full_document_before_change={mode}")
    def _pre_image(mode=mode):
        coll = db["probe_preimage"]
        coll.delete_many({})
        coll.insert_one({"_id": mode, "a": 1})
        with coll.watch(full_document_before_change=mode, max_await_time_ms=500) as s:
            coll.update_one({"_id": mode}, {"$set": {"a": 2}})
            e = next_event(s)
        record(f"full_document_before_change={mode}",
               "PASS" if e and e.get("fullDocumentBeforeChange") else "FAIL",
               fullDocumentBeforeChange=e.get("fullDocumentBeforeChange") if e else None)


PIPELINES = {
    "$match": [{"$match": {"operationType": "insert", "fullDocument.dept": "IT"}}],
    "$project": [{"$project": {"operationType": 1, "fullDocument.name": 1, "ns": 1, "documentKey": 1}}],
    "$addFields": [{"$addFields": {"probe": "added"}}],
    "$set": [{"$set": {"probe": "set"}}],
    "$unset": [{"$unset": "fullDocument.dept"}],
    "$replaceRoot": [{"$replaceRoot": {"newRoot": {"_id": "$_id", "op": "$operationType"}}}],
    "$redact": [{"$redact": "$$KEEP"}],
}
for stage, pipeline in PIPELINES.items():
    @check(f"pipeline {stage}")
    def _pipeline(stage=stage, pipeline=pipeline):
        coll = fresh(f"pl_{stage[1:]}")
        with coll.watch(pipeline, max_await_time_ms=500) as s:
            coll.insert_one({"name": "x", "dept": "HR"})
            coll.insert_one({"name": "y", "dept": "IT"})
            events = [e for e in (next_event(s, 8), next_event(s, 3)) if e]
        record(f"pipeline {stage}", "PASS" if events else "FAIL", events=len(events),
               sample={k: v for k, v in events[0].items() if k != "_id"} if events else None)


@check("pipeline_update_updateDescription")
def _pipeline_update():
    coll = fresh("pipeline_update")
    coll.insert_one({"_id": 1, "a": 1})
    with coll.watch(max_await_time_ms=500) as s:
        coll.update_one({"_id": 1}, [{"$set": {"a": {"$add": ["$a", 1]}}}])
        e = next_event(s)
    record("pipeline_update_updateDescription", "INFO", operationType=e.get("operationType") if e else None,
           has_updateDescription=bool(e and "updateDescription" in e),
           updateDescription=e.get("updateDescription") if e else None)


@check("database_watch")
def _db_watch():
    coll = fresh("dbwatch")
    with db.watch(max_await_time_ms=500) as s:
        coll.insert_one({"a": 1})
        e = next_event(s)
    record("database_watch", "PASS" if e else "FAIL", ns=e.get("ns") if e else None)


@check("cluster_watch")
def _cluster_watch():
    coll = fresh("clusterwatch")
    with client.watch(max_await_time_ms=500) as s:
        coll.insert_one({"a": 1})
        e = next_event(s)
    record("cluster_watch", "PASS" if e else "FAIL", ns=e.get("ns") if e else None)


@check("resume_after")
def _resume_after():
    coll = fresh("resume")
    with coll.watch(max_await_time_ms=500) as s:
        coll.insert_one({"_id": 1})
        first = next_event(s)
    coll.insert_one({"_id": 2})
    coll.insert_one({"_id": 3})
    with coll.watch(resume_after=first["_id"], max_await_time_ms=500) as s:
        got = [next_event(s, 8), next_event(s, 8)]
    ids = [e["documentKey"]["_id"] for e in got if e]
    record("resume_after", "PASS" if ids == [2, 3] else "FAIL", resumed_ids=ids,
           token_sample=first["_id"])


@check("start_after")
def _start_after():
    coll = fresh("startafter")
    with coll.watch(max_await_time_ms=500) as s:
        coll.insert_one({"_id": 1})
        first = next_event(s)
    coll.insert_one({"_id": 2})
    with coll.watch(start_after=first["_id"], max_await_time_ms=500) as s:
        e = next_event(s, 8)
    record("start_after", "PASS" if e and e["documentKey"]["_id"] == 2 else "FAIL",
           got=e["documentKey"] if e else None)


@check("start_at_operation_time")
def _start_at_op_time():
    coll = fresh("optime")
    with client.start_session() as session:
        coll.insert_one({"_id": 1}, session=session)
        op_time = session.operation_time
    coll.insert_one({"_id": 2})
    with coll.watch(start_at_operation_time=op_time, max_await_time_ms=500) as s:
        got = [next_event(s, 8), next_event(s, 8)]
    ids = [e["documentKey"]["_id"] for e in got if e]
    record("start_at_operation_time", "PASS" if 2 in ids else "FAIL", operation_time=op_time, ids=ids)


@check("start_at_operation_time_minus_10m")
def _historical():
    coll = db["probe_optime"]
    past = Timestamp(int((utcnow() - timedelta(minutes=10)).timestamp()), 1)
    with coll.watch(start_at_operation_time=past, max_await_time_ms=500) as s:
        e = next_event(s, 8)
    record("start_at_operation_time_minus_10m", "PASS" if e else "INFO", first=e.get("documentKey") if e else None)


@check("invalid_resume_token")
def _invalid_token():
    coll = fresh("badtoken")
    with coll.watch(resume_after={"_data": "AAAAAAAAAAAA"}, max_await_time_ms=500) as s:
        coll.insert_one({"a": 1})
        e = next_event(s, 5)
    record("invalid_resume_token", "INFO", note="stream opened with bogus token", got=bool(e))


@check("show_expanded_events")
def _expanded():
    coll = fresh("expanded")
    with coll.watch(show_expanded_events=True, max_await_time_ms=500) as s:
        coll.insert_one({"a": 1})
        e = next_event(s, 5)
    record("show_expanded_events", "INFO", note="accepted", got=bool(e))


@check("post_batch_resume_token_idle")
def _pbrt():
    coll = fresh("pbrt")
    with coll.watch(max_await_time_ms=500) as s:
        before = s.resume_token
        s.try_next()
        time.sleep(1)
        s.try_next()
        after = s.resume_token
    record("post_batch_resume_token_idle", "PASS" if after else "FAIL", before=before, after=after,
           advanced=before != after)


@check("transaction_events")
def _txn():
    coll = fresh("txn")
    with coll.watch(max_await_time_ms=500) as s:
        with client.start_session() as session:
            with session.start_transaction():
                coll.insert_one({"_id": 1}, session=session)
                coll.insert_one({"_id": 2}, session=session)
        got = [next_event(s, 8), next_event(s, 8)]
    got = [e for e in got if e]
    record("transaction_events", "PASS" if len(got) == 2 else "FAIL", events=len(got),
           txn_fields={k: str(got[0].get(k)) for k in ("lsid", "txnNumber") if got and k in got[0]})


@check("drop_and_invalidate")
def _drop():
    coll = fresh("drop")
    with coll.watch(max_await_time_ms=500) as s:
        coll.insert_one({"a": 1})
        coll.drop()
        ops = []
        for _ in range(3):
            e = next_event(s, 6)
            if e is None:
                break
            ops.append(e["operationType"])
        alive = s.alive
    record("drop_and_invalidate", "INFO", ops=ops, stream_alive_after=alive)


@check("rename")
def _rename():
    coll = fresh("rename")
    db["probe_renamed"].drop()
    with coll.watch(max_await_time_ms=500) as s:
        coll.rename("probe_renamed")
        e = next_event(s, 6)
    record("rename", "INFO", op=e.get("operationType") if e else None, to=e.get("to") if e else None)


@check("large_document_event")
def _large():
    coll = fresh("large")
    payload = "x" * (7 * 1024 * 1024)  # doc 14 MiB; event with updateDescription exceeds 16 MiB
    with coll.watch(full_document="updateLookup", max_await_time_ms=500) as s:
        coll.insert_one({"_id": 1, "blob": payload})
        coll.update_one({"_id": 1}, {"$set": {"blob2": payload}})
        got = [next_event(s, 15), next_event(s, 15)]
    record("large_document_event", "INFO", ops=[e["operationType"] if e else None for e in got])


print(json.dumps({"summary": {r["check"]: r["status"] for r in results}}, indent=2))
client.close()
