# 02. 클라이언트·SDK 확인사항 — 무엇을 고쳐야 하는가

> 이 문서는 [ACR → AMR 마이그레이션 가이드](../azure-cache-to-managed-redis-migration.md)의 상세 문서입니다.
> **절 번호는 문서마다 1부터 매깁니다.** 다른 문서를 가리킬 때는 문서 이름을 함께 씁니다.
> 측정값은 Korea Central에서 3.77GB / 215만 키 규모로 잰 것입니다 ([테스트 환경](03-migration-paths.md#61-테스트-환경)).

관련 문서: [ACR과 AMR의 차이](01-differences.md) · [이관 경로와 실측](03-migration-paths.md)

---


[ACR과 AMR의 차이](01-differences.md) 2절의 결론은 "우리 애플리케이션이 허용 목록 밖의 다중 키 명령을 쓰는가"를 확인하라는 것이었습니다.
이 문서가 그 확인 목록입니다. **데이터를 옮기기 전에, `clusteringPolicy`를 정하기 전에 해야 하는 작업입니다.**

## 1. 연결 설정 — 무조건 바뀌는 것

| 항목 | ACR | AMR |
|---|---|---|
| 포트 | 6380 (TLS) / 6379 (비TLS) | **10000** (TLS·비TLS 공통) |
| 호스트명 | `<name>.redis.cache.windows.net` | `<name>.<region>.redis.azure.net` |
| TLS | 두 모드 **동시 지원** | **생성 시 한 모드만 선택**, 이후 전 클라이언트가 동일 모드 |
| 데이터베이스 | SKU에 따라 16~64개 | **0번 하나** |
| Redis 버전 | 6.0.x | 7.4.x |
| `CONFIG` 변경 | 명령 자체가 차단 (실측) | 명령은 통과하나 반영 안 됨 (실측) |

두 쪽 모두 **설정 변경은 관리 평면을 거쳐야 합니다.** 다만 실패하는 방식이 다릅니다 —
ACR은 `unknown command`로 시끄럽게 실패하고, AMR은 `OK`를 돌려주면서 조용히 무시합니다 ([6절](#6-tier-34--정책-의존-항목과-관리-명령)).

포트가 바뀐다는 것은 **방화벽·NSG·프라이빗 엔드포인트 규칙도 바뀐다**는 뜻입니다.
연결 문자열만 고치고 네트워크 규칙을 빠뜨리는 것이 컷오버 당일 가장 흔한 실패입니다.

## 2. SDK별 확인 포인트

> 이 표는 각 SDK의 문서·API 기준으로 정리한 것입니다.
> **이 랩에서 실제로 접속해 본 것은 `redis-py` 하나뿐입니다** (비클러스터·클러스터 양쪽 모두, [ACR과 AMR의 차이 2.4절](01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)).
> 나머지 SDK는 자신의 환경에서 확인하세요.

| SDK | `EnterpriseCluster`로 갈 때 | `OSSCluster`로 갈 때 | 함께 볼 것 |
|---|---|---|---|
| `redis-py` (Python) | `Redis`/`StrictRedis` 그대로 — **실측** | `RedisCluster`로 교체 — **실측** | `ssl=True`, `port=10000`, `db=0`. `OSSCluster`에서는 TLS 호스트명 검증 문제 있음 (아래) |
| `StackExchange.Redis` (.NET) | `ConnectionMultiplexer` 그대로 | 그대로 (MOVED 자동 처리) | `ssl=true`, **`defaultDatabase` 제거**, `IServer.ConfigSet`은 실패, 크로스 슬롯 `IBatch`/`ITransaction` 주의 |
| Lettuce (Java / Spring Boot 기본) | `RedisClient` 그대로 | **`RedisClusterClient`로 교체** | `spring.data.redis.database=0`, `ssl: true`, `spring.data.redis.cluster.nodes`로 설정 형태가 바뀜 |
| Jedis (Java) | `JedisPool` 그대로 | **`JedisCluster`로 교체** — `select()` 자체가 없음 | |
| ioredis (Node) | `new Redis()` 그대로 | **`new Redis.Cluster()`로 교체** | `tls: {}`, `db` 옵션 제거 |
| node-redis v4+ | `createClient` 그대로 | **`createCluster`로 교체** | `socket.tls: true` |
| go-redis | `redis.NewClient` 그대로 | **`redis.NewClusterClient`로 교체** | `TLSConfig` 필수 |

**핵심은 한 줄입니다.** `EnterpriseCluster`를 고르면 SDK 객체를 바꿀 필요가 없고,
`OSSCluster`를 고르면 대부분의 SDK에서 **클러스터 전용 클라이언트로 교체**해야 합니다.
그리고 클러스터 클라이언트로 바꾸는 순간 `SELECT`, 크로스 슬롯 파이프라인, 서버 전체 대상 명령의 동작이 함께 달라집니다.

`OSSCluster`로 갈 때 SDK와 무관하게 두 가지를 더 확인하세요. 둘 다 이 랩에서 실제로 걸렸던 항목입니다.

- **비클러스터 클라이언트를 그대로 두면 안 됩니다.** 연결도 되고 `SET`/`GET`도 되지만
  다중 키 명령이 커넥션 단위로 `MOVED`를 냅니다 ([ACR과 AMR의 차이 2.4절](01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)).
- **클러스터 클라이언트는 샤드 IP로 재접속하므로 TLS 호스트명 검증에서 막힐 수 있습니다.**
  인증서가 `<region>.redis.azure.net` 이름으로 발급돼 있어 IP와 대조하면 실패합니다.
  SDK마다 해법이 다르니(SNI 지정, 호스트명 검증 옵션 등) 미리 확인하세요.

## 3. 명령어 감사 — 자동 스캔

정적 스캔 스크립트를 [`migration-lab/audit_commands.sh`](../migration-lab/audit_commands.sh)에 넣어 뒀습니다.

```bash
./migration-lab/audit_commands.sh ./src ./config
# TIER 1 적중이 있으면 종료 코드 1 (CI 게이트로 쓸 수 있습니다)
```

| 등급 | 의미 | 조치 |
|---|---|---|
| **TIER 1** | 다중 DB, 키스페이스 알림 의존 — **정책으로 해결 안 됨** | 코드 수정 / 별도 판단 ([3.4](#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)) |
| **TIER 2** | 허용 목록 6개 밖의 크로스 슬롯 다중 키 명령 | 해시 태그 / 로직 대체 / `NoCluster` ([3.5](#5-tier-2--크로스-슬롯-다중-키-명령)) |
| **TIER 3** | 허용 목록 6개의 다중 키 호출 | `OSSCluster`를 고를 때만 문제 ([3.6](#6-tier-34--정책-의존-항목과-관리-명령)) |
| **TIER 4** | 서버·관리 명령 | 대부분 양쪽에서 차단 ([3.6](#6-tier-34--정책-의존-항목과-관리-명령)) |

> **스크립트는 [7절](#7-정적-스캔만으로는-부족합니다)과 반드시 함께 쓰세요.**
> 정적 스캔은 프레임워크가 대신 호출하는 명령을 구조적으로 놓칩니다.

## 4. TIER 1 — 정책과 무관하게 반드시 고쳐야 하는 것

`NoCluster`를 골라도, 해시 태그를 다 붙여도 해결되지 않습니다. **코드를 고치는 것 말고는 방법이 없습니다.**

| 확인 대상 | 무엇을 찾나 | 왜 |
|---|---|---|
| **다중 데이터베이스** | `SELECT n` (n≥1), `MOVE`, `SWAPDB`, 커넥션 문자열 끝의 `/1`~`/63`, Spring `spring.redis.database`, Lettuce/Jedis의 `database` 옵션, `redis://host:6380/2` | **AMR은 데이터베이스 0 하나만 제공합니다.** ACR은 SKU에 따라 **최대 16~64개**를 씁니다 (C0~C3·P1 16개, C4·P2 32개, C5·P3 48개, C6·P4·P5 64개). 여기서 넘어오면 깨짐 |
| **키스페이스 알림** | `__keyspace@0__:`, `__keyevent@0__:expired`, `notify-keyspace-events`, `RedisIndexedSessionRepository`, `@EnableRedisIndexedHttpSession` | **문서와 실측이 어긋나는 항목.** 문서는 AMR 미지원이라고 하지만, 이 랩의 AMR은 기본값 `AKE`로 이벤트를 실제로 발행. 지원 대상이 아닌 동작에 의존하는 셈이라 그대로 두면 위험 |

Redis 클러스터를 켠 Premium ACR에서 넘어온다면 이미 DB 0뿐이라 이 항목은 해당 없습니다.
문제가 되는 건 **비클러스터 ACR에서 DB를 용도별로 나눠 쓰던 경우**입니다 (`0`=캐시, `1`=세션, `2`=큐 같은 패턴).
AMR에서는 키 접두사로 분리해야 하고, **`FLUSHDB`로 특정 용도만 비우던 운영 절차가 함께 깨집니다.**

키스페이스 알림은 **이 가이드에서 문서와 실측이 갈린 유일한 항목**이라 따로 적습니다.

Microsoft 문서는 명시적으로 미지원이라고 씁니다.

> **Keyspace notifications.** Keyspace notifications are supported in Azure Cache for Redis
> but aren't currently available in Azure Managed Redis.

그런데 이 랩에서 AMR에 실제로 붙어 보면 반대로 나옵니다.

| 확인한 것 | ACR (Basic C0) | AMR (`EnterpriseCluster` / `OSSCluster` 동일) |
|---|---|---|
| `notify-keyspace-events` 기본값 | 빈 값 | **`AKE`** |
| `set`/`expire`/`del` 이벤트 구독 | **0건 수신** | **10건 수신** |
| `expired` 이벤트 (TTL 만료 대기) | 0건 | **2/2건 수신** |
| 데이터 평면에서 `CONFIG`로 켜기 | `unknown command`로 차단 | 명령은 통과하나 **값이 바뀌지 않음** (`AKE` 유지) |
| 관리 평면(`az redis update`)으로 켜기 | Basic은 **거부** (`not allowed on 'Basic' cache instances`) | 해당 옵션 없음 |

즉 **ACR에서는 꺼져 있고 AMR에서는 켜져 있는**, 문서 설명과 정반대 상태였습니다.
(ACR의 `notify-keyspace-events`는 Standard/Premium 전용 설정이라 Basic C0에서는 양쪽 평면 모두 막혀 있습니다.
Standard/Premium에서 관리 평면으로 켜지는 것까지는 이 랩에서 확인하지 못했습니다.)

**그래도 의존하지 마세요.** 동작한다는 것과 지원된다는 것은 다릅니다.
문서가 미지원이라고 명시한 기능은 사전 공지 없이 바뀔 수 있고, 장애가 나도 지원 대상이 아닙니다.
Spring Session의 `RedisIndexedSessionRepository`처럼 만료 이벤트로 인덱스를 정리하는 구조라면,
지금 당장은 동작하더라도 **인덱싱이 필요 없을 때 `RedisSessionRepository`(비인덱스)로 바꿔 두는 것**이
안전한 선택입니다. 반드시 필요하다면 Microsoft에 현재 지원 상태를 확인하세요.

> 마이그레이션 도구를 쓸 때도 [이관 경로와 실측 3절](03-migration-paths.md#3-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다) 표에 있듯
> **알림 설정 자체는 넘어가지 않습니다.** 타깃에서 다시 확인해야 합니다.

## 5. TIER 2 — 크로스 슬롯 다중 키 명령

**`EnterpriseCluster`를 골라도 실패할 수 있는 명령들입니다.** 허용 목록은 6개(`DEL`·`MSET`·`MGET`·`EXISTS`·`UNLINK`·`TOUCH`)뿐이고,
아래는 전부 그 밖입니다. [ACR과 AMR의 차이 2.4절](01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)에서 목록 밖 24개를 실제로 돌려 봤고
**전부 `CROSSSLOT`으로 실패했습니다.** 아래 표는 그 결과를 계열별로 넓힌 것입니다.

| 계열 | 명령 | 비고 |
|---|---|---|
| 집합 | `SINTER` `SUNION` `SDIFF` `SINTERSTORE` `SUNIONSTORE` `SDIFFSTORE` `SINTERCARD` `SMOVE` | 태그 기반 필터링·추천 로직에서 흔함 |
| 정렬셋 | `ZUNION` `ZINTER` `ZDIFF` `ZUNIONSTORE` `ZINTERSTORE` `ZDIFFSTORE` `ZINTERCARD` `ZRANGESTORE` | 랭킹 집계에서 흔함 |
| 리스트 이동 | `RPOPLPUSH` `BRPOPLPUSH` `LMOVE` `BLMOVE` `LMPOP` `BLMPOP` | **큐 구현의 핵심 패턴.** 작업 큐를 Redis로 쓰면 거의 확실히 걸림 |
| 다중 키 블로킹 | `BLPOP` `BRPOP` `BZPOPMIN` `BZPOPMAX` `BZMPOP` | 키를 하나만 넘기면 문제없지만, 여러 큐를 동시에 기다리는 형태가 문제 |
| 키 조작 | `RENAME` `RENAMENX` `COPY` `SORT ... STORE` | 원본과 대상이 다른 슬롯이면 실패 |
| 비트/HLL | `BITOP` `PFMERGE`, 다중 키 `PFCOUNT` | 일별 UV 집계에서 흔함 |
| 스트림/GEO | 다중 키 `XREAD`/`XREADGROUP`, `GEOSEARCHSTORE` | |
| 기타 | `MSETNX` `LCS` | `MSET`과 달리 허용 목록에 **없음** |
| 트랜잭션 | 서로 다른 슬롯의 키를 묶는 `MULTI`/`EXEC`, `WATCH` | 명령이 아니라 **묶인 키들의 슬롯**이 관건 |
| Lua | `EVAL`/`EVALSHA`/`FCALL`의 `KEYS` 인자가 여러 슬롯에 걸칠 때 | 같은 문제 |

**조치는 셋 중 하나입니다.**

1. **해시 태그로 같은 슬롯에 모읍니다.** ([ACR과 AMR의 차이 2.2절](01-differences.md#22-샤딩과-클러스터--amr은-항상-클러스터입니다))
   가장 정공법이지만 **키 이름이 바뀌므로 마이그레이션 이전에 애플리케이션 배포가 선행돼야 합니다.**
2. **명령을 클라이언트 측 로직으로 대체합니다.** `SUNIONSTORE` → 각 집합을 `SMEMBERS`로 읽어 애플리케이션에서 합치기.
   왕복이 늘어나므로 대상 집합이 작을 때만 유효합니다.
3. **`NoCluster`를 씁니다.** 25GB 이하일 때만 가능하고 성능이 가장 낮습니다.
   Microsoft가 문서에서 `NoCluster`의 대표 사례로 드는 것이 정확히 이 상황(크로스 슬롯 `MULTI` 광범위 사용)입니다.

## 6. TIER 3·4 — 정책 의존 항목과 관리 명령

**TIER 3 (`OSSCluster`를 고를 때만 문제):** 허용 목록 6개 명령(`MGET`/`MSET`/`DEL`/`EXISTS`/`UNLINK`/`TOUCH`)의 다중 키 호출.
`EnterpriseCluster`에서는 그대로 동작하지만, `OSSCluster`에서는 이것들도 같은 슬롯 제약을 받습니다.
**`OSSCluster`를 검토 중이라면 TIER 2와 TIER 3이 모두 0건이어야 무수정 전환이 가능합니다.**

**TIER 4 (서버·관리 명령):** 양쪽이 차단하는 목록이 서로 다릅니다. **합집합을 봐야 합니다.**
아래 표에서 "실측"은 이 랩에서 ACR Basic C0(Redis 6.0.14)과 AMR B0 두 정책에 **비클러스터 클라이언트로**
직접 실행해 본 결과입니다. 나머지는 문서 근거입니다.

| 명령 | ACR | AMR (Redis Enterprise) |
|---|---|---|
| `SELECT n` (n≥1) | 허용 (실측) | **차단** (실측: `DB index is out of range`) |
| `SWAPDB` | 허용 (실측) | **차단** (실측: `unknown command`) |
| `CONFIG GET` / `CONFIG SET` | **차단** (실측: `unknown command`) | **수락** (실측) — 아래 주의 |
| `ROLE` | 허용 (실측) | **허용** (실측) |
| `FAILOVER` | **차단** (실측: `unknown command`) | 차단 (실측: `unknown command`) |
| `REPLICAOF` `SLAVEOF` `SYNC` `PSYNC` `REPLCONF` `MIGRATE` | 차단 (`REPLICAOF` 실측) | 차단 (`REPLICAOF` 실측) |
| `INFO commandstats` | 허용 (실측) | 허용 (실측) |
| `DBSIZE` | 허용 (실측) | 허용 (실측) |
| `ACL` `DEBUG` `SAVE` `BGSAVE` `BGREWRITEAOF` `SHUTDOWN` | 차단 | 차단 |
| `CLUSTER` (쓰기 계열) | 차단 (읽기 전용만 허용) | — |
| `FLUSHALL` `FLUSHDB` | 액티브 지역 복제 사용 시 차단 | — |

ACR 목록은 [미지원 명령 문서](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis) 기준입니다.

**`CONFIG`는 방향이 흔히 알려진 것과 반대였습니다.** ACR에서는 아예 `unknown command`로 막히지만,
AMR에서는 명령이 통과합니다. 문제는 **통과한다고 해서 반영되는 게 아니라는 점**입니다.

| 실행 | AMR 응답 | 실제 |
|---|---|---|
| `CONFIG GET maxmemory` | `[]` (빈 결과) | 조회 자체가 비어 있음 |
| `CONFIG GET notify-keyspace-events` | `AKE` | 조회됨 |
| `CONFIG SET notify-keyspace-events KEA` | `OK` | **바뀌지 않음** — 다시 읽으면 `AKE` |
| `CONFIG SET maxmemory-policy ...` | `Unsupported CONFIG parameter` | 거부 |

`OK`를 받고 설정이 반영됐다고 가정하는 코드는 **조용히 틀립니다.** 예외도 안 나고 로그도 안 남습니다.
설정 변경은 ACR·AMR 모두 **관리 평면(`az redis update` / `az redisenterprise database update`, 포털)** 을 거치세요.
`StackExchange.Redis`의 `IServer.ConfigSet`도 같은 이유로 신뢰할 수 없습니다.

`SELECT`와 `SWAPDB`는 **ACR에서는 되는데 AMR에서 안 되는** 항목이라 특히 놓치기 쉽습니다 (TIER 1과 같은 뿌리입니다).
반대로 `ROLE`은 **양쪽 다 동작**했습니다 — 다만 `OSSCluster`에 **클러스터 클라이언트로** 붙은 조합에서는 실패했으므로,
헬스체크에 쓰고 있다면 클라이언트 종류까지 함께 확인하세요.
이때의 실패는 서버가 거부한 것이 아니라 **클라이언트가 보낼 노드를 못 정해서**입니다
(redis-py: `No way to dispatch this command to Redis Cluster. Missing key.`).
보낼 노드를 지정하는 옵션이 있는 클라이언트라면 그 옵션으로 풀립니다.

## 7. 정적 스캔만으로는 부족합니다

`audit_commands.sh`가 구조적으로 놓치는 것:

- 문자열로 명령을 조립하는 코드 (`redis.execute_command(cmd_name, ...)`)
- **프레임워크가 대신 호출하는 명령** — Spring Session, Celery, Sidekiq, Bull, ORM 2차 캐시, 분산 락 라이브러리(Redisson 등).
  이들은 소스에 명령 이름이 나타나지 않습니다.
- 서드파티 라이브러리 내부

**확정적 근거는 소스 ACR의 런타임 관측입니다.**

```bash
# 실제로 어떤 명령이 얼마나 호출됐는지
redis-cli -h <acr>.redis.cache.windows.net -p 6380 --tls -a <key> INFO commandstats

# 짧게 표본 뜨기 (부하가 큽니다. 프로덕션에서는 수 초만)
redis-cli -h <acr>.redis.cache.windows.net -p 6380 --tls -a <key> MONITOR | head -5000 \
  | awk '{print $4}' | tr -d '"' | tr 'a-z' 'A-Z' | sort | uniq -c | sort -rn
```

`INFO commandstats`는 **재시작 이후 누적**이므로, 하루에 한 번 도는 배치가 쓰는 명령까지 잡으려면
관측 창을 충분히 길게 잡아야 합니다. 정적 스캔과 런타임 관측의 **합집합**을 보세요.

> **두 명령 모두 ACR에서 동작하는 것을 확인했습니다** (Basic C0, Redis 6.0.14).
> `INFO commandstats`는 정상 응답했고, `MONITOR`도 다른 연결에서 실행한 명령을 그대로 받아 왔습니다.
> AMR에서도 `INFO commandstats`는 동작합니다.
> 다만 `MONITOR`는 **모든 명령을 흘려보내므로 부하가 큽니다.** 프로덕션에서는 수 초만 표본을 뜨세요.

---
