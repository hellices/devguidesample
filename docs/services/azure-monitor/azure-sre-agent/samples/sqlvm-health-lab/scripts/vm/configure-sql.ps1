param(
    [string]$MonitorLogin = 'sre_monitor',
    [string]$MonitorPassword
)

# One-time lab preparation, executed through a managed Run Command as the VM
# local administrator (a sysadmin on the SQL Server marketplace image).
# - Enables SQL Server and Windows authentication mode (restarts SQL Server once).
# - Creates the login that Azure SRE Agent uses over the VNet. It can read
#   server state, metadata, and msdb backup/job history, but no table data.
# - Creates the SreDemo database (FULL recovery, no log backups on purpose)
#   with dbo.Orders and dbo.AuditEvents.
# - Lets LocalSystem read/write only SreDemo so scripts/vm/load.ps1 can run.
# With RunAs, a script failure is reported only as "Incorrect function" (exit code 1).
$ErrorActionPreference = 'Stop'

$connectionString = 'Server=localhost;Database=master;Integrated Security=SSPI;Connect Timeout=15;Application Name=sre-lab-setup'

function Invoke-NonQuery([string]$sql, [int]$timeout = 600) {
    $connection = New-Object System.Data.SqlClient.SqlConnection $connectionString
    try {
        $connection.Open()
        $command = $connection.CreateCommand()
        $command.CommandTimeout = $timeout
        $command.CommandText = $sql
        [void]$command.ExecuteNonQuery()
    }
    finally { $connection.Dispose() }
}

if (-not $MonitorPassword) { throw 'MonitorPassword is required.' }

# LoginMode 2 = SQL Server and Windows authentication. The change needs a restart.
$instanceKey = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL').MSSQLSERVER
$loginModePath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\$instanceKey\MSSQLServer"
if ((Get-ItemProperty $loginModePath).LoginMode -ne 2) {
    Set-ItemProperty -Path $loginModePath -Name LoginMode -Value 2
    Restart-Service -Name MSSQLSERVER -Force
    Start-Service -Name SQLSERVERAGENT -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 10
}

$login = $MonitorLogin.Replace(']', ']]')
$password = $MonitorPassword.Replace("'", "''")
Invoke-NonQuery @"
IF SUSER_ID(N'$login') IS NULL
    CREATE LOGIN [$login] WITH PASSWORD = N'$password', CHECK_POLICY = ON, DEFAULT_DATABASE = master;
ELSE
    ALTER LOGIN [$login] WITH PASSWORD = N'$password';
-- DMVs, Query Store, logins, and Extended Events targets; object names; per-database
-- DMVs. None of these grants allow reading table data.
GRANT VIEW SERVER STATE, VIEW ANY DEFINITION, CONNECT ANY DATABASE TO [$login];
"@
Invoke-NonQuery @"
USE msdb;
IF USER_ID(N'$login') IS NULL CREATE USER [$login] FOR LOGIN [$login];
GRANT SELECT ON dbo.backupset TO [$login];
GRANT SELECT ON dbo.sysjobs TO [$login];
GRANT SELECT ON dbo.sysjobhistory TO [$login];
"@

Invoke-NonQuery @"
IF DB_ID(N'SreDemo') IS NULL
BEGIN
    CREATE DATABASE SreDemo;
    ALTER DATABASE SreDemo SET RECOVERY FULL;
END
"@

Invoke-NonQuery @"
USE SreDemo;
IF OBJECT_ID(N'dbo.Orders') IS NULL
BEGIN
    CREATE TABLE dbo.Orders (
        OrderId    int IDENTITY(1, 1) NOT NULL CONSTRAINT PK_Orders PRIMARY KEY,
        CustomerId int            NOT NULL,
        OrderDate  datetime2(0)   NOT NULL,
        Status     tinyint        NOT NULL,
        Amount     decimal(10, 2) NOT NULL,
        Note       char(200)      NOT NULL
    );

    WITH n AS (
        SELECT TOP (500000) ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) AS i
        FROM sys.all_objects AS a CROSS JOIN sys.all_objects AS b)
    INSERT dbo.Orders (CustomerId, OrderDate, Status, Amount, Note)
    SELECT ABS(CHECKSUM(NEWID())) % 20000,
           DATEADD(MINUTE, -CAST(i AS int), SYSUTCDATETIME()),
           CAST(i % 5 AS tinyint),
           CAST(ABS(CHECKSUM(NEWID())) % 100000 / 100.0 AS decimal(10, 2)),
           'demo'
    FROM n;
END
IF OBJECT_ID(N'dbo.AuditEvents') IS NULL
    CREATE TABLE dbo.AuditEvents (
        EventId   bigint IDENTITY(1, 1) NOT NULL CONSTRAINT PK_AuditEvents PRIMARY KEY,
        EventTime datetime2(0) NOT NULL CONSTRAINT DF_AuditEvents_EventTime DEFAULT SYSUTCDATETIME(),
        Payload   char(400)    NOT NULL
    );
IF USER_ID(N'NT AUTHORITY\SYSTEM') IS NULL
    CREATE USER [NT AUTHORITY\SYSTEM] FOR LOGIN [NT AUTHORITY\SYSTEM];
ALTER ROLE db_datareader ADD MEMBER [NT AUTHORITY\SYSTEM];
ALTER ROLE db_datawriter ADD MEMBER [NT AUTHORITY\SYSTEM];
"@

Write-Output "Login $MonitorLogin and the SreDemo database are ready."
