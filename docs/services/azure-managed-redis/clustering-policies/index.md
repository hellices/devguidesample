---
title: "Azure Managed Redis 클러스터링 정책: 연결 방식·명령 제약에 따른 선택"
description: OSS·Enterprise·Non-clustered의 연결 구조와 제약을 비교하고, 정책 선택에서 언어별 연결과 마이그레이션으로 이어지는 출발점입니다.
document_type: guide
services:
- azure-managed-redis
technologies:
- redis
tags:
- design
- operate
status: current
verification_status: verified
sources_checked_at: 2026-10-25
official_sources:
- title: Choose a clustering policy for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/choose-clustering-policy
- title: Azure Managed Redis architecture
  url: https://learn.microsoft.com/azure/redis/architecture
- title: Connection resilience with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-connection
- title: Failover and patching for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/failover
- title: Use Microsoft Entra ID for cache authentication with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/entra-for-authentication
- title: az redisenterprise
  url: https://learn.microsoft.com/cli/azure/redisenterprise
- title: az redisenterprise database
  url: https://learn.microsoft.com/cli/azure/redisenterprise/database
last_verified: 2026-10-25
review_cycle_days: 180
applies_to:
- Azure Managed Redis
related_cases:
- ../cluster-failover-recovery/index.md
related_guides:
- ../migration-from-azure-cache/index.md
- ../eviction-policy-and-ttl/index.md
redirect_from:
- services/azure-managed-redis/cluster-failover-recovery/clustering-policies-and-migration/index.md
---

# Azure Managed Redis 클러스터링 정책: 연결 방식·명령 제약에 따른 선택 { #azure-managed-redis }

Azure Managed Redis를 만들 때는 **OSS**, **Enterprise**, **Non-clustered** 중 하나의 클러스터링 정책을 선택합니다. 이 선택은 제품의 Redis 구현을 바꾸는 것이 아니라, **데이터를 샤딩할지, 클라이언트가 샤드에 직접 연결할지, 프록시를 거칠지**를 정합니다.

이 문서는 정책 선택에 집중합니다. 특정 애플리케이션의 코드나 장애 사례를 먼저 읽을 필요는 없습니다. 구현은 [Node.js](nodejs/index.md) 또는 [Java](java/index.md), 기존 서비스 이전은 [마이그레이션 가이드](../migration-from-azure-cache/index.md)로 이어집니다.

## 클러스터 운영은 Azure가, 샤드 연결 방식은 정책이 결정 { #cluster-policies }

Azure Managed Redis는 Redis Enterprise 기반입니다. 노드(VM)는 여러 Redis 프로세스인 **샤드**를 실행할 수 있고, 샤드는 데이터를 나누어 처리합니다. 작은 구성은 샤드 하나만 사용할 수도 있습니다.

![Azure Managed Redis의 노드 구조. Load Balancer 뒤의 두 VM에서 Redis proxy와 주·복제본 샤드가 동작하고 VM 사이에 복제가 이루어진다.](images/managed-redis-architecture.png)

