# 01. ACR과 AMR의 차이 — 기능·정책·명령어

> 이 문서는 [ACR → AMR 마이그레이션 가이드](../azure-cache-to-managed-redis-migration.md)의 상세 문서입니다.
> **절 번호는 문서마다 1부터 매깁니다.** 다른 문서를 가리킬 때는 문서 이름을 함께 씁니다.
> 측정값은 Korea Central에서 3.77GB / 215만 키 규모로 잰 것입니다 ([테스트 환경](03-migration-paths.md#61-테스트-환경)).

관련 문서: [클라이언트·SDK 확인사항](02-client-audit.md) · [이관 경로와 실측](03-migration-paths.md)

---

## 1. 기능 차이 — 엔진, 샤딩, 명령어, 클라이언트

ACR(Basic/Standard/Premium)과 AMR은 **서로 다른 소프트웨어** 위에 올라가 있습니다.
같은 Redis API를 쓰지만 클러스터 구조, 쓸 수 있는 명령, 붙일 수 있는 클라이언트가 갈립니다.
"실측"이 붙은 항목은 이 랩에서 직접 측정한 값이고, 나머지는 문서 근거입니다.
**어떻게 옮길 것인가는 [마이그레이션 가이드 4절](../azure-cache-to-managed-redis-migration.md#5-우선순위와-순서)부터입니다.**

#### 엔진과 클러스터 구조

| 항목 | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 기반 소프트웨어 | OSS Redis | **Redis Enterprise 스택** | `EnterpriseCluster`의 "Enterprise"는 이 스택을 가리키는 이름 ([2.1절](#21-제품-계보--이름부터-정리하기)) |
| Redis 버전 | 4.0.x / 6.0.x (이 랩은 6.0.14) | 7.4.x (이 랩은 7.4.3) | `DUMP`/`RESTORE` 페이로드 호환은 실측에서 오류 0건 |
| 샤딩·클러스터링 | Premium에서 **켜고 끄는 옵션** (Basic/Standard는 불가) | **SKU 무관 항상 켜져 있음** | 클러스터를 안 쓰던 워크로드도 크로스 슬롯 제약을 받게 됨 ([2.2절](#22-샤딩과-클러스터--amr은-항상-클러스터입니다)) |
| 클러스터를 보여 주는 방식 | 해당 없음 (단일 엔드포인트) | `clusteringPolicy`로 결정 — `OSSCluster` / `EnterpriseCluster` / `NoCluster` | 클라이언트에 보이는 모습 자체가 정책마다 다름 ([2.3절](#23-clusteringpolicy-세-가지)) |
| 그 정책의 변경 | 해당 없음 | `NoCluster`에서 나오는 방향만 가능. `OSSCluster`·`EnterpriseCluster`가 되면 **DB를 지우지 않고는 변경 불가** | 처음에 둘 중 하나를 고르면 되돌리려면 재생성 + 데이터 재이관 ([2.6절](#26-정책-변경은-nocluster에서-나오는-방향만-됩니다)) |
| 데이터베이스 개수 | SKU별 16~64개 | **0번 하나** | `SELECT`/`MOVE`/`SWAPDB`와 커넥션 문자열의 DB 번호를 전부 걷어내야 함 |
| 명령 처리 | OSS Redis 설계상 **단일 스레드** | Redis Enterprise가 인스턴스당 **다중 vCPU 활용** | 메모리 크기가 같아도 처리량 특성이 다름 |

#### Redis Enterprise 스택이 새로 주는 것

ACR Basic/Standard/Premium에는 아예 없던 기능들입니다. 마이그레이션에 필수는 아니지만,
**모듈은 생성 시점에만 켤 수 있어서** 나중에 필요해지면 다시 만들어야 합니다.

| 기능 | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis | 무엇을 확인할 것 |
|---|---|---|---|
| 모듈 — RediSearch / RedisJSON / RedisBloom / RedisTimeSeries | **없음** (ACR은 Enterprise 계층에서만) | 있음 | **생성할 때만 추가할 수 있습니다.** 수동 로드도, 버전 갱신도 불가 |
| RediSearch의 전제 조건 | — | `EnterpriseCluster` 정책 + `NoEviction` 축출 정책 **필수** | 벡터 검색을 쓸 계획이면 정책이 사실상 하나로 정해짐 |
| 지역 복제 | Premium만, **수동(passive)** | **액티브(active)** — Balanced B0·B1과 Flash Optimized는 제외 | 액티브 구성에서는 `FLUSHALL`/`FLUSHDB`가 차단됨 ([클라이언트·SDK 확인사항 6절](02-client-audit.md#6-tier-34--정책-의존-항목과-관리-명령)) |
| 액티브 지역 복제와 모듈 병행 | — | `RediSearch`와 `RedisJSON`만 가능 | Bloom·TimeSeries는 액티브 구성과 함께 못 씀 |
| 디스크 계층 | 없음 | Flash Optimized가 콜드 데이터를 NVMe로 내림 | 이 계층에서는 RedisJSON만 되고 검색·Bloom·TimeSeries는 안 됨 |
| 데이터 지속성 | Premium만 (RDB/AOF) | 전 계층 | Flash Optimized의 디스크 사용과는 별개 기능 |
| SLA | Basic 없음 / Standard·Premium 있음 | 전 계층 있음 | HA를 끄면 데이터 유실·다운타임을 감수 (dev/test 전용) |

#### 명령어

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 다중 키 명령 | 비클러스터면 제약 없음 | `EnterpriseCluster`에서도 `DEL`·`MSET`·`MGET`·`EXISTS`·`UNLINK`·`TOUCH` **6개만** 허용 | 실측: 허용 목록 밖 24개가 전부 `CROSSSLOT`으로 실패 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) |
| 그 허용 목록이 더 줄어드는 경우 | — | **액티브 지역 복제(Active-Active)를 켜면 `MGET`·`EXISTS`·`TOUCH` 3개로** 축소 | 쓰기 계열 `DEL`·`MSET`·`UNLINK`까지 같은 슬롯 전용이 됨 |
| 같은 슬롯으로 모으면 | — | 정책 2 × 클라이언트 2, **네 조합 모두 통과** (실측 31/31) | 해시 태그가 사실상 유일한 일반 해법. 단 **키 이름이 바뀜** |
| `SELECT` (1번 이상) | 허용 (실측) | 차단 — `DB index is out of range` (실측) | 다중 DB 전제가 깨짐 |
| `SWAPDB` | 허용 (실측) | 차단 — `unknown command` (실측) | 다중 DB 기반 운영 절차(블루/그린 스왑 등)를 대체해야 함 |
| `CONFIG GET`/`SET` | 차단 — `unknown command` (실측) | **수락됨** (실측). 단 `SET`은 무효과, 미지원 파라미터는 거부 | 성공 응답을 믿고 설정이 바뀌었다고 가정하면 안 됨 ([클라이언트·SDK 확인사항 6절](02-client-audit.md#6-tier-34--정책-의존-항목과-관리-명령)) |
| 키스페이스 알림 | Basic 불가 (실측: 기본값에서 0건 수신), Standard/Premium은 관리 평면에서 활성화 | 문서는 "미지원", 실측은 기본값 `AKE`로 **동작** | 문서와 실측이 어긋나는 항목. 지원 대상이 아니므로 의존하면 안 됨 ([클라이언트·SDK 확인사항 4절](02-client-audit.md#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)) |
| `ROLE` | 허용 (실측) | 허용 (실측) | 비클러스터 클라이언트 기준. 클러스터 클라이언트에서는 실패 |
| `FAILOVER` | `unknown command` (실측) — Redis 6.2에 추가된 명령이라 **ACR의 6.0.x에는 없음** | `unknown command` (실측). 문서도 "명시적 Failover 명령을 지원하지 않는다"고 명시 | 어느 쪽에서도 명령으로 페일오버를 유도할 수 없음. AMR에는 재부팅도 없고 대신 Flush 관리 작업만 있음 |
| `REPLICAOF` / `PSYNC` / `REPLCONF` | 차단 | 차단 | 물리적 복제를 붙이는 구성 자체가 불가. `REPLICAOF`는 양쪽 실측, 나머지는 문서 근거 ([이관 경로와 실측 4.1절](03-migration-paths.md#41-가장-먼저-떠오르는-방법-그리고-왜-막히는가)) |

#### 클라이언트와 연결

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 포트 | 6380 (TLS) / 6379 (비TLS) | **TLS든 비TLS든 10000** | 연결 문자열, 방화벽, NSG |
| TLS | **두 모드가 동시에 열려 있음** — 같은 인스턴스에 TLS로도 비TLS로도 붙을 수 있음 | **생성 시 한 모드만 선택** (`--client-protocol Encrypted\|Plaintext`, 기본 TLS). 고른 뒤에는 모든 클라이언트가 같은 모드여야 함 | "AMR은 TLS 필수"가 아니라 **혼용이 안 되는 것**. 비TLS로 붙던 배치 잡 하나 때문에 전체를 비TLS로 만들면 안 됨 |
| 샤드(노드) 개별 포트 | 13XXX | **85XX** (실측 8501) | 클러스터 클라이언트가 리다이렉트를 따라갈 때 열려 있어야 하는 포트 |
| 호스트명 | `<name>.redis.cache.windows.net` | `<name>.<region>.redis.azure.net` | DNS, 허용 목록 |
| 필요한 클라이언트 | 비클러스터 클라이언트로 충분 | `OSSCluster`면 **클러스터 지원 클라이언트 필수**, `EnterpriseCluster`·`NoCluster`면 기존 그대로 | 정책 선택이 곧 클라이언트 교체 여부 ([마이그레이션 가이드 1.2절](../azure-cache-to-managed-redis-migration.md#2-무엇을-고를-것인가--clusteringpolicy)) |
| `OSSCluster`에 비클러스터 클라이언트로 붙으면 | — | 연결도 되고 `GET`/`SET`도 되지만, **커넥션 단위로 갈려** 풀의 일부만 계속 실패 (실측) | 스모크 테스트로는 잡히지 않는 실패 방식 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) |
| 클러스터 클라이언트의 TLS | — | 클라이언트가 샤드 IP로 재접속해 **호스트명 검증에서 걸림** (실측) | 인증서가 `<region>.redis.azure.net` 이름으로 발급돼 있기 때문 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) |

#### 네트워크와 운영 — AMR로 가면 없어지는 것

이 랩에서 측정한 항목은 아니고 전부 [Understand the differences](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-understand) 근거입니다.
**명령이나 클라이언트보다 먼저 걸리는 항목들**이라 1절에 둡니다. 특히 VNet 주입은 마이그레이션 도구에서 아예 오류로 막힙니다.

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇을 해야 하나 |
|---|---|---|---|
| VNet 주입 | Premium에서 지원 | **미지원** | Private Link로 전환. 네트워크 설계를 다시 그려야 하는 항목 |
| IP 기반 방화벽 규칙 | 지원 | **미지원** | 접근 제어를 Private Link + 관리 ID 쪽으로 옮겨야 함 |
| Microsoft Entra ID | 인증 지원 + **RBAC 지원** | 인증은 지원, **RBAC은 미지원** | 액세스 정책으로 권한을 나눠 뒀다면 대안이 필요 |
| 수동 재부팅 | 노드 수동 재부팅 지원 | **없음** (노드 운영은 자동) | 재부팅으로 캐시를 비우던 절차는 **Flush 관리 작업**으로 대체 |
| 예약 업데이트 창 | 지원 | **미리 보기** | 업데이트 시간을 통제하던 운영 절차를 재검토 |
| 영역 중복 | Premium부터 | HA를 켜고 리전이 AZ를 지원하면 **기본값** | 별도 설정 없이 얻는 항목 |
| RDB 가져오기/내보내기 | **Premium만** | **전 SKU** | 원본이 Basic/Standard면 [경로 A](03-migration-paths.md#1-경로-a-rdb-export--import) 사용 불가 |

#### 용량과 지표

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 유효 메모리 | 표기 용량 − 예약 2종 (실측: P1 6GB → 약 4.4~4.75GB) | 표기 용량 × 약 0.8 | ACR 데이터 크기를 같은 숫자의 AMR SKU에 1:1 매핑하면 한계에 근접 ([이관 경로와 실측 5절](03-migration-paths.md#5-용량-산정--두-번-속습니다)) |
| HA 복제본 | Premium 복제본은 지표가 별도 | `usedmemory`에 **함께 집계** (실측 1.98배) | 사용률을 그대로 읽으면 두 배로 오독 |

**"실측" 값은 이 랩의 환경(3.77GB / 215만 키, Korea Central 같은 리전 VM)에서 나온 것입니다.**
명령 호환성은 데이터 크기를 타지 않지만, 메모리 비율은 SKU마다 다시 확인해야 합니다
([이관 경로와 실측 7절](03-migration-paths.md#7-이-문서가-측정하지-않은-것)).

---

## 2. 왜 다른가 — 제품 계보와 클러스터 정책

### 2.1 제품 계보 — 이름부터 정리하기

두 서비스는 **서로 다른 소프트웨어** 위에 올라가 있습니다.

| | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis |
|---|---|---|
| 기반 | **OSS Redis** | **Redis Enterprise** 스택 |
| 이 랩의 버전 | 6.0.14 | 7.4.3 |
| 샤딩 | Premium에서 **선택적으로** 켜는 기능 | **항상 켜져 있음** |
| 엔드포인트 | 단일 | 정책에 따라 단일 또는 클러스터 |

`EnterpriseCluster`의 "Enterprise"는 **소스가 ACR이라서**도, **ACR의 Enterprise 계층**과도 관계가 없습니다.
AMR이 Redis Enterprise 스택 위에서 동작하고, 그 소프트웨어가 제공하는 **프록시 기반 클러스터링**을 가리키는 이름입니다.

> The **Enterprise clustering policy** is a simpler configuration that uses a single endpoint for all client
> connections. (...) it routes all requests to a single Redis node that **acts as a proxy**. (...) The advantage
> of this approach is that it makes Azure Managed Redis **look nonclustered** to users.
> — [Azure Managed Redis Architecture](https://learn.microsoft.com/azure/redis/architecture#cluster-policies)

### 2.2 샤딩과 클러스터 — AMR은 항상 클러스터입니다

ACR에서는 클러스터링이 **Premium에서 켜고 끄는 옵션**이었습니다. 대부분의 ACR 사용자는 꺼 놓고 씁니다.
그래서 "우리는 클러스터를 안 쓰니 상관없다"고 넘어가기 쉬운데, **AMR에서는 그 선택지가 없습니다.**

> **AMR은 SKU와 무관하게 내부적으로 항상 클러스터링됩니다.**
> `clusteringPolicy`는 "샤딩을 하느냐"가 아니라 **"클라이언트에게 클러스터를 어떻게 보여 주느냐"** 를 정합니다.

여기서 두 가지가 따라옵니다.

1. **키가 슬롯으로 흩어집니다.** 여러 키를 한 명령으로 묶는 연산은 그 키들이 같은 슬롯에 있어야 합니다.
2. **`NoCluster`를 고르더라도** 25GB 이하라는 제약과 가장 낮은 성능을 받아들여야 합니다.

같은 슬롯에 모으려면 **해시 태그**를 씁니다. 키 이름의 `{}` 안이 같으면 같은 슬롯에 들어갑니다.

```
{user1}:profile   ─┐
{user1}:session    ├─ 같은 슬롯 → 함께 묶을 수 있음
{user1}:cart      ─┘
user2:profile      ─ 다른 슬롯
```

**해시 태그는 키 이름을 바꿉니다.** 그래서 데이터 이관보다 **애플리케이션 배포가 먼저**여야 합니다.
이관을 끝낸 뒤에 태그를 붙이면 이미 옮긴 키를 전부 다시 써야 합니다.

### 2.3 clusteringPolicy 세 가지

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

### 2.4 실측: 정책 × 클라이언트 조합별 명령 호환성

정책을 고르는 근거를 문서에만 두지 않으려고, `EnterpriseCluster`와 `OSSCluster` 데이터베이스를
**따로 만들어 같은 명령 집합을 양쪽에 돌렸습니다.** (`clusteringPolicy`는 생성 후 못 바꾸므로 클러스터가 두 개 필요합니다.)

- 명령 31개 — 단일 키 쓰기, 문서상 허용 목록 6개, 목록 밖 24개
- 클라이언트 2종 — 비클러스터(`redis.StrictRedis`) / 클러스터(`redis.cluster.RedisCluster`), redis-py 7.0.1
- 키 배치 2종 — 서로 다른 슬롯에 흩어진 키 / 해시 태그로 한 슬롯에 모은 키
- **각 케이스 3회 반복.** 결과가 갈리면 `불안정`으로 기록 — 아래 표의 값은 **전부 3회 일치**했습니다.

재현 스크립트와 원본 결과는 [이관 경로와 실측 6.2절](03-migration-paths.md#62-재현하기)에 있습니다. `NoCluster`는 테스트하지 않았습니다.

**먼저 붙는지부터:**

| | 비클러스터 클라이언트 | 클러스터 클라이언트 |
|---|---|---|
| **`EnterpriseCluster`** | 연결됨 · `cluster_enabled=0` · 7.4.3 | **연결 불가** — `Cluster mode is not enabled on this node` |
| **`OSSCluster`** | 연결됨 · `cluster_enabled=1` · 7.4.3 | 연결됨 · 노드 `20.249.34.150:8501` 1개 |

`EnterpriseCluster`가 **비클러스터 클라이언트에게 `cluster_enabled=0`으로 보인다**는 점이 핵심입니다.
프록시가 클러스터를 감춰 주기 때문인데, 그래서 **클러스터 클라이언트로는 오히려 붙지 못합니다.**
이미 클러스터 클라이언트를 쓰고 있다면 `EnterpriseCluster`는 선택지에서 빠집니다.

**서로 다른 슬롯의 키를 다루는 명령 (31개 중 성공 수):**

| 명령 그룹 | `EnterpriseCluster` × 비클러스터 | `OSSCluster` × 비클러스터 | `OSSCluster` × 클러스터 |
|---|---|---|---|
| 단일 키 `SET` ×50 | 성공 | 성공 | 성공 |
| 허용 목록 `MGET` `MSET` | **성공** | 실패 | 실패 |
| 허용 목록 `DEL` `EXISTS` `UNLINK` `TOUCH` (다중 키) | **성공** | 실패 | 성공 |
| 목록 밖 24개 | 전부 실패 | 전부 실패 | 전부 실패 |
| **합계** | **7 / 31** | **1 / 31** | **5 / 31** |

문서가 말한 허용 목록 6개(`DEL` `MSET` `MGET` `EXISTS` `UNLINK` `TOUCH`)와
`EnterpriseCluster`의 통과 항목이 **정확히 일치**했습니다. 문서대로입니다.

`OSSCluster` × 클러스터 클라이언트에서 4개가 통과한 건 서버가 허용해서가 아니라
**redis-py가 키별로 쪼개서 각 노드에 나눠 보내기 때문**입니다. 클라이언트 구현에 기댄 동작이라
다른 언어의 SDK에서는 같은 코드가 실패할 수 있습니다. 실제로 같은 클라이언트에서도
`MGET`/`MSET`은 쪼개 주지 않아 실패했습니다.

**해시 태그로 같은 슬롯에 모으면 네 조합 모두 31 / 31 성공했습니다.**
정책을 무엇으로 고르든, 클라이언트가 무엇이든, **키를 같은 슬롯에 모으는 것만이 보편적인 해법**입니다.

#### `OSSCluster`에 비클러스터 클라이언트로 붙으면 절반만 동작합니다

가장 주의할 조합입니다. 연결도 되고 `SET`/`GET`도 되니 **얼핏 잘 되는 것처럼 보입니다.**
그런데 허용 목록의 다중 키 명령이 **같은 슬롯 키인데도** `MOVED`로 실패합니다.

새 연결을 20번 맺어 같은 명령을 한 번씩 실행한 결과입니다.

| 명령 | 성공 | `MovedError` |
|---|---|---|
| `GET` (단일 키) | 20 | 0 |
| `SET` (단일 키) | 20 | 0 |
| `DEL` | 7 | **13** |
| `UNLINK` | 11 | **9** |
| `EXISTS` | 12 | **8** |
| `TOUCH` | 11 | **9** |

거의 동전 던지기입니다. 그리고 **연결을 하나 잡아 20번 반복하면 결과가 한쪽으로 고정**됩니다
(어떤 연결은 `DEL` 20/20 실패, 다른 연결은 `TOUCH` 20/20 성공).
즉 **성공 여부가 연결을 맺는 순간 정해지고 그 연결이 사는 동안 유지됩니다.**

커넥션 풀을 쓰는 애플리케이션에서 이게 어떻게 나타나는지가 중요합니다.
**풀의 일부 커넥션은 계속 실패하고 나머지는 계속 성공합니다.** 그래서
재시도해도 같은 커넥션이면 또 실패하고, 실패가 특정 키와도 무관해 보입니다.
스모크 테스트가 통과했는데 운영에서 간헐적으로 깨지는 전형적인 모양입니다.

이 클러스터는 **샤드가 하나뿐이고 슬롯 0–16383을 전부 그 샤드가 갖고 있습니다.**
리다이렉트할 다른 노드가 없는데도 `MOVED`가 돌아옵니다. 샤드를 늘리면 나아지는 문제가 아닙니다.

> **결론:** `OSSCluster`를 고른다면 **클라이언트도 클러스터 모드로 바꿔야 합니다.**
> 비클러스터 클라이언트를 그대로 두는 건 선택지가 아닙니다.

#### 클러스터 클라이언트는 TLS 인증서에서 한 번 더 걸립니다

`OSSCluster`에 클러스터 클라이언트로 붙을 때, redis-py는 `CLUSTER SLOTS`로 받은
**샤드의 IP 주소로 다시 접속합니다.** 그런데 인증서는 `*.koreacentral.redis.azure.net` 이름으로 발급돼 있어
IP로는 검증에 실패합니다.

```
SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
  certificate verify failed: IP address mismatch,
  certificate is not valid for '20.249.34.150'
```

이 랩에서는 **체인 검증은 유지한 채 호스트명 대조만 끄고**(`ssl_check_hostname=False`) 측정했습니다.
운영에서 이 옵션을 쓸지는 별도로 판단하세요 — 클라이언트마다 대응 방법이 다르고,
이 문제 자체가 `OSSCluster` 전환 비용의 일부입니다.

### 2.5 EnterpriseCluster도 크로스 슬롯 제약이 남습니다

위 표를 "무조건 무수정"으로 읽으면 안 됩니다. 문서가 명시하는 허용 목록은 6개뿐입니다.

> You might also see `CROSSSLOT` errors with Enterprise clustering policy. **Only the following multikey
> commands are allowed across slots**: `DEL`, `MSET`, `MGET`, `EXISTS`, `UNLINK`, `TOUCH`.

[2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)에서 이 목록을 그대로 확인했습니다.
`EnterpriseCluster`가 크로스 슬롯으로 통과시킨 다중 키 명령은 **정확히 이 6개**였고,
목록 밖으로 시험한 **24개는 전부 `CROSSSLOT`으로 실패**했습니다 (각 3회, 결과 일치).

| | 명령 |
|---|---|
| 통과 (6) | `MGET` `MSET` `DEL` `EXISTS` `UNLINK` `TOUCH` |
| 실패 (24) | `SUNION` `SINTER` `SDIFF` `SUNIONSTORE` `SMOVE` `ZUNIONSTORE` `ZINTERSTORE` `ZDIFF` `RENAME` `COPY` `RPOPLPUSH` `LMOVE` `BLPOP` `LMPOP` `BITOP` `PFMERGE` `PFCOUNT` `MSETNX` `SORT ... STORE` `GEOSEARCHSTORE` `LCS` `XREAD` `MULTI`/`EXEC` `EVAL`(다중 `KEYS`) |

집합 연산, 정렬 집합 연산, 키 이동·복사, 리스트 간 이동, 스트림 다중 구독,
그리고 **서로 다른 슬롯의 키를 묶는 `MULTI`와 Lua 스크립트가 모두 여기 걸립니다.**
`EnterpriseCluster`는 크로스 슬롯 제약을 없애 주는 것이 아니라 **6개만 예외로 두는 것**입니다.

> **그러므로 실제로 확인해야 할 것**은 "AMR이 단일 엔드포인트로 보이는가"가 아니라
> **"우리 애플리케이션이 위 6개 밖의 다중 키 명령을 쓰는가"** 입니다. 그 확인 방법이 [클라이언트·SDK 확인사항 3절](02-client-audit.md)입니다.

### 2.6 정책 변경은 `NoCluster`에서 나오는 방향만 됩니다

`OSSCluster`로 만든 DB의 정책을 바꾸려 했더니 거부됐습니다.

```
$ az redisenterprise database update --clustering-policy EnterpriseCluster ...
BadRequest: 'properties.clusteringPolicy' cannot be changed
```

다만 **모든 방향이 막힌 것은 아닙니다.** CLI 정의가 규칙을 그대로 적어 두고 있습니다.

```
$ az redisenterprise database update --help
--clustering-policy : Clustering policy - default is OSSCluster.
    This property can be updated only if the current value is NoCluster.
    If the value is OSSCluster or EnterpriseCluster, it cannot be updated
    without deleting the database.
```

| 현재 정책 | 바꿀 수 있나 |
|---|---|
| `NoCluster` | **가능** — `OSSCluster`/`EnterpriseCluster`로 변경. 단 액티브 지역 복제가 켜져 있으면 이것도 막힘 |
| `OSSCluster` | 불가 — DB 삭제 후 재생성 (위 실측) |
| `EnterpriseCluster` | 불가 — DB 삭제 후 재생성 |

`NoCluster`는 25GB 이하에서만 쓸 수 있고 **성능이 가장 낮으며, 이 상태로는 스케일 업이 막힙니다.**
크기를 키우려면 먼저 정책을 바꿔야 합니다. 그래서 `NoCluster`는 "일단 안전하게 시작하고 나중에 정한다"는
선택지가 되기는 하지만, **정한 다음에는 그 방향으로 한 번만 갈 수 있는 일방통행**입니다.

`OSSCluster`/`EnterpriseCluster`에서 바꾸려면 데이터베이스를 삭제하고 다시 만들어야 합니다.
재생성한 데이터베이스는 **액세스 키 인증이 기본 비활성**이라 다시 켜고 키를 새로 받아야 합니다.

```bash
az redisenterprise database create \
  --cluster-name <amr-name> --resource-group <rg> \
  --clustering-policy EnterpriseCluster \
  --access-keys-auth Enabled
```

> 데이터를 다 옮긴 뒤에 잘못 고른 걸 발견하면 **처음부터 다시 해야 합니다.**
> 그래서 [클라이언트·SDK 확인사항](02-client-audit.md)의 명령어 감사가 AMR 생성보다 시간상 앞에 옵니다.
> 반대로 애플리케이션이 이미 클러스터 클라이언트를 쓰거나 처리량이 중요하다면 `OSSCluster`가 맞습니다.

---
