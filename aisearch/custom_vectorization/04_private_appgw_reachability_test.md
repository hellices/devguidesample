# Private-only App Gateway 앞단으로 AI Search 도달 가능 여부 검증

> 가설: AKS Internal LB 앞에 **Private-only** Application Gateway (Public IP 없음)를
> 둬도, **Azure AI Search** 인덱서/벡터라이저가 그 사설 IP로 도달할 수 없다.
>
> 결론: **도달 불가**. 실제 인덱서 실행 결과에서 TCP connect timeout 발생.

## TL;DR

- AppGW를 Private-only (Public IP 없음, frontend = VNet 내 IP만)로 띄움.
- VNet **내부**에서는 정상: AppGW → Internal LB → mock-embed → 200.
- AI Search 인덱서는 Web API Skill을 통해 같은 사설 IP(`https://10.50.1.10/api/embed`)로 호출:
  - 응답: `"transientFailure"` / `statusCode=400`
  - 상세: **"A connection attempt failed because the connected party did not properly respond after a period of time"** (TCP connect timeout)
- 이유: AI Search는 멀티테넌트 환경에서 실행되며, 고객 VNet 내 사설 IP에 도달하려면 **Shared Private Link(SPL)** 가 있어야 함. SPL은 정해진 리소스 타입만 지원하고 **Application Gateway는 그 목록에 없음**. 따라서 Private-only AppGW는 AI Search 입장에서 보이지 않음.

이는 `02_custom_vectorization.md` / `03_gpu_vllm_rag_guide.md` 에서 다룬 통합 흐름 중
"AI Search → 사설 임베딩 엔드포인트" 경로에는 **반드시 Public/SPL 접근이 필요**함을 실증한다.

§7에서 후속 검증: **Function App을 AppGW 앞단에 두고 SPL(`groupId=sites`) 로 연결하면 양쪽 모두 public 차단 상태에서도 작동**(인덱서 success 5/0). 단 SKU ≥ Standard(S1) + `executionEnvironment=private` 필수. `private` 실행 환경에서도 AppGW 사설 IP로의 직접 호출은 여전히 TCP timeout (= "내 VNet 진입"이 아니라 "SPL 전용 풀"이라는 의미 확인).

---

## 1. 테스트 토폴로지

```
                +-----------------------------+
                |  Azure AI Search (multi-    |
                |  tenant control+data plane) |
                +--------------+--------------+
                               |  (no path)
                               x  TCP timeout
                               |
   +---------- VNet 10.50.0.0/16 -----------------------+
   |                                                    |
   |  snet-appgw 10.50.1.0/24 (delegated to AGW)        |
   |   +------------------------+                       |
   |   | AppGW v2  Private-only |  fe=10.50.1.10        |
   |   | listener-http  :80     |                       |
   |   | listener-https :443    |                       |
   |   +-----------+------------+                       |
   |               | backend pool: 10.50.2.250          |
   |               v                                    |
   |  snet-aks 10.50.2.0/23                             |
   |   +------------------------+                       |
   |   | AKS  (Azure CNI)       |                       |
   |   |  Internal LB 10.50.2.250                       |
   |   |   -> mock-embed pod    |                       |
   |   +------------------------+                       |
   |                                                    |
   +----------------------------------------------------+
```

### 1.1 Resource Group

| Resource | Name | Note |
| --- | --- | --- |
| RG | `rg-appgw-priv-test` | koreacentral |
| VNet | `vnet-appgw-priv` | 10.50.0.0/16 |
| Subnet | `snet-appgw` | 10.50.1.0/24, `Microsoft.Network/applicationGateways` 위임 |
| Subnet | `snet-aks` | 10.50.2.0/23 |
| Subnet | `snet-pe` | 10.50.4.0/24, PE policies disabled |
| AKS | `aks-appgw-priv` | 1× D2as_v5, Azure CNI |
| AppGW | `agw-priv` | Standard_v2, Private-only (Public IP 없음), frontend 10.50.1.10 |
| AI Search | `ais-priv-50764` | Basic, `publicNetworkAccess=Enabled` |
| Storage | `saappgwpriv1362` | source blob, RBAC only |

### 1.2 Private-only AppGW 핵심 조건

