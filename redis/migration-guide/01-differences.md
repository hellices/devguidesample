# 01. ACR과 AMR의 차이 — 기능·정책·명령어

> 이 문서는 [ACR → AMR 마이그레이션 가이드](../azure-cache-to-managed-redis-migration.md)의 상세 문서다.
> **절 번호는 문서마다 1부터 매긴다.** 다른 문서를 가리킬 때는 문서 이름을 함께 쓴다.
> 측정값은 Korea Central에서 3.77GB / 215만 키 규모로 잰 것이다 ([테스트 환경](03-migration-paths.md#61-테스트-환경)).

관련 문서: [클라이언트·SDK 확인사항](02-client-audit.md) · [이관 경로와 실측](03-migration-paths.md)

---

## 1. 기능 차이 — 엔진, 샤딩, 명령어, 클라이언트

차이를 항목별로 외울 필요는 없다. 대부분 **하나의 사실에서 갈라져 나오기** 때문이다 —
ACR(Basic/Standard/Premium)은 OSS Redis 위에 있다. AMR은 Redis Enterprise 스택 위에 있다.
같은 Redis API를 말하지만 다른 소프트웨어다.

그 하나가 어디까지 번지는지 따라가 보면 이렇게 이어진다.

```
다른 소프트웨어 → AMR은 SKU와 무관하게 항상 클러스터 → 키가 슬롯으로 흩어짐
                                                  ├→ 다중 키 명령이 제한된다
                                                  └→ 클라이언트가 클러스터를 알아야 한다
```

사슬의 처음과 중간과 끝이 각각 다른 것을 말한다.

- **출발점은 제품 계보 하나다.** 두 서비스가 다른 소프트웨어 위에 서 있다는 사실 말고는 아무것도 가정하지 않는다.
- **중간 고리는 선택으로 끊을 수 없다.** AMR에서 클러스터는 전제이므로 이 화살표만은 우회할 방법이 없다.
- **끝의 두 갈래가 실제 비용이다.** 코드를 고치는 쪽과 클라이언트를 갈아 끼우는 쪽이다.

아래 여섯 묶음은 이 사슬을 한 칸씩 짚는다. "실측"이 붙은 항목은 이 랩에서 직접 측정한 값이고
나머지는 문서 근거다. 어떻게 옮길 것인가는 [마이그레이션 가이드 5절](../azure-cache-to-managed-redis-migration.md#5-우선순위와-순서)부터다.

### 1.1 사슬의 출발점 — 엔진과 클러스터 구조

표는 일곱 줄이지만 마이그레이션 계획을 실제로 바꾸는 것은 **샤딩**과 **정책 변경**뿐이다.
ACR에서 클러스터링은 Premium에서 켜고 끄는 옵션이었다. 대부분은 꺼 놓고 쓴다.
AMR에는 그 스위치가 아예 없다. 그리고 `clusteringPolicy`는 클러스터를 클라이언트에게
어떻게 보여 줄지 정하는데 한 번 정하면 되돌리는 방법이 사실상 재생성뿐이다.

| 항목 | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 기반 소프트웨어 | OSS Redis | **Redis Enterprise 스택** | `EnterpriseCluster`의 "Enterprise"는 이 스택을 가리키는 이름 ([2.1절](#21-제품-계보--이름부터-정리하기)) |
| Redis 버전 | 4.0.x / 6.0.x (이 랩은 6.0.14) | 7.4.x (이 랩은 7.4.3) | `DUMP`/`RESTORE` 페이로드 호환은 실측에서 오류 0건 |
| 샤딩·클러스터링 | Premium에서 **켜고 끄는 옵션** (Basic/Standard는 불가) | **SKU 무관 항상 켜져 있음** | 클러스터를 안 쓰던 워크로드도 크로스 슬롯 제약을 받게 됨 ([2.2절](#22-샤딩과-클러스터--항상-켜져-있는-클러스터)) |
| 클러스터를 보여 주는 방식 | 해당 없음 (단일 엔드포인트) | `clusteringPolicy`로 결정 — `OSSCluster` / `EnterpriseCluster` / `NoCluster` | 클라이언트에 보이는 모습 자체가 정책마다 다름 ([2.3절](#23-clusteringpolicy-세-가지)) |
| 그 정책의 변경 | 해당 없음 | `NoCluster`에서 나오는 방향만 가능. `OSSCluster`·`EnterpriseCluster`가 되면 **DB를 지우지 않고는 변경 불가** | 처음에 둘 중 하나를 고르면 되돌리려면 재생성 + 데이터 재이관 ([2.6절](#26-정책-변경의-방향--nocluster에서-나오는-길-하나)) |
| 데이터베이스 개수 | SKU별 16~64개 | **0번 하나** | `SELECT`/`MOVE`/`SWAPDB`와 커넥션 문자열의 DB 번호를 전부 걷어내야 함 |
| 명령 처리 | OSS Redis 설계상 **단일 스레드** | Redis Enterprise가 인스턴스당 **다중 vCPU 활용** | 메모리 크기가 같아도 처리량 특성이 다름 |

데이터베이스가 0번 하나뿐이라는 줄도 사슬과 무관해 보이지만 같은 뿌리다.
Redis Cluster 규격 자체가 DB를 하나만 두기 때문이다.

### 1.2 사슬 밖에서 얻는 것 — Redis Enterprise 스택의 추가 기능

이 묶음은 "없던 것이 생기는" 쪽이다.
ACR Basic/Standard/Premium에는 아예 없던 기능이다. 마이그레이션에 필수는 아니다.
그런데도 이 자리에 적는 이유는 하나다 — **모듈은 생성 시점에만 켤 수 있다.**
쓸 계획이 조금이라도 있으면 지금 정해야 한다. 나중에 필요해지면 그때는 다시 만드는 수밖에 없다.

| 기능 | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis | 무엇을 확인할 것 |
|---|---|---|---|
| 모듈 — RediSearch / RedisJSON / RedisBloom / RedisTimeSeries | **없음** (ACR은 Enterprise 계층에서만) | 있음 | **생성할 때만 추가 가능.** 수동 로드도, 버전 갱신도 불가 |
| RediSearch의 전제 조건 | — | `EnterpriseCluster` 정책 + `NoEviction` 축출 정책 **필수** | 벡터 검색을 쓸 계획이면 정책이 사실상 하나로 정해짐 |
| 지역 복제 | Premium만, **수동(passive)** | **액티브(active)** — Balanced B0·B1과 Flash Optimized는 제외 | 액티브 구성에서는 `FLUSHALL`/`FLUSHDB`가 차단됨 ([클라이언트·SDK 확인사항 6절](02-client-audit.md#6-tier-34--정책-의존-항목과-관리-명령)) |
| 액티브 지역 복제와 모듈 병행 | — | `RediSearch`와 `RedisJSON`만 가능 | Bloom·TimeSeries는 액티브 구성과 함께 못 씀 |
| 디스크 계층 | 없음 | Flash Optimized가 콜드 데이터를 NVMe로 내림 | 이 계층에서는 RedisJSON만 되고 검색·Bloom·TimeSeries는 안 됨 |
| 데이터 지속성 | Premium만 (RDB/AOF) | 전 계층 | Flash Optimized의 디스크 사용과는 별개 기능 |
| SLA | Basic 없음 / Standard·Premium 있음 | 전 계층 있음 | HA를 끄면 데이터 유실·다운타임을 감수 (dev/test 전용) |

RediSearch 줄은 특히 조심할 자리다. 벡터 검색을 쓸 생각이 있으면 `clusteringPolicy`가
`EnterpriseCluster`로 못 박히므로 정책 선택이 아래 명령어·클라이언트 논의를 거치기 전에 이미 끝나 버린다.

### 1.3 사슬이 코드에 닿는 곳 — 명령어

클러스터가 항상 켜져 있다는 말은 실무에서 이렇게 나타난다.
**여러 키를 한 명령으로 묶는 순간, 그 키들이 같은 슬롯에 있어야 한다.**
그렇지 않으면 서버가 `CROSSSLOT`으로 거부한다. ACR에서 비클러스터로 쓰던 코드에는
이 조건을 지킬 이유가 없었다. 그러니 대개 지켜져 있지 않다.

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

정작 발목을 더 자주 잡는 쪽은 크로스 슬롯과 무관해 보이는 아래쪽 절반이다.
`SELECT`와 `SWAPDB`는 **ACR에서는 되던 것이 AMR에서 안 되는** 몇 안 되는 항목이고
`REPLICAOF` 줄은 "복제로 무중단 전환한다"는 계획을 통째로 지운다.

### 1.4 그보다 먼저 걸리는 것 — 클라이언트와 연결

명령이 거부되는 건 그래도 코드를 고치면 되는 문제다.
그 앞에 **연결 자체가 성립하지 않는 조합**이 있다. 더 곤란한 것은
**연결도 되고 얼핏 동작까지 하는데 일부만 실패하는 조합**이다.

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 포트 | 6380 (TLS) / 6379 (비TLS) | **TLS든 비TLS든 10000** | 연결 문자열, 방화벽, NSG |
| TLS | **두 모드가 동시에 열려 있음** — 같은 인스턴스에 TLS로도 비TLS로도 붙을 수 있음 | **생성 시 한 모드만 선택** (`--client-protocol Encrypted\|Plaintext`, 기본 TLS). 고른 뒤에는 모든 클라이언트가 같은 모드여야 함 | "AMR은 TLS 필수"가 아니라 **혼용이 안 되는 것**. 비TLS로 붙던 배치 잡 하나 때문에 전체를 비TLS로 만들면 안 됨 |
| 샤드(노드) 개별 포트 | 13XXX | **85XX** (실측 8501) | 클러스터 클라이언트가 리다이렉트를 따라갈 때 열려 있어야 하는 포트 |
| 호스트명 | `<name>.redis.cache.windows.net` | `<name>.<region>.redis.azure.net` | DNS, 허용 목록 |
| 필요한 클라이언트 | 비클러스터 클라이언트로 충분 | `OSSCluster`면 **클러스터 지원 클라이언트 필수**, `EnterpriseCluster`·`NoCluster`면 기존 그대로 | 정책 선택이 곧 클라이언트 교체 여부 ([마이그레이션 가이드 2절](../azure-cache-to-managed-redis-migration.md#2-무엇을-고를-것인가--clusteringpolicy)) |
| `OSSCluster`에 비클러스터 클라이언트로 붙으면 | — | 연결도 되고 `GET`/`SET`도 되지만, **커넥션 단위로 갈려** 풀의 일부만 계속 실패 (실측) | 스모크 테스트로는 잡히지 않는 실패 방식 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) |
| 클러스터 클라이언트의 TLS | — | 클라이언트가 샤드 IP로 재접속해 **호스트명 검증에서 걸림** (실측) | 인증서가 `<region>.redis.azure.net` 이름으로 발급돼 있기 때문 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) |

마지막 두 줄이 이 문서에서 가장 오래 붙잡고 있었던 항목이다.
왜 그런 모양으로 실패하는지는 [2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)에서 측정치와 함께 풀어 두었다.

### 1.5 Redis 바깥에서 먼저 걸리는 것 — 네트워크와 운영

이 묶음은 **Redis에 닿기 전에 걸리는 항목**이라 코드 감사보다 앞에 놓아야 한다.
특히 VNet 주입은 마이그레이션 도구에서 경고가 아니라 오류로 진행이 막힌다.
여기 있는 항목은 이 랩에서 측정한 것이 아니고 전부
[Understand the differences](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-understand) 근거다.

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇을 해야 하나 |
|---|---|---|---|
| VNet 주입 | Premium에서 지원 | **미지원** | Private Link로 전환. 네트워크 설계를 다시 그려야 하는 항목 |
| IP 기반 방화벽 규칙 | 지원 | **미지원** | 접근 제어를 Private Link + 관리 ID 쪽으로 옮겨야 함 |
| Microsoft Entra ID | 인증 지원 + **RBAC 지원** | 인증은 지원, **RBAC은 미지원** | 액세스 정책으로 권한을 나눠 뒀다면 대안이 필요 |
| 수동 재부팅 | 노드 수동 재부팅 지원 | **없음** (노드 운영은 자동) | 재부팅으로 캐시를 비우던 절차는 **Flush 관리 작업**으로 대체 |
| 예약 업데이트 창 | 지원 | **미리 보기** | 업데이트 시간을 통제하던 운영 절차를 재검토 |
| 영역 중복 | Premium부터 | HA를 켜고 리전이 AZ를 지원하면 **기본값** | 별도 설정 없이 얻는 항목 |
| RDB 가져오기/내보내기 | **Premium만** | **전 SKU** | 원본이 Basic/Standard면 [경로 A](03-migration-paths.md#1-경로-a-rdb-export--import) 사용 불가 |

다른 항목이 대부분 "AMR에서 없어지는 것"인데 RDB 내보내기는 **AMR 쪽이 넓다.**
다만 이관에서 필요한 것은 소스인 ACR의 내보내기라
Basic/Standard에서 출발한다면 이 확장은 도움이 되지 않는다.

### 1.6 마지막 칸 — 용량과 지표

사이징은 두 번 속는다. 소스에서 한 번, 타깃에서 한 번이다.
ACR은 표기 용량에서 예약 영역 두 개를 빼야 실제 쓸 수 있는 양이 나온다.
AMR에서는 **지표에 찍히는 숫자가 실제보다 크다** — HA 복제본이 함께 세어지기 때문이다.

| 항목 | Azure Cache for Redis | Azure Managed Redis | 무엇이 달라지나 |
|---|---|---|---|
| 유효 메모리 | 표기 용량 − 예약 2종 (실측: P1 6GB → 약 4.4~4.75GB) | 표기 용량 × 약 0.8 | ACR 데이터 크기를 같은 숫자의 AMR SKU에 1:1 매핑하면 한계에 근접 ([이관 경로와 실측 5절](03-migration-paths.md#5-용량-산정--두-번의-착시)) |
| HA 복제본 | Premium 복제본은 지표가 별도 | `usedmemory`에 **함께 집계** (실측 1.98배) | 사용률을 그대로 읽으면 두 배로 오독 |

두 오차가 같은 방향으로 겹치면 "6GB에서 4.5GB 쓰고 있으니 6GB짜리로 가면 되겠다"는 계산이 그대로 한계에 부딪힌다.
어떻게 어긋나는지는 [이관 경로와 실측 5절](03-migration-paths.md#5-용량-산정--두-번의-착시)에서 관측치로 확인했다.

**"실측" 값은 이 랩의 환경(3.77GB / 215만 키, Korea Central 같은 리전 VM)에서 나온 것이다.**
명령 호환성은 데이터 크기를 타지 않으므로 그대로 가져다 써도 된다. 다만 메모리 비율은 SKU마다 다시 확인해야 한다
([이관 경로와 실측 7절](03-migration-paths.md#7-측정하지-않은-것)).

---

## 2. 왜 다른가 — 제품 계보와 클러스터 정책

1절의 "무엇이 다른가"에 이어 여기서는 "왜 그렇게 됐는가"를 본다.
특히 정책 이름 하나가 오해를 자주 산다. 그 오해를 먼저 풀어 두면 나머지 선택이 한결 쉬워진다.

### 2.1 제품 계보 — 이름부터 정리하기

`EnterpriseCluster`라는 이름을 처음 보면 대개 둘 중 하나로 읽는다.
**"소스가 ACR Enterprise 계층일 때 고르는 것"** 아니면
**"Enterprise급 기능을 켜는 옵션"** 이다. 둘 다 아니다.
이 이름은 소스가 무엇인지와도, ACR의 계층 이름과도 아무 관계가 없다.

이름의 출처는 AMR이 딛고 선 소프트웨어다.

| | Azure Cache for Redis (Basic/Standard/Premium) | Azure Managed Redis |
|---|---|---|
| 기반 | **OSS Redis** | **Redis Enterprise** 스택 |
| 이 랩의 버전 | 6.0.14 | 7.4.3 |
| 샤딩 | Premium에서 **선택적으로** 켜는 기능 | **항상 켜져 있음** |
| 엔드포인트 | 단일 | 정책에 따라 단일 또는 클러스터 |

그러니까 `EnterpriseCluster`는 **Redis Enterprise 스택이 제공하는 프록시 기반 클러스터링**을 가리킨다.
프록시가 앞에 서서 요청을 대신 라우팅한다. 그 덕분에 클라이언트에게는 클러스터가 아닌 것처럼 보인다.

> The **Enterprise clustering policy** is a simpler configuration that uses a single endpoint for all client
> connections. (...) it routes all requests to a single Redis node that **acts as a proxy**. (...) The advantage
> of this approach is that it makes Azure Managed Redis **look nonclustered** to users.
> — [Azure Managed Redis Architecture](https://learn.microsoft.com/azure/redis/architecture#cluster-policies)

### 2.2 샤딩과 클러스터 — 항상 켜져 있는 클러스터

ACR에서는 클러스터링이 **Premium에서 켜고 끄는 옵션**이었다. 대부분의 ACR 사용자는 꺼 놓고 쓴다.
그래서 "우리는 클러스터를 안 쓰니 상관없다"고 넘어가기 쉬운데, **AMR에서는 그 선택지가 없다.**

> **AMR은 SKU와 무관하게 내부적으로 항상 클러스터링된다.**
> `clusteringPolicy`는 "샤딩을 하느냐"가 아니라 **"클라이언트에게 클러스터를 어떻게 보여 주느냐"** 를 정한다.

이 전제는 곧바로 두 곳에 닿는다.

- **키가 슬롯으로 흩어진다.** 여러 키를 한 명령으로 묶는 연산은 그 키들이 같은 슬롯에 있어야 한다.
- **`NoCluster`를 고르더라도 대가가 있다.** 25GB 이하라는 제약과 가장 낮은 성능을 받아들여야 한다.

같은 슬롯에 모으려면 **해시 태그**를 쓴다. 키 이름의 `{}` 안이 같으면 같은 슬롯에 들어간다.

```
{user1}:profile   ─┐
{user1}:session    ├─ 같은 슬롯 → 함께 묶을 수 있음
{user1}:cart      ─┘
user2:profile      ─ 다른 슬롯
```

**해시 태그는 키 이름을 바꾼다.** 그래서 데이터 이관보다 **애플리케이션 배포가 먼저**여야 한다.
이관을 끝낸 뒤에 태그를 붙이면 이미 옮긴 키를 전부 다시 써야 한다.

### 2.3 clusteringPolicy 세 가지

샤딩을 켤지 말지는 앞 절에서 봤듯 정할 수 없다.
남는 선택은 **그 클러스터를 클라이언트에게 어떻게 보여 줄 것인가**뿐이다.
셋의 실질적인 차이는 결국 두 축으로 수렴한다 — **클라이언트를 바꿔야 하는가**, 그리고 **얼마나 빠른가**.

| 정책 | 클라이언트가 보는 것 | 비고 |
|---|---|---|
| `OSSCluster` | Redis Cluster API. 클라이언트가 샤드에 직접 연결 | **CLI 기본값.** 처리량이 가장 높음. 클러스터 지원 클라이언트 필수 |
| `EnterpriseCluster` | 단일 엔드포인트 (프록시가 라우팅) | 비클러스터 클라이언트 사용 가능. 프록시가 병목이 될 수 있음 |
| `NoCluster` | 단일 엔드포인트, 샤딩 없음 | **25GB 이하만.** 성능은 가장 낮음 |

두 축이 서로 반대 방향이라 고르기가 어렵다.
빠른 쪽을 고르면 클라이언트를 갈아야 한다. 코드를 안 건드리는 쪽을 고르면 프록시를 하나 더 통과해야 한다.

```
$ az redisenterprise database create --help
--clustering-policy : Allowed values: EnterpriseCluster, NoCluster, OSSCluster.
```

Microsoft는 **비샤딩 ACR(Basic/Standard/Premium)에서 넘어오는 경우 성능을 위해 `OSSCluster`를 우선 검토**하고
애플리케이션이 OSS도 Enterprise도 감당 못 할 때만 `NoCluster`를 쓰라고 권한다.
문서가 드는 `NoCluster`의 대표 사례는 `MULTI` 같은 크로스 슬롯 명령을 광범위하게 쓰는 워크로드다.

권고는 분명히 `OSSCluster` 쪽을 가리킨다. 다만 그 권고를 받아들이려면
"우리 클라이언트가 클러스터 모드로 갈 수 있는가"에 먼저 답해야 한다. 다음 절에서 그 답을 재 봤다.

### 2.4 실측: 정책 × 클라이언트 조합별 명령 호환성

정책을 고르는 근거를 문서에만 두지 않으려고 `EnterpriseCluster`와 `OSSCluster` 데이터베이스를
**따로 만들어 같은 명령 집합을 양쪽에 돌렸다.** (`clusteringPolicy`는 생성 후 못 바꾸므로 클러스터가 두 개 필요하다.)

- 명령 31개 — 단일 키 쓰기, 문서상 허용 목록 6개, 목록 밖 24개
- 클라이언트 2종 — 비클러스터(`redis.StrictRedis`) / 클러스터(`redis.cluster.RedisCluster`), redis-py 7.0.1
- 키 배치 2종 — 서로 다른 슬롯에 흩어진 키 / 해시 태그로 한 슬롯에 모은 키
- **각 케이스 3회 반복.** 결과가 갈리면 `불안정`으로 기록했고 아래 표의 값은 **전부 3회 일치**했다.

재현 스크립트와 원본 결과는 [이관 경로와 실측 6.2절](03-migration-paths.md#62-재현하기)에 있다. `NoCluster`는 테스트하지 않았다.

**먼저 붙는지부터:**

| | 비클러스터 클라이언트 | 클러스터 클라이언트 |
|---|---|---|
| **`EnterpriseCluster`** | 연결됨 · `cluster_enabled=0` · 7.4.3 | **연결 불가** — `Cluster mode is not enabled on this node` |
| **`OSSCluster`** | 연결됨 · `cluster_enabled=1` · 7.4.3 | 연결됨 · `CLUSTER SLOTS` 응답 노드 1개 |

`EnterpriseCluster`는 **비클러스터 클라이언트에게 `cluster_enabled=0`으로 보인다.** 프록시가
클러스터를 감춰 주기 때문이다. 그래서 **클러스터 클라이언트로는 오히려 붙지 못한다.**
이미 클러스터 클라이언트를 쓰고 있다면 `EnterpriseCluster`는 선택지에서 빠진다.

**서로 다른 슬롯의 키를 다루는 명령 (31개 중 성공 수):**

| 명령 그룹 | `EnterpriseCluster` × 비클러스터 | `OSSCluster` × 비클러스터 | `OSSCluster` × 클러스터 |
|---|---|---|---|
| 단일 키 `SET` ×50 | 성공 | 성공 (샤드 1개 기준 — 아래 참고) | 성공 |
| 허용 목록 `MGET` `MSET` | **성공** | 실패 | 실패 |
| 허용 목록 `DEL` `EXISTS` `UNLINK` `TOUCH` (다중 키) | **성공** | 실패 | 성공 |
| 목록 밖 24개 | 전부 실패 | 전부 실패 | 전부 실패 |
| **합계** | **7 / 31** | **1 / 31** | **5 / 31** |

이 표에서 눈여겨볼 대목을 짚으면 이렇다.

- **문서와 실측이 정확히 맞았다.** 문서가 말한 허용 목록 6개(`DEL` `MSET` `MGET` `EXISTS` `UNLINK` `TOUCH`)와
  `EnterpriseCluster`의 통과 항목이 한 개도 어긋나지 않았다.
- **`OSSCluster` × 클러스터의 4개는 서버가 허용한 것이 아니다.** redis-py가 키별로 쪼개서 각 노드에 나눠 보내기
  때문이다. 클라이언트 구현에 기댄 동작이라 다른 언어의 SDK에서는 같은 코드가 실패할 수 있다.
  실제로 같은 클라이언트에서도 `MGET`/`MSET`은 쪼개 주지 않아 실패했다.
- **가장 낮은 점수는 `OSSCluster` × 비클러스터의 1 / 31이다.** 그런데도 연결은 되고 단일 키 명령은 통과한다.
  숫자만큼 위험해 보이지 않는 것이 이 조합의 진짜 문제다.

**해시 태그로 같은 슬롯에 모으면 네 조합 모두 31 / 31 성공했다.**
정책을 무엇으로 고르든, 클라이언트가 무엇이든, **키를 같은 슬롯에 모으는 것만이 보편적인 해법**이다.

#### 2.4.1 OSSCluster + 비클러스터 클라이언트 — 절반만 동작하는 조합

가장 주의할 조합이다. 연결도 되고 `SET`/`GET`도 되니 **얼핏 잘 되는 것처럼 보인다.**
그런데 허용 목록의 다중 키 명령이 **같은 슬롯 키인데도** `MOVED`로 실패한다.

새 연결을 20번 맺어 같은 명령을 한 번씩 실행했다.

| 명령 | 성공 | `MovedError` |
|---|---|---|
| `GET` (단일 키) | 20 | 0 |
| `SET` (단일 키) | 20 | 0 |
| `DEL` | 7 | **13** |
| `UNLINK` | 11 | **9** |
| `EXISTS` | 12 | **8** |
| `TOUCH` | 11 | **9** |

거의 동전 던지기다. 그리고 **연결을 하나 잡아 20번 반복하면 결과가 한쪽으로 고정된다**
(어떤 연결은 `DEL` 20/20 실패, 다른 연결은 `TOUCH` 20/20 성공).
즉 **성공 여부가 연결을 맺는 순간 정해지고 그 연결이 사는 동안 유지된다.**

커넥션 풀을 쓰는 애플리케이션에서는 이게 이렇게 나타난다.
**풀의 일부 커넥션은 계속 실패하고 나머지는 계속 성공한다.** 그래서
재시도해도 같은 커넥션이면 또 실패하고 실패가 특정 키와도 무관해 보인다.
스모크 테스트가 통과했는데 운영에서 간헐적으로 깨지는 전형적인 모양이다.

이 클러스터는 **샤드가 하나뿐이고 슬롯 0–16383을 전부 그 샤드가 맡는다.**
리다이렉트할 다른 노드가 없는데도 `MOVED`가 돌아온다. 샤드를 늘리면 나아지는 문제가 아니다.

**그리고 샤드가 하나였기 때문에 단일 키 `SET`/`GET`이 살아남았다.**
같은 랩에서 `Balanced_B5` 데이터베이스에 같은 비클러스터 클라이언트로 붙어 단일 키 `SET`을 500번 돌렸을 때는
**대부분이 `MovedError`로 실패**했다 ([`clustering-policy.json`](../migration-lab/results/clustering-policy.json)).
두 측정에서 기록이 갈리는 지점은 클러스터 구성 하나뿐이다.

| | 위 표의 클러스터 | `Balanced_B5` 클러스터 |
|---|---|---|
| `CLUSTER SLOTS` 응답 노드 | 1개 | 기록하지 않음 |
| 단일 키 `SET` | 성공 | 대부분 `MovedError` |
| 다중 키 (허용 목록) | 커넥션에 따라 갈림 | `ClusterCrossSlotError` |

**따라서 "단일 키는 괜찮다"로 읽으면 안 된다.** 슬롯을 나눠 가진 샤드가 둘 이상이면
비클러스터 클라이언트는 자기 슬롯이 아닌 키에서는 단일 키 명령에서도 `MOVED`를 받는다.
샤드가 하나인 구성에서는 오히려 문제가 **덜 보인다.**

> **결론:** `OSSCluster`를 고른다면 **클라이언트도 클러스터 모드로 바꿔야 한다.**
> 비클러스터 클라이언트를 그대로 두는 건 선택지가 아니다.

#### 2.4.2 클러스터 클라이언트의 TLS 인증서 검증 실패

`OSSCluster`에 클러스터 클라이언트로 붙을 때, redis-py는 `CLUSTER SLOTS`로 받은
**샤드의 IP 주소로 다시 접속한다.** 그런데 인증서는 `*.koreacentral.redis.azure.net` 이름으로 발급돼 있어
IP로는 검증에 실패한다.

```
SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED]
  certificate verify failed: IP address mismatch,
  certificate is not valid for '<노드 IP>'
```

이 랩에서는 **체인 검증은 유지한 채 호스트명 대조만 끄고**(`ssl_check_hostname=False`) 측정했다.
운영에서 이 옵션을 쓸지는 별도로 판단해야 한다 — 클라이언트마다 대응 방법이 다르고
이 문제 자체가 `OSSCluster` 전환 비용의 일부다.

### 2.5 EnterpriseCluster에 남는 크로스 슬롯 제약

위 표를 "무조건 무수정"으로 읽으면 안 된다. 문서가 명시하는 허용 목록은 6개뿐이다.

> You might also see `CROSSSLOT` errors with Enterprise clustering policy. **Only the following multikey
> commands are allowed across slots**: `DEL`, `MSET`, `MGET`, `EXISTS`, `UNLINK`, `TOUCH`.

[2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)에서 이 목록을 그대로 확인했다.
`EnterpriseCluster`가 크로스 슬롯으로 통과시킨 다중 키 명령은 **정확히 이 6개**였고
목록 밖으로 시험한 **24개는 전부 `CROSSSLOT`으로 실패**했다 (각 3회, 결과 일치).

- **통과 (6개)**: `MGET` `MSET` `DEL` `EXISTS` `UNLINK` `TOUCH`
- **실패 (24개)**: `SUNION` `SINTER` `SDIFF` `SUNIONSTORE` `SMOVE` `ZUNIONSTORE` `ZINTERSTORE` `ZDIFF`
  `RENAME` `COPY` `RPOPLPUSH` `LMOVE` `BLPOP` `LMPOP` `BITOP` `PFMERGE` `PFCOUNT` `MSETNX`
  `SORT ... STORE` `GEOSEARCHSTORE` `LCS` `XREAD` `MULTI`/`EXEC` `EVAL`(다중 `KEYS`)

실패 목록을 성격별로 묶으면 집합 연산, 정렬 집합 연산, 키 이동·복사, 리스트 간 이동, 스트림 다중 구독,
그리고 **서로 다른 슬롯의 키를 묶는 `MULTI`와 Lua 스크립트**다.
`EnterpriseCluster`는 크로스 슬롯 제약을 없애 주는 것이 아니라 **6개만 예외로 두는 것**이다.

> **그러므로 실제로 확인해야 할 것**은 "AMR이 단일 엔드포인트로 보이는가"가 아니라
> **"우리 애플리케이션이 위 6개 밖의 다중 키 명령을 쓰는가"** 다. 그 확인 방법이 [클라이언트·SDK 확인사항 3절](02-client-audit.md)이다.

### 2.6 정책 변경의 방향 — `NoCluster`에서 나오는 길 하나

`OSSCluster`로 만든 DB의 정책을 바꾸려 했더니 거부됐다.

```
$ az redisenterprise database update --clustering-policy EnterpriseCluster ...
BadRequest: 'properties.clusteringPolicy' cannot be changed
```

다만 **모든 방향이 막힌 것은 아니다.** CLI 정의가 규칙을 그대로 적어 두고 있다.

```
$ az redisenterprise database update --help
--clustering-policy : Clustering policy - default is OSSCluster.
    This property can be updated only if the current value is NoCluster.
    If the value is OSSCluster or EnterpriseCluster, it cannot be updated
    without deleting the database.
```

정책별로 정리하면 이렇다.

- **`NoCluster`에서는 나갈 수 있다.** `OSSCluster`나 `EnterpriseCluster`로 바꿀 수 있다.
  단 액티브 지역 복제가 켜져 있으면 이 방향도 막힌다.
- **`OSSCluster`에서는 나갈 수 없다.** DB를 삭제하고 다시 만드는 것 말고는 방법이 없다 (위 실측).
- **`EnterpriseCluster`도 마찬가지다.** 역시 DB 삭제 후 재생성이다.

`NoCluster`는 25GB 이하에서만 쓸 수 있다. **성능이 가장 낮고 이 상태로는 스케일 업이 막힌다.**
크기를 키우려면 먼저 정책을 바꿔야 한다. 그래서 `NoCluster`는 "일단 안전하게 시작하고 나중에 정한다"는
선택지가 된다. 다만 **정한 다음에는 그 방향으로 한 번만 갈 수 있는 일방통행**이다.

`OSSCluster`/`EnterpriseCluster`에서 바꾸려면 데이터베이스를 삭제하고 다시 만들어야 한다.
재생성한 데이터베이스는 **액세스 키 인증이 기본 비활성**이라 다시 켜고 키를 새로 받아야 한다.

```bash
az redisenterprise database create \
  --cluster-name <amr-name> --resource-group <rg> \
  --clustering-policy EnterpriseCluster \
  --access-keys-auth Enabled
```

> 데이터를 다 옮긴 뒤에 잘못 고른 걸 발견하면 **처음부터 다시 해야 한다.**
> 그래서 [클라이언트·SDK 확인사항](02-client-audit.md)의 명령어 감사가 AMR 생성보다 시간상 앞에 온다.
> 반대로 애플리케이션이 이미 클러스터 클라이언트를 쓰거나 처리량이 중요하다면 `OSSCluster`가 맞다.

---
