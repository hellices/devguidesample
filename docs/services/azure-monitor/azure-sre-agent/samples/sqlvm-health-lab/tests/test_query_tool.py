import datetime
import decimal
import re
import sys
import unittest
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SAMPLE_DIR / "agent/tools"))

import sql_server_query as query  # noqa: E402

LOCK_WAITS = """
SELECT wt.session_id, wt.blocking_session_id, wt.wait_type, wt.wait_duration_ms, wt.resource_description,
       DB_NAME(tl.resource_database_id) AS db, tl.resource_type, tl.request_mode
FROM sys.dm_os_waiting_tasks AS wt
JOIN sys.dm_tran_locks AS tl ON tl.lock_owner_address = wt.resource_address
WHERE wt.wait_type LIKE N'LCK[_]%';
"""


class ValidateSqlTests(unittest.TestCase):
    def assertAllowed(self, sql):
        self.assertEqual(query.validate_sql(sql), sql)

    def assertBlocked(self, sql):
        with self.assertRaises(ValueError, msg=sql):
            query.validate_sql(sql)

    def test_allows_diagnostic_queries(self):
        for sql in (
            LOCK_WAITS,
            "WITH r AS (SELECT session_id FROM sys.dm_exec_requests) SELECT * FROM r;",
            "SET NOCOUNT ON; DECLARE @t TABLE (id int); INSERT @t SELECT 1; SELECT * FROM @t;",
            "SELECT name INTO #db FROM sys.databases; SELECT * FROM #db; DROP TABLE #db;",
            "CREATE TABLE #x (a int); INSERT INTO #x VALUES (1); UPDATE #x SET a = 2; DELETE FROM #x; SELECT * FROM #x;",
            "IF OBJECT_ID(N'tempdb..#x') IS NULL BEGIN SELECT 1 AS a END",
            "BEGIN TRY SELECT 1/0 END TRY BEGIN CATCH SELECT ERROR_MESSAGE() END CATCH",
            "EXEC sp_who2;",
            "EXECUTE sys.sp_lock;",
            "DBCC SQLPERF(LOGSPACE);",
            "DBCC INPUTBUFFER(52);",
            "SELECT last_user_update, user_updates FROM sys.dm_db_index_usage_stats;",
            "SELECT N'DROP TABLE dbo.Orders' AS text_only -- DELETE in a comment",
            "SELECT [Delete], \"insert\" FROM sys.objects;",
            "SELECT * FROM sys.objects OPTION (USE HINT('DISABLE_OPTIMIZED_PLAN_FORCING'));",
            "SELECT TOP 5 * FROM sys.query_store_runtime_stats WHERE count_executions > 0;",
        ):
            self.assertAllowed(sql)

    def test_blocks_changes_and_escapes(self):
        for sql in (
            "UPDATE dbo.Orders SET Amount = 0",
            "SELECT 1; DELETE FROM dbo.Orders",
            "SELECT * INTO dbo.copy FROM sys.objects",
            "SELECT 1; INSERT INTO dbo.Orders VALUES (1)",
            "SELECT 1; DROP TABLE dbo.Orders",
            "SELECT 1; CREATE INDEX ix ON dbo.Orders (CustomerId)",
            "SELECT 1; ALTER LOGIN app_user WITH PASSWORD = 'x' UNLOCK",
            "SELECT 1; KILL 52",
            "SELECT 1; TRUNCATE TABLE dbo.Orders",
            "SELECT 1; GRANT CONTROL SERVER TO x",
            "SELECT 1; BEGIN TRAN; SELECT 2; COMMIT",
            "SELECT 1; COMMIT",
            "EXEC sp_executesql N'DELETE FROM dbo.Orders'",
            "EXEC ('DELETE FROM dbo.Orders')",
            "EXEC msdb.dbo.sp_start_job N'job'",
            "EXEC xp_cmdshell 'dir'",
            "sp_configure 'show advanced options', 1",
            "DBCC FREEPROCCACHE",
            "SELECT 1; WAITFOR DELAY '00:10:00'",
            "SELECT * FROM OPENROWSET('SQLNCLI', 'x', 'SELECT 1')",
            "SELECT 1; USE SreDemo; SELECT 2",
            "SELECT 1; EXECUTE AS LOGIN = 'sa'",
            "SELECT 1\nGO\nSELECT 2",
            "SELECT 1; SHUTDOWN",
            "SELECT a FROM sys.objects UPDATE dbo.Orders SET Amount = 0 SELECT b INTO #t FROM sys.objects",
            "INSERT #t EXEC sp_executesql N'SELECT 1'",
            "UPDATE TOP (1) dbo.Orders SET Amount = 0",
            "SELECT 1; BACKUP DATABASE SreDemo TO DISK = 'x'",
            "MERGE dbo.Orders AS t USING (SELECT 1 AS id) AS s ON t.OrderId = s.id WHEN MATCHED THEN DELETE;",
            "",
            "   ",
        ):
            self.assertBlocked(sql)

    def test_rejects_oversized_sql(self):
        self.assertBlocked("SELECT 1 " + " " * query.MAX_SQL_CHARS)


