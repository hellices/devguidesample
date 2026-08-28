# Azure Cache for Redis → Azure Managed Redis 마이그레이션

> Korea Central에 실제 리소스를 만들어 **3.77GB / 215만 키** 규모로 측정했다 (2026-08-27 KST).
> 이 문서는 **판단에 필요한 것만** 담고, 상세는 세 개의 문서로 나눠 두었다.
> 스크립트와 원본 JSON은 [`migration-lab/`](migration-lab/)에 있다.

---

## 핵심 요약

ACR과 AMR은 이름이 비슷하고 같은 Redis API를 말하지만 **다른 소프트웨어**다.
ACR(Basic/Standard/Premium)은 OSS Redis 위에, AMR은 Redis Enterprise 스택 위에 올라가 있다.
이 마이그레이션에서 겪는 일의 대부분이 이 한 문장에서 나온다.

경로를 고르는 기준은 공식 문서의 **Option 1(자체 마이그레이션)** 이고 이 문서도 그 전제로 썼다.
Option 2인 Azure 마이그레이션 도구는 이름에서 기대하게 되는 것과 달리 **데이터를 옮기지 않는다** —
호스트 이름만 넘긴다. 어떤 조건에서 쓸 만한지는 [4절](#4-경로-선택--option-1이-기본)에 있다.

그래서 먼저 정할 것이 셋이다. 앞의 결정이 뒤를 제약하므로 순서도 이대로다.

1. **`clusteringPolicy`** — 한 번 `OSSCluster`/`EnterpriseCluster`로 만들면 DB를 지워야 바꾼다 ([2절](#2-무엇을-고를-것인가--clusteringpolicy))
2. **정합성 전략** — 쓰기 차단 창을 잡을 수 있는가 ([5절](#5-우선순위와-순서))
3. **용량** — ACR 크기를 AMR에 1:1로 매핑하면 모자란다 ([이관 경로와 실측 5절 상세](migration-guide/03-migration-paths.md#5-용량-산정--두-번의-착시))

### 실측 결론

숫자를 먼저 보면 이 마이그레이션의 모양이 대강 잡힌다.
**쓰기를 멈추면 2분 안에 무손실로 끝나고, 멈추지 않으면 절반가량을 잃는다.**
그 사이의 중간 지대가 생각보다 좁다는 것이 아래 표의 요지다.

| 측정 | 값 | 조건 |
|---|---|---|
| 최종 복사 패스 다운타임 | 약 **111초** | 쓰기 차단 후. 키 개수에 거의 선형 |
| 쓰기 차단 없이 1회 복사 | **48.47% 유실** | **키 개수 검증은 통과** |
| 복사 2회 반복 후 | 20.21% 유실 | 반복만으로는 0에 수렴하지 않음 |
| AMR `usedmemory` | 표기의 **1.98배** | HA 복제본이 합산됨 |
| AMR 유효 메모리 | 표기의 약 **0.8배** | 20% 예약 |

48.47%라는 숫자보다 그 옆 칸을 더 눈여겨봐야 한다. **키 개수 검증은 통과했다.**
유실이 조용히 지나간다는 것이 이 문서에서 가져갈 것이 하나뿐이라면 그 하나다.
측정 방법과 원본 데이터는 [이관 경로와 실측](migration-guide/03-migration-paths.md)에 있다.

### 반드시 알고 갈 차이

다른 소프트웨어라는 사실이 실무에서 어떤 모습으로 나타나는지를 한 화면에 모았다.
**첫 줄이 나머지를 거의 다 설명한다** — AMR은 SKU와 무관하게 항상 클러스터이고,
그래서 클러스터를 켜 본 적 없는 워크로드도 크로스 슬롯 제약을 받게 된다.

| | 결론 | 상세 |
|---|---|---|
| 클러스터 | AMR은 **SKU 무관 항상 클러스터**. 안 쓰던 워크로드도 크로스 슬롯 제약을 받음 | [ACR과 AMR의 차이 1절](migration-guide/01-differences.md#1-기능-차이--엔진-샤딩-명령어-클라이언트) |
| 다중 키 명령 | `EnterpriseCluster`에서도 **6개만** 허용 (`DEL` `MSET` `MGET` `EXISTS` `UNLINK` `TOUCH`) | [ACR과 AMR의 차이 2.5절](migration-guide/01-differences.md#25-enterprisecluster에-남는-크로스-슬롯-제약) |
| 데이터베이스 | **0번 하나뿐.** `SELECT`/`SWAPDB`와 연결 문자열의 DB 번호를 걷어내야 함 | [클라이언트·SDK 확인사항 4절](migration-guide/02-client-audit.md#4-tier-1--정책과-무관하게-반드시-고쳐야-하는-것) |
| 연결 | 포트 **10000**, 호스트명 `<name>.<region>.redis.azure.net` | [클라이언트·SDK 확인사항 1절](migration-guide/02-client-audit.md#1-연결-설정--무조건-바뀌는-것) |
| TLS | AMR은 **생성 시 TLS/비TLS 중 하나만** 선택. ACR처럼 혼용 불가 | [ACR과 AMR의 차이 1절](migration-guide/01-differences.md#1-기능-차이--엔진-샤딩-명령어-클라이언트) |
| 네트워크 | **VNet 주입·IP 방화벽 규칙 미지원.** Private Link로 전환 필요 | [ACR과 AMR의 차이 1절](migration-guide/01-differences.md#1-기능-차이--엔진-샤딩-명령어-클라이언트) |
| 복제 | `REPLICAOF`는 **소스·타깃 양쪽에서 차단**. 물리 복제 기반 전략은 불가 | [이관 경로와 실측 4.1절](migration-guide/03-migration-paths.md#41-가장-먼저-떠오르는-방법-그리고-왜-막히는가) |

마지막 줄이 계획을 가장 크게 흔든다. "복제를 걸어 두고 따라잡으면 무중단으로 되지 않나"는
가장 자연스러운 발상인데, 이 구간에서는 그 길이 아예 없다. 왜 없는지는
[이관 경로와 실측 4.1절](migration-guide/03-migration-paths.md#41-가장-먼저-떠오르는-방법-그리고-왜-막히는가)에서 양쪽을 다 확인했다.

---

## 1. 이 문서 묶음과 공식 가이드

이 문서는 Microsoft 공식 마이그레이션 가이드를 대체하지 않는다. **먼저 읽어야 할 것은 공식 문서이고**,
이 묶음은 거기에 적히지 않은 것 — 실제로 재 봤을 때의 숫자, 정책·클라이언트 조합별 실패 방식,
막다른 길로 확인된 접근 — 을 채우는 보조 자료다.

공식 가이드는 3단계이고, 이 묶음이 그대로 대응한다.

| 공식 가이드 | 이 묶음 |
|---|---|
| ① [Understand the differences](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-understand) | [ACR과 AMR의 차이](migration-guide/01-differences.md) · [클라이언트·SDK 확인사항](migration-guide/02-client-audit.md) |
| ② [**Migration options**](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options) — **기준 문서** | 이 문서 [4절](#4-경로-선택--option-1이-기본) |
| ③ [Plan execution — self-service](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service) / [with tooling](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-with-tooling) | 이 문서 [6절](#6-권장-절차) · [이관 경로와 실측](migration-guide/03-migration-paths.md) |

### 상세 문서

판단에 필요한 것만 이 문서에 두고, 근거와 절차는 세 문서로 내려 두었다.
세 문서는 순서대로 읽어도 되지만, 대개는 지금 하고 있는 일에 맞는 하나만 펼치게 된다.

| 문서 | 담긴 것 | 언제 보나 |
|---|---|---|
| [ACR과 AMR의 차이](migration-guide/01-differences.md) | 기능·명령어·클라이언트 차이, `clusteringPolicy` 세 가지, **정책 × 클라이언트 실측 호환성 매트릭스**, 정책 변경 규칙 | 정책을 고를 때 |
| [클라이언트·SDK 확인사항](migration-guide/02-client-audit.md) | TIER 1~4 체크리스트, SDK별 확인 포인트, 명령어 감사 스크립트, 정적 스캔의 한계 | 코드를 감사할 때 |
| [이관 경로와 실측](migration-guide/03-migration-paths.md) | 경로 A/B/C, 실시간 전략 비교, 용량 산정, 테스트 환경과 재현, 측정하지 않은 것 | 실제로 옮길 때 |

### 목적별 읽기 경로

- **아직 고르는 중이다** → 이 문서 [핵심 요약](#핵심-요약) → [2절](#2-무엇을-고를-것인가--clusteringpolicy) → [ACR과 AMR의 차이](migration-guide/01-differences.md)
- **코드를 감사해야 한다** → [클라이언트·SDK 확인사항](migration-guide/02-client-audit.md) 전체
- **날짜를 잡고 실행한다** → 이 문서 [5절](#5-우선순위와-순서) → [6절](#6-권장-절차) → [이관 경로와 실측](migration-guide/03-migration-paths.md)
- **왜 무중단이 안 되는지 설명해야 한다** → 이 문서 [3절](#3-클라이언트-무수정-가능-범위와-다운타임-하한) → [이관 경로와 실측 4절 상세](migration-guide/03-migration-paths.md#4-실시간-마이그레이션-전략--replicaof는-왜-안-되는가)

> Microsoft는 마이그레이션 질문에 답하고 환경에 맞는 계획을 세워 주는 **마이그레이션 에이전트 스킬**도 함께 안내한다.
> 공식 문서 각 페이지 상단의 "Redis migration agent skill" 링크를 참고하면 된다.

---

## 2. 무엇을 고를 것인가 — `clusteringPolicy`

AMR을 만들 때 정해야 하는 값이고, **한 번 `OSSCluster`나 `EnterpriseCluster`로 만들면 DB를 지우지 않는 한 되돌릴 수 없다**
([ACR과 AMR의 차이 2.6절](migration-guide/01-differences.md#26-정책-변경의-방향--nocluster에서-나오는-길-하나)). 무엇을 고를지는 취향이 아니라
**애플리케이션이 어떤 명령을 쓰는지, 어떤 클라이언트를 쓰는지** 두 가지로 결정된다.

```
                     허용 목록 6개 밖의 다중 키 명령을 쓰는가?
                     (SUNION, ZUNIONSTORE, RENAME, RPOPLPUSH,
                      크로스 슬롯 MULTI/Lua 등 → 확인사항 5절)
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

위 분기를 조건별로 편 것이 아래 표다. 자기 경우에 해당하는 한 줄만 보면 된다.

| 조건 | 정책 | 클라이언트 작업 |
|---|---|---|
| 다중 키 명령을 거의 안 쓰고, 클러스터 클라이언트 사용 가능 | `OSSCluster` | 클러스터 전용 클라이언트로 교체 ([클라이언트·SDK 확인사항 2절](migration-guide/02-client-audit.md#2-sdk별-확인-포인트)) |
| `MGET`/`MSET`/`DEL`/`EXISTS`/`UNLINK`/`TOUCH`를 여러 키로 사용 | `EnterpriseCluster` | 대체로 그대로. 포트·TLS·DB 번호만 |
| 허용 목록 밖 명령을 쓰지만 해시 태그 적용 가능 | 태그 적용 후 위 둘 중 하나 | 키 이름이 바뀌므로 **이관보다 배포가 먼저** |
| 허용 목록 밖 명령을 쓰고 태그도 못 붙이며 25GB 이하 | `NoCluster` | 그대로. 대신 성능이 가장 낮고 스케일 업이 막힘 |
| 허용 목록 밖 명령을 쓰고 태그도 못 붙이며 25GB 초과 | 정책으로는 해결 안 됨 | 명령을 클라이언트 로직으로 대체 |

**첫 칸을 채우는 방법이 [클라이언트·SDK 확인사항 3절](migration-guide/02-client-audit.md#3-명령어-감사--자동-스캔)의 명령어 감사다.**
스크립트가 TIER 2(허용 목록 밖)와 TIER 3(허용 목록 6개)을 세어 주므로, 그 두 숫자가 위 표의 입력값이 된다.
정책별로 무엇이 통과하고 무엇이 막히는지는 [ACR과 AMR의 차이 2.4절](migration-guide/01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)에서 실제로 돌려 봤다.

> **`OSSCluster`를 고른다면 클라이언트 교체는 선택이 아니라 필수다.**
> 비클러스터 클라이언트로도 연결은 되고, **샤드가 하나면** `SET`/`GET`까지 동작해서 괜찮아 보인다.
> 그런데 다중 키 명령은 그 구성에서도 **커넥션 단위로 갈려서** 풀의 일부만 계속 실패하고,
> 샤드가 둘 이상이면 단일 키 명령까지 `MOVED`로 실패한다
> (실측: [ACR과 AMR의 차이 2.4절](migration-guide/01-differences.md#24-실측-정책--클라이언트-조합별-명령-호환성)).
> 스모크 테스트로는 잡히지 않는 실패 방식이다.

> **RediSearch를 쓸 계획이면 정책은 이미 정해져 있다.**
> `EnterpriseCluster` + `NoEviction`이 전제 조건이고, **모듈은 생성 시점에만 추가할 수 있다.**

---

## 3. 클라이언트 무수정 가능 범위와 다운타임 하한

클라이언트를 안 고치는 것과 다운타임을 없애는 것은 거의 항상 함께 요구받는다.
결론부터 적으면 **앞쪽은 조건부로 가능하고, 뒤쪽은 Azure가 주는 기능만으로는 성립하지 않는다.**

**클라이언트 무수정**부터 본다. AMR 데이터베이스를 `EnterpriseCluster` 정책으로 만들면
프록시가 클러스터를 감춰 주므로 기존 비클러스터 클라이언트가 그대로 붙는다. 조건은 시점이다 —
**생성할 때** 정해야 하고, 나중에 바꾸려면 DB를 지워야 한다
([ACR과 AMR의 차이 2절](migration-guide/01-differences.md#2-왜-다른가--제품-계보와-클러스터-정책)).

그런데 정책으로 덮이지 않는 것이 셋 남는다.

- **다중 데이터베이스**: AMR이 주는 데이터베이스는 0번 하나뿐이라 프록시가 대신해 줄 것이 없다.
  어떤 정책을 고르든 코드를 고쳐야 한다.
- **허용 목록 6개 밖의 다중 키 명령**: `EnterpriseCluster`에서도 그대로 실패한다.
  프록시가 감춰 주는 것은 엔드포인트이고, 슬롯 경계는 그 뒤에 그대로 남아 있다.
- **키스페이스 알림**: 문서는 미지원이라고 하는데 이 랩에서는 동작했다.
  동작한다는 것과 지원된다는 것이 갈리는 자리라 판단이 한 겹 더 필요하다.

셋 다 정책 선택 이전의 문제이므로, 정책을 고르기 전에 코드에 이것들이 있는지부터 확인해야 한다.
그 확인 목록이 [클라이언트·SDK 확인사항](migration-guide/02-client-audit.md)이다.

**다운타임 0**은 사정이 다르다. 무중단을 만들어 줄 수 있었을 방법이 둘 있는데, 둘 다 막혀 있다.

- **Azure 마이그레이션 도구**: 이름 때문에 기대하게 되지만 엔드포인트만 넘기고
  **데이터를 옮기지 않는다**
  ([이관 경로와 실측 3절](migration-guide/03-migration-paths.md#3-경로-c-데이터를-옮기지-않는-azure-마이그레이션-도구)).
- **`REPLICAOF` 기반 복제**: 타깃이 소스를 따라오게 하는 정석적인 방법인데,
  소스와 타깃 **양쪽에서** 막혀 있어 시작조차 못 한다
  ([이관 경로와 실측 4.1절](migration-guide/03-migration-paths.md#41-가장-먼저-떠오르는-방법-그리고-왜-막히는가)).

한쪽만 막혀 있다면 우회할 여지가 있겠지만 양쪽이다.
물리적 복제를 전제로 한 무중단 계획은 이 지점에서 전부 지워진다.

남는 것은 다운타임을 없애는 쪽이 아니라 **줄이는 쪽**이다. 이 랩 규모(3.77GB / 215만 키)에서
복사 방식의 하한은 약 111초로 측정됐다
([이관 경로와 실측 2.3절](migration-guide/03-migration-paths.md#23-반복-복사로-유실이-얼마나-줄어드나)).
그보다 짧게 하려면 Azure 바깥으로 — 논리적 복제나 애플리케이션 계층으로 — 내려가야 한다
([이관 경로와 실측 4절](migration-guide/03-migration-paths.md#4-실시간-마이그레이션-전략--replicaof는-왜-안-되는가)).

한 가지만 덧붙이면, 복사가 도는 동안 소스에 들어온 쓰기는 그대로 두면 타깃에 반영되지 않는다.
이 랩에서는 단일 패스 기준 48.47%가 그렇게 빠졌고, **키 개수 비교로는 드러나지 않았다**
([이관 경로와 실측 2.2절](migration-guide/03-migration-paths.md#22-복사-중-들어온-쓰기의-4847-유실)).

여기까지가 제약이다. 그 제약 안에서 어느 경로로 옮길지가 다음 절이다.

---

## 4. 경로 선택 — Option 1이 기본

경로를 고르는 기준 문서는 [Migration options](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options)이고,
**Option 1(자체 마이그레이션)이 권장**이다. 문서가 드는 이유는 세 가지다.

- **Full control**: 전환 시점을 직접 정하고, 전환 전에 새 인스턴스를 테스트할 수 있다.
  **여러 앱이 공유하는 Redis라면 앱 단위로 하나씩** 옮길 수 있다.
- **Minimal downtime**: **이중 쓰기(dual-write)나 내보내기/가져오기** 같은 동기화 전략으로
  두 캐시를 병행 운영하다 최소 중단으로 전환한다.
- **Independent validation**: 기존 캐시를 지우기 전에 새 인스턴스가 제대로 동작하는지 검증할 수 있다.

세 이유가 공통으로 가리키는 것은 **통제권**이다. 언제 넘길지, 무엇부터 넘길지, 넘기기 전에 확인할지를
직접 정할 수 있다는 것이 Option 1이 주는 것이다. 그 통제권을 실제로 행사하는 방법이 아래 세 경로이고,
이 랩이 측정한 것은 그중 경로 B다.

| 경로 | 공식 문서 대응 | 한 줄 |
|---|---|---|
| [경로 A](migration-guide/03-migration-paths.md#1-경로-a-rdb-export--import) RDB Export/Import | Option 1의 export/import | 원본이 **Premium일 때만** 가능 |
| [경로 B](migration-guide/03-migration-paths.md#2-경로-b-scan--dumprestore-프로그래매틱-복사) SCAN + DUMP/RESTORE | Option 1의 데이터 이관 | 전 SKU 가능. **이 랩이 측정한 경로** |
| [경로 C](migration-guide/03-migration-paths.md#3-경로-c-데이터를-옮기지-않는-azure-마이그레이션-도구) 마이그레이션 도구 | Option 2 (preview) | **데이터를 옮기지 않음.** 엔드포인트 전환만 |
| [이관 경로와 실측 4절](migration-guide/03-migration-paths.md#4-실시간-마이그레이션-전략--replicaof는-왜-안-되는가) 실시간 복제 | (해당 없음) | 공식 경로가 아님. 막힌 이유를 정리한 절 |

경로 C가 이 표에서 가장 자주 오해받는 자리다. 이름과 달리 데이터는 그대로 두고 호스트 이름만 옮기므로,
이 경로를 고르더라도 **데이터 이관은 A나 B로 따로 해야 한다.**

**Option 2는 아래를 전부 만족할 때만** 검토한다. 하나라도 걸리면 Option 1이다.

- 프라이빗 엔드포인트·VNet 주입·지역 복제를 쓰지 않음
- 전환 시점을 직접 고르지 않아도 됨
- 그 Redis에 붙은 **모든** 애플리케이션이 동시에 넘어가도 됨
- 데이터는 별도로 옮긴다는 것을 이해함

> 실무에서는 첫 줄에서 대부분 걸린다. 프로덕션 Redis가 프라이빗 엔드포인트를 안 쓰는 경우가 드물다.

> 공식 문서가 "minimal downtime"의 수단으로 **dual-write를 먼저 든다.** 애플리케이션에 손을 댈 수 있다면
> 이 방법이 이 문서의 111초보다 짧다 ([6.2절](#62-쓰기를-멈출-수-없는-경우--애플리케이션-이중-쓰기)).

---

## 5. 우선순위와 순서

마이그레이션에서는 **모든 것을 동시에 최적화할 수 없다.**
다운타임을 줄이면 정합성이 흔들리고, 정합성을 지키면 다운타임이 늘어난다. 그래서 순위가 필요하다.

### 5.1 우선순위의 기준 — 되돌릴 수 있는가

순위를 매기는 기준은 여러 가지일 수 있다 — 영향 범위, 발생 확률, 복구 비용, 눈에 띄는 정도.
여기서는 **되돌릴 수 있는가** 하나로 줄였다. 마이그레이션은 창이 정해져 있고
그 안에서는 복구 가능성이 나머지 기준을 전부 압도하기 때문이다.

| 순위 | 관심사 | 실패하면 | 되돌릴 수 있나 | 어떻게 드러나나 |
|---|---|---|---|---|
| **P0** | **데이터 정합성** | 쓰기 유실 | **불가능** — 소스를 지우면 끝 | **조용히.** 키 개수 검증은 통과 |
| **P1** | 호환성 (정책·명령어) | 애플리케이션 실패 | 가능하지만 비쌈 — DB 재생성 + 재이관 | 대부분 시끄럽게 (예외·`CROSSSLOT`). **단 키스페이스 알림은 조용함** |
| **P2** | 용량 | 축출 시작 | 가능 — SKU 상향 | 반쯤 조용히 (지표로만 보임) |
| **P3** | 다운타임 | 서비스 중단 | 가능 — 창을 늘리면 됨 | 즉시, 명확하게 |

**데이터 정합성이 1순위인 이유는 두 가지다.**

1. **유일하게 되돌릴 수 없다.** 나머지 셋은 시간과 비용으로 복구된다. 정책을 잘못 골랐으면 DB를 다시 만들고,
   용량이 모자라면 SKU를 올리고, 다운타임이 길면 다음 창을 잡으면 된다.
   반면 복사되지 않은 쓰기는 소스를 지우고 나면 되찾을 방법이 없다.
2. **유일하게 조용하다.** 호환성 문제는 예외로 터지고, 용량은 지표에 뜨고, 다운타임은 누구나 안다.
   정합성은 신호 없이 지나간다. 이 랩에서 48.47%를 잃은 마이그레이션도 키 개수 검증은 통과했다.

> 트레이드오프가 생기면 정합성 쪽을 택하는 것을 기본으로 삼는다.
> "다운타임 111초(실측: 3.77GB / 215만 키)" vs "다운타임 0초 + 유실 20%"의 선택이라면 111초가 기본값이다.
> 유실을 감수하겠다는 결정은 **데이터 성격을 확인한 뒤 명시적으로** 내려야 한다 (순수 캐시라면 정당한 선택이다).

관심사별 상세 판단 기준은 [이관 경로와 실측](migration-guide/03-migration-paths.md)에 있다.

### 5.2 우선순위 ≠ 순서

우선순위는 **"충돌하면 무엇을 지키나"**, 순서는 **"무엇을 먼저 하나"** 다. 두 축이 다르다.
정합성이 P0이지만, 시간축에서는 감사(P1)가 가장 앞에 온다 — 그 결과가 나머지 전부를 결정하기 때문이다.

```
1. [P1] 명령어 감사        → 코드 수정 필요 여부와 clusteringPolicy가 여기서 정해진다
2. [P1] 해시 태그가 필요하면 애플리케이션 먼저 배포
3. [P2] 용량 산정          → AMR SKU 결정
4. [P1] AMR 생성           → clusteringPolicy 확정. 이후 되돌리려면 DB 재생성
5. [P0] 정합성 전략 확정   → 쓰기 차단 창을 잡을 수 있는가?
6. [P3] 리허설             → 다운타임 실측. 여기서 나온 숫자로 창을 협의
7.      본 이관
8. [P0] 검증               → 키 개수가 아니라 값과 TTL
9.      소스 삭제          → 되돌릴 수 없는 지점. 8이 통과한 뒤에만
```

---

## 6. 권장 절차

[5.2절](#52-우선순위--순서)의 순서를 명령 단위로 편 것이다. **공식 문서의 Option 1을 따른다.**

### 6.1 쓰기 차단 창을 확보할 수 있는 경우 — 가장 단순하고 검증된 절차

이 랩에서 무손실을 실증한 절차다.

1. **애플리케이션 명령어를 감사한다.** ([클라이언트·SDK 확인사항](migration-guide/02-client-audit.md))
   TIER 1이 있으면 여기서 코드 수정이 선행돼야 하고, TIER 2 결과가 다음 단계의 정책 선택을 결정한다.
2. **AMR을 `EnterpriseCluster`로 생성**하고 액세스 키 인증을 켠다. ([2절](#2-무엇을-고를-것인가--clusteringpolicy))
3. 서비스를 그대로 둔 채 **복사를 1~2회 돌린다.** 대부분의 데이터가 미리 넘어간다.
4. **애플리케이션의 Redis 쓰기를 멈춘다.** (배포 일시 중지, 쓰기 경로 차단, 또는 읽기 전용 모드)
5. **최종 복사 패스를 돌린다.** ← 이 구간이 실제 다운타임이다.
   이 랩의 실측값은 3.77GB / 215만 키에 약 111초 (같은 리전 VM). 데이터 크기에 따라 달라진다.
6. 연결 문자열을 AMR로 바꾸고 애플리케이션을 재시작한다. **포트가 6380 → 10000으로 바뀐다.**
7. 검증한다. 키 개수만 보지 말고 **TTL과 값까지** 확인해야 한다. ([`verify_migration.py`](migration-lab/verify_migration.py))
8. 문제가 없으면 ACR을 삭제한다.

다운타임을 미리 계산하려면 **자기 데이터로 5단계만 먼저 재 보면 된다.** 키 개수에 거의 선형으로 비례한다.

### 6.2 쓰기를 멈출 수 없는 경우 — 애플리케이션 이중 쓰기

> **이 항목은 이 랩에서 검증하지 않았다.** 설계 지침으로만 읽어야 한다.
> 이중 쓰기 말고 다른 선택지도 있다 — [이관 경로와 실측 4절](migration-guide/03-migration-paths.md#4-실시간-마이그레이션-전략--replicaof는-왜-안-되는가)에서
> RIOT 라이브 복제, 읽기 폴백, 프록시 미러링, 캐시 재수화를 비교했다.

복사 방식으로는 다운타임을 최종 패스 시간(이 랩 실측 약 111초 / 3.77GB / 215만 키) 아래로 내릴 수 없다.
더 줄이려면 애플리케이션이 도와야 한다.

1. 애플리케이션을 **ACR과 AMR 양쪽에 쓰도록** 배포한다. 읽기는 아직 ACR에서만 한다.
   AMR 쓰기 실패는 삼켜서 서비스에 영향이 없게 한다.
2. 이중 쓰기가 도는 상태에서 **과거 데이터를 복사한다.** 이 시점부터의 신규 쓰기는 이미 양쪽에 들어가므로,
   [이관 경로와 실측 2.2절](migration-guide/03-migration-paths.md#22-복사-중-들어온-쓰기의-4847-유실)의 유실 구간이 사라진다.
3. 복사 후 검증한다.
4. **읽기를 AMR로 전환한다.** 다운타임은 배포 롤아웃 시간뿐이다.
5. 안정화되면 ACR 쓰기를 제거하고 ACR을 삭제한다.

주의할 점은 셋이다.

- `INCR`, `LPUSH`, `SETNX` 같은 **읽기-수정-쓰기 성격의 명령은 이중 쓰기로 정합성이 깨질 수 있다.**
  카운터나 큐로 Redis를 쓰고 있다면 해당 키만 따로 처리해야 한다. 순수 캐시 용도라면 문제되지 않는다.
- TTL도 양쪽에 동일하게 걸어야 한다.
- 2단계의 복사는 `RESTORE ... REPLACE`를 쓰므로, 이중 쓰기로 이미 들어간 **최신 값을 과거 값으로 덮어쓸 수 있다.**
  복사를 먼저 끝내고 이중 쓰기를 켜거나, `RESTORE`에서 `REPLACE`를 빼는 쪽을 검토해야 한다.

### 6.3 Azure 마이그레이션 도구를 쓸 경우

호스트 이름을 유지하고 싶고 [이관 경로와 실측 3절](migration-guide/03-migration-paths.md#3-경로-c-데이터를-옮기지-않는-azure-마이그레이션-도구)의 제약을 모두 받아들일 수 있을 때만 고려한다.
이 경우에도 **데이터는 6.1 또는 6.2로 별도 이관해야 한다.**

---

## 참고

**Azure 공식 마이그레이션 가이드 — 이 문서의 기준**

경로 선택의 기준 문서는 **② Migration options**다. 이 묶음은 그 위에 실측을 얹은 보조 자료다.

- [① Understand the differences](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-understand) — 기능·SKU·클라이언트 차이
- [② **Migration options**](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-options) — **기준 문서.** Option 1(자체 마이그레이션, 권장) / Option 2(도구, preview)
- [③-a Plan execution — self-service](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-self-service) — 경로 A·B의 근거
- [③-b Plan execution — with tooling (preview)](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-with-tooling) — 경로 C의 근거
- [가이드 시작점 — Migrate from Basic, Standard, and Premium tiers](https://learn.microsoft.com/azure/redis/migrate/migrate-basic-standard-premium-overview)
- [Redis migration agent skill (GitHub)](https://github.com/AzureManagedRedis/amr-migration-skill) — 공식 문서가 함께 안내하는 마이그레이션 계획 보조 도구

**정책과 명령 호환성 판단에 직접 필요한 것**

| 무엇을 볼 때 | 문서 |
|---|---|
| 클러스터 정책 세 가지의 동작과 선택 기준 | [AMR architecture — Cluster policies](https://learn.microsoft.com/azure/redis/architecture#cluster-policies) |
| 허용 목록 6개와 `CROSSSLOT` 조건 | [AMR architecture — Multi-key commands](https://learn.microsoft.com/azure/redis/architecture#multi-key-commands) |
| 모듈을 쓸 계획이 있을 때 (RediSearch는 정책을 강제) | [Using Redis modules with AMR](https://learn.microsoft.com/azure/redis/redis-modules) |
| ACR에서 막혀 있는 명령 | [Redis commands not supported in ACR](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#redis-commands-not-supported-in-azure-cache-for-redis) |
| AMR(Redis Enterprise)에서 막혀 있는 명령 | [Redis Enterprise command compatibility](https://redis.io/docs/latest/operate/rs/references/compatibility/commands/) |
| 해시 태그로 슬롯을 모으는 규칙 | [Redis Cluster specification — Hash tags](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags) |

**제품 기능 비교**

- [What is Azure Managed Redis? — 계층별 기능 비교](https://learn.microsoft.com/azure/redis/overview#feature-comparison) — 액티브 지역 복제, 지속성, Flash Optimized, SLA
- [What is Azure Cache for Redis? — 계층별 기능 비교](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-overview#feature-comparison) — Basic/Standard/Premium이 무엇을 못 하는지
- [Azure Cache for Redis 메모리 정책](https://learn.microsoft.com/azure/azure-cache-for-redis/cache-configure#memory-policies)
- [Redis 키스페이스 알림](https://redis.io/docs/latest/develop/use/keyspace-notifications/)

**실시간 복제 도구 (모두 미검증)**

- [RIOT — Redis Input/Output Tools](https://redis.github.io/riot/) · [`riot replicate`](https://redis.github.io/riot/#_replicate)
- [Envoy Redis proxy — `request_mirror_policy`](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/network/redis_proxy/v3/redis_proxy.proto)

**Redis 명령**

- [`SCAN`](https://redis.io/docs/latest/commands/scan/) · [`DUMP`](https://redis.io/docs/latest/commands/dump/) · [`RESTORE`](https://redis.io/docs/latest/commands/restore/)

---

**이 문서가 측정하지 않은 것**과 재현 절차는 [이관 경로와 실측](migration-guide/03-migration-paths.md#7-이-문서가-측정하지-않은-것)에 있다.
