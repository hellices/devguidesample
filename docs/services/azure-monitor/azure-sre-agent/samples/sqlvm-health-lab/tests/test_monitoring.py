import base64
import json
import re
import sys
import unittest
from pathlib import Path

import yaml

SAMPLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SAMPLE_DIR / "scripts"))

import render_dashboard  # noqa: E402
import render_monitoring_script  # noqa: E402

COLLECTORS = [
    yaml.safe_load(path.read_text(encoding="utf-8"))
    for path in sorted((SAMPLE_DIR / "monitoring").glob("*.collector.yml"))
]
DASHBOARD = json.loads((SAMPLE_DIR / "monitoring/grafana/sql-server-vm.dashboard.json").read_text(encoding="utf-8"))
STATE = {
    "vmName": "example-sqlvm",
    "vmMetricsClientId": "22222222-2222-2222-2222-222222222222",
}
REMOTE_WRITE_URL = (
    "https://example.koreacentral-1.metrics.ingest.monitor.azure.com/dataCollectionRules/dcr-0000"
    "/streams/Microsoft-PrometheusMetrics/api/v1/write?api-version=2023-04-24"
)
# windows_exporter metrics used by the dashboard (cpu, memory, logical_disk, mssql collectors).
WINDOWS_EXPORTER_METRICS = {
    "windows_cpu_time_seconds_total",
    "windows_memory_available_bytes",
    "windows_logical_disk_free_bytes",
    "windows_logical_disk_size_bytes",
    "windows_mssql_bufman_page_life_expectancy_seconds",
    "windows_mssql_genstats_user_connections",
    "windows_mssql_locks_deadlocks_total",
    "windows_mssql_locks_lock_waits_total",
    "windows_mssql_locks_lock_wait_seconds_total",
    "windows_mssql_locks_lock_timeouts_excluding_nowait_total",
    "windows_mssql_accessmethods_table_lock_escalations_total",
    "windows_mssql_memmgr_pending_memory_grants",
    "windows_mssql_memmgr_target_server_memory_bytes",
    "windows_mssql_memmgr_total_server_memory_bytes",
    "windows_mssql_sqlstats_batch_requests_total",
    "windows_mssql_sqlstats_sql_compilations_total",
    "windows_mssql_sqlstats_sql_recompilations_total",
}
WRITE_KEYWORDS = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|EXEC|EXECUTE|KILL|GRANT|TRUNCATE)\b", re.I)


def collector_metric_names():
    return {metric["metric_name"] for collector in COLLECTORS for metric in collector["metrics"]}


def collector_sql_texts():
    for collector in COLLECTORS:
        yield from (metric.get("query", "") for metric in collector["metrics"])
        yield from (query["query"] for query in collector.get("queries", []))


def dashboard_exprs():
    for panel in DASHBOARD["panels"]:
        for target in panel.get("targets", []):
            yield panel["title"], target["expr"]


class CollectorTests(unittest.TestCase):
    def test_every_metric_has_a_resolvable_query(self):
        for collector in COLLECTORS:
            queries = {query["query_name"]: query["query"] for query in collector.get("queries", [])}
            for metric in collector["metrics"]:
                sql = metric.get("query") or queries.get(metric.get("query_ref"))
                self.assertTrue(sql, metric["metric_name"])
                for column in metric.get("key_labels", []) + metric["values"]:
                    self.assertRegex(sql, rf"\b{re.escape(column)}\b", f"{metric['metric_name']} misses column {column}")

    def test_queries_do_not_change_data(self):
        # Allowed: temp tables for per-database loops and sp_executesql that runs
        # the read-only statement inside each database.
        allowed = re.compile(r"INSERT\s+#\w+|CREATE TABLE\s+#\w+|EXEC sys\.sp_executesql", re.I)
        for sql in collector_sql_texts():
            without_literals = re.sub(r"'[^']*'", "''", allowed.sub("", sql))
            self.assertIsNone(WRITE_KEYWORDS.search(without_literals), sql[:80])

    def test_counters_end_with_total(self):
        for collector in COLLECTORS:
            for metric in collector["metrics"]:
                if metric["type"] == "counter":
                    self.assertTrue(metric["metric_name"].endswith("_total"), metric["metric_name"])

    def test_no_reserved_prometheus_labels(self):
        for collector in COLLECTORS:
            for metric in collector["metrics"]:
                labels = set(metric.get("key_labels", [])) | {metric.get("value_label")}
                self.assertFalse(labels & {"job", "instance"}, metric["metric_name"])

    def test_metric_names_are_unique(self):
        names = [m["metric_name"] for c in COLLECTORS for m in c["metrics"]]
        self.assertEqual(len(names), len(set(names)))

    def test_exporter_config_lists_every_collector(self):
        config = yaml.safe_load((SAMPLE_DIR / "monitoring/sql_exporter.yml").read_text(encoding="utf-8"))
        self.assertEqual(set(config["target"]["collectors"]), {c["collector_name"] for c in COLLECTORS})

    def test_expensive_collectors_are_rate_limited(self):
        intervals = {c["collector_name"]: c.get("min_interval") for c in COLLECTORS}
        self.assertEqual(intervals["mssql_inventory"], "300s")
        self.assertEqual(intervals["mssql_audit"], "60s")


