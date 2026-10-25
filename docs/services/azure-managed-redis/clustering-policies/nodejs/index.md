---
title: "Azure Managed Redis Node.js: 정책별 클라이언트 선택과 토폴로지 갱신"
description: node-redis와 ioredis의 정책별 클라이언트 선택, 인증·TLS 구성, 토폴로지 갱신과 연결 검증 방법을 설명합니다.
document_type: guide
topic_order: 1
services:
- azure-managed-redis
technologies:
- nodejs
- redis
tags:
- build
- operate
status: current
verification_status: verified
sources_checked_at: 2026-10-25
official_sources:
- title: 'Quickstart: Connect to Azure Managed Redis in a Node.js app'
  url: https://learn.microsoft.com/azure/redis/nodejs-get-started
- title: Choose a clustering policy for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/choose-clustering-policy
- title: Connection resilience with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-connection
- title: Node.js Best Practices
  url: https://github.com/Azure/AzureCacheForRedis/blob/main/Redis-BestPractices-Node-js.md
- title: node-redis v5 to v6 migration guide
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/docs/v5-to-v6.md
- title: node-redis createClient configuration
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/docs/client-configuration.md
- title: node-redis cluster options
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/packages/client/lib/cluster/index.ts
- title: node-redis cluster reconnection tracker
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/packages/client/lib/cluster/cluster-reconnection-tracker.ts
- title: node-redis 5.11.0 cluster options
  url: https://github.com/redis/node-redis/blob/redis@5.11.0/packages/client/lib/cluster/index.ts
- title: node-redis command options
  url: https://github.com/redis/node-redis/blob/redis@6.0.0/docs/command-options.md
- title: ioredis Cluster
  url: https://github.com/redis/ioredis#cluster
last_verified: 2026-10-25
review_cycle_days: 180
applies_to:
- Azure Managed Redis
- node-redis 6.0.0 / ioredis
related_cases:
- ../../cluster-failover-recovery/index.md
related_guides:
- ../../migration-from-azure-cache/index.md
---

# Azure Managed Redis Node.js: 정책별 클라이언트 선택과 토폴로지 갱신 { #azure-managed-redis-nodejs }

