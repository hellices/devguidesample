# AKS Workload Identity로 Databricks Model Serving 키리스(Keyless) 호출

> 시나리오: AKS Pod → Databricks Foundation Model API (`databricks-meta-llama-3-1-8b-instruct`)
> 어떤 PAT/시크릿/Databricks OAuth secret도 사용하지 않고, **AKS Workload Identity**가 발급한 Entra ID(AAD) 액세스 토큰을 그대로 Databricks Bearer 토큰으로 사용합니다.
> APIM 가이드(`apim/databricks_keyless_managed_identity.md`)와 같은 인증 모델을 Pod-측에서 구현한 패턴.

---

## 인증 체인 (검증 완료)

```
Pod (SA: dbx-client)
  │ azure.workload.identity/use=true 라벨 → mutating webhook이 토큰 파일/env 주입
  │   AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_FEDERATED_TOKEN_FILE
  │
  ▼
@azure/identity DefaultAzureCredential
  │ projected SA JWT  →  AKS OIDC issuer가 서명
  │   ↓ Federated Credential (subject=system:serviceaccount:default:dbx-client)
  │ UAMI(applicationId = AZURE_CLIENT_ID)
  │
  ▼
Entra ID 토큰 엔드포인트 — audience: 2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default
  │ access_token (≈1h)
  │
  ▼
POST https://adb-<workspaceId>.<n>.azuredatabricks.net
       /serving-endpoints/<name>/invocations
       Authorization: Bearer <AAD access_token>
       Content-Type: application/json
  │
  ▼
Databricks: appid claim → SCIM SP(workspace-access entitlement) → 200 OK
```

핵심: **Databricks Serving 엔드포인트 호출은 SDK가 필요 없습니다.** 그냥 HTTP POST + Bearer.

---

## 사전 준비 (1회)

| 단계 | 명령 / 값 |
|---|---|
| AKS OIDC + Workload Identity | `az aks update -g <rg> -n <aks> --enable-oidc-issuer --enable-workload-identity` |
| UAMI 생성 | `az identity create -g <rg> -n uami-dbx-wi` → `clientId`, `principalId` 기록 |
| Federated Credential | `az identity federated-credential create --identity-name uami-dbx-wi -g <rg> -n fed-dbx --issuer <OIDC_ISSUER> --subject system:serviceaccount:default:dbx-client --audiences api://AzureADTokenExchange` |
| Databricks SP 등록 | `POST /api/2.0/preview/scim/v2/ServicePrincipals` body: `{"applicationId":"<UAMI clientId>","displayName":"aks-wi-dbx","active":true,"entitlements":[{"value":"workspace-access"}]}` |
| (PayGo/Custom 모델만) 권한 | `PUT /api/2.0/permissions/serving-endpoints/{endpoint_id}` → `CAN_QUERY` (FM 엔드포인트는 PATCH 불가, workspace-access 엔타이틀먼트로 충분) |

---

## 1) 앱 코드 (`server.js`)

```js
import http from "node:http";
import { Pool } from "undici";
import { DefaultAzureCredential } from "@azure/identity";

const DBX_HOST = process.env.DBX_HOST;                                          // https://adb-...azuredatabricks.net
const DBX_ENDPOINT = process.env.DBX_ENDPOINT || "databricks-meta-llama-3-1-8b-instruct";
const DBX_SCOPE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default";              // AzureDatabricks audience

const credential = new DefaultAzureCredential();                                // WI env 자동 사용
let cached = null;
async function getToken() {
  const now = Date.now();
  if (cached && cached.expiresOnTimestamp - now > 5 * 60_000) return cached.token;
  const t = await credential.getToken(DBX_SCOPE);
  cached = t;
  return t.token;
}

// keep-alive + HTTP/2 풀
const pool = new Pool(DBX_HOST, {
  connections: 16, pipelining: 1,
  keepAliveTimeout: 60_000, keepAliveMaxTimeout: 600_000, allowH2: true,
});

async function chat(prompt) {
  const token = await getToken();
  const res = await pool.request({
    path: `/serving-endpoints/${DBX_ENDPOINT}/invocations`,
    method: "POST",
    headers: {
      authorization: `Bearer ${token}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      messages: [{ role: "user", content: prompt }],
      max_tokens: 128, temperature: 0.2,
    }),
  });
  return { status: res.statusCode, body: await res.body.text() };
}

