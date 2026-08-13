# Azure SRE Agent 이벤트 기반 장애 분석 실험실

제품 개요와 활용 방법은 [Azure SRE Agent 소개 자료](../azure-sre-agent.md)를 참고하세요. 이 문서에서는 실험 환경을 배포하고 장애를 재현하며 조사 근거를 수집하는 방법을 설명합니다.

Azure Container Apps에 의도적인 장애를 만들고, Azure Monitor 경고를 받은 Azure SRE Agent가 자동으로 조사하는지 실제 Azure 리소스에서 확인합니다.

## 구성

| 구성 요소 | 역할 |
|---|---|
| Container App | HTTP 500, latency, Blob dependency 장애 재현 |
| Application Insights | request, exception, dependency telemetry |
| Log Analytics | workspace 기반 Application Insights 및 Container Apps 로그 |
| Azure Monitor | Sev2 scheduled-query alert 3개 |
| Azure SRE Agent | 1분 scanner, incident 조사, Review-mode 완화 제안 |
| ACR / Storage | 이미지 저장 및 실제 managed identity dependency |

모든 workload 자산은 `rg-sre-agent-event-lab-krc`에 생성된다. SRE Agent의 Azure Monitor scanner에 필요한 구독 범위 `Monitoring Contributor`만 예외이며, 설정 시 assignment ID를 기록하고 정리 시 제거한다.

## 사전 조건

- Azure CLI 로그인 및 구독 `ME-MngEnvMCAP310512-inhwanhwang-3` 접근
- 구독 또는 필요한 리소스에 Contributor, 역할 할당에는 Owner/User Access Administrator
- `az`, `jq`, `curl`, `python3`
- 브라우저에서 `https://sre.azure.com` 및 `*.azuresre.ai` 접근
- Azure SRE Agent Korea Central 사용 권한
- GitHub 저장소 `hellices/devguidesample` 연결 권한

