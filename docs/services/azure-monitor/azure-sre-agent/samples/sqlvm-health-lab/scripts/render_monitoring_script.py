"""Render the self-contained VM install script for the SQL Server metrics pipeline.

Usage:
    python3 render_monitoring_script.py <state.json> <remote-write-url> > configure-monitoring.ps1

The exporter configuration files are embedded as base64 so that a single
Run Command script can write them on the VM without quoting issues.
"""

import base64
import json
import re
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
PLACEHOLDER_PATTERN = re.compile(r"@@[A-Z0-9_]+@@")


def _b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def render_prometheus_config(state, remote_write_url):
    if not remote_write_url.startswith("https://") or "/api/v1/write" not in remote_write_url:
        raise ValueError("remote write URL must be the Azure Monitor workspace ingestion URL")
    text = (SAMPLE_DIR / "monitoring/prometheus.yml.tmpl").read_text(encoding="utf-8")
    values = {
        "@@VM_NAME@@": state["vmName"],
        "@@REMOTE_WRITE_URL@@": remote_write_url,
        "@@METRICS_CLIENT_ID@@": state["vmMetricsClientId"],
    }
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)
    if PLACEHOLDER_PATTERN.search(text):
        raise ValueError("unrendered placeholder in prometheus.yml")
    return text


def render_install_script(state, remote_write_url):
    script = (SAMPLE_DIR / "scripts/vm/configure-monitoring.ps1").read_text(encoding="utf-8")
    files = {
        "@@SQL_EXPORTER_YML_B64@@": (SAMPLE_DIR / "monitoring/sql_exporter.yml").read_text(encoding="utf-8"),
        "@@COLLECTOR_HEALTH_B64@@": (SAMPLE_DIR / "monitoring/mssql_health.collector.yml").read_text(encoding="utf-8"),
        "@@COLLECTOR_AUDIT_B64@@": (SAMPLE_DIR / "monitoring/mssql_audit.collector.yml").read_text(encoding="utf-8"),
        "@@COLLECTOR_INVENTORY_B64@@": (SAMPLE_DIR / "monitoring/mssql_inventory.collector.yml").read_text(encoding="utf-8"),
        "@@PROMETHEUS_YML_B64@@": render_prometheus_config(state, remote_write_url),
    }
    for placeholder, content in files.items():
        script = script.replace(placeholder, _b64(content))
    if PLACEHOLDER_PATTERN.search(script):
        raise ValueError("unrendered placeholder in configure-monitoring.ps1")
    return script


def main(argv):
    state = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    sys.stdout.write(render_install_script(state, argv[2]))


if __name__ == "__main__":
    main(sys.argv)
