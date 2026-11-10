---
name: grafana-metrics-dashboard
description: Application Insights customMetrics로 들어오는 Micrometer 지표를 직접 조회해 집계식을 정하고, Azure Managed Grafana 대시보드를 만들어 모든 panel query와 렌더링 화면까지 검증합니다. custom metric, Micrometer, customMetrics로 Grafana 대시보드를 만들거나 고칠 때 사용합니다.
---

# customMetrics 기반 Grafana 대시보드

코드와 문서에 적힌 meter 이름을 믿지 말고, Application Insights `customMetrics`에 실제로
들어온 데이터를 조회해서 panel과 집계식을 정한다. 대시보드는 모든 query 실행과 화면 확인을
통과한 뒤에만 완료로 보고한다.

## 시작 전에 사용자에게 받을 값

- Application Insights: `<resource-group>/<name>` 또는 resource ID
- Azure Managed Grafana: `<resource-group>/<name>`, Azure Monitor data source uid
  (두 resource group은 다를 수 있다. `az grafana` 명령에는 항상 Grafana의 resource group을 쓴다)
- `cloud_RoleName`과 meter prefix(예: `movielog_`). 모르면 1단계 inventory로 찾는다.
- Grafana에 직접 반영할지, JSON 파일만 만들지

## 도구

둘 중 사용할 수 있는 것을 쓴다.

| 경로 | 조회 | 반영·확인 |
|---|---|---|
| Managed Grafana MCP (`https://<grafana-endpoint>/api/azure-mcp`) | `amgmcp_query_resource_log` | `amgmcp_dashboard_update`, `amgmcp_dashboard_inspect` |
| 터미널(`az` 로그인) | `scripts/kql.sh` + `scripts/*.kql` | `az grafana dashboard create`, `scripts/verify_panels.py`, `scripts/capture.mjs` |

- `amgmcp_query_resource_log`는 시간 범위를 보내지 않고 Grafana macro와 변수를 거부한다.
  query 안에 `ago(...)`, `now()`와 실제 값을 직접 쓴다.
- `scripts/kql.sh`는 `METRIC_PREFIX` 환경 변수로 query의 `{{METRIC_PREFIX}}`를 바꾼다.
  `az monitor app-insights query`는 기본으로 최근 1시간만 조회하므로 지난 구간은
  `KQL_OFFSET=12h`처럼 늘린다.
- Grafana data plane API token은
  `az account get-access-token --resource https://dashboard.azure.com`으로 받는다.
  Azure Managed Grafana의 data plane audience는 `https://dashboard.azure.com`이며,
  `https://grafana.azure.com`으로 받은 token은 401로 거부된다.
- 지난 구간(예: 클러스터가 정지된 뒤)을 다룰 때
  - `*.kql`의 `timestamp > ago(30m)`를
    `timestamp between (datetime(<start>) .. datetime(<end>))`로 바꾸고, `KQL_OFFSET`을
    구간 시작부터 지금까지보다 길게 준다. `03-value-shape.kql`의 `30`은 구간 길이(분)로 바꾼다.
  - `verify_panels.py`에는 `--from <start> --to <end>`(ISO 8601 UTC)를 준다.
  - dashboard JSON의 `time`은 ISO 8601 UTC 문자열(예: `2026-11-07T23:05:00.000Z`)로 저장한다.
    epoch 문자열을 저장하면 Grafana 화면이 `Invalid date`로 해석한다. 캡처 URL의 `from`·`to`만
    epoch ms를 쓴다.
- `capture.mjs`는 Playwright Chromium이 필요하다. 없으면 작업 폴더 밖 임시 디렉터리에서
  `npm i playwright && npx playwright install chromium-headless-shell`로 준비한다.

## 규칙

- 읽기 전용 조회와 Grafana dashboard 생성·수정만 한다. 클러스터와 앱 설정은 바꾸지 않는다.
- connection string, subscription ID, resource ID를 출력·보고·스크린샷과 작업 폴더의 파일에
  남기지 않는다. 예외는 Grafana에 저장되는 dashboard 정의 하나다. 그 안에서만 resource ID를
  숨긴 변수 값으로 둔다.
- 작업 폴더나 저장소에 남기는 dashboard JSON은 resource ID 변수 값을 비운다. 값을 채운
  JSON이 반영에 필요하면 작업 폴더 밖 임시 파일로만 만들고, 반영 직후 지운다.
- 각 단계 결과를 표로 요약하고, 다음 단계 결정의 근거를 한 줄로 적는다.

## 단계

1. **inventory**: `01-inventory.kql`로 name·`cloud_RoleName`·행 수·instance 수를 조회한다.
   - prefix 지표가 없으면 멈추고 사용자에게 알린다. 주입된 Application Insights Java agent
     버전(Spring Boot 4는 3.7.9 이상 필요), annotation, meter 허용 목록을 확인하라고 안내한다.
   - 코드의 meter 목록과 비교해 빠진 meter가 있으면 그 이벤트가 구간 안에 일어났는지,
     배포된 image가 그 코드를 포함하는지 확인한다.
2. **dimensions**: `02-dimensions.kql`로 dimension key와 값 개수를 조회한다.
   값 개수가 계속 늘어나는 dimension은 대시보드에 쓰지 말고 코드 수정 대상으로 보고한다.
