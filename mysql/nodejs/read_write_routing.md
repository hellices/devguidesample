아래는 **Node.js에서 mysql2를 사용해 Azure Database for MySQL Flexible Server를 Primary(쓰기) + Replica(읽기) 구성 시 적용할 수 있는 한글 가이드**입니다. Microsoft Learn 공식 문서 링크도 포함했습니다.

***

# **Azure MySQL Flexible Server + Node.js(mysql2) 가이드**

## ✅ 개요

Azure Database for MySQL Flexible Server는 **읽기 복제본(Read Replica)** 기능을 제공하여 읽기 트래픽을 분산할 수 있습니다.

*   **Primary 서버**: 쓰기 전용 (INSERT, UPDATE, DELETE)
*   **Replica 서버**: 읽기 전용 (SELECT)
*   복제는 **비동기** → 약간의 지연(Lag) 발생 가능
*   **자동 승격(Failover)** 기능 필요 시 HA 구성 필요

***

## ✅ 공식 문서 참고

*   <https://learn.microsoft.com/azure/mysql/flexible-server/concepts-read-replicas>
*   <https://learn.microsoft.com/azure/mysql/flexible-server/how-to-read-replicas-portal>
*   <https://learn.microsoft.com/cli/azure/mysql/flexible-server/replica?view=azure-cli-latest>
*   <https://learn.microsoft.com/azure/mysql/flexible-server/connect-nodejs>
*   <https://learn.microsoft.com/azure/mysql/flexible-server/concept-performance-best-practices>

***

## ✅ 환경 변수 설정

```bash
MYSQL_PRIMARY_HOST=your-primary.mysql.database.azure.com
MYSQL_REPLICA_HOST=your-replica.mysql.database.azure.com
MYSQL_USER=your-username
MYSQL_PASSWORD=your-password
MYSQL_DB=your-database
```

***

## ✅ 공통 설정: Connection Pool

```javascript
const mysql = require('mysql2/promise');

const writePool = mysql.createPool({
  host: process.env.MYSQL_PRIMARY_HOST,
  user: process.env.MYSQL_USER,
  password: process.env.MYSQL_PASSWORD,
  database: process.env.MYSQL_DB,
  waitForConnections: true,
  connectionLimit: 10,
});

const readPool = mysql.createPool({
  host: process.env.MYSQL_REPLICA_HOST,
  user: process.env.MYSQL_USER,
  password: process.env.MYSQL_PASSWORD,
  database: process.env.MYSQL_DB,
  waitForConnections: true,
  connectionLimit: 10,
});
```

***

## ✅ 전략 1: 타입 기반 라우팅

쿼리 실행 시 `type`을 명시 (`read` 또는 `write`).

```javascript
async function safeQuery(sql, params, type = 'read') {
  const pool = type === 'write' ? writePool : readPool;
  try {
    const [rows] = await pool.execute(sql, params);
    return rows;
  } catch (err) {
    if (type === 'read') {
      console.warn('Replica 장애 발생 → Primary로 Fallback');
      const [rows] = await writePool.execute(sql, params);
      return rows;
    }
    throw err;
  }
}
```

***

## ✅ 전략 2: SQL 기반 자동 라우팅

SQL 첫 키워드로 읽기/쓰기 판별.

```javascript
function getQueryType(sql) {
  const firstWord = sql.trim().split(/\s+/)[0].toUpperCase();
  const readCommands = ['SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN'];
  return readCommands.includes(firstWord) ? 'read' : 'write';
}

async function safeAutoQuery(sql, params = []) {
  const type = getQueryType(sql);
  const pool = type === 'read' ? readPool : writePool;
  try {
    const [rows] = await pool.execute(sql, params);
    return rows;
  } catch (err) {
    if (type === 'read') {
      console.warn('Replica 장애 발생 → Primary로 Fallback');
      const [rows] = await writePool.execute(sql, params);
      return rows;
    }
    throw err;
  }
}
```

***

## ✅ Circuit Breaker + Retry (권장)

반복 장애 시 Replica를 일정 시간 동안 제외하고 Primary로만 처리.

```javascript
let replicaDown = false;
let failureCount = 0;
const FAILURE_THRESHOLD = 3;
const RESET_TIMEOUT = 10000;

async function retryWrapper(fn, retries = 3) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      if (attempt === retries) throw err;
      await new Promise(res => setTimeout(res, 500));
    }
  }
}

async function safeAutoQueryWithBreaker(sql, params = []) {
  const type = getQueryType(sql);
  return retryWrapper(async () => {
    if (type === 'read' && !replicaDown) {
      try {
        return (await readPool.execute(sql, params))[0];
      } catch (err) {
        failureCount++;
        if (failureCount >= FAILURE_THRESHOLD) {
          replicaDown = true;
          console.warn('Replica DOWN → Primary로 전환');
          setTimeout(() => { replicaDown = false; failureCount = 0; }, RESET_TIMEOUT);
        }
        throw err;
      }
    }
    return (await writePool.execute(sql, params))[0];
  });
}
```
***

## ✅ 모범 사례

*   **Replica Lag 모니터링**: Azure Portal 활용
*   **강한 일관성**: Primary에서 읽기
*   **SQL Injection 방지**: `?` placeholder 사용
*   **DNS 기반 Failover**: 장애 시 자동 전환 고려
*   **ProxySQL/Heimdall**: 고급 라우팅 필요 시 사용