- 구독 feature 등록 필요:
  ```bash
  az feature register --namespace Microsoft.Network --name EnableApplicationGatewayNetworkIsolation
  az provider register -n Microsoft.Network
  ```
- AppGW 서브넷에 위임 필요:
  - delegation: `Microsoft.Network/applicationGateways`
- Frontend IP 구성에 `publicIPAddress` 없이 `privateIPAddress` + `privateIPAllocationMethod=Static`만.
- Azure CLI 2.86 기준 `az network application-gateway create` 에 `--frontend-ip-type Private` 옵션이 없으므로
  **ARM template** 으로 생성 (실제 사용한 템플릿은 `/tmp/appgw-priv-test/agw-private.json` 형식, 본 문서 §5 참고).
- 생성 후 검증:
  ```bash
  az network application-gateway show -g rg-appgw-priv-test -n agw-priv \
    --query '{state:provisioningState, opState:operationalState, fe:frontendIPConfigurations[]}' -o json
  # => provisioningState=Succeeded, operationalState=Running, publicIPAddress=null
  ```

---

## 2. VNet 내부 reachability — PASS

AKS 내 `jump` pod(curlimages/curl)에서 :

| 대상 | 결과 |
| --- | --- |
| `http://10.50.2.250/` (Internal LB 직결) | HTTP 200 `{"status":"ok"}` |
| `http://10.50.1.10/` (AppGW HTTP) | HTTP 200 `{"status":"ok"}` |
| `POST http://10.50.1.10/api/embed` (AppGW HTTP) | HTTP 200, 1024-dim vector |
| `https://10.50.1.10/` (AppGW HTTPS self-signed) | HTTP 200 `{"status":"ok"}` |
| `POST https://10.50.1.10/api/embed` (AppGW HTTPS) | HTTP 200, 1024-dim vector |

즉 AppGW 자체는 **정상 동작**.

---

## 3. AI Search에서의 도달 시도 — FAIL

### 3.1 사전 시도: HTTP

```json
"uri": "http://10.50.1.10/api/embed"
```

→ **400 Bad Request, 스킬셋 PUT 단계에서 거부**:

```
"One or more skills are invalid. Details: Error in skill 'embed-via-appgw':
 HTTPS is required in the 'uri' parameter"
```

→ Web API Skill / Custom Vectorizer는 **HTTPS scheme만 허용**. 컨트롤 플레인 검증.

### 3.2 HTTPS로 재시도

AppGW에 self-signed cert(IP SAN `10.50.1.10`)로 `listener-https`를 추가하고
`uri` 를 `https://10.50.1.10/api/embed` 로 변경 후 인덱서 실행:

```bash
POST https://ais-priv-50764.search.windows.net/indexers/ixr-priv-test/run?api-version=2024-07-01
```

30초 후 status:

```json
{
  "status": "running",
  "lastResult": {
    "status": "transientFailure",
    "itemsProcessed": 1,
    "itemsFailed": 1,
    "errors": [
      {
        "key": "localId=doc-1.txt&documentKey=doc-1.txt",
        "statusCode": 400,
        "name": "Enrichment.WebApiSkill.embed-via-appgw",
        "errorMessage": "Could not execute skill because Web Api skill response is invalid. ...",
        "details": "A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected host has failed to respond."
      }
    ]
  }
}
```

여기서 **`details` 문구가 핵심 증거** — AI Search 실행 노드 → `10.50.1.10:443` TCP connect 자체가 실패하여 timeout.

> 추가: self-signed cert가 원인이라면 TLS handshake 단계의 `RemoteCertificateNameMismatch` 또는
> `AuthenticationException` 류 메시지가 떴을 것. 여기서는 TLS 이전, **L3/L4 connect 실패**가 나왔으므로
> 원인은 cert가 아니라 **네트워크 도달 불가** 확정.

---

## 4. 왜 도달 불가인가

