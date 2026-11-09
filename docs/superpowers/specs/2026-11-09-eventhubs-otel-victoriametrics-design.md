# Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습 설계

**작성일:** 2026-11-09  
**상태:** 사용자 승인 완료, 구현 계획 전 검토 대상  
**대상 저장소:** `hellices/devguidesample`  
**배포 범위:** Korea Central의 임시 resource group, 검증·캡처 후 전체 삭제

## 목적과 성공 조건

이 작업은 Azure Event Hubs Premium의 platform metrics를 OpenTelemetry Collector
Contrib로 수집해 AKS의 VictoriaMetrics에 저장하고, Grafana OSS 대시보드를 agent가
실제 데이터에 맞춰 생성·검증·캡처하는 재현 가능한 실습을 만든다. 단순 구성 예시가
아니라 Azure 구독에 실제 배포하고 다음 증거를 확보한 뒤 공개 문서와 `azd` sample로
정리한다.

성공 조건은 다음과 같다.

1. Event Hubs Premium 1 PU namespace에서 CPU, memory, incoming requests,
   throttled requests, incoming/outgoing messages, incoming/outgoing bytes series를
   실제로 수집한다.
2. 지원되지 않는 `Outgoing Requests`는 추정값으로 만들지 않고 Azure Monitor의
   지원 공백으로 표시한다.
3. `azuremonitorreceiver`의 Azure Monitor API polling 경로와
   `azureeventhubreceiver`의 Diagnostic Settings streaming 경로를 모두 실제로
   배포한다.
4. Collector에서 VictoriaMetrics로 보내는 Prometheus scrape와 Prometheus remote
   write 경로를 모두 실제로 배포하고 동일 구간의 freshness, sample count, 값 형태를
   비교한다.
5. AKS의 producer와 느린 consumer로 consumer-group lag를 증가시킨 뒤 producer를
   멈춰 lag가 감소하는 과정을 관측한다.
6. 모든 Grafana panel query를 API로 실행하고, 실제 렌더링된 전체 dashboard를
   Playwright로 캡처한다.
7. 구독 ID, resource ID, 실제 IP·hostname, 비밀을 문서·sample·캡처에서 제거한다.
8. `azd up`으로 재배포할 수 있고 `azd down --purge` 및 resource group 존재 확인으로
   정리할 수 있다.
9. 저장소의 문서·source·link·public-safety·MkDocs 검증을 모두 통과한다.
10. Dedicated cluster는 생성하지 않는다. 대신 기존 Dedicated cluster resource ID를
    입력했을 때 cluster metric을 수집할 수 있는 비생성 profile과 지표 매핑을
    제공하고, 이 profile은 문서 기반·runtime 미검증으로 표시한다.

## 제품 용어와 지원 경계

Premium Event Hubs의 용량 단위는 CU가 아니라 PU(Processing Unit)다. 요청의
“CU당 평균”은 공개 문서와 dashboard에서 “PU당 값”으로 정정한다. 1 PU 실습에서는
원값과 PU당 값이 같지만 dashboard 변수 `processing_units`와 나눗셈을 유지한다.

Microsoft Learn의 `Microsoft.EventHub/namespaces` 지표표를 기준으로 다음 경계를
적용한다.

- `NamespaceCpuUsage`와 `NamespaceMemoryUsage`는 Premium namespace 지표다.
- `IncomingRequests`, `SuccessfulRequests`, `ThrottledRequests`는 지원되지만
  `OutgoingRequests`는 지원 목록에 없다.
- `IncomingMessages`, `OutgoingMessages`, `IncomingBytes`, `OutgoingBytes`는
  `EntityName` dimension과 1분 time grain을 지원한다.
- CPU와 memory는 `Replica` dimension을 가진다.
- Diagnostic Settings export는 지표마다 다르다. CPU, memory, throttled requests는
  현재 표에서 DS Export가 `No`이므로 Event Hub streaming 경로만으로 전체 요구를
  충족하지 못한다.

`azureeventhubreceiver`는 telemetry가 담긴 Event Hub를 소비하는 receiver다. 임의의
workload consumer group lag를 계산하지 않으며, receiver 자신의 checkpoint를
workload lag로 해석하지 않는다.

