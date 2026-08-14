# 01. Azure SRE Agent 설정

포털에서만 할 수 있는 설정을 마치고, 그 사실을 실습 상태 파일에 기록하는 단계입니다. 여기까지 끝나야 S1을 시작할 수 있습니다.

## 시작 조건

- [README](../README.md)의 `azd up`이 성공했고 `/healthz`가 HTTP 200을 반환합니다.
- `https://sre.azure.com`에 로그인할 수 있고, 대상 구독에 Azure SRE Agent가 **Running** 상태로 하나 있습니다.
- 역할을 만들 수 있는 권한(Owner 또는 User Access Administrator)이 있습니다.
- 아래 값을 손에 들고 시작합니다.

```bash
cd monitor/sre-agent-event-lab
azd env get-value AZURE_SUBSCRIPTION_ID
azd env get-value AZURE_RESOURCE_GROUP
```

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
| Code | 이 저장소(`hellices/devguidesample`)와 브랜치 | 조사 결론이 코드와 최근 변경을 짚게 합니다 |
| Azure resources | `azd env get-value AZURE_RESOURCE_GROUP`이 출력한 리소스 그룹 | 메트릭·리소스 상태·Activity Log를 읽습니다 |
| Knowledge files | [runbooks/incident-response.md](../runbooks/incident-response.md) | 조사 순서와 금지 사항을 팀 규칙으로 강제합니다 |
| Incidents | Azure Monitor | 경고를 자동으로 받아 조사 스레드를 엽니다 |

