#!/usr/bin/env python3
import argparse
import html
import json
import re
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Any, Optional, Sequence


BEARER_PATTERN = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+")
INSTRUMENTATION_PATTERN = re.compile(
    r"(?i)InstrumentationKey\s*=\s*[0-9a-f-]{36}"
)
CALLBACK_SIGNATURE_PATTERN = re.compile(r"(?i)([?&]sig=)[A-Za-z0-9_-]+")
CONNECTION_STRING_PATTERN = re.compile(
    r"(?i)(?:DefaultEndpointsProtocol|AccountName|AccountKey|"
    r"SharedAccessSignature|EndpointSuffix)=[^;\s]+(?:;[^;\s]+=[^;\s]+)*"
)
IDENTITY_CLAIM_PATTERN = re.compile(
    r"(?i)\b(?:oid|upn|preferred_username|email)="
    r"(?:[0-9a-f-]{36}|[^\s;]+)"
)


def sanitize(value: str) -> str:
    value = BEARER_PATTERN.sub("Bearer [REDACTED]", value)
    value = INSTRUMENTATION_PATTERN.sub(
        "InstrumentationKey=[REDACTED]", value
    )
    value = CONNECTION_STRING_PATTERN.sub("[CONNECTION STRING REDACTED]", value)
    value = IDENTITY_CLAIM_PATTERN.sub("[IDENTITY CLAIM REDACTED]", value)
    return CALLBACK_SIGNATURE_PATTERN.sub(r"\1[REDACTED]", value)


def strip_markdown(value: str) -> str:
    return sanitize(value).replace("**", "").replace("`", "")


def find_event(timeline: list[dict[str, Any]], state: str, last: bool = False):
    matches = [event for event in timeline if event.get("state") == state]
    if not matches:
        raise ValueError(f"timeline has no {state} event")
    return matches[-1] if last else matches[0]


def issue_markdown(
    alert: dict[str, Any],
    thread: dict[str, Any],
    conclusion: dict[str, Any],
    report_url: str,
) -> str:
    summary = sanitize(conclusion["summary"])
    return f"""## Impact

- Service: `ca-sre-event-lab-vnet`
- Operation: `GET /api/orders`
- Customer impact: 120 requests returned HTTP 500
- Alert fired: {alert["timestamp"]}
- Agent conclusion: {conclusion["timestamp"]}

## Detection

- Azure Monitor rule: `alert-sre-lab-s1-http500`
- Severity: Sev2
- Alert fired: {alert["timestamp"]}
- SRE Agent thread created: {thread["timestamp"]}

## Root cause

Container App revision `0000010` was deployed with `FAILURE_MODE=http500`.

## Evidence

- Application Insights recorded 120 failed `GET /api/orders` requests.
- The active failing revision exposed `FAILURE_MODE=http500`.
- Activity Log and revision timing matched the first failed request.
- Agent conclusion:

> {summary}

## Current status

Resolved. A succeeding revision uses `FAILURE_MODE=none`, receives traffic, and returned no further 5xx responses in the verification window.

## Recommended follow-up

1. Add deployment validation that rejects fault-injection settings outside the lab.
2. Keep Review mode until response-plan accuracy is established across more incidents.
3. Preserve the incident timeline as Agent knowledge for recurrence detection.

## Tracking

- Agent thread ID: `{thread["event_id"]}`
- Detailed validation appendix: {report_url}
- Generated from actual Azure SRE Agent evidence; no resource change was executed by the Agent.
"""


