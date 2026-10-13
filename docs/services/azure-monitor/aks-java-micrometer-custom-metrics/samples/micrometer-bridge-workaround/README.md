# Spring Boot 4 Micrometer workarounds

이 sample은 Spring Boot 4와 AKS Application Monitoring managed
`3.7.7-aks` 조합에서 검증한 두 임시 대응을 제공합니다.

1. **권장:** checksum-pinned standalone 3.7.9 jar를 ACR init image로 공급
2. **코드 옵션:** managed 3.7.7이 만든 existing Azure Monitor registry를
   Spring `MeterRegistry` bean으로 노출

application image에 jar를 직접 포함하는 PoC 방식은 포함하지 않습니다.

## 안전 행렬

| agent 구성 | bridge flag | 결과 |
|---|---:|---|
| managed `3.7.7-aks` | `true` | 지원하는 bridge 옵션 |
| custom `3.7.9` | `true` | 금지: registry unavailable과 CrashLoop 실측 |
| custom `3.7.9` | `false` | 권장 custom init 구성 |
| managed `3.7.9+` | `false` | agent auto-configuration에 위임 |

## 파일

| 파일 | 용도 |
|---|---|
| `Dockerfile` | 권장 3.7.9 init image를 build하고 SHA-256을 검증합니다. |
| `helm/values.yaml` | managed/custom mode와 optional bridge flag 기본값입니다. |
| `helm/values.schema.json` | custom 3.7.9 mode에서 bridge `false`를 강제합니다. |
| `helm/templates/deployment.yaml` | custom init path와 managed bridge env를 상호 배타적으로 렌더링합니다. |
| `src/main/.../AzureMonitorMeterRegistryBridgeConfiguration.java` | 선택적 feature-flagged bridge입니다. |
| `src/test/` | registry 노출, startup fail과 future-agent takeover test입니다. |
| `pom.xml` | Spring Boot 4.0.0 기반 bridge test입니다. |

## 1. 권장 3.7.9 init image build

기존 mutable tag의 존재 여부만으로 image를 재사용하지 않습니다.
version-controlled Dockerfile로 build한 뒤 manifest digest를 기록합니다.

```bash
set -euo pipefail

ACR_NAME="<acr-name>"

az acr build \
  --registry "$ACR_NAME" \
  --image observability/applicationinsights-agent:3.7.9 \
  --file Dockerfile \
  .

AGENT_DIGEST="$(az acr manifest show-metadata \
  --registry "$ACR_NAME" \
  --name observability/applicationinsights-agent:3.7.9 \
  --query digest \
  --output tsv)"
[[ "$AGENT_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]]

AGENT_IMAGE="${ACR_NAME}.azurecr.io/observability/applicationinsights-agent@${AGENT_DIGEST}"
```

build 또는 digest 조회가 실패하면 Helm upgrade를 실행하지 않습니다.

## 2. custom 3.7.9 mode 배포

실제 Spring Boot application image를 필수로 지정합니다.

```bash
APP_IMAGE_REPOSITORY="<application-image-repository>"
APP_IMAGE_TAG="<application-image-tag>"

helm lint ./helm \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG"

helm template example ./helm \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG" \
  --set monitoring.javaAgentMode=custom \
  --set monitoring.micrometerBridgeEnabled=false \
  --set-string monitoring.javaAgentImage="$AGENT_IMAGE"

helm upgrade --install example ./helm \
  --namespace apps \
  --create-namespace \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG" \
  --set monitoring.javaAgentMode=custom \
  --set monitoring.micrometerBridgeEnabled=false \
  --set-string monitoring.javaAgentImage="$AGENT_IMAGE"
```

custom mode에서 bridge를 `true`로 설정하면 values schema와 template이
render를 거부합니다. 이 조합은 실환경에서 registry unavailable 예외,
CrashLoop과 Helm timeout을 일으켰으며 auto-configuration 순서 annotation으로
안정적으로 back-off하지 않았습니다. rendered Pod에는 다음이 있어야 합니다.

- `instrumentation.opentelemetry.io/inject-java: "false"`
- custom init container 한 개
- agent jar용 `emptyDir`와 app read-only mount
- `JAVA_TOOL_OPTIONS=-javaagent:...`
- Secret 기반 connection string, self-diagnostics와 resource attributes

