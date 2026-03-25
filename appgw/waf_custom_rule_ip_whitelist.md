# Application Gateway WAF: 경로 기반 IP 화이트리스트 설정 가이드

> Azure Application Gateway WAF v2에서 커스텀 룰을 사용하여 특정 경로에 대해 허용된 IP만 접근 가능하도록 설정하는 방법을 정리한 문서. AGW 레벨(전체 적용)과 리스너별 적용 두 가지 방식을 모두 다룬다.

---

## 개요

Application Gateway WAF v2의 커스텀 룰을 사용하면 다음 조합으로 트래픽을 제어할 수 있다:

- **소스 IP** (RemoteAddr)
- **요청 경로** (RequestUri)
- **HTTP 메서드** (RequestMethod)
- **헤더, 쿠키, 쿼리스트링** 등

이 문서에서는 **특정 경로(`/chat`)로 들어오는 요청을 허용된 IP 외에는 차단**하는 시나리오를 다룬다.

커스텀 룰의 로직:

```
IF   RequestUri Contains "/chat"          (조건 1: 경로 매칭)
AND  RemoteAddr NOT IPMatch <허용 IP>     (조건 2: 허용 IP가 아닌 경우)
THEN Block                                (403 Forbidden 응답)
```

> 커스텀 룰 내 모든 조건은 **AND**로 평가된다. 두 조건 모두 참일 때만 Block이 실행된다.

---

## 전제 조건

| 항목 | 요구사항 |
|---|---|
| Application Gateway | **WAF_v2** SKU |
| 상태 | **Running** (Stopped 상태에서는 설정 변경 불가) |
| WAF 정책 | AGW에 WAF 정책이 이미 연결되어 있어야 함 |

---

## AGW 레벨 vs 리스너별 적용

| 항목 | AGW 레벨 (방법 A) | 리스너별 (방법 B) |
|---|---|---|
| **적용 범위** | **모든 리스너** | 지정한 **리스너만** |
| **WAF 정책 수** | 기존 1개 사용 | 별도 정책 추가 생성 |
| **관리 복잡도** | 낮음 | 정책이 2개 이상 |
| **사용 시점** | 전체 리스너에 동일 룰 적용 | 리스너마다 다른 룰 필요 |

### WAF 정책 우선순위

```
리스너별 WAF 정책  >  AGW 레벨 WAF 정책
```

리스너에 별도 WAF 정책이 연결되면, AGW 레벨 정책은 해당 리스너에 **적용되지 않는다** (완전 대체). 리스너별 정책에서도 OWASP 관리 규칙이 필요하면, 정책 생성 시 `--type OWASP --version 3.2`를 별도로 지정해야 한다.

---

## 방법 A: AGW 레벨 — 기존 WAF 정책에 커스텀 룰 추가

기존 AGW에 연결된 WAF 정책에 커스텀 룰을 추가한다. **모든 리스너**에 적용된다.

### Step 1: 기존 WAF 정책 이름 확인

#### CLI

```bash
az network application-gateway show \
  --name <AGW_NAME> \
  --resource-group <RG_NAME> \
  --query "firewallPolicy.id" -o tsv
```

출력의 마지막 경로 세그먼트가 WAF 정책 이름이다.

#### 포탈

1. `Application Gateways → <AGW_NAME> → Overview`
2. **Properties** 또는 **Web application firewall** 항목에서 연결된 WAF 정책 이름 확인

---

### Step 2: 커스텀 룰 생성

#### CLI

```bash
az network application-gateway waf-policy custom-rule create \
  --policy-name <EXISTING_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --name <RULE_NAME> \
  --priority 10 \
  --rule-type MatchRule \
  --action Block \
  --match-conditions '[
    {
      "operator": "Contains",
      "values": ["/chat"],
      "variables": [{"variable-name": "RequestUri"}],
      "transforms": ["Lowercase"]
    },
    {
      "operator": "IPMatch",
      "negate": true,
      "values": ["<ALLOWED_IP>"],
      "variables": [{"variable-name": "RemoteAddr"}]
    }
  ]'
```

#### 포탈

1. Portal 검색창 → 기존 WAF 정책명 입력 → **Web Application Firewall policies** 선택
2. 왼쪽 메뉴 → **Custom rules** 클릭
3. **+ Add custom rule** 클릭
4. 룰 기본 설정:

   | 항목 | 값 |
   |---|---|
   | Custom rule name | 원하는 이름 |
   | Priority | `10` |
   | Rule type | Match |
   | Action | Block |

5. **조건 1 (경로)**:
   - Match type: `String`
   - Match variable: `RequestUri`
   - Operator: `Contains`
   - Transform: `Lowercase` 체크
   - Match values: `/chat`

6. **+ Add condition** 클릭 → **조건 2 (IP)**:
   - Match type: `IP address`
   - Match variable: `RemoteAddr`
   - **Negate**: `Does not` 체크
   - IP address or range: `<ALLOWED_IP>`