Dedicated는 전송 구조는 같지만 metric resource와 용량 의미가 다르다.

- 용량 단위는 PU가 아니라 CU(Capacity Unit)다.
- cluster resource type은 `Microsoft.EventHub/clusters`다.
- cluster CPU는 `CPU`, 가용 메모리는 `AvailableMemory`다. 두 지표 모두 `Role`
  dimension과 `Maximum` aggregation을 사용하므로 Premium의 namespace memory usage와
  같은 의미로 취급하지 않는다.
- `AvailableMemory`는 가용률 그대로 표시하고 threshold 방향을 반대로 설정한다.
  `100 - Maximum(AvailableMemory)`를 현재 memory usage로 이름 붙이지 않는다.
- `ClusterUtilization`은 공식 지표표에서 preview이므로 안정 지표처럼 표현하지 않는다.
- Dedicated cluster 생성 후 최소 4시간 동안 삭제할 수 없고 최소 4시간 사용료가
  청구되므로 이 실습은 Dedicated를 생성하지 않는다.
- Premium 실측 결과를 Dedicated runtime 검증으로 일반화하지 않는다.

## 선택한 접근법

### 기본 수집 경로

OTel Collector Contrib `azuremonitorreceiver`가 Gateway VM의 system-assigned managed
identity로 Azure Monitor Metrics API를 polling한다. receiver는 resource group,
`Microsoft.EventHub/namespaces` service와 승인된 metric 이름으로 제한한다. 현재
upstream에서 metrics stability가 alpha이므로 Collector version과 image digest를
고정하고 startup·수집 회귀 검증을 둔다.

### Diagnostic Settings 비교 경로

Premium namespace의 export 가능한 platform metrics를 별도 Standard telemetry Event
Hubs namespace로 보낸다. 동일 Collector의 `azureeventhubreceiver`가 managed
identity로 이 Event Hub를 소비하고 Blob checkpoint로 진행 상태를 보존한다. 이
경로는 API polling의 대체재가 아니라 export 가능 지표의 도착 지연과 record mapping을
비교하는 보조 경로다. telemetry sink namespace 자체에는 같은 diagnostic setting을
적용하지 않아 순환을 만들지 않는다.

### 실배포 fallback

`azuremonitorreceiver`가 실제 환경에서 시작 또는 수집에 실패하면
`webdevops/azure-metrics-exporter:26.10.0`을 활성화한다. exporter는 동일 managed
identity와 metric allowlist를 사용하고 Collector의 Prometheus receiver로 연결한다.
실패 증거를 보존한 뒤 fallback을 켜며, 정상 경로와 fallback 결과를 섞어 기본 경로가
성공한 것처럼 보고하지 않는다.

### lag 수집 경로

작은 lag exporter가 Event Hubs partition properties의
`last_enqueued_sequence_number`와 Blob checkpoint의 consumer sequence를 읽어
partition별 차이를 계산한다. 공개 metric은 검증 가능한 message lag만 사용한다.
checkpoint blob 수정 시각을 event lag seconds로 오해하지 않는다. checkpoint가 없는
partition, 빈 partition, consumer 재시작은 별도 상태 label과 test case로 처리한다.
Exporter의 Prometheus endpoint를 Collector의 Prometheus receiver가 수집한다.

### Dedicated 비생성 profile

기본 `azd up`은 Premium만 생성한다. 선택적인
`existingDedicatedClusterResourceId`가 주어지면 infrastructure를 추가 생성하지 않고
Collector allowlist에 `Microsoft.EventHub/clusters`와 `CPU`, `AvailableMemory`,
`ClusterUtilization`을 추가한다. dashboard는 `capacity_unit=CU`와 기존 cluster의
capacity 값을 사용한다. 이 profile은 실제 Dedicated cluster에서 실행하기 전까지
`documented-not-runtime-verified` 상태로 유지한다. 입력값이 없으면 관련 receiver와
panel을 생성하지 않아 빈 panel을 만들지 않는다.

## 전체 아키텍처

### Azure managed service 계층

- Event Hubs Premium namespace, 1 PU
  - workload Event Hub
  - workload consumer group