*출처: [Microsoft Learn — Azure Managed Redis architecture](https://learn.microsoft.com/azure/redis/architecture). HA를 사용하는 샤딩 구성의 개념도입니다.*

**서버 측 클러스터 운영은 모든 정책에서 Azure가 담당합니다.** OSS에서 클라이언트가 관리하는 것은 서버 자체가 아니라, 요청을 어느 샤드로 보낼지 결정하는 **토폴로지 정보**입니다.

[![정책별 연결 모델. OSS는 초기 엔드포인트에서 샤드 위치를 알아낸 뒤 직접 연결하고, Enterprise는 단일 엔드포인트의 프록시를 거치며, Non-clustered는 데이터를 샤딩하지 않는다.](images/clustering-policies.svg)](images/clustering-policies.svg)

*그림의 성능 비교는 일반적 경향이며 측정값이 아닙니다. 실제 처리량과 지연은 SKU와 워크로드에 따라 검증합니다.*

### OSS: 클라이언트가 샤드로 직접 연결

1. 클러스터 클라이언트가 캐시 호스트의 `10000` 포트에 처음 연결합니다.
2. Redis Cluster API로 샤드 위치와 해시 슬롯의 배치를 알아냅니다.
3. 키가 속한 슬롯을 담당하는 샤드의 `85XX` 포트로 요청을 보냅니다.

샤드 위치가 바뀌면 클라이언트는 리디렉션과 토폴로지 갱신을 처리해야 합니다. **발견한 노드 주소나 `85XX` 포트를 코드에 고정하지 않습니다.** 직접 연결하므로 일반적으로 처리량과 지연 측면에서 유리하지만, Redis Cluster API를 지원하는 클라이언트가 필요합니다.

### Enterprise: 단일 엔드포인트 뒤의 프록시가 라우팅

클라이언트는 `10000` 포트의 단일 엔드포인트로 연결합니다. 내부 프록시가 키를 담당하는 샤드로 요청을 전달하므로, 애플리케이션에는 일반 Redis 서버처럼 보입니다.

클러스터를 인식하지 않는 클라이언트와도 연결할 수 있지만 **내부 데이터가 샤딩되지 않는다는 뜻은 아닙니다.** 멀티키 명령 제약이 남아 있고, 단일 프록시 노드의 CPU나 네트워크가 처리량의 병목이 될 수 있습니다.

### Non-clustered: 데이터를 샤딩하지 않음

단일 엔드포인트를 사용하고 데이터를 여러 Redis 프로세스로 나누지 않습니다. 슬롯을 넘는 명령 문제를 피해야 하는 작은 캐시에 검토할 수 있습니다.

Enterprise와 클라이언트 형태는 같지만 데이터 배치는 다릅니다. **25GB 이하**에서만 사용할 수 있고, 여러 샤드의 병렬 처리 이점을 얻지 못합니다. 또한 Non-clustered는 **HA 비활성화와 다른 설정**입니다. 샤딩 여부만으로 복제본이나 장애 조치가 없다고 판단하지 않습니다.

## 정책별 클라이언트·멀티키 명령·크기·변경 제약 { #policy-comparison }

| 확인 항목 | OSS | Enterprise | Non-clustered |
|---|---|---|---|
| 클라이언트 형태 | 클러스터 클라이언트 | 일반 단일 엔드포인트 클라이언트 | 일반 단일 엔드포인트 클라이언트 |
| 요청 라우팅 | 클라이언트가 샤드를 선택 | 서비스 프록시가 샤드를 선택 | 데이터 샤딩 없음 |
| 성능상 고려 | 직접 연결로 일반적으로 높은 처리량 | 프록시 병목 가능 | 멀티샤드 병렬 처리 불가 |
| 멀티키 명령 | 같은 슬롯의 키에 실행 | 대부분 같은 슬롯, 아래 예외 참고 | 슬롯 기반 제한 없음 |
| 클러스터 탐색 명령 | 클라이언트의 샤드 탐색에 사용 | `CLUSTER NODES`·`CLUSTER SLOTS` 등 차단 | 해당 없음 |
| RediSearch | 사용 불가 | RediSearch 사용 시 필요한 정책 | 사용 불가 |
| 캐시 크기 | 지원되는 SKU 범위 | 지원되는 SKU 범위 | 25GB 이하 |
| 생성 후 정책 변경 | 불가 | 불가 | 클러스터 정책으로 변경 가능. Active geo-replication 그룹은 제외 |

Enterprise에서 active geo-replication을 사용하지 않으면 `DEL`, `MSET`, `MGET`, `EXISTS`, `UNLINK`, `TOUCH`가 슬롯을 넘어 실행될 수 있습니다. Active geo-replication을 사용하면 이 중 `MGET`, `EXISTS`, `TOUCH`만 해당합니다. 그 밖의 멀티키 명령·트랜잭션·Lua는 관련 키를 같은 슬롯에 배치해야 합니다.

같은 슬롯이 필요한 키에는 `{user1}:profile`, `{user1}:session`처럼 공통 **해시 태그**를 사용할 수 있습니다. 단, 모든 키에 같은 태그를 붙이면 데이터가 한 슬롯에 몰리므로 작업 단위에 맞춰 설계합니다.

!!! warning "Enterprise 정책과 Enterprise 티어는 다른 개념입니다"
    여기서 Enterprise는 Azure Managed Redis의 **클러스터링 정책**입니다. 이전 제품인 Azure Cache for Redis의 Enterprise/Enterprise Flash 티어 이름과 혼동하지 않습니다.

## RediSearch·멀티키 요구·성능 목표로 정책 선택 { #at-a-glance }

먼저 기능 제약을 확인한 뒤 성능과 클라이언트 변경 비용을 비교합니다.

1. **RediSearch가 필요한가?** Enterprise 정책이 필요합니다.
2. **슬롯을 맞추기 어려운 멀티키·트랜잭션 사용이 있는가?** 명령 제약을 먼저 검토합니다. 25GB 이하이고 샤딩을 수용하기 어렵다면 Non-clustered를 검토합니다.
3. **클라이언트가 Redis Cluster API를 지원하고 키 설계를 조정할 수 있는가?** OSS를 우선 검토하고 실제 부하로 확인합니다.
4. **일반 클라이언트 연결 구조를 유지해야 하는가?** Enterprise를 검토하되 멀티키 명령과 프록시 처리량을 확인합니다.
5. **Active geo-replication을 사용할 것인가?** 연결할 인스턴스들의 정책을 일치시키고 그룹 구성 전에 확정합니다.

특정 장애 사례에서 Enterprise를 선택했다고 해서 모든 워크로드에 가장 적합한 것은 아닙니다. 반대로 OSS의 토폴로지 갱신 요구를 제품 장애 자체로 해석하지 않습니다.

## CLI 기본값은 OSSCluster: 생성 시 원하는 정책을 명시 { #set-and-check-policy }

Azure CLI의 `az redisenterprise create --clustering-policy` 기본값은 `OSSCluster`입니다. 원하는 연결 형태를 정했다면 기본값에 의존하지 말고 명시합니다.

기존 Azure Managed Redis 또는 Azure Cache for Redis Enterprise의 정책은 다음과 같이 확인합니다.

```bash
az redisenterprise database show \
  --cluster-name <cache-name> \
  --resource-group <resource-group> \
  --query clusteringPolicy \
  --output tsv
```

출력은 `OSSCluster`, `EnterpriseCluster`, `NoCluster` 중 하나입니다. 클라이언트의 생성자만 보고 실제 리소스 정책을 추정하지 않습니다.

다음은 **새 이름의 테스트 캐시**를 Enterprise 정책으로 생성하는 예입니다. SKU·리전은 환경에 맞게 정하고, 기존 운영 캐시 이름으로 실행하지 않습니다.

```bash
az redisenterprise create \
  --cluster-name <new-cache-name> \
  --resource-group <resource-group> \
  --location <region> \
  --sku Balanced_B10 \
  --clustering-policy EnterpriseCluster \
  --client-protocol Encrypted \
  --public-network-access Disabled
```

이 명령만으로 애플리케이션 연결 준비가 끝나지는 않습니다. 별도로 Private Endpoint·DNS·접근 경로와 [Microsoft Entra ID 사용자 등록](https://learn.microsoft.com/azure/redis/entra-for-authentication)을 구성해야 합니다. 접근 키 예제를 사용할 경우 키 인증이 허용되어 있는지도 확인합니다. CLI 참조의 현재 요구 버전은 Azure CLI 2.75.0 이상입니다.

OSS와 Enterprise는 기존 캐시에서 정책을 바꿀 수 없습니다. 전환은 원하는 정책의 **별도 캐시를 준비하고 연결을 이전**하는 작업으로 계획합니다. Non-clustered의 변경 예외는 위 비교표와 공식 정책 문서를 따릅니다.

## 정책과 무관하게 인증 갱신·timeout·재시도 구성 { #connection-resilience }

| 항목 | 기준 |
|---|---|
| 인증과 TLS | Microsoft Entra ID를 우선 검토하고 토큰 갱신까지 구성합니다. 인증서 검증을 끄지 않습니다. |
| Connect timeout | Microsoft Learn은 5초를 권장합니다. 짧게 설정한다고 복구가 빨라지는 것은 아닙니다. |
| Command timeout | 5초 미만에서 시작해 명령·값 크기와 지연 요구에 맞춥니다. 실제 제한 범위는 클라이언트 API별로 확인합니다. |
| 유휴 연결 | 서버의 10분 유휴 제한보다 짧은 heartbeat/keepalive를 구성합니다. |
| 재연결 | 백오프와 지터를 적용하고 연결 폭증을 피합니다. 연결을 재생성한다면 이전 연결도 정리합니다. |
| 요청 처리 | 재연결 성공과 실패한 요청의 재실행은 별개입니다. 재시도 시 중복 쓰기 가능성과 시간 제한을 검토합니다. |

Linux에서 연결 단절 감지가 오래 걸린다면 [TCP 설정 권장 사항](https://learn.microsoft.com/azure/redis/best-practices-connection#tcp-settings-for-linux-hosted-client-applications)도 확인합니다. 호스트 전체에 영향을 주는 설정이므로 플랫폼 운영자와 적용 범위를 검토합니다.

프록시를 사용하는 Enterprise도 일시적인 연결 오류를 완전히 없애지는 않습니다. 지속적인 오류에는 Circuit Breaker나 허용 가능한 대체 경로를 설계하되, **캐시 조회 실패와 세션·락·업무 데이터 유실을 같은 방식으로 처리하지 않습니다.**

## Node.js·Java 연결 구현과 Azure Cache for Redis 이전 절차 { #client-libraries }

이전 통합 문서의 링크로 들어왔다면 아래에서 분리된 문서로 이동할 수 있습니다. 정책 설명과 비교표는 이 페이지에서만 유지합니다.

### Node.js: 정책별 생성자와 토폴로지 갱신 { #nodejs }

[Node.js의 클라이언트 선택과 토폴로지 갱신](nodejs/index.md): node-redis·ioredis의 연결 예제와 버전별 토폴로지 갱신을 다룹니다.

### Java: 라이브러리별 연결과 Spring Boot 설정 { #java }

<span id="lettuce-vs-jedis"></span>
<span id="lettuce"></span>
<span id="jedis"></span>
<span id="spring-boot"></span>

[Java의 클라이언트 선택과 토폴로지 갱신](java/index.md): [Lettuce](java/index.md#lettuce), [Jedis](java/index.md#jedis), [Spring Boot](java/index.md#spring-boot), [Redisson](java/index.md#redisson)의 설정을 다룹니다.

### Azure Cache for Redis: 연결·데이터 전환과 롤백 { #_1 }

<span id="migrate-from-single-endpoint"></span>
<span id="migrate-from-cluster-client"></span>
<span id="migrate-from-enterprise-tier"></span>

[Azure Cache for Redis에서 마이그레이션](../migration-from-azure-cache/index.md): 원본 구성에 따른 변경 사항, 데이터 처리와 전환 검증을 다룹니다.

### 재연결 실패 사례와 Eviction·TTL 설계 { #_2 }

- [OSS 정책의 Failover 후 재연결 실패 사례](../cluster-failover-recovery/index.md): 당시 연결 설정·관측·원인 추정을 보존합니다.
- [Eviction Policy와 TTL 설계](../eviction-policy-and-ttl/index.md): 메모리 한도와 키 수명주기를 다룹니다.