def email_html(
    alert: dict[str, Any],
    thread: dict[str, Any],
    conclusion: dict[str, Any],
    report_url: str,
    issue_url: str,
) -> str:
    summary = html.escape(strip_markdown(conclusion["summary"])).replace(
        "\n", "<br>"
    )
    ticket = (
        f'<a href="{html.escape(issue_url)}">{html.escape(issue_url)}</a>'
        if issue_url
        else "GitHub Issue 발행 전 draft"
    )
    report_reference = (
        f'<a href="{html.escape(report_url)}">Open detailed validation appendix</a>'
        if report_url.startswith(("https://", "http://"))
        else f"<code>{html.escape(report_url)}</code>"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>SRE incident summary</title>
  <style>
    body {{ margin: 0; background: #eef2f7; color: #172033; font-family: Arial, "Apple SD Gothic Neo", sans-serif; }}
    .mail {{ max-width: 760px; margin: 32px auto; background: white; border-radius: 14px; overflow: hidden; box-shadow: 0 8px 30px #16203522; }}
    .header {{ padding: 28px 34px; background: #0e1930; color: white; }}
    .badge {{ display: inline-block; padding: 6px 12px; border-radius: 16px; background: #16a34a; font-weight: 700; }}
    .content {{ padding: 30px 34px 36px; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .card {{ padding: 16px; border: 1px solid #dbe3ef; border-radius: 10px; background: #f8fafc; }}
    h1 {{ margin: 14px 0 4px; font-size: 26px; }}
    h2 {{ margin-top: 28px; font-size: 18px; color: #0f4c81; }}
    p, li {{ line-height: 1.55; }}
    .footer {{ padding: 20px 34px; background: #f3f6fa; color: #64748b; font-size: 13px; }}
  </style>
</head>
<body>
  <main class="mail">
    <header class="header">
      <span class="badge">RESOLVED · DRAFT</span>
      <h1>Order API HTTP 500 incident</h1>
      <p>Azure SRE Agent investigation summary</p>
    </header>
    <section class="content">
      <div class="grid">
        <div class="card"><strong>Severity</strong><br>Sev2</div>
        <div class="card"><strong>Service</strong><br>ca-sre-event-lab-vnet</div>
        <div class="card"><strong>Alert fired</strong><br>{html.escape(alert["timestamp"])}</div>
        <div class="card"><strong>Conclusion</strong><br>{html.escape(conclusion["timestamp"])}</div>
      </div>
      <h2>Customer impact</h2>
      <p>120 <code>GET /api/orders</code> requests returned HTTP 500.</p>
      <h2>Root cause and evidence</h2>
      <p>{summary}</p>
      <h2>Mitigation and current status</h2>
      <p>A healthy revision with <code>FAILURE_MODE=none</code> restored service. The Agent remained in Review mode and did not modify Azure resources.</p>
      <h2>Ticket</h2>
      <p>{ticket}</p>
      <h2>Follow-up</h2>
      <ol>
        <li>Reject lab-only fault settings in non-lab deployments.</li>
        <li>Keep the response plan in Review mode while accuracy is monitored.</li>
        <li>Retain this investigation in the Agent knowledge base.</li>
      </ol>
      <p>{report_reference}</p>
    </section>
    <footer class="footer">
      Draft artifact — not sent. Agent thread {html.escape(thread["event_id"])}
    </footer>
  </main>
</body>
</html>
"""


def email_plain(
    alert: dict[str, Any],
    conclusion: dict[str, Any],
    report_url: str,
    issue_url: str,
) -> str:
    return sanitize(
        f"""[DRAFT] Order API HTTP 500 incident

Severity: Sev2
Alert fired: {alert["timestamp"]}
Conclusion: {conclusion["timestamp"]}
Impact: 120 GET /api/orders requests returned HTTP 500.

Root cause:
Container App revision 0000010 had FAILURE_MODE=http500.

Current status:
Resolved by a healthy revision with FAILURE_MODE=none.

Ticket: {issue_url or "GitHub Issue 발행 전 draft"}
Detailed validation appendix: {report_url}
"""
    )


def generate_notifications(
    timeline: list[dict[str, Any]],
    output_dir: Path,
    report_url: str,
    issue_url: str = "",
) -> dict[str, str]:
    alert = find_event(timeline, "alert-fired")
    thread = find_event(timeline, "thread-created")
    conclusion = find_event(timeline, "conclusion", last=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    issue_path = output_dir / "s1-github-issue.md"
    html_path = output_dir / "s1-incident-summary.html"
    eml_path = output_dir / "s1-incident-summary.eml"

    issue_path.write_text(
        issue_markdown(alert, thread, conclusion, report_url)
    )
    html_body = email_html(
        alert, thread, conclusion, report_url, issue_url
    )
    html_path.write_text(html_body)

    message = EmailMessage()
    message["From"] = "azure-sre-agent-demo@example.invalid"
    message["To"] = "oncall@example.invalid"
    message["Subject"] = "[Resolved][SRE-LAB] Order API HTTP 500 incident"
    message["X-SRE-Agent-Draft"] = "true"
    message.set_content(
        email_plain(alert, conclusion, report_url, issue_url)
    )
    message.add_alternative(html_body, subtype="html")
    eml_path.write_bytes(message.as_bytes(policy=SMTP))

    return {
        "issue": str(issue_path),
        "html": str(html_path),
        "eml": str(eml_path),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SRE ticket and email artifacts")
    parser.add_argument("--timeline", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--report-url", required=True)
    parser.add_argument("--issue-url", default="")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    timeline = json.loads(args.timeline.read_text())
    outputs = generate_notifications(
        timeline=timeline,
        output_dir=args.output_dir,
        report_url=args.report_url,
        issue_url=args.issue_url,
    )
    print(json.dumps(outputs, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