| 항목 | 내용 |
| --- | --- |
| AI Search 실행 평면 | 멀티테넌트, Microsoft 관리 VNet (subscription/region 단위 공용 pool) |
| 고객 VNet 사설 IP로 가는 길 | 기본 없음. 두 가지 옵션만 존재 |
| 옵션 A | **Shared Private Link**: AI Search → 고객 VNet의 Private Endpoint를 통해 도달. 단 SPL은 **정해진 `groupId` 목록**의 PaaS 리소스만 지원 |
| 옵션 B | 엔드포인트가 **Public**으로 노출 (FQDN/IP 도달 가능) + 필요 시 IP allowlist/auth로 보호 |

SPL이 지원하는 `groupId` 예시 (2024-07-01 API 기준): `blob`, `table`, `queue`, `file`, `dfs`, `sql`, `vault`, `Sql`, `mongoCluster`, `mysqlServer`, `documents` (Cosmos), `sites` (App Service/Functions), `account` (Cognitive Services), `cosmos`, `mongo`, `gateway` (API Management), `redis` 등.

→ **`Microsoft.Network/applicationGateways`** 도, **`Microsoft.ContainerService/managedClusters`** 도 SPL `groupId`로 존재하지 않음.

따라서 "AKS 앞단에 AppGW를 (Private이든 Public-IP-없는 형태로든) 두어 AI Search가 그것을 호출하게 하자"는
설계는 SPL로 풀리지 않으며, **유일한 실제 해결책은 엔드포인트를 Public scheme으로 노출**하는 것이다.

---

## 5. 재현 자료

테스트 중 사용한 핵심 파일 (`/tmp/appgw-priv-test/` 아래):

- `agw-private.json` — Private-only AppGW ARM template
- `mock-embed.yaml` — Internal LB(10.50.2.250) + 1024-dim 더미 벡터를 돌려주는 Python HTTP 서버
- `openssl-san.cnf`, `appgw.pfx` — IP SAN(10.50.1.10) 포함 self-signed cert
- `index.json`, `datasource.json`, `skillset.json`, `indexer.json` — AI Search 컴포넌트

핵심 스킬셋 정의 (실패 재현용):

```json
{
  "name": "ss-priv-test",
  "skills": [{
    "@odata.type": "#Microsoft.Skills.Custom.WebApiSkill",
    "name": "embed-via-appgw",
    "uri": "https://10.50.1.10/api/embed",
    "httpMethod": "POST",
    "timeout": "PT30S",
    "batchSize": 1,
    "context": "/document",
    "inputs": [{ "name": "text", "source": "/document/content" }],
    "outputs": [{ "name": "vector", "targetName": "embedding" }]
  }]
}
```

---

## 6. 권장 패턴 (관련 가이드와의 연결)

`03_gpu_vllm_rag_guide.md` 에서 다룬 vLLM-on-AKS RAG 흐름에는 두 가지 경로가 있다:

1. **인덱싱 시 임베딩** — AI Search 인덱서/Web API Skill → vLLM
2. **쿼리 시 임베딩** — AI Search Vectorizer → vLLM (Mode A) **또는** 클라이언트가 직접 vLLM 호출 후 vector를 AI Search에 전달 (Mode B)

본 실험의 결론을 적용하면:

- **Mode B (클라이언트 임베딩)** 채택 시 → 임베딩 엔드포인트가 사설/private-only여도 무방. AI Search는 임베딩을 호출하지 않음.
- **Mode A / 인덱서 호출** 채택 시 → 임베딩 엔드포인트는 반드시 다음 중 하나:
  - Public FQDN (예: `https://embed.example.com/api/embed`) + JWT/IP allowlist 등으로 인증
  - 또는 SPL이 지원하는 PaaS로 래핑 (예: API Management 앞에 두고 SPL 연결)

> **"AppGW를 (Private-only로) 띄워서 AI Search가 들어오게 하자"는 설계는 작동하지 않는다.** 이 문서가 그 실증 기록.

---

## 7. 후속 실증: Function 래핑 + Shared Private Link (`sites`)

§1~§6은 "AppGW를 직접 SPL로 연결할 수 없다"는 점만 보였다. 이 절은 **실제로 작동하는 우회로**를 끝까지 구성하고, 동시에 "혹시 `executionEnvironment=private`을 켜면 AppGW 사설 IP에 도달하지 않을까?"라는 자연스러운 후속 가설도 실증한다.

### 7.1 토폴로지 추가