const server = http.createServer(async (req, res) => {
  if (req.url === "/healthz") { res.writeHead(200); return res.end("ok"); }
  if (req.method === "POST" && req.url === "/chat") {
    let buf = ""; for await (const c of req) buf += c;
    const { prompt } = JSON.parse(buf || "{}");
    const r = await chat(prompt || "Say hello.");
    res.writeHead(r.status, { "content-type": "application/json" });
    return res.end(r.body);
  }
  res.writeHead(404); res.end();
});
server.listen(8080);
```

`package.json`:

```json
{
  "name": "dbx-wi-client",
  "type": "module",
  "scripts": { "start": "node server.js" },
  "dependencies": {
    "@azure/identity": "^4.5.0",
    "undici": "^6.21.0"
  }
}
```

`Dockerfile`:

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY server.js ./
EXPOSE 8080
CMD ["node","server.js"]
```

빌드/푸시:

```powershell
az acr build -r <acrName> -t dbx-wi-client:v1 .
```

---

## 1.5) MI로 호출되는 과정 — 가이드 코드

Databricks ML Serving Endpoint(`POST /serving-endpoints/{name}/invocations`)는 항상 `Authorization: Bearer <token>` 을 요구합니다. AKS Workload Identity 환경에서 이 Bearer는 **MI가 받은 AAD 토큰**입니다. 코드가 하는 일은 단 두 단계:

1. **토큰 발급** — `DefaultAzureCredential`이 Pod에 주입된 환경변수
   `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_FEDERATED_TOKEN_FILE` 를 자동으로 읽어
   audience `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default` (= AzureDatabricks 1st-party 앱)로 AAD 토큰을 받아옵니다.
2. **호출** — 그 토큰을 그대로 Bearer로 붙여 `/serving-endpoints/{name}/invocations` 에 POST.

```js
// callServing.js — 가이드 최소 예제 (헬퍼 없음)
import { DefaultAzureCredential } from '@azure/identity';

const HOST     = process.env.DBX_HOST;        // https://adb-<id>.<n>.azuredatabricks.net
const ENDPOINT = process.env.DBX_ENDPOINT;    // e.g. keyless-iris

// (1) MI → AAD 토큰
const credential = new DefaultAzureCredential();
const { token } = await credential.getToken('2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default');

// (2) Serving Endpoint 호출
const res = await fetch(`${HOST}/serving-endpoints/${ENDPOINT}/invocations`, {
  method: 'POST',
  headers: {
    Authorization: `Bearer ${token}`,         // ← MI가 받은 AAD 토큰을 그대로 사용
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    dataframe_split: {
      columns: ['sepal_length', 'sepal_width', 'petal_length', 'petal_width'],
      data: [[5.1, 3.5, 1.4, 0.2]],
    },
  }),
});

console.log(res.status, await res.json());
```

흐름 요약:

```
Pod env (WI 주입)                          → DefaultAzureCredential.getToken(scope)
                                              ↓ federated token → AAD STS
                                           AAD access_token (≈1h)
                                              ↓ Authorization: Bearer
POST {DBX_HOST}/serving-endpoints/{ENDPOINT}/invocations  → 200 + predictions
```

운영용 보강이 필요할 때만 추가 (이 가이드 범위 밖):

- 토큰 캐시 (만료 5분 전 갱신)
- HTTP keep-alive / HTTP/2 풀 (`undici Pool`)
- 타임아웃 / AbortSignal / 재시도

