# Azure Cache for Redis → Azure Managed Redis 마이그레이션 (GB 규모 실측)

> Korea Central에 실제 리소스를 만들어 **3.77GB / 215만 키** 규모로 측정한 결과입니다.
> 측정일 2026-08-27 KST (결과 JSON의 타임스탬프는 UTC라 2026-08-26으로 찍혀 있습니다).
> 스크립트와 원본 결과 JSON은 [`migration-lab/`](migration-lab/)에 있습니다.

---

## 1. 결론 먼저

"클라이언트 수정 없이, 다운타임 없이" 옮기고 싶다는 요구는 두 부분으로 나눠서 봐야 합니다.
**클라이언트 수정은 대체로 피할 수 있습니다. 다운타임 없이는 Azure가 해 주지 않습니다.**

| 요구 | 답 | 근거 |
|---|---|---|
| 클라이언트 코드 수정 없이 | **대체로 가능하다.** AMR 데이터베이스를 `EnterpriseCluster` 정책으로 **생성할 때** 정해야 한다. 단 다중 키 명령을 쓴다면 확인 필요 | [3절](#3-clusteringpolicy-클라이언트-수정-여부를-가르는-유일한-설정) |
| 다운타임 없이 | **Azure 기능만으로는 불가능하다.** 마이그레이션 도구는 데이터를 옮기지 않는다 | [6절](#6-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다) |
| 부득이한 다운타임 최소화 | 이 규모에서 **약 111초**가 복사 방식의 하한. 더 줄이려면 애플리케이션 이중 쓰기 | [5.3절](#53-반복-복사로-유실이-얼마나-줄어드나), [7절](#7-권장-절차) |

그리고 가장 자주 놓치는 것 하나. **데이터 복사가 도는 동안 소스에 들어온 쓰기는 절반 가까이 사라집니다.**
단일 복사 패스에서 실측 유실률은 **48.47%**였습니다. 키 개수만 비교하는 검증으로는 이게 잡히지 않습니다.

---

## 2. 테스트 환경

| 구성 | 값 |
|---|---|
| 리전 | Korea Central |
| 소스 | Azure Cache for Redis **Premium P1 (6GB)**, Redis 6.0.14, 포트 6380 |
| 소스 메모리 설정 | `maxmemory` 5.68G, `maxmemory-reserved` 642MB, `maxfragmentationmemory-reserved` 642MB |
| 타깃 | Azure Managed Redis **Balanced_B5**, Redis 7.4.3, 포트 10000, HA `Enabled` |
| 타깃 클러스터 정책 | `EnterpriseCluster` |
| 마이그레이션 실행 호스트 | 같은 리전의 Linux VM (Standard_D4s_v5) |
| 클라이언트 | Python `redis-py`, **비클러스터** `StrictRedis` (ACR에 붙일 때와 동일한 코드) |

데이터는 실제 캐시 워크로드에 가깝게 섞었습니다. 문자열 60%, 해시 15%, 리스트 10%, 정렬셋 10%,
그리고 필드 10만 개짜리 큰 해시 50개. 값은 압축 가능한 JSON 70% / 난수 바이트 30%로 섞어
RDB 압축률이 현실적으로 나오게 했습니다. 문자열 키의 30%에는 TTL을 걸었습니다.

**적재 결과**: 2,839,833 키 / `used_memory` 4.50G를 242.5초에 적재 (11,712 keys/s).
4.50G에서 `OutOfMemoryError`가 났습니다 — P1의 헤드라인 6GB에서 예약 영역 두 개(642MB × 2)를 빼면
실제로 쓸 수 있는 건 4.4~4.75GB 수준입니다. **SKU 표기 용량을 그대로 믿고 사이징하면 안 됩니다.**

이후 측정은 프로브 키 정리 등을 거친 **2,155,260 키 / 3.77G** 상태를 기준으로 합니다.

---

## 3. clusteringPolicy: 클라이언트 수정 여부를 가르는 유일한 설정

### 먼저 이름부터

`EnterpriseCluster`의 "Enterprise"는 **소스가 ACR이라서**도, **ACR의 Enterprise 계층**과도 관계가 없습니다.
AMR 자체가 Redis Enterprise 스택 위에서 동작하고, 그 소프트웨어가 제공하는 **프록시 기반 클러스터링**을 가리키는 이름입니다.

> The **Enterprise clustering policy** is a simpler configuration that uses a single endpoint for all client
> connections. (...) it routes all requests to a single Redis node that **acts as a proxy**. (...) The advantage
> of this approach is that it makes Azure Managed Redis **look nonclustered** to users.
> — [Azure Managed Redis Architecture](https://learn.microsoft.com/azure/redis/architecture#cluster-policies)

**AMR은 SKU와 무관하게 내부적으로 항상 클러스터링됩니다.** 정책은 "샤딩을 하느냐"가 아니라
**"클라이언트에게 클러스터를 어떻게 보여 주느냐"** 를 정합니다.

### 세 가지 정책

| 정책 | 클라이언트가 보는 것 | 비고 |
|---|---|---|
| `OSSCluster` | Redis Cluster API. 클라이언트가 샤드에 직접 연결 | **CLI 기본값.** 처리량이 가장 높음. 클러스터 지원 클라이언트 필수 |
| `EnterpriseCluster` | 단일 엔드포인트 (프록시가 라우팅) | 비클러스터 클라이언트 사용 가능. 프록시가 병목이 될 수 있음 |
| `NoCluster` | 단일 엔드포인트, 샤딩 없음 | **25GB 이하만.** 성능은 가장 낮음 |

```
$ az redisenterprise database create --help
--clustering-policy : Allowed values: EnterpriseCluster, NoCluster, OSSCluster.
```

Microsoft는 **비샤딩 ACR(Basic/Standard/Premium)에서 넘어오는 경우 성능을 위해 `OSSCluster`를 우선 검토**하고,
애플리케이션이 OSS도 Enterprise도 감당 못 할 때만 `NoCluster`를 쓰라고 권합니다.
`MULTI`처럼 크로스 슬롯 명령을 광범위하게 쓰는 워크로드가 `NoCluster`의 대표 사례로 문서에 나옵니다.

### 실측: 같은 비클러스터 클라이언트로 붙여 보기

`OSSCluster`와 `EnterpriseCluster`에 **동일한 비클러스터 코드**로 접속해 봤습니다.
(`NoCluster`는 이 랩에서 테스트하지 않았습니다.)

| 동작 | `OSSCluster` (기본값) | `EnterpriseCluster` |
|---|---|---|
| 키 500개 `SET` | 대부분 `redis.exceptions.MovedError`로 실패 | **500/500 성공, MOVED 0건** |
| 여러 키 `MGET` | `redis.exceptions.ClusterCrossSlotError` | 정상 |
| 여러 키 `DEL` | `redis.exceptions.ClusterCrossSlotError` | 정상 |
| `INFO`의 `cluster_enabled` | 1 | **0** |

### EnterpriseCluster도 크로스 슬롯 제약이 남습니다

위 표를 "무조건 무수정"으로 읽으면 안 됩니다. 문서가 명시하는 허용 목록은 6개뿐입니다.

> You might also see `CROSSSLOT` errors with Enterprise clustering policy. **Only the following multikey
> commands are allowed across slots**: `DEL`, `MSET`, `MGET`, `EXISTS`, `UNLINK`, `TOUCH`.

**위 실측에서 통과한 `MGET`과 `DEL`은 하필 이 허용 목록 안에 있는 명령입니다.**
즉 이 테스트는 "허용된 명령이 허용된다"를 확인했을 뿐, 목록 밖의 명령은 검증하지 못했습니다.
`SUNION`, `ZUNIONSTORE`, `RENAME`, `SMOVE`, 서로 다른 슬롯의 키를 묶는 `MULTI`나 Lua 스크립트 등은
**여전히 `CROSSSLOT`으로 실패할 수 있습니다.**

> **그러므로 실제로 확인해야 할 것**은 "AMR이 단일 엔드포인트로 보이는가"가 아니라
> **"우리 애플리케이션이 위 6개 밖의 다중 키 명령을 쓰는가"** 입니다.
> 순수 캐시(GET/SET/EXPIRE 위주)라면 문제가 없습니다.
> 다중 키 연산이 있다면 해당 키들을 해시 태그(`{user1}:profile`, `{user1}:session`)로 같은 슬롯에 모으거나,
> 25GB 이하에서는 `NoCluster`를 검토해야 합니다.

### 생성 후에는 바꿀 수 없습니다

```
$ az redisenterprise database update --clustering-policy EnterpriseCluster ...
BadRequest: 'properties.clusteringPolicy' cannot be changed
```

바꾸려면 데이터베이스를 삭제하고 다시 만들어야 합니다. 재생성한 데이터베이스는 **액세스 키 인증이 기본 비활성**이라
다시 켜고 키를 새로 받아야 합니다.

```bash
az redisenterprise database create \
  --cluster-name <amr-name> --resource-group <rg> \
  --clustering-policy EnterpriseCluster \
  --access-keys-auth Enabled
```

> 마이그레이션 계획에서 **가장 먼저** 확정해야 할 항목입니다. 데이터를 다 옮긴 뒤에 발견하면 처음부터 다시 해야 합니다.
> 반대로 애플리케이션이 이미 클러스터 클라이언트를 쓰거나 처리량이 중요하다면 `OSSCluster`가 맞습니다.

---

## 4. 경로 A: RDB Export / Import

```
ACR (Premium) --export--> Blob Storage --import--> AMR
```

### 4.1 Export는 잘 됩니다

| 항목 | 값 |
|---|---|
| 소요 시간 | **186.99초** |
| 결과 blob | 2,271,735,296 B (**2.12 GiB**) |
| 인메모리 대비 | 약 47% (압축됨) |
| 인증 | 시스템 할당 관리 ID |

Export는 관리 ID를 지원하므로, 스토리지 계정이 공용 네트워크 접근을 막고 있어도
신뢰할 수 있는 서비스 예외를 통해 동작합니다.

### 4.2 Import는 이 환경에서 실패했습니다

```
az redisenterprise database import --sas-uris "https://.../dump.rdb?<sas>"
→ OperationFailed (128.97초 후)
```

원인을 추적한 결과는 다음과 같습니다.

1. `az redisenterprise database import`는 **`--sas-uris`만 지원**합니다. 관리 ID 인증 옵션이 없습니다.
2. 테넌트에 걸린 Azure Policy(`MCAPSGovDeployPolicies`의 `StorageAccount_PublicNetwork_Modify`,
   `StorageAccount_DisableLocalAuth_Modify`)가 **modify 효과**로 스토리지 계정의
   `publicNetworkAccess=Disabled`와 `allowSharedKeyAccess=false`를 강제합니다.
   포털·CLI·raw ARM PATCH로 되돌려도 조용히 원복됐습니다.
3. SAS 트래픽은 관리 ID와 달리 **신뢰할 수 있는 서비스 우회 대상이 아닙니다.**
   인터넷에서 해당 blob의 공용 URL에 접근하면 `HTTP 403 AuthorizationFailure`가 돌아옵니다.

즉 이 실패는 제품 결함이 아니라 **환경 정책과 Import API 인증 방식의 조합** 문제입니다.

> **시사점**: 규제가 걸린 구독에서는 경로 A가 막힐 수 있습니다.
> 마이그레이션 계획을 세우기 전에 `az redisenterprise database import`를 작은 RDB로 **먼저 한 번 성공시켜 보세요.**
> 스토리지 계정에 공용 네트워크 접근을 허용할 수 있는지, 공유 키 인증이 켜지는지가 관건입니다.

이 문서는 Import 소요 시간을 측정하지 못했습니다. **모르는 값을 추정치로 쓰지 않았습니다.**

---

## 5. 경로 B: `SCAN` + `DUMP`/`RESTORE` 프로그래매틱 복사

Basic/Standard처럼 Export를 못 쓰거나, 경로 A가 정책으로 막힌 경우의 대안입니다.
[`migration-lab/migrate_scan_copy.py`](migration-lab/migrate_scan_copy.py)가 하는 일은 다음과 같습니다.

- `KEYS *` 대신 **`SCAN` 커서** — `KEYS`는 O(N) 블로킹 명령이라 수백만 키 인스턴스를 멈춥니다.
- 타입별 `HGETALL`/`LRANGE` 대신 **`DUMP` → `RESTORE ... REPLACE`** — 타입에 무관하고 클라이언트 메모리도 덜 씁니다.
- **`PTTL`을 함께 읽어 TTL을 보존** — 이걸 빠뜨리면 만료 예정 키가 영구 키가 됩니다.
- 읽기·쓰기 모두 파이프라인(500개 단위)으로 묶어 왕복 지연을 상쇄합니다.

Redis 6.0.14에서 만든 `DUMP` 페이로드를 Redis 7.4.3에 `RESTORE`하는 것은 정상 동작했습니다 (오류 0건).

### 5.1 복사 자체는 빠르고 정확합니다

| 항목 | 값 |
|---|---|
| 복사한 키 | 2,129,472 |
| 소요 시간 | **130.2초** (약 16,400 keys/s) |
| `RESTORE` 오류 | **0건** |
| TTL 옮긴 키 | 470,774 |
| TTL 보존 (표본 2,000) | **2,000 / 2,000 (유실 0%)** |
| 값 무결성 (무작위 표본 2,496) | 일치 2,482, **불일치 0**, 타깃에 없음 14 |

### 5.2 그런데 복사 중 들어온 쓰기의 48.47%가 사라집니다

복사가 도는 동안 소스에 초당 약 140건씩 프로브 키를 쓰고, 각 프로브의 키와 쓰기 시각을 로컬에 기록했습니다.
복사가 끝난 뒤 타깃에서 프로브를 **값까지** 대조했습니다.

| 항목 | 값 |
|---|---|
| 기록한 프로브 | 22,644 |
| 타깃에 정상 존재 | 11,668 |
| 타깃에 없음 | **10,976** |
| 타깃에 있으나 값이 옛것 | 0 |
| **유실률** | **48.47%** |
| 유실 구간 | 139.9초 (복사 시작 직후부터 끝까지) |

왜 하필 절반일까요. `SCAN`은 키스페이스를 커서로 한 번 훑습니다.
**커서가 이미 지나간 자리에 새로 쓰인 키는 이번 패스에서 복사되지 않습니다.**
복사 도중 무작위 시점에 쓰인 키가 "아직 안 지나간 구간"에 떨어질 확률은 평균 50%입니다. 실측 48.47%가 그 값입니다.

RDB Export도 같은 성질을 갖습니다. Export는 시작 시점의 스냅샷이므로 그 이후 쓰기는 담기지 않습니다.
**복사 방식은 무엇이든 이 문제를 갖습니다.**

> 소규모 테스트에서 이게 안 보이는 이유가 여기 있습니다. 키가 몇 개뿐이면 복사가 몇 초 만에 끝나서
> 유실 구간이 사실상 없습니다. GB 규모에서는 이 구간이 **2분**입니다.

### 5.3 반복 복사로 유실이 얼마나 줄어드나

같은 복사를 여러 번 돌리면 이전 패스가 놓친 키를 다음 패스가 회수합니다. 실제로 해 봤습니다.

| 패스 | 소스 쓰기 | 소요 시간 | 복사한 키 | 오류 | 그 시점의 누적 유실 |
|---|---|---|---|---|---|
| 1 | 진행 중 | 135.6초 | 2,130,079 | 0 | — |
| 2 | 진행 중 | 109.9초 | 2,146,668 | 0 | **20.21%** (7,311 / 36,175) |
| 3 | **차단** | 111.1초 | 2,155,260 | 0 | **0%** (0 / 37,456) |

2회 패스 후 남은 유실 7,311건은 **전부 2번째 패스가 도는 동안 쓰인 키**였습니다
(가장 이른 유실 시각이 2번째 패스 시작 시각과 일치). 1번째 패스가 놓친 것은 2번째 패스가 모두 회수했습니다.
패스마다 "그 패스가 도는 동안 들어온 쓰기"의 약 절반이 남는 구조입니다.

쓰기를 차단하고 최종 패스를 돌리자 결과는 깨끗했습니다.

```
소스: 2,155,260 키 (3.77G)
타깃: 2,155,260 키 (7.47G)
차이: 0

프로브 유실:      0 / 37,456  (0.00%)
TTL 보존:     2,000 / 2,000   (유실 0%)
값 무결성:    2,497 / 2,497   (불일치 0)
```

**여기서 중요한 것**: 반복 패스는 **유실을 줄이지만 다운타임은 줄이지 못합니다.**
이 스크립트는 델타만 옮기는 게 아니라 매번 **전수 재스캔**을 하기 때문에,
쓰기를 차단한 최종 패스도 여전히 전체 키를 훑습니다. 그래서 **111초**가 그대로 다운타임이 됩니다.

이 규모(215만 키 / 3.77GB, 같은 리전 VM에서 실행)에서 **복사 방식의 다운타임 하한은 약 111초**입니다.
클라이언트가 다른 리전에 있거나 파이프라인 크기가 작으면 더 늘어납니다.

---

## 6. 경로 C: Azure 마이그레이션 도구는 데이터를 옮기지 않는다

"복제 기반 무중단 마이그레이션"을 기대하고 확인했지만, 그런 기능은 없습니다.

Microsoft 공식 문서는 마이그레이션 경로를 두 가지로 제시합니다.
**Option 1은 자체 마이그레이션(권장)**, **Option 2가 마이그레이션 도구(preview)**입니다.
Option 2에 대한 문서의 제약 목록에는 다음이 그대로 적혀 있습니다.

> **Data sync not supported.** This tooling will orchestrate hostname/endpoint migration but **does not migrate any data**.

이 도구가 하는 일은 **미리 만들어 둔 AMR로 ACR의 호스트 이름을 넘기는 것**입니다.
클라이언트는 같은 호스트 이름과 액세스 키로 재연결되면서 AMR에 붙습니다. 데이터는 별도로 옮겨야 합니다.

리소스 공급자에 노출된 작업 이름도 이와 일치합니다.

```
$ az provider operation show --namespace Microsoft.Cache
Microsoft.Cache/redis/getMigrationInfo/action
Microsoft.Cache/redis/updateMigrationStatus/action
Microsoft.Cache/redis/updateDnsForMigration/action
Microsoft.Cache/redis/rollbackDnsForMigration/action
```

전부 DNS와 상태 조작입니다. 데이터 복제 관련 작업은 없습니다.

### 문서에 명시된 그 밖의 제약

| 제약 | 내용 |
|---|---|
| 전환 시점 통제 불가 | 마이그레이션을 시작할 수는 있지만 실제 트래픽 전환 시점은 고를 수 없다 |
| 전체 동시 전환 | 하나의 Redis에 붙은 **모든** 애플리케이션이 동시에 넘어간다. 서비스 단위 점진 전환 불가 |
| 롤백 창 제한 | 성공 후 검증·롤백 가능 시간이 짧다 |
| 두 호스트명 병존 기간 제한 | 기존 ACR 호스트명은 이후 자동 삭제된다 |
| 관리 작업 잠금 | 상태가 `Migrating`인 동안 다른 관리 작업이 차단된다 |
| **프라이빗 엔드포인트 미지원** | 프라이빗 엔드포인트를 쓰는 캐시는 대상이 아니다 |
| VNet 주입 캐시 미지원 | |
| 지역 복제 캐시 미지원 | |
| 설정 미복사 | 관리 ID, 방화벽 규칙, 지속성 설정, 업데이트 일정, 키스페이스 알림은 넘어가지 않는다 |

프라이빗 엔드포인트를 쓰는 프로덕션 환경이라면 애초에 대상이 아닙니다.

---

## 7. 권장 절차

### 7.1 쓰기 차단 창을 확보할 수 있다면 (가장 단순하고 검증됨)

이 랩에서 무손실을 실증한 절차입니다.

1. **AMR을 `EnterpriseCluster`로 생성**하고 액세스 키 인증을 켭니다. ([3절](#3-clusteringpolicy-클라이언트-수정-여부를-가르는-유일한-설정))
2. 서비스를 그대로 둔 채 **복사를 1~2회 돌립니다.** 대부분의 데이터가 미리 넘어갑니다.
3. **애플리케이션의 Redis 쓰기를 멈춥니다.** (배포 일시 중지, 쓰기 경로 차단, 또는 읽기 전용 모드)
4. **최종 복사 패스를 돌립니다.** ← 이 구간이 실제 다운타임. 이 랩 기준 **약 111초 / 215만 키**
5. 연결 문자열을 AMR로 바꾸고 애플리케이션을 재시작합니다. **포트가 6380 → 10000으로 바뀝니다.**
6. 검증합니다. 키 개수만 보지 말고 **TTL과 값까지** 확인하세요. ([`verify_migration.py`](migration-lab/verify_migration.py))
7. 문제가 없으면 ACR을 삭제합니다.

다운타임을 미리 계산하려면 **자기 데이터로 4단계만 먼저 재 보세요.** 키 개수에 거의 선형으로 비례합니다.

### 7.2 쓰기를 멈출 수 없다면: 애플리케이션 이중 쓰기

> **이 항목은 이 랩에서 검증하지 않았습니다.** 설계 지침으로만 읽어 주세요.

복사 방식으로는 다운타임을 111초 아래로 못 내립니다. 더 줄이려면 애플리케이션이 도와야 합니다.

1. 애플리케이션을 **ACR과 AMR 양쪽에 쓰도록** 배포합니다. 읽기는 아직 ACR에서만 합니다.
   AMR 쓰기 실패는 삼켜서 서비스에 영향이 없게 합니다.
2. 이중 쓰기가 도는 상태에서 **과거 데이터를 복사**합니다. 이 시점부터의 신규 쓰기는 이미 양쪽에 들어가므로,
   [5.2절](#52-그런데-복사-중-들어온-쓰기의-4847가-사라집니다)의 유실 구간이 사라집니다.
3. 복사 후 검증합니다.
4. **읽기를 AMR로 전환**합니다. 다운타임은 배포 롤아웃 시간뿐입니다.
5. 안정화되면 ACR 쓰기를 제거하고 ACR을 삭제합니다.

주의할 점:

- `INCR`, `LPUSH`, `SETNX` 같은 **읽기-수정-쓰기 성격의 명령은 이중 쓰기로 정합성이 깨질 수 있습니다.**
  카운터나 큐로 Redis를 쓰고 있다면 해당 키만 따로 처리해야 합니다. 순수 캐시 용도라면 문제되지 않습니다.
- TTL도 양쪽에 동일하게 걸어야 합니다.
- 2단계의 복사는 `RESTORE ... REPLACE`를 쓰므로, 이중 쓰기로 이미 들어간 **최신 값을 과거 값으로 덮어쓸 수 있습니다.**
  복사를 먼저 끝내고 이중 쓰기를 켜거나, `RESTORE`에서 `REPLACE`를 빼는 쪽을 검토하세요.

### 7.3 Azure 마이그레이션 도구를 쓸 경우

호스트 이름을 유지하고 싶고 [6절](#6-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다)의 제약을 모두 받아들일 수 있을 때만 고려하세요.
이 경우에도 **데이터는 7.1 또는 7.2로 별도 이관해야 합니다.**

---

## 8. 용량 산정 — 두 번 속습니다

### 소스: SKU 표기 용량 ≠ 쓸 수 있는 용량

Premium P1은 6GB로 표기되지만, `maxmemory-reserved`(642MB)와
`maxfragmentationmemory-reserved`(642MB)를 빼면 실제 데이터는 4.4~4.75GB 선에서 한계에 부딪힙니다.
이 랩에서도 4.50G에서 `OutOfMemoryError`가 났습니다.

```bash
az redis show -n <acr-name> -g <rg> --query "redisConfiguration.{maxmemory:maxmemory, reserved:maxmemoryReserved, fragReserved:maxfragmentationmemoryReserved}"
```

여기에 더해, ACR의 기본 축출 정책은 **`volatile-lru`** 입니다 (이 랩의 소스도 기본값 그대로였습니다).
메모리가 한계에 닿으면 **TTL이 걸린 키를 조용히 지우고 쓰기는 성공한 것처럼 계속 받습니다.**
하필 마이그레이션 중에 압박이 커집니다 — RDB Export의 fork가 메모리를 더 쓰고, 서비스 쓰기는 계속 들어옵니다.

> 소스가 이미 `maxmemory` 근처에서 돌고 있다면, **마이그레이션을 시작하기 전에** 여유를 확보하세요.
> (SKU 상향, 불필요한 키 정리, 또는 `maxmemory-policy`를 `noeviction`으로 바꿔 조용한 유실 대신 오류로 드러내기)
> 이 랩은 축출량을 정량화하지 않았습니다. 메커니즘과 기본값만 확인한 항목입니다.

### 타깃: HA 복제본이 메모리를 두 배로 씁니다

`highAvailability: Enabled`인 AMR은 복제본을 함께 두고, **이 복제본이 사용량 지표에 그대로 포함됩니다.**

| 시점 | `usedmemory` 지표 | `usedmemorypercentage` |
|---|---|---|
| 단일 패스 복사 직후 | 8,364,071,328 B (7.79 GiB) | **81%** |
| 반복 패스 최종 상태 | 8,036,226,283 B (7.48 GiB) | **77%** |

소스 데이터는 **3.77 GiB**인데 지표는 **7.48 GiB**로 잡힙니다. 정확히 **1.98배** — 복제본이 함께 세어진 값입니다.

사용률의 분모도 표기 용량이 아닙니다. 위 두 관측치에서 역산하면 유효 용량은 **약 9.6~9.7 GiB**입니다.
Balanced_B5(6 GiB)에 HA 2사본이면 12 GiB이고, 여기서 시스템 예약 약 20%를 빼면 `12 GiB × 0.8 = 9.60 GiB`.
관측값과 **0.2% 이내로 일치**합니다.

이 20%는 추정이 아니라 문서에 명시된 값입니다.

> On each Azure Managed Redis Instance, **approximately 20% of the available memory is reserved** as a buffer
> for noncache operations, such as replication during failover and active geo-replication buffer.
> — [Azure Managed Redis Architecture](https://learn.microsoft.com/azure/redis/architecture#reserved-memory)

정리하면 실무에서 쓸 규칙은 하나입니다.

> **AMR에 실제로 담을 수 있는 데이터는 SKU 표기 용량의 약 80%입니다.**
> 3.77 GiB ÷ (6 GiB × 0.8 = 4.8 GiB) = 78.5% → 실측 77~81%와 맞습니다.

**ACR의 데이터 크기를 같은 숫자의 AMR SKU에 1:1로 매핑하면 안 됩니다.**
소스가 6GB SKU에서 4.5GB를 쓰고 있었다면, 6GB짜리 AMR은 이미 한계(4.8 GiB)에 붙습니다.

```bash
# 사이징 검증은 데이터베이스가 아니라 클러스터 리소스에서 합니다.
# .../databases 네임스페이스에는 지표가 없습니다.
az monitor metrics list \
  --resource "$(az redisenterprise show -n <amr> -g <rg> --query id -o tsv)" \
  --metric usedmemory usedmemorypercentage --aggregation Maximum --interval PT5M
```

원시 관측치는 [`results/amr-memory-sizing.json`](migration-lab/results/amr-memory-sizing.json)에 있습니다.
20% 예약은 문서상 모든 AMR 인스턴스에 적용되지만, **역산으로 확인한 것은 Balanced_B5 하나**입니다.

---

## 9. 재현하기

[`migration-lab/`](migration-lab/)에 스크립트와 결과 JSON이 있습니다. 실행 방법은
[`migration-lab/README.md`](migration-lab/README.md)를 보세요.

| 파일 | 내용 |
|---|---|
| [`results/clustering-policy.json`](migration-lab/results/clustering-policy.json) | OSSCluster vs EnterpriseCluster 실측 |
| [`results/path-a-rdb.json`](migration-lab/results/path-a-rdb.json) | Export 성공 / Import 실패와 근본 원인 |
| [`results/path-b-scan-copy.json`](migration-lab/results/path-b-scan-copy.json) | 단일 패스 복사와 48.47% 유실 |
| [`results/path-b-repeat-pass.json`](migration-lab/results/path-b-repeat-pass.json) | 반복 패스 수렴과 111초 다운타임 하한 |
| [`results/path-c-tooling.json`](migration-lab/results/path-c-tooling.json) | 마이그레이션 도구 제약 (문서 인용) |
| [`results/amr-memory-sizing.json`](migration-lab/results/amr-memory-sizing.json) | AMR 사용량 지표 원시값과 유효 용량 역산 |

검증할 때 실제로 걸려 넘어졌던 함정 세 가지를 스크립트에 반영해 두었습니다.

- **`EXISTS`로 유실을 세면 안 됩니다.** 키는 있는데 값이 옛것인 경우를 놓칩니다.
- **`DUMP` 페이로드를 바이트 비교하면 안 됩니다.** RDB 버전 푸터 때문에 Redis 6 → 7.4에서는
  값이 같아도 **표본 전체가 불일치로 나옵니다.** 타입별로 실제 값을 읽어 비교하도록 바꾸자
  불일치 0건이 됐습니다 ([`path-b-scan-copy.json`](migration-lab/results/path-b-scan-copy.json):
  표본 2,496 중 일치 2,482 · 불일치 0 · 타깃에 없음 14).
- **표본을 `SCAN` 앞부분에서 뽑으면 안 됩니다.** 먼저 적재된 키에 표본이 쏠려 뒤쪽 유실을 놓칩니다. `RANDOMKEY`를 쓰세요.

---

## 10. 이 문서가 측정하지 않은 것

숫자를 추정으로 채우지 않았습니다. 다음은 미측정입니다.

- **RDB Import 소요 시간** — 환경 정책으로 Import 자체가 막혀 측정 불가 ([4.2절](#42-import는-이-환경에서-실패했습니다))
- **이중 쓰기 방식의 실제 다운타임** — 설계 지침으로만 기술 ([7.2절](#72-쓰기를-멈출-수-없다면-애플리케이션-이중-쓰기))
- **Azure 마이그레이션 도구의 실동작** — 프라이빗 엔드포인트 환경이라 대상 밖 ([6절](#6-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다))
- **비용 비교** — SKU별 단가는 리전·계약·시점에 따라 달라집니다. [Azure 가격 계산기](https://azure.microsoft.com/pricing/calculator/)로 직접 확인하세요.
- **Entra ID 인증 경로** — 이 랩은 액세스 키만 사용했습니다.
- **마이그레이션 중 소스 축출량** — `volatile-lru` 기본값과 `OutOfMemoryError` 발생은 확인했지만,
  축출된 키 수를 재현 가능한 형태로 기록하지 못했습니다 ([8절](#8-용량-산정--두-번-속습니다))
- **B5 외 SKU의 메모리 예약 비율** — 20% 예약은 Balanced_B5 한 SKU에서만 역산했습니다
- **`EnterpriseCluster`의 크로스 슬롯 제약 범위** — 실측한 `MGET`/`DEL`은 문서상 **허용 목록에 있는 명령**입니다.
  허용 목록 밖(`SUNION`, `RENAME`, 크로스 슬롯 `MULTI`/Lua 등)은 시험하지 않았습니다 ([3절](#enterprisecluster도-크로스-슬롯-제약이-남습니다))
- **`NoCluster` 정책** — 25GB 이하 비샤딩 옵션으로, 이 랩에서는 생성·테스트하지 않았습니다

---

## 11. 참고 자료

- [Migration options — Basic/Standard/Premium → Azure Managed Redis](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options)
- [Self-service migration](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service)
- [Azure Managed Redis 클러스터링 정책](https://learn.microsoft.com/azure/redis/architecture#clustering-policy)
- [Azure Cache for Redis 메모리 정책](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#memory-policies)
- [Redis migration agent skill (GitHub)](https://github.com/AzureManagedRedis/amr-migration-skill)
- [`SCAN`](https://redis.io/docs/latest/commands/scan/) · [`DUMP`](https://redis.io/docs/latest/commands/dump/) · [`RESTORE`](https://redis.io/docs/latest/commands/restore/)
