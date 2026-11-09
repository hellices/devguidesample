---
title: "Micrometer 비즈니스 지표 · AKS 자동 계측 · agent 기반 Grafana 대시보드"
description: Spring Boot 앱에 Micrometer meter만 남기면 AKS 자동 계측이 Application Insights로 수집하고, agent에게 실제 customMetrics를 조회·검증하게 하면 Grafana 대시보드가 데이터에 맞게 완성됩니다. MovieLog 캡처, agent prompt 예시, 로컬 agent 직접 반영과 JSON import 방식을 함께 안내합니다.
document_type: guide
services: [azure-monitor, azure-kubernetes-service, azure-managed-grafana]
technologies: [java, spring-boot, micrometer, kubernetes, grafana]
tags: [build, operate]
status: current
verification_status: verified
sources_checked_at: 2026-11-10
official_sources:
  - title: Autoinstrument AKS apps with Azure Monitor Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless
  - title: Configure Azure Monitor Application Insights for Java
    url: https://learn.microsoft.com/azure/azure-monitor/app/java-standalone-config
  - title: Metrics in Application Insights
    url: https://learn.microsoft.com/azure/azure-monitor/app/metrics-overview
  - title: Micrometer Meters
    url: https://docs.micrometer.io/micrometer/reference/concepts/meters.html
  - title: Micrometer Counters
    url: https://docs.micrometer.io/micrometer/reference/concepts/counters.html
  - title: Micrometer Timers
    url: https://docs.micrometer.io/micrometer/reference/concepts/timers.html
  - title: Micrometer Observation Components
    url: https://docs.micrometer.io/micrometer/reference/observation/components.html
  - title: How to manage data sources in Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-data-source-plugins-managed-identity
  - title: Configure an Azure Managed Grafana remote MCP server
    url: https://learn.microsoft.com/azure/managed-grafana/grafana-mcp-server
  - title: Create a dashboard in Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-create-dashboard
  - title: Migrate to Azure Managed Grafana
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-migrate
  - title: Authenticate to Azure Managed Grafana data plane APIs with Microsoft Entra ID
    url: https://learn.microsoft.com/azure/managed-grafana/how-to-authenticate-data-plane-api
  - title: Fix Spring Boot 4 Micrometer auto-configuration and add actuator metrics smoke coverage
    url: https://github.com/microsoft/ApplicationInsights-Java/pull/4672
last_verified: 2026-11-10
review_cycle_days: 30
applies_to:
  - Spring Boot와 Micrometer를 사용하는 Java workload
  - AKS Application Monitoring Java autoinstrumentation (Linux node pool)
  - workspace 기반 Application Insights와 Azure Managed Grafana
related_guides:
  - ../aks-java-micrometer-custom-metrics/index.md
---

# Micrometer 비즈니스 지표 · AKS 자동 계측 · agent 기반 Grafana 대시보드

## 핵심 흐름: meter 기록 → 자동 수집 → agent 대시보드 { #message }

meter 기록, 자동 수집, agent 검증의 세 단계만 연결하면 비즈니스 대시보드가
완성됩니다. "오늘 리뷰가 몇 건 올라왔나", "별점 평균이 떨어지고 있나" 같은 지표를
보려고 exporter를 붙이거나, scrape 설정을 만들거나, 대시보드 query를 손으로
설계할 필요는 없습니다.

1. **앱은 Micrometer API로 지표를 기록합니다.** 도메인 이벤트가 일어날 때
   Counter, DistributionSummary, Gauge 값을 남깁니다.
2. **AKS 자동 계측이 수집합니다.** 클러스터의 자동 계측을 켜면 Pod에 주입된
   Application Insights Java agent가 Micrometer 지표를 읽어 Application Insights
   `customMetrics`로 보냅니다. 앱에는 exporter도, metrics endpoint도 필요 없습니다.
3. **agent가 실제 지표를 보며 Grafana 대시보드를 만듭니다.** 코드의 meter 이름을
   추측하지 않고 `customMetrics`를 직접 조회해 집계식을 정하고, 모든 panel
   query를 실행하고, 렌더링한 화면을 캡처해 확인합니다.

