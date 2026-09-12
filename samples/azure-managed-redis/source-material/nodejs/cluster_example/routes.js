'use strict';

const { redisClient, isClusterMode, connectionMode, logger } = require('./redisClient');

/**
 * 클러스터 노드 정보 조회
 * - 클러스터 모드: CLUSTER INFO, CLUSTER NODES, CLUSTER SLOTS 등 조회
 * - 단일 모드: INFO server, INFO clients 등 조회
 */
async function getClusterInfo(req, res) {
    try {
        const result = {};

        if (isClusterMode) {
            // --- Cluster 모드 ---
            // 1) CLUSTER INFO: 클러스터 상태 요약
            const clusterInfoRaw = await redisClient.sendCommand(
                undefined, true, ['CLUSTER', 'INFO']
            );
            result.clusterInfo = parseRedisInfoString(clusterInfoRaw);

            // 2) CLUSTER NODES: 각 노드별 상세 정보
            const clusterNodesRaw = await redisClient.sendCommand(
                undefined, true, ['CLUSTER', 'NODES']
            );
            result.clusterNodes = parseClusterNodes(clusterNodesRaw);

            // 3) CLUSTER MYID: 현재 연결된 노드 ID
            const myId = await redisClient.sendCommand(
                undefined, true, ['CLUSTER', 'MYID']
            );
            result.myId = myId;

            // 4) 내부 슬롯 매핑 정보 (라이브러리가 보유한 정보)
            result.librarySlots = getLibrarySlotInfo();

        } else {
            // --- 단일(Standalone) 모드 ---
            const infoServer = await redisClient.sendCommand(['INFO', 'server']);
            result.serverInfo = parseRedisInfoString(infoServer);

            const infoClients = await redisClient.sendCommand(['INFO', 'clients']);
            result.clientsInfo = parseRedisInfoString(infoClients);

            const infoMemory = await redisClient.sendCommand(['INFO', 'memory']);
            result.memoryInfo = parseRedisInfoString(infoMemory);
        }

        result.isClusterMode = isClusterMode;
        result.isOpen = redisClient.isOpen;
        result.timestamp = new Date().toISOString();

        res.json(result);
    } catch (err) {
        logger.e('getClusterInfo', 'Error fetching cluster info:', err.message);
        res.status(500).json({ error: err.message });
    }
}

/**
 * 클러스터 슬롯 정보 조회
 */
async function getClusterSlots(req, res) {
    try {
        if (!isClusterMode) {
            return res.json({ message: 'Not in cluster mode', isClusterMode: false });
        }

        // CLUSTER SHARDS (Redis 7+)
        let shards = null;
        try {
            shards = await redisClient.sendCommand(
                undefined, true, ['CLUSTER', 'SHARDS']
            );
        } catch (e) {
            logger.d('getClusterSlots', 'CLUSTER SHARDS not supported, falling back to CLUSTER SLOTS');
        }

        // CLUSTER SLOTS (fallback)
        let slots = null;
        try {
            slots = await redisClient.sendCommand(
                undefined, true, ['CLUSTER', 'SLOTS']
            );
        } catch (e) {
            logger.d('getClusterSlots', 'CLUSTER SLOTS failed:', e.message);
        }

        // 라이브러리 내부 슬롯 매핑
        const librarySlots = getLibrarySlotInfo();

        res.json({
            shards,
            slots,
            librarySlots,
            timestamp: new Date().toISOString(),
        });
    } catch (err) {
        logger.e('getClusterSlots', 'Error fetching cluster slots:', err.message);
        res.status(500).json({ error: err.message });
    }
}

/**
 * 간단한 key set/get 테스트 - 클러스터에서 어떤 노드로 라우팅되는지 확인
 */
