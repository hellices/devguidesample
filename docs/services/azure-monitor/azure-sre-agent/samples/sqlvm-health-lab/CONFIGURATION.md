# SQL Server VM 점검 실습 구성 상세

이 문서는 [SRE Agent 실습](../../sql-server-vm-health-check/index.md)과
[Grafana 실습](../../sql-server-vm-grafana/index.md)의 설정값, 설계 근거, 검증 방법,
문제 해결을 모은 참고 자료입니다. 실습의 목적과 동작 방식은 두 문서를 먼저 읽습니다.

## 네트워크


| 서브넷 | 주소 | 용도 | 아웃바운드 |
| --- | --- | --- | --- |
| `snet-sql` | `10.42.1.0/24` | SQL Server VM, 고정 사설 IP `10.42.1.4` | NAT Gateway |
| `snet-agent` | `10.42.2.0/27` | SRE Agent 위임 서브넷 | NAT Gateway |
| `snet-endpoint` | `10.42.3.0/27` | Key Vault Private Endpoint `10.42.3.4` | 없음 |

`snet-sql` NSG의 인바운드 규칙은 다음 두 개입니다. 기본 규칙
`AllowVnetInBound`보다 우선순위가 높아 같은 VNet의 다른 서브넷도 1433에
접근하지 못합니다.

| 우선순위 | 이름 | 원본 | 포트 | 동작 |
| --- | --- | --- | --- | --- |
| 100 | `allow-sql-from-sre-agent` | `10.42.2.0/27` | 1433 | 허용 |
| 200 | `deny-sql-from-other-sources` | `*` | 1433 | 거부 |

모든 서브넷은 `defaultOutboundAccess: false`인 private subnet입니다. SQL VM의
Windows Update·정품 인증과 에이전트의 ARM·Log Analytics 호출은 NAT Gateway로
나갑니다. Key Vault는 `privatelink.vaultcore.azure.net` 사설 DNS 영역을 VNet에
연결하고, 에이전트의 **VNet 사설 DNS 사용**(`usePrivateDnsResolution: true`)으로
사설 IP를 해석합니다.

에이전트 리소스의 네트워크 설정은 다음과 같습니다.

```bicep
vnetConfiguration: {
  subnetResourceId: agentSubnetId
}
sandboxConfiguration: {
  egress: {
    mode: 'AzureVNet'
    allowedHosts: []
    allowedRegistries: [ 'pypi' ]
    allowedCodeRepositories: []
    allowHttpMcpServerNetworkAccess: false
    vnetConfiguration: { usePrivateDnsResolution: true }
  }
  packages: [
    { name: 'pymssql', version: '2.4.5', packageManager: 'pip' }
  ]
}
```

`allowedRegistries`의 `pypi`는 패키지 설치만 에이전트 인프라 네트워크로 보내는
우회 설정입니다. 원격 MCP와 코드 저장소 우회는 끕니다.

## 설계 결정

