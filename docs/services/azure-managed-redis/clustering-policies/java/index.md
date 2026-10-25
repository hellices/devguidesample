---
title: "Azure Managed Redis Java: 정책별 클라이언트 선택과 토폴로지 갱신"
description: Lettuce·Jedis의 정책별 연결과 TLS·토폴로지 갱신을 설명하고 Spring Boot·Redisson의 적용 지점을 구분합니다.
document_type: guide
topic_order: 2
services:
- azure-managed-redis
technologies:
- java
- spring-boot
- redis
tags:
- build
- operate
status: current
verification_status: verified
sources_checked_at: 2026-10-25
official_sources:
- title: Choose a clustering policy for Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/choose-clustering-policy
- title: Azure Managed Redis Client libraries
  url: https://learn.microsoft.com/azure/redis/best-practices-client-libraries
- title: 'Quickstart: Use Azure Managed Redis in Java with Jedis Redis client'
  url: https://learn.microsoft.com/azure/redis/java-get-started
- title: Connection resilience with Azure Managed Redis
  url: https://learn.microsoft.com/azure/redis/best-practices-connection
- title: Lettuce Best Practices
  url: https://github.com/Azure/AzureCacheForRedis/blob/main/Lettuce%20Best%20Practices.md
- title: Jedis Best Practices
  url: https://github.com/Azure/AzureCacheForRedis/blob/main/Redis-BestPractices-Java-Jedis.md
- title: Jedis RedisClient
  url: https://github.com/redis/jedis/blob/v7.2.0/src/main/java/redis/clients/jedis/RedisClient.java
- title: Jedis RedisClusterClient
  url: https://github.com/redis/jedis/blob/v7.2.0/src/main/java/redis/clients/jedis/RedisClusterClient.java
- title: Jedis ClusterClientBuilder
  url: https://github.com/redis/jedis/blob/v7.2.0/src/main/java/redis/clients/jedis/builders/ClusterClientBuilder.java
- title: Jedis SslOptions
  url: https://github.com/redis/jedis/blob/v7.2.0/src/main/java/redis/clients/jedis/SslOptions.java
- title: Jedis DefaultJedisSocketFactory
  url: https://github.com/redis/jedis/blob/v7.2.0/src/main/java/redis/clients/jedis/DefaultJedisSocketFactory.java
- title: Spring Boot 3.5 Redis properties
  url: https://github.com/spring-projects/spring-boot/blob/v3.5.0/spring-boot-project/spring-boot-autoconfigure/src/main/java/org/springframework/boot/autoconfigure/data/redis/RedisProperties.java
- title: Spring Boot 4.0 Redis properties
  url: https://github.com/spring-projects/spring-boot/blob/v4.0.0/module/spring-boot-data-redis/src/main/java/org/springframework/boot/data/redis/autoconfigure/DataRedisProperties.java
- title: Spring Boot ClientResourcesBuilderCustomizer
  url: https://github.com/spring-projects/spring-boot/blob/v3.5.0/spring-boot-project/spring-boot-autoconfigure/src/main/java/org/springframework/boot/autoconfigure/data/redis/ClientResourcesBuilderCustomizer.java
- title: Redisson cluster configuration
  url: https://github.com/redisson/redisson/blob/master/redisson/src/main/java/org/redisson/config/ClusterServersConfig.java
- title: Redisson client configuration
  url: https://github.com/redisson/redisson/blob/master/redisson/src/main/java/org/redisson/config/Config.java
last_verified: 2026-10-25
review_cycle_days: 180
applies_to:
- Azure Managed Redis
- Lettuce / Jedis 7.2.0
- Spring Boot 3.5 / 4.0
related_cases:
- ../../cluster-failover-recovery/index.md
related_guides:
- ../../migration-from-azure-cache/index.md
---

# Azure Managed Redis Java: 정책별 클라이언트 선택과 토폴로지 갱신 { #azure-managed-redis-java }

Java에서는 라이브러리 선택과 Azure Managed Redis의 정책을 함께 확인합니다. 정책 자체의 설명은 [정책 개요](../index.md), 서비스 이전 절차는 [마이그레이션 가이드](../../migration-from-azure-cache/index.md)에 모아 두었습니다.

## 예제는 접근 키 인증 기준이며 Entra ID에는 토큰 갱신 필요 { #_1 }

아래 Java 코드는 기존 프로젝트의 초기화 코드에 넣는 **구성 단편**입니다. import·클래스 선언·애플리케이션 수명주기는 생략하되, 사용되는 입력과 타입은 다음과 같이 구분합니다.

