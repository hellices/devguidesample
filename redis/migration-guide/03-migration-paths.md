# 03. 이관 경로와 실측 — 경로 A/B/C와 측정 결과

> 이 문서는 [ACR → AMR 마이그레이션 가이드](../azure-cache-to-managed-redis-migration.md)의 상세 문서다.
> **절 번호는 문서마다 1부터 매긴다.** 다른 문서를 가리킬 때는 문서 이름을 함께 쓴다.
> 측정값은 Korea Central에서 3.77GB / 215만 키 규모로 잰 것이다 ([테스트 환경](#61-테스트-환경)).

관련 문서: [ACR과 AMR의 차이](01-differences.md) · [클라이언트·SDK 확인사항](02-client-audit.md)

---

## 1. 경로 A: RDB Export / Import

```
ACR (Premium) --export--> Blob Storage --import--> AMR
```

### 1.1 Export — 정상 동작

| 항목 | 값 |
|---|---|
| 소요 시간 | **186.99초** |
| 결과 blob | 2,271,735,296 B (**2.12 GiB**) |
| 인메모리 대비 | 약 47% (압축됨) |
| 인증 | 시스템 할당 관리 ID |

Export는 관리 ID를 지원하므로 스토리지 계정이 공용 네트워크 접근을 막고 있어도
신뢰할 수 있는 서비스 예외로 동작한다.

### 1.2 Import — 이 환경에서의 실패

```
az redisenterprise database import --sas-uris "https://.../dump.rdb?<sas>"
→ OperationFailed (128.97초 후)
```

원인을 하나씩 짚으면 이렇다.

1. `az redisenterprise database import`는 **`--sas-uris`만 지원한다.** 관리 ID 인증 옵션이 없다.
2. 테넌트에 걸린 Azure Policy(`MCAPSGovDeployPolicies`의 `StorageAccount_PublicNetwork_Modify`,
   `StorageAccount_DisableLocalAuth_Modify`)가 **modify 효과**로 스토리지 계정의
   `publicNetworkAccess=Disabled`와 `allowSharedKeyAccess=false`를 강제한다.
   포털·CLI·raw ARM PATCH로 되돌려도 조용히 원복됐다.
3. SAS 트래픽은 관리 ID와 달리 **신뢰할 수 있는 서비스 우회 대상이 아니다.**
   인터넷에서 해당 blob의 공용 URL에 접근하면 `HTTP 403 AuthorizationFailure`가 돌아온다.

즉 이 실패는 제품 결함이 아니라 **환경 정책과 Import API 인증 방식의 조합** 문제다.

> **시사점**: 규제가 걸린 구독에서는 경로 A가 막힐 수 있다.
> 마이그레이션 계획을 세우기 전에 `az redisenterprise database import`를 작은 RDB로 **먼저 한 번 성공시켜 봐야 한다.**
> 스토리지 계정에 공용 네트워크 접근을 허용할 수 있는지, 공유 키 인증이 켜지는지가 관건이다.

이 문서는 Import 소요 시간을 측정하지 못했다. **모르는 값을 추정치로 쓰지 않았다.**

---

## 2. 경로 B: `SCAN` + `DUMP`/`RESTORE` 프로그래매틱 복사

Basic/Standard처럼 Export를 못 쓰거나 경로 A가 정책으로 막혔을 때 쓰는 대안이다.
[`migration-lab/migrate_scan_copy.py`](../migration-lab/migrate_scan_copy.py)는 이렇게 짜여 있다.

- `KEYS *` 대신 **`SCAN` 커서**를 쓴다. `KEYS`는 O(N) 블로킹 명령이라 수백만 키 인스턴스를 멈춘다.
- 타입별 `HGETALL`/`LRANGE` 대신 **`DUMP` → `RESTORE ... REPLACE`** 를 쓴다. 타입에 무관하고 클라이언트 메모리도 덜 쓴다.
- **`PTTL`을 함께 읽어 TTL을 보존한다.** 이걸 빠뜨리면 만료 예정 키가 영구 키가 된다.
- 읽기·쓰기 모두 파이프라인(500개 단위)으로 묶어 왕복 지연을 상쇄한다.

Redis 6.0.14에서 만든 `DUMP` 페이로드를 Redis 7.4.3에 `RESTORE`하는 것은 정상 동작했다 (오류 0건).

### 2.1 복사 자체의 속도와 정확도

| 항목 | 값 |
|---|---|
| 복사한 키 | 2,129,472 |
| 소요 시간 | **130.2초** (약 16,400 keys/s) |
| `RESTORE` 오류 | **0건** |
| TTL 옮긴 키 | 470,774 |
| TTL 보존 (표본 2,000) | **2,000 / 2,000 (유실 0%)** |
| 값 무결성 (무작위 표본 2,496) | 일치 2,482, **불일치 0**, 타깃에 없음 14 |

### 2.2 복사 중 들어온 쓰기의 48.47% 유실

복사가 도는 동안 소스에 초당 약 140건씩 프로브 키를 쓰면서 각 프로브의 키와 쓰기 시각을 로컬에 기록했다.
복사가 끝난 뒤 타깃에서 프로브를 **값까지** 대조했다.

| 항목 | 값 |
|---|---|
| 기록한 프로브 | 22,644 |
| 타깃에 정상 존재 | 11,668 |
| 타깃에 없음 | **10,976** |
| 타깃에 있으나 값이 옛것 | 0 |
| **유실률** | **48.47%** |
| 유실 구간 | 139.9초 (복사 시작 직후부터 끝까지) |

왜 하필 절반인가. `SCAN`은 키스페이스를 커서로 한 번 훑기 때문에
**커서가 이미 지나간 자리에 새로 쓰인 키는 이번 패스에서 복사되지 않는다.**
복사 도중 무작위 시점에 쓰인 키가 "아직 안 지나간 구간"에 떨어질 확률은 평균 50%다. 실측 48.47%가 그 값이다.

RDB Export도 성질이 같다. Export는 시작 시점의 스냅샷이라 그 이후 쓰기는 담기지 않는다.
복사 방식은 무엇이든 이 문제를 피하지 못한다.

> 소규모 테스트에서 이게 안 보이는 이유가 여기 있다. 키가 몇 개뿐이면 복사가 몇 초 만에 끝나서
> 유실 구간이 사실상 없다. GB 규모에서는 이 구간이 **2분**이다.

### 2.3 반복 복사로 유실이 얼마나 줄어드나

같은 복사를 여러 번 돌리면 이전 패스가 놓친 키를 다음 패스가 회수한다. 실제로 해 봤다.

| 패스 | 소스 쓰기 | 소요 시간 | 복사한 키 | 오류 | 그 시점의 누적 유실 |
|---|---|---|---|---|---|
| 1 | 진행 중 | 135.6초 | 2,130,079 | 0 | — |
| 2 | 진행 중 | 109.9초 | 2,146,668 | 0 | **20.21%** (7,311 / 36,175) |
| 3 | **차단** | 111.1초 | 2,155,260 | 0 | **0%** (0 / 37,456) |

2회 패스 후 남은 유실 7,311건은 **전부 2번째 패스가 도는 동안 쓰인 키**였다
(가장 이른 유실 시각이 2번째 패스 시작 시각과 일치). 1번째 패스가 놓친 것은 2번째 패스가 모두 회수했다.
패스마다 "그 패스가 도는 동안 들어온 쓰기"의 약 절반이 남는 구조다.

쓰기를 차단하고 최종 패스를 돌리자 결과는 깨끗했다.

```
소스: 2,155,260 키 (3.77G)
타깃: 2,155,260 키 (7.47G)
차이: 0

프로브 유실:      0 / 37,456  (0.00%)
TTL 보존:     2,000 / 2,000   (유실 0%)
값 무결성:    2,497 / 2,497   (불일치 0)
```

반복 패스는 **유실을 줄이지만 다운타임은 줄이지 못한다.**
이 스크립트는 델타만 옮기는 게 아니라 매번 **전수 재스캔**을 하기 때문에
쓰기를 차단한 최종 패스도 여전히 전체 키를 훑는다. 그래서 그 패스 시간이 그대로 다운타임이 된다.

이 규모(215만 키 / 3.77GB, 같은 리전 VM에서 실행)에서 **복사 방식의 다운타임 하한은 약 111초**다.
클라이언트가 다른 리전에 있거나 파이프라인 크기가 작으면 더 늘어난다.

---

## 3. 경로 C: 데이터를 옮기지 않는 Azure 마이그레이션 도구

"복제 기반 무중단 마이그레이션"을 기대하고 확인했지만 그런 기능은 없다.

Microsoft 공식 문서는 마이그레이션 경로를 두 가지로 제시한다.
**Option 1은 자체 마이그레이션(권장)**, **Option 2가 마이그레이션 도구(preview)**다.
Option 2에 대한 문서의 제약 목록에는 다음이 그대로 적혀 있다.

> **Data sync not supported.** This tooling will orchestrate hostname/endpoint migration but **does not migrate any data**.

이 도구는 **미리 만들어 둔 AMR로 ACR의 호스트 이름을 넘긴다.**
클라이언트는 같은 호스트 이름과 액세스 키로 재연결되면서 AMR에 붙는다. 데이터는 별도로 옮겨야 한다.

리소스 공급자에 노출된 작업 이름도 이와 일치한다.

```
$ az provider operation show --namespace Microsoft.Cache
Microsoft.Cache/redis/getMigrationInfo/action
Microsoft.Cache/redis/updateMigrationStatus/action
Microsoft.Cache/redis/updateDnsForMigration/action
Microsoft.Cache/redis/rollbackDnsForMigration/action
```

전부 DNS와 상태 조작이다. 데이터 복제 관련 작업은 없다.

### 3.1 문서에 명시된 그 밖의 제약

데이터를 옮기지 않는다는 사실 하나로 대부분 여기서 물러선다.
그걸 감수하기로 했다면 아래를 마저 봐야 한다. 전부
[Migrate with tooling](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-with-tooling)에 적혀 있는 제약이다.

- **전환 시점 통제 불가**: 마이그레이션 시작만 고를 수 있고 실제 트래픽이 언제 넘어가는지는 고를 수 없다.
- **전체 동시 전환**: 하나의 Redis에 붙은 **모든** 애플리케이션이 동시에 전환된다. 서비스 단위 점진 전환이 안 된다.
- **롤백 창 제한**: 마이그레이션이 성공한 뒤 검증하고 되돌릴 수 있는 시간이 짧다.
- **두 호스트명 병존 기간 제한**: 기존 ACR 호스트명은 일정 기간 뒤 자동 삭제된다.
- **관리 작업 잠금**: 상태가 `Migrating`인 동안에는 다른 관리 작업이 차단된다.
- **프라이빗 엔드포인트 미지원**: 프라이빗 엔드포인트를 쓰는 캐시는 아예 대상에서 빠진다.
- **VNet 주입 캐시 미지원**: 같은 이유로 대상 밖이며 검증 단계에서 오류로 잡혀 진행이 막힌다.
- **지역 복제 캐시 미지원**: 지역 복제를 구성한 캐시도 대상이 아니다.
- **설정 미복사**: 관리 ID, 방화벽 규칙, 지속성 설정, 업데이트 일정, 키스페이스 알림은 이관 대상이 아니다.

프라이빗 엔드포인트를 쓰는 프로덕션 환경이라면 애초에 대상이 아니다.

### 3.2 그래도 도구를 쓸 때 알아 둘 것

[Migrate with tooling](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-with-tooling) 기준이다.

- **AMR을 먼저 만들어 둬야 한다.** 도구가 대상을 생성해 주지 않는다.
- 포털에서 `Migrate` → 대상 선택 → **`Validate`** 순서다. 검증 결과는 **경고와 오류로 나뉘고**
  지속성 설정 불일치 같은 것은 경고(무시하고 진행 가능), **VNet 주입은 오류**로 진행이 막힌다.
- 전환 시 클라이언트는 **유지 관리와 비슷한 "연결 끊김(blip)"** 을 겪고 재연결된다.
- ACR을 삭제한 뒤에도 **기존 ACR 호스트명은 계속 AMR을 가리킨다.** 다만 이후 자동 삭제 예정이므로
  애플리케이션은 AMR 호스트명(`<name>.<region>.redis.azure.net`)으로 갱신해야 한다.
- 포털 외에 **PowerShell로 사전 검증·시작·상태 확인·취소**를 할 수 있다.
- 데이터가 필요하면 도구 절차 안에서도 결국 [1·2절](#1-경로-a-rdb-export--import)의 이관을 따로 해야 한다
  (공식 문서의 Step 2b도 self-service의 데이터 이관 절로 연결된다).

---

## 4. 실시간 마이그레이션 전략 — `REPLICAOF`는 왜 안 되는가

2절에서 측정한 111초(3.77GB / 215만 키)는 **복사 방식의 하한**이다. 그 아래로 내려가려면
**"소스가 살아 있는 동안 타깃이 계속 따라오게 하는"** 방식이 필요하다. 이 절이 그 선택지를 정리한다.

### 4.1 가장 먼저 떠오르는 방법, 그리고 왜 막히는가

자체 관리 Redis라면 이게 정석이다.

```
1. 타깃에서 REPLICAOF <소스> <포트>
2. 초기 동기화(RDB 전송) + 이후 스트리밍 복제
3. master_repl_offset 지연이 0에 수렴할 때까지 대기
4. 소스 쓰기 차단 → 타깃에서 REPLICAOF NO ONE으로 승격 → 트래픽 전환
```

다운타임이 4단계의 수 초로 압축된다. 개념적으로 정확하고 실제로 온프레미스 Redis 이관의 표준 절차다.

**하지만 ACR → AMR에서는 소스와 타깃 양쪽 모두에서 차단된다.**

**소스(ACR)가 외부 복제본을 거부한다.** Microsoft의 미지원 명령 목록에
`PSYNC`, `REPLICAOF`, `SLAVEOF`, `SYNC`, `REPLCONF`, `MIGRATE`가 모두 올라 있고 `REPLCONF` 항목에는 이유가 명시돼 있다.

> Azure cache for Redis instances **don't allow customers to add external replicas**.
> — [Redis commands not supported in Azure Cache for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis)

**타깃(AMR)도 복제 명령을 제공하지 않는다.** AMR이 올라가 있는 Redis Enterprise 스택의 호환성 표에서
`REPLICAOF`, `SLAVEOF`, `SYNC`, `PSYNC`, `REPLCONF`, `ROLE`, `FAILOVER`, `MIGRATE`가 전부 **Not supported**다.

즉 "타깃에서 명령을 못 쓴다"와 "소스가 받아 주지 않는다"가 동시에 성립한다. 한쪽만 막혔다면 우회할 여지가 있겠지만 양쪽이다.

**Redis Enterprise의 "Replica Of" 기능은 어떤가.** Redis Enterprise 제품에는 외부 Redis를 소스로 삼는
액티브-패시브 복제(Replica Of) 기능이 실제로 있다. 그러나 **Azure의 ARM 표면에 노출돼 있지 않다.**

```
$ az redisenterprise database create --help
--group-nickname     : Name for the group of linked database resources.
--linked-databases   : List of database resources to link with this database.
```

이건 **AMR ↔ AMR 액티브 지역 복제**다. 링크 대상이 `.../redisEnterprise/.../databases/` 리소스 ID여야 하므로
ACR을 넣을 수 없다. 설령 노출됐더라도 결국 소스를 향해 복제 프로토콜을 말해야 하고 그건 위에서 막혀 있다.

같은 이유로 **`redis-shake`의 `sync` 모드도 쓸 수 없다.** `PSYNC`를 쓰기 때문이다.

> **정리**: 물리적 복제(replication protocol) 기반 전략은 관리형 → 관리형 구간에서 존재하지 않는다.
> 남는 것은 **논리적 복제** — 쓰기를 이벤트나 애플리케이션 레벨에서 관찰해 타깃에 다시 적용하는 방식뿐이다.

### 4.2 RIOT / RIOT-X 라이브 복제 — 의도에 가장 가까운 대안

> **이 랩에서 검증하지 않았다.** 문서 근거만 확인했다.

Microsoft가 self-service 마이그레이션 문서에서 "Programmatic migration" 경로로 안내하는 도구다.
`REPLICAOF`와 **형태는 같고 전송 계층만 다르다** — PSYNC 대신 **키스페이스 알림(pub/sub)** 으로 변경을 관찰한다.

```bash
# 1) 소스 ACR에 키스페이스 알림을 켠다. CONFIG SET이 막혀 있으므로 관리 평면으로 설정한다.
az redis update -n <acr> -g <rg> --set "redisConfiguration.notify-keyspace-events=KEA"

# 2) 스냅샷 + 라이브 스트림
riot replicate \
  -h <acr>.redis.cache.windows.net -p 6380 --tls --pass <key> \
  --target-h <amr>.<region>.redis.azure.net --target-p 10000 --target-tls --target-pass <key> \
  --mode live

# 3) 컷오버 전 대조
riot compare --full ...
```

`--mode live`는 초기 `SCAN` 스냅샷과 실시간 스트림을 **동시에** 돌린다.
2절에서 본 "커서가 지나간 자리의 쓰기가 사라지는" 문제를 알림 스트림이 메워 주는 구조다.

**받아들여야 하는 제약:**

- **일관성을 보장하지 않는다.** RIOT 문서가 직접 그렇게 쓴다 —
  *"The live replication mechanism does not guarantee data consistency."*
  키스페이스 알림은 **fire-and-forget pub/sub**이라 구독자가 잠깐 느리거나 끊기면 그 사이 이벤트는 그냥 사라진다.
  **그래서 컷오버 전 `riot compare --full`이 선택이 아니라 필수다.**
- 알림은 **키 이름만** 알려 준다. RIOT은 이름을 받고 소스에서 값을 다시 읽으므로 소스 읽기 부하가 늘어난다.
- **Basic SKU에서는 쓸 수 없다.** 키스페이스 알림은 Standard 이상이다.
- `KEA`는 모든 이벤트를 발행한다. 쓰기가 많은 인스턴스에서 소스 CPU 부담이 얼마나 되는지는
  **이 랩에서 측정하지 않았다.** 프로덕션에 켜기 전에 관측해야 한다.
- 여기서 알림이 필요한 쪽은 **소스인 ACR**이다. [클라이언트·SDK 확인사항 4절](02-client-audit.md#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)의
  AMR 쪽 논의와는 방향이 다르다. (반대 방향, 즉 AMR에서 다른 곳으로 나가는 라이브 복제는 이 방법으로 안 된다.)

### 4.3 애플리케이션 계층 — 이중 쓰기와 지연 백필

> **이 랩에서 검증하지 않았다.** 설계 지침이다.

**(a) 이중 쓰기** — [마이그레이션 가이드 6.2절](../azure-cache-to-managed-redis-migration.md#62-쓰기를-멈출-수-없는-경우--애플리케이션-이중-쓰기)에서 다룬다. 유실 구간을 원천 제거하는 유일한 방법이지만 애플리케이션 변경이 가장 크다.

**(b) 읽기 폴백 + 지연 백필** — 캐시라면 이쪽이 훨씬 싸다.

```
읽기: AMR 조회 → miss → ACR 조회 → 값이 있으면 AMR에 채우고 반환 → 없으면 원본에서 계산
쓰기: 처음부터 AMR에만
```

트래픽이 도는 대로 뜨거운 키가 자연스럽게 AMR로 넘어가면서 벌크 복사 자체가 필요 없어진다.
쓰기가 AMR에만 가므로 이중 쓰기의 읽기-수정-쓰기 정합성 문제도 없다.
대신 전환 기간 동안 **캐시 미스마다 왕복이 두 번**이고 두 인스턴스를 동시에 유지해야 한다.
TTL이 짧은 순수 캐시라면 며칠이면 ACR을 뗄 수 있다.

### 4.4 프록시 계층 미러링 — 애플리케이션을 안 고치는 경우

> **이 랩에서 검증하지 않았다.**

애플리케이션 코드를 못 고치는 상황(레거시, 서드파티, 다수 팀)에서 이중 쓰기를 인프라로 밀어 넣는 방법이다.
Envoy의 Redis 프록시 필터가 `request_mirror_policy`를 제공한다.

```yaml
prefix_routes:
  catch_all_route:
    cluster: acr_primary
    request_mirror_policy:
      - cluster: amr_target
        exclude_read_commands: true     # 읽기는 미러링하지 않음
        runtime_fraction: { default_value: { numerator: 100, denominator: HUNDRED } }
```

애플리케이션은 프록시 주소만 본다. 쓰기는 ACR과 AMR 양쪽으로 간다.
**미러 트래픽은 fire-and-forget이다.** 응답을 기다리지 않으므로 **AMR 쓰기 실패가 아무 데도 드러나지 않는다.**
Envoy 문서도 이 필터를 "not hardened"로 표기한다. 대조 검증을 반드시 별도로 돌려야 한다.

트래픽 경로에 홉이 하나 늘어나고 프록시 자체가 새로운 단일 장애점이 된다는 것도 계산에 넣어야 한다.

### 4.5 캐시 재수화 — 데이터를 아예 안 옮기는 선택지

**Redis를 순수 look-aside 캐시로만 쓴다면 데이터를 옮길 이유가 없다.** Microsoft도 문서에서 이 선택지를 명시한다.
빈 AMR로 연결을 바꾸고 원본(DB/API)에서 다시 채우면 끝이다. 다운타임 0, 데이터 유실은 "전량이지만 의도된 것".

대신 전제 조건을 반드시 확인해야 한다.

- Redis에만 있는 데이터가 없어야 한다. **세션, 분산 락, 레이트 리밋 카운터, 작업 큐, 스트림은 재계산이 불가능하다.**
  하나라도 있으면 이 방법은 못 쓴다.
- **백엔드가 콜드 스타트 부하를 견뎌야 한다.** 캐시가 비면 모든 요청이 원본으로 간다.
  전환 직후 몇 분간 DB가 감당 못 하면 이 방법이 가장 긴 장애가 된다. 미리 워밍업하거나 점진 전환해야 한다.

### 4.6 비교

4.1부터 4.5까지를 같은 축에 놓으면 고를 것이 꽤 좁아진다.
**"이 랩 검증"이 ✅인 줄은 둘뿐이고 둘 다 `SCAN` 복사다.** 나머지는 설계 지침으로만 읽어야 한다.

| 전략 | 다운타임 | 데이터 유실 | 애플리케이션 변경 | 이 랩 검증 |
|---|---|---|---|---|
| `REPLICAOF` 복제 | — | — | — | **불가능 (양쪽 차단)** |
| RDB Export/Import | 스냅샷 이후 쓰기 전부 | 큼 | 없음 | Export만 (1절) |
| `SCAN` 복사 + 쓰기 차단 | 약 111초 (실측: 3.77GB / 215만 키) | 0 | 없음 | ✅ (2.3절) |
| `SCAN` 복사 반복 (쓰기 유지) | 0 | 패스당 약 절반씩 수렴 (2패스 후 20.21%) | 없음 | ✅ (2.3절) |
| RIOT `--mode live` | 롤아웃 시간 | **보장 없음** — 대조 필수 | 없음 | ✗ |
| 애플리케이션 이중 쓰기 | 롤아웃 시간 | 0 (읽기-수정-쓰기 제외) | **큼** | ✗ |
| 읽기 폴백 + 지연 백필 | 롤아웃 시간 | 해당 없음 | 중간 | ✗ |
| 프록시 미러링 (Envoy) | 롤아웃 시간 | fire-and-forget이라 미검출 | 없음 (인프라 변경) | ✗ |
| 캐시 재수화 | 0 | 전량 (의도적) | 없음 | ✗ |

표를 세로로 훑으면 **다운타임과 유실이 동시에 0인 줄이 없다.**
한쪽을 0으로 만들면 다른 쪽이나 애플리케이션 변경 비용으로 지불하게 된다. 그래서 선택 기준이 필요하다.

### 4.7 선택 기준

```
Redis에 재계산 불가능한 데이터가 있는가?
├─ 아니오 → 4.5절 캐시 재수화. 가장 싸고 가장 빠르다. 백엔드 콜드 스타트만 확인하면 된다.
└─ 예
   └─ 수 분의 쓰기 차단 창을 잡을 수 있는가?
      ├─ 예 → 2.3절 SCAN 복사 + 쓰기 차단. 이 랩에서 무손실을 실증한 유일한 경로다.
      └─ 아니오
         └─ 애플리케이션을 고칠 수 있는가?
            ├─ 예 → 4.3절 이중 쓰기 또는 읽기 폴백. 유실 구간이 원천적으로 없다.
            └─ 아니오 → 4.2절 RIOT live 또는 4.4절 프록시 미러링.
                        둘 다 일관성을 보장하지 않으므로 컷오버 전 전수 대조가 필수다.
```

> 4.2·4.4를 고르더라도 **컷오버 다운타임이 0이 되는 건 아니다.** 연결 문자열을 바꾼 배포가 롤아웃되는 시간은 남는다.
> 다만 그 시간은 데이터 크기와 무관하므로 215만 키든 2천만 키든 동일하다. 복사 패스 시간이 데이터에 비례해 늘어나는 것과 다르다.

---

## 5. 용량 산정 — 두 번의 착시

### 5.1 소스 — SKU 표기 용량 ≠ 쓸 수 있는 용량

Premium P1은 6GB로 표기되지만 `maxmemory-reserved`(642MB)와
`maxfragmentationmemory-reserved`(642MB)를 빼면 실제 데이터는 4.4~4.75GB 선에서 한계에 부딪힌다.
이 랩에서도 4.50G에서 `OutOfMemoryError`가 났다.

```bash
az redis show -n <acr-name> -g <rg> --query "redisConfiguration.{maxmemory:maxmemory, reserved:maxmemoryReserved, fragReserved:maxfragmentationmemoryReserved}"
```

여기에 더해 ACR의 기본 축출 정책은 **`volatile-lru`** 다 (이 랩의 소스도 기본값 그대로였다).
메모리가 한계에 닿으면 **TTL이 걸린 키를 조용히 지우고 쓰기는 성공한 것처럼 계속 받는다.**
하필 마이그레이션 중에 압박이 커진다 — RDB Export의 fork가 메모리를 더 쓰고 서비스 쓰기는 계속 들어온다.

> 소스가 이미 `maxmemory` 근처에서 돌고 있다면 **마이그레이션을 시작하기 전에** 여유를 확보해야 한다.
> (SKU 상향, 불필요한 키 정리, 또는 `maxmemory-policy`를 `noeviction`으로 바꿔 조용한 유실 대신 오류로 드러내기)
> 이 랩은 축출량을 정량화하지 않았다. 메커니즘과 기본값만 확인한 항목이다.

### 5.2 타깃 — 메모리를 두 배로 쓰는 HA 복제본

`highAvailability: Enabled`인 AMR은 복제본을 함께 두고 **이 복제본이 사용량 지표에 그대로 포함된다.**

| 시점 | `usedmemory` 지표 | `usedmemorypercentage` |
|---|---|---|
| 단일 패스 복사 직후 | 8,364,071,328 B (7.79 GiB) | **81%** |
| 반복 패스 최종 상태 | 8,036,226,283 B (7.48 GiB) | **77%** |

소스 데이터는 **3.77 GiB**인데 지표는 **7.48 GiB**로 잡힌다. 정확히 **1.98배** — 복제본이 함께 세어진 값이다.

사용률의 분모도 표기 용량이 아니다. 위 두 관측치에서 역산하면 유효 용량은 **약 9.6~9.7 GiB**다.
Balanced_B5(6 GiB)에 HA 2사본이면 12 GiB이고 여기서 시스템 예약 약 20%를 빼면 `12 GiB × 0.8 = 9.60 GiB`.
관측값과 **0.2% 이내로 일치**한다.

이 20%는 추정이 아니라 문서에 명시된 값이다.

> On each Azure Managed Redis Instance, **approximately 20% of the available memory is reserved** as a buffer
> for noncache operations, such as replication during failover and active geo-replication buffer.
> — [Azure Managed Redis Architecture](https://learn.microsoft.com/azure/redis/architecture#reserved-memory)

정리하면 실무에서 쓸 규칙은 하나다.

> **AMR에 실제로 담을 수 있는 데이터는 SKU 표기 용량의 약 80%다.**
> 3.77 GiB ÷ (6 GiB × 0.8 = 4.8 GiB) = 78.5% → 실측 77~81%와 맞는다.

ACR의 데이터 크기를 같은 숫자의 AMR SKU에 1:1로 매핑하면 안 된다.
소스가 6GB SKU에서 4.5GB를 쓰고 있었다면 6GB짜리 AMR은 이미 한계(4.8 GiB)에 붙는다.

```bash
# 사이징 검증은 데이터베이스가 아니라 클러스터 리소스에서 한다.
# .../databases 네임스페이스에는 지표가 없다.
az monitor metrics list \
  --resource "$(az redisenterprise show -n <amr> -g <rg> --query id -o tsv)" \
  --metric usedmemory usedmemorypercentage --aggregation Maximum --interval PT5M
```

원시 관측치는 [`results/amr-memory-sizing.json`](../migration-lab/results/amr-memory-sizing.json)에 있다.
20% 예약은 문서상 모든 AMR 인스턴스에 적용된다. 다만 **역산으로 확인한 것은 Balanced_B5 하나**다.

---

## 6. 테스트 환경과 재현

### 6.1 테스트 환경

| 구성 | 값 |
|---|---|
| 리전 | Korea Central |
| 소스 | Azure Cache for Redis **Premium P1 (6GB)**, Redis 6.0.14, 포트 6380 |
| 소스 메모리 설정 | `maxmemory` 5.68G, `maxmemory-reserved` 642MB, `maxfragmentationmemory-reserved` 642MB |
| 타깃 | Azure Managed Redis **Balanced_B5**, Redis 7.4.3, 포트 10000, HA `Enabled` |
| 타깃 클러스터 정책 | `EnterpriseCluster` |
| 마이그레이션 실행 호스트 | 같은 리전의 Linux VM (Standard_D4s_v5) |
| 클라이언트 | Python `redis-py`, **비클러스터** `StrictRedis` (ACR에 붙일 때와 동일한 코드) |

데이터는 실제 캐시 워크로드에 가깝게 섞었다. 문자열 60%, 해시 15%, 리스트 10%, 정렬셋 10%,
그리고 필드 10만 개짜리 큰 해시 50개. 값은 압축 가능한 JSON 70% / 난수 바이트 30%로 섞어
RDB 압축률이 현실적으로 나오게 했다. 문자열 키의 30%에는 TTL을 걸었다.

**적재 결과**: 2,839,833 키 / `used_memory` 4.50G를 242.5초에 적재 (11,712 keys/s).
4.50G에서 `OutOfMemoryError`가 났다 — P1의 헤드라인 6GB에서 예약 영역 두 개(642MB × 2)를 빼면
실제로 쓸 수 있는 건 4.4~4.75GB 수준이다. SKU 표기 용량을 그대로 믿고 사이징하면 안 된다.

이후 측정은 프로브 키 정리 등을 거친 **2,155,260 키 / 3.77G** 상태를 기준으로 한다.

#### 6.1.1 명령 호환성 랩

[ACR과 AMR의 차이 2.4절](01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)과
[클라이언트·SDK 확인사항 6절](02-client-audit.md#6-tier-34--정책-의존-항목과-관리-명령)의
정책별 명령 호환성과 관리 명령 비교는 **위와 별개의 인스턴스**에서 측정했다.
`clusteringPolicy`는 생성 후 변경할 수 없어 정책마다 클러스터를 따로 만들어야 하고
데이터 크기가 결과에 영향을 주지 않는 측정이라 최소 SKU를 썼다.

| 인스턴스 | 구성 | 용도 |
|---|---|---|
| `amr-lab-ent` | AMR **Balanced_B0**, Redis 7.4.3, `EnterpriseCluster` | 정책 × 클라이언트 매트릭스 |
| `amr-lab-oss` | AMR **Balanced_B0**, Redis 7.4.3, `OSSCluster` | 정책 × 클라이언트 매트릭스 |
| `acr-lab-c0` | ACR **Basic C0**, Redis 6.0.14 | 관리 명령·키스페이스 알림의 ACR 쪽 대조군 |

- 리전 Korea Central, 클라이언트 redis-py 7.0.1, 로컬에서 실행 (**왕복 지연 약 180ms**)
- 명령 31개 × 클라이언트 2종 × 키 배치 2종, **각 3회 반복** — 기록된 모든 결과가 3회 일치
- 왕복 지연이 큰 환경이라 픽스처 준비는 파이프라인으로 묶었다. 순차 전송 시 38분이 걸린다.
- `acr-lab-c0`가 **Basic**이라는 점은 키스페이스 알림 해석에서 중요하다.
  `notify-keyspace-events`는 Standard/Premium 전용 설정이라 Basic에서는 관리 평면도 거부한다
  ([클라이언트·SDK 확인사항 4절](02-client-audit.md#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)).

### 6.2 재현하기

[`migration-lab/`](../migration-lab/)에 스크립트와 결과 JSON이 있다. 실행 방법은
[`migration-lab/README.md`](../migration-lab/README.md)에 있다.

| 파일 | 내용 |
|---|---|
| [`audit_commands.sh`](../migration-lab/audit_commands.sh) | 클라이언트·SDK 확인사항의 명령어 감사 정적 스캐너 (TIER 1 적중 시 종료 코드 1) |
| [`policy_matrix_test.py`](../migration-lab/policy_matrix_test.py) | ACR과 AMR의 차이 2.4절 정책 × 클라이언트 매트릭스 재현 스크립트 (`--repeat`로 반복 검증) |
| [`results/policy-matrix-ent.json`](../migration-lab/results/policy-matrix-ent.json) | `EnterpriseCluster` 원본 결과 (명령별 성공/실패와 예외 타입) |
| [`results/policy-matrix-oss.json`](../migration-lab/results/policy-matrix-oss.json) | `OSSCluster` 원본 결과 |
| [`results/clustering-policy.json`](../migration-lab/results/clustering-policy.json) | OSSCluster vs EnterpriseCluster 실측 |
| [`results/path-a-rdb.json`](../migration-lab/results/path-a-rdb.json) | Export 성공 / Import 실패와 근본 원인 |
| [`results/path-b-scan-copy.json`](../migration-lab/results/path-b-scan-copy.json) | 단일 패스 복사와 48.47% 유실 |
| [`results/path-b-repeat-pass.json`](../migration-lab/results/path-b-repeat-pass.json) | 반복 패스 수렴과 다운타임 하한 111초 (3.77GB / 215만 키) |
| [`results/path-c-tooling.json`](../migration-lab/results/path-c-tooling.json) | 마이그레이션 도구 제약 (문서 인용) |
| [`results/amr-memory-sizing.json`](../migration-lab/results/amr-memory-sizing.json) | AMR 사용량 지표 원시값과 유효 용량 역산 |

검증하다가 실제로 걸려 넘어진 함정은 스크립트에 반영해 두었다.

- **`EXISTS`로 유실을 세면 안 된다.** 키는 있는데 값이 옛것인 경우를 놓친다.
- **`DUMP` 페이로드를 바이트 비교하면 안 된다.** RDB 버전 푸터 때문에 Redis 6 → 7.4에서는
  값이 같아도 **표본 전체가 불일치로 나온다.** 타입별로 실제 값을 읽어 비교하도록 바꾸자
  불일치 0건이 됐다 ([`path-b-scan-copy.json`](../migration-lab/results/path-b-scan-copy.json):
  표본 2,496 중 일치 2,482 · 불일치 0 · 타깃에 없음 14).
- **표본을 `SCAN` 앞부분에서 뽑으면 안 된다.** 먼저 적재된 키에 표본이 쏠려 뒤쪽 유실을 놓친다. `RANDOMKEY`를 써야 한다.

---

## 7. 측정하지 않은 것

숫자를 추정으로 채우지 않았다. 다음은 미측정이다.

- **RDB Import 소요 시간** — 환경 정책으로 Import 자체가 막혀 측정 불가 ([1.2절](#12-import--이-환경에서의-실패))
- **이중 쓰기 방식의 실제 다운타임** — 설계 지침으로만 기술 ([마이그레이션 가이드 6.2절](../azure-cache-to-managed-redis-migration.md#62-쓰기를-멈출-수-없는-경우--애플리케이션-이중-쓰기))
- **4절의 실시간 전략 전부** — RIOT 라이브 복제, 프록시 미러링, 읽기 폴백, 캐시 재수화는
  **한 건도 실행하지 않았다.** 문서 근거와 설계만 정리한 것이다. 특히:
  - RIOT `--mode live`의 실제 유실률과 `riot compare` 결과
  - `notify-keyspace-events=KEA`를 켰을 때 소스 ACR의 CPU·서버 부하 증가폭
  - Envoy Redis 프록시 미러링의 실동작과 실패 시 관측 방법
- **`audit_commands.sh`의 실제 코드베이스 적중률** — 이 저장소의 샘플과 인위적 위반 파일로만 시험했다.
  실전 코드베이스의 오탐·미탐 비율은 모른다
- **`WAIT` 명령의 AMR 지원 여부** — 이중 쓰기 절차에서 타깃 쓰기 확정을 기다리려면 필요하지만 확인하지 않았다
- **Azure 마이그레이션 도구의 실동작** — 프라이빗 엔드포인트 환경이라 대상 밖 ([3절](#3-경로-c-데이터를-옮기지-않는-azure-마이그레이션-도구))
- **비용 비교** — SKU별 단가는 리전·계약·시점에 따라 달라진다. [Azure 가격 계산기](https://azure.microsoft.com/pricing/calculator/)로 직접 확인해야 한다.
- **Entra ID 인증 경로** — 이 랩은 액세스 키만 사용했다.
- **마이그레이션 중 소스 축출량** — `volatile-lru` 기본값과 `OutOfMemoryError` 발생은 확인했지만
  축출된 키 수를 재현 가능한 형태로 기록하지 못했다 ([5절](#5-용량-산정--두-번의-착시))
- **B5 외 SKU의 메모리 예약 비율** — 20% 예약은 Balanced_B5 한 SKU에서만 역산했다
- **`EnterpriseCluster`의 크로스 슬롯 제약** — 허용 목록 6개와 목록 밖 24개를 실측했다
  ([ACR과 AMR의 차이 2.5절](01-differences.md#25-enterprisecluster에-남는-크로스-슬롯-제약)). 다만 Redis 명령 전체를 훑은 것은 아니라
  **여기 없는 다중 키 명령은 여전히 직접 확인해야 한다.**
- **`OSSCluster`에서 `MOVED`가 커넥션 단위로 갈리는 원인** — 현상은 반복 측정으로 확인했지만
  ([ACR과 AMR의 차이 2.4절](01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)), 프록시·엔드포인트 내부 구조는 관측 범위 밖이다.
  Microsoft 문서에서 설명을 찾지 못했다
- **샤드가 여러 개인 `OSSCluster`** — 이 랩의 B0는 **샤드 1개**로 슬롯 0–16383을 전부 갖는다.
  샤드를 늘렸을 때 위 현상이 어떻게 달라지는지는 모른다
- **키스페이스 알림의 문서–실측 불일치가 언제까지 유지되는지** — AMR에서 기본값 `AKE`로
  동작하는 것을 확인했지만 ([클라이언트·SDK 확인사항 4절](02-client-audit.md#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)),
  **문서상 미지원이라 예고 없이 바뀔 수 있다.** 지속성은 보장할 수 없다
- **ACR Standard/Premium의 키스페이스 알림 활성화** — 대조군이 Basic C0라 관리 평면에서 거부됐다.
  Standard/Premium에서 `az redis update`로 켜지는 것까지는 확인하지 못했다
- **`NoCluster` 정책** — 25GB 이하 비샤딩 옵션으로, 이 랩에서는 생성·테스트하지 않았다

---