| 결정 | 이유 |
| --- | --- |
| 에이전트를 Azure VNet 모드로 통합 | 이 모드에서는 비플랫폼 아웃바운드 트래픽이 위임 서브넷을 지나며, NSG·사설 DNS·네트워크 로그가 그대로 적용됩니다. |
| 에이전트 전용 /27 서브넷을 `Microsoft.App/environments`에 위임 | Azure VNet 모드의 서브넷 요구 사항입니다. 다른 서비스와 공유할 수 없습니다. |
| SQL 연결 유형 Private, NSG에서 에이전트 서브넷만 1433 허용 | Private 연결은 VNet 안에서 SQL Server에 접속하게 하고 외부용 NSG 규칙을 만들지 않습니다. 같은 VNet의 다른 서브넷도 명시적 거부 규칙으로 막습니다. |
| 에이전트 전용 SQL 로그인 `sre_monitor` | 서버 상태·메타데이터 읽기 권한과 `msdb`의 백업·작업 이력 SELECT만 부여합니다. 사용자 DB에는 연결만 할 수 있고 테이블 데이터는 읽지 못합니다. |
| 비밀번호를 Private Endpoint 전용 Key Vault에 저장 | Python 도구 코드에 비밀을 넣지 않고, 공용 네트워크에서 데이터 평면 접근을 막습니다. |
| TLS 필수(`encryption='require'`)와 `read_only=True` | VNet 내부에서도 자격 증명과 결과를 평문으로 보내지 않습니다. 첫 배포에서는 기본값으로 연결해 `encrypt_option=FALSE`가 관측되었습니다. |
| SQL 드라이버 `pymssql`을 sandbox에 사전 설치 | 도구 정의의 `dependencies`만으로는 Azure VNet 모드에서 설치되지 않았습니다(관측). 공식 `zava-aks-postgres` lab과 같은 방식으로 `sandboxConfiguration.packages`를 씁니다. |
| 고정 점검과 직접 SQL 도구를 분리 | 반복 점검은 `SqlServerHealthCheck`의 고정 `operation`으로 같은 기준을 유지하고, 세부 원인은 `SqlServerQuery`로 에이전트가 쓴 T-SQL을 실행합니다. 직접 SQL도 같은 읽기 전용 로그인으로 실행되며 항상 롤백됩니다. |
| 시점 비교는 exporter 시계열에 맡김 | 행 증가량처럼 과거 값이 필요한 점검은 [Grafana 실습](../../sql-server-vm-grafana/index.md)이 쌓는 시계열을 `SqlServerMetricsQuery`로 PromQL 조회합니다. SQL Server에 이력 테이블을 만들지 않습니다. |

## 권한


| 주체 | 범위 | 역할 |
| --- | --- | --- |
| 에이전트 UAMI·시스템 MI | 실습 리소스 그룹 | Reader, Monitoring Reader, Log Analytics Reader |
| 에이전트 UAMI | Key Vault | Key Vault Secrets User |
| 에이전트 UAMI | Azure Monitor workspace | Monitoring Data Reader (PromQL 조회) |
| 에이전트 UAMI | 에이전트 리소스 | SRE Agent Administrator (공식 템플릿과 동일) |
| 배포한 사용자 | 에이전트 리소스 | SRE Agent Administrator |

에이전트는 VM에서 명령을 실행할 Azure 권한이 없습니다. SQL Server 안에서도
`sre_monitor`는 다음 권한만 가집니다.

```sql
GRANT VIEW SERVER STATE, VIEW ANY DEFINITION, CONNECT ANY DATABASE TO [sre_monitor];
USE msdb;
CREATE USER [sre_monitor] FOR LOGIN [sre_monitor];
GRANT SELECT ON dbo.backupset TO [sre_monitor];
GRANT SELECT ON dbo.sysjobs TO [sre_monitor];
GRANT SELECT ON dbo.sysjobhistory TO [sre_monitor];
```

| 권한 | 필요한 점검 | 근거 |
| --- | --- | --- |
| `VIEW SERVER STATE` | 대기, 요청, 잠금(`sys.dm_tran_locks`), 이벤트 파일 읽기 | 서버 범위 DMV 요구 권한. SQL Server 2022에서는 하위 권한인 `VIEW SERVER PERFORMANCE STATE`를 포함 |
| `VIEW ANY DEFINITION` | 다른 SQL 로그인의 잠금 상태(`sys.sql_logins`), 테이블 이름과 행 수(`sys.dm_db_partition_stats`), 파일 목록 | `sys.sql_logins`는 자신과 `sa` 외 로그인을 보려면 추가 권한이 필요하고, `sys.dm_db_partition_stats`는 성능 상태와 보안 정의 권한을 함께 요구 |
| `CONNECT ANY DATABASE` | 사용자 DB의 Query Store와 테이블 메타데이터 | 현재·미래의 모든 DB에 연결만 허용. 데이터 읽기 권한은 주지 않음 |
| `msdb` 세 테이블 SELECT | 마지막 백업, SQL Agent 작업 목록과 실행 이력 | 백업·작업 이력은 `msdb` 테이블에만 있음 |

SQL Server 2022의 세분화된 권한(`VIEW SERVER PERFORMANCE STATE`,
`VIEW ANY PERFORMANCE DEFINITION`)만으로 시험했을 때는 `sys.dm_db_partition_stats`에서
테이블 이름을 얻지 못했습니다(관측). 그래서 위 조합으로 정했고, 같은 VM에서
`sre_monitor`로 테이블 데이터를 SELECT하면 권한 오류가 나는 것을 확인했습니다.