class DashboardTests(unittest.TestCase):
    def test_every_expression_uses_known_metrics(self):
        known = collector_metric_names() | WINDOWS_EXPORTER_METRICS | {"up"}
        for title, expr in dashboard_exprs():
            names = set(re.findall(r"\b((?:mssql|windows)_[a-z_]+|up)\{", expr))
            self.assertTrue(names, title)
            self.assertLessEqual(names, known, f"{title}: {names - known}")

    def test_every_query_is_scoped_to_the_selected_vm(self):
        for title, expr in dashboard_exprs():
            for selector in re.findall(r"\{([^}]*)\}", expr):
                self.assertIn('sql_vm="$sql_vm"', selector, title)

    def test_panels_use_the_datasource_variable(self):
        for panel in DASHBOARD["panels"]:
            if panel["type"] != "row":
                self.assertEqual(panel["datasource"]["uid"], "${datasource}", panel["title"])

    def test_panel_ids_are_unique(self):
        ids = [panel["id"] for panel in DASHBOARD["panels"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_render_sets_default_datasource(self):
        payload = render_dashboard.render(DASHBOARD, "prom-uid")
        variable = next(v for v in payload["dashboard"]["templating"]["list"] if v["name"] == "datasource")
        self.assertEqual(variable["current"]["value"], "prom-uid")
        self.assertTrue(payload["overwrite"])


class InstallScriptTests(unittest.TestCase):
    def test_install_script_embeds_rendered_files(self):
        script = render_monitoring_script.render_install_script(STATE, REMOTE_WRITE_URL)
        self.assertIsNone(render_monitoring_script.PLACEHOLDER_PATTERN.search(script))
        blobs = re.findall(r"Write-Base64File \([^)]*\) '([A-Za-z0-9+/=]+)'", script)
        decoded = [base64.b64decode(blob).decode("utf-8") for blob in blobs]
        self.assertEqual(len(decoded), 5)
        prometheus = yaml.safe_load(next(text for text in decoded if "remote_write" in text))
        remote = prometheus["remote_write"][0]
        self.assertEqual(remote["url"], REMOTE_WRITE_URL)
        self.assertEqual(remote["azuread"]["managed_identity"]["client_id"], STATE["vmMetricsClientId"])
        self.assertEqual(prometheus["global"]["external_labels"]["sql_vm"], STATE["vmName"])

    def test_rejects_non_ingestion_url(self):
        with self.assertRaises(ValueError):
            render_monitoring_script.render_prometheus_config(STATE, "http://example.com")

    def test_downloads_are_pinned_by_sha256(self):
        script = (SAMPLE_DIR / "scripts/vm/configure-monitoring.ps1").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"Sha256 = '[0-9a-f]{64}'", script)), 3)
        self.assertNotIn("latest", script)

    def test_exporters_listen_on_loopback_only(self):
        script = (SAMPLE_DIR / "scripts/vm/configure-monitoring.ps1").read_text(encoding="utf-8")
        self.assertIn("LISTEN_ADDR=127.0.0.1", script)
        self.assertIn("--web.listen-address=127.0.0.1:9399", script)
        self.assertIn("--web.listen-address=127.0.0.1:9090", script)


if __name__ == "__main__":
    unittest.main()
