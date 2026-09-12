/**
 * server.js — 타이트한 동시 CRUD + 정밀 다운타임 측정
 *
 * AKS Pod 에서 실행. DB_HOST = {prefix}-old-db.mysql.database.azure.com
 * (privatelink.mysql.database.azure.com 에서 PE IP 해석 → cutover 시 A record 교체)
 *
 * 측정 항목:
 *   - 첫 번째 에러 시각 (DOWNTIME START)
 *   - 재연결 성공 시각 (RECOVERED)
 *   - 다운타임 지속시간 (ms 단위)
 *   - RECOVERED 후 어느 DB 서버로 접속됐는지 (@@hostname)
 *
 * 환경변수:
 *   DB_HOST      필수 ({prefix}-old-db.mysql.database.azure.com)
 *   DB_PORT      (3306)
 *   DB_USER      필수
 *   DB_PASSWORD  필수
 *   DB_NAME      (simdb)
 *   WORKERS      (5) — 동시 비동기 워커 수
 *   LOOP_MS      (20) — 워커당 루프 간격(ms). 5명×20ms ≈ 250 ops/s
 */

'use strict';

const db = require('./dbHandler');

const WORKERS = parseInt(process.env.WORKERS || '5', 10);
const LOOP_MS = parseInt(process.env.LOOP_MS || '20', 10);

// ─── Metrics ──────────────────────────────────────────────────────────────────
const m = {
    // 1초 슬라이딩 윈도우
    windowOps: 0,
    windowErrors: 0,
    windowLatencies: [],
    // 누적
    totalOps: 0,
    totalErrors: 0,
    // 다운타임 추적
    isDown: false,
    downtimeStart: null,
    downtimes: [],          // [{start, end, durationMs, errors}]
    downtimeErrors: 0,
};

function recordSuccess(latencyMs) {
    m.totalOps++;
    m.windowOps++;
    m.windowLatencies.push(latencyMs);
    if (m.isDown) {
        const end = Date.now();
        const dt = { start: m.downtimeStart, end, durationMs: end - m.downtimeStart, errors: m.downtimeErrors };
        m.downtimes.push(dt);
        const ts = new Date().toISOString().substring(11, 23);
        console.log(`[${ts}] ✅ RECOVERED  downtime=${(dt.durationMs / 1000).toFixed(3)}s  errors_during=${dt.errors}  total_downtimes=${m.downtimes.length}`);
        m.isDown = false;
        m.downtimeStart = null;
        m.downtimeErrors = 0;
        // RECOVERED 직후: 어느 DB 서버로 재연결됐는지 확인 (cutover 검증 핵심)
        db.getDbHostname().then((h) => {
            const ts2 = new Date().toISOString().substring(11, 23);
            console.log(`[${ts2}]    → reconnected to DB server: ${h}`);
        }).catch(() => {});
    }
}

function recordError(opName, code, msg) {
    m.totalErrors++;
    m.windowErrors++;
    if (!m.isDown) {
        m.isDown = true;
        m.downtimeStart = Date.now();
        m.downtimeErrors = 0;
        const ts = new Date().toISOString().substring(11, 23);
        console.log(`[${ts}] ⚠️  DOWNTIME START  op=${opName}  code=${code}`);
    }
    m.downtimeErrors++;
    // 다운타임 중 에러 상세는 처음 5개만 출력 (로그 폭발 방지)
    if (m.downtimeErrors <= 5) {
        const ts = new Date().toISOString().substring(11, 23);
        console.log(`[${ts}]    err#${m.downtimeErrors}  op=${opName}  code=${code}  ${msg?.substring(0, 60)}`);
    }
}

function percentile(arr, p) {
    if (arr.length === 0) return '-';
    const sorted = [...arr].sort((a, b) => a - b);
    const idx = Math.ceil((p / 100) * sorted.length) - 1;
    return sorted[Math.max(0, idx)];
}

// ─── Stats 출력 (1초마다) ─────────────────────────────────────────────────────
setInterval(() => {
    const ts = new Date().toISOString().substring(11, 23);
    const p50 = percentile(m.windowLatencies, 50);
    const p99 = percentile(m.windowLatencies, 99);

    if (m.isDown) {
        const ongoing = ((Date.now() - m.downtimeStart) / 1000).toFixed(1);
        console.log(`[${ts}] ops=0/s  p50=-  p99=-  err_window=${m.windowErrors}  ⚠ DOWNTIME=${ongoing}s`);
    } else {
        console.log(`[${ts}] ops=${m.windowOps}/s  p50=${p50}ms  p99=${p99}ms  total=${m.totalOps}  err=${m.totalErrors}`);
    }

    // 슬라이딩 윈도우 초기화
    m.windowOps = 0;
    m.windowErrors = 0;
    m.windowLatencies = [];
}, 1000);

