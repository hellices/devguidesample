#!/usr/bin/env python3
import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from capture_model import normalize_capture, redact


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def build_snapshot(
    *,
    captured_at: str,
    source_file: str,
    threads: list[dict[str, Any]],
    thread: Any,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a snapshot that is safe to persist and normalize."""
    return redact(
        {
            "captured_at": captured_at,
            "source_file": source_file,
            "threads": threads,
            "thread": thread,
            "messages": messages,
        }
    )


def run_json(command: list[str]) -> Any:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def get_token() -> str:
    completed = subprocess.run(
        [
            "az",
            "account",
            "get-access-token",
            "--resource",
            "https://azuresre.dev",
            "--query",
            "accessToken",
            "-o",
            "tsv",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def data_plane_get(endpoint: str, path: str, token: str) -> Any:
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise RuntimeError(f"SRE Agent data-plane RBAC failure: HTTP {exc.code}")
        if exc.code == 429 or exc.code >= 500:
            retry_after = int(exc.headers.get("Retry-After", "10"))
            raise TransientApiError(retry_after, exc.code)
        raise


class TransientApiError(RuntimeError):
    def __init__(self, retry_after: int, status_code: int):
        super().__init__(f"Transient API failure: HTTP {status_code}")
        self.retry_after = max(1, min(retry_after, 60))


def list_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("value", "items", "threads", "messages"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def thread_id(thread: dict[str, Any]) -> str:
    return str(thread.get("id", thread.get("threadId", "")))


def thread_matches(thread: dict[str, Any], alert_title: str, scenario: str) -> bool:
    searchable = json.dumps(redact(thread), sort_keys=True).lower()
    scenario_marker = f"[sre-lab-{scenario[1:]}]".lower()
    return alert_title.lower() in searchable or scenario_marker in searchable


def has_conclusion(timeline: list[dict[str, Any]]) -> bool:
    return any(event["state"] == "conclusion" for event in timeline)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture Azure SRE Agent incident evidence")
    parser.add_argument("--scenario", required=True, choices=("s1", "s2", "s3"))
    parser.add_argument("--alert-id", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--thread-id")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args(argv)
    if not 60 <= args.timeout <= 3600:
        parser.error("--timeout must be between 60 and 3600 seconds")
    if not 5 <= args.interval <= 60:
        parser.error("--interval must be between 5 and 60 seconds")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output_dir = args.output_dir
    snapshot_dir = output_dir / "thread-snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    alert_url = args.alert_id
    separator = "&" if "?" in alert_url else "?"
    if "api-version=" not in alert_url:
        alert_url = f"{alert_url}{separator}api-version=2019-03-01"
    alert = run_json(["az", "rest", "--method", "get", "--url", alert_url])
    atomic_json(output_dir / "alert.json", alert)
    alert_title = (
        alert.get("properties", {})
        .get("essentials", {})
        .get("alertRule", args.scenario)
    )

    snapshots = []
    token = get_token()
    token_acquired_at = time.monotonic()
    deadline = time.monotonic() + args.timeout
    sequence = 0

    while time.monotonic() < deadline:
        if time.monotonic() - token_acquired_at > 300:
            token = get_token()
            token_acquired_at = time.monotonic()
        try:
            threads_payload = data_plane_get(args.endpoint, "/api/v1/threads", token)
            available_threads = list_items(threads_payload)
            threads = []
            messages: Any = []
            thread_payload: Any = {}
            candidates = (
                [
                    item
                    for item in available_threads
                    if thread_id(item) == args.thread_id
                ]
                if args.thread_id
                else list(reversed(available_threads))
            )
            for candidate in candidates:
                selected_id = thread_id(candidate)
                if not selected_id:
                    continue
                candidate_thread = data_plane_get(
                    args.endpoint, f"/api/v1/threads/{selected_id}", token
                )
                candidate_messages = data_plane_get(
                    args.endpoint,
                    f"/api/v1/threads/{selected_id}/messages",
                    token,
                )
                searchable = {
                    "thread": candidate_thread,
                    "messages": list_items(candidate_messages),
                }
                if args.thread_id or thread_matches(
                    searchable, alert_title, args.scenario
                ):
                    threads = [candidate_thread]
                    thread_payload = candidate_thread
                    messages = candidate_messages
                    break
            sequence += 1
            source_file = f"thread-snapshots/{sequence:04d}.json"
            snapshot = build_snapshot(
                captured_at=utc_now(),
                source_file=source_file,
                threads=threads,
                thread=thread_payload,
                messages=list_items(messages),
            )
            atomic_json(output_dir / source_file, snapshot)
            snapshots.append(snapshot)
            timeline = normalize_capture(alert, snapshots)
            atomic_json(output_dir / "normalized-timeline.json", timeline)
            if has_conclusion(timeline):
                return 0
            time.sleep(args.interval)
        except TransientApiError as exc:
            time.sleep(exc.retry_after)

    timeline = normalize_capture(alert, snapshots)
    atomic_json(output_dir / "normalized-timeline.json", timeline)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