환경 변수는 정확히
`APPLICATIONINSIGHTS_METRICS_TO_LOGANALYTICS_ENABLED=true`를 사용합니다.
3.7.7/3.7.9 agent와 공식 AKS smoke test는 `LOGANALYTICS`를 한 단어로
사용합니다. `APPLICATIONINSIGHTS_METRICS_TO_LOG_ANALYTICS_ENABLED`처럼
underscore를 추가한 변형은 사용하지 않습니다.

## 3. application bridge test

관리형 onboarding을 유지하면서 code로 해결하려는 경우에만 bridge를
선택합니다. Java 17 이상과 Maven 3.9 이상을 사용합니다.

```bash
mvn test
```

bridge는 agent 내부 type을 import하지 않고 runtime class 이름만 비교합니다.
flag가 `true`인데 registry가 없으면 startup을 실패시킵니다.
이 runtime class 이름 의존을 허용할 수 없는 환경에서는 bridge를 선택하지
말고 권장 custom 3.7.9 init image를 사용합니다.

## 4. application에 bridge import

`AzureMonitorMeterRegistryBridgeConfiguration`을 application source에
복사하고 명시적으로 import합니다.

```java
import com.example.observability.AzureMonitorMeterRegistryBridgeConfiguration;
import org.springframework.boot.autoconfigure.ImportAutoConfiguration;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@ImportAutoConfiguration(AzureMonitorMeterRegistryBridgeConfiguration.class)
public class Application {
}
```

Actuator dependency는 유지하되 `/actuator/metrics` HTTP endpoint를 외부에
노출할 필요는 없습니다.

## 5. managed 3.7.7 + bridge 배포

Portal namespace-wide onboarding이면
`monitoring.managedInstrumentationRef=true`를 사용합니다. named
`Instrumentation` CR이면 그 이름 또는 `namespace/name`을 사용합니다.

```bash
helm template example ./helm \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG" \
  --set monitoring.javaAgentMode=managed \
  --set monitoring.micrometerBridgeEnabled=true \
  --set-string monitoring.managedInstrumentationRef=true

helm upgrade --install example ./helm \
  --namespace apps \
  --create-namespace \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG" \
  --set monitoring.javaAgentMode=managed \
  --set monitoring.micrometerBridgeEnabled=true \
  --set-string monitoring.managedInstrumentationRef=true
```

rendered Pod에는 managed annotation과 다음 environment가 있어야 합니다.
custom init container와 agent volume은 없어야 합니다.

```text
MANAGEMENT_APPLICATION_INSIGHTS_MICROMETER_BRIDGE_ENABLED=true
```

flag가 `true`인데 agent registry가 없으면 application startup이
`Application Insights AzureMonitorMeterRegistry is unavailable`로
실패합니다.

## 6. managed 3.7.9+ 전환

bridge option을 사용했다면 agent upgrade와 **같은 Helm rollout**에서
bridge를 끕니다.

```bash
helm upgrade --install example ./helm \
  --namespace apps \
  --create-namespace \
  --set-string image.repository="$APP_IMAGE_REPOSITORY" \
  --set-string image.tag="$APP_IMAGE_TAG" \
  --set monitoring.javaAgentMode=managed \
  --set monitoring.micrometerBridgeEnabled=false \
  --set-string monitoring.managedInstrumentationRef=true
```

`@ConditionalOnMissingBean`만으로는 configuration 순서에 따른 같은 이름의
bean definition 충돌을 막지 못할 수 있습니다. 3.7.9+에서 bridge를
`true`로 남기지 마세요.

## 검증

두 방식 모두 다음을 확인합니다.

1. 실제 agent는 하나만 시작합니다.
2. restart 0과 health baseline을 유지합니다.
3. gauge, counter, timer와 dimension의 positive sample을 확인합니다.
4. 같은 합성 transaction의 각 metric이 한 번씩만 export되는지 확인합니다.
5. 합성 데이터를 정리하고 read-after-delete를 확인합니다.

## 정리

sample release를 설치했다면 제거합니다.

```bash
helm uninstall example --namespace apps
```

ACR image는 다른 workload가 사용하지 않는지 확인한 뒤 조직의 retention
절차로 정리하세요.
