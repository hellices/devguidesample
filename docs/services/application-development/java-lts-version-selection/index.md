---
services:
- application-development
official_sources:
- title: Support roadmap for the Microsoft Build of OpenJDK
  url: https://learn.microsoft.com/en-us/java/openjdk/support
- title: JDK 8 Project
  url: https://openjdk.org/projects/jdk8/
- title: JDK 8 Features
  url: https://openjdk.org/projects/jdk8/features
- title: JDK 17 Project
  url: https://openjdk.org/projects/jdk/17/
- title: JEPs in JDK 17 integrated since JDK 11
  url: https://openjdk.org/projects/jdk/17/jeps-since-jdk-11
- title: JEP 248 - Make G1 the Default Garbage Collector
  url: https://openjdk.org/jeps/248
- title: JEP 261 - Module System
  url: https://openjdk.org/jeps/261
- title: JEP 286 - Local-Variable Type Inference
  url: https://openjdk.org/jeps/286
- title: JEP 321 - HTTP Client API
  url: https://openjdk.org/jeps/321
- title: JDK 21 Project
  url: https://openjdk.org/projects/jdk/21/
- title: JEPs in JDK 21 integrated since JDK 17
  url: https://openjdk.org/projects/jdk/21/jeps-since-jdk-17
- title: JDK 25 Project
  url: https://openjdk.org/projects/jdk/25/
- title: JEPs in JDK 25 integrated since JDK 21
  url: https://openjdk.org/projects/jdk/25/jeps-since-jdk-21
- title: JEP 444 - Virtual Threads
  url: https://openjdk.org/jeps/444
- title: JEP 439 - Generational ZGC
  url: https://openjdk.org/jeps/439
- title: JEP 491 - Synchronize Virtual Threads without Pinning
  url: https://openjdk.org/jeps/491
- title: JEP 483 - Ahead-of-Time Class Loading and Linking
  url: https://openjdk.org/jeps/483
- title: JEP 506 - Scoped Values
  url: https://openjdk.org/jeps/506
- title: JEP 519 - Compact Object Headers
  url: https://openjdk.org/jeps/519
document_type: guide
status: current
verification_status: verified
sources_checked_at: 2026-09-16
last_verified: 2026-09-16
review_cycle_days: 180
applies_to:
- Java SE 8, 17, 21, 25
title: Java 8·17·21·25 LTS 선택과 현대화 가이드
description: Java 주요 LTS의 기능과 성능 특성을 비교하고 신규 도입 및 업그레이드 기준과 구현 패턴을 정리합니다.
technologies:
- java
tags:
- evaluate
- migrate
- optimize
---

# Java 8·17·21·25 LTS 선택과 현대화 가이드

Java 버전 선택은 새 문법의 개수보다 **전체 애플리케이션 스택의 지원
범위**와 **실제 워크로드에서 측정한 결과**로 결정해야 한다. 이 글은 Java
8, 17, 21, 25를 비교하지만, 모든 JEP를 나열하기보다 설계와 운영에 영향을
주는 변화에 집중한다.

## 먼저 내릴 결론

| 상황 | 기본 선택 | 이유 |
|---|---|---|
| 프레임워크, 라이브러리, Java agent, base image와 운영 플랫폼이 모두 지원하는 신규 서비스 | **Java 25** | 25까지 누적된 기능과 런타임 개선을 사용하고 다음 업그레이드까지의 여유를 확보하기 쉽다. |
| Java 25 지원이 아직 완전하지 않은 기존 서비스 | **Java 21** | virtual thread와 pattern matching을 안정 기능으로 사용하면서도 생태계가 충분히 성숙했다. |
| 제품 인증이나 핵심 의존성이 Java 21을 막는 서비스 | **Java 17** | Java 8을 벗어나는 현실적인 호환성 단계다. 제약이 없다면 신규 서비스의 최종 목표로 고르지는 않는다. |
| 애플리케이션 또는 공급자 제약으로 이전할 수 없는 시스템 | **Java 8 임시 유지** | 보안 업데이트가 제공되는 배포판을 유지하되 업그레이드 일정과 예산을 별도로 확보해야 한다. |