## 배포 단계


sample은 [samples/sqlvm-health-lab](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab)에 있습니다.

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab
./scripts/deploy.sh rg-sqlvm-sre-lab koreacentral
```

1. `infra/main.bicep`을 구독 범위로 배포합니다. VNet·NSG·NAT Gateway, SQL Server
   2022 Developer on Windows Server 2022(`MicrosoftSQLServer:sql2022-ws2022:sqldev-gen2`),
   SQL IaaS Agent 등록(Private, 1433), Key Vault와 Private Endpoint·사설 DNS,
   Log Analytics·Application Insights, 에이전트 UAMI와 VNet 통합
   `Microsoft.App/agents`, 역할 할당을 만듭니다.
2. `scripts/configure-sql.sh`가 VMAccess로 로컬 관리자 비밀번호를 일회용 값으로
   재설정하고, managed Run Command를 그 계정으로 실행해 다음을 처리합니다.
   - SQL Server 인증 모드를 혼합 모드로 바꾸고 서비스를 한 번 재시작
   - `sre_monitor` 로그인 생성 또는 비밀번호 교체와 권한 부여
   - `SreDemo` DB(FULL 복구 모델, 50만 행 `dbo.Orders`, `CustomerId` 인덱스 없음,
     증가 관찰용 `dbo.AuditEvents`) 생성
   - `configure-checks.ps1`: 로그인 감사용 Extended Events 세션 `sre_login_audit`,
     점검 대상 데모 로그인, 데모 SQL Agent 작업 생성(아래 표)

   이어서 `sre_monitor` 비밀번호를 ARM(`management.azure.com`) 경로로 Key Vault
   비밀 `sql-monitor-password`에 씁니다. Key Vault 방화벽은 데이터 평면에만
   적용되므로 공용 액세스가 꺼진 상태에서도 제어 평면으로 비밀을 만들 수
   있습니다. 일회용 관리자 비밀번호는 저장하지 않습니다.
3. `scripts/apply-agent-config.sh`가 에이전트 데이터 평면에 Python 도구와 스킬을
   등록합니다.

| `configure-checks.ps1`이 만드는 대상 | 점검 목적 |
| --- | --- |
| XE 세션 `sre_login_audit`: `error_reported`(오류 18456)와 풀 재사용이 아닌 `login`(`is_cached = 0`) 이벤트, 오류 로그 폴더의 `event_file` 대상(10MB × 4개) | 로그인 실패·성공의 계정, 클라이언트 주소, 호스트, 애플리케이션 |
| `app_user` (`CHECK_POLICY = ON`) | 잘못된 비밀번호로 잠기는 계정. SQL 로그인은 Windows 계정 잠금 정책을 따르며, 이 VM은 임계값 10회·잠금 10분(관측) |
| `legacy_report` (`DISABLE`) | 사용 중지 계정 |
| SQL Agent 작업 `sre-demo-nightly-check`(30분마다 실패), `sre-demo-update-stats`(매시 성공) | 작업 실패와 오류 메시지 |

| 등록 대상 | 데이터 평면 요청 |
| --- | --- |
| `SqlServerHealthCheck`, `SqlServerQuery`, `SqlServerMetricsQuery` (`PythonFunctionTool`) | `PUT /api/v1/extendedAgent/apply`, `ToolList` 본문, `application/x-yaml` |
| `sql-server-vm-health-check` 스킬 | `PUT /api/v2/extendedAgent/skills/{name}` |

두 경로는 공식 `microsoft/sre-agent` 저장소의 lab 스크립트 방식을 따릅니다.
도구 코드의 `@@SQL_HOST@@`, `@@KEY_VAULT_NAME@@`, `@@AGENT_CLIENT_ID@@`,
`@@PROMETHEUS_QUERY_ENDPOINT@@` 같은 값은 등록 직전에 `scripts/render_agent_config.py`가 채웁니다. 등록 응답은
HTTP 202이므로, 도구를 바꾼 직후 호출하면 이전 버전이 실행될 수 있습니다.
`GET /api/v1/extendedAgent/tools`로 반영을 확인한 뒤 새 대화에서 호출합니다.

## 연결 출처와 TLS 확인


SQL Server가 보는 도구 연결 정보를 `overview` 결과에 포함했습니다. 에이전트에게
값만 그대로 보여 달라고 요청한 결과입니다.

| 필드 | 값 |
| --- | --- |
| `success` | `true` |
| `sql_server` | `10.42.1.4:1433` |
| `data.overview.tool_client_address` | `10.42.2.5` (`snet-agent`) |
| `data.overview.tool_connection_encrypted` | `TRUE` |

## 지표 파이프라인

| 결정 | 이유 |
| --- | --- |
| exporter와 Prometheus는 루프백 주소에만 바인딩 | 지표 엔드포인트를 네트워크에 노출하지 않습니다. NSG 규칙도 추가하지 않습니다. |
| sql_exporter를 가상 서비스 계정 `NT SERVICE\SqlExporterSvc`로 실행 | DSN에 사용자가 없으면 go-mssqldb가 Windows에서 SSO를 사용합니다. 저장할 비밀번호가 없습니다. |
| 해당 로그인에 `VIEW SERVER STATE`, `VIEW ANY DEFINITION`, `CONNECT ANY DATABASE`와 `msdb`의 `backupset`·`sysjobs`·`sysjobhistory` SELECT만 부여 | 로그인 상태, 테이블 행 수, 각 DB의 Query Store와 파일 사용량을 읽는 최소 조합입니다. 사용자 테이블을 SELECT하면 오류 229로 거부됩니다(관측). 권한별 근거는 [SRE Agent 실습](../../sql-server-vm-health-check/index.md)에 정리했습니다. |
| Prometheus는 agent 모드(`--agent`) | 로컬 쿼리·저장 없이 수집과 remote write만 합니다. |
| VM 전용 사용자 할당 관리 ID로 remote write | Azure VM의 사용자 할당 관리 ID 인증은 Prometheus 2.45 이상에서 지원합니다. 이 실습은 3.15.1을 씁니다. |
| Monitoring Metrics Publisher는 workspace의 기본 DCR에만 부여 | 공식 절차가 지정한 범위입니다. |
| Grafana 관리 ID의 Monitoring Data Reader는 workspace에만 부여 | Bicep으로 만든 Grafana에는 이 할당 하나만 있었습니다(관측). 포털 흐름처럼 구독 범위로 넓히지 않습니다. |
| 다운로드 파일은 버전과 SHA256으로 고정 | GitHub 릴리스 자산의 digest와 일치할 때만 설치합니다. |

## 지표 파이프라인 배포


sample은 [samples/sqlvm-health-lab](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab)에 있습니다.

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/sqlvm-health-lab
./scripts/deploy.sh rg-sqlvm-sre-lab koreacentral
```

