# Prompt: customMetrics를 직접 조회한 뒤 Grafana 대시보드를 만들어 줘

아래 블록을 agent(GitHub Copilot 등)에 그대로 붙이고 `<...>`만 바꿉니다.
agent가 쓸 도구는 둘 중 하나를 고릅니다.

| 도구 경로 | 준비 | probe | 반영·확인 |
|---|---|---|---|
| Managed Grafana MCP | `vscode-mcp.json`처럼 `https://<grafana-endpoint>/api/azure-mcp` 등록, Entra OAuth 로그인 | `amgmcp_query_resource_log` | `amgmcp_dashboard_update`, `amgmcp_dashboard_inspect` |
| CLI toolkit | `az` 로그인된 터미널 | `kql.sh` + `*.kql` | `az grafana dashboard create`, `verify_panels.py`, `capture.mjs` |

MCP의 `amgmcp_query_resource_log`는 시간 범위를 보내지 않고 Grafana macro와
변수를 거부하므로 query 안에 `ago(...)`와 실제 값을 직접 씁니다.

```text
목표: Application Insights customMetrics에 들어오는 Micrometer 지표로 Grafana 대시보드를 만든다.
코드와 문서에 적힌 meter 이름을 믿지 말고, 실제로 들어온 데이터를 조회해서 결정한다.

환경
- Application Insights: <resource-group>/<app-insights-name>
- Grafana: Azure Managed Grafana <grafana-name> (Azure Monitor data source uid: <datasource-uid>)
- cloud_RoleName: <role-name>, meter prefix: <prefix>_
- 도구: Grafana MCP(amgmcp_query_resource_log, amgmcp_dashboard_update, amgmcp_dashboard_inspect)
  또는 samples/movielog-app/agent 의 kql.sh, build_dashboard.py, verify_panels.py, capture.mjs

규칙
- 읽기 전용 조회와 Grafana dashboard 생성·수정만 한다. 클러스터와 앱 설정은 바꾸지 않는다.
- connection string, subscription ID, resource ID를 출력·파일·스크린샷에 남기지 않는다.
- 각 단계 결과를 표로 요약하고, 다음 단계 결정의 근거를 한 줄로 적는다.

단계
1. inventory: 01-inventory.kql로 name·cloud_RoleName·행 수·instance 수를 조회한다.
   <prefix>_ 지표가 없으면 멈추고 주입된 agent 버전부터 확인한다(3.7.9 미만이면 Spring Boot 4 custom meter가 오지 않는다).
2. dimensions: 02-dimensions.kql로 dimension key와 값 개수를 조회한다.
   값 개수가 계속 늘어나는 dimension은 대시보드에 쓰지 말고 코드 수정 대상으로 보고한다.
3. value shape: 03-value-shape.kql로 metric별 행 주기와 valueCount 유무, 값 범위를 본다.
   Counter·DistributionSummary/Timer·Gauge를 구분하고 metric별 집계식을 표로 정한다.
   Pod마다 같은 값을 보내는 gauge(DB 합계 등)는 Pod 간 sum이 아니라 max를 쓴다.
4. design: panel마다 "답할 질문 / metric / 집계식 / 시각화"를 표로 먼저 제안한다.
5. build: build_dashboard.py를 고쳐 JSON을 만든다. bin은 max_of($__interval, 1m) 이상으로 한다.
6. verify: 모든 panel query를 실제로 실행한다. FAIL이나 0행이 하나라도 있으면 원인을 고치고 다시 실행한다.
   - CLI: verify_panels.py
   - MCP: amgmcp_dashboard_inspect(includeQueries) 결과의 KQL에서 macro를 ago(1h)와 1m으로 바꿔 amgmcp_query_resource_log로 실행
7. push: az grafana dashboard create --overwrite true 또는 amgmcp_dashboard_update로 올린다.
8. look: capture.mjs로 대시보드를 캡처해서 직접 보고 아래를 점검한다.
   - 식별자(subscription ID 등)가 화면에 보이는가
   - 정상 값이 경고색(빨강)으로 보이는가
   - legend가 "<column> <value>"처럼 읽기 어려운가
   - 시간축이 비어 보이거나 한 Pod에만 데이터가 몰리는가
   문제가 있으면 5단계로 돌아간다.
9. report: 최종 panel 목록, 각 집계식의 근거가 된 probe 결과, 남은 한계를 보고한다.
```

## 왜 이렇게 시키나

- 1~3단계는 agent가 추측으로 panel을 그리지 못하게 합니다. 실습에서 managed
  `3.7.7-aks`일 때는 1단계에서 `movielog_*`가 0건으로 나와 대시보드 작업 전에
  agent 버전 문제를 찾았습니다.
- 3단계의 표가 집계 오류를 막습니다. 실습에서 `movielog_*_stored` gauge는 두
  Pod가 같은 DB 값을 보내 sum이면 두 배가 됐습니다.
- 6단계는 렌더링 전에 KQL 오류를 잡습니다. 실습에서 `views`가 KQL 예약어라
  한 panel이 400으로 실패했습니다.
- 8단계는 query로는 보이지 않는 문제를 잡습니다. 실습에서 resource ID 변수에
  subscription ID가 노출됐고, stat 기본 threshold 때문에 정상 값이 빨갛게
  보였습니다.
