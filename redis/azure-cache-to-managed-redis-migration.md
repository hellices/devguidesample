# Azure Cache for Redis → Azure Managed Redis 마이그레이션 (GB 규모 실측)

> Korea Central에 실제 리소스를 만들어 **3.77GB / 215만 키** 규모로 측정한 결과입니다.
> 측정일 2026-08-27 KST (결과 JSON의 타임스탬프는 UTC라 2026-08-26으로 찍혀 있습니다).
> 테스트 환경 상세는 [11절](#11-부록-테스트-환경과-재현), 스크립트와 원본 JSON은 [`migration-lab/`](migration-lab/)에 있습니다.

**1~3절은 옮기기 전에 알아야 할 것, 4절부터는 어떻게 옮길 것인가입니다.**

---

## 1. 주의사항 한눈에 보기

### 1.1 ACR → AMR에서 바뀌는 것

우선순위 열은 [4절](#4-마이그레이션-우선순위)의 기준을 따릅니다. P0이 가장 높고, 데이터 정합성이 여기에 속합니다.
"실측" 표시가 붙은 항목은 이 랩에서 측정한 값이고, 나머지는 문서 근거입니다.

| 항목 | Azure Cache for Redis | Azure Managed Redis | 영향 | 우선순위 |
|---|---|---|---|---|
| 복사 중 유입된 쓰기 | — | — | 단일 복사 패스에서 유실률 48.47% (실측: 3.77GB / 215만 키). 키 개수 검증으로는 드러나지 않음 | P0 |
| 데이터 이관 수단 | — | Azure 마이그레이션 도구는 데이터를 옮기지 않음 (DNS 전환만) | 데이터는 직접 옮겨야 함 | P0 |
| 복제 명령 | `REPLICAOF`/`PSYNC`/`REPLCONF` 차단 | 동일하게 차단 | `REPLICAOF`로 따라붙게 하는 전략은 불가 | P0 |
| 데이터베이스 개수 | SKU별 16~64개 | 0번 하나 | `SELECT`/`MOVE`/`SWAPDB`, 커넥션 문자열의 DB 번호 수정 | P1 |
| 키스페이스 알림 | Basic 불가, Standard/Premium은 관리 평면에서 활성화 (실측: Basic C0 기본값 0건 수신) | 문서는 "미지원", 실측은 기본값 `AKE`로 **동작** | 문서와 실측이 어긋나는 항목. 지원 대상이 아니므로 **의존하면 안 됨** ([3.4절](#34-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)) | P1 |
| 클러스터링 | 선택 (Premium만) | SKU 무관 항상 켜짐 | 크로스 슬롯 제약이 상시 존재 | P1 |
| 다중 키 명령 | 비클러스터면 제약 없음 | `EnterpriseCluster`에서도 6개만 허용 (실측: 목록 밖 24개 전부 실패) | 그 밖은 `CROSSSLOT` 실패 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)) | P1 |
| `clusteringPolicy` | 해당 없음 | 생성 후 변경 불가 | 다시 고르려면 DB 재생성 + 데이터 재이관 | P1 |
| `SWAPDB` | 허용 (실측) | 차단 (실측: `unknown command`) | 다중 DB 전제의 운영 절차가 깨짐 | P1 |
| `ROLE` | 허용 (실측) | **허용** (실측) | 비클러스터 클라이언트 기준. 클러스터 클라이언트에서는 실패 | P3 |
| `FAILOVER` | **차단** (실측: `unknown command`) | 차단 (실측: `unknown command`) | 양쪽 다 안 되므로 페일오버 유도는 관리 평면으로 | P3 |
| 포트 | 6380 (TLS) / 6379 | 10000 | 연결 문자열, 방화벽, NSG | P1 |
| TLS | 선택 (비TLS 포트 존재) | 필수 | 비TLS 클라이언트는 연결 불가 | P1 |
| 호스트명 | `<name>.redis.cache.windows.net` | `<name>.<region>.redis.azure.net` | DNS, 허용 목록 | P1 |
| 유효 메모리 | 표기 용량 − 예약 2종 (P1 6GB → 약 4.4~4.75GB) | 표기 용량 × 약 0.8 | 1:1 매핑하면 한계에 근접 | P2 |
| HA 복제본 | Premium 복제본은 별도 | `usedmemory` 지표에 포함 (실측 1.98배) | 사용률 오독 | P2 |
| Redis 버전 | 6.0.x | 7.4.x | `DUMP`/`RESTORE` 호환은 확인됨 (실측: 오류 0건) | — |
| `CONFIG` | 차단 (실측: `unknown command`) | 명령은 **수락됨** (실측). 단 `SET`은 무효과, 미지원 파라미터는 거부 | AMR에서 성공 응답을 믿고 설정이 바뀌었다고 가정하면 안 됨 ([3.6절](#36-tier-34--정책-의존-항목과-관리-명령)) | P2 |
| 다운타임 | — | — | 복사 방식의 하한 약 111초 (실측: 3.77GB / 215만 키, 같은 리전 VM) | P3 |

**실측값은 이 랩의 데이터 크기·키 개수·네트워크 조건에서 나온 숫자입니다.** 48.47%와 111초 모두
3.77GB / 215만 키를 같은 리전 VM에서 옮겼을 때의 값이고, 데이터가 커지면 둘 다 커집니다.
자기 환경의 숫자는 리허설로 직접 재야 합니다 ([6.3절](#63-반복-복사로-유실이-얼마나-줄어드나)).

### 1.2 `EnterpriseCluster`냐 `OSSCluster`냐 — 쓰는 명령과 클라이언트가 결정합니다

AMR을 만들 때 정해야 하는 값이고 **생성 후에는 바꿀 수 없습니다.** 무엇을 고를지는 취향이 아니라
**애플리케이션이 어떤 명령을 쓰는지, 어떤 클라이언트를 쓰는지** 두 가지로 결정됩니다.

```
                     허용 목록 6개 밖의 다중 키 명령을 쓰는가?
                     (SUNION, ZUNIONSTORE, RENAME, RPOPLPUSH,
                      크로스 슬롯 MULTI/Lua 등 → 3.5절)
                                    │
                ┌───────────────────┴───────────────────┐
              아니오                                    예
                │                                       │
   클라이언트가 클러스터를 지원하는가?          해시 태그로 같은 슬롯에
   (RedisCluster / JedisCluster /              모을 수 있는가?
    Redis.Cluster / NewClusterClient)                   │
                │                          ┌────────────┴────────────┐
        ┌───────┴───────┐                 예                        아니오
       예             아니오               │                          │
        │               │            태그 적용 후 왼쪽 분기      데이터 25GB 이하?
   OSSCluster    EnterpriseCluster     (키 이름 변경 =              ┌───┴───┐
   (처리량 우위)   (단일 엔드포인트)     이관 전 배포 필요)         예      아니오
                                                                  │        │
                                                            NoCluster   로직 대체
                                                            (성능 최저)  (코드 수정)
```

| 조건 | 정책 | 클라이언트 작업 |
|---|---|---|
| 다중 키 명령을 거의 안 쓰고, 클러스터 클라이언트를 쓸 수 있다 | `OSSCluster` | 클러스터 전용 클라이언트로 교체 ([3.2절](#32-sdk별-확인-포인트)) |
| `MGET`/`MSET`/`DEL`/`EXISTS`/`UNLINK`/`TOUCH`를 여러 키로 쓴다 | `EnterpriseCluster` | 대체로 그대로. 포트·TLS·DB 번호만 |
| 허용 목록 밖 명령을 쓰지만 해시 태그를 붙일 수 있다 | 태그 적용 후 위 둘 중 하나 | 키 이름이 바뀌므로 **이관보다 배포가 먼저** |
| 허용 목록 밖 명령을 쓰고 태그도 못 붙이며 25GB 이하 | `NoCluster` | 그대로. 대신 성능이 가장 낮음 |
| 허용 목록 밖 명령을 쓰고 태그도 못 붙이며 25GB 초과 | 정책으로는 해결 안 됨 | 명령을 클라이언트 로직으로 대체 |

**첫 칸을 채우는 방법이 [3.3절](#33-명령어-감사--자동-스캔)의 명령어 감사입니다.**
스크립트가 TIER 2(허용 목록 밖)와 TIER 3(허용 목록 6개)을 세어 주므로, 그 두 숫자가 위 표의 입력값이 됩니다.
정책별로 무엇이 통과하고 무엇이 막히는지는 [2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)에서 실제로 돌려 봤습니다.

> **`OSSCluster`를 고른다면 클라이언트 교체는 선택이 아니라 필수입니다.**
> 비클러스터 클라이언트로도 연결은 되고 `SET`/`GET`도 동작해서 괜찮아 보이지만,
> 다중 키 명령이 **커넥션 단위로 갈려서** 풀의 일부만 계속 실패합니다 (실측: [2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)).
> 스모크 테스트로는 잡히지 않는 실패 방식입니다.

### 1.3 "클라이언트 수정 없이, 다운타임 없이"에 대한 답

클라이언트 수정은 대체로 피할 수 있습니다. 다운타임 없는 전환은 Azure 기능만으로는 되지 않습니다.

| 요구 | 답 | 근거 |
|---|---|---|
| 클라이언트 코드 수정 없이 | 대체로 가능하다. AMR 데이터베이스를 `EnterpriseCluster` 정책으로 **생성할 때** 정해야 한다 | [2절](#2-acr과-amr은-무엇이-다른가) |
| 그래도 확인할 것 | 다중 DB는 정책과 무관하게 코드를 고쳐야 한다. 키스페이스 알림은 문서상 미지원이나 실측으로는 동작했다 — 의존 중이라면 따로 판단이 필요하다. 다중 키 명령은 허용 목록 6개 밖이면 확인이 필요하다 | [3절](#3-클라이언트sdk-확인사항) |
| 다운타임 없이 | Azure 기능만으로는 불가능하다. 마이그레이션 도구는 데이터를 옮기지 않는다 | [7절](#7-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다) |
| 복제로 따라붙게 하면? | `REPLICAOF`는 소스·타깃 양쪽에서 차단된다. 물리적 복제 기반 전략은 쓸 수 없다 | [8.1절](#81-가장-먼저-떠오르는-방법-그리고-왜-막히는가) |
| 부득이한 다운타임 최소화 | 이 랩 규모(3.77GB / 215만 키)에서 실측 약 111초가 복사 방식의 하한. 더 줄이려면 논리적 복제나 애플리케이션 계층 전략 | [6.3절](#63-반복-복사로-유실이-얼마나-줄어드나), [8절](#8-실시간-마이그레이션-전략--replicaof는-왜-안-되는가) |

한 가지만 덧붙이면, 복사가 도는 동안 소스에 들어온 쓰기는 그대로 두면 타깃에 반영되지 않습니다.
이 랩에서는 단일 패스 기준 48.47%가 그렇게 빠졌고, 키 개수 비교로는 드러나지 않았습니다 ([6.2절](#62-그런데-복사-중-들어온-쓰기의-4847가-사라집니다)).

### 1.4 먼저 읽어 둘 문서

정책 선택과 명령 호환성 판단에 직접 필요한 것만 추렸습니다. 전체 목록은 [13절](#13-참고-자료)에 있습니다.

| 무엇을 볼 때 | 문서 |
|---|---|
| 클러스터 정책 세 가지의 동작과 선택 기준 | [Azure Managed Redis architecture — Cluster policies](https://learn.microsoft.com/azure/redis/architecture#cluster-policies) |
| 허용 목록 6개와 `CROSSSLOT` 조건 | [AMR architecture — Multi-key commands](https://learn.microsoft.com/azure/redis/architecture#multi-key-commands) |
| ACR에서 막혀 있는 명령 | [Redis commands not supported in Azure Cache for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis) |
| AMR(Redis Enterprise)에서 막혀 있는 명령 | [Redis Enterprise command compatibility](https://redis.io/docs/latest/operate/rs/references/compatibility/commands/) |
| 해시 태그로 슬롯을 모으는 규칙 | [Redis Cluster specification — Hash tags](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags) |
| ACR → AMR 마이그레이션 경로 (Microsoft 안내) | [Migration options](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options) |

---

## 2. ACR과 AMR은 무엇이 다른가

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

재현 스크립트와 원본 결과는 [11.2절](#112-재현하기)에 있습니다. `NoCluster`는 테스트하지 않았습니다.

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
> **"우리 애플리케이션이 위 6개 밖의 다중 키 명령을 쓰는가"** 입니다. 그 확인 방법이 [3절](#3-클라이언트sdk-확인사항)입니다.

### 2.6 생성 후에는 바꿀 수 없습니다

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

> 데이터를 다 옮긴 뒤에 잘못 고른 걸 발견하면 **처음부터 다시 해야 합니다.**
> 그래서 3절의 명령어 감사가 AMR 생성보다 시간상 앞에 옵니다.
> 반대로 애플리케이션이 이미 클러스터 클라이언트를 쓰거나 처리량이 중요하다면 `OSSCluster`가 맞습니다.

---

## 3. 클라이언트·SDK 확인사항

2절의 결론은 "우리 애플리케이션이 허용 목록 밖의 다중 키 명령을 쓰는가"를 확인하라는 것이었습니다.
이 절이 그 확인 목록입니다. **데이터를 옮기기 전에, `clusteringPolicy`를 정하기 전에 해야 하는 작업입니다.**

### 3.1 연결 설정 — 무조건 바뀌는 것

| 항목 | ACR | AMR |
|---|---|---|
| 포트 | 6380 (TLS) / 6379 (비TLS) | **10000** |
| 호스트명 | `<name>.redis.cache.windows.net` | `<name>.<region>.redis.azure.net` |
| TLS | 선택 (비TLS 포트 존재) | **필수** |
| 데이터베이스 | SKU에 따라 16~64개 | **0번 하나** |
| Redis 버전 | 6.0.x | 7.4.x |
| `CONFIG` 변경 | 명령 자체가 차단 (실측) | 명령은 통과하나 반영 안 됨 (실측) |

두 쪽 모두 **설정 변경은 관리 평면을 거쳐야 합니다.** 다만 실패하는 방식이 다릅니다 —
ACR은 `unknown command`로 시끄럽게 실패하고, AMR은 `OK`를 돌려주면서 조용히 무시합니다 ([3.6절](#36-tier-34--정책-의존-항목과-관리-명령)).

포트가 바뀐다는 것은 **방화벽·NSG·프라이빗 엔드포인트 규칙도 바뀐다**는 뜻입니다.
연결 문자열만 고치고 네트워크 규칙을 빠뜨리는 것이 컷오버 당일 가장 흔한 실패입니다.

### 3.2 SDK별 확인 포인트

> 이 표는 각 SDK의 문서·API 기준으로 정리한 것입니다.
> **이 랩에서 실제로 접속해 본 것은 `redis-py` 하나뿐입니다** (비클러스터·클러스터 양쪽 모두, [2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)).
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
  다중 키 명령이 커넥션 단위로 `MOVED`를 냅니다 ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)).
- **클러스터 클라이언트는 샤드 IP로 재접속하므로 TLS 호스트명 검증에서 막힐 수 있습니다.**
  인증서가 `<region>.redis.azure.net` 이름으로 발급돼 있어 IP와 대조하면 실패합니다.
  SDK마다 해법이 다르니(SNI 지정, 호스트명 검증 옵션 등) 미리 확인하세요.

### 3.3 명령어 감사 — 자동 스캔

정적 스캔 스크립트를 [`migration-lab/audit_commands.sh`](migration-lab/audit_commands.sh)에 넣어 뒀습니다.

```bash
./migration-lab/audit_commands.sh ./src ./config
# TIER 1 적중이 있으면 종료 코드 1 (CI 게이트로 쓸 수 있습니다)
```

| 등급 | 의미 | 조치 |
|---|---|---|
| **TIER 1** | 다중 DB, 키스페이스 알림 의존 — **정책으로 해결 안 됨** | 코드 수정 / 별도 판단 ([3.4](#34-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)) |
| **TIER 2** | 허용 목록 6개 밖의 크로스 슬롯 다중 키 명령 | 해시 태그 / 로직 대체 / `NoCluster` ([3.5](#35-tier-2--크로스-슬롯-다중-키-명령)) |
| **TIER 3** | 허용 목록 6개의 다중 키 호출 | `OSSCluster`를 고를 때만 문제 ([3.6](#36-tier-34--정책-의존-항목과-관리-명령)) |
| **TIER 4** | 서버·관리 명령 | 대부분 양쪽에서 차단 ([3.6](#36-tier-34--정책-의존-항목과-관리-명령)) |

> **스크립트는 [3.7절](#37-정적-스캔만으로는-부족합니다)과 반드시 함께 쓰세요.**
> 정적 스캔은 프레임워크가 대신 호출하는 명령을 구조적으로 놓칩니다.

### 3.4 TIER 1 — 정책과 무관하게 반드시 고쳐야 하는 것

`NoCluster`를 골라도, 해시 태그를 다 붙여도 해결되지 않습니다. **코드를 고치는 것 말고는 방법이 없습니다.**

| 확인 대상 | 무엇을 찾나 | 왜 |
|---|---|---|
| **다중 데이터베이스** | `SELECT n` (n≥1), `MOVE`, `SWAPDB`, 커넥션 문자열 끝의 `/1`~`/63`, Spring `spring.redis.database`, Lettuce/Jedis의 `database` 옵션, `redis://host:6380/2` | **AMR은 데이터베이스 0 하나만 제공합니다.** ACR은 SKU에 따라 **최대 16~64개**를 씁니다 (C0~C3·P1 16개, C4·P2 32개, C5·P3 48개, C6·P4·P5 64개). 여기서 넘어오면 깨집니다 |
| **키스페이스 알림** | `__keyspace@0__:`, `__keyevent@0__:expired`, `notify-keyspace-events`, `RedisIndexedSessionRepository`, `@EnableRedisIndexedHttpSession` | **문서와 실측이 어긋납니다.** 문서는 AMR 미지원이라고 하지만, 이 랩의 AMR은 기본값 `AKE`로 이벤트를 실제로 발행했습니다. 지원 대상이 아닌 동작에 의존하는 셈이라 그대로 두면 위험합니다 |

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

> 마이그레이션 도구를 쓸 때도 [7절](#7-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다) 표에 있듯
> **알림 설정 자체는 넘어가지 않습니다.** 타깃에서 다시 확인해야 합니다.

### 3.5 TIER 2 — 크로스 슬롯 다중 키 명령

**`EnterpriseCluster`를 골라도 실패할 수 있는 명령들입니다.** 허용 목록은 6개(`DEL`·`MSET`·`MGET`·`EXISTS`·`UNLINK`·`TOUCH`)뿐이고,
아래는 전부 그 밖입니다. [2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)에서 목록 밖 24개를 실제로 돌려 봤고
**전부 `CROSSSLOT`으로 실패했습니다.** 아래 표는 그 결과를 계열별로 넓힌 것입니다.

| 계열 | 명령 | 비고 |
|---|---|---|
| 집합 | `SINTER` `SUNION` `SDIFF` `SINTERSTORE` `SUNIONSTORE` `SDIFFSTORE` `SINTERCARD` `SMOVE` | 태그 기반 필터링·추천 로직에서 흔함 |
| 정렬셋 | `ZUNION` `ZINTER` `ZDIFF` `ZUNIONSTORE` `ZINTERSTORE` `ZDIFFSTORE` `ZINTERCARD` `ZRANGESTORE` | 랭킹 집계에서 흔함 |
| 리스트 이동 | `RPOPLPUSH` `BRPOPLPUSH` `LMOVE` `BLMOVE` `LMPOP` `BLMPOP` | **큐 구현의 핵심 패턴.** 작업 큐를 Redis로 쓰면 거의 확실히 걸립니다 |
| 다중 키 블로킹 | `BLPOP` `BRPOP` `BZPOPMIN` `BZPOPMAX` `BZMPOP` | 키를 하나만 넘기면 문제없지만, 여러 큐를 동시에 기다리는 형태가 문제 |
| 키 조작 | `RENAME` `RENAMENX` `COPY` `SORT ... STORE` | 원본과 대상이 다른 슬롯이면 실패 |
| 비트/HLL | `BITOP` `PFMERGE`, 다중 키 `PFCOUNT` | 일별 UV 집계에서 흔함 |
| 스트림/GEO | 다중 키 `XREAD`/`XREADGROUP`, `GEOSEARCHSTORE` | |
| 기타 | `MSETNX` `LCS` | `MSETNX`는 `MSET`과 달리 허용 목록에 **없습니다** |
| 트랜잭션 | 서로 다른 슬롯의 키를 묶는 `MULTI`/`EXEC`, `WATCH` | 명령이 아니라 **묶인 키들의 슬롯**이 관건 |
| Lua | `EVAL`/`EVALSHA`/`FCALL`의 `KEYS` 인자가 여러 슬롯에 걸칠 때 | 같은 문제 |

**조치는 셋 중 하나입니다.**

1. **해시 태그로 같은 슬롯에 모읍니다.** ([2.2절](#22-샤딩과-클러스터--amr은-항상-클러스터입니다))
   가장 정공법이지만 **키 이름이 바뀌므로 마이그레이션 이전에 애플리케이션 배포가 선행돼야 합니다.**
2. **명령을 클라이언트 측 로직으로 대체합니다.** `SUNIONSTORE` → 각 집합을 `SMEMBERS`로 읽어 애플리케이션에서 합치기.
   왕복이 늘어나므로 대상 집합이 작을 때만 유효합니다.
3. **`NoCluster`를 씁니다.** 25GB 이하일 때만 가능하고 성능이 가장 낮습니다.
   Microsoft가 문서에서 `NoCluster`의 대표 사례로 드는 것이 정확히 이 상황(크로스 슬롯 `MULTI` 광범위 사용)입니다.

### 3.6 TIER 3·4 — 정책 의존 항목과 관리 명령

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

### 3.7 정적 스캔만으로는 부족합니다

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

## 4. 마이그레이션 우선순위

여기서부터가 "어떻게 옮길 것인가"입니다. 그리고 마이그레이션에서는 **모든 것을 동시에 최적화할 수 없습니다.**
다운타임을 줄이면 정합성이 흔들리고, 정합성을 지키면 다운타임이 늘어납니다. 그래서 순위가 필요합니다.

### 4.1 우선순위는 "되돌릴 수 있는가"로 정합니다

| 순위 | 관심사 | 실패하면 | 되돌릴 수 있나 | 어떻게 드러나나 |
|---|---|---|---|---|
| **P0** | **데이터 정합성** | 쓰기가 사라진다 | **불가능** — 소스를 지우면 끝 | **조용히.** 키 개수 검증을 통과한다 |
| **P1** | 호환성 (정책·명령어) | 애플리케이션이 실패한다 | 가능하지만 비쌈 — DB 재생성 + 재이관 | 대부분 시끄럽게 (예외·`CROSSSLOT`). **단 키스페이스 알림은 조용함** |
| **P2** | 용량 | 축출이 시작된다 | 가능 — SKU 상향 | 반쯤 조용히 (지표로만 보임) |
| **P3** | 다운타임 | 서비스가 멈춘다 | 가능 — 창을 늘리면 된다 | 즉시, 명확하게 |

**데이터 정합성이 1순위인 이유는 두 가지입니다.**

1. **유일하게 되돌릴 수 없습니다.** 나머지 셋은 시간과 비용으로 복구됩니다. 정책을 잘못 골랐으면 DB를 다시 만들고,
   용량이 모자라면 SKU를 올리고, 다운타임이 길면 다음 창을 잡으면 됩니다.
   반면 복사되지 않은 쓰기는 소스를 지우고 나면 되찾을 방법이 없습니다.
2. **유일하게 조용합니다.** 호환성 문제는 예외로 터지고, 용량은 지표에 뜨고, 다운타임은 누구나 압니다.
   정합성은 신호 없이 지나갑니다. 이 랩에서 48.47%를 잃은 마이그레이션도 키 개수 검증은 통과했습니다.

> 트레이드오프가 생기면 정합성 쪽을 택하는 것을 기본으로 삼으세요.
> "다운타임 111초(실측: 3.77GB / 215만 키)" vs "다운타임 0초 + 유실 20%"의 선택이라면 111초가 기본값입니다.
> 유실을 감수하겠다는 결정은 **데이터 성격을 확인한 뒤 명시적으로** 내려야 합니다 (순수 캐시라면 정당한 선택입니다).

### 4.2 P0 — 데이터 정합성

**전략별 정합성 등급.** 무엇을 고르든 이 표의 오른쪽 열을 먼저 보세요.

| 전략 | 정합성 | 근거 |
|---|---|---|
| 쓰기 차단 + 최종 복사 패스 | 무손실 | 실측 (프로브 37,456건 중 유실 0) |
| 애플리케이션 이중 쓰기 | 무손실 설계 (읽기-수정-쓰기 제외) | 미검증 |
| 반복 복사 패스 (쓰기 유지) | 손실 있음 — 2패스 후 20.21% | 실측 |
| RIOT `--mode live` | 보장 없음 — 도구 문서가 명시 | 미검증 |
| 프록시 미러링 | 보장 없음 — 미러 쓰기 실패가 드러나지 않음 | 미검증 |
| 단일 복사 패스 | 48.47% 손실 | 실측 |
| RDB Export/Import | 스냅샷 이후 쓰기 전부 손실 | 구조상 |
| 캐시 재수화 | 전량 손실 (의도적) | — |

**체크리스트:**

- [ ] **유실 구간을 어떻게 없앨지 먼저 정한다.** 복사를 시작한 뒤에 고민하면 늦습니다.
- [ ] **TTL을 함께 옮긴다.** `PTTL`을 읽어 `RESTORE`의 ttl 인자로 넘기지 않으면 **만료 예정 키가 영구 키가 됩니다.**
- [ ] **검증을 키 개수로 하지 않는다.** `EXISTS`도 안 됩니다 — 키는 있는데 값이 옛것인 경우를 놓칩니다. **값과 TTL까지** 봅니다.
- [ ] **표본을 `RANDOMKEY`로 뽑는다.** `SCAN` 앞부분에서 뽑으면 먼저 적재된 키에 쏠려 뒤쪽 유실을 놓칩니다.
- [ ] **`DUMP` 페이로드를 바이트 비교하지 않는다.** RDB 버전 푸터 때문에 Redis 6 → 7.4에서는 값이 같아도 전부 불일치로 나옵니다.
- [ ] **소스가 `maxmemory` 근처면 먼저 여유를 확보한다.** 기본 축출 정책 `volatile-lru`는 **조용히 지우고 쓰기는 성공시킵니다.**
- [ ] **읽기-수정-쓰기 명령을 식별한다.** `INCR`, `LPUSH`, `SETNX`는 이중 쓰기로 정합성이 깨집니다.
- [ ] **소스는 검증을 통과하기 전까지 지우지 않는다.** 되돌릴 수 없는 지점은 여기 하나뿐입니다.

### 4.3 P1 — 호환성

- [ ] [3.3절](#33-명령어-감사--자동-스캔) 명령어 감사를 돌린다. **TIER 1이 0건이 아니면 코드 수정이 선행돼야 합니다.**
- [ ] TIER 2 결과로 `clusteringPolicy`를 정한다. TIER 2·3이 모두 0건이면 `OSSCluster`(성능 우위)를 검토합니다.
- [ ] 해시 태그가 필요하면 **애플리케이션 배포를 데이터 이관보다 먼저** 한다. 키 이름이 바뀌기 때문입니다.
- [ ] SDK를 클러스터 클라이언트로 바꿔야 하는지 확인한다 ([3.2절](#32-sdk별-확인-포인트)).
- [ ] 포트·TLS·호스트명 변경에 맞춰 **방화벽·NSG·프라이빗 엔드포인트를 함께 수정**한다.
- [ ] `clusteringPolicy`를 확정하고 AMR을 생성한다. **이후에는 바꿀 수 없습니다.**

### 4.4 P2 — 용량

- [ ] 소스의 **실제 `used_memory`** 를 본다. SKU 표기 용량이 아닙니다.
- [ ] 타깃 유효 용량 = **표기 용량 × 약 0.8**. ACR 데이터 크기를 같은 숫자의 AMR SKU에 1:1로 매핑하면 안 됩니다.
- [ ] HA를 켰다면 `usedmemory` 지표가 **약 2배로 보입니다** (실측 1.98배). 오독하지 마세요.
- [ ] 소스의 `maxmemory-policy`를 확인한다. 용량 부족은 **P0 문제(조용한 유실)로 번집니다.**

자세한 근거는 [10절](#10-용량-산정--두-번-속습니다).

### 4.5 P3 — 다운타임

- [ ] 이 랩의 실측값은 3.77GB / 215만 키를 같은 리전 VM에서 옮겼을 때 약 111초입니다.
      데이터 크기에 비례해 늘어나므로 **자기 데이터로 리허설해서 직접 재세요.**
- [ ] 더 줄이려면 애플리케이션 계층이나 논리적 복제가 필요합니다 ([8절](#8-실시간-마이그레이션-전략--replicaof는-왜-안-되는가)).
- [ ] 다운타임을 줄이려고 유실을 감수하는 선택은 P0을 내려놓는 것입니다. 데이터 성격을 확인한 뒤에만 하세요.

### 4.6 우선순위 ≠ 순서

우선순위는 **"충돌하면 무엇을 지키나"**, 순서는 **"무엇을 먼저 하나"** 입니다. 두 축이 다릅니다.
정합성이 P0이지만, 시간축에서는 감사(P1)가 가장 앞에 옵니다 — 그 결과가 나머지 전부를 결정하기 때문입니다.

```
1. [P1] 명령어 감사        → 코드 수정 필요 여부와 clusteringPolicy가 여기서 정해진다
2. [P1] 해시 태그가 필요하면 애플리케이션 먼저 배포
3. [P2] 용량 산정          → AMR SKU 결정
4. [P1] AMR 생성           → clusteringPolicy 확정. 이후 변경 불가
5. [P0] 정합성 전략 확정   → 쓰기 차단 창을 잡을 수 있는가?
6. [P3] 리허설             → 다운타임 실측. 여기서 나온 숫자로 창을 협의
7.      본 이관
8. [P0] 검증               → 키 개수가 아니라 값과 TTL
9.      소스 삭제          → 되돌릴 수 없는 지점. 8이 통과한 뒤에만
```

구체적인 실행 절차는 [9절](#9-권장-절차)에 있습니다.

---

## 5. 경로 A: RDB Export / Import

```
ACR (Premium) --export--> Blob Storage --import--> AMR
```

### 5.1 Export는 잘 됩니다

| 항목 | 값 |
|---|---|
| 소요 시간 | **186.99초** |
| 결과 blob | 2,271,735,296 B (**2.12 GiB**) |
| 인메모리 대비 | 약 47% (압축됨) |
| 인증 | 시스템 할당 관리 ID |

Export는 관리 ID를 지원하므로, 스토리지 계정이 공용 네트워크 접근을 막고 있어도
신뢰할 수 있는 서비스 예외를 통해 동작합니다.

### 5.2 Import는 이 환경에서 실패했습니다

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

## 6. 경로 B: `SCAN` + `DUMP`/`RESTORE` 프로그래매틱 복사

Basic/Standard처럼 Export를 못 쓰거나, 경로 A가 정책으로 막힌 경우의 대안입니다.
[`migration-lab/migrate_scan_copy.py`](migration-lab/migrate_scan_copy.py)가 하는 일은 다음과 같습니다.

- `KEYS *` 대신 **`SCAN` 커서** — `KEYS`는 O(N) 블로킹 명령이라 수백만 키 인스턴스를 멈춥니다.
- 타입별 `HGETALL`/`LRANGE` 대신 **`DUMP` → `RESTORE ... REPLACE`** — 타입에 무관하고 클라이언트 메모리도 덜 씁니다.
- **`PTTL`을 함께 읽어 TTL을 보존** — 이걸 빠뜨리면 만료 예정 키가 영구 키가 됩니다.
- 읽기·쓰기 모두 파이프라인(500개 단위)으로 묶어 왕복 지연을 상쇄합니다.

Redis 6.0.14에서 만든 `DUMP` 페이로드를 Redis 7.4.3에 `RESTORE`하는 것은 정상 동작했습니다 (오류 0건).

### 6.1 복사 자체는 빠르고 정확합니다

| 항목 | 값 |
|---|---|
| 복사한 키 | 2,129,472 |
| 소요 시간 | **130.2초** (약 16,400 keys/s) |
| `RESTORE` 오류 | **0건** |
| TTL 옮긴 키 | 470,774 |
| TTL 보존 (표본 2,000) | **2,000 / 2,000 (유실 0%)** |
| 값 무결성 (무작위 표본 2,496) | 일치 2,482, **불일치 0**, 타깃에 없음 14 |

### 6.2 그런데 복사 중 들어온 쓰기의 48.47%가 사라집니다

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

### 6.3 반복 복사로 유실이 얼마나 줄어드나

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
쓰기를 차단한 최종 패스도 여전히 전체 키를 훑습니다. 그래서 그 패스 시간이 그대로 다운타임이 됩니다.

이 규모(215만 키 / 3.77GB, 같은 리전 VM에서 실행)에서 **복사 방식의 다운타임 하한은 약 111초**입니다.
클라이언트가 다른 리전에 있거나 파이프라인 크기가 작으면 더 늘어납니다.

---

## 7. 경로 C: Azure 마이그레이션 도구는 데이터를 옮기지 않는다

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

## 8. 실시간 마이그레이션 전략 — `REPLICAOF`는 왜 안 되는가

6절에서 측정한 111초(3.77GB / 215만 키)는 **복사 방식의 하한**입니다. 그 아래로 내려가려면 복사가 아니라
**"소스가 살아 있는 동안 타깃이 계속 따라오게 하는"** 방식이 필요합니다. 이 절이 그 선택지를 정리합니다.

### 8.1 가장 먼저 떠오르는 방법, 그리고 왜 막히는가

자체 관리 Redis라면 이게 정석입니다.

```
1. 타깃에서 REPLICAOF <소스> <포트>
2. 초기 동기화(RDB 전송) + 이후 스트리밍 복제
3. master_repl_offset 지연이 0에 수렴할 때까지 대기
4. 소스 쓰기 차단 → 타깃에서 REPLICAOF NO ONE으로 승격 → 트래픽 전환
```

다운타임이 4단계의 수 초로 압축됩니다. 개념적으로 정확하고, 실제로 온프레미스 Redis 이관의 표준 절차입니다.

**하지만 ACR → AMR에서는 소스와 타깃 양쪽 모두에서 차단됩니다.**

**소스(ACR)가 외부 복제본을 거부합니다.** Microsoft의 미지원 명령 목록에
`PSYNC`, `REPLICAOF`, `SLAVEOF`, `SYNC`, `REPLCONF`, `MIGRATE`가 모두 올라 있고, `REPLCONF` 항목에는 이유가 명시돼 있습니다.

> Azure cache for Redis instances **don't allow customers to add external replicas**.
> — [Redis commands not supported in Azure Cache for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis)

**타깃(AMR)도 복제 명령을 제공하지 않습니다.** AMR이 올라가 있는 Redis Enterprise 스택의 호환성 표에서
`REPLICAOF`, `SLAVEOF`, `SYNC`, `PSYNC`, `REPLCONF`, `ROLE`, `FAILOVER`, `MIGRATE`가 전부 **Not supported**입니다.

즉 "타깃에서 명령을 못 쓴다"와 "소스가 받아 주지 않는다"가 동시에 성립합니다. 한쪽만 문제라면 우회할 여지가 있지만, 양쪽입니다.

**Redis Enterprise의 "Replica Of" 기능은요?** Redis Enterprise 제품에는 외부 Redis를 소스로 삼는
액티브-패시브 복제(Replica Of) 기능이 실제로 있습니다. 그러나 **Azure의 ARM 표면에 노출돼 있지 않습니다.**

```
$ az redisenterprise database create --help
--group-nickname     : Name for the group of linked database resources.
--linked-databases   : List of database resources to link with this database.
```

이건 **AMR ↔ AMR 액티브 지역 복제**입니다. 링크 대상이 `.../redisEnterprise/.../databases/` 리소스 ID여야 하므로
ACR을 넣을 수 없습니다. 설령 노출됐더라도 결국 소스를 향해 복제 프로토콜을 말해야 하고, 그건 위에서 막혀 있습니다.

같은 이유로 **`redis-shake`의 `sync` 모드도 쓸 수 없습니다.** `PSYNC`를 씁니다.

> **정리**: 물리적 복제(replication protocol) 기반 전략은 관리형 → 관리형 구간에서 존재하지 않습니다.
> 남는 것은 **논리적 복제** — 쓰기를 이벤트나 애플리케이션 레벨에서 관찰해 타깃에 다시 적용하는 방식뿐입니다.

### 8.2 RIOT / RIOT-X 라이브 복제 — 의도에 가장 가까운 대안

> **이 랩에서 검증하지 않았습니다.** 문서 근거만 확인했습니다.

Microsoft가 self-service 마이그레이션 문서에서 "Programmatic migration" 경로로 안내하는 도구입니다.
`REPLICAOF`와 **형태는 같고 전송 계층만 다릅니다** — PSYNC 대신 **키스페이스 알림(pub/sub)** 으로 변경을 관찰합니다.

```bash
# 1) 소스 ACR에 키스페이스 알림을 켭니다. CONFIG SET이 막혀 있으므로 관리 평면으로 설정합니다.
az redis update -n <acr> -g <rg> --set "redisConfiguration.notify-keyspace-events=KEA"

# 2) 스냅샷 + 라이브 스트림
riot replicate \
  -h <acr>.redis.cache.windows.net -p 6380 --tls --pass <key> \
  --target-h <amr>.<region>.redis.azure.net --target-p 10000 --target-tls --target-pass <key> \
  --mode live

# 3) 컷오버 전 대조
riot compare --full ...
```

`--mode live`는 초기 `SCAN` 스냅샷과 실시간 스트림을 **동시에** 돌립니다.
6절에서 본 "커서가 지나간 자리의 쓰기가 사라지는" 문제를 알림 스트림이 메워 주는 구조입니다.

**받아들여야 하는 제약:**

- **일관성을 보장하지 않습니다.** RIOT 문서가 직접 그렇게 씁니다 —
  *"The live replication mechanism does not guarantee data consistency."*
  키스페이스 알림은 **fire-and-forget pub/sub**이라, 구독자가 잠깐 느리거나 끊기면 그 사이 이벤트는 그냥 사라집니다.
  **그래서 컷오버 전 `riot compare --full`이 선택이 아니라 필수입니다.**
- 알림은 **키 이름만** 알려 줍니다. RIOT은 이름을 받고 소스에서 값을 다시 읽으므로, 소스 읽기 부하가 늘어납니다.
- **Basic SKU에서는 쓸 수 없습니다.** 키스페이스 알림은 Standard 이상입니다.
- `KEA`는 모든 이벤트를 발행합니다. 쓰기가 많은 인스턴스에서 소스 CPU 부담이 얼마나 되는지는
  **이 랩에서 측정하지 않았습니다.** 프로덕션에 켜기 전에 관측하세요.
- 여기서 알림이 필요한 쪽은 **소스인 ACR**입니다. [3.4절](#34-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)의
  AMR 쪽 논의와는 방향이 다릅니다. (반대 방향, 즉 AMR에서 다른 곳으로 나가는 라이브 복제는 이 방법으로 안 됩니다.)

### 8.3 애플리케이션 계층 — 이중 쓰기와 지연 백필

> **이 랩에서 검증하지 않았습니다.** 설계 지침입니다.

**(a) 이중 쓰기** — 9.2절에서 다룹니다. 유실 구간을 원천 제거하는 유일한 방법이지만 애플리케이션 변경이 가장 큽니다.

**(b) 읽기 폴백 + 지연 백필** — 캐시라면 이쪽이 훨씬 쌉니다.

```
읽기: AMR 조회 → miss → ACR 조회 → 값이 있으면 AMR에 채우고 반환 → 없으면 원본에서 계산
쓰기: 처음부터 AMR에만
```

트래픽이 도는 대로 뜨거운 키가 자연스럽게 AMR로 넘어갑니다. **벌크 복사 자체가 필요 없어집니다.**
쓰기가 AMR에만 가므로 이중 쓰기의 읽기-수정-쓰기 정합성 문제도 없습니다.
대신 전환 기간 동안 **캐시 미스마다 왕복이 두 번**이고, 두 인스턴스를 동시에 유지해야 합니다.
TTL이 짧은 순수 캐시라면 며칠이면 ACR을 뗄 수 있습니다.

### 8.4 프록시 계층 미러링 — 애플리케이션을 안 고치는 경우

> **이 랩에서 검증하지 않았습니다.**

애플리케이션 코드를 못 고치는 상황(레거시, 서드파티, 다수 팀)에서 이중 쓰기를 인프라로 밀어 넣는 방법입니다.
Envoy의 Redis 프록시 필터가 `request_mirror_policy`를 제공합니다.

```yaml
prefix_routes:
  catch_all_route:
    cluster: acr_primary
    request_mirror_policy:
      - cluster: amr_target
        exclude_read_commands: true     # 읽기는 미러링하지 않음
        runtime_fraction: { default_value: { numerator: 100, denominator: HUNDRED } }
```

애플리케이션은 프록시 주소만 봅니다. 쓰기는 ACR과 AMR 양쪽으로 갑니다.
**주의: 미러 트래픽은 fire-and-forget입니다.** 응답을 기다리지 않으므로 **AMR 쓰기 실패가 아무 데도 드러나지 않습니다.**
Envoy 문서도 이 필터를 "not hardened"로 표기합니다. 대조 검증을 반드시 별도로 돌려야 합니다.

트래픽 경로에 홉이 하나 늘어난다는 점, 그리고 프록시 자체가 새로운 단일 장애점이 된다는 점도 계산에 넣으세요.

### 8.5 캐시 재수화 — 데이터를 아예 안 옮기는 선택지

**Redis를 순수 look-aside 캐시로만 쓴다면, 데이터를 옮길 이유가 없습니다.** Microsoft도 문서에서 이 선택지를 명시합니다.
빈 AMR로 연결을 바꾸고 원본(DB/API)에서 다시 채우면 끝입니다. 다운타임 0, 데이터 유실은 "전량이지만 의도된 것".

**전제 조건 두 가지를 반드시 확인하세요.**

- Redis에만 있는 데이터가 없어야 합니다. **세션, 분산 락, 레이트 리밋 카운터, 작업 큐, 스트림은 재계산이 불가능합니다.**
  하나라도 있으면 이 방법은 못 씁니다.
- **백엔드가 콜드 스타트 부하를 견뎌야 합니다.** 캐시가 비면 모든 요청이 원본으로 갑니다.
  전환 직후 몇 분간 DB가 감당 못 하면 이 방법이 가장 긴 장애가 됩니다. 미리 워밍업하거나 점진 전환하세요.

### 8.6 비교

| 전략 | 다운타임 | 데이터 유실 | 애플리케이션 변경 | 이 랩 검증 |
|---|---|---|---|---|
| `REPLICAOF` 복제 | — | — | — | **불가능 (양쪽 차단)** |
| RDB Export/Import | 스냅샷 이후 쓰기 전부 | 큼 | 없음 | Export만 (5절) |
| `SCAN` 복사 + 쓰기 차단 | 약 111초 (실측: 3.77GB / 215만 키) | 0 | 없음 | ✅ (6.3절) |
| `SCAN` 복사 반복 (쓰기 유지) | 0 | 패스당 약 절반씩 수렴 (2패스 후 20.21%) | 없음 | ✅ (6.3절) |
| RIOT `--mode live` | 롤아웃 시간 | **보장 없음** — 대조 필수 | 없음 | ✗ |
| 애플리케이션 이중 쓰기 | 롤아웃 시간 | 0 (읽기-수정-쓰기 제외) | **큼** | ✗ |
| 읽기 폴백 + 지연 백필 | 롤아웃 시간 | 해당 없음 | 중간 | ✗ |
| 프록시 미러링 (Envoy) | 롤아웃 시간 | fire-and-forget이라 미검출 | 없음 (인프라 변경) | ✗ |
| 캐시 재수화 | 0 | 전량 (의도적) | 없음 | ✗ |

### 8.7 선택 기준

```
Redis에 재계산 불가능한 데이터가 있는가?
├─ 아니오 → 8.5 캐시 재수화. 가장 싸고 가장 빠릅니다. 백엔드 콜드 스타트만 확인하세요.
└─ 예
   └─ 수 분의 쓰기 차단 창을 잡을 수 있는가?
      ├─ 예 → 9.1 SCAN 복사 + 쓰기 차단. 이 랩에서 무손실을 실증한 유일한 경로입니다.
      └─ 아니오
         └─ 애플리케이션을 고칠 수 있는가?
            ├─ 예 → 8.3 이중 쓰기 또는 읽기 폴백. 유실 구간이 원천적으로 없습니다.
            └─ 아니오 → 8.2 RIOT live 또는 8.4 프록시 미러링.
                        둘 다 일관성을 보장하지 않으므로 컷오버 전 전수 대조가 필수입니다.
```

> 8.2·8.4를 고르더라도 **컷오버 다운타임이 0이 되는 건 아닙니다.** 연결 문자열을 바꾼 배포가 롤아웃되는 시간은 남습니다.
> 다만 그 시간은 데이터 크기와 무관하므로 215만 키든 2천만 키든 동일합니다. 복사 패스 시간이 데이터에 비례해 늘어나는 것과 다릅니다.

---

## 9. 권장 절차

[4.6절](#46-우선순위--순서)의 실행 순서를 구체적인 명령 단위로 편 것입니다.

### 9.1 쓰기 차단 창을 확보할 수 있다면 (가장 단순하고 검증됨)

이 랩에서 무손실을 실증한 절차입니다.

1. **애플리케이션 명령어를 감사합니다.** ([3절](#3-클라이언트sdk-확인사항))
   TIER 1이 있으면 여기서 코드 수정이 선행돼야 하고, TIER 2 결과가 다음 단계의 정책 선택을 결정합니다.
2. **AMR을 `EnterpriseCluster`로 생성**하고 액세스 키 인증을 켭니다. ([2절](#2-acr과-amr은-무엇이-다른가))
3. 서비스를 그대로 둔 채 **복사를 1~2회 돌립니다.** 대부분의 데이터가 미리 넘어갑니다.
4. **애플리케이션의 Redis 쓰기를 멈춥니다.** (배포 일시 중지, 쓰기 경로 차단, 또는 읽기 전용 모드)
5. **최종 복사 패스를 돌립니다.** ← 이 구간이 실제 다운타임입니다.
   이 랩의 실측값은 3.77GB / 215만 키에 약 111초 (같은 리전 VM). 데이터 크기에 따라 달라집니다.
6. 연결 문자열을 AMR로 바꾸고 애플리케이션을 재시작합니다. **포트가 6380 → 10000으로 바뀝니다.**
7. 검증합니다. 키 개수만 보지 말고 **TTL과 값까지** 확인하세요. ([`verify_migration.py`](migration-lab/verify_migration.py))
8. 문제가 없으면 ACR을 삭제합니다.

다운타임을 미리 계산하려면 **자기 데이터로 5단계만 먼저 재 보세요.** 키 개수에 거의 선형으로 비례합니다.

### 9.2 쓰기를 멈출 수 없다면: 애플리케이션 이중 쓰기

> **이 항목은 이 랩에서 검증하지 않았습니다.** 설계 지침으로만 읽어 주세요.
> 이중 쓰기 말고 다른 선택지도 있습니다 — [8절](#8-실시간-마이그레이션-전략--replicaof는-왜-안-되는가)에서
> RIOT 라이브 복제, 읽기 폴백, 프록시 미러링, 캐시 재수화를 비교했습니다.

복사 방식으로는 다운타임을 최종 패스 시간(이 랩 실측 약 111초 / 3.77GB / 215만 키) 아래로 내릴 수 없습니다.
더 줄이려면 애플리케이션이 도와야 합니다.

1. 애플리케이션을 **ACR과 AMR 양쪽에 쓰도록** 배포합니다. 읽기는 아직 ACR에서만 합니다.
   AMR 쓰기 실패는 삼켜서 서비스에 영향이 없게 합니다.
2. 이중 쓰기가 도는 상태에서 **과거 데이터를 복사**합니다. 이 시점부터의 신규 쓰기는 이미 양쪽에 들어가므로,
   [6.2절](#62-그런데-복사-중-들어온-쓰기의-4847가-사라집니다)의 유실 구간이 사라집니다.
3. 복사 후 검증합니다.
4. **읽기를 AMR로 전환**합니다. 다운타임은 배포 롤아웃 시간뿐입니다.
5. 안정화되면 ACR 쓰기를 제거하고 ACR을 삭제합니다.

주의할 점:

- `INCR`, `LPUSH`, `SETNX` 같은 **읽기-수정-쓰기 성격의 명령은 이중 쓰기로 정합성이 깨질 수 있습니다.**
  카운터나 큐로 Redis를 쓰고 있다면 해당 키만 따로 처리해야 합니다. 순수 캐시 용도라면 문제되지 않습니다.
- TTL도 양쪽에 동일하게 걸어야 합니다.
- 2단계의 복사는 `RESTORE ... REPLACE`를 쓰므로, 이중 쓰기로 이미 들어간 **최신 값을 과거 값으로 덮어쓸 수 있습니다.**
  복사를 먼저 끝내고 이중 쓰기를 켜거나, `RESTORE`에서 `REPLACE`를 빼는 쪽을 검토하세요.

### 9.3 Azure 마이그레이션 도구를 쓸 경우

호스트 이름을 유지하고 싶고 [7절](#7-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다)의 제약을 모두 받아들일 수 있을 때만 고려하세요.
이 경우에도 **데이터는 9.1 또는 9.2로 별도 이관해야 합니다.**

---

## 10. 용량 산정 — 두 번 속습니다

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

## 11. 부록: 테스트 환경과 재현

### 11.1 테스트 환경

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

#### 명령 호환성 랩 (2.4절·3.6절)

정책별 명령 호환성과 관리 명령 비교는 **위와 별개의 인스턴스**에서 측정했습니다.
`clusteringPolicy`는 생성 후 변경할 수 없어 정책마다 클러스터를 따로 만들어야 하고,
데이터 크기가 결과에 영향을 주지 않는 측정이라 최소 SKU를 썼습니다.

| 인스턴스 | 구성 | 용도 |
|---|---|---|
| `amr-lab-ent` | AMR **Balanced_B0**, Redis 7.4.3, `EnterpriseCluster` | 정책 × 클라이언트 매트릭스 |
| `amr-lab-oss` | AMR **Balanced_B0**, Redis 7.4.3, `OSSCluster` | 정책 × 클라이언트 매트릭스 |
| `acr-lab-c0` | ACR **Basic C0**, Redis 6.0.14 | 관리 명령·키스페이스 알림의 ACR 쪽 대조군 |

- 리전 Korea Central, 클라이언트 redis-py 7.0.1, 로컬에서 실행 (**왕복 지연 약 180ms**)
- 명령 31개 × 클라이언트 2종 × 키 배치 2종, **각 3회 반복** — 기록된 모든 결과가 3회 일치
- 왕복 지연이 큰 환경이라 픽스처 준비는 파이프라인으로 묶었습니다. 순차 전송 시 38분이 걸립니다.
- `acr-lab-c0`가 **Basic**이라는 점은 키스페이스 알림 해석에서 중요합니다.
  `notify-keyspace-events`는 Standard/Premium 전용 설정이라 Basic에서는 관리 평면도 거부합니다
  ([3.4절](#34-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)).

### 11.2 재현하기

[`migration-lab/`](migration-lab/)에 스크립트와 결과 JSON이 있습니다. 실행 방법은
[`migration-lab/README.md`](migration-lab/README.md)를 보세요.

| 파일 | 내용 |
|---|---|
| [`audit_commands.sh`](migration-lab/audit_commands.sh) | 3절 명령어 감사 정적 스캐너 (TIER 1 적중 시 종료 코드 1) |
| [`policy_matrix_test.py`](migration-lab/policy_matrix_test.py) | 2.4절 정책 × 클라이언트 매트릭스 재현 스크립트 (`--repeat`로 반복 검증) |
| [`results/policy-matrix-ent.json`](migration-lab/results/policy-matrix-ent.json) | `EnterpriseCluster` 원본 결과 (명령별 성공/실패와 예외 타입) |
| [`results/policy-matrix-oss.json`](migration-lab/results/policy-matrix-oss.json) | `OSSCluster` 원본 결과 |
| [`results/clustering-policy.json`](migration-lab/results/clustering-policy.json) | OSSCluster vs EnterpriseCluster 실측 |
| [`results/path-a-rdb.json`](migration-lab/results/path-a-rdb.json) | Export 성공 / Import 실패와 근본 원인 |
| [`results/path-b-scan-copy.json`](migration-lab/results/path-b-scan-copy.json) | 단일 패스 복사와 48.47% 유실 |
| [`results/path-b-repeat-pass.json`](migration-lab/results/path-b-repeat-pass.json) | 반복 패스 수렴과 다운타임 하한 111초 (3.77GB / 215만 키) |
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

## 12. 이 문서가 측정하지 않은 것

숫자를 추정으로 채우지 않았습니다. 다음은 미측정입니다.

- **RDB Import 소요 시간** — 환경 정책으로 Import 자체가 막혀 측정 불가 ([5.2절](#52-import는-이-환경에서-실패했습니다))
- **이중 쓰기 방식의 실제 다운타임** — 설계 지침으로만 기술 ([9.2절](#92-쓰기를-멈출-수-없다면-애플리케이션-이중-쓰기))
- **8절의 실시간 전략 전부** — RIOT 라이브 복제, 프록시 미러링, 읽기 폴백, 캐시 재수화는
  **한 건도 실행하지 않았습니다.** 문서 근거와 설계만 정리한 것입니다. 특히:
  - RIOT `--mode live`의 실제 유실률과 `riot compare` 결과
  - `notify-keyspace-events=KEA`를 켰을 때 소스 ACR의 CPU·서버 부하 증가폭
  - Envoy Redis 프록시 미러링의 실동작과 실패 시 관측 방법
- **`audit_commands.sh`의 실제 코드베이스 적중률** — 이 저장소의 샘플과 인위적 위반 파일로만 시험했습니다.
  실전 코드베이스의 오탐·미탐 비율은 모릅니다
- **`WAIT` 명령의 AMR 지원 여부** — 이중 쓰기 절차에서 타깃 쓰기 확정을 기다리려면 필요하지만 확인하지 않았습니다
- **Azure 마이그레이션 도구의 실동작** — 프라이빗 엔드포인트 환경이라 대상 밖 ([7절](#7-경로-c-azure-마이그레이션-도구는-데이터를-옮기지-않는다))
- **비용 비교** — SKU별 단가는 리전·계약·시점에 따라 달라집니다. [Azure 가격 계산기](https://azure.microsoft.com/pricing/calculator/)로 직접 확인하세요.
- **Entra ID 인증 경로** — 이 랩은 액세스 키만 사용했습니다.
- **마이그레이션 중 소스 축출량** — `volatile-lru` 기본값과 `OutOfMemoryError` 발생은 확인했지만,
  축출된 키 수를 재현 가능한 형태로 기록하지 못했습니다 ([10절](#10-용량-산정--두-번-속습니다))
- **B5 외 SKU의 메모리 예약 비율** — 20% 예약은 Balanced_B5 한 SKU에서만 역산했습니다
- **`EnterpriseCluster`의 크로스 슬롯 제약** — 허용 목록 6개와 목록 밖 24개를 실측했습니다
  ([2.5절](#25-enterprisecluster도-크로스-슬롯-제약이-남습니다)). 다만 Redis 명령 전체를 훑은 것은 아니라
  **여기 없는 다중 키 명령은 여전히 직접 확인해야 합니다.**
- **`OSSCluster`에서 `MOVED`가 커넥션 단위로 갈리는 원인** — 현상은 반복 측정으로 확인했지만
  ([2.4절](#24-실측-정책--클라이언트-조합별-명령-호환성)), 프록시·엔드포인트 내부 구조는 관측 범위 밖입니다.
  Microsoft 문서에서 설명을 찾지 못했습니다
- **샤드가 여러 개인 `OSSCluster`** — 이 랩의 B0는 **샤드 1개**로 슬롯 0–16383을 전부 갖습니다.
  샤드를 늘렸을 때 위 현상이 어떻게 달라지는지는 모릅니다
- **키스페이스 알림의 문서–실측 불일치가 언제까지 유지되는지** — AMR에서 기본값 `AKE`로
  동작하는 것을 확인했지만 ([3.4절](#34-tier-1--정책과-무관하게-반드시-고쳐야-하는-것)),
  **문서상 미지원이라 예고 없이 바뀔 수 있습니다.** 지속성은 보장할 수 없습니다
- **ACR Standard/Premium의 키스페이스 알림 활성화** — 대조군이 Basic C0라 관리 평면에서 거부됐습니다.
  Standard/Premium에서 `az redis update`로 켜지는 것까지는 확인하지 못했습니다
- **`NoCluster` 정책** — 25GB 이하 비샤딩 옵션으로, 이 랩에서는 생성·테스트하지 않았습니다

---

## 13. 참고 자료

**Azure 마이그레이션**

- [Migration options — Basic/Standard/Premium → Azure Managed Redis](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options)
- [Self-service migration](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service)
- [Redis migration agent skill (GitHub)](https://github.com/AzureManagedRedis/amr-migration-skill)

**제약과 아키텍처 (2·3절·8절 근거)**

- [Azure Managed Redis architecture — 클러스터링 정책과 예약 메모리](https://learn.microsoft.com/azure/redis/architecture)
- [Redis commands not supported in Azure Cache for Redis](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis) — `REPLICAOF`/`PSYNC`/`REPLCONF` 차단 근거
- [Azure Cache for Redis 메모리 정책](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#memory-policies)
- [Redis Enterprise 명령 호환성](https://redis.io/docs/latest/operate/rs/references/compatibility/commands/) — 타깃 측 복제 명령 미지원 근거
- [Redis 키스페이스 알림](https://redis.io/docs/latest/develop/use/keyspace-notifications/)
- [Redis Cluster 명세 — 해시 태그](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

**실시간 복제 도구 (8절, 모두 미검증)**

- [RIOT — Redis Input/Output Tools](https://redis.github.io/riot/) · [`riot replicate`](https://redis.github.io/riot/#_replicate)
- [Envoy Redis proxy — `request_mirror_policy`](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/network/redis_proxy/v3/redis_proxy.proto)

**Redis 명령**

- [`SCAN`](https://redis.io/docs/latest/commands/scan/) · [`DUMP`](https://redis.io/docs/latest/commands/dump/) · [`RESTORE`](https://redis.io/docs/latest/commands/restore/)