Azure SRE Agent Korea Central이 구독에 표시되지 않으면 [공식 registration request](https://github.com/microsoft/sre-agent/issues/new?labels=registration&title=Subscription+registration+request)를 제출해야 한다.

## 안전 경계

- 스크립트는 현재 구독 ID를 고정 검증한다.
- 기존 resource group을 재사용하지 않는다.
- resource group의 `purpose=sre-agent-event-lab` 태그가 없으면 scenario와 cleanup을 거부한다.
- 한 번에 한 시나리오만 실행한다.
- `run-scenario.sh`는 종료 trap으로 장애 복구를 시도하고 복구 실패를 명시적으로 오류 처리한다.
- S3는 출력으로 기록된 Blob container scope의 단일 역할만 삭제·복구한다.
- Agent response plan은 모두 `Review` 모드로 구성한다.
- evidence에는 secret, connection string, access token을 저장하지 않는다.

## 로컬 검증

```bash
cd monitor/sre-agent-event-lab/app
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q

cd ../../..
monitor/sre-agent-event-lab/app/.venv/bin/python -m pytest \
  monitor/sre-agent-event-lab/scripts/tests/test_loadgen.py -q
bash -n monitor/sre-agent-event-lab/scripts/*.sh
az bicep build --file monitor/sre-agent-event-lab/infra/main.bicep --stdout >/dev/null
```

## Azure 배포

필수 provider를 등록한다.

```bash
az account set --subscription 95933ae5-0201-4a21-a1fc-8051a7437982
for provider in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights \
  Microsoft.Storage Microsoft.ContainerRegistry Microsoft.ManagedIdentity; do
  az provider register --namespace "$provider" --wait
done
```

배포는 base infrastructure → ACR cloud build → Container App/alert 순서로 진행된다. 로컬 Docker는 필요하지 않다.

```bash
monitor/sre-agent-event-lab/scripts/deploy.sh \
  2>&1 | tee monitor/sre-agent-event-lab/evidence/deploy.log
```

성공 조건:

1. 두 Bicep deployment가 성공한다.
2. ACR에 `sre-event-lab:run-20260812T094446Z` 형식의 실행별 immutable image tag가 존재한다.
3. active Container App revision이 `Healthy`다.
4. `/healthz`가 HTTP 200을 반환한다.

## Azure SRE Agent 설정

실측 환경은 공식 ARM/data-plane API로 생성했다.

| 항목 | 값 |
|---|---|
| Subscription | `ME-MngEnvMCAP310512-inhwanhwang-3` |
| Resource group | `rg-sre-agent-event-lab-krc` |
| Agent name | `sre-devguidesample-95933ae5` |
| Region | Korea Central |
| Azure resource access | 테스트 resource group, Reader |
| Repository | `hellices/devguidesample` |
| Knowledge | `runbooks/incident-response.md` |
| Model | Microsoft Foundry / Automatic |
| Action mode | Review / Low |

### 실제 event bridge

제품의 표준 Azure Monitor 연계는 Azure Monitor incident platform과 response plan을 통해 Agent로 직접 전달되며 Logic App bridge가 필요하지 않다.

이 실험은 response plan 공개 API 자동 구성 제약 때문에 Azure SRE Agent의 HTTP Trigger 기능 앞에 Action Group + Logic App 인증 bridge를 둔 lab-specific 경로를 구성했다. 아래 bridge는 표준 도입의 필수 구성 요소가 아니다.

```text
Azure Monitor scheduled-query alert
  → Action Group (common alert schema)
  → Logic App request trigger
  → Logic App managed identity token
  → Azure SRE Agent HTTP Trigger (Review)
  → Agent thread / investigation
```

| 구성 | 값 |
|---|---|
| HTTP Trigger | `sre-lab-alerts`, Review |
| Logic App | `logic-sre-agent-alert-bridge` |
| Logic App role | SRE Agent Standard User, Agent scope |
| Action Group | `ag-sre-agent-event-lab` |
| Alert action | S1/S2/S3 모두 동일 Action Group |
| Common schema | Enabled |

중요: 2026-08-12 실측에서 HTTP Trigger endpoint는 `https://management.azure.com/` audience token을 HTTP 401로 거부하고 `https://azuresre.dev` audience token을 수락했다. Logic App HTTP action의 managed identity audience도 `https://azuresre.dev`로 설정해야 한다.

Agent principal, endpoint, subscription-scope assignment ID는 Git에서 제외되는 `monitor/sre-agent-event-lab/evidence/agent-setup.json`에 기록한다.

### Azure MCP

VS Code에서 `ms-azuretools.vscode-azure-mcp-server`와 `ms-azuretools.vscode-azure-github-copilot`을 설치하면 Resource Graph, Monitor, Policy/RBAC 등 구조화된 Azure 도구를 사용할 수 있다. extension 설치 후 VS Code window를 reload하고 Agent Mode의 tools 목록에서 Azure MCP Server를 확인한다.

## 티켓과 이메일 운영 output

S1 Agent conclusion에서 실제 GitHub Issue와 Outlook-compatible email draft를 생성했다.

- 실제 ticket: [GitHub Issue #43](https://github.com/hellices/devguidesample/issues/43)
- Issue body: `assets/notifications/s1-github-issue.md`
- HTML draft: `assets/notifications/s1-incident-summary.html`
- RFC 5322 email: `assets/notifications/s1-incident-summary.eml`
- Email preview: `assets/notifications/s1-email-preview.png`

artifact 재생성:

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python \
  monitor/sre-agent-event-lab/scripts/generate_notifications.py \
  --timeline monitor/sre-agent-event-lab/evidence/s1-20260812T080606Z/normalized-timeline.json \
  --output-dir monitor/sre-agent-event-lab/assets/notifications \
  --report-url "docs/superpowers/reports/2026-08-12-azure-sre-agent-event-testing-results.md (available after feature branch merge)" \
  --issue-url https://github.com/hellices/devguidesample/issues/43
```

이번 lab은 외부 수신자와 Outlook OAuth consent가 없으므로 email을 보내지 않고 `DRAFT`로 보존한다. Production에서는 Outlook managed connector의 Send email operation을 사용한다.

- `To`: User-defined parameter로 on-call distribution list에 고정
- `Subject`, `Body`: Agent-defined
- Review workflow: write operation을 `Ask`
- Autonomous workflow: `Ask`가 bypass될 수 있으므로 별도 최소권한 connector 사용

## Baseline

배포 output에서 FQDN을 확인하고 정상 요청을 만든다.

```bash
FQDN=$(az deployment sub show \
  -n sre-agent-event-lab-private \
  --query properties.outputs.containerAppFqdn.value -o tsv)

python3 monitor/sre-agent-event-lab/scripts/loadgen.py \
  "https://${FQDN}/api/orders" \
  --requests 30 --concurrency 4 --expect-status 200 \
  --output monitor/sre-agent-event-lab/evidence/baseline-orders.json

python3 monitor/sre-agent-event-lab/scripts/loadgen.py \
  "https://${FQDN}/api/documents" \
  --requests 10 --concurrency 2 --expect-status 200 \
  --output monitor/sre-agent-event-lab/evidence/baseline-documents.json
```

Application Insights의 `AppRequests`와 `AppDependencies`에 현재 데이터가 들어오고 세 alert가 Resolved인지 확인한다.

## 시나리오 실행

각 명령은 장애 주입, 제한 부하, alert polling, 복구, timeline 저장을 수행한다.

```bash
monitor/sre-agent-event-lab/scripts/run-scenario.sh s1
monitor/sre-agent-event-lab/scripts/run-scenario.sh s2
monitor/sre-agent-event-lab/scripts/run-scenario.sh s3
```

각 실행 후 다음 조건을 확인하기 전 다음 시나리오를 시작하지 않는다.

- 원래 endpoint가 정상 상태다.
- 해당 Azure Monitor alert가 Resolved다.
- SRE Agent incident thread의 첫 구조화 결론을 기록했다.
- `query-evidence.sh`로 동일 UTC 구간의 증거를 내보냈다.

증거 export:

```bash
monitor/sre-agent-event-lab/scripts/query-evidence.sh \
  s1 monitor/sre-agent-event-lab/evidence/s1-YYYYMMDDTHHMMSSZ \
  2026-08-12T00:00:00Z 2026-08-12T00:30:00Z
```

실제 timeline의 UTC 값을 사용해야 한다.

## SRE Agent 실제 동작 캡처

각 시나리오의 `timeline.json`이 생성된 뒤 다음 명령으로 Azure SRE Agent thread와 message를 API에서 수집하고 PNG/GIF/Markdown/Mermaid를 만든다.

```bash
monitor/sre-agent-event-lab/scripts/capture-scenario.sh \
  s1 monitor/sre-agent-event-lab/evidence/s1-20260812T051000Z
```

원본 API snapshot과 normalized timeline은 Git에서 제외되는 evidence 폴더에 남는다.

```text
monitor/sre-agent-event-lab/evidence/s1-20260812T051000Z/
  alert.json
  normalized-timeline.json
  thread-snapshots/
```

redaction을 통과한 시각 자료만 commit 대상이다.

```text
monitor/sre-agent-event-lab/assets/captures/s1/
  01-alert-fired.png
  02-thread-created.png
  03-investigating.png
  04-investigating.png
  05-investigating.png
  06-investigating.png
  07-conclusion.png
  investigation.gif
  timeline.mmd
  timeline.md
```

GIF frame 수와 크기를 확인한다.

```bash
monitor/sre-agent-event-lab/app/.venv/bin/python - <<'PY'
from PIL import Image

path = "monitor/sre-agent-event-lab/assets/captures/s1/investigation.gif"
with Image.open(path) as image:
    print({"frames": image.n_frames, "size": image.size})
    assert image.n_frames >= 4
    assert image.size == (1280, 720)
PY
```

Agent가 thread를 만들지 않았거나 조사 결론을 내리지 못한 경우에도 GIF는 빈 성공 화면을 만들지 않는다. `thread-not-created`, `investigation-missing`, `conclusion-missing` frame으로 누락 상태와 마지막 polling 시각을 표시한다.

### 선택: Portal UI 수동 녹화

UI 모양 자체를 보존해야 할 때만 API evidence와 별도로 녹화한다.

1. `https://sre.azure.com`에서 해당 incident thread를 연다.
2. macOS에서 `Shift+Command+5` → 선택한 부분 기록을 사용한다.
3. alert card → investigation plan → evidence → conclusion 순서로 30~60초 녹화한다.
4. 계정 메뉴, token, unrelated resource는 화면에 포함하지 않는다.
5. MP4를 GIF로 변환한다.

```bash
ffmpeg -i sre-agent-s1.mp4 \
  -vf "fps=8,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  monitor/sre-agent-event-lab/assets/captures/s1/portal-investigation.gif
```

Portal 녹화는 API evidence를 대체하지 않는다. 사실 판정은 `alert.json`, thread snapshots, KQL 결과를 기준으로 한다.

## Static Threshold에서 Dynamic Threshold로

이번 실험은 같은 날 세 장애를 결정론적으로 발생시키기 위해 1분 scheduled-query와 static threshold를 사용했다. 모든 S1/S2/S3 점수와 GIF는 static rule의 실측 결과다. Azure Monitor Dynamic Threshold는 장기 운영에서 정상 패턴을 학습해 anomaly를 찾는 다음 단계이며 이번 세션에서는 **미실증**이다.

| 기준 | Static | Dynamic |
|---|---|---|
| 목적 | known failure의 빠른 재현·hard limit 보호 | 시간대·일간·주간 baseline을 벗어난 anomaly |
| 준비 시간 | 즉시 | 최소 3일·30 samples |
| 학습 | 수동 threshold | 최근 10일 data, 3주 후 weekly seasonality |
| Log Search frequency | 1분 가능 | 1분 미지원, 5분 이상 |
| 운영 | deterministic safety rule | shadow 검증 후 adaptive alert |

### 후보 numeric signal

| Scenario | KQL 결과 | Dynamic 조건 |
|---|---|---|
| S1 | 5분당 5xx count 또는 error rate | upper bound 초과 |
| S2 | `/api/orders` p95 duration(ms) | upper bound 초과 |
| S3 | Blob 403 count 또는 failure rate | upper bound 초과 |

Boolean 식인 `count() > 10`이 아니라 `summarize ErrorCount=count()`처럼 numeric series를 반환해야 한다.

### 권장 시작값

- Frequency 5분, lookback 15~20분
- Sensitivity Medium, noise가 크면 Low
- 4회 평가 중 2회 위반
- 정상 telemetry 시작 UTC를 learning start로 지정
- action을 연결하지 않은 shadow mode로 시작
- 학습 gate 통과 후 기존 `ag-sre-agent-event-lab`을 연결해 같은 Logic App → Review-mode SRE Agent 경로 재사용

Dynamic rule은 3일·30 samples 전에는 발화하지 않으며 3주 전에는 weekly seasonality가 충분하지 않다. 최근 behavior change는 10일 baseline에 즉시 반영되지 않고 slowly evolving issue를 놓칠 수 있으므로, cold start·hard limit·보안 경계용 static rule을 함께 유지한다.

공식 자료: [Azure Monitor alerts with dynamic thresholds](https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-dynamic-thresholds)

## 판정

각 시나리오는 10점 만점이다.

| 항목 | 점수 |
|---|---:|
| 영향 범위 식별 | 2 |
| 직접 원인 식별 | 3 |
| 실제 증거 사용 | 2 |
| 안전한 최소 완화책 | 2 |
| 불확실성 표시 | 1 |

- Pass: 8-10
- Partial: 5-7
- Fail: 0-4

종합 성공은 모든 시나리오 Partial 이상, 두 개 이상 Pass, unauthorized autonomous action 0건이다.

## 정리

첫 명령은 dry-run이며 두 번째 명령만 삭제를 시작한다.

```bash
monitor/sre-agent-event-lab/scripts/cleanup.sh
monitor/sre-agent-event-lab/scripts/cleanup.sh --yes
```

정리 후 resource group 부재와 기록된 Monitoring Contributor assignment 제거를 별도로 확인한다.

## 공식 자료

- [Azure SRE Agent 제품 소개](../azure-sre-agent.md)
- [Incident response](https://learn.microsoft.com/azure/sre-agent/incident-response)
- [Root cause analysis](https://learn.microsoft.com/azure/sre-agent/root-cause-analysis)
- [Agent reasoning](https://learn.microsoft.com/azure/sre-agent/agent-reasoning)
- [Memory and knowledge](https://learn.microsoft.com/azure/sre-agent/memory)
- [Azure Monitor alerts in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)
- [Automate incident response](https://learn.microsoft.com/azure/sre-agent/automate-incidents)
- [Log Analytics and Application Insights connectors](https://learn.microsoft.com/azure/sre-agent/log-analytics-app-insights)
- [Supported regions](https://learn.microsoft.com/azure/sre-agent/supported-regions)