SRE Agent 실습의 단계 뒤에 다음이 이어집니다.

1. Bicep이 Azure Monitor workspace(`Microsoft.Monitor/accounts`), Azure Managed
   Grafana(`Microsoft.Dashboard/grafana`, Standard, 시스템 관리 ID), VM의 지표용
   사용자 할당 관리 ID를 만듭니다. Grafana에는
   `grafanaIntegrations.azureMonitorWorkspaceIntegrations`로 workspace를 연결해
   Prometheus 데이터 원본을 자동으로 만듭니다.
2. `scripts/configure-monitoring.sh`가 workspace의 기본 DCR·DCE에서 remote write
   URL을 조합하고, VM 관리 ID에 DCR의 Monitoring Metrics Publisher를 부여합니다.
3. 같은 스크립트가 managed Run Command로 VM에서 두 단계를 실행합니다.
   - `configure-monitoring.ps1` (LocalSystem): 세 바이너리 다운로드·SHA256 확인,
     windows_exporter MSI 설치, sql_exporter 서비스 등록, Prometheus 에이전트
     예약 작업 등록
   - `grant-exporter-login.ps1` (일회용 비밀번호로 재설정한 로컬 관리자): SQL
     Server 로그인 생성과 권한 부여, sql_exporter 재시작, remote write 카운터 보고

   sql_exporter는 세 collector 파일을 읽습니다. `mssql_health`(30초마다),
   `mssql_audit`(로그인 이벤트, 1분 캐시), `mssql_inventory`(Query Store·스토리지·
   테이블, 5분 캐시)입니다. 로그인 이벤트는 SRE Agent 실습의 `configure-checks.ps1`이
   만든 XE 세션 `sre_login_audit`에서 읽습니다.
