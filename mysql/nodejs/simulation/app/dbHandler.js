/**
 * dbHandler.js — 시뮬레이션용 DB 핸들러
 *
 * urecaDbHandler.js 의 핵심 로직만 추출한 시뮬레이션용 경량 버전.
 *
 * 프로덕션과 동일하게 적용한 변경사항 (컷오버 최적화 한정):
 *   1. connectTimeout: 10000  (hang 방지)
 *   2. enableKeepAlive / keepAliveInitialDelay  (idle 커넥션 조기 감지)
 *   3. tsWrapper rollback 에러 분리  (session kill 시 2중 에러 스택 방지)
 *
 * 시뮬레이션에만 적용하는 추가 설정:
 *   - removeNodeErrorCount: 5  (일시적 ECONNREFUSED 허용, 5회 연속 에러 시 노드 제거)
 *     ※ 1로 설정 시 50-pod connection storm에서 영구 사망 확인 → 5로 상향
 *     ※ 프로덕션에는 일시 네트워크 오류에도 노드 제거되는 리스크로 미적용
 *
 * 연결 대상: DB_HOST = primary.db.{prefix}.internal  (Custom Private DNS Zone CNAME)
 *           CNAME → {prefix}-old-db.mysql.database.azure.com → privatelink A record → PE IP
 * TLS: rejectUnauthorized:true = CA 체인 검증만 수행 (mysql2는 hostname 검증 미적용 — 실증 확인)
 *      — custom FQDN(primary.db.{prefix}.internal) 사용 시에도 접속 영향 없음
 *      — old/new 모두 동일 wildcard cert(*.mysql.database.azure.com) — cutover 후 변경 불필요
 */

'use strict';

const mysql = require('mysql2');

const CLUSTER_CONFIG = {
    restoreNodeTimeout: 3000,
    canRetry: true,
    removeNodeErrorCount: 5, // 시뮬레이션 전용: 50-pod storm 허용 (1→5 상향)
};

function makeConfig(host, port) {
    return {
        host,
        port,
        user: process.env.DB_USER,
        password: process.env.DB_PASSWORD,
        database: process.env.DB_NAME || 'simdb',
        // ─ 프로덕션과 동일하게 적용한 설정 ─
        connectTimeout: 10000,
        enableKeepAlive: true,
        keepAliveInitialDelay: 10000,
        // ─ TLS: rejectUnauthorized:true = CA 체인 검증만 수행 (hostname 검증 미적용) ─
        // ─ custom FQDN 사용 시에도 접속 영향 없음; old/new 동일 wildcard cert ─
        ssl: { rejectUnauthorized: true },
    };
}

const MASTER_HOST = process.env.DB_HOST;
const MASTER_PORT = parseInt(process.env.DB_PORT || '3306', 10);

if (!MASTER_HOST) throw new Error('DB_HOST env var is required');

let cluster = null;

function initCluster() {
    if (cluster) {
        try { cluster.end(); } catch (_) {}
    }
    cluster = mysql.createPoolCluster(CLUSTER_CONFIG);
    // 시뮬레이션: 레플리카 미고려, MASTER/SLAVE 모두 동일 FQDN
    cluster.add('MASTER', makeConfig(MASTER_HOST, MASTER_PORT));
    cluster.add('SLAVE1', makeConfig(MASTER_HOST, MASTER_PORT));
    console.log(`[dbHandler] cluster init → ${MASTER_HOST}:${MASTER_PORT}`);
}

initCluster();

// ─────────────────────────────────────────────────────────────────────────────

const query = (pool, sql, params = []) => new Promise((resolve, reject) => {
    pool.query(sql, params, (error, results) => {
        if (error) { reject(error); return; }
        resolve(results.map ? results.map((r) => ({ ...r })) : results);
    });
});

const upsert = (pool, sql, params = []) => new Promise((resolve, reject) => {
    pool.query(sql, params, (error, results) => {
        if (error) { reject(error); return; }
        resolve({ ...results });
    });
});

const queryMaster = (sql, params) => {
    const pool = cluster.of('MASTER');
    return query(pool, sql, params);
};

const queryReplica = (sql, params) => {
    const pool = cluster.of('SLAVE*', 'RR');
    return query(pool, sql, params);
};

const upsertMaster = (sql, params) => {
    const pool = cluster.of('MASTER');
    return upsert(pool, sql, params);
};

// ─ tsWrapper: rollback 에러 분리 ─────────────────────────────────────────────
const wrapBeginTransaction = (conn) => () => new Promise((res, rej) => {
    conn.beginTransaction((err) => { if (err) rej(err); else res(); });
});
const wrapQuery = (conn) => (sql, params) => new Promise((res, rej) => {
    conn.query(sql, params, (err, results) => { if (err) rej(err); else res(results); });
});
const wrapCommit = (conn) => () => new Promise((res, rej) => {
    conn.commit((err) => { if (err) rej(err); else res(); });
});
const wrapRollback = (conn) => () => new Promise((res) => {
    conn.rollback(() => res());
});

const getConn = () => new Promise((resolve, reject) => {
    const pool = cluster.of('MASTER');
    pool.getConnection((err, conn) => {
        if (err) { reject(err); return; }
        conn.beginTransactionAsync = wrapBeginTransaction(conn);
        conn.queryAsync = wrapQuery(conn);
        conn.commitAsync = wrapCommit(conn);
        conn.rollbackAsync = wrapRollback(conn);
        resolve(conn);
    });
});

const tsWrapper = async (callback) => {
    const conn = await getConn();
    try {
        await conn.beginTransactionAsync();
        const result = await callback(conn);
        await conn.commitAsync();
        return result;
    } catch (err) {
        try {
            await conn.rollbackAsync();
        } catch (rollbackErr) {
            // session kill 시 rollback도 실패하지만 DB가 서버 측에서 자동 rollback
            console.warn('[dbHandler] rollback failed (auto-rolled back by server):', rollbackErr.code);
        }
        throw err;
    } finally {
        conn.release();
    }
};

// 현재 연결된 DB 서버 식별 (cutover 후 어느 DB로 붙었는지 확인)
const getDbHostname = () => queryMaster('SELECT @@hostname AS h').then((rows) => rows[0].h);

module.exports = { queryMaster, queryReplica, upsertMaster, tsWrapper, getDbHostname };