async function testKeyRouting(req, res) {
    try {
        const testKeys = [];
        const keyCount = parseInt(req.query.count) || 5;
        const prefix = req.query.prefix || 'cluster-test';

        for (let i = 0; i < keyCount; i++) {
            const key = `${prefix}:${i}`;
            const value = `value-${i}-${Date.now()}`;

            await redisClient.set(key, value, { EX: 60 });
            const retrieved = await redisClient.get(key);

            const keyInfo = { key, value, retrieved, match: value === retrieved };

            // 클러스터 모드에서 슬롯 번호 계산
            if (isClusterMode) {
                try {
                    const slot = await redisClient.sendCommand(
                        key, true, ['CLUSTER', 'KEYSLOT', key]
                    );
                    keyInfo.slot = slot;
                } catch (e) {
                    // slot 정보를 가져올 수 없는 경우 무시
                }
            }

            testKeys.push(keyInfo);
        }

        res.json({
            isClusterMode,
            testKeys,
            totalKeys: testKeys.length,
            allMatched: testKeys.every((k) => k.match),
            timestamp: new Date().toISOString(),
        });
    } catch (err) {
        logger.e('testKeyRouting', 'Error testing key routing:', err.message);
        res.status(500).json({ error: err.message });
    }
}

/**
 * Redis 연결 상태 확인 (PING)
 */
async function getConnectionStatus(req, res) {
    try {
        const start = Date.now();
        const pong = await redisClient.ping();
        const latencyMs = Date.now() - start;

        res.json({
            status: 'connected',
            ping: pong,
            latencyMs,
            isOpen: redisClient.isOpen,
            isClusterMode,
            timestamp: new Date().toISOString(),
        });
    } catch (err) {
        logger.e('getConnectionStatus', 'Ping failed:', err.message);
        res.status(503).json({
            status: 'disconnected',
            error: err.message,
            isOpen: redisClient.isOpen,
            isClusterMode,
            timestamp: new Date().toISOString(),
        });
    }
}

/**
 * Redis CLIENT LIST - 현재 연결된 클라이언트 목록
 */
async function getClientList(req, res) {
    try {
        let clientListRaw;
        if (isClusterMode) {
            clientListRaw = await redisClient.sendCommand(
                undefined, true, ['CLIENT', 'LIST']
            );
        } else {
            clientListRaw = await redisClient.sendCommand(['CLIENT', 'LIST']);
        }

        const clients = parseClientList(clientListRaw);

        res.json({
            totalConnections: clients.length,
            clients,
            isClusterMode,
            timestamp: new Date().toISOString(),
        });
    } catch (err) {
        logger.e('getClientList', 'Error fetching client list:', err.message);
        res.status(500).json({ error: err.message });
    }
}

// ===== Helper functions =====

/**
 * Redis INFO 문자열 파싱
 */
