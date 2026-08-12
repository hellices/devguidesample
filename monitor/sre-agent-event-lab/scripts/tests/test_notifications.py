import importlib.util
import json
import sys
from email import policy
from email.parser import BytesParser
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "generate_notifications.py"


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("generate_notifications", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timeline():
    return [
        {
            "event_id": "alert-1",
            "timestamp": "2026-08-12T08:07:56Z",
            "state": "alert-fired",
            "title": "alert-sre-lab-s1-http500",
            "summary": "Sev2 alert fired",
            "source": "azure-monitor",
            "source_file": "alert.json",
        },
        {
            "event_id": "thread-1",
            "timestamp": "2026-08-12T08:07:58Z",
            "state": "thread-created",
            "title": "HTTP Trigger",
            "summary": "Thread created",
            "source": "sre-agent",
            "source_file": "0001.json",
        },
        {
            "event_id": "conclusion-1",
            "timestamp": "2026-08-12T08:10:21Z",
            "state": "conclusion",
            "title": "Root cause",
            "summary": (
                "**Root cause confirmed:** Container App `ca-sre-event-lab-vnet` "
                "revision `0000010` had `FAILURE_MODE=http500`. "
                "120 GET /api/orders requests failed. "
                "A healthy revision restored service."
            ),
            "source": "sre-agent",
            "source_file": "0001.json",
        },
    ]


def test_generate_notifications_creates_ticket_and_email(tmp_path):
    notifications = load_module()

    outputs = notifications.generate_notifications(
        timeline=timeline(),
        output_dir=tmp_path,
        report_url="docs/superpowers/reports/report.md (available after merge)",
        issue_url="https://github.com/hellices/devguidesample/issues/123",
    )

    issue = (tmp_path / "s1-github-issue.md").read_text()
    for heading in (
        "## Impact",
        "## Detection",
        "## Root cause",
        "## Evidence",
        "## Current status",
        "## Recommended follow-up",
    ):
        assert heading in issue
    assert "120" in issue
    assert "thread-1" in issue
    assert "available after merge" in issue
    assert "Incident window" not in issue
    assert "Alert fired:" in issue
    assert "Agent conclusion:" in issue

    message = BytesParser(policy=policy.default).parse(
        open(tmp_path / "s1-incident-summary.eml", "rb")
    )
    assert message["Subject"] == "[Resolved][SRE-LAB] Order API HTTP 500 incident"
    assert message["To"] == "oncall@example.invalid"
    assert "https://github.com/hellices/devguidesample/issues/123" in message.get_body(
        preferencelist=("html",)
    ).get_content()
    assert "available after merge" in message.get_body(
        preferencelist=("html",)
    ).get_content()
    assert "**" not in (tmp_path / "s1-incident-summary.html").read_text()
    assert outputs["issue"].endswith("s1-github-issue.md")


def test_generate_notifications_redacts_sensitive_values(tmp_path):
    notifications = load_module()
    unsafe = timeline()
    unsafe[-1]["summary"] += (
        " Authorization: Bearer hidden-token "
        "InstrumentationKey=11111111-1111-1111-1111-111111111111 "
        "DefaultEndpointsProtocol=https;AccountName=demo;AccountKey=abc123;EndpointSuffix=core.windows.net "
        "oid=11111111-2222-3333-4444-555555555555 "
        "upn=user@contoso.com "
        "https://logic.example/path?sig=verylongcallbacksigrandomvalue"
    )

    notifications.generate_notifications(
        timeline=unsafe,
        output_dir=tmp_path,
        report_url="https://example.invalid/report",
    )

    rendered = "\n".join(
        path.read_text(errors="ignore")
        for path in tmp_path.iterdir()
        if path.suffix in {".md", ".html", ".eml"}
    )
    assert "hidden-token" not in rendered
    assert "11111111-1111-1111-1111-111111111111" not in rendered
    assert "abc123" not in rendered
    assert "user@contoso.com" not in rendered
    assert "verylongcallbacksigrandomvalue" not in rendered
    assert "[REDACTED]" in rendered
