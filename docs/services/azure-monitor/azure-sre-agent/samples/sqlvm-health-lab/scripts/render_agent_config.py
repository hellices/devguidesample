"""Render SRE Agent data-plane request bodies for the SQL VM health-check lab.

Usage:
    python3 render_agent_config.py tool  <state.json>  > tool.json
    python3 render_agent_config.py skill <state.json>  > skill.json
"""

import json
import re
import sys
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
TOOL_NAME = "SqlServerHealthCheck"
METRICS_TOOL_NAME = "SqlServerMetricsQuery"
QUERY_TOOL_NAME = "SqlServerQuery"
SKILL_NAME = "sql-server-vm-health-check"
OPERATIONS_HELP = (
    "One of: summary (start here), overview, cpu, waits, memory, top_queries, active_requests, "
    "databases, backups, io, missing_indexes, long_running, locks, today_queries, slow_queries, "
    "security, login_attempts, storage, table_growth, jobs."
)


PLACEHOLDER_PATTERN = re.compile(r"@@[A-Z_]+@@")
PLACEHOLDERS = {
    "@@PROMETHEUS_QUERY_ENDPOINT@@": "prometheusQueryEndpoint",
    "@@VM_NAME@@": "vmName",
    "@@SQL_HOST@@": "sqlHost",
    "@@SQL_PORT@@": "sqlPort",
    "@@SQL_LOGIN@@": "sqlLogin",
    "@@KEY_VAULT_NAME@@": "keyVaultName",
    "@@SECRET_NAME@@": "secretName",
    "@@AGENT_CLIENT_ID@@": "agentIdentityClientId",
}


def render_tool_code(state, source="sql_server_health_check.py"):
    rendered = (SAMPLE_DIR / "agent/tools" / source).read_text(encoding="utf-8")
    for placeholder, key in PLACEHOLDERS.items():
        rendered = rendered.replace(placeholder, str(state[key]))
    # T-SQL itself uses @@SERVERNAME and @@SPID, so look only for @@NAME@@ placeholders.
    if PLACEHOLDER_PATTERN.search(rendered):
        raise ValueError("unrendered placeholder in tool code")
    return rendered


def tool_body(state):
    """ToolList body accepted by PUT /api/v1/extendedAgent/apply (JSON is valid YAML)."""
    health = {
        "name": TOOL_NAME,
        "type": "PythonFunctionTool",
        "description": (
            "Read-only SQL Server checks for the lab SQL Server VM. Connects over the agent's VNet to the "
            "SQL Server private IP with a monitoring login that can read server state and metadata but no "
            "table data. Operations cover health (CPU, waits, memory, databases, backups, IO), locks and "
            "blocking chains, long-running requests, today's and slow queries from Query Store, SQL login "
            "lockout and login attempts, storage, table sizes, and SQL Agent jobs. Accepts only a fixed "
            "operation name."
        ),
        "function_code": render_tool_code(state),
        "timeout_seconds": 180,
        "dependencies": ["pymssql", "azure-identity", "requests"],
        "parameters": [
            {
                "name": "operation",
                "type": "string",
                "required": False,
                "description": OPERATIONS_HELP,
                "target": "direct",
            }
        ],
    }
    metrics = {
        "name": METRICS_TOOL_NAME,
        "type": "PythonFunctionTool",
        "description": (
            "Read-only PromQL query against the Azure Monitor workspace that stores the SQL Server exporter "
            "metrics (windows_exporter windows_mssql_*, sql_exporter mssql_*). Use it for trends and growth "
            "over time, for example delta(mssql_table_rows[24h]). Every series has the label "
            f"sql_vm=\"{state['vmName']}\". Set lookback_minutes to run a range query."
        ),
        "function_code": render_tool_code(state, "sql_server_metrics_query.py"),
        "timeout_seconds": 90,
        "dependencies": ["azure-identity", "requests"],
        "parameters": [
            {"name": "promql", "type": "string", "required": True,
             "description": "PromQL expression.", "target": "direct"},
            {"name": "lookback_minutes", "type": "integer", "required": False,
             "description": "0 (default) for an instant query, or the range length in minutes (max 10080).",
             "target": "direct"},
            {"name": "step_seconds", "type": "integer", "required": False,
             "description": "Range query step in seconds (30-3600, default 300).", "target": "direct"},
        ],
    }
    query = {
        "name": QUERY_TOOL_NAME,
        "type": "PythonFunctionTool",
        "description": (
            "Runs an ad hoc read-only T-SQL batch that you write against the lab SQL Server (DMVs, catalog views, "
            "Query Store, msdb job and backup history) when SqlServerHealthCheck operations do not answer the "
            "question, for example lock waits from sys.dm_os_waiting_tasks and sys.dm_tran_locks. The monitoring "
            "login can read server state and metadata but not user table data. INSERT, UPDATE, DELETE, DDL, "
            "transaction control, dynamic SQL, and EXEC are rejected except temporary tables (#t, @t), "
            "EXEC sp_who/sp_who2/sp_lock/sp_helpdb/sp_helpfile/sp_spaceused/sp_helpindex/sp_helpstats, and "
            "DBCC SQLPERF/INPUTBUFFER/OPENTRAN/SHOW_STATISTICS. The batch runs in a transaction that is always "
            "rolled back, with a 5-second lock timeout. Returns columns and rows per result set."
        ),
        "function_code": render_tool_code(state, "sql_server_query.py"),
        "timeout_seconds": 180,
        "dependencies": ["pymssql", "azure-identity", "requests"],
        "parameters": [
            {"name": "sql", "type": "string", "required": True,
             "description": "One T-SQL batch without GO. Start with SELECT, WITH, SET, DECLARE, IF, EXEC of an "
                            "allowed procedure, or an allowed DBCC command.", "target": "direct"},
            {"name": "database", "type": "string", "required": False,
             "description": "Database context, for example SreDemo for sys.dm_db_* views, sys.tables, or Query "
                            "Store. Default master.", "target": "direct"},
            {"name": "max_rows", "type": "integer", "required": False,
             "description": "Rows returned per result set (1-1000, default 200).", "target": "direct"},
            {"name": "timeout_seconds", "type": "integer", "required": False,
             "description": "Query timeout in seconds (5-120, default 30).", "target": "direct"},
        ],
    }
    return {"api_version": "azuresre.ai/v1", "kind": "ToolList", "spec": {"tools": [health, metrics, query]}}


def skill_body(state):
    content = (SAMPLE_DIR / f"agent/skills/{SKILL_NAME}.md").read_text(encoding="utf-8")
    for placeholder, value in {"@@VM_NAME@@": state["vmName"], "@@RESOURCE_GROUP@@": state["resourceGroup"], "@@SQL_HOST@@": state["sqlHost"]}.items():
        content = content.replace(placeholder, str(value))
    return {
        "name": SKILL_NAME,
        "type": "Skill",
        "tags": [],
        "properties": {
            "description": "Check SQL Server health on the lab SQL Server VM with fixed checks, ad hoc read-only T-SQL, and exporter metrics, and report findings.",
            "tools": [TOOL_NAME, QUERY_TOOL_NAME, METRICS_TOOL_NAME],
            "skillContent": content,
            "additionalFiles": [],
        },
    }


def main(argv):
    kind, state_path = argv[1], argv[2]
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    body = {"tool": tool_body, "skill": skill_body}[kind](state)
    json.dump(body, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main(sys.argv)