3. **value shape**: `03-value-shape.kql`로 metric별 행 주기, `valueCount`, 값 범위를 본다.
   metric별 집계식을 표로 정한다.
   - Counter: 모든 행이 `valueCount` = 1이고 `value`가 간격의 증가량 → `sum(value)`
   - DistributionSummary·Timer: `valueCount` > 1, `valueSum`이 합계 →
     `sum(valueSum) / sum(valueCount)`. 기록이 드물면 `valueCount`가 1뿐일 수 있으므로 코드의
     meter 종류로 확인한다.
   - Gauge: 시점 값. 시간으로 더하지 않는다. 여러 Pod가 같은 원천을 보고하는 gauge(DB 합계
     등)는 Pod 간 sum이 아니라 max를 쓴다. 각 Pod의 cache 갱신 시점이 달라 같은 분에도 값이
     조금 다를 수 있으므로, 원천이 같은지는 값이 아니라 코드로 판단한다.
4. **design**: panel마다 "답할 질문 / metric / 집계식 / 시각화"를 표로 먼저 제안하고
   사용자 확인을 받는다. 시각화는 질문 유형으로 고른다.
   - 구간 동안 몇 건인가 → stat(같은 bin의 sparkline 포함)
   - 값이 정상 범위인가 → gauge(도메인 기준을 threshold로)
   - 구성 비율은 → donut
   - 무엇이 많은가, Pod 간 쏠림은 → bar gauge
   - 시간에 따라 어떻게 변하는가 → time series(누적 area, bar, line)
   - Pod마다 빠진 지표가 없는가 → status history(누락 수, 0이 정상) 또는 table.
     기대 목록은 받은 데이터가 아니라 코드에서 시작할 때 등록하는 Counter·Gauge 이름으로
     고정한다. 처음 사용할 때 생기는 meter와 기록이 없으면 행이 없는 분포 meter는 뺀다.
5. **build**: dashboard JSON을 만든다.
   - bin은 `max_of($__interval, 1m)` 이상으로 한다.
   - 모든 panel query에서 채워지는 중인 현재 bin을 뺀다
     (`| where timestamp < bin(now(), <bin>)`).
   - Application Insights resource ID와 `cloud_RoleName`은 dashboard 변수로 둔다.
     작업 폴더에는 resource ID 변수 값이 빈 JSON만 저장한다. Grafana에 직접 반영할 때만
     값을 채우고 그 변수를 숨긴 사본을 임시 파일로 만든다(규칙 참고).
   - 건수 stat은 고정색, 크기만 비교하는 bar gauge는 중립 색 구간을 쓴다. threshold 색은
     도메인 기준이 있는 값에만 쓴다.
   - legend는 `displayName`에 dimension label을 쓴다. KQL 예약어(`views`, `first` 등)를
     column 이름으로 쓰지 않는다.
6. **verify**: 접힌 row 안의 panel까지 모든 panel query를 실제로 실행한다.
   HTTP 오류나 0행(숫자 field가 모두 null인 행 포함)이 하나라도 있으면 고치고 다시 실행한다.
   0은 정상 값이다.
   - 터미널: `scripts/verify_panels.py <dashboard.json> --appinsights-id <resource-id> --role <role>`
     (지난 구간은 `--from`·`--to` 추가)
   - MCP: `amgmcp_dashboard_inspect`(includeQueries)로 받은 KQL을 아래처럼 바꿔
     `amgmcp_query_resource_log`로 실행한다.
     - `$__timeFilter(<column>)` → `<column> > ago(1h)` (조건 전체를 바꾼다)
     - `$__interval` → `1m`, `$__timeTo()` → `now()`
     - `${role:singlequote}` 같은 변수 → 따옴표를 포함한 실제 값(예: `'movielog'`)
7. **push**: 값을 채운 임시 JSON으로
   `az grafana dashboard create -g <grafana-resource-group> -n <grafana-name> --definition @<temp-dashboard.json> --overwrite true`를
   실행하고 임시 파일을 지운다. MCP는 `amgmcp_dashboard_update`로 올린다.
   Grafana 쓰기 권한이 없거나 사용자가 파일만 원하면 resource ID 변수 값이 빈 JSON을 만들고
   import 방법
   (**Dashboards > Import** 또는 `az grafana dashboard import`)을 안내한다.
8. **look**: 대시보드를 캡처해서 직접 보고 아래를 점검한다. 하나라도 걸리면 5단계로 돌아간다.
   - 터미널: `GRAFANA_URL=... GRAFANA_TOKEN=... node scripts/capture.mjs "<path-and-query>" out.png`
     `capture.mjs`는 panel query 실패, `No data`·`Invalid date` 표시, 화면의 subscription·resource
     식별자를 발견하면 실패로 끝난다. 실패하면 캡처를 보지 않고 원인부터 고친다.
   - panel 간 합계를 비교할 캡처는 분 단위로 맞춘 절대 범위(`from`·`to` epoch ms)로 찍는다.
   - 점검 항목
     - subscription ID 같은 식별자가 화면에 보이는가
     - 정상 값이 경고색으로 보이는가
     - legend와 이름이 잘리거나 `<column> <value>`처럼 읽기 어려운가
     - 시계열이 오른쪽 끝에서 함께 떨어지는가
     - 같은 지표의 합계가 panel마다 다른가
     - 대부분 panel이 꺾은선이라 무엇을 답하는 panel인지 구분되지 않는가
9. **report**: 최종 panel 목록, 각 집계식의 근거가 된 조회 결과, 남은 한계를 보고한다.
