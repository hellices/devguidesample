# **Azure MySQL Read/Write Routing in Node.js (mysql2)**

## ✅ Overview

When using **Azure Database for MySQL** with **read replicas**, you need to route queries correctly:

*   **Primary** → Write operations (INSERT, UPDATE, DELETE, etc.)
*   **Replica** → Read operations (SELECT)

Below are **two strategies** for implementing this in Node.js using `mysql2`.

***

## **Strategy 1: Explicit Type-Based Routing**

You explicitly pass a `type` parameter (`read` or `write`) when calling the query function.

### **Implementation**

#### **Connection Pools**

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

#### **Query Function**

```javascript
async function query(sql, params, type = 'read') {
  const pool = type === 'write' ? writePool : readPool;
  const [rows] = await pool.execute(sql, params);
  return rows;
}

// Usage
await query('SELECT * FROM users WHERE id = ?', [1], 'read');
await query('UPDATE users SET name = ? WHERE id = ?', ['Alice', 1], 'write');
```

#### **Failover Logic**

```javascript
async function safeQuery(sql, params, type = 'read') {
  try {
    return await query(sql, params, type);
  } catch (err) {
    if (type === 'read') {
      console.warn('Replica failed, fallback to Primary');
      return await query(sql, params, 'write');
    }
    throw err;
  }
}
```

***

## **Strategy 2: SQL-Based Automatic Routing**

Instead of passing `type`, determine read/write by inspecting the SQL statement.

### **Implementation**

#### **Determine Query Type**

```javascript
function getQueryType(sql) {
  const firstWord = sql.trim().split(/\s+/)[0].toUpperCase();
  const readCommands = ['SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN'];
  return readCommands.includes(firstWord) ? 'read' : 'write';
}
```

#### **Auto Routing Function**

```javascript
async function autoQuery(sql, params = []) {
  const type = getQueryType(sql);
  const pool = type === 'read' ? readPool : writePool;
  const [rows] = await pool.execute(sql, params);
  return rows;
}

// Usage
await autoQuery('SELECT * FROM users WHERE id = ?', [1]);
await autoQuery('UPDATE users SET name = ? WHERE id = ?', ['Alice', 1]);
```

#### **Failover Logic**

```javascript
async function safeAutoQuery(sql, params = []) {
  const type = getQueryType(sql);
  const pool = type === 'read' ? readPool : writePool;
  try {
    const [rows] = await pool.execute(sql, params);
    return rows;
  } catch (err) {
    if (type === 'read') {
      console.warn('Replica failed, fallback to Primary');
      const [rows] = await writePool.execute(sql, params);
      return rows;
    }
    throw err;
  }
}
```

***

## ✅ Pros & Cons

| Strategy       | Pros                        | Cons                                          |
| -------------- | --------------------------- | --------------------------------------------- |
| **Type-Based** | Simple, explicit control    | Requires developer discipline                 |
| **SQL-Based**  | Automatic, less boilerplate | Risk of misclassification for complex queries |

***

## ✅ Best Practices

*   Monitor **replica lag** in Azure Portal.
*   Use **Primary for strong consistency reads**.
*   Always use **parameterized queries** to prevent SQL injection.
*   Set **timeouts** and consider **circuit breaker** for failover.

***

## ✅ References

*   <https://learn.microsoft.com/azure/mysql/concepts-read-replicas>
*   <https://github.com/sidorares/node-mysql2>

***