- Dedicated cluster는 생성하지 않음
  - 선택 입력으로 기존 cluster resource ID만 연결 가능
- Event Hubs Standard telemetry namespace
  - Diagnostic Settings sink Event Hub
  - Collector consumer group
- Storage Account
  - workload consumer checkpoint container
  - `azureeventhubreceiver` checkpoint container
- Azure Container Registry
- Key Vault
- Virtual Network
  - Gateway VM subnet
  - AKS node subnet

### Gateway VM 계층

하나의 Ubuntu 24.04 LTS VM에서 Docker Compose로 다음 컴포넌트를 격리 실행한다.

- OTel Collector Contrib `0.165.0`
- lag exporter
- 비활성 기본값의 Azure metrics fallback exporter `26.10.0`
- Grafana OSS `13.3.0`
- Playwright dashboard capture 도구

Collector는 각 source를 두 metrics pipeline으로 fan-out한다.

- scrape pipeline: Prometheus exporter endpoint 노출
- push pipeline: Prometheus remote write exporter가 AKS VMSingle에 전송

두 pipeline은 각각 `delivery_path=scrape|remote_write`를 붙인다. receiver 쪽에는
`source_path=azure_monitor_api|diagnostic_eventhub|lag_exporter|fallback_exporter`를
붙인다. 같은 receiver instance를 공유해 delivery 비교가 서로 다른 Azure API 호출의
차이가 되지 않게 한다.

### AKS 계층

Korea Central의 AKS 1.36 cluster에 다음을 배포한다.

- VictoriaMetrics Operator `0.75.2`
- VMSingle `1.155.0`
- VMAgent
- Collector VM private endpoint를 수집하는 `VMStaticScrape`
- synthetic producer
- slow consumer

VMSingle은 internal service로만 노출한다. Grafana는 같은 VNet에서 private endpoint를
통해 조회한다. VMAgent scrape와 Collector remote write가 같은 VMSingle에 저장할 때
`source_path`와 `delivery_path`가 항상 존재해 series collision을 막는다.

## 인증과 권한

### Gateway VM managed identity

- Premium namespace scope: `Monitoring Reader`
- workload Event Hub scope: `Azure Event Hubs Data Receiver`
- telemetry Event Hub scope: `Azure Event Hubs Data Receiver`
- checkpoint containers scope: `Storage Blob Data Reader`
- Key Vault scope: `Key Vault Secrets User`

### AKS workload identity

- producer identity:
  - workload Event Hub scope의 `Azure Event Hubs Data Sender`
- slow consumer identity:
  - workload Event Hub scope의 `Azure Event Hubs Data Receiver`
  - workload checkpoint container scope의 `Storage Blob Data Contributor`

Diagnostic Settings의 Event Hub authorization rule은 Azure service 전달에만 사용한다.
연결 문자열과 key는 deployment output, agent 로그, 문서에 출력하지 않는다. custom
workload는 connection string 대신 `DefaultAzureCredential`과 Workload Identity를
사용한다.

## 네트워크 경계

- Grafana `3000/tcp`와 AKS public API authorized IP range는 실행 중인 agent VM의
  현재 egress IP로 제한한다.
- SSH inbound는 열지 않는다. Gateway bootstrap과 진단은 cloud-init 및 Azure VM Run
  Command를 사용한다.
- Collector Prometheus endpoint는 AKS node subnet에서만 접근할 수 있다.
- VMSingle과 workload 서비스는 public IP를 만들지 않는다.
- Gateway VM outbound는 Azure Monitor, Event Hubs, Storage, Key Vault, ACR와 필요한
  upstream image registry에 한정하는 것을 목표로 하되, 실습에서 service tag로
  정확히 표현할 수 없는 registry egress 제한은 검증 결과에 명시한다.
- public screenshot에는 Grafana URL, 실제 IP, subscription/resource ID를 표시하지
  않는다.

## metric 의미와 dashboard 계약

