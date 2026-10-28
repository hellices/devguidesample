import datetime
import decimal
import re
import sys
import unittest
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SAMPLE_DIR / "agent/tools"))
sys.path.insert(0, str(SAMPLE_DIR / "scripts"))

import render_agent_config  # noqa: E402
import sql_server_health_check as tool  # noqa: E402

STATE = {
    "resourceGroup": "rg-example",
    "vmName": "example-sqlvm",
    "sqlHost": "10.0.1.4",
    "sqlPort": 1433,
    "sqlLogin": "sre_monitor",
    "secretName": "sql-monitor-password",
    "keyVaultName": "kv-example",
    "agentIdentityClientId": "11111111-1111-1111-1111-111111111111",
    "prometheusQueryEndpoint": "https://example.koreacentral.prometheus.monitor.azure.com",
}


class FakeCursor:
    """Returns canned rows keyed by a fragment of the SQL text."""

    def __init__(self, responses, failing=()):
        self.responses = responses
        self.failing = failing
        self.description = None
        self._rows = []
        self.executed = []

    def execute(self, sql):
        self.executed.append(sql)
        for fragment in self.failing:
            if fragment in sql:
                raise RuntimeError("permission denied")
        for fragment, (columns, rows) in self.responses.items():
            if fragment in sql:
                self.description = [(name,) for name in columns]
                self._rows = rows
                return
        self.description = None
        self._rows = []

    def fetchall(self):
        return self._rows


class OperationTests(unittest.TestCase):
    def test_rejects_unknown_operation(self):
        with self.assertRaises(ValueError):
            tool.validate_operation("DROP DATABASE")

    def test_every_base_operation_except_summary_has_a_query(self):
        for operation in tool.BASE_OPERATIONS:
            if operation != "summary":
                self.assertIn(operation, tool.QUERIES)

    def test_extra_operations_are_accepted(self):
        for operation in tool.EXTRA_OPERATIONS:
            self.assertEqual(tool.validate_operation(operation), operation)

    def test_queries_are_read_only(self):
        forbidden = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|EXEC|EXECUTE|KILL|GRANT|TRUNCATE)\b", re.I)
        queries = {**tool.QUERIES, **tool.EXTRA_QUERIES, **tool.PER_DB_QUERIES}
        for name, sql in queries.items():
            # String literals such as 'GRANT' (a lock status) are not statements.
            self.assertIsNone(forbidden.search(re.sub(r"'[^']*'", "''", sql)), f"{name} contains a write keyword")

    def test_json_values_are_serializable(self):
        self.assertEqual(tool.to_json_value(decimal.Decimal("1.5")), 1.5)
        self.assertEqual(tool.to_json_value(datetime.datetime(2026, 1, 2, 3, 4, 5)), "2026-01-02T03:04:05")


class LoginEventTests(unittest.TestCase):
    MESSAGE = ("Login failed for user 'app_user'. Reason: Password did not match that for the login provided. "
               "[CLIENT: 127.0.0.1]")

    def test_parse_failed_login(self):
        self.assertEqual(tool.parse_failed_login(self.MESSAGE),
                         ("app_user", "127.0.0.1", "Password did not match that for the login provided"))

    def test_parse_unexpected_message(self):
        self.assertEqual(tool.parse_failed_login("something else"), ("unknown", "unknown", "unknown"))

    def test_summarize_login_events(self):
        events = [
            {"event": "error_reported", "ts_utc": "2026-10-27T10:00:00", "message": self.MESSAGE, "state": 8},
            {"event": "error_reported", "ts_utc": "2026-10-27T10:01:00", "message": self.MESSAGE, "state": 8},
            # The generic copy sent to the client has no [CLIENT: ...] and is not counted twice.
            {"event": "error_reported", "ts_utc": "2026-10-27T10:01:00",
             "message": "Login failed for user 'app_user'.", "state": 1},
            {"event": "login", "ts_utc": "2026-10-27T10:02:00", "login": "sre_monitor", "host": "h", "app": "a"},
        ]
        summary = tool.summarize_login_events(events)
        self.assertEqual(summary["failed_by_login_client_reason"][0]["attempts"], 2)
        self.assertEqual(summary["succeeded_by_login_host_app"][0]["login"], "sre_monitor")
        self.assertEqual(summary["recent_failures"][0]["ts_utc"], "2026-10-27T10:01:00")


class CompactTests(unittest.TestCase):
    def test_compact_drops_empty_values_but_keeps_flags(self):
        rows = [{"login": "a", "locked": 0, "disabled": 0, "bad_password_count": 0, "lockout_time": None}]
        self.assertEqual(tool.compact(rows), [{"login": "a", "locked": 0, "disabled": 0}])


class PerDatabaseTests(unittest.TestCase):
    def test_quote_name_escapes_brackets(self):
        self.assertEqual(tool.quote_name("a]b"), "[a]]b]")

    def test_rows_in_db_uses_sp_executesql_with_parameters(self):
        cursor = FakeCursor({"sp_executesql": (["x"], [(1,)])})
        captured = []
        original = cursor.execute

        def execute(sql, params=None):
            captured.append((sql, params))
            original(sql)

        cursor.execute = execute
        rows = tool._rows_in_db(cursor, "SreDemo", "SELECT 1", "@today datetimeoffset", [("today", "2026-10-27")])
        self.assertEqual(rows, [{"x": 1}])
        self.assertEqual(captured[0][0], "EXEC [SreDemo].sys.sp_executesql %s, %s, @today = %s")
        self.assertEqual(captured[0][1], ("SELECT 1", "@today datetimeoffset", "2026-10-27"))


