"""Export change stream events to Parquet files in ADLS Gen2.

One run is one Airflow task: resume from the checkpoint, read the events of
the time windows that closed before the run started (or up to a limit), write
Parquet chunks and move the checkpoint after every uploaded chunk.

Events are grouped by ``wallTime`` into windows of ``WINDOW_MINUTES``. A chunk
holds events of one window and ends at the window boundary or before its rows
pass ``CHUNK_BYTES``. Both cut points depend only on the events, so a retry
cuts the same chunks. The run never writes the window that is still open, so
one window is not spread over several runs.

A chunk is named after the resume token that precedes its first event. A retry
starts from the same checkpoint, reads the same events in the same order and
overwrites the same file with the same chunk, so a crash between the upload
and the checkpoint does not leave duplicate rows. The first run saves its
start time before reading, so its retry starts at the same place.

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
# Rows are moved into Arrow every BATCH_ROWS rows. A large chunk then holds
# the column data once instead of as Python objects plus an Arrow copy.
BATCH_ROWS = 10_000


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


def row_bytes(row: dict) -> int:
    """Plain-encoded size of a row: string bytes plus a 4-byte length each,
    and 8 bytes per timestamp. ``read_at`` changes on a retry but its size
    does not, so the same events always give the same size."""
    size = 16
    for column in ("resume_token", "op", "doc_id", "ns", "full_document"):
        if row[column] is not None:
            size += len(row[column].encode()) + 4
    return size


def window_start(wall_time, minutes: int):
    if wall_time is None:
        return None
    return wall_time.replace(minute=wall_time.minute - wall_time.minute % minutes,
                             second=0, microsecond=0)


def chunk_path(prefix: str, start: dict, window) -> str:
    """Path from the chunk start position and window only, so a retry
    rewrites the same file."""
    key = start["token"]["_data"] if start.get("token") else f"start-{start['start_at']}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    # Without wallTime the read time would move the file on a later retry.
    if window is None:
        return f"{prefix}/dt=unknown/part-{digest}.parquet"
    return f"{prefix}/dt={window:%Y-%m-%d}/hour={window:%H}/part-{window:%Y%m%dT%H%M}-{digest}.parquet"


class Chunk:
    """Rows of one window, started after the position in ``start``."""

    def __init__(self, start: dict):
        self.start = start
        self.batches: list = []
        self.pending: list = []
        self.count = 0
        self.size = 0
        self.window = None
        self.end_token: Optional[dict] = None

    def fits(self, size: int, window, max_bytes: int) -> bool:
        if not self.count:
            return True
        # None (no wallTime) is its own window, kept apart from dated ones.
        if window != self.window:
            return False
        return self.size + size <= max_bytes

    def add(self, row: dict, size: int, window, token: dict) -> None:
        if not self.count:
            self.window = window
        self.pending.append(row)
        self.count += 1
        self.size += size
        self.end_token = token
        if len(self.pending) >= BATCH_ROWS:
            self.batches.append(pa.RecordBatch.from_pylist(self.pending, schema=SCHEMA))
            self.pending = []

    def table(self) -> pa.Table:
        if self.pending:
            self.batches.append(pa.RecordBatch.from_pylist(self.pending, schema=SCHEMA))
            self.pending = []
        return pa.Table.from_batches(self.batches, schema=SCHEMA)


def write_chunk(fs, path: str, table: pa.Table) -> int:
    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    size = buffer.tell()
    # Upload from the buffer itself instead of a bytes copy of the file.
    buffer.seek(0)
    fs.get_file_client(path).upload_data(buffer, length=size, overwrite=True)
    return size


def publish(fs, lock: StreamLock, checkpoint: Checkpoint, prefix: str, chunk: Chunk, fault: bool) -> int:
    """Upload the chunk, then move the checkpoint past its last event."""
    path = chunk_path(prefix, chunk.start, chunk.window)
    lock.check()
    size = write_chunk(fs, path, chunk.table())
    if fault:
        log_json(logger, "fault_exit", path=path)
        os._exit(137)
    lock.check()
    checkpoint.save(chunk.end_token, chunk.count)
    log_json(logger, "chunk", path=path, rows=chunk.count, row_bytes=chunk.size, bytes=size)
    return size


def main() -> None:
    stream_id = env("STREAM_ID", "orders")
    prefix = env("LAKE_PREFIX", "orders")
    window_minutes = int(os.getenv("WINDOW_MINUTES", "10"))
    if window_minutes <= 0 or 60 % window_minutes:
        raise SystemExit("WINDOW_MINUTES must divide 60")
    chunk_bytes = int(os.getenv("CHUNK_BYTES", str(80_000_000)))
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
    # Events from the start of the open window on belong to a later run.
    cutoff = window_start(utcnow(), window_minutes)
    log_json(logger, "export_start", stream_id=stream_id, resume=bool(token), cutoff=cutoff,
             window_minutes=window_minutes, chunk_bytes=chunk_bytes)
    total = chunks = written_bytes = 0
    caught_up = read_any = False
    with source.watch(**kwargs) as stream:
        chunk = Chunk(position)
        while True:
            change = stream.try_next()
            if change is None:
                # Every buffered row is older than the open window.
                caught_up = True
            else:
                read_any = True
                wall_time = change.get("wallTime")
                # Under steady load try_next rarely returns None, so stop at
                # the first event of the open window. The next run reads it.
                caught_up = wall_time is not None and wall_time >= cutoff
            if change is not None and not caught_up:
                row = to_row(change)
                size = row_bytes(row)
                window = window_start(wall_time, window_minutes)
                if not chunk.fits(size, window, chunk_bytes):
                    chunks += 1
                    written_bytes += publish(fs, lock, checkpoint, prefix, chunk,
                                             fault_after_chunks and chunks >= fault_after_chunks)
                    total += chunk.count
                    chunk = Chunk({"token": chunk.end_token})
                chunk.add(row, size, window, change["_id"])
            limit = (max_events and total + chunk.count >= max_events) or \
                    (max_seconds and time.monotonic() - started >= max_seconds)
            if caught_up or limit:
                if chunk.count:
                    chunks += 1
                    written_bytes += publish(fs, lock, checkpoint, prefix, chunk,
                                             fault_after_chunks and chunks >= fault_after_chunks)
                    total += chunk.count
                break
        # Nothing to read: move the checkpoint to the post-batch resume token
        # so the next run does not scan the same idle range again. Skip it
        # when an event of the open window was read, or that event is lost.
        if not read_any and stream.resume_token and stream.resume_token != token:
            lock.check()
            checkpoint.save(stream.resume_token, 0)

    lock.release()
    log_json(logger, "export_done", events=total, chunks=chunks, bytes=written_bytes,
             caught_up=caught_up, elapsed_s=round(time.monotonic() - started, 2))
    client.close()


if __name__ == "__main__":
    main()