아래는 Spring Boot로 만든 영화 리뷰 sample 앱 MovieLog의 custom metric을 이 흐름으로
시각화한 대시보드입니다. 앱 구성과 배포, 대시보드를 만든 과정과 실측값은
[MovieLog 실습](movielog-lab/index.md)에 있습니다.

![MovieLog 비즈니스 지표 대시보드. 영화 조회 13.0K, 새 리뷰 2.26K, 신규 회원 3.23K stat과 sparkline, 평균 별점 3.50 gauge, fresh/rotten donut, 채널별 누적 area, 판정별 막대, 활동별 bar gauge, 평균 별점 추이, 누적 현황 stat, Pod별 분포 bar gauge, 외부 조회 결과, Pod별 누락 metric status history, metric 수신 상태 table](images/movielog-dashboard.png)

## 앱 코드: Micrometer API 기반 custom metric { #record }

앱은 Micrometer API로 비즈니스 이벤트를 custom metric으로 만듭니다. Micrometer는
Java 애플리케이션의 지표 계측 API입니다. 앱은 `MeterRegistry`에 meter를 등록하고
값을 기록할 뿐이고, 그 값을 어느 모니터링 백엔드로 보낼지는 registry 구현이나 수집
agent가 정합니다. Spring Boot에서는 `spring-boot-starter-actuator`가 `MeterRegistry`
bean을 구성하므로 생성자로 주입받아 바로 씁니다.

meter는 이름과 tag 조합으로 구분되며, 측정하려는 값의 성격에 따라 종류를 고릅니다.
Micrometer가 제공하는 meter는 다음과 같습니다.

| meter | 기록하는 값 | 어울리는 지표 | MovieLog 예 |
|---|---|---|---|
| Counter | 늘어나기만 하는 발생 횟수 | 조회, 가입, 작성 같은 이벤트 수 | `movielog.reviews.posted`, `movielog.movie.views` |
| Gauge | 읽는 시점의 현재 값 | 저장 건수, queue 길이, pool 사용량 | `movielog.reviews.stored` |
| DistributionSummary | 기록한 값들의 분포(횟수, 합계, 최댓값) | 별점, payload 크기처럼 시간이 아닌 값 | `movielog.review.rating` |
| Timer | 짧은 작업의 소요 시간 분포와 횟수 | 요청·처리 지연 | 쓰지 않음 |
| LongTaskTimer | 실행 중인 긴 작업의 수와 경과 시간 | batch, 예약 작업 | 쓰지 않음 |
| FunctionCounter | 객체가 이미 가진 누적 횟수를 함수로 읽은 값 | cache hit 수 같은 라이브러리 내부 통계 | 쓰지 않음 |
| FunctionTimer | 객체가 이미 가진 누적 횟수와 총 시간을 함수로 읽은 값 | 라이브러리가 집계한 처리 시간 | 쓰지 않음 |
| TimeGauge | 시간 단위를 가진 현재 값 | 마지막 처리 후 경과 시간 | 쓰지 않음 |

meter를 만드는 방법도 여러 가지입니다.

| 방법 | 형태 | 쓰임 |
|---|---|---|
| Builder API | `Counter.builder("name").tag(...).register(registry)` | 설명·단위·tag를 함께 지정. MovieLog가 쓰는 방식 |
| registry 단축 메서드 | `registry.counter("name", "tag", "value")` | 간단한 meter를 한 줄로 등록 |
| annotation | 메서드에 `@Counted`, `@Timed` | 호출 횟수와 실행 시간을 메서드 본문 수정 없이 기록. `CountedAspect`·`TimedAspect` 구성 필요 |
| `MeterBinder` | `bindTo(MeterRegistry)` 구현 | 관련 meter를 한 class에 묶어 등록. MovieLog의 DB Gauge가 쓰는 방식 |
| Observation API | `Observation.createNotStarted("name", observationRegistry).observe(...)` | 한 번 계측해 등록된 handler에 따라 metric과 trace를 생성. metric은 `MeterObservationHandler`, trace는 tracing bridge와 exporter 구성이 별도로 필요 |
| Spring Boot 자동 등록 | Actuator 의존성 추가 | JVM, HTTP 요청, DB connection pool 지표가 코드 없이 등록 |