```
  Azure AI Search (S1)  ───SPL(sites)──►  Function (Flex, public off)
   public off, PE→10.50.4.4                FQDN: fnemb-2276.azurewebsites.net
   executionEnvironment=private            VNet integ.: snet-func 10.50.5.0/26
                                                │
                                                ▼  (private proxy)
                                  AppGW 10.50.1.10 ──► AKS ILB ──► mock-embed
```

추가 리소스:

| 리소스 | 값 |
|--------|----|
| Function App | `fnemb-2276` (Flex Consumption, Python 3.11, MSI) |
| Function VNet integ. subnet | `snet-func` (10.50.5.0/26, delegated `Microsoft.Web/serverFarms`) |
| Function `publicNetworkAccess` | `Disabled` (lockdown) |
| AI Search S1 | `ais-priv-s1-eb52` (sku=standard, replica=1, partition=1) |
| S1 `publicNetworkAccess` | `Disabled` |
| S1 Private Endpoint | `pe-s1-search` in `snet-pe` (10.50.4.4) |
| SPL (Search → Function) | `spl-func-embed`, groupId `sites`, Approved/Succeeded |

### 7.2 왜 Basic SKU에서는 SPL을 만들어도 실제로 안 통하나

Basic에서 SPL 자체는 `Approved/Succeeded` 까지 진행되지만, 인덱서가 `Web Api response status: 'Forbidden'` (Function의 PNA-Disabled 페이지)을 계속 받았다. 원인:

```text
PUT /indexers/ixr-priv-test
  parameters.configuration.executionEnvironment = "private"
→ HTTP 400
  "Setting execution mode of indexer to 'Private' is unsupported for your search service SKU basic"
```

즉 Basic의 인덱서는 항상 multitenant 풀에서 실행되고, **그 풀은 SPL을 통한 PE 경로를 사용하지 않는다 (public DNS만 사용).** SPL 객체는 만들어지지만 "사용 가능한 indexer 실행 환경" 자체가 없으므로 실효 없음. 따라서 **AI Search에서 SPL을 인덱서가 실제로 사용하려면 최소 Standard(S1) 이상이 강제 조건이다.**

### 7.3 S1로 올린 뒤 `executionEnvironment=private` + SPL 결과

| 테스트 | skillset URI | Function 공개 | SPL | 결과 |
|--------|--------------|-------------|------|------|
| **A** | `https://fnemb-2276.azurewebsites.net/api/embed` | Disabled | Function 대상 (sites) | **success 5/0, 27초** |
| **B** | `https://10.50.1.10/api/embed` (AppGW 사설 IP 직격) | n/a | (SPL 불가능) | **transientFailure** — TCP timeout |

테스트 A 인덱서 실행 결과:

```json
{
  "status": "success",
  "itemsProcessed": 5,
  "itemsFailed": 0,
  "startTime": "2026-06-19T07:43:43.115Z",
  "endTime":   "2026-06-19T07:43:48.536Z",
  "errors": []
}
```

테스트 B 인덱서 실행 결과:

```json
{
  "status": "transientFailure",
  "itemsProcessed": 1,
  "itemsFailed": 1,
  "errors": [{
    "errorMessage": "Could not execute skill because Web Api skill response is invalid.",
    "details": "A connection attempt failed because the connected party did not properly respond after a period of time, or established connection failed because connected host has failed to respond."
  }]
}
```

### 7.4 결론 — `executionEnvironment=private` 의 실제 의미

`executionEnvironment: "private"`은 **"인덱서를 SPL 전용 격리 실행 풀에서 돌린다"** 는 뜻이지, **"내 VNet의 임의 사설 IP에 도달할 수 있다"** 는 뜻이 아니다.

- ✅ 해당 풀에서 도달 가능 = **SPL이 Approved된 PaaS 리소스의 PE 만**.
- ❌ 도달 불가 = SPL groupId가 정의되지 않은 모든 것 (Application Gateway, 임의 Internal LB IP, 직접 VM IP 등).

AppGW가 SPL 지원 목록에 없는 이상, `executionEnvironment=private`을 켜도 AppGW 사설 IP로는 못 간다. §1의 결론이 이 모드에서도 동일하게 유지됨이 실증되었다.

