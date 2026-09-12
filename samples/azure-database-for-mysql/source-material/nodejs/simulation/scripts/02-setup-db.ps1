<#
.SYNOPSIS
  02 - old-db 초기화 및 K8s 리소스 배포

  DNS 구조:
    앱 FQDN: primary.db.{prefix}.internal  (Custom Private DNS Zone)
      → CNAME: {prefix}-old-db.mysql.database.azure.com  (custom zone, TTL=5s)
      → CNAME: {prefix}-old-db.privatelink.mysql.database.azure.com  (Azure 자동)
      → A record: old PE IP  (privatelink zone, DNS Zone Group 자동 관리)

  new-db는 이 스크립트에서 초기화하지 않음.
  다음 단계 02b-setup-replication.ps1 에서 old-db의 Read Replica로 생성 → 스키마/데이터 자동 동기화.

  Cutover 시: CNAME 을 old FQDN → new FQDN 으로 변경 (05-cutover.ps1)
  TLS: rejectUnauthorized:true (CA 체인 검증만 수행 — mysql2는 hostname 검증 미적용, servername 불필요)

  수행 작업:
    1. AKS kubeconfig 획득
    2. mysql-client Pod 로 old-db 테이블 생성 (TLS 유지)
    3. K8s Secret(DB_HOST = primary.db.{prefix}.internal) + Deployment 적용

.USAGE
  .\02-setup-db.ps1
#>
param()
$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path $MyInvocation.MyCommand.Path
$e = Get-Content (Join-Path $scriptDir "sim-env.json") | ConvertFrom-Json
$rg = $e.resourceGroup

# ─── AKS kubeconfig ─────────────────────────────────────────────────────────
Write-Host "`n[02] AKS kubeconfig 획득..."
az aks get-credentials --resource-group $rg --name $e.aksName --overwrite-existing

# ─── DB 초기화 (mysql-client Pod via AKS) ────────────────────────────────────
# TLS 유지 (--ssl-mode=REQUIRED), FQDN = *.mysql.database.azure.com 이므로 cert 일치
Write-Host "[02] mysql-client Pod 기동..."
@"
apiVersion: v1
kind: Pod
metadata:
  name: mysql-client
  namespace: default
spec:
  restartPolicy: Never
  containers:
  - name: mysql
    image: mysql:8.0
    command: ["sleep", "3600"]
"@ | kubectl apply -f -
kubectl wait pod/mysql-client --for=condition=Ready --timeout=120s

# 테이블: server_name 컬럼 포함 → cutover 후 어느 DB 에 INSERT 됐는지 확인
$initSql = @"
CREATE DATABASE IF NOT EXISTS $($e.dbName);
USE $($e.dbName);
CREATE TABLE IF NOT EXISTS orders (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  item        VARCHAR(100) NOT NULL,
  qty         INT NOT NULL DEFAULT 1,
  server_name VARCHAR(100) DEFAULT NULL COMMENT 'DB server hostname at insert time',
  created_at  DATETIME(3) DEFAULT CURRENT_TIMESTAMP(3)
);
INSERT INTO orders (item, qty, server_name) VALUES ('seed', 0, @@hostname);
"@

$oldFqdn = $e.mysqlOldFqdn  # "{prefix}-old-db.mysql.database.azure.com"
$newFqdn = $e.mysqlNewFqdn  # "{prefix}-new-db.mysql.database.azure.com"

Write-Host "[02] old-db 테이블 생성 (TLS)..."
kubectl exec mysql-client -- mysql `
    -h $oldFqdn -u $e.mysqlAdminUser -p"$($e.password)" `
    --ssl-mode=REQUIRED -e $initSql

# ─── App 전용 DB 사용자 생성 ────────────────────────────────────────────────
# 프로덕션과 동일하게 admin/app 계정 분리 (app = CRUD 전용, admin = 관리 작업)
$appUser = $e.appUser        # "appuser"
$appPass = $e.appPassword    # "App@Pass2026!"
Write-Host "[02] App 전용 사용자 '$appUser' 생성 (old-db)..."
$appUserSql = @"
CREATE USER IF NOT EXISTS '${appUser}'@'%' IDENTIFIED BY '${appPass}';
GRANT SELECT, INSERT, UPDATE, DELETE ON $($e.dbName).* TO '${appUser}'@'%';
FLUSH PRIVILEGES;
"@
kubectl exec mysql-client -- mysql `
    -h $oldFqdn -u $e.mysqlAdminUser -p"$($e.password)" `
    --ssl-mode=REQUIRED -e $appUserSql

# old-db seed row 확인
Write-Host "[02] old-db seed 확인..."
kubectl exec mysql-client -- mysql `
    -h $oldFqdn -u $e.mysqlAdminUser -p"$($e.password)" `
    --ssl-mode=REQUIRED -e "SELECT id, item, server_name FROM $($e.dbName).orders;"

# new-db 는 02b-setup-replication.ps1 에서 Read Replica 로 생성 → 스키마/데이터 자동 복제됨
Write-Host "[02] new-db 테이블 초기화 스킵 — 02b-setup-replication.ps1 에서 Replica 생성 후 자동 동기화됨."

kubectl delete pod mysql-client --ignore-not-found=true

# ─── K8s Secret + Deployment ─────────────────────────────────────────────────
Write-Host "`n[02] K8s Namespace / Secret / Deployment 배포..."
$k8sDir = Join-Path $scriptDir "..\k8s"

kubectl create namespace db-sim --dry-run=client -o yaml | kubectl apply -f -

# DB_HOST = custom FQDN (primary.db.{prefix}.internal)
# App pod 는 appuser 로 접속 (admin 아님)
kubectl create secret generic db-secret -n db-sim `
    --from-literal=DB_HOST=$($e.appFqdn) `
    --from-literal=DB_PORT="3306" `
    --from-literal=DB_USER=$($e.appUser) `
    --from-literal=DB_PASSWORD=$($e.appPassword) `
    --from-literal=DB_NAME=$($e.dbName) `
    --dry-run=client -o yaml | kubectl apply -f -

$deployYaml = Get-Content (Join-Path $k8sDir "deployment.yaml") -Raw
$deployYaml = $deployYaml -replace "REPLACE_ACR", $e.acrLoginServer
$deployYaml | kubectl apply -f -

Write-Host "[02] 완료."
Write-Host "  앱 접속 FQDN : $($e.appFqdn)"
Write-Host "  DNS chain    : $($e.appFqdn) → CNAME → $oldFqdn → privatelink → PE IP (DNS Zone Group)"
Write-Host "  다음 단계  : .\02b-setup-replication.ps1  (new-db Read Replica 생성)"
Write-Host ""
kubectl get pods -n db-sim