| 질문 | 원본 metric 또는 계산 | aggregation | 시각화 |
|---|---|---|---|
| Premium replica CPU 상태 | `NamespaceCpuUsage` | Replica별 Average와 Maximum | gauge, time series |
| Premium replica memory 상태 | `NamespaceMemoryUsage` | Replica별 Average와 Maximum | gauge, time series |
| Dedicated cluster CPU 상태 | `CPU` | Role별 Maximum | gauge, time series |
| Dedicated cluster 가용 메모리 | `AvailableMemory` | Role별 Maximum | 역방향 threshold gauge, time series |
| Dedicated cluster 종합 사용률 | `ClusterUtilization` | cluster Average | preview 표기 gauge |
| 구간의 요청 수 | `IncomingRequests` | 1분 Total | stat, bars |
| 구간의 성공 요청 수 | `SuccessfulRequests` | 1분 Total | stat, bars |
| throttle 발생 여부 | `ThrottledRequests` | 1분 Total | stat, bars |
| 송신 방향 request 수 | Azure Monitor 미지원 | 계산하지 않음 | text panel |
| PU당 incoming messages | `IncomingMessages / processing_units` | EntityName별 1분 Total | stat, time series |
| PU당 outgoing messages | `OutgoingMessages / processing_units` | EntityName별 1분 Total | stat, time series |
| PU당 incoming bytes | `IncomingBytes / processing_units` | EntityName별 1분 Total | stat, time series |
| PU당 outgoing bytes | `OutgoingBytes / processing_units` | EntityName별 1분 Total | stat, time series |
| CU당 message·byte 처리량 | message·byte Total / 기존 cluster CU | 1분 Total | stat, time series |
| consumer lag | last enqueued sequence - checkpoint sequence | partition별 latest, max, sum | stat, bar gauge, time series |
| receiver 경로 차이 | source별 sample | freshness, count, value | status/table/time series |
| delivery 경로 차이 | delivery별 sample | freshness, count, value | status/table/time series |

0행과 값 0을 구분한다. `ThrottledRequests=0`은 series가 실제 존재하면 “관측 구간에
throttle 없음”이며, 누락 series를 0으로 치환하지 않는다. 모든 raw series를 먼저
보존하고 receiver별 이름 차이는 probe 이후 dashboard MetricsQL에서 비교한다.

## 부하와 lag 시나리오

1. producer를 시작해 여러 partition에 event를 지속 전송한다.
2. slow consumer는 producer보다 낮은 처리율과 주기적인 checkpoint로 lag를 만든다.
3. Azure Monitor 1분 지표가 도착할 충분한 시간 동안 workload를 유지한다.
4. producer를 중지하고 consumer를 유지해 backlog가 감소하게 한다.
5. partition별 Event Hubs property, Blob checkpoint, exporter metric을 같은 시점에
   수집해 계산을 대조한다.
6. fallback 전환은 별도 표시한 짧은 구간에서 수행한다.

Premium 1 PU를 강제로 throttle할 만큼 과도한 트래픽은 성공 조건이 아니다. 실제
series와 0값을 확인하면 충분하다. 부하 generator가 target을 설정했다는 사실과 실제
전송 처리량을 구분해 보고한다.

## agent dashboard workflow

기존 MovieLog 자료의 `probe → build → verify → look` 절차를 재사용한다.

### Probe

- receiver별 metric inventory
- unit, labels/dimensions, aggregation, sample period
- `source_path × delivery_path` 조합
- Premium의 PU당 계산 입력과 Dedicated profile의 CU당 계산 입력
- lag partition 값과 checkpoint 근거
- Collector receiver/exporter 자체 telemetry와 오류

### Build

agent는 panel을 만들기 전에 “답할 질문 / metric / MetricsQL / 시각화” 표를 만든다.
합계는 stat, 정상 범위는 gauge, 비교는 table/bar gauge, 추이만 time series를 사용한다.
dashboard JSON은 환경 식별자를 변수의 기본값으로 커밋하지 않는다.

### Verify

Grafana datasource API를 통해 모든 panel query를 실행한다. 오류, 0행, NaN/Inf,
예상 label 부재가 하나라도 있으면 dashboard를 수정하고 전체 query를 다시 실행한다.
scrape와 remote write의 값 비교는 동일한 절대 시간 범위를 사용한다.

### Look

