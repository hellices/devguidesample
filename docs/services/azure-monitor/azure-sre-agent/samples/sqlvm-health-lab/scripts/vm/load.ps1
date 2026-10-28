param(
    [ValidateSet('cpu', 'blocking', 'longrun', 'badlogin', 'growth')]
    [string]$Mode = 'cpu',
    [int]$Minutes = 10
)
# Demo workload for the SRE lab. scripts/generate-load.sh installs this file as
# C:\SreLab\load.ps1 and starts it as LocalSystem, which can read/write SreDemo only.
#   cpu       6 sessions scan dbo.Orders (CustomerId has no index)
#   blocking  one session holds row locks for 50 seconds at a time; 3 readers wait
#   longrun   one request keeps scanning dbo.Orders for the whole period
#   badlogin  failed SQL logins: app_user (locks after 10 failures) and an unknown login
#   growth    inserts 2,000 rows into dbo.AuditEvents every 30 seconds
$cs = 'Server=localhost;Database=SreDemo;Integrated Security=SSPI;Application Name=sre-demo-load'
$end = (Get-Date).AddMinutes($Minutes)

$worker = {
    param($cs, $sql, $end, $once = $false)
    $connection = New-Object System.Data.SqlClient.SqlConnection $cs
    $connection.Open()
    # $once runs the batch exactly once, regardless of how long the job took to start.
    do {
        $command = $connection.CreateCommand()
        $command.CommandTimeout = 0
        $command.CommandText = $sql.Replace('@@CUSTOMER@@', [string](Get-Random -Maximum 20000))
        try { [void]$command.ExecuteScalar() } catch { Start-Sleep -Seconds 1 }
    } while (-not $once -and (Get-Date) -lt $end)
    $connection.Dispose()
}

$jobs = @()
switch ($Mode) {
    'cpu' {
        $sql = 'SELECT COUNT(*), SUM(Amount) FROM dbo.Orders WHERE CustomerId = @@CUSTOMER@@ OPTION (MAXDOP 1);'
        1..6 | ForEach-Object { $jobs += Start-Job -ScriptBlock $worker -ArgumentList $cs, $sql, $end }
    }
    'blocking' {
        $holder = "BEGIN TRAN; UPDATE dbo.Orders SET Status = (Status + 1) % 5 WHERE OrderId <= 1000; WAITFOR DELAY '00:00:50'; ROLLBACK;"
        $jobs += Start-Job -ScriptBlock $worker -ArgumentList $cs, $holder, $end
        Start-Sleep -Seconds 2
        $reader = 'SELECT SUM(Amount) FROM dbo.Orders WHERE OrderId <= 1000;'
        1..3 | ForEach-Object { $jobs += Start-Job -ScriptBlock $worker -ArgumentList $cs, $reader, $end }
    }
    'longrun' {
        # A single batch, so the request's elapsed time grows for the whole period.
        $sql = "DECLARE @end datetime2 = DATEADD(MINUTE, $Minutes, SYSDATETIME()), @n bigint;
WHILE SYSDATETIME() < @end
    SELECT @n = COUNT(*) FROM dbo.Orders WHERE Note LIKE '%x%' OPTION (MAXDOP 1);"
        $jobs += Start-Job -ScriptBlock $worker -ArgumentList ($cs.Replace('sre-demo-load', 'sre-demo-report')), $sql, $end, $true
    }
    'badlogin' {
        while ((Get-Date) -lt $end) {
            foreach ($user in 'app_user', 'scanner') {
                $bad = "Server=tcp:127.0.0.1,1433;Database=master;User ID=$user;Password=wrong-$(Get-Random);Connect Timeout=5;Application Name=sre-demo-badlogin"
                $connection = New-Object System.Data.SqlClient.SqlConnection $bad
                try { $connection.Open() } catch { } finally { $connection.Dispose() }
            }
            Start-Sleep -Seconds 20
        }
    }
    'growth' {
        $sql = "INSERT dbo.AuditEvents (Payload) SELECT TOP (2000) 'event' FROM sys.all_objects AS a CROSS JOIN sys.all_objects AS b;
WAITFOR DELAY '00:00:30';"
        $jobs += Start-Job -ScriptBlock $worker -ArgumentList $cs, $sql, $end
    }
}
if ($jobs) { $jobs | Wait-Job | Remove-Job }
