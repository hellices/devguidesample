# SQL Server VM health check with a VNet-integrated Azure SRE Agent

This runnable sample deploys a SQL Server 2022 Developer VM that has only a
private IP, and an Azure SRE Agent integrated with the same virtual network
(Azure VNet egress mode). The agent's `SqlServerHealthCheck` Python tool
connects to SQL Server over TDS (port 1433) from the agent's delegated subnet
with a read-only login (`VIEW SERVER STATE`, `VIEW ANY DEFINITION`,
`CONNECT ANY DATABASE`, and `msdb` backup and job history) and returns JSON for
fixed operations: overall health, held and waiting locks, long-running requests,
today's and slow queries (Query Store), locked or disabled logins, login
attempts (Extended Events), storage, table sizes, and SQL Agent job failures.
The `SqlServerQuery` tool runs an ad hoc read-only T-SQL batch that the agent
writes (for example lock waits from `sys.dm_os_waiting_tasks` and
`sys.dm_tran_locks`): it rejects data-changing, DDL, transaction-control, and
dynamic statements and always rolls back. The `SqlServerMetricsQuery` tool runs PromQL against the Azure Monitor
workspace, for example row growth with `delta(mssql_table_rows[1h])`. The login password lives in a Key Vault that is reachable only
through a private endpoint; the tool reads it with the agent's managed identity.

The same deployment also installs a metrics pipeline on the VM. windows_exporter
(SQL Server performance counters) and sql_exporter (health, audit, and
inventory collectors with the same checks) are
scraped by a Prometheus agent that remote-writes to an Azure Monitor workspace
with the VM's managed identity, and Azure Managed Grafana shows the
`SQL Server VM 상태` dashboard.

Settings, design decisions, verification steps, and troubleshooting are in
[CONFIGURATION.md](CONFIGURATION.md) (Korean).

Follow the lab instructions for the
[SRE Agent health check](../../sql-server-vm-health-check/index.md) and the
[exporter and Grafana dashboard](../../sql-server-vm-grafana/index.md) for the
architecture, permissions, verification, and cleanup.

## Layout

| Path | Purpose |
| --- | --- |
| `infra/main.bicep` | Resource group and the lab module |
| `infra/resources.bicep` | VNet (SQL, agent, endpoint subnets), NSGs, NAT Gateway, SQL VM with PRIVATE connectivity and a metrics identity, Key Vault with private endpoint and private DNS, Log Analytics, Application Insights, Azure Monitor workspace, Azure Managed Grafana, agent identity, VNet-integrated Azure SRE Agent, RBAC |
| `agent/tools/sql_server_health_check.py` | SRE Agent SQL tool source with `@@...@@` placeholders |
| `agent/tools/sql_server_query.py` | SRE Agent tool source for ad hoc read-only T-SQL |
| `agent/tools/sql_server_metrics_query.py` | SRE Agent PromQL tool source for the Azure Monitor workspace |
| `agent/skills/sql-server-vm-health-check.md` | Skill that tells the agent how to call the tool and judge results |
| `scripts/deploy.sh` | End-to-end deployment |
| `scripts/configure-sql.sh` | Creates the `sre_monitor` login, the `SreDemo` database, and the check fixtures; stores the login password in Key Vault |
| `scripts/vm/configure-sql.ps1` | Script that `configure-sql.sh` runs on the VM as the local administrator |
| `scripts/vm/configure-checks.ps1` | Login audit Extended Events session (`event_file`), demo logins `app_user` and `legacy_report`, demo SQL Agent jobs |
| `scripts/apply-agent-config.sh` | Registers the tool and the skill on the agent data plane |
| `monitoring/mssql_health.collector.yml` | sql_exporter collector with the DMV checks that well-known admin scripts start with, plus locks, long-running requests, logins, and jobs |
| `monitoring/mssql_audit.collector.yml` | Failed and new successful logins in the last hour from the audit session (cached 60 s) |
| `monitoring/mssql_inventory.collector.yml` | Today's top queries, volumes, database files, and table rows (cached 300 s) |
| `monitoring/sql_exporter.yml`, `monitoring/prometheus.yml.tmpl` | Exporter and Prometheus agent configuration |
| `monitoring/grafana/sql-server-vm.dashboard.json` | Grafana dashboard |
| `scripts/configure-monitoring.sh` | Installs the exporters and the Prometheus agent on the VM and grants remote-write access |
| `scripts/vm/configure-monitoring.ps1`, `scripts/vm/grant-exporter-login.ps1` | Scripts that `configure-monitoring.sh` runs on the VM |
| `scripts/import-dashboard.sh` | Imports the dashboard into Azure Managed Grafana |
| `scripts/verify_dashboard_queries.py` | Runs every dashboard query against the Azure Monitor workspace |
| `scripts/generate-load.sh`, `scripts/vm/load.ps1` | Starts a `cpu`, `blocking`, `longrun`, `badlogin`, or `growth` demo workload as a scheduled task |
| `scripts/cleanup.sh` | Deletes the resource group and purges the Key Vault |
| `CONFIGURATION.md` | Network, permissions, deployment steps, verification, and troubleshooting details (Korean) |
| `assets/architecture.svg` | Architecture diagram published to both lab pages through `sample.yml` |
| `tests/` | Unit tests for the tools, collectors, dashboard, and renderers |

## Run

Requirements: Azure CLI signed in with Owner (or Contributor + User Access
Administrator) on the subscription, `jq`, `openssl`, `curl`, `python3`, and a
subscription registered for Azure SRE Agent.

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab
./scripts/deploy.sh rg-sqlvm-sre-lab koreacentral
./scripts/generate-load.sh cpu 20
./scripts/generate-load.sh blocking 15
./scripts/generate-load.sh badlogin 15
./scripts/generate-load.sh growth 60
```

Then ask the agent at <https://sre.azure.com>, for example
`sql-server-vm-health-check 스킬로 SQL Server VM 상태를 점검해줘` or
`지금 어떤 세션이 어떤 테이블에 잠금을 잡고 있는지 알려줘`, or open the
Grafana endpoint printed by `deploy.sh` and select the `SQL Server VM 상태`
dashboard. To check every panel query from the command line:

```bash
python3 scripts/verify_dashboard_queries.py .lab-state.json
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

## Clean up

```bash
./scripts/cleanup.sh
```