7. **Add** → 상단 **Save** 클릭

> Save를 누르지 않으면 룰이 저장되지 않는다.

---

### Step 3: WAF 정책 모드 확인

커스텀 룰이 실제로 트래픽을 차단하려면 WAF 정책이 **Enabled + Prevention** 상태여야 한다.

#### CLI

```bash
# 현재 상태 확인
az network application-gateway waf-policy show \
  --name <EXISTING_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --query "policySettings" -o json

# 필요 시 활성화 + Prevention 모드로 변경
az network application-gateway waf-policy policy-setting update \
  --policy-name <EXISTING_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --state Enabled \
  --mode Prevention
```

#### 포탈

1. WAF 정책 블레이드 → 왼쪽 메뉴 **Policy settings**
2. **State**: `Enabled` 확인
3. **Mode**: `Prevention` 확인 (Detection이면 로그만 남고 차단 안 됨)
4. 변경 시 **Save**

| 모드 | 동작 |
|---|---|
| `Detection` | 로그만 기록, 트래픽 통과 |
| `Prevention` | 매칭되면 실제 차단 (403) |

> **권장**: 처음에는 Detection으로 설정하여 로그를 확인한 뒤 Prevention으로 전환한다. 특히 프로덕션 환경에서는 비프로덕션 환경에서 먼저 규칙을 검증한 후 Prevention 모드를 적용할 것을 강력히 권장한다.

이것으로 AGW 레벨 설정이 완료된다. 추가 리스너 연결 작업은 불필요하다 (기존 AGW 정책이 이미 모든 리스너에 적용 중).

---

## 방법 B: 리스너별 — 별도 WAF 정책 생성 후 연결

특정 리스너에만 커스텀 룰을 적용하고, 나머지 리스너는 기존 AGW 레벨 정책을 유지하는 방법이다.

### Step 1: 새 WAF 정책 생성

#### CLI

```bash
az network application-gateway waf-policy create \
  --name <NEW_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --type OWASP \
  --version 3.2
```

#### 포탈

1. Portal 검색창 → **"Web Application Firewall policies"** → 클릭
2. **+ Create** 클릭
3. 설정:

   | 항목 | 값 |
   |---|---|
   | Policy name | 원하는 이름 |
   | Resource group | AGW와 동일한 리소스 그룹 |
   | Region | AGW와 동일한 지역 |

4. **Policy settings** 탭:
   - Policy mode: `Prevention`
   - Policy state: `Enabled`
5. **Review + create** → **Create**

---

### Step 2: 커스텀 룰 생성

방법 A의 Step 2와 동일한 절차. 대상 정책만 새로 생성한 `<NEW_WAF_POLICY_NAME>`으로 지정한다.

#### CLI

```bash
az network application-gateway waf-policy custom-rule create \
  --policy-name <NEW_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --name <RULE_NAME> \
  --priority 10 \
  --rule-type MatchRule \
  --action Block \
  --match-conditions '[
    {
      "operator": "Contains",
      "values": ["/chat"],
      "variables": [{"variable-name": "RequestUri"}],
      "transforms": ["Lowercase"]
    },
    {
      "operator": "IPMatch",
      "negate": true,
      "values": ["<ALLOWED_IP>"],
      "variables": [{"variable-name": "RemoteAddr"}]
    }
  ]'
```

#### 포탈

1. 생성된 WAF 정책 블레이드 → 왼쪽 **Custom rules**
2. **+ Add custom rule** 클릭
3. 방법 A Step 2의 포탈 절차와 동일하게 조건 1(경로), 조건 2(IP) 설정
4. **Add** → **Save**

---

### Step 3: WAF 정책 활성화 확인

정책 생성 시 포탈에서 Enabled + Prevention을 선택했다면 이미 완료. CLI로 생성한 경우 기본값이 Disabled + Detection이므로 변경 필요.

#### CLI

```bash
az network application-gateway waf-policy policy-setting update \
  --policy-name <NEW_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --state Enabled \
  --mode Prevention
```

#### 포탈

1. WAF 정책 블레이드 → **Policy settings**
2. State: `Enabled`, Mode: `Prevention` 확인 → **Save**

---

### Step 4: 리스너에 WAF 정책 연결

#### CLI

```bash
WAF_POLICY_ID=$(az network application-gateway waf-policy show \
  --name <NEW_WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --query id -o tsv)

az network application-gateway http-listener update \
  --gateway-name <AGW_NAME> \
  --resource-group <RG_NAME> \
  --name <LISTENER_NAME> \
  --waf-policy "$WAF_POLICY_ID"
```

#### 포탈

1. `Application Gateways → <AGW_NAME> → 왼쪽 메뉴 "Listeners"`
2. 대상 리스너 클릭
3. 하단 **WAF policy** 드롭다운에서 새로 생성한 정책 선택
4. **Save** (1~2분 소요)

