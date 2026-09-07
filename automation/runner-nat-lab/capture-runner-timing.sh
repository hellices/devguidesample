#!/usr/bin/env bash
set -euo pipefail
python3 - "$@" <<'PY'
import argparse
import collections
import datetime
import json
import pathlib
import re
import urllib.parse

HEADER = re.compile(r"^\[([0-9-]+ [0-9:.]+Z) \w+ ([^\]]+)\] (.*)$")
START = re.compile(r"^Started GET request to (\S+)$")
FINISH = re.compile(r"^Finished GET request to (\S+) with status code (\d+)")
FAILURE = re.compile(r"GET request to (\S+) (?:failed|has been cancelled|timed out)")


def parse_lines(lines):
    pending = collections.defaultdict(collections.deque)
    requests = []
    events = []
    failures = 0
    cancelled = 0
    overlapping = 0
    unmatched_finishes = 0
    listener = None
    version = None
    for line in lines:
        header = HEADER.match(line.strip())
        if not header:
            continue
        stamp, component, message = header.groups()
        time = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        iso = time.isoformat().replace("+00:00", "Z")
        if component in ("MessageListener", "BrokerMessageListener"):
            listener = component
        version_match = re.search(r"(?:Runner version|Current runner version): '?(\d+\.\d+\.\d+)", message)
        if version_match:
            version = version_match.group(1)
        for phrase, label in (
            ("Listening for Jobs", "listening"),
            ("Session created.", "session_created"),
            ("Received job message", "job_message_received"),
            ("Running job:", "job_started"),
            ("Job completed.", "job_completed"),
        ):
            if phrase in message:
                events.append({"at": iso, "event": label})
        if component != "GitHubActionsService":
            continue
        start = START.match(message)
        finish = FINISH.match(message)
        failure = FAILURE.search(message)
        match = start or finish or failure
        if not match:
            continue
        uri = match.group(1)
        endpoint = urllib.parse.urlsplit(uri).path.rstrip("/")
        if not endpoint.endswith(("/message", "/messages")):
            continue
        endpoint_kind = "broker/message" if endpoint.endswith("/message") else "legacy/messages"
        if start:
            if pending[uri]:
                overlapping += 1
            pending[uri].append(time)
        elif finish:
            if not pending[uri]:
                unmatched_finishes += 1
                continue
            begin = pending[uri].popleft()
            requests.append({
                "start": begin.isoformat().replace("+00:00", "Z"),
                "finish": iso,
                "duration_seconds": (time - begin).total_seconds(),
                "status": int(finish.group(2)),
                "endpoint": endpoint_kind,
            })
        elif failure:
            if "has been cancelled" in message:
                cancelled += 1
            else:
                failures += 1
            pending.pop(uri, None)
    return {
        "listener": listener,
        "version": version,
        "requests": requests,
        "events": events,
        "failed_request_events": failures,
        "cancelled_request_events": cancelled,
        "overlapping_starts": overlapping,
        "unmatched_finishes": unmatched_finishes,
        "pending_requests": sum(len(q) for q in pending.values()),
    }


parser = argparse.ArgumentParser(description="Extract message GET timings without exporting request URLs or payloads")
parser.add_argument("--self-test", action="store_true")
args = parser.parse_args()

if args.self_test:
    sample = [
        "[2026-09-07 12:00:00Z INFO BrokerMessageListener] Session created.",
        "[2026-09-07 12:00:01Z VERB GitHubActionsService] Started GET request to https://example.invalid/message?sessionId=do-not-export",
        "[2026-09-07 12:00:51Z VERB GitHubActionsService] Finished GET request to https://example.invalid/message?sessionId=do-not-export with status code 204 (private-request-id)",
        "[2026-09-07 12:00:51Z VERB GitHubActionsService] Started GET request to https://example.invalid/message?sessionId=do-not-export",
        "[2026-09-07 12:00:54Z VERB GitHubActionsService] Finished GET request to https://example.invalid/message?sessionId=do-not-export with status code 200 (private-request-id)",
        "[2026-09-07 12:00:54Z INFO Runner] Received job message of length 123 from service, with hash 'do-not-export'",
        "[2026-09-07 12:00:55Z VERB GitHubActionsService] Started GET request to https://example.invalid/other?token=do-not-export",
    ]
    result = parse_lines(sample)
    assert [item["duration_seconds"] for item in result["requests"]] == [50, 3]
    assert [item["status"] for item in result["requests"]] == [204, 200]
    assert result["listener"] == "BrokerMessageListener"
    assert result["pending_requests"] == 0
    assert result["overlapping_starts"] == 0
    assert result["unmatched_finishes"] == 0
    assert len(result["events"]) == 2
    assert "do-not-export" not in json.dumps(result)
    assert "private-request-id" not in json.dumps(result)
    cancelled = parse_lines([
        "[2026-09-07 12:00:00Z VERB GitHubActionsService] Started GET request to https://example.invalid/message?sessionId=do-not-export",
        "[2026-09-07 12:00:03Z WARN GitHubActionsService] GET request to https://example.invalid/message?sessionId=do-not-export has been cancelled.",
        "[2026-09-07 12:00:05Z VERB GitHubActionsService] Started GET request to https://example.invalid/message?sessionId=do-not-export",
        "[2026-09-07 12:00:35Z VERB GitHubActionsService] Finished GET request to https://example.invalid/message?sessionId=do-not-export with status code 200 (private-request-id)",
    ])
    assert cancelled["requests"][0]["duration_seconds"] == 30
    assert cancelled["pending_requests"] == 0
    assert cancelled["overlapping_starts"] == 0
    assert cancelled["cancelled_request_events"] == 1
    print("PASS: timing pairs, status, path filter, event labels, and secret exclusion")
else:
    folder = pathlib.Path("/opt/actions-runner/_diag")
    logs = sorted(folder.glob("Runner_*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        raise RuntimeError("No runner diagnostic log is available")
    log = logs[-1]
    with log.open(encoding="utf-8-sig") as stream:
        result = parse_lines(stream)
    if not result["requests"]:
        raise RuntimeError("No completed message GET found; observe a runner with GITHUB_ACTIONS_RUNNER_TRACE=1 first")
    if result["overlapping_starts"] or result["unmatched_finishes"]:
        raise RuntimeError("Ambiguous request pairing; do not use these records as timing evidence")
    result["captured_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    result["log_file"] = log.name
    result["timestamp_resolution_seconds"] = 1
    result["completed_request_count"] = len(result["requests"])
    result["requests"] = result["requests"][-12:]
    result["events"] = result["events"][-12:]
    print(json.dumps(result, separators=(",", ":")))
PY