> 인증 모델은 [apim/databricks_keyless_managed_identity.md](../apim/databricks_keyless_managed_identity.md) 의 APIM 정책(`authentication-managed-identity`)과 동일. APIM에서는 게이트웨이가 토큰을 받아 붙여주지만, 여기서는 앱 코드가 같은 일을 두 줄로 합니다.

---

## 2) Kubernetes 매니페스트 (`app.yaml`)

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: dbx-client
  namespace: default
  annotations:
    azure.workload.identity/client-id: "<UAMI_CLIENT_ID>"   # ← 토큰을 받을 UAMI
---
apiVersion: apps/v1
kind: Deployment
metadata: { name: dbx-wi-client, namespace: default, labels: { app: dbx-wi-client } }
spec:
  replicas: 1
  selector: { matchLabels: { app: dbx-wi-client } }
  template:
    metadata:
      labels:
        app: dbx-wi-client
        azure.workload.identity/use: "true"                 # ← mutating webhook 트리거
    spec:
      serviceAccountName: dbx-client
      containers:
      - name: app
        image: <acr>.azurecr.io/dbx-wi-client:v1
        ports: [{ containerPort: 8080 }]
        env:
        - { name: DBX_HOST,     value: "https://adb-<workspaceId>.<n>.azuredatabricks.net" }
        - { name: DBX_ENDPOINT, value: "databricks-meta-llama-3-1-8b-instruct" }
        readinessProbe:
          httpGet: { path: /healthz, port: 8080 }
          initialDelaySeconds: 3
---
apiVersion: v1
kind: Service
metadata: { name: dbx-wi-client, namespace: default }
spec:
  type: LoadBalancer
  selector: { app: dbx-wi-client }
  ports: [{ port: 80, targetPort: 8080 }]
```

배포:

```powershell
az aks get-credentials -g <rg> -n <aks>
kubectl apply -f app.yaml
kubectl get svc dbx-wi-client -w   # EXTERNAL-IP 대기
```

---

## 3) 호출 (Keyless)

클라이언트가 어떤 토큰도 보유하지 않습니다.

### curl
```bash
curl -X POST http://<EXTERNAL_IP>/chat \
  -H 'content-type: application/json' \
  -d '{"prompt":"Say hello in one short sentence."}'
```

### PowerShell
```powershell
Invoke-RestMethod -Uri http://<EXTERNAL_IP>/chat -Method POST `
  -ContentType 'application/json' `
  -Body '{"prompt":"Say hello in one short sentence."}'
```

