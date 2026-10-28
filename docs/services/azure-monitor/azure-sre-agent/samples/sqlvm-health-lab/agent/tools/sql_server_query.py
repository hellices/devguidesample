"""Ad hoc read-only T-SQL for the lab SQL Server VM, invoked by Azure SRE Agent.

The agent writes the query (for example a lock-wait or blocking-chain query
over the DMVs) when the fixed operations of SqlServerHealthCheck do not answer
the question. Layers that keep it read-only:

1. The monitoring login can read server state and metadata but has no write
   permission and cannot SELECT user table data.
2. This tool rejects data-changing, DDL, administrative, transaction-control,
   and dynamic SQL statements before sending the batch.
3. The batch runs inside a transaction that is always rolled back, with a lock
   timeout, a low deadlock priority, a query timeout, and result size limits.
"""

import datetime
import decimal
import re
import time

import requests

try:
    from azure.identity import ManagedIdentityCredential
except ImportError:  # pragma: no cover - the SRE Agent sandbox provides azure-identity
    ManagedIdentityCredential = None

try:
    import pymssql
except ImportError:  # pragma: no cover - preinstalled in the sandbox
    pymssql = None

SQL_HOST = "@@SQL_HOST@@"
SQL_PORT = "@@SQL_PORT@@"
SQL_LOGIN = "@@SQL_LOGIN@@"
KEY_VAULT_NAME = "@@KEY_VAULT_NAME@@"
SECRET_NAME = "@@SECRET_NAME@@"
AGENT_CLIENT_ID = "@@AGENT_CLIENT_ID@@"

KEY_VAULT_SCOPE = "https://vault.azure.net/.default"
APP_NAME = "sre-agent-adhoc-query"
LOGIN_TIMEOUT_SECONDS = 10
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
LOCK_TIMEOUT_MS = 5000
DEFAULT_MAX_ROWS = 200
MAX_ROWS = 1000
MAX_RESULT_SETS = 5
MAX_CELL_CHARS = 1000
MAX_SQL_CHARS = 20000

BLOCKED_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "MERGE", "DROP", "ALTER", "CREATE", "TRUNCATE",
    "GRANT", "REVOKE", "DENY", "KILL", "SHUTDOWN", "BACKUP", "RESTORE", "RECONFIGURE",
    "CHECKPOINT", "USE", "BULK", "OPENROWSET", "OPENQUERY", "OPENDATASOURCE",
    "WAITFOR", "COMMIT", "ROLLBACK", "SETUSER", "REVERT",
    "UPDATETEXT", "WRITETEXT", "INTO", "EXEC", "EXECUTE", "DBCC",
)
BLOCKED_PHRASES = re.compile(
    r"\b(?:BEGIN\s+(?:DISTRIBUTED\s+)?TRAN(?:SACTION)?|SAVE\s+TRAN(?:SACTION)?|(?:ENABLE|DISABLE)\s+TRIGGER)\b",
    re.IGNORECASE,
)
# Temporary objects stay inside this session and are dropped with it. Each
# pattern matches only the keywords directly in front of the #/@ name, so it
# cannot hide another statement written without a semicolon.
ALLOWED_TEMP_FORMS = re.compile(
    r"\b(?:INSERT\s+(?:INTO\s+)?|INTO\s+|CREATE\s+TABLE\s+|DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
    r"|UPDATE\s+|DELETE\s+(?:FROM\s+)?)[#@]",
    re.IGNORECASE,
)
ALLOWED_PROCEDURES = (
    "sp_who", "sp_who2", "sp_lock", "sp_helpdb", "sp_helpfile", "sp_spaceused",
    "sp_helpindex", "sp_helpstats", "sp_server_info",
)
ALLOWED_PROCEDURE_CALL = re.compile(
    r"\bEXEC(?:UTE)?\s+(?:(?:master|sys|dbo)\s*\.\s*)*(?:" + "|".join(ALLOWED_PROCEDURES) + r")\b",
    re.IGNORECASE,
)
ALLOWED_DBCC = re.compile(r"\bDBCC\s+(?:SQLPERF|INPUTBUFFER|OPENTRAN|SHOW_STATISTICS|TRACESTATUS|USEROPTIONS)\b",
                          re.IGNORECASE)
FIRST_KEYWORDS = ("SELECT", "WITH", "SET", "DECLARE", "IF", "BEGIN", "EXEC", "EXECUTE", "DBCC", "CREATE", "INSERT", "DROP")
DATABASE_NAME = re.compile(r"^[^\x00-\x1f\[\]]{1,128}$")


def strip_literals_and_comments(sql):
    """Remove comments, string literals, and delimited identifiers so that only T-SQL keywords remain."""
    pattern = re.compile(r"--[^\n]*|/\*.*?\*/|N?'(?:[^']|'')*'|\[(?:[^\]]|\]\])*\]|\"(?:[^\"]|\"\")*\"", re.DOTALL)
    return pattern.sub(" ", sql)