class SkillExampleTests(unittest.TestCase):
    def test_skill_reference_queries_pass_validation(self):
        skill = (SAMPLE_DIR / "agent/skills/sql-server-vm-health-check.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```sql\n(.*?)```", skill, re.DOTALL)
        self.assertTrue(blocks)
        for block in blocks:
            for statement in re.split(r"\n\s*\n", block.strip()):
                self.assertEqual(query.validate_sql(statement), statement)


class OptionsTests(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(query.validate_options(None, None, None), ("master", 200, 30))

    def test_bounds(self):
        self.assertEqual(query.validate_options("SreDemo", 1000, 120), ("SreDemo", 1000, 120))
        for args in (("x", 1001, 30), ("x", 10, 1), ("x", 10, 121), ("bad]name", 10, 30)):
            with self.assertRaises(ValueError, msg=args):
                query.validate_options(*args)


class FakeCursor:
    def __init__(self, result_sets):
        self.result_sets = result_sets
        self.index = 0
        self.position = 0

    @property
    def description(self):
        columns, _ = self.result_sets[self.index]
        return None if columns is None else [(name,) for name in columns]

    def fetchmany(self, size):
        rows = self.result_sets[self.index][1][self.position:self.position + size]
        self.position += len(rows)
        return rows

    def fetchall(self):
        rows = self.result_sets[self.index][1][self.position:]
        self.position = len(self.result_sets[self.index][1])
        return rows

    def nextset(self):
        if self.index + 1 < len(self.result_sets):
            self.index += 1
            self.position = 0
            return True
        return None


class ResultSetTests(unittest.TestCase):
    def test_reads_every_result_set_and_truncates(self):
        cursor = FakeCursor([
            (["session_id", "started"], [(52, datetime.datetime(2026, 10, 27, 1, 2, 3)), (53, None), (54, None)]),
            (None, []),
            (["amount", "sql"], [(decimal.Decimal("1.5"), "x" * (query.MAX_CELL_CHARS + 10))]),
        ])
        sets = query.read_result_sets(cursor, max_rows=2)
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[0]["rows"], [[52, "2026-10-27T01:02:03"], [53, None]])
        self.assertTrue(sets[0]["truncated"])
        self.assertEqual(sets[1]["rows"][0][0], 1.5)
        self.assertTrue(sets[1]["rows"][0][1].endswith("...(truncated)"))
        self.assertFalse(sets[1]["truncated"])


class FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.rolled_back = False

    def cursor(self):
        return self._cursor

    def rollback(self):
        self.rolled_back = True


class RunTests(unittest.TestCase):
    def test_sets_session_limits_and_always_rolls_back(self):
        executed = []

        class Cursor(FakeCursor):
            def execute(self, sql):
                executed.append(sql)
                if "boom" in sql:
                    raise RuntimeError("boom")

        connection = FakeConnection(Cursor([(["a"], [(1,)])]))
        self.assertEqual(query.run(connection, "SELECT 1 AS a", 10)[0]["rows"], [[1]])
        self.assertIn("SET LOCK_TIMEOUT 5000", executed[0])
        self.assertTrue(connection.rolled_back)

        failing = FakeConnection(Cursor([(["a"], [])]))
        with self.assertRaises(RuntimeError):
            query.run(failing, "SELECT 'boom'", 10)
        self.assertTrue(failing.rolled_back)

    def test_main_returns_validation_error_without_connecting(self):
        result = query.main("DELETE FROM dbo.Orders")
        self.assertFalse(result["success"])
        self.assertIn("DELETE", result["error"])

    def test_connect_keeps_autocommit_off_and_tls(self):
        captured = {}

        class FakePymssql:
            @staticmethod
            def connect(**kwargs):
                captured.update(kwargs)
                return object()

        original = query.pymssql, query.SQL_PORT
        query.pymssql, query.SQL_PORT = FakePymssql, "1433"
        try:
            query._connect("pw", "SreDemo", 30)
        finally:
            query.pymssql, query.SQL_PORT = original
        self.assertFalse(captured["autocommit"])
        self.assertEqual(captured["encryption"], "require")
        self.assertEqual(captured["database"], "SreDemo")
        self.assertEqual(captured["appname"], "sre-agent-adhoc-query")


if __name__ == "__main__":
    unittest.main()