### 7.5 작동하는 우회 핵심 조건 (요약)

`AppGW 앞단에 Function App을 두고 SPL(sites)로 연결`하면 다음 조건을 모두 만족할 때 **양쪽 모두 public 차단 상태에서도** 인덱서가 임베딩에 도달 가능:

1. AI Search SKU ≥ Standard (S1) — `executionEnvironment=private` 지원.
2. 인덱서 `parameters.configuration.executionEnvironment = "private"`.
3. Function App에 SPL(`groupId=sites`) 생성, Function 측 PE를 **Approved** 로 승인.
4. Function App `publicNetworkAccess=Disabled` (네트워크 정책상 SPL PE 외엔 진입 불가).
5. Function 코드는 VNet 통합(`snet-func`)을 통해 AppGW 사설 IP로 프록시.
6. (선택) AI Search 자체도 PE + `publicNetworkAccess=Disabled` 로 완전 VNet 통합.

운영상 트레이드오프:
- Flex Consumption은 storage account `allowSharedKeyAccess=false` 환경에서도 식별자 기반(`AzureWebJobsStorage__accountName`, `AzureWebJobsStorage__credential=managedidentity`)으로 동작 가능. App Service Plan/Premium은 파일 공유 SMB를 요구하므로 동일 정책 환경에서는 사용 불가.
- SPL 승인 후 Search 실행 환경에서 PE DNS가 보이기까지 시간 차가 있을 수 있음 (이 실험은 PE 승인 즉시 27초 만에 success).
- S1 비용 (월 약 $250) 발생 — `private` 실행 환경과 Search 자체 PE 모두 S1 이상 필요.

### 7.6 재현 명령 핵심 발췌

```bash
# Function 만들기 (Flex Consumption, identity-based 스토리지)
az functionapp create -g $RG -n $FUNC --flexconsumption-location koreacentral \
  --runtime python --runtime-version 3.11 \
  --storage-account $SA --assign-identity \
  --deployment-storage-name $SA --deployment-storage-container-name app-package \
  --deployment-storage-auth-type SystemAssignedIdentity
az functionapp config appsettings delete -g $RG -n $FUNC --setting-names AzureWebJobsStorage
az functionapp config appsettings set -g $RG -n $FUNC --settings \
  AzureWebJobsStorage__accountName=$SA AzureWebJobsStorage__credential=managedidentity
az functionapp vnet-integration add -g $RG -n $FUNC --vnet vnet-appgw-priv --subnet snet-func

# 코드 zip 배포 후 호스트 키로 smoke test 통과 확인 (생략)

# Function public off
az resource update --ids $(az functionapp show -g $RG -n $FUNC --query id -o tsv) \
  --set properties.publicNetworkAccess=Disabled

# Search S1 + SPL
az search service create -g $RG -n $SEARCH_S1 --sku standard --location koreacentral
# SPL via ARM (data plane는 405 반환하므로 ARM endpoint 필수)
curl -X PUT "$ARM/.../sharedPrivateLinkResources/spl-func-embed?api-version=2024-06-01-preview" \
  -d '{"properties":{"privateLinkResourceId":"'$FUNC_ID'","groupId":"sites","requestMessage":"..."}}'
# Function 측 PE 승인
curl -X PUT "$ARM/.../privateEndpointConnections/$PE_NAME?api-version=2024-04-01" \
  -d '{"properties":{"privateLinkServiceConnectionState":{"status":"Approved","description":"..."}}}'

# Indexer: executionEnvironment=private 강제 (S1+ 필수)
curl -X PUT "$BASE/indexers/ixr-priv-test?api-version=2024-07-01" \
  -d '{..., "parameters":{"configuration":{"executionEnvironment":"private", ...}}, ...}'

# Search 자체도 private: PE + PNA off
az network private-endpoint create -g $RG -n pe-s1-search \
  --vnet-name vnet-appgw-priv --subnet snet-pe \
  --private-connection-resource-id $SEARCH_S1_ID --group-id searchService \
  --connection-name conn-s1-search
az search service update -g $RG -n $SEARCH_S1 --public-network-access disabled
```

---

## 8. Cleanup

```bash
az group delete -n rg-appgw-priv-test --yes --no-wait
```
