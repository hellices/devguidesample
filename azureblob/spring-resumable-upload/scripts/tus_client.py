#!/usr/bin/env python3
"""
tus.io 1.0.0 client — mobile-style resumable upload simulator.

Flow per upload:
    1. POST /files (Upload-Length, Upload-Metadata)         → Location: /files/{id}
    2. HEAD /files/{id}                                      → Upload-Offset
    3. PATCH /files/{id} (Upload-Offset, body=chunk) × N    → 204 + new Upload-Offset
    4. (last PATCH triggers server-side commitBlockList)

The client retries any PATCH failure by re-issuing HEAD and resuming from the
server's authoritative offset — that's exactly what TUSKit / tus-android-client
do under the hood. Demonstrates that server is truly stateless across both
client interruption and server restart.

Subcommands
-----------
    upload   — create (or resume) and stream the file
    head     — print Upload-Offset / Upload-Length of an upload id
    delete   — abort an upload

Examples
--------
    python tus_client.py upload --file test-50mb.bin
    python tus_client.py upload --file test-50mb.bin --id <uuid>            # resume
    python tus_client.py upload --file test-50mb.bin --stop-after 4         # stop mid-upload
    python tus_client.py upload --file test-50mb.bin --fail-on-patch 3      # inject one fault
    python tus_client.py head --id <uuid>
    python tus_client.py delete --id <uuid>
"""
import argparse
import base64
import math
import os
import sys
import time
from urllib.parse import urlparse, urlsplit

import requests

TUS_VERSION = "1.0.0"
DEFAULT_SERVER = os.environ.get("UPLOAD_SERVER", "http://localhost:8080")
DEFAULT_CHUNK = 1 * 1024 * 1024  # 1 MiB (cellular-friendly; tunable via --chunk-size)
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _headers(extra=None):
    h = {"Tus-Resumable": TUS_VERSION}
    if extra:
        h.update(extra)
    return h


def _encode_metadata(pairs):
    parts = []
    for k, v in pairs.items():
        b64 = base64.b64encode(v.encode("utf-8")).decode("ascii")
        parts.append(f"{k} {b64}")
    return ",".join(parts)


def create(server, total, metadata):
    r = requests.post(
        f"{server}/files",
        headers=_headers({
            "Upload-Length": str(total),
            "Upload-Metadata": _encode_metadata(metadata),
        }),
        timeout=30,
    )
    if r.status_code != 201:
        r.raise_for_status()
    loc = r.headers["Location"]
    parsed = urlsplit(loc)
    upload_id = parsed.path.rsplit("/", 1)[-1]
    return upload_id


def head(server, upload_id):
    r = requests.head(
        f"{server}/files/{upload_id}",
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return int(r.headers["Upload-Offset"]), int(r.headers["Upload-Length"])


def patch(server, upload_id, offset, data):
    r = requests.patch(
        f"{server}/files/{upload_id}",
        headers=_headers({
            "Upload-Offset": str(offset),
            "Content-Type": "application/offset+octet-stream",
            "Content-Length": str(len(data)),
        }),
        data=data,
        timeout=120,
    )
    if r.status_code != 204:
        if r.status_code in RETRYABLE_STATUS:
            raise TransientError(f"HTTP {r.status_code}")
        r.raise_for_status()
    return int(r.headers["Upload-Offset"])


def delete(server, upload_id):
    r = requests.delete(
        f"{server}/files/{upload_id}",
        headers=_headers(),
        timeout=30,
    )
    if r.status_code not in (204, 404):
        r.raise_for_status()


class TransientError(Exception):
    pass


class InjectedFault(TransientError):
    pass


def cmd_upload(args):
    file_size = os.path.getsize(args.file)
    chunk_size = args.chunk_size
    total_chunks = math.ceil(file_size / chunk_size) if file_size else 0

    if args.id:
        upload_id = args.id
        print(f"resume: id={upload_id}")
    else:
        upload_id = create(
            args.server,
            file_size,
            {"filename": os.path.basename(args.file)},
        )
        print(f"created: id={upload_id}")

    server_offset, server_length = head(args.server, upload_id)
    if server_length != file_size:
        print(f"FATAL: server Upload-Length={server_length} != local size={file_size}",
              file=sys.stderr)
        sys.exit(2)
    print(f"server offset={server_offset}/{server_length} "
          f"({server_offset / server_length * 100 if server_length else 0:.1f}%)")

    patches_sent = 0
    patches_attempted = 0

    with open(args.file, "rb") as f:
        while server_offset < file_size:
            f.seek(server_offset)
            chunk = f.read(chunk_size)
            patches_attempted += 1

            try:
                if args.fail_on_patch and patches_attempted == args.fail_on_patch:
                    print(f"  PATCH #{patches_attempted} offset={server_offset}: "
                          f"INJECTED FAULT (chunk not sent)")
                    raise InjectedFault("fail-on-patch")
                new_offset = _patch_with_retry(args.server, upload_id, server_offset, chunk)
                patches_sent += 1
                print(f"  PATCH #{patches_attempted} offset={server_offset} "
                      f"size={len(chunk)} -> new_offset={new_offset}")
                server_offset = new_offset
            except TransientError as e:
                # Re-sync with server: HEAD to learn authoritative offset, then continue.
                print(f"  PATCH failed ({e}), HEAD to re-sync")
                server_offset, _ = head(args.server, upload_id)
                print(f"  server says offset={server_offset}, resuming")

            if args.stop_after and patches_sent >= args.stop_after:
                print(f"stop-after {args.stop_after} reached, exiting")
                print(f"to resume: --id {upload_id}")
                return

    print(f"done: sent {patches_sent} chunk(s) over {patches_attempted} attempt(s)")
    final_offset, _ = head(args.server, upload_id)
    if final_offset != file_size:
        print(f"FATAL: final offset {final_offset} != file size {file_size}", file=sys.stderr)
        sys.exit(2)
    print(f"committed blob id={upload_id} size={final_offset}")


def _patch_with_retry(server, upload_id, offset, data, max_retries=3):
    backoff = 0.5
    for attempt in range(1, max_retries + 1):
        try:
            return patch(server, upload_id, offset, data)
        except requests.RequestException as e:
            if attempt == max_retries:
                raise TransientError(f"network: {e}") from e
            print(f"    transport error attempt {attempt}: {e}")
            time.sleep(backoff)
            backoff *= 2


def cmd_head(args):
    offset, length = head(args.server, args.id)
    print(f"id={args.id} offset={offset} length={length} "
          f"progress={offset / length * 100 if length else 0:.1f}%")


def cmd_delete(args):
    delete(args.server, args.id)
    print(f"deleted id={args.id}")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", default=DEFAULT_SERVER)
    sub = p.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upload")
    up.add_argument("--file", required=True)
    up.add_argument("--id", default=None, help="existing upload id (resume)")
    up.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK)
    up.add_argument("--stop-after", type=int, default=None,
                    help="exit after N successful PATCHes (simulates interruption)")
    up.add_argument("--fail-on-patch", type=int, default=None,
                    help="inject one fault on the Nth PATCH attempt")
    up.set_defaults(func=cmd_upload)

    hd = sub.add_parser("head")
    hd.add_argument("--id", required=True)
    hd.set_defaults(func=cmd_head)

    dl = sub.add_parser("delete")
    dl.add_argument("--id", required=True)
    dl.set_defaults(func=cmd_delete)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
