'use strict';

const express = require('express');
const { redisClient, connectRedis, logger } = require('./redisClient');
const { getClusterInfo, getClusterSlots, testKeyRouting, getConnectionStatus, getClientList, monitorTopology, getConnectionModeInfo, testFailoverRecovery } = require('./routes');
const { startHealthCheck, stopHealthCheck, performHealthCheck } = require('./healthCheck');

const app = express();
const PORT = parseInt(process.env.PORT) || 3000;

app.use(express.json());

// ===== REST API Routes =====

// Redis 연결 상태 (PING)
app.get('/redis/status', getConnectionStatus);

// 클러스터 정보 (CLUSTER INFO, CLUSTER NODES 등)
app.get('/redis/cluster-info', getClusterInfo);

// 클러스터 슬롯 매핑 정보
app.get('/redis/cluster-slots', getClusterSlots);

// Key 라우팅 테스트 (어떤 슬롯으로 분배되는지)
// GET /redis/test-keys?count=10&prefix=mytest
app.get('/redis/test-keys', testKeyRouting);

// CLIENT LIST - 연결된 클라이언트 목록
app.get('/redis/client-list', getClientList);

// Health Check 수동 실행
app.get('/redis/health', async (req, res) => {
    await performHealthCheck();
    res.json({ message: 'Health check executed, see server logs', timestamp: new Date().toISOString() });
});

// 연결 방식 비교 정보 (OSS Cluster vs Enterprise vs Standalone)
app.get('/redis/connection-mode', getConnectionModeInfo);

// 토폴로지 변경 모니터링 (?duration=10&interval=1)
app.get('/redis/monitor', monitorTopology);

// Failover 복구 테스트 (?duration=30&interval=2)
app.get('/redis/failover-recovery', testFailoverRecovery);

// 서버 시작
async function main() {
    try {
        logger.i('main', 'Connecting to Redis...');
        await connectRedis();
        logger.i('main', 'Redis connected!');

        // Health Check Probe 시작
        startHealthCheck();

        app.listen(PORT, () => {
            logger.i('main', `Server running on http://localhost:${PORT}`);
            logger.i('main', '');
            logger.i('main', 'Available endpoints:');
            logger.i('main', `  GET http://localhost:${PORT}/redis/status        - Connection status (PING)`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/cluster-info   - Cluster info (CLUSTER INFO/NODES)`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/cluster-slots  - Cluster slot mapping`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/test-keys      - Key routing test (?count=5&prefix=test)`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/client-list    - Connected client list`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/health         - Manual health check`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/connection-mode - Connection mode info (OSS/Enterprise)`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/monitor        - Monitor topology (?duration=10&interval=1)`);
            logger.i('main', `  GET http://localhost:${PORT}/redis/failover-recovery - Failover recovery test (?duration=30&interval=2)`);
        });
    } catch (error) {
        logger.e('main', 'Failed to start server:', error);
        process.exit(1);
    }
}

// Graceful shutdown
const gracefulShutdown = async (signal) => {
    logger.i('main', `${signal} received`);
    stopHealthCheck();
    process.exit(0);
};

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

main();