- `host`: `REDIS_HOST`에서 읽은 캐시 호스트 이름. 스킴·포트 없이 사용합니다.
- `password`: `REDIS_ACCESS_KEY`에서 읽은 테스트 캐시의 접근 키. 해당 캐시는 키 인증을 허용해야 합니다.
- `username`: 접근 키 예제에서는 `default`입니다.
- `uri`, `resources`, `config`: 각 라이브러리 절에서 만드는 객체입니다. 다른 절의 코드를 섞지 않습니다.

운영 인증은 [Microsoft Entra ID와 Java 빠른 시작](https://learn.microsoft.com/azure/redis/java-get-started)을 우선 검토합니다. 아래 접근 키 예제의 `password`에 한 번 발급받은 Entra 토큰만 넣는 것으로 대체할 수는 없습니다. 토큰 갱신·재인증까지 구성해야 합니다.

각 예제를 적용하기 전에 입력 누락을 명시적으로 처리합니다.

```java
String host = System.getenv("REDIS_HOST");
String password = System.getenv("REDIS_ACCESS_KEY");
if (host == null || host.isBlank() || password == null || password.isBlank()) {
    throw new IllegalArgumentException("REDIS_HOST and REDIS_ACCESS_KEY are required");
}
String username = "default";
```

## Lettuce·Jedis: RedisClient와 RedisClusterClient를 정책에 맞게 선택 { #lettuce-vs-jedis }

| 항목 | Lettuce | Jedis 7.2.0 예제 |
|---|---|---|
| 의존성 | `io.lettuce:lettuce-core` | `redis.clients:jedis` |
| Enterprise / Non-clustered | `io.lettuce.core.RedisClient` | `redis.clients.jedis.RedisClient` |
| OSS | `io.lettuce.core.cluster.RedisClusterClient` | `redis.clients.jedis.RedisClusterClient` |
| 토폴로지 갱신 설정 | `ClusterTopologyRefreshOptions` | `topologyRefreshPeriod` |
| 주로 확인할 것 | 공유 연결, 갱신 옵션과 `ClientResources` | 연결 풀, 재시도와 주기적 슬롯 갱신 |

두 라이브러리에 **이름이 같은 클래스**가 있습니다. 아래 절에서는 생성자의 패키지를 명시해 구분합니다. 일반 연결인지 클러스터 연결인지는 이름만이 아니라 실제 리소스 정책과 맞춰야 합니다.

## Lettuce: TLS 주소 매핑과 주기적·적응형 토폴로지 갱신 { #lettuce }

### RedisURI와 SocketOptions로 인증·TLS·연결 timeout 설정 { #_2 }

이 절의 `RedisURI`, `SocketOptions`는 `io.lettuce.core` 타입이고, `Duration`은 `java.time.Duration`입니다.

```java
RedisURI uri = RedisURI.Builder.redis(host, 10000)
        .withSsl(true)
        .withAuthentication(username, password)
        .build();
SocketOptions socketOptions = SocketOptions.builder()
        .connectTimeout(Duration.ofSeconds(5))
        .keepAlive(true)
        .build();
```

### Enterprise·Non-clustered: RedisClient로 단일 엔드포인트 연결 { #enterprise-non-clustered }

```java
io.lettuce.core.RedisClient client = io.lettuce.core.RedisClient.create(uri);
client.setOptions(io.lettuce.core.ClientOptions.builder()
        .socketOptions(socketOptions)
        .build());
try (var connection = client.connect()) {
    System.out.println(connection.sync().ping());
} finally {
    client.shutdown();
}
```

### OSS: RedisClusterClient에 주소 매핑과 갱신 옵션 적용 { #oss }

`ClientResources`, `DefaultClientResources`, `MappingSocketAddressResolver`, `DnsResolvers`는 `io.lettuce.core.resource`, `HostAndPort`는 `io.lettuce.core.internal` 타입입니다. 아래 매핑은 **IPv4로 알려진 노드 주소**를 캐시 호스트 이름으로 바꾸는 예입니다. IPv6 등 다른 주소 형식을 사용한다면 그 형식도 처리해야 합니다.

```java
ClientResources resources = DefaultClientResources.builder()
        .socketAddressResolver(MappingSocketAddressResolver.create(
                DnsResolvers.JVM_DEFAULT,
                address -> address.getHostText().matches("\\d{1,3}(\\.\\d{1,3}){3}")
                        ? HostAndPort.of(host, address.getPort())
                        : address))
        .build();

io.lettuce.core.cluster.RedisClusterClient client =
        io.lettuce.core.cluster.RedisClusterClient.create(resources, uri);
var refresh = io.lettuce.core.cluster.ClusterTopologyRefreshOptions.builder()
        .enablePeriodicRefresh(Duration.ofSeconds(5))
        .enableAllAdaptiveRefreshTriggers()
        .adaptiveRefreshTriggersTimeout(Duration.ofSeconds(5))
        .dynamicRefreshSources(false)
        .build();
client.setOptions(io.lettuce.core.cluster.ClusterClientOptions.builder()
        .socketOptions(socketOptions)
        .topologyRefreshOptions(refresh)
        .build());
try (var connection = client.connect()) {
    System.out.println(connection.sync().ping());
} finally {
    client.shutdown();
    resources.shutdown();
}
```

[Azure Lettuce 모범 사례](https://github.com/Azure/AzureCacheForRedis/blob/main/Lettuce%20Best%20Practices.md)의 주소 매핑과 주기적·적응형 갱신을 적용한 구성입니다. 원문의 Azure Cache for Redis 호스트·포트는 사용하지 않고 Azure Managed Redis의 값을 사용합니다. TLS 호스트 이름 검증을 끄지 않습니다.

5초 주기는 갱신 설정이지 5초 복구 보장이 아닙니다. 기본값은 라이브러리 버전별로 달라질 수 있으므로 사용할 갱신 정책을 명시합니다. 예제는 일회성 확인 후 정리하지만 실제 서버에서는 연결·클라이언트·리소스를 재사용하고 종료 시 닫습니다.

## Jedis 7.2.0: TLS 검증과 주기적 슬롯 갱신을 빌더로 구성 { #jedis }

### SslOptions와 주소 매핑으로 TLS 호스트 이름 검증 { #tls }

이 절의 `DefaultJedisClientConfig`, `SslOptions`, `SslVerifyMode`, `HostAndPort`는 모두 `redis.clients.jedis` 타입입니다. `Set`은 `java.util.Set`입니다.

```java
var config = DefaultJedisClientConfig.builder()
        .user(username)
        .password(password)
        .sslOptions(SslOptions.builder()
                .sslVerifyMode(SslVerifyMode.FULL)
                .build())
        .hostAndPortMapper(address ->
                address.getHost().matches("\\d{1,3}(\\.\\d{1,3}){3}")
                        ? new HostAndPort(host, address.getPort())
                        : address)
        .connectionTimeoutMillis(5_000)
        .socketTimeoutMillis(1_000)
        .build();
```

`SslOptions`로 인증서와 호스트 이름 검증을 명시합니다. IPv4 주소 매핑은 OSS의 발견된 노드 연결에도 적용됩니다. timeout의 시작 값은 [Azure Jedis 모범 사례](https://github.com/Azure/AzureCacheForRedis/blob/main/Redis-BestPractices-Java-Jedis.md)를 따르되 실제 지연 요구에 맞춥니다.

### Enterprise·Non-clustered: RedisClient 빌더로 일반 연결 { #enterprise-non-clustered_1 }

```java
try (var client = redis.clients.jedis.RedisClient.builder()
        .hostAndPort(host, 10000)
        .clientConfig(config)
        .build()) {
    System.out.println(client.ping());
}
```

### OSS: RedisClusterClient와 topologyRefreshPeriod 설정 { #oss_1 }

```java
try (var client = redis.clients.jedis.RedisClusterClient.builder()
        .nodes(Set.of(new HostAndPort(host, 10000)))
        .clientConfig(config)
        .topologyRefreshPeriod(java.time.Duration.ofSeconds(5))
        .build()) {
    System.out.println(client.ping());
}
```

`topologyRefreshPeriod`는 주기적 슬롯 갱신 옵션입니다. 이 가이드의 5초는 Lettuce 예제와 맞춘 시작 값이며 **Jedis의 기본값이나 공식 권장 주기라는 뜻은 아닙니다.**

위 빌더 예제는 Jedis **7.2.0** API를 기준으로 합니다. 이전 버전의 `JedisPooled`·`JedisCluster` 생성자를 사용하는 프로젝트는 자기 버전의 API와 업그레이드 변경 사항을 확인합니다. 라이브러리만 바꿨다고 기존 연결 풀·인증 설정이 자동으로 동일해지는 것은 아닙니다.

## Spring Boot 3.5·4.0: 정책별 연결 속성과 Lettuce 갱신 설정 { #spring-boot }

`spring-boot-starter-data-redis`의 기본 클라이언트는 Lettuce입니다. 다음 속성 예제는 **Spring Boot 3.5와 4.0**의 Redis 속성을 기준으로 합니다. `spring.data.redis.url` 등 기존 설정이 남아 새 host·port 설정을 덮어쓰지 않는지도 확인합니다.

두 정책 분기에서 함께 사용하는 설정입니다.

```properties
spring.data.redis.username=default
spring.data.redis.password=${REDIS_ACCESS_KEY}
spring.data.redis.ssl.enabled=true
spring.data.redis.connect-timeout=5s
```

**Enterprise / Non-clustered**에는 일반 연결 속성을 사용합니다.

```properties
spring.data.redis.host=${REDIS_HOST}
spring.data.redis.port=10000
```

**OSS**에는 클러스터 속성을 사용합니다. 두 분기를 동시에 설정하지 않습니다.

```properties
spring.data.redis.cluster.nodes=${REDIS_HOST}:10000
spring.data.redis.lettuce.cluster.refresh.period=5s
spring.data.redis.lettuce.cluster.refresh.dynamic-refresh-sources=false
spring.data.redis.lettuce.cluster.refresh.adaptive=true
```

3.5와 4.0 모두 위 `adaptive` 속성이 있습니다. 다른 버전으로 올릴 때는 [해당 버전의 속성 목록](https://docs.spring.io/spring-boot/appendix/application-properties/index.html)을 확인하며, “4.x에서는 모두 제거됐다”처럼 major 버전 전체로 일반화하지 않습니다.

OSS에서 필요한 주소 매핑은 위 Lettuce 절과 같습니다. Boot 3.5에서는 `@Configuration` 클래스에 다음 `ClientResourcesBuilderCustomizer` 빈을 등록해 자동 구성의 리소스를 조정할 수 있습니다. `@Bean`은 `org.springframework.context.annotation.Bean`입니다.

```java
@Bean
org.springframework.boot.autoconfigure.data.redis.ClientResourcesBuilderCustomizer
mapRedisNodeAddresses() {
    String host = System.getenv("REDIS_HOST");
    if (host == null || host.isBlank()) {
        throw new IllegalArgumentException("REDIS_HOST is required");
    }
    return builder -> builder.socketAddressResolver(
            io.lettuce.core.resource.MappingSocketAddressResolver.create(
                    io.lettuce.core.resource.DnsResolvers.JVM_DEFAULT,
                    address -> address.getHostText().matches("\\d{1,3}(\\.\\d{1,3}){3}")
                            ? io.lettuce.core.internal.HostAndPort.of(host, address.getPort())
                            : address));
}
```

이 빈 예제의 패키지는 Boot 3.5 기준입니다. Boot 4 계열로 옮길 때는 자동 구성 패키지 변경도 확인합니다. Jedis를 선택했다면 Lettuce 전용 속성으로 Jedis의 갱신이 설정된다고 기대하지 않습니다.

## Redisson: 일반·클러스터 연결 모드와 scanInterval 선택 { #redisson }

이미 Redisson을 사용한다면 일반 연결의 `useSingleServer()`와 OSS용 `useClusterServers()`를 구분합니다. 주기적 토폴로지 스캔은 `scanInterval`을 검토합니다. 구체적인 버전·TLS·풀 설정은 [Redisson 공식 구성 문서](https://redisson.pro/docs/configuration/)를 따릅니다. Lettuce·Jedis의 옵션 이름을 그대로 적용하지 않습니다.

## PING 이후 실제 키 접근·연결 복구·토큰 갱신 검증 { #_3 }

1. 위 `PING`은 초기 연결 확인일 뿐입니다. 실제 애플리케이션에서 TTL 있는 테스트 키의 쓰기·읽기와, OSS라면 여러 슬롯의 키 접근을 확인합니다.
2. 토폴로지 갱신 설정이 실제 생성된 클라이언트에 적용되는지 확인합니다. Spring Boot에서는 선택한 라이브러리와 활성 프로필도 확인합니다.
3. 테스트 환경에서 연결 단절 후 요청 복구와 연결 수를 관찰합니다. 클라이언트나 풀을 재생성한다면 이전 리소스가 남지 않아야 합니다.
4. Entra 인증은 토큰 갱신까지 검증하고, 실패를 정상 응답으로 바꾸어 숨기지 않습니다.

언어와 무관한 timeout·재시도·장애 시 요청 처리 기준은 [공통 연결 원칙](../index.md#connection-resilience)에 있습니다.