class BlockingTests(unittest.TestCase):
    def test_head_blocker_is_blocker_that_is_not_blocked(self):
        rows = [
            {"sid": 61, "blocked_by": 54},
            {"sid": 55, "blocked_by": 61},
            {"sid": 73, "blocked_by": 61},
            {"sid": 80, "blocked_by": 0},
        ]
        summary = tool.summarize_requests(rows)
        self.assertEqual(summary["blocked"], 3)
        self.assertEqual(summary["head_blockers"], [54])


class CollectTests(unittest.TestCase):
    def test_section_error_does_not_drop_other_sections(self):
        cursor = FakeCursor(
            {"sys.dm_os_wait_stats": (["wait_type", "wait_time_ms"], [("LCK_M_S", 10)])},
            failing=("msdb.dbo.backupset",),
        )
        data = tool.collect(cursor, "waits")
        self.assertEqual(data["waits"], [{"wait_type": "LCK_M_S", "wait_time_ms": 10}])
        self.assertNotIn("section_errors", data)
        data = tool.collect(cursor, "backups")
        self.assertIn("backups", data["section_errors"])

    def test_session_is_read_uncommitted_with_lock_timeout(self):
        cursor = FakeCursor({})
        tool.collect(cursor, "io")
        self.assertIn("SET LOCK_TIMEOUT", cursor.executed[0])


class ConnectionTests(unittest.TestCase):
    def test_connection_requires_tls_and_read_only_intent(self):
        captured = {}

        class FakeDriver:
            @staticmethod
            def connect(**kwargs):
                captured.update(kwargs)
                return object()

        original = (tool.pymssql, tool.SQL_PORT)
        tool.pymssql, tool.SQL_PORT = FakeDriver, "1433"
        try:
            tool._connect("secret")
        finally:
            tool.pymssql, tool.SQL_PORT = original
        self.assertEqual(captured["encryption"], "require")
        self.assertTrue(captured["read_only"])
        self.assertEqual(captured["database"], "master")


class RenderTests(unittest.TestCase):
    def test_tool_body_renders_all_placeholders(self):
        body = render_agent_config.tool_body(STATE)
        rendered = body["spec"]["tools"][0]
        metrics = body["spec"]["tools"][1]
        self.assertEqual(metrics["name"], "SqlServerMetricsQuery")
        self.assertIsNone(re.search(r"@@[A-Z_]+@@", metrics["function_code"]))
        self.assertIn(STATE["prometheusQueryEndpoint"], metrics["function_code"])
        self.assertEqual(body["kind"], "ToolList")
        self.assertEqual(rendered["type"], "PythonFunctionTool")
        self.assertIn("pymssql", rendered["dependencies"])
        self.assertIsNone(re.search(r"@@[A-Z_]+@@", rendered["function_code"]))
        self.assertIn('SQL_HOST = "10.0.1.4"', rendered["function_code"])

    def test_query_tool_renders_and_compiles(self):
        query = render_agent_config.tool_body(STATE)["spec"]["tools"][2]
        self.assertEqual(query["name"], "SqlServerQuery")
        self.assertIsNone(re.search(r"@@[A-Z_]+@@", query["function_code"]))
        namespace = {}
        exec(compile(query["function_code"], "rendered_query_tool", "exec"), namespace)
        self.assertEqual(namespace["SQL_HOST"], "10.0.1.4")
        self.assertEqual([p["name"] for p in query["parameters"]], ["sql", "database", "max_rows", "timeout_seconds"])

    def test_rendered_tool_compiles(self):
        code = render_agent_config.tool_body(STATE)["spec"]["tools"][0]["function_code"]
        namespace = {}
        exec(compile(code, "rendered_tool", "exec"), namespace)
        self.assertEqual(int(namespace["SQL_PORT"]), 1433)
        self.assertEqual(namespace["validate_operation"]("summary"), "summary")

    def test_skill_body_references_tool_vm_and_host(self):
        body = render_agent_config.skill_body(STATE)
        content = body["properties"]["skillContent"]
        self.assertEqual(body["properties"]["tools"], ["SqlServerHealthCheck", "SqlServerQuery", "SqlServerMetricsQuery"])
        self.assertIn(STATE["vmName"], content)
        self.assertIn(STATE["sqlHost"], content)
        self.assertNotIn("@@", content)


if __name__ == "__main__":
    unittest.main()


class MetricsToolTests(unittest.TestCase):
    def setUp(self):
        import sql_server_metrics_query
        self.metrics = sql_server_metrics_query

    def test_validate_limits(self):
        with self.assertRaises(ValueError):
            self.metrics.validate("", 0, 300)
        with self.assertRaises(ValueError):
            self.metrics.validate("up", 99999, 300)
        with self.assertRaises(ValueError):
            self.metrics.validate("up", 60, 5)
        self.metrics.validate("up", 60, 300)

    def test_summarize_range_drops_noise_labels(self):
        result = [{"metric": {"__name__": "mssql_table_rows", "table": "orders", "microsoft.amwresourceid": "x",
                              "job": "sql_exporter"},
                   "values": [[1, "100"], [2, "150"], [3, "NaN"], [4, "180"]]}]
        summary = self.metrics.summarize("matrix", result)
        series = summary["series"][0]
        self.assertEqual(series["labels"], {"__name__": "mssql_table_rows", "table": "orders"})
        self.assertEqual((series["first"], series["last"], series["change"], series["points"]), (100.0, 180.0, 80.0, 3))