// ─── CRUD 작업 정의 ───────────────────────────────────────────────────────────
async function opInsert() {
    await db.upsertMaster(
        'INSERT INTO orders (item, qty) VALUES (?, ?)',
        [`item-${process.pid}-${Date.now()}`, Math.ceil(Math.random() * 100)],
    );
}

async function opSelect() {
    await db.queryReplica('SELECT id, item, qty FROM orders ORDER BY id DESC LIMIT 10');
}

async function opUpdate() {
    // 랜덤 ID 범위 내 한 건 UPDATE (gap lock 회피, derived table로 ER_UPDATE_TABLE_USED 우회)
    await db.upsertMaster(
        'UPDATE orders SET qty = qty + 1 WHERE id >= (SELECT rid FROM (SELECT FLOOR(MIN(id) + RAND() * (MAX(id) - MIN(id))) AS rid FROM orders) t) ORDER BY id LIMIT 1',
    );
}

async function opTransaction() {
    await db.tsWrapper(async (conn) => {
        // MIN/MAX 범위 내 랜덤 PK 선택 (full scan + gap lock 회피)
        const rows = await conn.queryAsync(
            'SELECT id FROM orders WHERE id >= (SELECT FLOOR(MIN(id) + RAND() * (MAX(id) - MIN(id))) FROM orders) LIMIT 1',
        );
        if (rows.length > 0) {
            await conn.queryAsync('UPDATE orders SET qty = qty + 1 WHERE id = ?', [rows[0].id]);
        }
    });
}

async function opSelectCount() {
    await db.queryReplica('SELECT COUNT(*) as cnt FROM orders');
}

// 워커별 작업 타입 (워커 인덱스로 결정 → 골고루 분산)
const opsByWorker = [opInsert, opSelect, opUpdate, opTransaction, opSelectCount];

// ─── Worker 루프 ─────────────────────────────────────────────────────────────
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
let running = true;

async function worker(id) {
    const op = opsByWorker[id % opsByWorker.length];
    while (running) {
        const start = Date.now();
        try {
            await op();
            recordSuccess(Date.now() - start);
        } catch (err) {
            recordError(op.name, err.code, err.message);
            // 에러 시 짧은 backoff (최대 500ms)
            const backoff = Math.min(50 * (m.downtimeErrors || 1), 500);
            await sleep(backoff);
            continue;
        }
        await sleep(LOOP_MS);
    }
}

// ─── 종료 시 요약 출력 ────────────────────────────────────────────────────────
function printSummary() {
    console.log('\n══════════════════════════════════════════════════');
    console.log(' SUMMARY');
    console.log(`  total ops    : ${m.totalOps}`);
    console.log(`  total errors : ${m.totalErrors}`);
    console.log(`  downtimes    : ${m.downtimes.length}`);
    m.downtimes.forEach((dt, i) => {
        const start = new Date(dt.start).toISOString().substring(11, 23);
        const end   = new Date(dt.end).toISOString().substring(11, 23);
        console.log(`    [${i + 1}] ${start} → ${end}  duration=${(dt.durationMs / 1000).toFixed(3)}s  errors=${dt.errors}`);
    });
    const totalDowntimeMs = m.downtimes.reduce((s, d) => s + d.durationMs, 0);
    console.log(`  total downtime: ${(totalDowntimeMs / 1000).toFixed(3)}s`);
    console.log('══════════════════════════════════════════════════\n');
}

process.on('SIGINT', () => { running = false; setTimeout(() => { printSummary(); process.exit(0); }, 1500); });
process.on('SIGTERM', () => { running = false; setTimeout(() => { printSummary(); process.exit(0); }, 1500); });

// ─── Main ────────────────────────────────────────────────────────────────────
async function main() {
    const host = process.env.DB_HOST || 'db.sim.mysql.internal';
    const port = process.env.DB_PORT || '3306';
    console.log('══════════════════════════════════════════════════');
    console.log(` DB Cutover Simulation — CRUD Worker`);
    console.log(`  host    : ${host}:${port}`);
    console.log(`  workers : ${WORKERS}  loop_ms : ${LOOP_MS}`);
    console.log(`  target  : ~${(WORKERS * (1000 / LOOP_MS)).toFixed(0)} ops/s`);
    console.log('══════════════════════════════════════════════════\n');

    // 모든 워커를 동시에 시작 (await 없이 — 독립 실행)
    for (let i = 0; i < WORKERS; i++) {
        worker(i).catch((err) => {
            console.error(`[worker${i}] fatal:`, err.message);
        });
    }

    // 프로세스 유지
    await new Promise(() => {});
}

main().catch((err) => {
    console.error('[server] fatal:', err);
    process.exit(1);
});
