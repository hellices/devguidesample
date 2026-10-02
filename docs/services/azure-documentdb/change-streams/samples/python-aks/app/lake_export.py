"""Export change stream events to Parquet files in ADLS Gen2.

One run is one Airflow task: resume from the checkpoint, read the events
written before the run started (or up to a limit), write Parquet chunks of a
fixed size and move the checkpoint after every uploaded chunk.

A chunk is named after the resume token that precedes its first event. A retry
starts from the same checkpoint, reads the same events in the same order and
overwrites the same file with the same or a longer chunk, so a crash between
the upload and the checkpoint does not leave duplicate rows. The first run
saves its start time before reading, so its retry starts at the same place.

A run holds a lease on a lock file next to the checkpoint, so two runs never
write chunks for the same stream at the same time.
"""

import hashlib
import io
import logging
import os
import socket
import threading
import time
from typing import Optional

import pyarrow as pa
import pyarrow.parquet as pq
from azure.core import MatchConditions
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.filedatalake import DataLakeServiceClient
from bson import json_util
from bson.timestamp import Timestamp

from common import env, get_client, get_database, get_source, log_json, setup_logging, utcnow

logger = setup_logging()
# The storage SDK logs every HTTP request at INFO.
logging.getLogger("azure").setLevel(logging.WARNING)

SCHEMA = pa.schema([
    ("resume_token", pa.string()),
    ("op", pa.string()),
    ("doc_id", pa.string()),
    ("ns", pa.string()),
    ("wall_time", pa.timestamp("ms", tz="UTC")),
    ("read_at", pa.timestamp("us", tz="UTC")),
    ("full_document", pa.string()),
])


class Checkpoint:
    """Stream position stored next to the data, updated with an ETag condition.

    The position is a resume token, or the start time saved by the first run.
    """

    def __init__(self, fs, stream_id: str):
        self.file = fs.get_file_client(f"_checkpoints/{stream_id}.json")
        self.etag: Optional[str] = None

    def load(self) -> Optional[dict]:
        try:
            download = self.file.download_file()
        except ResourceNotFoundError:
            return None
        self.etag = download.properties.etag
        return json_util.loads(download.readall())

    def save(self, token: Optional[dict], events: int, start_at: Optional[Timestamp] = None) -> None:
        body = json_util.dumps({"token": token, "start_at": start_at, "updated_at": utcnow(),
                                "events": events, "pod": socket.gethostname()})
        # IfNotModified fails if another run moved the checkpoint since we read it.
        condition = (dict(etag=self.etag, match_condition=MatchConditions.IfNotModified)
                     if self.etag else dict(match_condition=MatchConditions.IfMissing))
        result = self.file.upload_data(body, overwrite=True, **condition)
        self.etag = result["etag"]


class StreamLock:
    """Lease on ``_checkpoints/<stream>.lock`` held for the whole run.

    The lease is short and renewed in the background. A lease left by a killed
    pod expires, but Blob Storage can take up to a minute to grant a new one,
    so acquiring waits that long before the task fails.
    """

    DURATION_S = 20
    ACQUIRE_WAIT_S = 90

    def __init__(self, fs, stream_id: str):
        self.file = fs.get_file_client(f"_checkpoints/{stream_id}.lock")
        self.lease = None
        self.lost: Optional[Exception] = None
        self.stopped = threading.Event()

    def acquire(self) -> None:
        try:
            self.file.create_file(match_condition=MatchConditions.IfMissing)
        except HttpResponseError as error:
            if error.status_code != 409:
                raise
        deadline = time.monotonic() + self.ACQUIRE_WAIT_S
        while True:
            try:
                self.lease = self.file.acquire_lease(lease_duration=self.DURATION_S)
                break
            except HttpResponseError as error:
                # 409 while another run holds the lease.
                if error.status_code != 409 or time.monotonic() >= deadline:
                    raise
                time.sleep(5)
        threading.Thread(target=self._renew, daemon=True).start()

    def _renew(self) -> None:
        while not self.stopped.wait(self.DURATION_S / 4):
            try:
                self.lease.renew()
            except Exception as error:  # noqa: BLE001 - any failure means the lease may be gone
                self.lost = error
                return

    def check(self) -> None:
        """Call before every write; stop instead of writing without the lease."""
        if self.lost:
            raise RuntimeError(f"stream lease lost: {self.lost}")

    def release(self) -> None:
        self.stopped.set()
        if self.lease and not self.lost:
            self.lease.release()


def to_row(change: dict) -> dict:
    full = change.get("fullDocument")
    return {
        "resume_token": change["_id"]["_data"],
        "op": change["operationType"],
        "doc_id": str(change.get("documentKey", {}).get("_id")),
        "ns": f"{change['ns']['db']}.{change['ns']['coll']}",
        "wall_time": change.get("wallTime"),
        "read_at": utcnow(),
        "full_document": json_util.dumps(full, json_options=json_util.RELAXED_JSON_OPTIONS)
        if full is not None else None,
    }