이것으로 리스너별 설정이 완료된다. 해당 리스너에만 커스텀 룰이 적용되고, 나머지 리스너는 AGW 레벨 기본 정책을 유지한다.

---

## 검증 방법

### 설정 확인

#### CLI

```bash
# 리스너에 연결된 WAF 정책 확인
az network application-gateway http-listener show \
  --gateway-name <AGW_NAME> \
  --resource-group <RG_NAME> \
  --name <LISTENER_NAME> \
  --query "{name:name, firewallPolicy:firewallPolicy.id}" -o json

# 커스텀 룰 확인
az network application-gateway waf-policy custom-rule list \
  --policy-name <WAF_POLICY_NAME> \
  --resource-group <RG_NAME> -o json

# 정책 상태 확인
az network application-gateway waf-policy show \
  --name <WAF_POLICY_NAME> \
  --resource-group <RG_NAME> \
  --query "policySettings" -o json
```

#### 포탈

- **커스텀 룰**: 검색 → WAF 정책명 → **Custom rules** → 룰과 조건 확인
- **정책 상태**: 검색 → WAF 정책명 → **Policy settings** → Enabled / Prevention 확인
- **리스너 연결**: `Application Gateways → <AGW_NAME> → Listeners → <LISTENER_NAME>` → WAF policy 필드 확인
- **연결 현황**: 검색 → WAF 정책명 → **Associated application gateways** → 연결된 리스너 목록

### 트래픽 테스트

```bash
# 허용 IP에서 /chat 접근 → 200 OK 기대
curl -v http://<AGW_PUBLIC_IP>:<PORT>/chat

# 다른 IP에서 /chat 접근 → 403 Forbidden 기대

# 허용되지 않은 IP에서 다른 경로 → 200 OK 기대 (차단 대상 아님)
curl -v http://<AGW_PUBLIC_IP>:<PORT>/other-path
```

### WAF 로그 확인

Diagnostic settings에서 Log Analytics로 `ApplicationGatewayFirewallLog`를 전송하도록 설정한 경우:

```kusto
AzureDiagnostics
| where ResourceType == "APPLICATIONGATEWAYS"
| where action_s == "Blocked"
| project TimeGenerated, clientIp_s, requestUri_s, ruleName_s, message
| order by TimeGenerated desc
```

#### 포탈에서 진단 설정

1. `Application Gateways → <AGW_NAME> → Diagnostic settings`
2. **+ Add diagnostic setting** → `ApplicationGatewayFirewallLog` 체크
3. Destination: `Send to Log Analytics workspace` 선택 → **Save**

---

## 참고

### 커스텀 룰 match-conditions 연산자

| 연산자 | 설명 | 예시 |
|---|---|---|
| `IPMatch` | IP 주소 또는 CIDR 매칭 | `192.0.2.10`, `198.51.100.0/24` |
| `Contains` | 문자열 포함 여부 | RequestUri Contains `/chat` |
| `BeginsWith` | 문자열 시작 여부 | RequestUri BeginsWith `/api/` |
| `Equal` | 정확히 일치 | RequestMethod Equal `POST` |
| `Regex` | 정규식 매칭 | RequestUri Regex `^/api/v[0-9]+/` |
| `GeoMatch` | 국가 코드 매칭 | RemoteAddr GeoMatch `KR` |

### 여러 IP 허용

`values`에 여러 IP 또는 CIDR을 추가한다:

```json
"values": ["192.0.2.10", "198.51.100.0/24", "203.0.113.50"]
```

포탈에서는 IP address or range 필드에 쉼표 또는 줄바꿈으로 여러 개 입력한다.

### 여러 경로 차단

`values`에 여러 경로를 추가한다:

```json
"values": ["/chat", "/admin", "/api/internal"]
```

> `Contains` 연산자의 `values`는 **OR로 평가**된다. 하나라도 포함되면 매칭.

### Backend Pool은 IP 제한 용도가 아니다

| 구성요소 | 역할 |
|---|---|
| **Backend Pool** | 트래픽을 **보낼 곳** (백엔드 서버 IP/FQDN) |
| **WAF Custom Rule** | 트래픽을 **받을 때** 소스 IP 필터링 |

---

## 참고 링크

- [Azure Application Gateway WAF custom rules overview](https://learn.microsoft.com/en-us/azure/web-application-firewall/ag/custom-waf-rules-overview)
- [Create and use Web Application Firewall v2 custom rules](https://learn.microsoft.com/en-us/azure/web-application-firewall/ag/create-custom-waf-rules)
- [Associate a WAF policy with an Application Gateway listener](https://learn.microsoft.com/en-us/azure/web-application-firewall/ag/associate-waf-policy-existing-gateway)
- [Web Application Firewall CRS rule groups and rules](https://learn.microsoft.com/en-us/azure/web-application-firewall/ag/application-gateway-crs-rulegroups-rules)