Playwright가 Grafana에 로그인해 내부 scroll 전체 높이를 캡처한다. agent는 이미지를
직접 확인해 다음을 검사한다.

- 구독·resource ID·IP·hostname 노출
- 정상 값의 경고색
- 지원되지 않는 metric을 정상 panel처럼 표시
- legend와 label 가독성
- 현재 미완성 1분 bin의 동시 하락
- 빈 panel과 실제 0값의 혼동
- 대부분의 질문을 같은 꺾은선으로 표현한 단조로운 구성

최종 캡처는 실제 배포 화면이어야 하며 mockup이나 합성 숫자로 대체하지 않는다.

## azd 배포 계약

sample root의 `azure.yaml`은 Bicep provisioning과 local hooks를 연결한다.

1. preprovision: subscription, Korea Central, 현재 egress IP, principal 권한과 provider
   registration 확인
2. provision: network, identities, Event Hubs, Storage, ACR, Key Vault, AKS, Gateway VM,
   role assignments, diagnostic setting 생성
3. postprovision: AKS credentials, Workload Identity federation, image build/push,
   VictoriaMetrics Operator와 VMSingle/VMAgent 설치, Gateway bootstrap 확인
4. deploy: producer·consumer 시작, probe, lag 시나리오, query 검증, dashboard 생성과
   캡처
5. predown/postdown: 외부 또는 hook 생성 리소스 정리, `azd down --purge`, resource
   group 존재 재확인

`azd up`은 interactive secret 입력을 요구하지 않는다. Grafana 초기 password는
Key Vault에 생성하고 Gateway VM identity가 bootstrap 시 root-only 파일로 읽는다.
`.azure/`, 실행 evidence, live dashboard JSON과 credential 파일은 커밋하지 않는다.
Dedicated cluster는 어떤 `azd` hook이나 Bicep module에서도 생성하지 않는다. 기존
Dedicated 연결은 명시적인 resource ID 입력이 있을 때만 read-only 수집 설정을
추가하며, 기본 Premium 실습의 성공 조건과 분리한다.

## 공개 문서 구조

```text
docs/services/azure-event-hubs/
└── opentelemetry-victoriametrics-monitoring/
    ├── index.md
    ├── images/
    │   ├── architecture.png
    │   └── grafana-dashboard.png
    ├── lab/
    │   └── index.md
    └── samples/
        └── eventhubs-otel-victoriametrics-lab/
            ├── sample.yml
            ├── README.md
            ├── azure.yaml
            ├── infra/
            ├── gateway/
            ├── workloads/
            ├── k8s/
            ├── agent/
            └── tests/
```

`index.md`는 핵심 결론과 실제 dashboard 캡처를 먼저 제시하고 상세 명령을
`lab/index.md`로 보낸다. sample은 `kind: runnable`이며 `used_by`에 `index`와 `lab`을
지정한다. taxonomy에는 새 service `azure-event-hubs`와 technology
`victoriametrics`만 필요할 때 추가한다. `open-telemetry`, `grafana`와 목적 tag는 기존
통제 값을 재사용한다.

## 테스트와 검증

### 정적·단위 검증

- Bicep build/lint와 resource dependency 검사
- `azure.yaml` hook과 environment contract test
- Docker Compose config와 image reference 검사
- Kubernetes client dry-run 및 실제 cluster server-side dry-run
- lag 계산 unit test: 정상, checkpoint 없음, 빈 partition, 역전 sequence, consumer
  재시작
- dashboard JSON schema, query 변수, 환경 식별자 기본값 부재 test
- Collector config에서 두 receiver, source/delivery label, 두 exporter 존재 확인

### 실제 배포 검증

- Collector startup과 component health
- Azure Monitor API receiver의 모든 요구 metric series
- Diagnostic Event Hub receiver의 DS Export 가능 metric series
- scrape와 remote write의 동일 기간 sample
- producer 실제 전송량과 consumer 실제 처리량
- lag 상승 및 회복
- fallback exporter의 독립 수집
- VMSingle 재시작 뒤 data retention 범위
- Grafana 전체 panel query와 screenshot
- Dedicated profile의 config render와 metric-name contract test. 실제 Dedicated
  runtime series와 dashboard는 이번 배포의 검증 대상이 아님