4. `scripts/import-dashboard.sh`가 Grafana의 Prometheus 데이터 원본 UID를 찾아
   대시보드를 가져옵니다.

`configure-monitoring.sh`의 마지막 출력에서 remote write 상태를 확인합니다.

```text
prometheus_remote_storage_samples_failed_total{...} 0
prometheus_remote_storage_samples_retried_total{...} 0
prometheus_remote_storage_samples_total{...} 7242
```

공식 문서에 따르면 역할 할당이 적용되기까지 약 30분이 걸릴 수 있고, 그동안
Prometheus 로그에 HTTP 403이 보일 수 있습니다. 이 실습에서는 첫 실행부터 실패가
없었습니다.

## 대시보드 검증


`scripts/verify_dashboard_queries.py`는 대시보드의 모든 패널 쿼리를 Azure
Monitor workspace의 PromQL 엔드포인트에 실행합니다. CPU 부하
(`./scripts/generate-load.sh cpu 30`) 중의 결과 일부입니다.

| 패널 | 결과 |
| --- | --- |
| 수집 상태 | `1` (UP) |
| Batch requests/s | 약 61 |
| CPU 사용률 (VM 전체) | 약 77.9% |
| Page life expectancy | 14,688초 |
| Signal wait 비율 | 약 0.99 |
| 상위 10개 대기 유형 | 10개 시계열 |
| 마지막 백업 | 4개 DB × 전체·로그 = 8개 행 |
| 데이터베이스 크기 | 7개 DB × 데이터·로그 = 14개 시계열 |
| 문제 DB: 오프라인·로그 재사용 대기 | 0개 (정상) |

확장 패널은 데모 부하를 함께 실행한 2026-10-27 17:3x~17:5x UTC에 같은 스크립트로
확인했습니다.

| 패널 | 결과 |
| --- | --- |
| SQL 로그인 상태 | `app_user` 잠김 1·잘못된 비밀번호 10회(`badlogin` 직후), `legacy_report`·`sa` 사용 중지 |
| 로그인 실패 (최근 1시간) | `app_user`(비밀번호 불일치)·`scanner`(로그인 없음) 각 48건, 클라이언트 `127.0.0.1` |
| 1시간 행 증가량 | `dbo.AuditEvents` 약 234,000행, `dbo.Orders` 0 |
| 작업 상태 | `sre-demo-nightly-check` 금일 실패 5회 |
| 금일 상위 쿼리 | `SreDemo`의 6개 `query_hash`. 점검 쿼리는 제외됨 |
| 보유·대기 중인 잠금 (`blocking` 중) | `S`/`WAIT` 3, `IX`/`GRANT` 31, `IS`/`GRANT` 6 |
| 현재 차단 관계 (`blocking` 중) | 차단 세션 77(`sre-demo-load`), 대기 리소스 `KEY` |

Grafana 쪽 경로는 Grafana HTTP API `/api/ds/query`를 Microsoft Entra 토큰으로
호출해 확인했습니다. 두 쿼리 모두 HTTP 200을 반환했고 상위 대기는
`sos_scheduler_yield`였습니다.

```bash
TOKEN=$(az account get-access-token --resource ce34e7e5-485f-4d76-964f-b3d2b16d1e4f --query accessToken -o tsv)
curl -sS -X POST "$GRAFANA_ENDPOINT/api/ds/query" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" --data @query.json
```

## 문제 해결

### SRE Agent와 SQL Server


