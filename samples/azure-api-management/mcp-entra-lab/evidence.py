"""Publish measurements, never raw cloud responses, credentials or identities."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re


STATUSES = {"passed", "failed", "blocked", "not-run"}
SCOPES = {"live", "local"}
COUNTS = {"http_status", "tool_count", "result_count", "resource_count", "exit_code"}
BOOLEANS = {
    "private_dns",
    "tls_verified",
    "obo",
    "downstream_authorized",
    "audience_matched",
    "scope_matched",
    "tool_error",
    "backend_invoked",
    "correlation_matched",
    "metadata_matched",
    "header_removed",
}
ERROR_CODES = {
    "AuthorizationFailed",
    "AuthenticationFailed",
    "InsufficientPrivileges",
    "ConsentRequired",
    "Timeout",
    "HttpError",
    "McpError",
    "NotConfigured",
    "NetworkUnavailable",
    "ProvisioningFailed",
    "Unsupported",
}


def check(
    identifier: str, scope: str, status: str, **observed: str | int | bool
) -> dict:
    if not isinstance(identifier, str) or not re.fullmatch(
        r"[a-z][a-z0-9-]{1,70}", identifier
    ):
        raise ValueError("invalid check id")
    if scope not in SCOPES:
        raise ValueError("invalid scope")
    if status not in STATUSES:
        raise ValueError("invalid status")
    for name, value in observed.items():
        if name in COUNTS:
            valid = type(value) is int and value >= 0
            if name == "http_status":
                valid = valid and 100 <= value <= 599
        elif name in BOOLEANS:
            valid = type(value) is bool
        elif name == "protocol_version":
            valid = isinstance(value, str) and bool(
                re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            )
        elif name == "error_code":
            valid = isinstance(value, str) and (
                value in ERROR_CODES or bool(re.fullmatch(r"AADSTS\d{5,9}", value))
            )
        else:
            raise ValueError(f"unapproved measurement: {name}")
        if not valid:
            raise ValueError(f"invalid public measurement: {name}")
    return {"id": identifier, "scope": scope, "status": status, "observed": observed}


def validate_document(document: dict) -> list[dict]:
    if not isinstance(document, dict) or set(document) != {"recorded_at", "checks"}:
        raise ValueError("invalid evidence document fields")
    recorded_at = datetime.fromisoformat(document["recorded_at"])
    if recorded_at.tzinfo is None:
        raise ValueError("recorded_at must include a timezone")
    if not isinstance(document["checks"], list):
        raise ValueError("checks must be a list")
    results = []
    seen = set()
    for item in document["checks"]:
        if not isinstance(item, dict) or set(item) != {
            "id", "scope", "status", "observed"
        }:
            raise ValueError("invalid check fields")
        if not isinstance(item["observed"], dict):
            raise ValueError("observed must be a mapping")
        result = check(
            item["id"], item["scope"], item["status"], **item["observed"]
        )
        if result["id"] in seen:
            raise ValueError(f"duplicate check id: {result['id']}")
        seen.add(result["id"])
        results.append(result)
    return results


def write_results(path: Path, checks: list[dict]) -> None:
    document = {
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checks": checks,
    }
    validate_document(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def render_report(document: dict) -> str:
    results = validate_document(document)
    counts = Counter(item["status"] for item in results)
    summary = " / ".join(
        f"{counts[status]} {status}"
        for status in ("passed", "failed", "blocked", "not-run")
    )
    rows = []
    for item in results:
        measurements = ", ".join(
            f"{key}={str(value).lower() if isinstance(value, bool) else value}"
            for key, value in item["observed"].items()
        )
        rows.append(
            f'<tr><td>{escape(item["id"])}</td>'
            f'<td>{escape(item["scope"])}</td>'
            f'<td class="{item["status"]}">{item["status"]}</td>'
            f'<td>{escape(measurements)}</td></tr>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCP lab execution evidence</title>
<style>
body {{ margin: 32px; color: #182230; background: #f5f7fb;
       font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 1280px; margin: auto; }}
h1 {{ font-size: 32px; }} h2 {{ font-size: 24px; }}
.summary {{ font-weight: 700; padding: 16px; background: #e7edf7; }}
table {{ width: 100%; border-collapse: collapse; background: white; }}
th,td {{ padding: 12px; text-align: left; border: 1px solid #cdd5df; }}
th {{ background: #e7edf7; }} td:first-child {{ font-family: monospace; }}
.passed {{ color: #156333; font-weight: 700; }}
.failed {{ color: #a11a1a; font-weight: 700; }}
.blocked,.not-run {{ color: #805000; font-weight: 700; }}
.note {{ color: #465366; }}
</style></head><body><main>
<h1>Azure MCP lab: execution evidence</h1>
<p>Sanitized execution evidence | UTC {escape(document["recorded_at"])}</p>
<p class="summary">{summary}</p>
<table><thead><tr><th>Check</th><th>Scope</th><th>Result</th>
<th>Observed measurements</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<p class="note">This is a rendering of collected results, not an Azure portal
screenshot. Local tests do not prove live Azure behavior. Blocked and not-run
checks are not passes. Raw responses, tokens and environment identifiers are
intentionally excluded.</p>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8"))
    html = render_report(document)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
