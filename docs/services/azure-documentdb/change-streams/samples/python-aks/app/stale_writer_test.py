"""Check that a run that lost the stream lease cannot overwrite a newer chunk.

Run A (this process) stops before its first Parquet upload, stops renewing
the stream lease and starts run B as a subprocess. B waits for the lease,
writes a shorter first chunk (``B_MAX_EVENTS``) to the same file and moves the
checkpoint. Then A goes on. The check passes when the file still holds B's
chunk, so its last resume token is the one in the checkpoint.

``STALL_AT=upload`` (default) stops A after it leased the file, right before
the upload. ``STALL_AT=lease`` stops A before it leases the file.

Needs unread events in a closed window, more than ``B_MAX_EVENTS``. Runs with
the same environment as ``lake_export.py``.
"""

import io
import json
import os
import subprocess
import sys

import pyarrow.parquet as pq
from azure.storage.filedatalake import DataLakeFileClient

import lake_export

locks = []
held: dict = {}
acquire = lake_export.StreamLock.acquire
upload_data = DataLakeFileClient.upload_data


def acquire_and_keep(self):
    acquire(self)
    locks.append(self)


lease_file = getattr(lake_export, "lease_file", None)


def run_b(path: str) -> None:
    held["path"] = path
    # The stream lease expires about 20 seconds after the last renewal.
    locks[0].stopped.set()
    env = dict(os.environ, MAX_EVENTS=os.getenv("B_MAX_EVENTS", "1000"))
    b = subprocess.run([sys.executable, "lake_export.py"], env=env, capture_output=True, text=True)
    held["b_exit"] = b.returncode
    held["b_log"] = [line for line in b.stdout.splitlines() + b.stderr.splitlines()
                     if '"event"' in line or "Error" in line][-8:]


def upload_after_b(self, data, *args, **kwargs):
    if self.path_name.endswith(".parquet") and not held:
        run_b(self.path_name)
    return upload_data(self, data, *args, **kwargs)


def lease_after_b(file, *args, **kwargs):
    if not held:
        run_b(file.path_name)
    return lease_file(file, *args, **kwargs)


def main() -> None:
    lake_export.StreamLock.acquire = acquire_and_keep
    if os.getenv("STALL_AT", "upload") == "lease":
        lake_export.lease_file = lease_after_b
    else:
        DataLakeFileClient.upload_data = upload_after_b
    try:
        lake_export.main()
        a_error = None
    except Exception as error:  # noqa: BLE001 - A is expected to fail
        a_error = f"{type(error).__name__}: {str(error).splitlines()[0]}"
    DataLakeFileClient.upload_data = upload_data
    if "path" not in held:
        raise SystemExit("run A wrote no chunk; write more events in a closed window first")

    fs, blobs = lake_export.get_storage_clients()
    data = fs.get_file_client(held["path"]).download_file().readall()
    tokens = pq.read_table(io.BytesIO(data), columns=["resume_token"]).column("resume_token").to_pylist()
    checkpoint = lake_export.Checkpoint(
        fs,
        blobs,
        lake_export.env("STREAM_ID", "orders"),
    ).load()
    ok = held["b_exit"] == 0 and tokens[-1] == checkpoint["token"]["_data"]
    print(json.dumps({"result": "pass" if ok else "fail", "path": held["path"], "file_rows": len(tokens),
                      "file_ends_at_checkpoint": tokens[-1] == checkpoint["token"]["_data"],
                      "checkpoint_events": checkpoint["events"], "a_error": a_error,
                      "b_exit": held["b_exit"], "b_log": held["b_log"]}, default=str))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