한 문장으로 줄이면 **전체 스택이 지원하면 25, 아직 지원하지 않으면 21,
호환성 제약이 있으면 17, 8은 이전 계획이 있는 유지 대상**이다. 다만 실제
지원 종료일은 버전 번호가 아니라 선택한 JDK 배포판과 계약에 따라 달라진다.

## LTS를 해석할 때 주의할 점

Java SE 사양과 OpenJDK 프로젝트가 모든 배포판에 하나의 LTS 기간을
부여하는 것은 아니다. OpenJDK의 JDK 17, 21, 25 릴리스 페이지도
“대부분의 공급자에게 LTS가 될 것”이라고 표현한다. 실제 binary, 보안
업데이트 주기, 지원 운영체제와 종료일은 공급자가 정한다.

예를 들어 [Microsoft Build of OpenJDK 지원
로드맵](https://learn.microsoft.com/en-us/java/openjdk/support)은 Microsoft
배포판의 17, 21, 25를 LTS로 분류한다. 같은 문서에서 Java 8은 Microsoft
Build의 LTS 표에 넣지 않고 일부 Azure 시나리오에 Eclipse Temurin 기반
binary와 container image를 사용한다고 설명한다. 이는 Microsoft 배포판과
명시된 Azure 시나리오의 정책이며 다른 공급자의 Java 8 지원 기간을 뜻하지
않는다.

버전을 선택할 때는 다음을 함께 확인한다.

1. JDK 배포판의 보안 업데이트 주기와 지원 종료일
2. 프레임워크, build plugin, annotation processor와 native library의 지원
3. APM, profiler, 보안 agent와 동적 agent loading 방식의 호환성
4. base image, CPU architecture와 운영체제 지원
5. 장애 시 JDK image와 JVM option을 함께 되돌릴 수 있는지

## 버전별 누적 주요 변화

아래 표의 Java 17, 21, 25 행은 해당 버전에만 추가된 기능이 아니라 **앞선
비교 버전 이후 누적된 주요 변화**를 요약한다.

| 버전 | 언어와 표준 API | 동시성·JVM·운영 변화 | 적용 관점 |
|---|---|---|---|
| **Java 8** | lambda와 method reference, interface default method, Stream, `Optional`, `java.time` | `CompletableFuture`, PermGen을 대체한 Metaspace | 함수형 collection 처리와 비동기 조합의 출발점이지만 이후 10년 이상의 런타임·진단 개선은 포함하지 않는다. |
| **Java 17**<br>(9~17 누적) | module system, `var`, 표준 HTTP Client, switch expression, text block, record, `instanceof` pattern matching, sealed class | JDK 9부터 G1이 기본 GC, JDK 15부터 ZGC가 production 기능, helpful `NullPointerException`, elastic Metaspace, JDK internal의 강한 캡슐화 | Java 8 코드와 라이브러리의 internal API·제거 모듈 의존성을 정리하면서 데이터 모델을 간결하게 만들 수 있다. |
| **Java 21**<br>(18~21 누적) | record pattern, pattern matching for `switch`, sequenced collection, 기본 charset UTF-8 | virtual thread, generational ZGC 도입, 동적 agent loading 경고 | blocking I/O 서비스의 thread-per-request 모델을 유지하면서 동시성 규모를 키울 수 있다. |
| **Java 25**<br>(22~25 누적) | unnamed variable/pattern, FFM API, Class-File API, Stream Gatherer, Scoped Value, module import, flexible constructor body | virtual thread pinning 완화, AOT cache와 profiling, compact object header, generational Shenandoah, JFR 개선, Security Manager 비활성화, 32-bit x86 port 제거 | 새 기능뿐 아니라 agent, JNI, 보안 설정, architecture와 관측 도구의 변경도 함께 검증해야 한다. |

### Java 25에서도 안정 기능이 아닌 항목

JDK 25의 **Structured Concurrency는 fifth preview**, Stable Value와 PEM
encoding은 preview, primitive type pattern은 third preview, Vector API는
tenth incubator다. JFR CPU-time profiling도 experimental 기능이다. 이런
기능은 `--enable-preview` 또는 별도 option이 필요한 실험 경로에서 검토하고
운영 기본 구현 패턴으로 삼지 않는다.

또한 Java 21에 generational ZGC가 도입됐다고 해서 당시 기본 GC가 ZGC로
바뀐 것은 아니다. JDK 21에서는 ZGC를 선택하고 generational mode를 별도로
활성화해야 했다. 이후 JDK 23에서 generational mode가 ZGC의 기본이 됐고,
JDK 24에서 non-generational mode가 제거됐다.

## 어떤 버전을 선택할까

### 신규 서비스

Java 25를 우선 검토한다. 단, “최신이므로 선택”하는 것이 아니라 다음
조건이 모두 충족되어야 한다.

- 배포판의 Java 25 지원 기간이 서비스 수명주기와 맞는다.
- framework와 모든 build·runtime dependency가 Java 25를 지원한다.
- APM, profiler, 보안 agent와 container base image가 검증됐다.
- 운영 환경과 같은 CPU architecture, memory limit, JVM option으로 부하
  테스트를 통과했다.

하나라도 막히면 Java 21을 선택하고 막힌 구성요소와 재검토 날짜를
기록한다. Java 17은 조직 표준 또는 제품 인증 때문에 21을 쓸 수 없을 때의
전환점으로 보는 편이 좋다.

### 기존 서비스

목표 버전을 먼저 고정한 뒤 Java 8 → 17 → 21 → 25를 모두 운영에 순차
배포할 필요는 없다. 중간 버전은 호환성 문제를 좁히는 진단 단계로 사용할
수 있지만, 운영 전환은 테스트와 rollback이 준비된 목표 LTS로 직접
진행할 수 있다.

Java 8 서비스라면 JDK 9의 module system과 JDK 17의 강한 캡슐화, JDK 11의
Java EE·CORBA module 제거가 주요 경계다. Java 17 서비스라면 agent,
reflection, JNI, virtual thread 사용 library와 제거 예정 API를 중심으로
21 또는 25 호환성을 확인한다.

## 최신 JDK가 성능에 유리할 수 있는 이유

최신 JDK는 누적된 JIT, GC, runtime, platform, 진단 개선을 포함하므로 더
나은 출발점이 될 수 있다. 하지만 **같은 코드가 항상 더 빨라진다는 보장은
없다**.

| 개선 경로 | 기대할 수 있는 효과 | 보장하지 않는 것 |
|---|---|---|
| JIT와 runtime 최적화 | 장기 실행 처리량, code generation, platform별 실행 효율 개선 가능성 | framework와 workload가 달라도 같은 향상률 |
| G1·ZGC·Shenandoah 개선 | pause, allocation stall, heap 회수와 memory overhead 개선 가능성 | 모든 heap 크기에서 ZGC가 G1보다 높은 처리량 |
| virtual thread | blocking I/O가 많은 서비스에서 적은 platform thread로 더 많은 동시 작업 처리 | CPU-bound 계산 가속, 개별 요청 latency 감소, downstream 용량 증가 |
| AOT class loading·linking과 profiling | 반복되는 시작 경로의 startup과 warm-up 단축 가능성 | native image와 같은 실행 모델, training 없이 자동 적용 |
| compact object header | 객체가 많은 workload에서 heap footprint와 cache locality 개선 가능성 | 기본 활성화 또는 모든 객체 구성에서 같은 효과 |
| JFR와 진단 개선 | 병목과 회귀를 더 낮은 비용으로 관찰해 튜닝 시간을 줄일 가능성 | 관측 기능 자체에 의한 application 처리량 증가 |

특히 JDK 25의 compact object header는 experimental 단계를 벗어난 product
기능이지만 **기본 object-header layout은 아니다**. 명시적으로 활성화하고
heap 크기, object 수, identity hash code 사용과 실제 latency를 비교해야
한다.

JDK 24부터는 `synchronized` 영역에서 blocking하는 virtual thread가
platform thread에 pinning되는 경우가 대부분 제거됐다. 이는 Java 21보다
기존 library와 함께 virtual thread를 적용하기 쉬워지는 변화지만, native
code 호출 같은 남은 pinning 원인과 외부 시스템의 동시성 한도까지 없애지는
않는다.

## 업그레이드는 호환성과 현대화를 분리한다

한 변경에서 JDK, framework major version, application 구조와 동시성 모델을
모두 바꾸면 회귀 원인을 구분하기 어렵다. 다음 두 단계를 별도 배포 가능한
변경으로 관리한다.

### 1단계: 기존 동작을 목표 JDK에서 재현

1. JDK 배포판과 지원 기간, OS·architecture, container image를 고정한다.
2. Maven·Gradle과 compiler plugin, framework, library, annotation
   processor, test tool을 목표 JDK 지원 버전으로 올린다.
3. APM·profiler·보안 agent, JNI/JNA와 reflection 기반 library를 확인한다.
4. 제거된 module·API, JDK internal 접근과 더 이상 유효하지 않은 JVM
   option을 찾는다.
5. 기능 회귀, startup, 부하, 장시간 안정성 테스트를 기존 구현 그대로
   통과시킨다.

JDK에 포함된 도구로 정적 의존성을 먼저 찾을 수 있다.

```bash
jdeps --jdk-internals build/app.jar
jdeprscan --release 25 build/app.jar
```

`jdeps`에 나오지 않는 reflection 접근과 runtime agent 동작은 실제 통합
테스트와 startup log로 보완한다. 경고를 무시하는 `--add-opens`를 영구
해결책으로 늘리기보다 library upgrade 또는 public API 전환을 우선한다.

### 2단계: 안정 기능을 작은 단위로 도입

runtime 전환이 안정된 뒤 record, sealed type, pattern matching, virtual
thread와 Scoped Value를 독립 변경으로 도입한다. 각 변경은 동작 테스트와
성능 지표를 다시 비교할 수 있어야 한다. preview 기능은 production
baseline과 분리한다.

## 버전 업그레이드 후 권장 구현 패턴

### 불변 값은 record로 의도를 드러낸다

보일러플레이트를 줄이기 위해 모든 class를 record로 바꾸는 것이 아니라,
값 자체가 정체성이고 불변 data carrier인 타입에 사용한다.

```java
public record CustomerId(String value) {
    public CustomerId {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException("value must not be blank");
        }
    }
}
```

가변 lifecycle, lazy loading, 상속 기반 proxy가 필요한 entity에는 기존
class가 더 적합할 수 있다.

### 닫힌 도메인은 sealed type과 exhaustive switch로 모델링한다

허용되는 결과가 정해진 도메인은 sealed hierarchy로 표현하고 Java 21의
record pattern과 pattern matching for `switch`를 함께 사용한다.

```java
sealed interface PaymentResult permits Approved, Declined {}

record Approved(String approvalId) implements PaymentResult {}

record Declined(String reason) implements PaymentResult {}

final class PaymentMessages {
    private PaymentMessages() {}

    static String message(PaymentResult result) {
        return switch (result) {
            case Approved(var approvalId) -> "approved: " + approvalId;
            case Declined(var reason) -> "declined: " + reason;
        };
    }
}
```

새 subtype이 추가되면 compiler가 누락된 분기를 찾을 수 있다. 외부 plugin이
임의 subtype을 추가해야 하는 확장 지점에는 sealed type을 사용하지 않는다.

### blocking I/O에는 virtual-thread-per-task를 검토한다

virtual thread 자체를 pool로 재사용하지 않는다. 작업마다 virtual thread를
만들되 connection pool, rate limiter, semaphore 또는 downstream quota로
실제 외부 호출 수를 제한한다.

```java
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.Semaphore;

final class DownstreamCalls {
    private static final Semaphore DOWNSTREAM_LIMIT = new Semaphore(100);

    private DownstreamCalls() {}

    static String fetch(Callable<String> request) throws Exception {
        DOWNSTREAM_LIMIT.acquire();
        try {
            return request.call();
        } finally {
            DOWNSTREAM_LIMIT.release();
        }
    }

    static List<String> fetchAll(List<Callable<String>> requests)
            throws Exception {
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = requests.stream()
                    .map(request -> executor.submit(() -> fetch(request)))
                    .toList();

            var results = new ArrayList<String>(futures.size());
            for (var future : futures) {
                results.add(future.get());
            }
            return List.copyOf(results);
        }
    }
}
```

CPU-bound 작업의 병렬도는 CPU core 수를 기준으로 제한한다. virtual thread
수를 늘려도 CPU core와 downstream connection 수는 늘어나지 않는다.

### Java 25에서는 불변 request context에 Scoped Value를 검토한다

Scoped Value는 Java 25에서 final이 됐다. child thread로 읽기 전용 context를
전달해야 할 때 mutable `ThreadLocal`보다 명확한 lifetime을 제공한다.

```java
final class RequestContext {
    private static final ScopedValue<String> TRACE_ID =
            ScopedValue.newInstance();

    private RequestContext() {}

    static void handle(String traceId, Runnable action) {
        ScopedValue.where(TRACE_ID, traceId).run(action);
    }

    static String traceId() {
        return TRACE_ID.get();
    }
}
```

framework가 tracing·security context 전파 방식을 이미 제공한다면 그
lifecycle을 우선한다. 같은 context를 framework API와 Scoped Value에
중복 저장하지 않는다.

## 성능 검증 체크리스트

기준 JDK와 목표 JDK에서 다음 조건을 같게 유지한다.

- application artifact, framework와 dependency version
- traffic model, test data, test duration과 concurrency
- CPU architecture, container CPU·memory limit
- JVM option, heap 크기, GC 종류와 warm-up 정책
- 외부 API·database의 용량과 connection pool

다음 지표를 함께 비교한다.

- throughput과 error rate
- p50, p95, p99 latency
- startup time과 steady state까지의 warm-up 시간
- CPU 사용량, RSS와 heap 사용량
- allocation rate, GC 횟수와 pause 분포
- thread·connection 수와 downstream saturation

평균값만 비교하지 말고 여러 회차의 분포와 confidence interval을 확인한다.
운영 반영은 canary 또는 점진적 배포로 진행하고, 기준을 벗어나면 JDK image와
JVM option을 함께 되돌린다.

## 제약 사항

- 이 문서는 framework별 지원 matrix나 JDK 공급자별 가격·전체 지원 기간을
  비교하지 않는다.
- Java 11은 요청된 비교 범위에서 제외했다. Java 8에서 17로 이동할 때
  9~11의 module·API 변화는 포함했다.
- 성능 수치는 특정 application을 측정한 결과가 아니므로 보편적인 향상률을
  제시하지 않는다.
- feature 상태는 2026-09-16에 확인했다. preview·incubator 기능은 이후
  릴리스에서 변경되거나 제거될 수 있다.

## 공식 참고 자료

- [Microsoft Build of OpenJDK 지원
  로드맵](https://learn.microsoft.com/en-us/java/openjdk/support)
- [JDK 8 프로젝트](https://openjdk.org/projects/jdk8/)와 [JDK 8 주요
  기능](https://openjdk.org/projects/jdk8/features)
- [JDK 17 프로젝트](https://openjdk.org/projects/jdk/17/)와 [JDK 11 이후
  JEP](https://openjdk.org/projects/jdk/17/jeps-since-jdk-11)
- [JDK 21 프로젝트](https://openjdk.org/projects/jdk/21/)와 [JDK 17 이후
  JEP](https://openjdk.org/projects/jdk/21/jeps-since-jdk-17)
- [JDK 25 프로젝트](https://openjdk.org/projects/jdk/25/)와 [JDK 21 이후
  JEP](https://openjdk.org/projects/jdk/25/jeps-since-jdk-21)
- [Virtual Threads](https://openjdk.org/jeps/444), [Generational
  ZGC](https://openjdk.org/jeps/439), [virtual thread pinning
  개선](https://openjdk.org/jeps/491)
- [Ahead-of-Time Class Loading &
  Linking](https://openjdk.org/jeps/483), [Scoped
  Values](https://openjdk.org/jeps/506), [Compact Object
  Headers](https://openjdk.org/jeps/519)