Counter와 DistributionSummary는 이벤트가 일어날 때 코드에서 값을 올립니다.
MovieLog는 서비스 로직이 발행한 도메인 이벤트를 listener 한 곳에서 받아 기록합니다.

```java
@Component
class BusinessMetrics {

    private final MeterRegistry registry;
    private final DistributionSummary reviewRating;

    BusinessMetrics(MeterRegistry registry) {
        this.registry = registry;
        this.reviewRating = DistributionSummary.builder("movielog.review.rating")
            .baseUnit("stars")
            .register(registry);
    }

    @TransactionalEventListener(fallbackExecution = true)
    void reviewCreated(ReviewEvents.Created event) {
        // The same name and tags return the already registered counter.
        Counter.builder("movielog.reviews.posted")
            .tag("channel", channel())
            .tag("verdict", event.fresh() ? "fresh" : "rotten")
            .register(registry)
            .increment();
        reviewRating.record(event.rating() / 2.0);
    }
}
```

Gauge는 값을 올리지 않고 값을 읽을 함수를 등록합니다. registry가 지표를 내보낼 때마다
이 함수를 호출하므로, DB 조회처럼 비싼 값은 cache로 감쌉니다. MovieLog는 저장 건수를
1분에 한 번만 다시 조회합니다.

```java
// CachedCount re-runs reviews.count() at most once per minute.
CachedCount reviewCount = new CachedCount(reviews::count, clock);
Gauge.builder("movielog.reviews.stored", reviewCount, CachedCount::value)
    .strongReference(true)
    .register(registry);
```

- 위 코드는 발췌입니다. MovieLog는 첫 이벤트 전에도 대시보드에 0이 보이도록
  channel별 Counter를 시작할 때 미리 등록합니다.
- tag 값은 `web`/`api`, `fresh`/`rotten`처럼 고정된 몇 개만 씁니다. 영화 ID나
  사용자명처럼 값이 계속 늘어나는 항목을 tag에 넣으면 series가 끝없이 늘어납니다.
- 내보낼 meter는 prefix 허용 목록으로 제한합니다. 내보낸 지표는 모두 과금 대상
  `customMetrics` 행이 됩니다.
