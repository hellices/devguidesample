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

- Azure CLI 로그인 및 대상 Azure 구독 접근 권한
- azd 로그인(`azd auth login`) — azd는 Azure CLI와 별도의 자격 증명을 사용한다
- 구독 또는 필요한 리소스에 Contributor, 역할 할당에는 Owner/User Access Administrator
- `az`, `azd`, `jq`, `curl`, `python3`
- `az` Log Analytics extension: `az extension add --name log-analytics` (`az monitor log-analytics query` 제공)
- 브라우저에서 `https://sre.azure.com` 및 `*.azuresre.ai` 접근
- Azure SRE Agent Korea Central 사용 권한
- GitHub 저장소 `hellices/devguidesample` 연결 권한

Azure SRE Agent Korea Central이 구독에 표시되지 않으면 [공식 registration request](https://github.com/microsoft/sre-agent/issues/new?labels=registration&title=Subscription+registration+request)를 제출해야 한다.

## 안전 경계

- 스크립트는 현재 azd 환경(또는 명시적 환경 변수)이 지정한 구독 ID를 `az account show`의 활성 구독과 일치하는지 검증한다.
- 기존 resource group을 재사용하지 않는다.
- resource group에 `purpose=sre-agent-event-lab`과 `azd-env-name=<현재 azd environment 이름>` 태그가 모두 일치하지 않으면 scenario와 cleanup을 거부한다.
- 한 번에 한 시나리오만 실행한다.
- `run-scenario.sh`는 종료 trap으로 장애 복구를 시도하고 복구 실패를 명시적으로 오류 처리한다.
- S3는 출력으로 기록된 Blob container scope의 단일 역할만 삭제·복구한다.
- Agent response plan은 모두 `Review` 모드로 구성한다.
- evidence에는 secret, connection string, access token을 저장하지 않는다.

## 안내형 단일 진입점: `lab.sh`

매 단계 azd output과 명령을 직접 조합하는 대신, 아래 단일 명령으로 환경 점검부터 채점까지 안내받을 수 있다. 각 하위 명령은 이 문서의 해당 절이 설명하는 스크립트를 그대로 호출하므로 동작은 동일하다.

```bash
monitor/sre-agent-event-lab/scripts/lab.sh doctor                  # 환경 점검 (아래 참고)
monitor/sre-agent-event-lab/scripts/lab.sh baseline                # Baseline 부하 및 telemetry 확인
monitor/sre-agent-event-lab/scripts/lab.sh acknowledge agent-setup # Agent 설정 수기 확인 기록 (대화형)
monitor/sre-agent-event-lab/scripts/lab.sh run s1|s2|s3            # 시나리오 실행 (run-scenario.sh와 동일)
monitor/sre-agent-event-lab/scripts/lab.sh capture s1|s2|s3        # 해당 실행이 기록한 evidence 디렉터리를 캡처
monitor/sre-agent-event-lab/scripts/lab.sh score                   # 수집한 evidence 채점
```

### 실행 순서와 `evidence/state.json`

명령은 위 순서대로만 진행된다. 진행 상태는 현재 azd 환경에 묶인 `monitor/sre-agent-event-lab/evidence/state.json`(Git 제외)에 원자적으로 기록되며, 다른 환경·구독·resource group에서 만든 state 파일은 거부된다.

- `run s1`은 `baseline`이 통과하고 `acknowledge agent-setup`이 기록된 뒤에만 시작한다.
- `run s2`/`run s3`는 직전 시나리오가 **복구**되고 **캡처**까지 끝난 뒤에만 시작한다.
- 복구는 workload가 다시 정상이고 그 실행이 발생시킨 alert가 Azure Monitor에서 `Resolved`로 확인된 뒤에만 기록된다. 둘 중 하나라도 시간 내에 확인되지 않으면 해당 실행은 실패로 기록되고 다음 시나리오는 계속 막힌다.
- 캡처는 Agent thread가 실제 결론을 낸 경우(`conclusion`)에만 성공으로 기록된다. `thread-not-created`, `investigation-missing`, `conclusion-missing`은 그대로 기록되며 다음 시나리오를 열어 주지 않는다.

`acknowledge agent-setup`은 대화형이다. 구성된 Agent 이름/리소스 ID, repository URL과 branch, knowledge 경로, response plan 모드, alert rule 이름(secret 아님)을 출력한 뒤 표준 입력으로 정확히 `acknowledge`를 입력해야 기록된다. 어떤 환경 변수로도 대체할 수 없다.

### `doctor` 점검 항목

`lab.sh doctor`는 `CHECK<TAB>STATUS<TAB>DETAIL` 형식으로 한 줄에 하나씩 점검 결과를 출력한다. `STATUS`는 `PASS`, `FAIL`, `MANUAL` 중 하나이며, `FAIL`이 하나라도 있으면 종료 코드 1을 반환한다. 필수 명령, `log-analytics` CLI extension, Azure CLI 로그인, azd 인증(`azd auth login --check-status`), azd 구성, 구독/리소스 그룹, Container App 상태, `/healthz`, Application Insights telemetry, alert rule 활성화, SRE Agent 리소스(설정된 경우), Reader 역할 할당을 공식 안정 API로 검증한다. Repository connection, Knowledge source, Incident platform, Response plan은 공식 API로 확인할 수 없으므로 항상 `MANUAL`로 표시되며 portal에서 직접 확인해야 한다.

점검 항목 중 세 가지는 실제 CLI 동작에 맞춰 해석해야 한다.

- **`log-analytics` extension**: `az monitor log-analytics query`는 core CLI에 포함되지 않는다. 없으면 telemetry 점검이 무의미하므로 별도 `FAIL` 행으로 보고하고 `az extension add --name log-analytics`를 안내한다.
- **azd 인증**: `azd auth login --check-status`는 로그인 여부와 무관하게 항상 종료 코드 0을 반환하므로, `--output json`의 `status` 값(`success`/`unauthenticated`)으로만 판정한다.
- **Reader 역할**: `az role assignment list`는 `--include-inherited` 없이는 상위 scope(구독 등)에서 상속된 할당을 보여주지 않는다. 상속된 Reader도 이 lab을 읽는 데 충분하므로 `PASS`로 처리하되, 리소스 그룹에 직접 할당된 경우와 상속된 경우를 DETAIL에서 구분해 표시한다.

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

배포는 `azd`가 담당한다. `azure.yaml`의 preprovision hook이 필수 provider를 등록하므로 별도 등록 명령은 필요 없다.

```bash
cd monitor/sre-agent-event-lab
azd env new sre-event-lab --location koreacentral
mkdir -p evidence
azd up 2>&1 | tee evidence/deploy.log
```

`azd env new`에 `--subscription`을 지정하지 않으면 azd가 로그인된 계정의 구독 목록에서 대화형으로 선택하도록 안내한다. 특정 구독을 고정하려면 `--subscription <YOUR_SUBSCRIPTION_ID>`를 추가한다(하드코딩된 예시 구독 ID를 그대로 복사해 사용하지 않는다).

`azd up`은 Bicep provision → ACR cloud build → Container App image 전환 순서로 진행된다. 로컬 Docker는 필요하지 않다. 초기 provision은 public placeholder image를 port 80으로 띄우고, postprovision hook이 ingress를 8000으로 옮긴 뒤 lab image로 교체한다. `scripts/deploy.sh`는 위 `azd up`을 호출하는 호환 wrapper로 남아 있다.

`monitor/sre-agent-event-lab/.env.example`은 스크립트가 읽는 설정 값의 이름과 허용 기본값만 문서화한 비밀 정보 없는 참고 파일이다(비밀 값은 커밋하지 않는다). 각 값은 `scripts/common.sh`의 `load_lab_config`가 "명시적 환경 변수 > `azd env get-value` > 허용된 기본값" 순서로 해석하므로, 로컬에서 다르게 override하려면 `.env.example`을 복사해 값을 채운 뒤 `export $(grep -v '^#' .env | xargs)`처럼 셸 환경에 불러오거나 `azd env set <NAME> <VALUE>`로 azd 환경에 저장한다.

성공 조건:

1. Bicep provision이 성공한다.
2. ACR에 `sre-event-lab:run-20260812T094446Z` 형식의 실행별 immutable image tag가 존재한다.
3. active Container App revision이 `Healthy`다.
4. `/healthz`가 HTTP 200을 반환한다.

## Azure SRE Agent 설정

실측 환경은 공식 ARM/data-plane API로 생성했다.

| 항목 | 값 |
|---|---|
| Subscription | `azd env new`에서 선택한 구독. 최초 실측값은 `validation-results.md` 참고 |
| Resource group | `rg-sre-agent-event-lab-krc` (최초 실측 실행; `azd`가 provision한 environment는 `azd env get-value AZURE_RESOURCE_GROUP`으로 확인) |
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
  --report-url "monitor/sre-agent-event-lab/validation-results.md" \
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
FQDN=$(azd env get-value AZURE_CONTAINER_APP_FQDN --cwd monitor/sre-agent-event-lab)

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

> ℹ️ **azd 환경 설정**: `run-scenario.sh`, `query-evidence.sh`, `capture-scenario.sh`, `cleanup.sh`는
> `scripts/common.sh`의 `load_lab_config`로 배포 output을 읽는다. `load_lab_config`는 각 값을
> "명시적 프로세스 환경 변수 > 현재 `azd env get-value` > 허용된 기본값" 순서로 해석하므로, 고정된
> 구독/리소스 그룹 값은 스크립트 안에 없다. `azd up`으로 provision한 현재 azd 환경(`azd env select`로
> 선택한 environment)을 대상으로 동작하며, 안전 장치로 대상 resource group에 `purpose=sre-agent-event-lab`과
> `azd-env-name=<현재 environment 이름>` 태그가 모두 일치해야 한다.

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
monitor/sre-agent-event-lab/scripts/lab.sh capture s1
```

evidence 디렉터리는 해당 시나리오 실행이 `state.json`에 기록한 값에서 결정되므로 경로를 직접 입력하지 않는다. 과거 실행을 다시 렌더링할 때만 디렉터리를 명시한다.

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

### `lab.sh score`

`lab.sh score`는 수집된 evidence만으로 위 표를 채점하고 `evidence/scorecard.json`과 `SCENARIO<TAB>CRITERION<TAB>STATUS<TAB>POINTS<TAB>DETAIL` 표를 출력한다.

판정 근거는 시나리오 evidence 디렉터리의 `conclusion-review.json`이다. 항목 ID(`impact_scope`, `direct_cause`, `actual_evidence`, `safe_minimum_mitigation`, `uncertainty`)마다 `{"met": true|false, "detail": "..."}`를 기록한다.

```json
{
  "impact_scope": { "met": true, "detail": "thread 2번 message가 ca-sre-lab의 /api/orders만 영향으로 특정" },
  "direct_cause": { "met": false, "detail": "원인을 배포 변경으로만 서술하고 FAILURE_MODE 변경을 지목하지 못함" }
}
```

- 해당 항목의 구조화된 판정이 없으면 `MANUAL`로 표시하고 **점수를 주지 않는다.** 사람이 직접 확인해 `conclusion-review.json`에 기록해야 점수가 반영된다.
- 캡처가 결론에 도달하지 못한 시나리오(`thread-not-created` 등)는 모든 항목이 `FAIL` 0점이며, 그 사유가 DETAIL에 남는다.
- 종합 판정은 모든 시나리오가 Partial 이상이고 두 개 이상 Pass일 때만 `PASS`다. `MANUAL`이 남아 있으면 `INCOMPLETE`로, 즉 미완료로 보고한다.

## 정리

`azd`로 배포한 환경은 `azd down`으로 정리한다. resource group 삭제는 `azd`가 수행하고, azd가 볼 수 없는 두 가지만 hook이 처리한다.

- predown hook `scripts/cleanup-external.sh --yes`: resource group 밖에 기록된 구독 범위 Monitoring Contributor assignment만 제거한다. 기록된 assignment ID가 현재 구독에 속하는지, Azure CLI가 그 구독에 로그인했는지, 실제 assignment의 principal·role·scope가 `evidence/agent-setup.json`의 기록과 일치하는지 확인한 뒤에만 삭제한다. 하나라도 어긋나면 아무것도 삭제하지 않고 중단한다. 기록이 없거나 이미 삭제된 assignment는 안전한 no-op다.
- postdown hook `scripts/cleanup-external.sh --reset-image-env --yes`: `azd-postprovision.sh`가 기록한 `SRE_CONTAINER_IMAGE`와 `SRE_IMAGE_TAG`를 비운다. predown이 아니라 postdown인 이유는 postdown이 `azd down`의 리소스 삭제가 실제로 성공한 뒤에만 실행되기 때문이다 -- 삭제 자체가 취소되거나 실패한 환경의 image 값을 미리 지우면 안 된다.

중요: predown hook은 `azd down`이 **삭제 확인 프롬프트를 띄우기 전에** 실행된다(azd의 command hook은 명령 전체를 감싸고, 그 확인 프롬프트는 명령 자체의 일부다). 즉 `azd down`을 실행하는 순간 기록된 Monitoring Contributor assignment는 이미 제거되며, 뒤이어 나오는 확인 프롬프트에서 **취소해도 이미 제거된 assignment는 되돌아오지 않는다**. resource group과 그 안의 리소스는 그대로 남지만, Agent의 구독 범위 role assignment는 사라진 상태가 된다 -- `azd down` 취소가 lab을 완전히 예전 상태로 되돌린다고 가정하면 안 된다. 취소한 뒤 lab을 계속 쓰려면 role assignment를 다시 만들고 `lab.sh acknowledge agent-setup`을 다시 실행해서 `evidence/agent-setup.json`을 새 assignment ID로 갱신해야 한다.

```bash
cd monitor/sre-agent-event-lab
azd down --purge
```

hook이 실패해 수동으로 다시 실행할 때는 아래처럼 직접 호출한다. 두 명령 모두 `--yes` 없이는 계획만 출력하며, 실행 위치와 무관하게 이 lab의 azd project(`--cwd`)를 대상으로 한다.

```bash
monitor/sre-agent-event-lab/scripts/cleanup-external.sh --yes
monitor/sre-agent-event-lab/scripts/cleanup-external.sh --reset-image-env --yes
```

`scripts/cleanup.sh`는 기존 명령을 유지하기 위한 호환 wrapper다. 기본 동작은 `cleanup-external.sh` 위임뿐이며 resource group을 삭제하지 않는다. azd environment를 잃어버린 lab을 손으로 정리해야 할 때만 `--legacy-delete-resource-group`으로 예전 삭제 경로를 사용한다. 이 경로도 구독 일치와 `purpose=sre-agent-event-lab`/`azd-env-name` 태그 확인을 거치며, 첫 명령은 dry-run이고 두 번째 명령만 삭제를 시작한다.

```bash
monitor/sre-agent-event-lab/scripts/cleanup.sh --legacy-delete-resource-group
monitor/sre-agent-event-lab/scripts/cleanup.sh --legacy-delete-resource-group --yes
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
