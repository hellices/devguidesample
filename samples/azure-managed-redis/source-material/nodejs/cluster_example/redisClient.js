'use strict';

require('dotenv').config();
const { createCluster, createClient } = require('@redis/client');

// 간단한 콘솔 로거 (urecaLogger 대체)
const logger = {
    i: (tag, ...args) => console.log(`[INFO][${new Date().toISOString()}][${tag}]`, ...args),
    d: (tag, ...args) => console.log(`[DEBUG][${new Date().toISOString()}][${tag}]`, ...args),
    e: (tag, ...args) => console.error(`[ERROR][${new Date().toISOString()}][${tag}]`, ...args),
};

let redisClient;
let isClusterMode = false;

// 연결 방식: 'oss-cluster' | 'enterprise' | 'standalone'
let connectionMode = 'standalone';

const reconnectStrategy = (retries) => {
    if (retries === 0) {
        return 0;
    }
    // 50ms -> 100ms -> 200ms -> 400ms ... max 5000ms
    const baseDelay = 50;
    const delay = Math.min(2 ** (retries - 1) * baseDelay, 5000);
    logger.i('reconnectStrategy', `Retry #${retries}, delay: ${delay}ms`);
    return delay;
};

let redisAuthType = 'local';
let endpoint = process.env.REDIS_URL || 'rediss://redis-oss-policy.koreacentral.redis.azure.net:10000';

if (process.env.PROFILE === 'DEVE' || process.env.PROFILE === 'STAG' || process.env.PROFILE === 'PROD') {
    redisAuthType = 'azure';
}

const redisUrl = new URL(endpoint);

// ============================================================
// REDIS_MODE 환경변수로 연결 방식 선택
//   'oss-cluster' : createCluster (OSS Cluster Policy)
//                   → 클라이언트가 topology 관리, Failover 시 이슈 가능
//   'enterprise'  : createClient (Enterprise Cluster Policy, Proxy 기반)
//                   → Azure proxy가 topology 관리, Failover 안정적
//   미지정 시     : azure 환경이면 oss-cluster, 로컬이면 standalone
// ============================================================
const redisMode = process.env.REDIS_MODE; // 'oss-cluster' | 'enterprise'

if (redisAuthType === 'azure') {
    const accessKey = process.env.REDIS_ACCESS_KEY;
    if (!accessKey) {
        throw new Error('REDIS_ACCESS_KEY 환경 변수가 설정되지 않았습니다.');
    }

    if (redisMode === 'enterprise') {
        // ===== 방안 1: Enterprise Cluster (Proxy 기반) =====
        // createClient로 단일 엔드포인트에 연결
        // proxy가 내부적으로 클러스터 라우팅을 처리
        // → topology 관리 이슈를 구조적으로 회피
        connectionMode = 'enterprise';
        isClusterMode = false;
        redisClient = createClient({
            url: `rediss://${redisUrl.hostname}:${redisUrl.port}`,
            password: accessKey,
            socket: {
                tls: true,
                servername: redisUrl.hostname,
                connectTimeout: 1000,
                reconnectStrategy,
            },
        });
        logger.i('init', '🔵 Enterprise mode (createClient) - proxy handles topology');
    } else {
        // ===== 기존 방식: OSS Cluster Policy =====
        // createCluster로 연결 → 클라이언트가 slot→node 매핑 관리
        // → Failover 시 기존 node endpoint로 재연결 시도하며 장애 가능
        connectionMode = 'oss-cluster';
        isClusterMode = true;
        redisClient = createCluster({
            rootNodes: [{ url: `rediss://${redisUrl.hostname}:${redisUrl.port}` }],
            defaults: {
                password: accessKey,
                socket: {
                    tls: true,
                    servername: redisUrl.hostname,
                    connectTimeout: 1000,
                    reconnectStrategy,
                },
            },
        });
        logger.i('init', '🟠 OSS Cluster mode (createCluster) - client manages topology');
    }
} else {
    // 로컬 개발 환경
    const useCluster = process.env.USE_CLUSTER === 'true';

    if (useCluster) {
        connectionMode = 'oss-cluster';
        isClusterMode = true;
        redisClient = createCluster({
            rootNodes: [{ url: `redis://${redisUrl.hostname}:${redisUrl.port}` }],
            defaults: {
                password: process.env.REDIS_PASSWORD || undefined,
                socket: {
                    rejectUnauthorized: false,
                    keepAlive: 20000,
                    reconnectStrategy,
                },
            },
        });
    } else {
        connectionMode = 'standalone';
        isClusterMode = false;
        redisClient = createClient({
            url: `redis://${redisUrl.hostname}:${redisUrl.port}`,
            password: process.env.REDIS_PASSWORD || undefined,
            socket: {
                rejectUnauthorized: false,
                keepAlive: 20000,
                reconnectStrategy,
            },
        });
    }
}

// Redis 이벤트 리스너
redisClient.on('connect', () => logger.i('redisClient.on', 'Redis connected!'));
redisClient.on('reconnecting', () => logger.i('redisClient.on', 'Redis reconnecting...'));
redisClient.on('ready', () => logger.i('redisClient.on', 'Redis is ready!'));
redisClient.on('error', (err) => logger.e('redisClient.on', 'Redis Client Error:', err.message || err));
redisClient.on('end', () => logger.i('redisClient.on', 'Redis connection closed.'));

/**
 * Redis 클라이언트를 연결하는 비동기 함수.
 */
const connectRedis = async () => {
    try {
        if (!redisClient.isOpen) {
            await redisClient.connect();
            logger.d('connectRedis', `Redis connected successfully! (mode: ${connectionMode})`);
        }
    } catch (error) {
        logger.e('connectRedis', 'Redis initial connection failed:', error);
        throw error;
    }
};

// 정상 종료 핸들러
const shutdown = async (signal) => {
    logger.i('shutdown', `${signal} received, starting graceful shutdown...`);
    try {
        if (redisClient && redisClient.isOpen) {
            await redisClient.quit();
            logger.d('shutdown', 'Redis connection closed successfully');
        } else {
            logger.d('shutdown', 'Redis connection already closed');
        }
    } catch (err) {
        logger.e('shutdown', 'Error closing Redis connection:', err.message || err);
    }
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

module.exports = {
    redisClient,
    connectRedis,
    isClusterMode,
    connectionMode,
    logger,
};