def chunk_path(prefix: str, start: dict, rows: list) -> str:
    """Path from the chunk start position only, so a retry rewrites the same file."""
    key = start["token"]["_data"] if start.get("token") else f"start-{start['start_at']}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    first = rows[0]["wall_time"]
    # Without wallTime the read time would move the file on a later retry.
    partition = f"dt={first:%Y-%m-%d}/hour={first:%H}" if first else "dt=unknown"
    return f"{prefix}/{partition}/part-{digest}.parquet"


def write_chunk(fs, path: str, rows: list) -> int:
    table = pa.Table.from_pylist(rows, schema=SCHEMA)
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    data = buffer.getvalue()
    fs.get_file_client(path).upload_data(data, overwrite=True)
    return len(data)


def main() -> None:
    stream_id = env("STREAM_ID", "orders")
    prefix = env("LAKE_PREFIX", "orders")
    chunk_events = int(os.getenv("CHUNK_EVENTS", "100000"))
    max_events = int(os.getenv("MAX_EVENTS", "0"))  # 0 = until caught up
    max_seconds = float(os.getenv("MAX_SECONDS", "0"))
    # Test-only: exit after uploading this many chunks, before the checkpoint.
    fault_after_chunks = int(os.getenv("FAULT_EXIT_AFTER_UPLOAD", "0"))

    service = DataLakeServiceClient(env("LAKE_URL"), credential=DefaultAzureCredential())
    fs = service.get_file_system_client(env("LAKE_FILESYSTEM", "cdc"))
    lock = StreamLock(fs, stream_id)
    lock.acquire()
    checkpoint = Checkpoint(fs, stream_id)
    position = checkpoint.load()
    if position is None:
        # First run: save the start time before reading, so a retry after a
        # failed first chunk reads the same events instead of starting later.
        position = {"token": None, "start_at": Timestamp(int(time.time()), 0)}
        checkpoint.save(None, 0, start_at=position["start_at"])
    token = position.get("token")

    client = get_client(f"cs-lake-export-{socket.gethostname()}")
    source = get_source(get_database(client))
    kwargs: dict = {"batch_size": int(os.getenv("CS_BATCH_SIZE", "1000"))}
    # The cluster applies maxAwaitTimeMS as a hard limit on getMore. Reading a
    # backlog older than the active change log can take several seconds per
    # getMore and then fails with ExceededTimeLimit, so leave it unset by
    # default. An idle getMore still returns after about one second.
    max_await_ms = int(os.getenv("MAX_AWAIT_MS", "0"))
    if max_await_ms:
        kwargs["max_await_time_ms"] = max_await_ms
    if token:
        kwargs["resume_after"] = token
    else:
        kwargs["start_at_operation_time"] = position["start_at"]

    started = time.monotonic()
    run_started_at = utcnow()
    log_json(logger, "export_start", stream_id=stream_id, resume=bool(token), chunk_events=chunk_events)
    total = chunks = written_bytes = 0
    caught_up = False
    with source.watch(**kwargs) as stream:
        rows: list = []
        chunk_start = position
        last_token = token
        while True:
            change = stream.try_next()
            if change is not None:
                rows.append(to_row(change))
                last_token = change["_id"]
                # Under steady load try_next rarely returns None, so stop once
                # the stream reaches events written after this run started.
                wall_time = change.get("wallTime")
                caught_up = wall_time is not None and wall_time >= run_started_at
            else:
                caught_up = True
            full = len(rows) >= chunk_events
            limit = (max_events and total + len(rows) >= max_events) or \
                    (max_seconds and time.monotonic() - started >= max_seconds)
            if rows and (full or caught_up or limit):
                path = chunk_path(prefix, chunk_start, rows)
                lock.check()
                size = write_chunk(fs, path, rows)
                chunks += 1
                if fault_after_chunks and chunks >= fault_after_chunks:
                    log_json(logger, "fault_exit", chunks=chunks, path=path)
                    os._exit(137)
                lock.check()
                checkpoint.save(last_token, len(rows))
                total += len(rows)
                written_bytes += size
                log_json(logger, "chunk", path=path, rows=len(rows), bytes=size, total=total)
                rows = []
                chunk_start = {"token": last_token}
            if caught_up or limit:
                break
        # Nothing new: move the checkpoint to the post-batch resume token so
        # the next run does not scan the same idle range again.
        if total == 0 and stream.resume_token and stream.resume_token != token:
            lock.check()
            checkpoint.save(stream.resume_token, 0)

    lock.release()
    log_json(logger, "export_done", events=total, chunks=chunks, bytes=written_bytes,
             caught_up=caught_up, elapsed_s=round(time.monotonic() - started, 2))
    client.close()


if __name__ == "__main__":
    main()