### 저장소 검증

```bash
python -m pytest tests/docs -q
python scripts/docs/validate_metadata.py
python scripts/docs/validate_sources.py
python scripts/docs/validate_links.py
python scripts/docs/validate_public_safety.py
mkdocs build --strict
python scripts/docs/validate_search_index.py
```

sample 전용 unit/integration test와 Bicep/Compose/Kubernetes 검증도 별도로 실행한다.
생성된 `site/`와 실행 evidence는 커밋하지 않는다.

## 실패 처리와 정리

- 시작 전에 현재 managed identity의 resource group create와 role assignment write
  가능 여부를 실제 요청으로 확인한다.
- 권한이 부족하면 필요한 action과 정확한 scope만 보고하고 Owner 같은 포괄 권한을
  임의로 요구하거나 부여하지 않는다.
- receiver가 metric을 내지 않으면 dashboard의 `or vector(0)` 같은 표현으로 숨기지
  않고 수집 단계에서 실패시킨다.
- `azuremonitorreceiver` 실패 시 Collector 로그·health·Azure API 직접 query를
  보존한 뒤 fallback을 켠다.
- Diagnostic Settings 경로는 DS Export 가능한 metric만 판정 대상으로 삼는다.
- deployment가 중간 실패해도 cleanup hook과 직접 RG 삭제 fallback을 실행하고 Azure
  Resource Graph 또는 resource group GET으로 삭제를 재확인한다.
- `verification_status: verified`는 실제 배포, query, screenshot, cleanup이 모두
  확인된 뒤에만 사용한다.

## 버전과 근거 기준

초기 구현 기준은 다음과 같고 container image는 실제 배포 전에 digest로 고정한다.

- AKS Kubernetes: 1.36, Korea Central의 2026-11-09 비-preview 지원 버전
- OpenTelemetry Collector Contrib: 0.165.0
- VictoriaMetrics Operator: 0.75.2
- VictoriaMetrics: 1.155.0
- Grafana OSS: 13.3.0
- webdevops Azure Metrics Exporter: 26.10.0
- OTel Contrib source evidence: commit
  `b83eb00d069d77f9bd77c6c247dfcdaa3628cdc9`
- VictoriaMetrics Operator source evidence: commit
  `2310d100a016d65738f483f8191d9405ff6307b4`
- Azure Metrics Exporter source evidence: commit
  `d028c6742b28d76a64d47f365e5cc16c5ead9b82`

Azure 동작과 지원 여부는 Microsoft Learn 원문을 최종 기준으로 한다. OTel Collector
Contrib와 VictoriaMetrics의 component 동작은 version/commit 고정 upstream 문서와
실제 실행 결과를 함께 사용한다. 문서의 주장은 공식 문서, 실제 관측, 설계 권고로
구분한다.

## 핵심 공식·upstream 자료

- Azure Event Hubs monitoring data reference:
  <https://learn.microsoft.com/azure/event-hubs/monitor-event-hubs-reference>
- Azure Event Hubs partition load balancing and checkpointing:
  <https://learn.microsoft.com/azure/event-hubs/event-processor-balance-partition-load>
- Azure Event Hubs Premium overview:
  <https://learn.microsoft.com/azure/event-hubs/event-hubs-premium-overview>
- Azure Event Hubs Dedicated tier overview:
  <https://learn.microsoft.com/azure/event-hubs/event-hubs-dedicated-overview>
- OTel Contrib Azure Monitor Receiver:
  <https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/b83eb00d069d77f9bd77c6c247dfcdaa3628cdc9/receiver/azuremonitorreceiver>
- OTel Contrib Azure Event Hub Receiver:
  <https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/b83eb00d069d77f9bd77c6c247dfcdaa3628cdc9/receiver/azureeventhubreceiver>
- VictoriaMetrics OpenTelemetry integration:
  <https://docs.victoriametrics.com/victoriametrics/integrations/opentelemetry/>
- VictoriaMetrics Operator VMStaticScrape:
  <https://docs.victoriametrics.com/operator/resources/vmstaticscrape/>
