'use strict';

const { redisClient, isClusterMode, connectionMode, logger } = require('./redisClient');

const HEALTH_CHECK_INTERVAL_MS = parseInt(process.env.HEALTH_CHECK_INTERVAL) || 30000; // 기본 30초
let healthCheckTimer = null;

/**
 * 주기적으로 Redis 연결 상태를 확인하는 Health Check Probe
 * - connection pool 상태 확인
 * - PING 수행 및 latency 측정
 * - 어떤 노드로 호출하는지 로그 출력
 */
async function performHealthCheck() {
    try {
        if (!redisClient.isOpen) {
            logger.e('healthCheck', 'Redis client is NOT open!');
            return;
        }

        const pingStart = Date.now();
        const pong = await redisClient.ping();
        const pingLatency = Date.now() - pingStart;

        if (isClusterMode) {
            let state = 'unknown';
            let nodes = 0;
            let nodeList = '';
            try {
                const raw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'INFO']);
                const info = parseInfoString(raw);
                state = info.cluster_state;
                nodes = info.cluster_known_nodes;
            } catch (_) {}
            try {
                const nodesRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
                const lines = nodesRaw.toString().split('\n').filter((l) => l.trim());
                nodeList = lines.map((line) => {
                    const parts = line.split(' ');
                    const endpoint = parts[1] || '?';
                    const flags = parts[2] || '';
                    const linkState = parts[7] || '';
                    return `${endpoint}(${flags},${linkState})`;
                }).join(' | ');
            } catch (_) {}

            logger.i('healthCheck', `PING=${pong} ${pingLatency}ms | cluster_state=${state} nodes=${nodes} | shards=[${nodeList}]`);
        } else {
            let clients = '?';
            try {
                const raw = await redisClient.sendCommand(['INFO', 'clients']);
                clients = parseInfoString(raw).connected_clients;
            } catch (_) {}

            logger.i('healthCheck', `PING=${pong} ${pingLatency}ms | connected_clients=${clients}`);
        }
    } catch (err) {
        logger.e('healthCheck', `Health check failed: ${err.message}`);
    }
}

function parseInfoString(infoStr) {
    if (!infoStr) return {};
    const result = {};
    const lines = infoStr.toString().split('\r\n');
    for (const line of lines) {
        if (line.startsWith('#') || line.trim() === '') continue;
        const idx = line.indexOf(':');
        if (idx !== -1) {
            result[line.substring(0, idx)] = line.substring(idx + 1);
        }
    }
    return result;
}

/**
 * Health Check 시작
 */
function startHealthCheck() {
    if (healthCheckTimer) {
        logger.d('healthCheck', 'Health check already running, skipping start');
        return;
    }
    logger.i('healthCheck', `Starting health check probe (interval: ${HEALTH_CHECK_INTERVAL_MS}ms)`);
    // 시작 즉시 한 번 실행
    performHealthCheck();
    healthCheckTimer = setInterval(performHealthCheck, HEALTH_CHECK_INTERVAL_MS);
}

/**
 * Health Check 중지
 */
function stopHealthCheck() {
    if (healthCheckTimer) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        logger.i('healthCheck', 'Health check probe stopped');
    }
}

module.exports = {
    startHealthCheck,
    stopHealthCheck,
    performHealthCheck,
};
