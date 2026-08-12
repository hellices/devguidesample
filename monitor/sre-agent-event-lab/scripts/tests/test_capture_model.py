import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "capture_model.py"


def load_module():
    spec = importlib.util.spec_from_file_location("capture_model", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_capture_redacts_and_reports_missing_conclusion():
    model = load_module()
    alert = {
        "id": "alert-1",
        "properties": {
            "essentials": {
                "alertRule": "[SRE-LAB-S1] HTTP 500 rate exceeded",
                "severity": "Sev2",
                "startDateTime": "2026-08-12T05:09:00Z",
            }
        },
    }
    snapshots = [
        {
            "captured_at": "2026-08-12T05:10:00Z",
            "source_file": "thread-snapshots/0001.json",
            "threads": [
                {
                    "id": "thread-1",
                    "title": "[SRE-LAB-S1] HTTP 500 rate exceeded",
                    "status": "Running",
                    "createdAt": "2026-08-12T05:09:30Z",
                }
            ],
            "messages": [
                {
                    "id": "message-1",
                    "createdAt": "2026-08-12T05:10:01Z",
                    "role": "assistant",
                    "content": "Investigating. Authorization: Bearer secret-token",
                }
            ],
        }
    ]

    events = model.normalize_capture(alert, snapshots)

    assert [event["state"] for event in events] == [
        "alert-fired",
        "thread-created",
        "investigating",
        "conclusion-missing",
    ]
    assert events[2]["event_id"] == "message-1"
    assert "secret-token" not in events[2]["summary"]
    assert "[REDACTED]" in events[2]["summary"]
    assert events[-1]["source_file"] == "thread-snapshots/0001.json"


def test_normalize_capture_detects_structured_conclusion():
    model = load_module()
    alert = {
        "id": "alert-2",
        "properties": {
            "essentials": {
                "alertRule": "[SRE-LAB-S2] Request p95 latency exceeded",
                "severity": "Sev2",
                "startDateTime": "2026-08-12T05:20:00Z",
            }
        },
    }
    snapshots = [
        {
            "captured_at": "2026-08-12T05:22:00Z",
            "source_file": "thread-snapshots/0002.json",
            "threads": [
                {
                    "id": "thread-2",
                    "title": "[SRE-LAB-S2] Request p95 latency exceeded",
                    "status": "Completed",
                    "createdAt": "2026-08-12T05:20:30Z",
                }
            ],
            "messages": [
                {
                    "id": "message-2",
                    "createdAt": "2026-08-12T05:21:00Z",
                    "role": "assistant",
                    "content": "Investigation started.",
                },
                {
                    "id": "message-3",
                    "createdAt": "2026-08-12T05:22:00Z",
                    "role": "assistant",
                    "content": "Root cause: the latest revision added request delay.",
                },
            ],
        }
    ]

    events = model.normalize_capture(alert, snapshots)

    assert events[-1]["state"] == "conclusion"
    assert events[-1]["event_id"] == "message-3"


def test_redact_removes_sensitive_keys_recursively():
    model = load_module()

    redacted = model.redact(
        {
            "Authorization": "Bearer top-secret",
            "nested": {
                "connectionString": "InstrumentationKey=abc",
                "safe": "value",
            },
        }
    )

    assert redacted["Authorization"] == "[REDACTED]"
    assert redacted["nested"]["connectionString"] == "[REDACTED]"
    assert redacted["nested"]["safe"] == "value"