- MovieLog의 meter 목록, 이벤트 처리 시점, AKS profile 설정은 실습의
  [MovieLog meter 절](movielog-lab/index.md#meters)에 있습니다.

## 수집: AKS 자동 계측과 Application Insights customMetrics { #collect }

AKS의 Application Monitoring 자동 계측을 켜면 앱이 기록한 Micrometer 지표가 코드
변경 없이 Application Insights로 수집됩니다. 앱에 exporter 라이브러리를 넣거나
metrics endpoint를 열고 scrape 설정을 만들 필요가 없습니다. 지표는 Application
Insights의 `customMetrics`에 저장되고, 대시보드는 이를 data source로 조회합니다.

1. 클러스터에서 자동 계측 지원을 켭니다(`az aks update --enable-azure-monitor-app-monitoring`,
   Azure CLI 2.86.0 이상). 포털의 **Monitor** 설정에서도 켤 수 있으며, 전체 절차는
   [Autoinstrument AKS apps with Azure Monitor Application Insights](https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless)에
   있습니다.
2. namespace에 `Instrumentation` CR을 만들어 지표를 보낼 Application Insights를
   지정합니다.
3. Deployment를 재시작하면 AKS가 Pod에 Application Insights Java agent를 주입합니다.
4. agent는 앱 프로세스 안의 Micrometer registry를 읽어 기본 60초마다
   `customMetrics`로 보냅니다. 요청, 의존성, JVM 지표도 같은 agent가 함께
   수집합니다.

namespace의 모든 Deployment를 계측하려면 `default`라는 이름의 CR에 언어를 지정합니다.
MovieLog처럼 Deployment를 골라 계측하는 per-deployment 방식은 `default`가 아닌
이름의 CR을 만들고 `autoInstrumentationPlatforms`를 빈 배열로 둡니다. 언어와 사용할
CR은 Pod template의 annotation(`inject-java`)이 정합니다.

```yaml
apiVersion: monitor.azure.com/v1
kind: Instrumentation
metadata:
  name: movielog
spec:
  settings:
    # Per-deployment CR: the list stays empty and the Pod annotation below picks the language.
    autoInstrumentationPlatforms: []
  destination:
    applicationInsightsConnectionString: "<connection-string>"
---
# Deployment spec.template.metadata.annotations
instrumentation.opentelemetry.io/inject-java: "movielog"
```

재시작한 Pod에 agent가 주입되면 Micrometer 이름의 점이 underscore로 바뀐
`movielog_*` 지표가 들어옵니다(`movielog.movie.views` → `movielog_movie_views`).
지표가 실제로 도착했는지는 `customMetrics`를 조회해 확인합니다. 아래는 MovieLog의
비즈니스 지표가 agent 기본 JVM 지표와 함께 두 Pod에서 도착한 inventory입니다.
단, Spring Boot 4 앱은 주입된 agent가 3.7.9 이상이어야 합니다
([Spring Boot 4 호환성](#spring-boot-4)). 이 캡처는 Application Insights Java 3.7.10
init image를 주입한 상태에서 얻었습니다.

![customMetrics inventory. JVM 기본 지표와 함께 movielog_comments_posted부터 movielog_reviews_stored까지 12개 비즈니스 지표가 두 Pod에서 도착](images/probe-inventory-agent-3.7.10.png)

## agent 대시보드 작성: 실제 지표 조회 기반 panel 설계 { #agent }

agent를 쓰면 KQL과 panel 설정을 직접 짜지 않고도 대시보드를 만들 수 있고, agent가
실제로 수집된 지표를 먼저 확인하게 하면 대시보드가 데이터에 더 정확히 맞습니다.
코드에는 meter 이름과 종류만 있습니다. Application Insights에 들어온 이름, dimension
값, 값 모양(`value`, `valueCount`, `valueSum`)은 조회해야 알 수 있습니다. 그래서
agent에게 "그려 줘" 한 번 대신 조회, 생성, 실행 확인, 화면 확인의 네 단계를 맡깁니다.

| agent 단계 | 하는 일 | 정확해지는 부분 |
|---|---|---|
| probe | 실제 `customMetrics`의 이름, dimension, Pod 수, 값 모양 조회 | metric별 집계식. Counter는 `sum`, 분포는 `sum(valueSum)/sum(valueCount)`, Pod마다 같은 값을 보내는 Gauge는 Pod 간 `max` |
| build | probe가 정한 집계식과 질문 유형별 시각화로 dashboard JSON 생성 | panel마다 답할 질문과 시각화의 짝 |
| verify | 모든 panel query를 Grafana에서 실행 | 오류나 0행 panel이 없는 대시보드 |
| look | 렌더링한 화면을 캡처해 직접 확인 | 색, legend, 미완성 시간 bin, 식별자 노출처럼 query 결과로는 안 보이는 화면 품질 |

query가 모두 성공해도 화면에서는 아래처럼 정상 건수가 경고색으로 보이거나 legend가
읽기 어려울 수 있습니다. look 단계는 이런 화면을 반영 전에 걸러 냅니다. 점검 기준을
통과한 결과가 이 문서 맨 위의 대시보드입니다.

![수정 전 캡처. 영화 조회 2.17K, 새 리뷰 366, 신규 회원 542가 빨간색으로 표시되고 legend가 perMin api, perMin web으로 표시됨](images/look-step-before-fix.png)

단계별 query와 통과 기준, 화면 점검 항목은 실습의
[agent 대시보드 방법론](movielog-lab/index.md#agent-method)에 있습니다.

### 질문 유형별 panel 시각화 { #visualization }

panel 시각화는 답할 질문의 유형으로 고릅니다. `customMetrics`는 시간 bin으로
조회되므로 agent에게 따로 말하지 않으면 거의 모든 panel을 꺾은선으로 그립니다.
질문 유형과 시각화의 짝을 prompt에 넣어 줍니다.

| 질문 유형 | 시각화 |
|---|---|
| 구간 동안 몇 건인가 | stat + sparkline |
| 값이 정상 범위인가 | gauge(도메인 기준 threshold) |
| 구성 비율은 | donut |
| 무엇이 많은가, 쏠림은 | bar gauge |
| 시간에 따라 어떻게 변하는가 | time series(누적 area, bar, line) |
| Pod마다 빠진 지표가 없는가 | status history(누락 수, 0이 정상), table |

MovieLog panel별 질문, 집계식, 시각화는 실습의 [build 절](movielog-lab/index.md#build)에
있습니다.

### MovieLog 대시보드 prompt 예시 { #prompt-example }

MovieLog 대시보드는 agent가 지표 조회 → 집계식 결정 → panel 제안 → query 실행 →
화면 확인 순서로 작업해 만들었습니다. 아래는 그 작업 순서를 다른 환경에서 다시
시킬 수 있게 줄여 정리한 prompt입니다. 단계별 query와 도구까지 적은 원본 지시문은
[agent-dashboard-prompt.md](downloads/agent-dashboard-prompt.md)입니다.
Managed Grafana MCP endpoint(`/api/azure-mcp`)를 연결한 VS Code의 GitHub Copilot이나,
`az`로 로그인한 터미널에서 실행하는 agent(예: GitHub Copilot CLI)에 붙입니다.
`<...>`는 자기 환경 값으로 바꿉니다.

```text
MovieLog의 비즈니스 지표로 Grafana 대시보드를 만들어 줘.
코드의 meter 이름을 그대로 믿지 말고, 실제로 들어온 데이터를 먼저 조회해서 결정해.

- 데이터: Application Insights <app-insights-resource-group>/<app-insights-name>의 customMetrics
  (cloud_RoleName = movielog, 지표 prefix = movielog_)
- Grafana: Azure Managed Grafana <grafana-resource-group>/<grafana-name>의 Azure Monitor data source

1. 최근 30분 동안 들어온 movielog_* 지표의 이름, Pod 수, dimension과 값 개수,
   valueCount·value 모양을 조회해서 표로 보여 줘.
2. 그 결과로 metric마다 집계식을 정해 줘. Counter, 분포(DistributionSummary·Timer),
   Gauge를 구분하고, 근거가 된 조회 결과를 한 줄씩 적어.
3. panel 목록을 "답할 질문 / metric / 집계식 / 시각화" 표로 먼저 제안해.
   시각화는 질문 유형으로 골라. 합계는 stat, 정상 범위는 gauge, 비율은 donut,
   비교와 쏠림은 bar gauge, 추이만 time series로 그려.
4. dashboard JSON을 만들고 모든 panel query를 Grafana에서 실제로 실행해서
   0행이나 오류가 있으면 고친 뒤 다시 실행해.
5. Grafana에 올리고 화면을 캡처해서 식별자 노출, 정상 값의 경고색,
   읽기 어려운 legend, 끝이 꺾이는 미완성 구간이 없는지 직접 확인해.

connection string, subscription ID, resource ID는 출력·파일·캡처에 남기지 마.
```

1단계가 돌려주는 표의 실제 형태는 실습의 [probe 1~3](movielog-lab/index.md#probe-inventory)
출력에 있습니다.

## 대시보드 반영 방식: 로컬 agent 직접 반영과 JSON import { #publish }

agent가 만든 대시보드를 Grafana에 넣는 방법은 두 가지입니다. 개발 환경에서는 로컬
agent가 직접 반영하고, 운영처럼 agent에 쓰기 권한을 주지 않는 환경에는 검증된 JSON을
import합니다.

| 방식 | 흐름 | 적합한 경우 |
|---|---|---|
| 로컬 agent 직접 반영 | 개발자 PC의 agent가 Managed Grafana MCP(`amgmcp_dashboard_update`) 또는 `az grafana dashboard create`로 반영하고, 같은 세션에서 query 실행과 캡처 확인까지 반복 | 대시보드를 처음 만들거나 자주 고칠 때, agent 계정에 Grafana Editor 이상을 줄 수 있을 때 |
| JSON 추출 후 import | agent가 만든 JSON 파일이나 검증된 dashboard를 Export한 파일을 저장소에 커밋·리뷰한 뒤, 대상 Grafana의 **Dashboards > Import** 또는 `az grafana dashboard import`로 가져옴 | 운영 Grafana에 agent 권한을 주지 않을 때, 여러 환경에 같은 대시보드를 배포하거나 변경 이력을 남길 때 |

- 환경마다 달라지는 Application Insights resource ID와 `cloud_RoleName`은
  dashboard 변수로 빼 두고, import 뒤 변수 값을 채웁니다.
- 한 환경에서 Export한 JSON에는 그 환경의 resource ID(구독 ID 포함)가 들어
  있습니다. 커밋하기 전에 변수 값을 비우거나, 변수가 빈 JSON을 따로 만듭니다.
- 두 방식의 실제 명령과 결과는
  [MovieLog 실습의 대시보드 반영 절](movielog-lab/index.md#publish)에서 실행합니다.

## MovieLog 실습 { #lab }

[MovieLog 실습](movielog-lab/index.md)은 AKS, Application Insights, Azure Managed
Grafana를 만들고 MovieLog와 합성 부하를 배포한 뒤, 위 네 단계와 두 반영 방식을
명령과 실측값, 캡처로 재현합니다. 약 90분이 걸리고 유료 자원을 쓰며, 마지막에 resource group을
지워 정리합니다. 실행 가능한 앱, manifest, agent 도구는 이 페이지의
`movielog-app` sample에 있습니다.

## Spring Boot 4 호환성: 관리형 agent 3.7.7-aks 제약 { #spring-boot-4 }

Spring Boot 4에서는 주입된 agent가 3.7.9 이상인지 먼저 확인합니다. Application
Insights Java agent는 3.7.9부터 Spring Boot 4의 Micrometer 구성을 인식합니다.
2026-11-06 기준 AKS가 주입하는 관리형 agent는 `3.7.7-aks`였습니다.

- 원인과 임시 대응: [AKS Java Micrometer custom metric 누락 임시 대응](../aks-java-micrometer-custom-metrics/index.md)
- MovieLog에서 관리형 agent로는 `movielog_*`가 오지 않던 결과와 3.7.10 init image로 바꾼 절차: [실습의 버전 확인 절](movielog-lab/index.md#version-gate)

## 공식 참고 자료

- [Autoinstrument AKS apps with Azure Monitor Application Insights](https://learn.microsoft.com/azure/azure-monitor/containers/kubernetes-codeless)
- [Configure Azure Monitor Application Insights for Java](https://learn.microsoft.com/azure/azure-monitor/app/java-standalone-config)
- [Metrics in Application Insights](https://learn.microsoft.com/azure/azure-monitor/app/metrics-overview)
- [Micrometer Meters](https://docs.micrometer.io/micrometer/reference/concepts/meters.html)
- [Micrometer Counters](https://docs.micrometer.io/micrometer/reference/concepts/counters.html)
- [Micrometer Timers](https://docs.micrometer.io/micrometer/reference/concepts/timers.html)
- [Micrometer Observation Components](https://docs.micrometer.io/micrometer/reference/observation/components.html)
- [How to manage data sources in Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-data-source-plugins-managed-identity)
- [Configure an Azure Managed Grafana remote MCP server](https://learn.microsoft.com/azure/managed-grafana/grafana-mcp-server)
- [Create a dashboard in Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-create-dashboard)
- [Migrate to Azure Managed Grafana](https://learn.microsoft.com/azure/managed-grafana/how-to-migrate)
- [Authenticate to Azure Managed Grafana data plane APIs with Microsoft Entra ID](https://learn.microsoft.com/azure/managed-grafana/how-to-authenticate-data-plane-api)
- [Fix Spring Boot 4 Micrometer auto-configuration (ApplicationInsights-Java PR #4672)](https://github.com/microsoft/ApplicationInsights-Java/pull/4672)