function parseRedisInfoString(infoStr) {
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
 * CLUSTER NODES 출력 파싱
 */
function parseClusterNodes(nodesStr) {
    if (!nodesStr) return [];
    const lines = nodesStr.toString().split('\n').filter((l) => l.trim());
    return lines.map((line) => {
        const parts = line.split(' ');
        return {
            id: parts[0],
            endpoint: parts[1],
            flags: parts[2],
            master: parts[3] === '-' ? null : parts[3],
            pingSent: parts[4],
            pongRecv: parts[5],
            configEpoch: parts[6],
            linkState: parts[7],
            slots: parts.slice(8).join(' '),
        };
    });
}

/**
 * CLIENT LIST 출력 파싱
 */
function parseClientList(clientListStr) {
    if (!clientListStr) return [];
    const lines = clientListStr.toString().split('\n').filter((l) => l.trim());
    return lines.map((line) => {
        const obj = {};
        const pairs = line.split(' ');
        for (const pair of pairs) {
            const idx = pair.indexOf('=');
            if (idx !== -1) {
                obj[pair.substring(0, idx)] = pair.substring(idx + 1);
            }
        }
        return obj;
    });
}

/**
 * @redis/client 라이브러리가 내부적으로 보유한 슬롯/노드 매핑 정보 추출
 */
function getLibrarySlotInfo() {
    const info = {
        isClusterMode,
        clientType: isClusterMode ? 'RedisCluster' : 'RedisClient',
    };

    if (!isClusterMode) return info;

    try {
        // RedisCluster 내부 구조 탐색
        // @redis/client v5에서 클러스터 클라이언트의 내부 속성 탐색
        const keys = Object.getOwnPropertyNames(redisClient);
        info.clientProperties = keys;

        // slots 정보가 있는지 확인
        if (redisClient._slots) {
            info._slots = {
                exists: true,
                description: 'Internal slot mapping found',
            };
        }

        // masters/replicas 정보
        if (redisClient.masters) {
            info.masters = Array.from(redisClient.masters || []).map((m) => ({
                address: m.address || m.url,
                isOpen: m.isOpen,
            }));
        }
        if (redisClient.replicas) {
            info.replicas = Array.from(redisClient.replicas || []).map((r) => ({
                address: r.address || r.url,
                isOpen: r.isOpen,
            }));
        }

        // 내부 prototype 메서드 목록
        const protoKeys = Object.getOwnPropertyNames(Object.getPrototypeOf(redisClient));
        info.prototypeMethods = protoKeys.filter((k) => k !== 'constructor');

    } catch (e) {
        info.error = e.message;
    }

    return info;
}

/**
 * Failover 시뮬레이션 - master/slave 역할 스왑
 * slave 노드에서 CLUSTER FAILOVER를 실행하여 메인터넌스와 유사한 상황 재현
 */
async function simulateFailover(req, res) {
    try {
        if (!isClusterMode) {
            return res.json({ message: 'Not in cluster mode', isClusterMode: false });
        }

        // 1) Failover 전 토폴로지 확인
        const beforeRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
        const beforeNodes = parseClusterNodes(beforeRaw);
        logger.i('failover', '=== Before Failover ===');
        beforeNodes.forEach((n) => logger.i('failover', `  ${n.endpoint} ${n.flags} slots=${n.slots}`));

        // 2) CLUSTER FAILOVER 실행 (slave 노드에서 실행해야 함)
        //    클러스터 클라이언트는 기본적으로 master로 명령을 보내므로,
        //    slave 노드의 주소를 찾아서 직접 연결하여 failover 실행
        let failoverResult = null;
        let failoverError = null;
        try {
            // 먼저 직접 CLUSTER FAILOVER 시도
            failoverResult = await redisClient.sendCommand(undefined, false, ['CLUSTER', 'FAILOVER']);
        } catch (e) {
            failoverError = e.message;
            logger.d('failover', 'CLUSTER FAILOVER direct attempt:', e.message);
        }

        // 3) 잠시 대기 후 토폴로지 재확인
        await new Promise((r) => setTimeout(r, 2000));

        const afterRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
        const afterNodes = parseClusterNodes(afterRaw);
        logger.i('failover', '=== After Failover (2s later) ===');
        afterNodes.forEach((n) => logger.i('failover', `  ${n.endpoint} ${n.flags} slots=${n.slots}`));

        // 4) 연결 테스트 - failover 후 정상 동작하는지 확인
        const testKey = `failover-test:${Date.now()}`;
        let writeOk = false;
        let readOk = false;
        try {
            await redisClient.set(testKey, 'after-failover', { EX: 30 });
            writeOk = true;
            const val = await redisClient.get(testKey);
            readOk = val === 'after-failover';
        } catch (e) {
            logger.e('failover', 'Post-failover read/write test failed:', e.message);
        }

        res.json({
            before: beforeNodes,
            failoverResult,
            failoverError,
            after: afterNodes,
            postFailoverTest: { writeOk, readOk },
            timestamp: new Date().toISOString(),
        });
    } catch (err) {
        logger.e('failover', 'Failover simulation failed:', err.message);
        res.status(500).json({ error: err.message });
    }
}

/**
 * 토폴로지 변경 모니터링 - 연속으로 호출하며 노드 역할 변화 감시
 * ?duration=10&interval=1 (초 단위, 기본 10초간 1초 간격)
 */
async function monitorTopology(req, res) {
    try {
        if (!isClusterMode) {
            return res.json({ message: 'Not in cluster mode', isClusterMode: false });
        }

        const durationSec = parseInt(req.query.duration) || 10;
        const intervalSec = parseFloat(req.query.interval) || 1;
        const snapshots = [];

        const endTime = Date.now() + durationSec * 1000;
        while (Date.now() < endTime) {
            try {
                const nodesRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
                const nodes = parseClusterNodes(nodesRaw);

                // PING으로 latency도 측정
                const pingStart = Date.now();
                await redisClient.ping();
                const pingMs = Date.now() - pingStart;

                snapshots.push({
                    time: new Date().toISOString(),
                    pingMs,
                    nodes: nodes.map((n) => ({
                        endpoint: n.endpoint,
                        flags: n.flags,
                        linkState: n.linkState,
                        slots: n.slots,
                    })),
                });
            } catch (e) {
                snapshots.push({
                    time: new Date().toISOString(),
                    error: e.message,
                });
            }
            await new Promise((r) => setTimeout(r, intervalSec * 1000));
        }

        res.json({
            durationSec,
            intervalSec,
            totalSnapshots: snapshots.length,
            snapshots,
        });
    } catch (err) {
        logger.e('monitorTopology', 'Error:', err.message);
        res.status(500).json({ error: err.message });
    }
}

/**
 * 연결 방식 비교 정보 조회
 * - 현재 연결 모드 (oss-cluster / enterprise / standalone)
 * - 각 모드의 특성 및 Failover 시 차이점 설명
 */
async function getConnectionModeInfo(req, res) {
    try {
        const info = {
            currentMode: connectionMode,
            isClusterMode,
            isOpen: redisClient.isOpen,
            description: getConnectionModeDescription(connectionMode),
        };

        // 현재 연결 테스트
        try {
            const start = Date.now();
            await redisClient.ping();
            info.pingLatencyMs = Date.now() - start;
            info.status = 'connected';
        } catch (e) {
            info.status = 'disconnected';
            info.error = e.message;
        }

        // 클러스터 모드일 때 추가 정보
        if (isClusterMode) {
            try {
                const nodesRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
                const nodes = parseClusterNodes(nodesRaw);
                info.connectedNodes = nodes.map((n) => ({
                    endpoint: n.endpoint,
                    flags: n.flags,
                    linkState: n.linkState,
                    slots: n.slots,
                }));
                info.topologyManagedBy = 'client (node-redis)';
            } catch (_) {}
        } else if (connectionMode === 'enterprise') {
            info.topologyManagedBy = 'Azure proxy';
        }

        info.failoverBehavior = getFailoverBehavior(connectionMode);
        info.timestamp = new Date().toISOString();

        res.json(info);
    } catch (err) {
        logger.e('getConnectionModeInfo', 'Error:', err.message);
        res.status(500).json({ error: err.message });
    }
}

function getConnectionModeDescription(mode) {
    const descriptions = {
        'oss-cluster': 'OSS Cluster Policy (createCluster) - 클라이언트가 slot→node 매핑을 관리. MOVED/ASK 응답을 통해 각 shard에 직접 연결.',
        'enterprise': 'Enterprise Cluster Policy (createClient) - Azure proxy가 클러스터 라우팅 처리. 단일 엔드포인트로 연결.',
        'standalone': 'Standalone (createClient) - 단일 Redis 인스턴스에 직접 연결.',
    };
    return descriptions[mode] || 'Unknown mode';
}

function getFailoverBehavior(mode) {
    const behaviors = {
        'oss-cluster': {
            risk: 'HIGH',
            description: 'Failover 시 기존 node endpoint가 무효화되면 클라이언트의 topology cache가 stale 상태가 됨. MOVED/ASK를 수신하지 못하면 topology 갱신 불가 → 연결 복구 실패 가능.',
            mitigation: 'topology refresh 주기 설정, reconnectStrategy 보강, Health Check 강화',
        },
        'enterprise': {
            risk: 'LOW',
            description: 'Failover 시 Azure proxy가 자동으로 새 node로 라우팅. 클라이언트는 단일 엔드포인트만 사용하므로 topology 변경에 영향 없음.',
            mitigation: 'reconnectStrategy로 일시적 연결 끊김만 처리하면 됨',
        },
        'standalone': {
            risk: 'MEDIUM',
            description: 'Failover 시 단일 엔드포인트로 재연결 시도. DNS 갱신에 의존.',
            mitigation: 'reconnectStrategy 설정',
        },
    };
    return behaviors[mode] || {};
}

/**
 * Failover 복구 테스트 - write/read를 반복하며 연결 복구 여부 확인
 * ?duration=30&interval=2 (초 단위, 기본 30초간 2초 간격)
 * Failover 전에 호출 → Failover 발생 → 복구 과정을 실시간 관찰
 */
async function testFailoverRecovery(req, res) {
    try {
        const durationSec = parseInt(req.query.duration) || 30;
        const intervalSec = parseFloat(req.query.interval) || 2;
        const results = [];

        logger.i('failoverRecovery', `Starting failover recovery test (${durationSec}s, ${intervalSec}s interval, mode: ${connectionMode})`);

        const endTime = Date.now() + durationSec * 1000;
        let seq = 0;

        while (Date.now() < endTime) {
            seq++;
            const testKey = `failover-recovery-test:${seq}`;
            const testValue = `val-${seq}-${Date.now()}`;
            const result = { seq, time: new Date().toISOString() };

            // Write 테스트
            try {
                const writeStart = Date.now();
                await redisClient.set(testKey, testValue, { EX: 60 });
                result.writeOk = true;
                result.writeMs = Date.now() - writeStart;
            } catch (e) {
                result.writeOk = false;
                result.writeError = e.message;
                logger.e('failoverRecovery', `Write #${seq} failed: ${e.message}`);
            }

            // Read 테스트
            try {
                const readStart = Date.now();
                const retrieved = await redisClient.get(testKey);
                result.readOk = true;
                result.readMs = Date.now() - readStart;
                result.dataMatch = retrieved === testValue;
            } catch (e) {
                result.readOk = false;
                result.readError = e.message;
                logger.e('failoverRecovery', `Read #${seq} failed: ${e.message}`);
            }

            // 클러스터 모드에서 현재 연결된 노드 정보
            if (isClusterMode) {
                try {
                    const nodesRaw = await redisClient.sendCommand(undefined, true, ['CLUSTER', 'NODES']);
                    const masters = parseClusterNodes(nodesRaw)
                        .filter((n) => n.flags.includes('master'))
                        .map((n) => n.endpoint);
                    result.connectedMasters = masters;
                } catch (_) {}
            }

            result.isOpen = redisClient.isOpen;
            results.push(result);

            await new Promise((r) => setTimeout(r, intervalSec * 1000));
        }

        const summary = {
            connectionMode,
            totalTests: results.length,
            writeSuccess: results.filter((r) => r.writeOk).length,
            writeFail: results.filter((r) => !r.writeOk).length,
            readSuccess: results.filter((r) => r.readOk).length,
            readFail: results.filter((r) => !r.readOk).length,
            avgWriteMs: Math.round(results.filter((r) => r.writeMs).reduce((sum, r) => sum + r.writeMs, 0) / (results.filter((r) => r.writeMs).length || 1)),
            avgReadMs: Math.round(results.filter((r) => r.readMs).reduce((sum, r) => sum + r.readMs, 0) / (results.filter((r) => r.readMs).length || 1)),
        };

        res.json({ summary, results });
    } catch (err) {
        logger.e('failoverRecovery', 'Error:', err.message);
        res.status(500).json({ error: err.message });
    }
}

module.exports = {
    getClusterInfo,
    getClusterSlots,
    testKeyRouting,
    getConnectionStatus,
    getClientList,
    simulateFailover,
    monitorTopology,
    getConnectionModeInfo,
    testFailoverRecovery,
};
