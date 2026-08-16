# 01. Azure SRE Agent 설정

포털에서만 할 수 있는 설정을 마치고, 그 사실을 실습 상태 파일에 기록하는 단계입니다. 여기까지 끝나야 S1을 시작할 수 있습니다.

## 시작 조건

- **이 저장소를 본인 계정으로 fork했습니다.** Agent에 연결하는 저장소는 fork여야 합니다. 아래 "연결할 원본"에서 설명하듯 조사 결과 이슈가 연결된 저장소에 생성되므로, 원본 저장소를 연결하면 참가자 전원의 이슈가 한곳에 쌓입니다.
- [README](../README.md)의 `azd up`이 성공했고 `/healthz`가 HTTP 200을 반환합니다.
- `https://sre.azure.com`에 로그인할 수 있고, 대상 구독에 Azure SRE Agent가 **Running** 상태로 하나 있습니다.
- 역할을 만들 수 있는 권한(Owner 또는 User Access Administrator)이 있습니다.
- 아래 값을 손에 들고 시작합니다.

```bash
cd monitor/sre-agent-event-lab
source ./scripts/lab-env.sh
```

`lab-env.sh`는 구독 ID, 리소스 그룹, 그리고 `origin` 원격에서 유추한 저장소 URL을 출력합니다. fork를 열었는지까지 확인하지는 않으므로, `Repository` 줄이 **본인 계정의 저장소**인지 직접 확인하세요. 원본 저장소가 찍혀 있다면 fork를 clone해 다시 시작합니다.

## 설정 페이지 열기

Agent를 열면 위쪽 상태 표시줄이 아직 연결하지 않은 데이터 원본 수를 보여 줍니다. 오른쪽 **Complete setup**을 누르면 설정 페이지로 이동합니다.

![Azure SRE Agent 포털 첫 화면. 위쪽 상태 표시줄에 주황색 글씨로 6 sources not configured가 뜨고 그 오른쪽에 Code, Logs, Deployments, Incidents, Azure resources, Knowledge files 여섯 항목이 점 표시와 함께 나열되며, 줄 끝에 Complete setup 링크와 Expand 화살표가 있다. 왼쪽 탐색에는 Activities, Builder, Monitor, Capabilities, Settings가 접힌 채로 있고 아래에 Favorites의 Team onboarding 항목이 보인다. 가운데는 Azure SRE Agent 로고와 질문 입력창이다.](../assets/official/portal-setup-status-bar.png)

> 출처: [Complete setup for Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/complete-setup)

설정 페이지에는 탭이 두 개입니다. 이 실습은 Azure 리소스와 지식 문서까지 연결해야 하므로 **Full setup** 탭을 사용합니다.