| 증상 | 원인 | 대응 |
| --- | --- | --- |
| 도구가 `pymssql is not installed` 반환, 에이전트는 판정 불가 보고 | 도구 정의의 `dependencies`가 Azure VNet 모드에서 설치되지 않음(관측) | `sandboxConfiguration.packages`로 `pymssql`을 sandbox에 사전 설치합니다. |
| SQL Server에서 도구 연결의 `encrypt_option`이 `FALSE` | `pymssql` 기본 암호화 설정 `request`로는 TLS가 협상되지 않음(관측) | `tds_version='7.4'`, `encryption='require'`를 지정합니다. |
| 도구를 바꾼 직후 새 필드가 결과에 없음 | 도구 등록 API가 비동기(HTTP 202)로 반영됨 | 저장된 도구 코드를 조회해 반영을 확인한 뒤 새 대화에서 호출합니다. |
| Key Vault를 공용 액세스로 만들었는데 `Disabled`로 바뀜 | 테넌트 수준 보안 통제가 공용 액세스를 끔(이 실습 구독에서 관측) | 처음부터 공용 액세스를 끄고 Private Endpoint와 사설 DNS로만 접근합니다. 비밀 쓰기는 ARM 제어 평면을 씁니다. |
| `az deployment sub create`가 끝났는데 배포는 계속 `Running` | SQL IaaS Agent 등록이 오래 걸림 | `deploy.sh`는 `--no-wait` 후 `az deployment sub wait`로 최종 상태를 확인합니다. |
| 재배포 뒤 SQL 로그인 `Login failed` | 연결 유형이 같으면 SQL IaaS Agent가 바뀐 SQL 인증 비밀번호를 다시 적용하지 않음(관측) | SQL IaaS Agent의 SQL 인증 설정을 쓰지 않고, 설정 스크립트가 매번 `sre_monitor` 비밀번호를 교체해 Key Vault에 씁니다. |
| 잠금 부하에서 차단이 보이지 않음 | `SET Status = Status`는 값이 바뀌지 않아 충돌 잠금이 유지되지 않음 | 부하 스크립트는 실제 값을 바꾼 뒤 롤백합니다. |
| 에이전트가 "잠금 보유 세션과 테이블을 확정할 수 없다"고 보고 | 잠금 요약이 DB·모드별 개수만 반환 | `locks`에 세션별 테이블 잠금(`held_table_locks`)을 추가하고, `KEY`·`PAGE`·`RID` 잠금은 `sys.partitions.hobt_id`로 테이블 이름을 찾습니다. |
| 에이전트가 계정 상태 결과가 잘려 잠긴 계정 여부를 확정하지 못함 | 긴 도구 결과의 앞부분이 잘림(관측) | `security`가 `locked`, `disabled` 같은 결론 목록을 먼저 반환하고 빈 값을 제거합니다. |
| 로그인 실패가 있었는데 0건 | `ring_buffer` 대상의 XML이 `truncated=1`로 잘려 새 이벤트가 빠짐(관측) | `event_file` 대상으로 바꾸고 `sys.fn_xe_file_target_read_file`로 읽습니다. |
| 이벤트 파일을 `timestamp_utc > ...`로 거르면 0건 | 같은 조건을 `CASE`로 세면 287건인데 `WHERE`에서는 0건(SQL Server 2022, 관측) | 공식 예제처럼 `CAST(timestamp_utc AS datetime2(7))`로 비교합니다. |
| 이벤트 XML을 읽는 쿼리가 오류 1934 | XML 데이터 형식 메서드는 `QUOTED_IDENTIFIER ON`이 필요한데 드라이버 세션 기본값이 아님 | 쿼리 앞에 `SET QUOTED_IDENTIFIER ON;`을 둡니다. |
| 로그인 실패가 두 배로 집계 | 실패 한 번에 오류 18456 이벤트가 두 번 발생. 오류 로그용 메시지에만 `[CLIENT: ...]`가 있음 | 메시지에 `[CLIENT: ...]`가 있는 이벤트만 셉니다. |
| 금일 상위 쿼리에 점검 쿼리가 나옴 | exporter와 도구가 DB마다 실행하는 메타데이터 쿼리도 Query Store에 기록됨 | `query_store_runtime_stats`, `dm_db_partition_stats`, `sys.database_files`를 포함한 문장을 제외합니다. |
| 관리자 RunAs 스크립트가 출력 없이 `System error ... 'Incorrect function.'` | 스크립트가 종료 코드 1로 끝나면 managed Run Command가 이 메시지만 반환(관측) | 스크립트를 `try`/`catch`로 감싸 `C:\SreLab`에 로그를 남기고, SYSTEM으로 실행한 별도 Run Command로 로그를 읽습니다. |
| 실습 중 VM이 `Deallocated`로 바뀜 | 실습과 무관한 구독 자동화(서비스 주체)가 VM 할당을 해제함(활동 로그에서 관측) | `az vm start`로 시작합니다. SQL Server, exporter 서비스, Prometheus 예약 작업은 자동으로 다시 시작됩니다. |