### Node.js (다른 클라이언트에서)
```js
const r = await fetch(`http://${EXTERNAL_IP}/chat`, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ prompt: "Say hello in one short sentence." })
});
console.log(await r.json());
```

### 응답 예시 (검증)
```json
{
  "id": "chatcmpl_67bb4b5a-...",
  "object": "chat.completion",
  "model": "meta-llama-3.1-8b-instruct-110524",
  "choices": [{
    "index": 0,
    "message": { "role": "assistant", "content": "Hello!" },
    "finish_reason": "stop"
  }],
  "usage": { "prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20 }
}
```

---

## 인증 체인 검증 패턴 (where it breaks)

| 호출 경로 | Bearer | 결과 |
|---|---|---|
| Pod → Databricks (정상) | ✅ AAD | **200** chat.completion |
| Pod → Databricks (헤더 제거) | ❌ | **401** `Credential was not sent` |
| Pod → Databricks (`Bearer invalid`) | 잘못 | **401** unsupported credential |
| SCIM SP 미등록 / `applicationId` 잘못 | ✅ AAD | **403** `PERMISSION_DENIED` |
| 엔드포인트 이름 오타 | ✅ AAD | **404** `ENDPOINT_NOT_FOUND` |

진단 헬퍼 (server.js):

```js
if (req.url === "/whoami") {
  return res.end(JSON.stringify({
    AZURE_CLIENT_ID: process.env.AZURE_CLIENT_ID,
    AZURE_TENANT_ID: process.env.AZURE_TENANT_ID,
    AZURE_FEDERATED_TOKEN_FILE: process.env.AZURE_FEDERATED_TOKEN_FILE,
  }));
}
```
세 env가 채워져 있으면 mutating webhook이 정상 작동 중. 비어 있으면 라벨/네임스페이스/SA 매칭 확인.

---

## 흔한 함정

### A) `getToken` 실패 — `ManagedIdentityCredential authentication failed`
- Pod 라벨에 `azure.workload.identity/use: "true"` 누락
- ServiceAccount 어노테이션 `azure.workload.identity/client-id` 누락 또는 잘못된 clientId
- Federated Credential의 `subject`가 `system:serviceaccount:<ns>:<sa>` 형식과 불일치

### B) 401 `Credential was not sent`
- Bearer 헤더 자체가 안 갔음 (헤더 키 대소문자/오타). 우리 코드는 lowercase `authorization`도 OK.

### C) 403 `PERMISSION_DENIED`
- SCIM에 SP 미등록 또는 `applicationId`에 UAMI **principalId**(Object ID)를 잘못 넣음 → 반드시 **clientId**(Application ID).
- FM 엔드포인트는 per-endpoint PATCH 불가 → SP에 `entitlements: workspace-access`로 충분.

### D) 토큰 캐시
- AAD 토큰 수명 ≈ 1시간. 5분 여유 캐시 권장 (위 코드 구현됨).
- 멀티 워커/멀티 Pod 환경에서 토큰을 공유 캐시로 묶지 말 것 — 단순 in-process 캐시가 가장 안전.

### E) HTTP/2 / 커넥션 풀
- `undici Pool` + `allowH2: true` 로 keep-alive 유지. cold connection 비용 큼(특히 TLS).
- 동시성 높은 워크로드면 `connections` 16 → 32~64로 상향.

---

## 보안 강화 (선택)

현재 구성은 LoadBalancer로 직접 Pod를 노출합니다. 운영 시 권장:

```
Client → Application Gateway (WAF, TLS) → Internal Service / Ingress → Pod
```

- Pod 자체 노출 금지: Service를 `ClusterIP`로 바꾸고 AGIC/NGINX Ingress를 Application Gateway 백엔드로.
- AppGW WAF_v2로 외부 인입 보호, 클라이언트는 자체 도메인(`api.contoso.com`)으로 호출.
- 필요하면 Pod 앞에 APIM(Internal VNet)을 추가해 `apim/databricks_keyless_managed_identity.md` 의 4계층 패턴(Client → AppGW → APIM → 백엔드) 적용 가능. 단, 이 경우 인증 부착 책임을 APIM 정책으로 옮길지(Pod에서 제거), 양쪽 다 둘지(이중 keyless) 결정 필요.

---

## 운영 체크리스트

- [ ] AKS `--enable-oidc-issuer --enable-workload-identity` 활성
- [ ] UAMI + Federated Credential (subject = `system:serviceaccount:<ns>:<sa>`)
- [ ] SA 어노테이션 `azure.workload.identity/client-id`
- [ ] Pod 라벨 `azure.workload.identity/use: "true"`
- [ ] Databricks SCIM SP `applicationId = UAMI clientId`, `entitlements: workspace-access`
- [ ] (custom model 한정) 엔드포인트 `CAN_QUERY` 부여
- [ ] AAD scope `2ff814a6-3304-4ab8-85cb-cd0e6f879c1d/.default`
- [ ] 토큰 5분 여유 캐시 + undici keep-alive 풀
- [ ] `/whoami`, `/healthz` 진단 엔드포인트
- [ ] 운영 노출은 AppGW(WAF) 뒤로

---

## 참고

- AKS Workload Identity: https://learn.microsoft.com/azure/aks/workload-identity-overview
- Databricks AAD audience: https://learn.microsoft.com/azure/databricks/dev-tools/api/latest/aad/service-prin-aad-token
- Databricks Serving Endpoints REST: https://docs.databricks.com/api/workspace/servingendpoints
- 자매 가이드 (게이트웨이 측 keyless): `apim/databricks_keyless_managed_identity.md`