![설정 페이지 상단에 More context. Better investigations. 제목과 그 아래 Quickstart, Full setup 두 개의 탭이 있고 Quickstart 탭이 파란색으로 선택되어 있다. 첫 카드에는 SRE Agent doesn't know anything about your app 이라는 경고 문구와 아직 채워지지 않은 회색 진행률 막대가 있다. 그 아래 Code 카드와 Logs 카드에는 각각 Recommended 배지와 오른쪽 끝 파란색 더하기 버튼이 있다.](../assets/official/portal-complete-setup-page.png)

> 출처: [Complete setup for Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/complete-setup)

## 연결할 원본

| 원본 | 이 실습에서 넣는 값 | 왜 필요한가 |
|---|---|---|
| Code | **본인이 fork한 저장소**와 브랜치 (`source ./scripts/lab-env.sh`가 출력한 `Repository` 값) | 조사 결론이 코드와 최근 변경을 짚게 합니다 |
| Azure resources | `lab-env.sh`가 출력한 `Resource group` 값 | 메트릭·리소스 상태·Activity Log를 읽습니다 |
| Knowledge files | [runbooks/incident-response.md](../runbooks/incident-response.md) | 조사 순서와 금지 사항을 팀 규칙으로 강제합니다 |
| Incidents | Azure Monitor | 경고를 자동으로 받아 조사 스레드를 엽니다 |

저장소는 [Connect source code](https://learn.microsoft.com/azure/sre-agent/connect-source-code)로 연결합니다. 이슈·PR 조작까지 맡기려면 [GitHub connector](https://learn.microsoft.com/azure/sre-agent/setup-github-connector)를 추가로 설정하되, 토큰 값은 포털 입력창에만 넣고 이 저장소의 어떤 파일에도 남기지 않습니다.

**연결 대상은 반드시 본인 fork여야 합니다.** GitHub connector를 붙이면 Agent가 조사 결과를 **이슈로 생성**하는데, 그 이슈는 연결된 저장소에 만들어집니다. 원본 저장소를 연결하면 본인 실습의 장애 이슈가 원본에 쌓이고, 원본에 쓰기 권한이 없으면 연결 자체가 실패합니다.

## 역할 부여

Agent가 실습 리소스를 읽고 구독의 경고를 훑을 수 있어야 합니다. 범위를 넓히지 마세요.

| 대상 | 역할 | 범위 |
|---|---|---|
| Agent 시스템 할당 ID, 사용자 할당 ID | Reader | 실습 리소스 그룹 |
| 같은 두 ID | Monitoring Contributor | 구독 |

Monitoring Contributor는 [Azure Monitor 스캐너](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)가 요구하는 유일한 구독 범위 권한입니다. 할당 ID는 아래에서 기록해 두고 정리 단계에서 자동으로 제거합니다.

포털에서 확인한 두 관리 ID의 object ID를 넣고 역할을 만듭니다. Reader는 azd가 삭제할 리소스 그룹 범위이고, Monitoring Contributor 두 건만 구독 범위이므로 ID를 변수에 보관합니다.

```bash
SUBSCRIPTION_ID="$(azd env get-value AZURE_SUBSCRIPTION_ID)"
RESOURCE_GROUP="$(azd env get-value AZURE_RESOURCE_GROUP)"
SUBSCRIPTION_SCOPE="/subscriptions/${SUBSCRIPTION_ID}"
RESOURCE_GROUP_SCOPE="${SUBSCRIPTION_SCOPE}/resourceGroups/${RESOURCE_GROUP}"
AGENT_PRINCIPAL_ID="<Agent 시스템 할당 ID의 objectId>"
AGENT_UAMI_PRINCIPAL_ID="<Agent 사용자 할당 ID의 objectId>"
SRE_AGENT_ENDPOINT="https://<agent>.<region>.azuresre.ai"

az role assignment create \
  --assignee-object-id "${AGENT_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Reader" \
  --scope "${RESOURCE_GROUP_SCOPE}" \
  --output none
az role assignment create \
  --assignee-object-id "${AGENT_UAMI_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Reader" \
  --scope "${RESOURCE_GROUP_SCOPE}" \
  --output none

MONITORING_CONTRIBUTOR_ASSIGNMENT_ID="$(az role assignment create \
  --assignee-object-id "${AGENT_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Contributor" \
  --scope "${SUBSCRIPTION_SCOPE}" \
  --query id -o tsv 2>/dev/null || az role assignment list \
    --assignee-object-id "${AGENT_PRINCIPAL_ID}" \
    --role "Monitoring Contributor" \
    --scope "${SUBSCRIPTION_SCOPE}" \
    --query "[0].id" -o tsv)"
UAMI_MONITORING_CONTRIBUTOR_ASSIGNMENT_ID="$(az role assignment create \
  --assignee-object-id "${AGENT_UAMI_PRINCIPAL_ID}" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Contributor" \
  --scope "${SUBSCRIPTION_SCOPE}" \
  --query id -o tsv 2>/dev/null || az role assignment list \
    --assignee-object-id "${AGENT_UAMI_PRINCIPAL_ID}" \
    --role "Monitoring Contributor" \
    --scope "${SUBSCRIPTION_SCOPE}" \
    --query "[0].id" -o tsv)"
```

## Builder > Incident platform 연결

1. 왼쪽에서 **Builder > Incident platform**을 엽니다.
2. 드롭다운에서 **Azure Monitor**를 고릅니다.
3. **Quickstart response plan** 토글은 끕니다. 다음 절에서 직접 만듭니다.
4. **Save**를 누르고 연결이 끝날 때까지 기다립니다.

연결되면 오른쪽 위에 초록색 체크가 붙습니다. 경고는 몇 분 안에 흘러들기 시작합니다.

![왼쪽 탐색의 Builder 메뉴가 펼쳐져 Agent Canvas, Skills, Incident response plans, Scheduled tasks, Plugins, Hooks, Connectors, Knowledge base 항목이 보이고 그중 Incident response plans가 선택되어 있다. 오른쪽 위에는 초록색 체크 아이콘과 함께 Azure Monitor is connected 문구가 있다. 표에는 계획 한 건이 있고 Status 열은 On, Autonomy level 열은 Autonomous로 표시되며, 위쪽에는 New incident response plan, Refresh, Delete, Turn off 버튼과 Severity equals All 필터가 있다.](../assets/official/portal-incident-response-plans-list.png)

> 출처: [Tutorial: Automate incident response in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/automate-incidents)
>
> **주의.** 이 캡처의 Autonomy level 열은 공식 문서 화면 그대로 `Autonomous`입니다. 이 실습에서는 계획의 자율 수준을 반드시 `Review`로 고릅니다.

## 응답 계획 만들기

1. **Builder > Incident response plans**에서 **New incident response plan**을 누릅니다.
2. 이름을 정하고 심각도는 실습 경고와 같은 **Sev2**를 포함하도록 고릅니다.
3. 필터 미리 보기를 지나 마지막 단계로 갑니다.
4. 자율 수준을 **Review**로 고르고 저장합니다.

`Review`는 Agent가 진단은 스스로 하되 리소스 변경 전에 승인을 기다리는 모드입니다. 이 실습은 장애 주입과 복구를 스크립트가 통제하므로, 자율 모드를 고르면 Agent와 스크립트가 같은 리소스를 동시에 되돌리려 할 수 있습니다.

![응답 계획 마법사의 세 번째 화면. 왼쪽 단계 목록에서 Set up incident filters와 Preview filter results는 초록색 체크로 완료되어 있고 3번 Save response plan이 진행 중이다. 오른쪽에는 Choose agent autonomy level for this handler 문구 아래 Review (Default)와 Autonomous 두 개의 라디오 버튼이 설명과 함께 있으며 Autonomous 쪽이 파란 점으로 켜져 있다. 그 아래 Turn on deep investigation 항목의 Run deep investigation autonomously 체크박스는 비어 있고, 화면 맨 아래에 Back, Save, Cancel 버튼이 있다.](../assets/official/portal-response-plan-autonomy-step.png)

> 출처: [Tutorial: Automate incident response in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/automate-incidents)
>
> **주의.** 이 캡처는 공식 문서 화면이라 `Autonomous` 라디오 버튼이 켜져 있습니다. 같은 화면에서 이 실습은 `Review (Default)`를 고릅니다.

## 설정 값을 azd 환경에 저장

스크립트가 읽는 값은 모두 이름·경로·리소스 ID뿐이며 비밀 값이 아닙니다.

```bash
azd env set SRE_AGENT_NAME "<포털에 보이는 Agent 이름>"
azd env set SRE_AGENT_RESOURCE_ID "<az resource list로 확인한 Agent 리소스 ID>"
azd env set SRE_REPOSITORY_BRANCH "main"
azd env set SRE_KNOWLEDGE_PATH "runbooks/incident-response.md"

if [[ -n "${SRE_REPOSITORY_URL}" ]]; then
  azd env set SRE_REPOSITORY_URL "${SRE_REPOSITORY_URL}"
else
  echo "저장소 URL을 직접 지정하세요: azd env set SRE_REPOSITORY_URL \"https://github.com/<본인 계정>/<저장소>\"" >&2
fi
```

`SRE_REPOSITORY_URL`은 `source ./scripts/lab-env.sh`가 `origin`에서 유추한 값입니다. 원격 URL에 자격 증명이 들어 있으면 `lab-env.sh`가 값을 비워 두므로, 위 분기가 직접 지정하라고 알려 줍니다. 어느 경우든 **본인이 이슈를 만들 수 있는 저장소**여야 합니다.

토큰, 연결 문자열, 클라이언트 비밀은 azd 환경에도 저장하지 않습니다. 인증은 Agent의 관리 ID와 포털 OAuth 흐름이 처리합니다.

## 근거 파일 만들기

`evidence/agent-setup.json`은 Git에서 제외되며, 정리 단계가 되돌릴 대상을 이 파일에서만 읽습니다. 값은 모두 식별자와 엔드포인트 URL입니다.
아래 블록은 역할을 만든 위 블록과 같은 셸에서 실행해야 앞에서 설정한 변수와 할당 ID를 그대로 사용합니다.

```bash
mkdir -p evidence
cat > evidence/agent-setup.json <<JSON
{
  "agent_principal_id": "${AGENT_PRINCIPAL_ID}",
  "agent_user_assigned_principal_id": "${AGENT_UAMI_PRINCIPAL_ID}",
  "agent_endpoint": "${SRE_AGENT_ENDPOINT}",
  "monitoring_contributor_assignment_id": "${MONITORING_CONTRIBUTOR_ASSIGNMENT_ID}",
  "uami_monitoring_contributor_assignment_id": "${UAMI_MONITORING_CONTRIBUTOR_ASSIGNMENT_ID}"
}
JSON

jq -e \
  --arg scope "${SUBSCRIPTION_SCOPE}/providers/Microsoft.Authorization/roleAssignments/" \
  '(.monitoring_contributor_assignment_id | startswith($scope))
   and (.uami_monitoring_contributor_assignment_id | startswith($scope))
   and (.agent_principal_id | length > 0)
   and (.agent_user_assigned_principal_id | length > 0)
   and (.agent_endpoint | test("^https://[^<>]+$"))' \
   evidence/agent-setup.json >/dev/null || {
     echo "agent-setup.json is incomplete; re-check the principals, endpoint, and assignment IDs above." >&2
     false
   }
```

## 정상 상태 확인과 승인

장애를 주입하기 전에, 정상 상태의 요청이 Application Insights까지 도달하는지 확인합니다. 이 확인이 통과해야 S1을 시작할 수 있습니다. 텔레메트리가 도착하지 않는 워크로드에 장애를 넣으면, 주입한 장애와 원래부터 안 보이던 상태를 구별할 수 없기 때문입니다.

먼저 정상 부하를 넣습니다. 두 엔드포인트 모두 200이어야 합니다.

```bash
EVIDENCE_DIR="${PWD}/evidence/baseline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "${EVIDENCE_DIR}"

python3 scripts/loadgen.py "https://${APP_FQDN}/api/orders" \
  --requests 30 --concurrency 4 --expect-status 200 \
  --output "${EVIDENCE_DIR}/orders.json"

python3 scripts/loadgen.py "https://${APP_FQDN}/api/documents" \
  --requests 10 --concurrency 2 --expect-status 200 \
  --output "${EVIDENCE_DIR}/documents.json"
```

두 요청 종류가 워크스페이스에 보이는지 확인합니다. 수집에는 보통 2~5분이 걸리므로, 결과가 비어 있으면 잠시 뒤 다시 실행합니다.

```bash
az monitor log-analytics query \
  --workspace "${WORKSPACE_CUSTOMER_ID}" \
  --analytics-query "AppRequests | where AppRoleName == '${TELEMETRY_SERVICE_NAME}' | where TimeGenerated > ago(30m) | summarize count() by Name" \
  --output table
```

`/api/orders`와 `/api/documents`가 모두 보이면 통과입니다. 그 사실을 기록해야 S1이 열립니다.

```bash
python3 scripts/lab_state.py mark baseline_passed --evidence-dir "${EVIDENCE_DIR}"
```

마지막으로 Agent 설정을 승인합니다. 이 명령은 설정 값을 출력한 뒤 표준 입력으로 정확히 `acknowledge`를 받아야 기록합니다. 어떤 환경 변수로도 대체할 수 없습니다. 값이 하나라도 다르면 그대로 중단하고 위 단계로 돌아가세요.

```bash
python3 scripts/lab_state.py acknowledge-agent
```

저장소 연결, 지식 원본, incident platform, 응답 계획은 읽을 수 있는 공식 안정 API가 없으므로 위 표를 보고 포털에서 직접 확인하는 것이 유일한 방법입니다.

## 실패했을 때

| 증상 | 조치 |
|---|---|
| `app/.venv`가 없음 (다음 문서의 캡처 단계가 Pillow를 씁니다) | `azd up`의 postprovision 단계가 만들어 둡니다. 없거나 깨졌다면 로컬 문제이므로 바로 실행: `./scripts/setup-venv.sh` |
| 두 principal ID로 Reader 권한이 확인되지 않음 | 두 ID가 근거 파일과 같은지 확인하고 리소스 그룹에 Reader를 다시 부여합니다 |
| 쿼리에 요청이 보이지 않음 | 10분 더 기다린 뒤 다시 조회합니다. 계속 비어 있으면 `curl -sS -o /dev/null -w '%{http_code}\n' "https://${APP_FQDN}/healthz"`로 앱을 직접 호출해 봅니다 |
| `acknowledge-agent`가 기록되지 않음 | 입력한 단어가 정확한지, `azd env select`로 올바른 환경을 골랐는지 확인합니다 |
| 경고가 Agent에 도착하지 않음 | Monitoring Contributor 범위가 구독인지, 응답 계획이 `On`인지 확인합니다 |

## 다음 단계

첫 장애를 주입합니다: [02-scenario-s1.md](02-scenario-s1.md)