def validate_sql(sql):
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql is required")
    if len(sql) > MAX_SQL_CHARS:
        raise ValueError(f"sql is longer than {MAX_SQL_CHARS} characters")
    if "/*" in re.sub(r"N?'(?:[^']|'')*'", "''", sql) and "*/" not in sql:
        raise ValueError("unterminated comment")
    code = strip_literals_and_comments(sql)
    if re.search(r"^\s*GO\s*$", code, re.IGNORECASE | re.MULTILINE):
        raise ValueError("GO batch separators are not supported; send one batch")
    phrase = BLOCKED_PHRASES.search(code)
    if phrase:
        raise ValueError(f"read-only queries only; blocked statement: {phrase.group(0).upper()}")
    remaining = ALLOWED_TEMP_FORMS.sub(" ", code)
    remaining = ALLOWED_PROCEDURE_CALL.sub(" ", remaining)
    remaining = ALLOWED_DBCC.sub(" ", remaining)
    remaining = re.sub(r"\bUSE\s+(?:HINT|PLAN)\b", " ", remaining, flags=re.IGNORECASE)
    blocked = sorted({word.upper() for word in re.findall(r"[A-Za-z_]+", remaining)} & set(BLOCKED_KEYWORDS))
    if blocked:
        raise ValueError(
            "read-only queries only; blocked keyword(s): " + ", ".join(blocked)
            + ". Temporary tables (#t, @t), EXEC of " + ", ".join(ALLOWED_PROCEDURES)
            + ", and DBCC SQLPERF/INPUTBUFFER/OPENTRAN/SHOW_STATISTICS/TRACESTATUS/USEROPTIONS are allowed."
        )
    first = re.match(r"\s*;*\s*\(?\s*([A-Za-z_]+)", code)
    # A bare procedure name as the first statement would run it without EXEC.
    if not first or first.group(1).upper() not in FIRST_KEYWORDS:
        raise ValueError("the batch must start with SELECT, WITH, SET, DECLARE, IF, BEGIN TRY, EXEC of an allowed procedure, "
                         "or an allowed DBCC command")
    return sql


def validate_options(database, max_rows, timeout_seconds):
    database = (database or "master").strip()
    if not DATABASE_NAME.match(database):
        raise ValueError("invalid database name")
    max_rows = DEFAULT_MAX_ROWS if max_rows in (None, "", 0) else int(max_rows)
    timeout_seconds = DEFAULT_TIMEOUT_SECONDS if timeout_seconds in (None, "", 0) else int(timeout_seconds)
    if not 1 <= max_rows <= MAX_ROWS:
        raise ValueError(f"max_rows must be between 1 and {MAX_ROWS}")
    if not 5 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be between 5 and {MAX_TIMEOUT_SECONDS}")
    return database, max_rows, timeout_seconds


def to_json_value(value):
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return "0x" + value.hex()
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "...(truncated)"
    return value


def read_result_sets(cursor, max_rows):
    result_sets = []
    more = True
    while more and len(result_sets) < MAX_RESULT_SETS:
        if cursor.description:
            columns = [column[0] or f"column{index + 1}" for index, column in enumerate(cursor.description)]
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                cursor.fetchall()
            result_sets.append({
                "columns": columns,
                "rows": [[to_json_value(value) for value in row] for row in rows[:max_rows]],
                "row_count": min(len(rows), max_rows),
                "truncated": truncated,
            })
        more = cursor.nextset()
    return result_sets


def _password(credential=None):
    if credential is None:
        if ManagedIdentityCredential is None:
            raise RuntimeError("azure-identity is not installed")
        credential = ManagedIdentityCredential(client_id=AGENT_CLIENT_ID)
    token = credential.get_token(KEY_VAULT_SCOPE).token
    response = requests.get(
        f"https://{KEY_VAULT_NAME}.vault.azure.net/secrets/{SECRET_NAME}?api-version=7.4",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["value"]


def _connect(password, database, timeout_seconds):
    if pymssql is None:
        raise RuntimeError("pymssql is not installed")
    # autocommit stays off: pymssql opens a transaction that is rolled back below.
    return pymssql.connect(
        server=SQL_HOST,
        port=int(SQL_PORT),
        user=SQL_LOGIN,
        password=password,
        database=database,
        login_timeout=LOGIN_TIMEOUT_SECONDS,
        timeout=timeout_seconds,
        appname=APP_NAME,
        tds_version="7.4",
        encryption="require",
        read_only=True,
        autocommit=False,
    )


def run(connection, sql, max_rows):
    cursor = connection.cursor()
    try:
        cursor.execute(f"SET LOCK_TIMEOUT {LOCK_TIMEOUT_MS}; SET DEADLOCK_PRIORITY LOW;")
        cursor.execute(sql)
        return read_result_sets(cursor, max_rows)
    finally:
        try:
            connection.rollback()
        except Exception:  # pragma: no cover - a broken connection has nothing to roll back
            pass


def main(sql: str, database: str = "master", max_rows: int = DEFAULT_MAX_ROWS,
         timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    started = time.time()
    try:
        validate_sql(sql)
        database, max_rows, timeout_seconds = validate_options(database, max_rows, timeout_seconds)
        connection = _connect(_password(), database, timeout_seconds)
        try:
            result_sets = run(connection, sql, max_rows)
        finally:
            connection.close()
        return {
            "success": True,
            "sql_server": f"{SQL_HOST}:{SQL_PORT}",
            "database": database,
            "executed_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration_seconds": round(time.time() - started, 1),
            "result_sets": result_sets,
            "note": "Executed read-only and rolled back. Use the server DMVs; user table data is not readable.",
        }
    except Exception as exc:  # return SQL Server errors to the agent so it can correct the query
        message = str(exc)
        if isinstance(getattr(exc, "args", None), tuple) and exc.args and isinstance(exc.args[-1], bytes):
            message = exc.args[-1].decode("utf-8", "replace")
        return {
            "success": False,
            "sql_server": f"{SQL_HOST}:{SQL_PORT}",
            "database": database,
            "error": f"{type(exc).__name__}: {message[:800]}",
        }