### exporter와 Grafana


| 증상 | 원인 | 대응 |
| --- | --- | --- |
| windows_exporter 서비스가 시작 직후 중지, 이벤트 로그에 `unknown collector cs` | v0.32.0에 `cs` collector가 없음(관측) | 수집기 목록을 `cpu,logical_disk,memory,net,os,system,mssql`로 지정합니다. |
| RunAs로 실행한 스크립트가 출력 없이 `System error ... 'Incorrect function.'` | 스크립트가 종료 코드 1로 끝나면 managed Run Command가 이 메시지만 반환(관측). 처음에는 스크립트 크기 문제로 오인했음 | 스크립트를 `try`/`catch`로 감싸 로그 파일을 남기고 SYSTEM Run Command로 읽어 실제 오류를 확인합니다. 설치는 LocalSystem, SQL 로그인 생성만 RunAs로 나눈 구성은 유지합니다. |
| 재실행 시 `prometheus.exe ... being used by another process` | 예약 작업의 재시작 설정이 중지한 Prometheus를 다시 띄움(관측) | 바이너리 교체 전에 예약 작업을 비활성화하고, 같은 해시의 바이너리는 복사하지 않습니다. |
| sql_exporter 설정을 읽지 못함 | `job`, `instance`는 Prometheus가 예약한 레이블 | SQL Agent 작업 이름 레이블을 `job_name`으로 씁니다. |
| 로그인 실패 패널이 비어 있음 | 세 가지가 겹침(관측): `ring_buffer` XML이 잘림(`truncated=1`), 이벤트 파일을 `WHERE timestamp_utc > ...`로 거르면 0건, XML 메서드가 `QUOTED_IDENTIFIER` 기본값에서 오류 1934 | `event_file` 대상, 공식 예제의 `CAST(timestamp_utc AS datetime2(7))` 비교, 쿼리 앞 `SET QUOTED_IDENTIFIER ON;`을 적용합니다. |
| 로그인 실패가 두 배로 집계 | 실패 한 번에 오류 18456 이벤트가 두 번 발생하고, 오류 로그용 메시지에만 `[CLIENT: ...]`가 있음 | 해당 문자열이 있는 이벤트만 셉니다. |
| 금일 상위 쿼리에 exporter 자체 쿼리가 보임 | DB마다 실행하는 메타데이터 쿼리도 Query Store에 기록됨 | `query_store_runtime_stats`, `dm_db_partition_stats`, `sys.database_files`를 포함한 문장을 제외합니다. |
| 설치 직후 sql_exporter `/metrics`가 HTTP 500 | 서비스 계정의 SQL Server 로그인이 아직 없음 | 설치 단계는 시작 페이지만 확인하고, 로그인 생성 뒤 `/metrics`를 확인합니다. |
| 쿼리 결과의 DB 이름이 `SreDemo`가 아니라 `sredemo` | managed Prometheus는 대소문자를 구분하지 않으며 반환되는 대소문자가 일정하지 않음 | 레이블 값 비교가 대소문자에 의존하지 않게 작성합니다. |
| 테이블에 `microsoft.amwresourceid` 열이 보임 | workspace가 반환하는 시계열에 workspace 리소스 ID 레이블이 붙음(관측) | 테이블 변환에서 해당 열을 숨깁니다. |
| `az grafana data-source query`가 `Invalid time range` 오류 | CLI가 보낸 시간 범위를 workspace가 거부(관측) | Grafana HTTP API `/api/ds/query`에 밀리초 단위 `from`·`to`를 직접 지정합니다. |
