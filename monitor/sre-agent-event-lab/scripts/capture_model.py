#!/usr/bin/env python3
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "token",
    "accesstoken",
    "connectionstring",
    "instrumentationkey",
    "pat",
    "password",
    "secret",
}
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
CONNECTION_PATTERN = re.compile(
    r"(?i)\b(InstrumentationKey|ConnectionString)\s*=\s*[^;\s]+"
)
CONCLUSION_PATTERN = re.compile(
    r"(?i)\b(root cause|conclusion|remediation summary|resolved)\b"
)


@dataclass(frozen=True)
class CaptureEvent:
    event_id: str
    timestamp: str
    state: str
    title: str
    summary: str
    source: str
    source_file: str


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _normalized_key(str(key)) in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact(item)
        return result
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        return CONNECTION_PATTERN.sub(r"\1=[REDACTED]", value)
    return value


def _timestamp(value: Any, fallback: str) -> str:
    if isinstance(value, str) and value:
        parsed = value.replace("Z", "+00:00")
        try:
            return (
                datetime.fromisoformat(parsed)
                .astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except ValueError:
            pass
    return fallback


def _get_timestamp(item: dict[str, Any], fallback: str) -> str:
    for key in (
        "createdAt",
        "created_at",
        "createdDateTime",
        "timestamp",
        "updatedAt",
    ):
        if item.get(key):
            return _timestamp(item[key], fallback)
    return fallback


def _message_summary(message: dict[str, Any]) -> str:
    content = message.get("content", message.get("text", message.get("message", "")))
    if not isinstance(content, str):
        content = json.dumps(content, sort_keys=True)
    return str(redact(content)).strip()


def _alert_event(alert: dict[str, Any]) -> CaptureEvent:
    essentials = alert.get("properties", {}).get("essentials", {})
    title = essentials.get("alertRule") or alert.get("name") or "Azure Monitor alert"
    timestamp = _timestamp(
        essentials.get("startDateTime"),
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    severity = essentials.get("severity", "unknown severity")
    return CaptureEvent(
        event_id=alert.get("id", "alert"),
        timestamp=timestamp,
        state="alert-fired",
        title=title,
        summary=f"{severity} alert fired",
        source="azure-monitor",
        source_file="alert.json",
    )


def _iter_threads(snapshot: dict[str, Any]) -> Iterable[dict[str, Any]]:
    threads = snapshot.get("threads", [])
    if isinstance(threads, dict):
        threads = threads.get("value", threads.get("items", []))
    return threads if isinstance(threads, list) else []


def _iter_messages(snapshot: dict[str, Any]) -> Iterable[dict[str, Any]]:
    messages = snapshot.get("messages", [])
    if isinstance(messages, dict):
        messages = messages.get("value", messages.get("items", []))
    return messages if isinstance(messages, list) else []


def normalize_capture(
    alert: dict[str, Any], snapshots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    events = [_alert_event(redact(alert))]
    seen_threads = set()
    seen_messages = set()
    conclusion_found = False
    last_snapshot_file = "thread-snapshots/none.json"
    last_timestamp = events[0].timestamp

    for snapshot in snapshots:
        captured_at = _timestamp(snapshot.get("captured_at"), last_timestamp)
        source_file = snapshot.get("source_file", "thread-snapshots/unknown.json")
        last_snapshot_file = source_file
        last_timestamp = max(last_timestamp, captured_at)

        for thread in _iter_threads(snapshot):
            thread_id = str(thread.get("id", thread.get("threadId", "thread")))
            if thread_id not in seen_threads:
                seen_threads.add(thread_id)
                thread_timestamp = _get_timestamp(thread, captured_at)
                last_timestamp = max(last_timestamp, thread_timestamp)
                events.append(
                    CaptureEvent(
                        event_id=thread_id,
                        timestamp=thread_timestamp,
                        state="thread-created",
                        title=thread.get("title", "SRE Agent incident thread"),
                        summary=f"Thread status: {thread.get('status', 'unknown')}",
                        source="sre-agent",
                        source_file=source_file,
                    )
                )

        messages = list(_iter_messages(snapshot))
        for message in messages:
            message_id = str(message.get("id", message.get("messageId", "message")))
            if message_id in seen_messages:
                continue
            seen_messages.add(message_id)
            summary = _message_summary(message)
            is_conclusion = bool(CONCLUSION_PATTERN.search(summary))
            state = "conclusion" if is_conclusion else "investigating"
            conclusion_found = conclusion_found or is_conclusion
            message_timestamp = _get_timestamp(message, captured_at)
            last_timestamp = max(last_timestamp, message_timestamp)
            events.append(
                CaptureEvent(
                    event_id=message_id,
                    timestamp=message_timestamp,
                    state=state,
                    title="SRE Agent message",
                    summary=summary,
                    source="sre-agent",
                    source_file=source_file,
                )
            )

        if not messages:
            for thread in _iter_threads(snapshot):
                status = str(thread.get("status", "")).lower()
                if status in {"running", "inprogress", "investigating"}:
                    status_id = f"{thread.get('id', 'thread')}:investigating"
                    if status_id not in seen_messages:
                        seen_messages.add(status_id)
                        events.append(
                            CaptureEvent(
                                event_id=status_id,
                                timestamp=captured_at,
                                state="investigating",
                                title="SRE Agent investigation",
                                summary=f"Thread status: {thread.get('status')}",
                                source="sre-agent",
                                source_file=source_file,
                            )
                        )

    if not conclusion_found:
        events.append(
            CaptureEvent(
                event_id="conclusion-missing",
                timestamp=last_timestamp,
                state="conclusion-missing",
                title="Conclusion not captured",
                summary="No structured conclusion was present before capture ended.",
                source="capture",
                source_file=last_snapshot_file,
            )
        )

    state_order = {
        "alert-fired": 0,
        "thread-created": 1,
        "investigating": 2,
        "conclusion": 3,
        "conclusion-missing": 4,
    }
    deduplicated = {}
    for event in events:
        key = (event.source, event.event_id, event.state)
        deduplicated[key] = event
    ordered = sorted(
        deduplicated.values(),
        key=lambda event: (event.timestamp, state_order.get(event.state, 99)),
    )
    return [asdict(event) for event in ordered]