이 문서는 Azure Managed Redis에 연결할 **Node.js 코드**를 작성하는 독자를 위한 가이드입니다. 정책의 선택 기준과 명령 제약은 [정책 개요](../index.md#policy-comparison), 기존 Azure Cache for Redis에서 바꾸어야 할 항목은 [마이그레이션 가이드](../../migration-from-azure-cache/index.md)에서 확인합니다.

## 실제 정책·캐시 호스트·인증 사용자 확인 { #_1 }

- 캐시의 실제 정책을 [조회](../index.md#set-and-check-policy)합니다. 아래 예제의 `REDIS_POLICY`는 코드 분기용 값이며 **리소스 정책을 변경하지 않습니다.**
- `REDIS_HOST`에는 `<cache-name>.<region>.redis.azure.net` 형태의 호스트만 넣습니다. URL 스킴이나 포트는 넣지 않습니다.
- 실행 환경에서 캐시와 발견된 샤드에 접근할 수 있어야 합니다. TLS 인증서 검증을 끄는 방식으로 연결 오류를 우회하지 않습니다.
- node-redis 예제는 **Node.js 20 이상, node-redis 6.x**를 기준으로 합니다. 인증에 사용하는 사용자·서비스 주체는 캐시의 Microsoft Entra 인증 사용자로 등록해야 합니다.

## OSS는 클러스터 생성자, Enterprise·Non-clustered는 일반 생성자 { #_2 }

| 라이브러리 | OSS | Enterprise / Non-clustered |
|---|---|---|
| node-redis | `createCluster({ rootNodes, defaults })` | `createClient({ url })` |
| ioredis | `new Redis.Cluster(startupNodes, options)` | `new Redis(options)` |

Enterprise에 클러스터 클라이언트를 연결하거나 OSS에 일반 클라이언트를 연결하지 않습니다. 이 표는 생성자 선택만 보여주며 인증·TLS·복구 설정까지 완료했다는 의미는 아닙니다.

## node-redis: Entra ID 인증·TLS·정책별 생성자를 함께 구성 { #node-redis }

다음은 인증 공급자 생성부터 연결·쓰기·읽기·정리까지 포함한 **독립 실행 예제**입니다. 기존 애플리케이션에 정의된 `provider`나 `reconnectStrategy`를 전제로 하지 않습니다.

```bash
npm install redis@6 @redis/entraid @azure/identity
```

`REDIS_HOST`와 `REDIS_POLICY`(`OSS`, `Enterprise`, `Non-clustered` 중 하나)를 설정하고, 아래 코드를 CommonJS 파일로 실행합니다. `DefaultAzureCredential`이 사용하는 개발자 로그인이나 Managed Identity는 실행 환경에 맞게 준비합니다.

```javascript
const net = require('node:net');
const { createClient, createCluster } = require('redis');
const { DefaultAzureCredential } = require('@azure/identity');
const {
  EntraIdCredentialsProviderFactory,
  REDIS_SCOPE_DEFAULT,
} = require('@redis/entraid');

async function main() {
  const host = process.env.REDIS_HOST;
  const policy = process.env.REDIS_POLICY;
  if (!host || !['OSS', 'Enterprise', 'Non-clustered'].includes(policy)) {
    throw new Error('REDIS_HOST and a valid REDIS_POLICY are required');
  }

  const credentialsProvider =
    EntraIdCredentialsProviderFactory.createForDefaultAzureCredential({
      credential: new DefaultAzureCredential(),
      scopes: REDIS_SCOPE_DEFAULT,
      options: {},
      tokenManagerConfig: { expirationRefreshRatio: 0.8 },
    });
  const connection = {
    credentialsProvider,
    pingInterval: 60_000,
    socket: { tls: true, servername: host, connectTimeout: 5_000 },
  };
  const url = `rediss://${host}:10000`;
  const client = policy === 'OSS'
    ? createCluster({
        rootNodes: [{ url }],
        defaults: connection,
        topologyRefreshOnReconnectionAttemptStrategy: 5_000,
        nodeAddressMap(address) {
          const separator = address.lastIndexOf(':');
          const nodeHost = address.slice(0, separator).replace(/^\[|\]$/g, '');
          return {
            host: net.isIP(nodeHost) ? host : nodeHost,
            port: Number(address.slice(separator + 1)),
          };
        },
      })
    : createClient({ url, ...connection });

  client.on('error', (error) => console.error('Redis connection error:', error));
  try {
    await client.connect();
    await client.set('docs:nodejs:check', 'ok', { EX: 60 });
    const value = await client.get('docs:nodejs:check');
    if (value !== 'ok') {
      throw new Error('Redis read/write verification failed');
    }
    console.info('Redis read/write verification passed');
  } finally {
    if (client.isOpen) client.destroy();
  }
}

main().catch((error) => {
  console.error('Redis example failed:', error);
  process.exitCode = 1;
});
```

OSS의 인증·TLS 설정은 `rootNodes` 하나에만 넣지 않고 `defaults`에 둡니다. 그래야 발견된 노드에도 적용됩니다. `nodeAddressMap`은 IP로 안내된 노드를 캐시 호스트 이름으로 연결하면서 발견된 포트는 유지합니다. 이는 [Microsoft Learn Node.js 빠른 시작](https://learn.microsoft.com/azure/redis/nodejs-get-started)의 주소 매핑 방식입니다.

예제는 연결 확인 후 종료하는 프로그램입니다. 실제 서버에서는 요청마다 클라이언트를 만들지 말고 재사용하며, 종료 시 정리합니다. 재시도는 node-redis의 기본 백오프·지터를 사용합니다. 빠른 시작의 실패 즉시 중단하는 `reconnectStrategy`를 운영 설정으로 그대로 가져오지 않습니다.

## ioredis: 접근 키 인증과 OSS 슬롯 갱신 주기 설정 { #ioredis }

이미 ioredis를 사용하는 프로젝트라면 생성자와 갱신 옵션을 확인합니다. 아래 코드는 **키 인증을 허용한 테스트 캐시**에 대한 별도 예제입니다. Microsoft Entra 토큰을 고정된 비밀번호처럼 넣어 두는 예제가 아니며, Entra 인증은 토큰 갱신까지 구현해야 합니다.

`ioredis` 패키지를 설치한 뒤 `REDIS_HOST`, `REDIS_POLICY`, `REDIS_ACCESS_KEY`를 실행 환경에서 전달합니다. 키를 코드나 공개 로그에 기록하지 않습니다.

```javascript
const Redis = require('ioredis');

async function main() {
  const host = process.env.REDIS_HOST;
  const policy = process.env.REDIS_POLICY;
  const password = process.env.REDIS_ACCESS_KEY;
  if (!host || !password || !['OSS', 'Enterprise', 'Non-clustered'].includes(policy)) {
    throw new Error('REDIS_HOST, REDIS_ACCESS_KEY and a valid REDIS_POLICY are required');
  }
  const connection = {
    username: 'default',
    password,
    tls: { servername: host },
    connectTimeout: 5_000,
  };
  const client = policy === 'OSS'
    ? new Redis.Cluster([{ host, port: 10000 }], {
        lazyConnect: true,
        slotsRefreshInterval: 5_000,
        redisOptions: connection,
      })
    : new Redis({ host, port: 10000, lazyConnect: true, ...connection });

  client.on('error', (error) => console.error('Redis connection error:', error));
  try {
    await client.connect();
    await client.set('docs:ioredis:check', 'ok', 'EX', 60);
    if (await client.get('docs:ioredis:check') !== 'ok') {
      throw new Error('Redis read/write verification failed');
    }
    console.info('Redis read/write verification passed');
  } finally {
    client.disconnect();
  }
}

main().catch((error) => {
  console.error('Redis example failed:', error);
  process.exitCode = 1;
});
```

`slotsRefreshInterval`의 기본값은 비활성입니다. 위의 5초는 이 가이드의 시작 예시이지 ioredis나 Azure가 보장하는 복구 시간이 아닙니다. 운영에서는 [공통 연결 원칙](../index.md#connection-resilience)에 따라 유휴 연결 유지와 재시도 간격도 조정합니다.

## 기존 주소 재연결과 새 샤드 발견은 별도 동작 { #topology-refresh }

소켓을 같은 주소에 다시 연결하는 일과, **새 샤드 주소를 발견하는 일**은 다릅니다. OSS에서는 둘 다 확인해야 합니다.

| 구성 | 확인할 동작 |
|---|---|
| node-redis 6.0.0 | `topologyRefreshOnReconnectionAttemptStrategy`가 준비 완료 후 노드 재연결 시도를 계기로 백그라운드 갱신을 판단합니다. 기본 지연 기준은 5000ms이며 `false` 또는 `0`이면 비활성입니다. |
| node-redis 5.x 유지 | 6.x의 위 옵션을 그대로 적용할 수 없습니다. 지속적인 연결 실패에 대한 클라이언트 재생성 경로를 검토하거나 업그레이드를 계획합니다. |
| ioredis | `MOVED` 처리에 더해 `slotsRefreshInterval`로 주기적 슬롯 정보 갱신을 설정할 수 있습니다. |

node-redis 6.0.0의 5000ms는 **재연결 시도 시 평가하는 갱신 기준**입니다. 장애 후 정확히 5초 안에 복구된다는 뜻은 아닙니다. 새 토폴로지를 읽을 수 있는 노드가 있어야 하고 네트워크·인증 문제도 해결되어야 합니다.

5.x에서 6.x로 올릴 때는 [공식 마이그레이션 문서](https://github.com/redis/node-redis/blob/redis@6.0.0/docs/v5-to-v6.md)를 함께 확인합니다.

- Node.js 최소 버전이 20으로 바뀝니다.
- 기본 프로토콜이 RESP3로 바뀌므로 사용 중인 명령의 반환 형식을 검증합니다.
- `commandOptions.timeout` 기본값은 5000ms입니다. 이는 **소켓에 아직 쓰지 못한 명령의 대기**를 제한하므로 전체 응답 시간 제한과 같지 않습니다.
- RESP3에서는 maintenance 알림의 기본 동작도 바뀝니다. 서버 측 지원 확인 없이 이를 Azure의 복구 보장으로 해석하지 않습니다.

오류가 지속되면 [Azure Node.js 모범 사례](https://github.com/Azure/AzureCacheForRedis/blob/main/Redis-BestPractices-Node-js.md)가 설명하는 연결 재생성을 검토합니다. 문서의 약 30초는 예시이며, 애플리케이션의 허용 중단 시간에 맞춰 정합니다. 재생성 중인 요청 처리와 기존 연결 정리를 설계하지 않은 단순 반복 재생성은 피합니다.

## 여러 슬롯·연결 단절·토큰 갱신까지 검증 { #_3 }

1. 선택한 정책과 생성자가 맞는지 확인하고 예제의 TTL 있는 키 쓰기·읽기를 실행합니다.
2. OSS에서는 `PING` 성공만 보지 말고 서로 다른 슬롯에 속한 키들로 요청합니다. 여러 샤드에 대한 네트워크·TLS 연결을 확인하기 위해서입니다.
3. 테스트 환경에서 연결 단절 후 재연결·토폴로지 갱신 로그와 요청 복구 시간을 확인합니다. 단순 네트워크 차단은 실제 Azure 노드 교체와 동일한 재현이 아닙니다.
4. Entra 인증은 토큰 갱신 시점까지 실행해 확인합니다. 초기 연결만 성공한 것으로 인증 검증을 끝내지 않습니다.
5. 운영에서는 오류율·지연·연결 수를 관찰하고, 명령 실패를 정상적인 캐시 미스로 숨기지 않습니다.

특정 구성에서 복구되지 않았던 경과는 [Failover 후 재연결 실패 사례](../../cluster-failover-recovery/index.md)에 보존합니다. 그 사례의 축약 코드를 현재 권장 설정으로 복사하지 않습니다.