저장소는 [Connect source code](https://learn.microsoft.com/azure/sre-agent/connect-source-code)로 연결합니다. 이슈·PR 조작까지 맡기려면 [GitHub connector](https://learn.microsoft.com/azure/sre-agent/setup-github-connector)를 추가로 설정하되, 토큰 값은 포털 입력창에만 넣고 이 저장소의 어떤 파일에도 남기지 않습니다.

## 역할 부여

Agent가 실습 리소스를 읽고 구독의 경고를 훑을 수 있어야 합니다. 범위를 넓히지 마세요.

| 대상 | 역할 | 범위 |
|---|---|---|
| Agent 시스템 할당 ID, 사용자 할당 ID | Reader | 실습 리소스 그룹 |
| 같은 두 ID | Monitoring Contributor | 구독 |

Monitoring Contributor는 [Azure Monitor 스캐너](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)가 요구하는 유일한 구독 범위 권한입니다. 할당 ID는 아래에서 기록해 두고 정리 단계에서 자동으로 제거합니다.

## Builder > Incident platform 연결

1. 왼쪽에서 **Builder > Incident platform**을 엽니다.
2. 드롭다운에서 **Azure Monitor**를 고릅니다.
3. **Quickstart response plan** 토글은 끕니다. 다음 절에서 직접 만듭니다.
4. **Save**를 누르고 연결이 끝날 때까지 기다립니다.

연결되면 오른쪽 위에 초록색 체크가 붙습니다. 경고는 몇 분 안에 흘러들기 시작합니다.

![왼쪽 탐색의 Builder 메뉴가 펼쳐져 Agent Canvas, Skills, Incident response plans, Scheduled tasks, Plugins, Hooks, Connectors, Knowledge base 항목이 보이고 그중 Incident response plans가 선택되어 있다. 오른쪽 위에는 초록색 체크 아이콘과 함께 Azure Monitor is connected 문구가 있다. 표에는 계획 한 건이 있고 Status 열은 On, Autonomy level 열은 Autonomous로 표시되며, 위쪽에는 New incident response plan, Refresh, Delete, Turn off 버튼과 Severity equals All 필터가 있다.](../assets/official/portal-incident-response-plans-list.png)

> 출처: [Tutorial: Automate incident response in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/automate-incidents)

## 응답 계획 만들기

1. **Builder > Incident response plans**에서 **New incident response plan**을 누릅니다.
2. 이름을 정하고 심각도는 실습 경고와 같은 **Sev2**를 포함하도록 고릅니다.
3. 필터 미리 보기를 지나 마지막 단계로 갑니다.
4. 자율 수준을 **Review**로 고르고 저장합니다.

`Review`는 Agent가 진단은 스스로 하되 리소스 변경 전에 승인을 기다리는 모드입니다. 이 실습은 장애 주입과 복구를 스크립트가 통제하므로, 자율 모드를 고르면 Agent와 스크립트가 같은 리소스를 동시에 되돌리려 할 수 있습니다.

![응답 계획 마법사의 세 번째 화면. 왼쪽 단계 목록에서 Set up incident filters와 Preview filter results는 초록색 체크로 완료되어 있고 3번 Save response plan이 진행 중이다. 오른쪽에는 Choose agent autonomy level for this handler 문구 아래 Review (Default)와 Autonomous 두 개의 라디오 버튼이 설명과 함께 있으며 Autonomous 쪽이 파란 점으로 켜져 있다. 그 아래 Turn on deep investigation 항목의 Run deep investigation autonomously 체크박스는 비어 있고, 화면 맨 아래에 Back, Save, Cancel 버튼이 있다.](../assets/official/portal-response-plan-autonomy-step.png)

> 출처: [Tutorial: Automate incident response in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/automate-incidents)

## 설정 값을 azd 환경에 저장

스크립트가 읽는 값은 모두 이름·경로·리소스 ID뿐이며 비밀 값이 아닙니다.

```bash
azd env set SRE_AGENT_NAME "<포털에 보이는 Agent 이름>"
azd env set SRE_AGENT_RESOURCE_ID "<az resource list로 확인한 Agent 리소스 ID>"
azd env set SRE_REPOSITORY_URL "https://github.com/<owner>/<repo>"
azd env set SRE_REPOSITORY_BRANCH "main"
azd env set SRE_KNOWLEDGE_PATH "runbooks/incident-response.md"
```

토큰, 연결 문자열, 클라이언트 비밀은 azd 환경에도 저장하지 않습니다. 인증은 Agent의 관리 ID와 포털 OAuth 흐름이 처리합니다.

## 근거 파일 만들기

`evidence/agent-setup.json`은 Git에서 제외되며, 정리 단계가 되돌릴 대상을 이 파일에서만 읽습니다. 값은 모두 식별자와 엔드포인트 URL입니다.

```bash
cat > evidence/agent-setup.json <<'JSON'
{
  "agent_principal_id": "<Agent 시스템 할당 ID의 objectId>",
  "agent_user_assigned_principal_id": "<Agent 사용자 할당 ID의 objectId>",
  "agent_endpoint": "https://<agent>.<region>.azuresre.ai",
  "monitoring_contributor_assignment_id": "/subscriptions/<id>/providers/Microsoft.Authorization/roleAssignments/<guid>",
  "uami_monitoring_contributor_assignment_id": "/subscriptions/<id>/providers/Microsoft.Authorization/roleAssignments/<guid>"
}
JSON
```

## 점검과 승인

```bash
./scripts/lab.sh doctor
./scripts/lab.sh baseline
./scripts/lab.sh acknowledge agent-setup
```

`doctor`가 출력하는 네 줄은 언제나 `MANUAL`입니다. 저장소 연결, 지식 원본, incident platform, 응답 계획을 읽을 수 있는 공식 안정 API가 없기 때문입니다. 나머지 검사에 `FAIL`이 남아 있으면 먼저 해결합니다.

`acknowledge agent-setup`은 설정 값을 출력한 뒤 표준 입력으로 정확히 `acknowledge`를 받아야 기록합니다. 어떤 환경 변수로도 대체할 수 없습니다. 값이 하나라도 다르면 그대로 중단하고 위 단계로 돌아가세요.

## 실패했을 때

| 증상 | 조치 |
|---|---|
| `doctor`의 Reader 검사가 `FAIL` | 두 principal ID가 근거 파일과 같은지 확인하고 리소스 그룹에 Reader를 다시 부여합니다 |
| `baseline`이 telemetry 없음으로 종료 | 10분 더 기다린 뒤 다시 실행합니다. 계속 실패하면 `azd env get-value AZURE_CONTAINER_APP_FQDN`으로 앱을 직접 호출해 봅니다 |
| `acknowledge`가 기록되지 않음 | 입력한 단어가 정확한지, `azd env select`로 올바른 환경을 골랐는지 확인합니다 |
| 경고가 Agent에 도착하지 않음 | Monitoring Contributor 범위가 구독인지, 응답 계획이 `On`인지 확인합니다 |

## 다음 단계

첫 장애를 주입합니다: [02-scenario-s1.md](02-scenario-s1.md)
