# APIM 타사 모델 Gateway 참조 구현

Azure API Management(APIM)를 공통 진입점으로 Google Gemini, Anthropic,
Amazon Bedrock, Vertex AI, 그리고 사내 MCP 서버를 노출하는 오프라인 검증
Bicep/policy 예제다. 상위 아키텍처 검토는
[`../../aifoundry/ai-hub-llm-gateway-scaling-review.md`](../../aifoundry/ai-hub-llm-gateway-scaling-review.md)를
참고하고, 각 provider 결정의 근거와 공식 출처는
[`third-party-model-integration.md`](./third-party-model-integration.md)에서
자세히 다룬다.

> **범위 주의**: 이 저장소는 **기존(existing) APIM 서비스**를 대상으로
> 리소스를 구성하는 예제만 제공한다. APIM 인스턴스 자체를 새로 만들거나,
> 실제 `az deployment` 실행, GCP/AWS 리소스 생성 등 클라우드를 변경하는
> 명령은 이 문서와 스크립트에서 실행하지 않는다. `scripts/configure-gcp-wif.sh`는
> 최초 1회 GCP WIF 설정을 위한 템플릿이며, 구문 검사(`bash -n`) 이상의 실행은
> 실제 GCP 프로젝트를 보유한 운영자가 직접 판단해 수행해야 한다.

## 1. 사전 준비물(Prerequisites)

- **기존 APIM 서비스** (Developer/Basic/Standard v2/Premium 등, 이미 배포되어
  있어야 함). `infra/main.bicep`은 `Microsoft.ApiManagement/service@2024-05-01
  existing`으로 이 서비스를 참조만 하며 생성하지 않는다.
- **APIM system-assigned managed identity**가 활성화되어 있어야 한다. 이
  identity가 Key Vault에서 named value용 secret을 읽는다.
- 해당 managed identity에 대상 Key Vault의 **Key Vault Secrets User** RBAC
  role(또는 동등한 access policy `Get`/`List` 권한)이 부여되어 있어야 한다.
  APIM Key Vault-backed named value는 identity에 읽기 권한이 없으면 배포는
  성공해도 secret 값을 가져오지 못한다.
- Gemini API key, Anthropic API key, Bedrock access key/secret key, Azure
  Language API key가 각각 Key Vault secret으로 이미 저장되어 있어야 한다. 이
  저장소는 secret 값 자체를 포함하지 않으며, secret **identifier**(Key
  Vault secret의 URI)만 배포 매개변수로 받는다.
- Vertex AI 호출은 공용 `aiplatform.googleapis.com`을 직접 호출하지 않는다.
  `infra/main.bicep`은 `vertexBrokerUrl`이 이 공용 호스트를 가리키면
  `fail()`로 배포를 중단시킨다. 대신 Azure managed identity와 Google
  Workload Identity Federation(WIF)을 모두 소유하는 **사설 Vertex 브로커**
  서비스가 별도로 준비되어 있어야 한다(§5, WIF 스크립트 참고).
- MCP를 사용하려면 RFC 8707 `resource` 파라미터와 MCP discovery를 지원하는
  **MCP 호환 Authorization Server**의 OpenID Connect discovery URL, issuer,
  사내 MCP backend URL, 그리고 backend API의 Entra Application ID URI가
  필요하다. 기존 APIM의 **system-assigned managed identity**에 backend API
  access 권한을 부여해야 하며, backend는 이 identity의 token issuer/audience와
  service principal 권한을 검증해야 한다.

## 2. 디렉터리 구성과 provider/MCP policy 파일

| Provider/기능 | OpenAPI | Policy |
|---|---|---|
| Gemini Developer API | `openapi/gemini.json` | [`policies/gemini.xml`](./policies/gemini.xml) |
| Anthropic Messages API | `openapi/anthropic.json` | [`policies/anthropic.xml`](./policies/anthropic.xml) |
| Amazon Bedrock Runtime | `openapi/bedrock.json` | [`policies/bedrock.xml`](./policies/bedrock.xml) |
| Vertex AI(사설 브로커 경유) | `openapi/vertex.json` | [`policies/vertex.xml`](./policies/vertex.xml) |
| MCP Resource Server | `openapi/mcp.json` | [`policies/mcp-resource-server.xml`](./policies/mcp-resource-server.xml) |
| MCP Protected Resource Metadata(RFC 9728) | `openapi/mcp-metadata.json` | [`policies/mcp-metadata.xml`](./policies/mcp-metadata.xml) |

공통 policy fragment(모든 provider API의 `<inbound>`에서
`<include-fragment>`로 재사용):

- [`policies/common-client-auth.xml`](./policies/common-client-auth.xml) —
  호출자 Entra JWT(`aud`, `scp`) 검증.
- [`policies/common-rate-limit.xml`](./policies/common-rate-limit.xml) —
  검증된 JWT `oid` claim 기준 per-caller rate limit.
- [`policies/common-pii-inbound.xml`](./policies/common-pii-inbound.xml) —
  inbound-only Azure Language PII 검사(§9의 "PII" 항목 참고). Bedrock 정책
  (`policies/bedrock.xml`)은 이 세 fragment를 다른 provider와 동일하게 모두
  포함하며, **MCP 정책만** 이 fragment 대신 별도의 일반 OIDC
  caller-authorization 처리를 수행한다(§9의 "MCP" 항목 참고).

**Unified Model API 미채택 이유**: APIM
[Unified Model API](https://learn.microsoft.com/en-us/azure/api-management/unified-model-api)는
여러 provider를 하나의 OpenAI-compatible endpoint로 노출하는 기능이지만
공식 문서상 **preview** 기능이다. 이 참조 구현은 Gemini/Anthropic/Bedrock/
Vertex 각각의 **provider-native passthrough**(공식 API 스키마를 그대로
노출)를 기본으로 채택하고, Unified Model API는 provider별 요청/응답 스키마
차이와 실 서비스(GA) 지원 정책이 확인되기 전까지 baseline으로 사용하지
않는다.

## 3. 고정 route와 native 요청 스키마

`infra/main.bicep`은 다음 고정 API 경로를 `existing` APIM 인스턴스 위에
생성한다(모두 `${apiPathPrefix}` 하위, 기본값 `ai`).

| API | Path | Native 요청 형태 |
|---|---|---|
| Gemini | `${apiPathPrefix}/gemini` | `POST /v1beta/models/{model}:generateContent` |
| Anthropic | `${apiPathPrefix}/anthropic` | `POST /v1/messages` (`anthropic-version` 헤더 자동 부여) |
| Bedrock | `${apiPathPrefix}/bedrock` | `POST /model/{modelId}/converse` (SigV4 서명은 APIM이 대행, `/` 없는 foundation/inference-profile ID만 지원) |
| Vertex(브로커 경유) | `${apiPathPrefix}/vertex` | `POST /v1/projects/{project}/locations/{location}/publishers/google/models/{model}:generateContent` |
| MCP | `${apiPathPrefix}/mcp` | `POST /`(API 루트 자체가 MCP endpoint) |
| MCP metadata | `.well-known/oauth-protected-resource/${apiPathPrefix}/mcp` | `GET`(RFC 9728 Protected Resource Metadata) |

> **MCP 공개 endpoint 표기 주의**: 실제 공개 MCP endpoint는 `mcpApi`의
> `path: '${apiPathPrefix}/mcp'`와 `openapi/mcp.json`의 루트(`/`) operation이
> 결합된 `/{apiPathPrefix}/mcp` 한 경로다. 메타데이터 URL은
> `/.well-known/oauth-protected-resource/{apiPathPrefix}/mcp`다. `mcp.json`이
> 루트 대신 중첩된 `/mcp` operation을 노출하면 실제 경로가
> `/{apiPathPrefix}/mcp/mcp`가 되어 리소스 감사(audience)·메타데이터 URL과
> 어긋난다. 이 저장소와 모든 문서는 `/{apiPathPrefix}/mcp`(예: `/ai/mcp`)
> 하나만을 사용하며 `/mcp/mcp` 표기는 사용하지 않는다.
> Bicep은 이 endpoint와 metadata URL을 `gatewayBaseUrl` 및 검증된
> `apiPathPrefix`에서 동시에 유도한다.

각 provider API는 자체 스키마를 그대로 통과시키는(passthrough)
`additionalProperties: true` OpenAPI 요청/응답 본문을 사용하므로, 호출자는
각 provider의 공식 API 문서를 그대로 참고할 수 있다.

## 4. Secret 및 매개변수 안전 공급

- `infra/main.bicep`의 `geminiApiKeySecretIdentifier`,
  `anthropicApiKeySecretIdentifier`, `bedrockAccessKeySecretIdentifier`,
  `bedrockSecretKeySecretIdentifier`, `languageApiKeySecretIdentifier`
  매개변수는 모두 `@secure()`로 선언되어 있으며, secret **값**이 아니라 Key
  Vault secret **identifier**(URI)를 받는다. 실제 secret 값은 Key Vault에만
  존재하고 이 저장소의 어떤 파일에도 포함되지 않는다.
- `gatewayBaseUrl`은 외부 MCP client가 사용하는 canonical HTTPS origin(예:
  `https://gateway.example.com`)이다. path, query, fragment, user-info,
  trailing slash 없이 입력해야 하며, Bicep은 `apiPathPrefix`와 결합해
  `https://gateway.example.com/{apiPathPrefix}/mcp` resource audience 및
  `https://gateway.example.com/.well-known/oauth-protected-resource/{apiPathPrefix}/mcp`
  metadata URL을 항상 함께 생성한다. 개별 MCP URL을 별도 매개변수로
  입력하지 않으므로 route/metadata/audience가 drift할 수 없다.
- `apiPathPrefix`는 비어 있지 않고 leading/trailing slash가 없는 path
  fragment여야 한다(기본값 `ai`).
- `vertexBrokerResourceAudience`는 사설 Vertex 브로커 API의 Entra
  Application ID URI(예: `api://<private-vertex-broker-app-id>`)이며 secret이
  아니다. `policies/vertex.xml`의 `authentication-managed-identity` 정책은
  이 audience의 access token을 기존 APIM 인스턴스의 system-assigned managed
  identity로 요청한다.
- `infra/main.bicepparam`은 커밋된 **템플릿**으로, `<entra-tenant-id>`처럼
  자리표시자만 담고 있다. 실제 배포 시에는 이 저장소의 `.gitignore`가 이미
  제외하는 `*.parameters.json`/`*.secrets.json`/`.env` 패턴을 따르는 별도의
  `secure.parameters.json` 파일(예: `infra/main.bicepparam`을 복사해 실제
  값으로 채운 JSON parameters 파일)에 실제 tenant ID, audience, Key Vault
  secret identifier 등을 채워 넣고, 이 파일은 절대 커밋하지 않는다.
- `mcpBackendResourceAudience`는 사설 MCP backend API의 Entra Application ID
  URI(예: `api://<private-mcp-server-app-id>`)다. `policies/mcp-resource-server.xml`
  의 `authentication-managed-identity`가 기존 APIM의 system-assigned managed
  identity로 이 audience token을 취득한다.
- CI/CD에서는 `secure.parameters.json`을 pipeline secret store 또는
  release-time 생성 파일로 관리하고, `az deployment group create`
  `--parameters @secure.parameters.json` 형태로만 전달한다.

## 5. 네트워크 사설 연결 요구사항

### GCP(Vertex AI, 사설 브로커 경유)

- **HA VPN**: 99.99% 가용성 SLA를 요구하는 워크로드는 HA VPN gateway의 두
  interface 각각에 tunnel을 구성해야 한다([Google Cloud HA VPN 개요](https://cloud.google.com/network-connectivity/docs/vpn/concepts/overview)).
- **BGP**: Cloud Router로 Azure/GCP 간 경로를 동적으로 교환한다.
- **PSC(Private Service Connect) for Google APIs**: `aiplatform.googleapis.com`을
  포함한 Google API를 VPC 내부 IP로 노출한다([Access Google APIs through Private Service Connect endpoints](https://cloud.google.com/vpc/docs/configure-private-service-connect-apis)).
- **Route 광고와 private DNS**: PSC endpoint의 내부 IP를 Azure 방향으로
  advertise하고, Vertex AI hostname이 사설 IP로 resolve되도록 private DNS를
  구성한다.
- **GCP WIF(Workload Identity Federation)**: 브로커의 Azure managed identity가
  장기 GCP service-account key 없이 Vertex AI를 호출하도록 하는 신뢰
  관계다([Workload identity federation with other clouds](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds)).
  최초 설정 스크립트는 [`scripts/configure-gcp-wif.sh`](./scripts/configure-gcp-wif.sh)를
  참고한다(§6).
- **APIM에서 브로커까지의 인증 경계**: 기존 APIM에 system-assigned managed
  identity를 활성화하고
  [`authentication-managed-identity`](https://learn.microsoft.com/en-us/azure/api-management/authentication-managed-identity-policy)
  로 브로커의 `vertexBrokerResourceAudience` token을 보낸다. 브로커는 이
  token의 issuer/audience를 검증하고 APIM managed identity만 authorize하며,
  사설 네트워크에 있더라도 익명/직접 요청은 거부해야 한다. APIM은 검증된
  caller JWT의 `oid`에서 `x-ai-hub-caller-oid`를 overwrite해 전달한다.
  브로커는 APIM managed-identity token을 먼저 검증한 경우에만 이 내부
  header를 호출자 식별자로 신뢰해야 한다.

### AWS(Amazon Bedrock)

- **Bedrock Interface VPC Endpoint(AWS PrivateLink)**: `bedrock-runtime`
  interface endpoint를 통해 Bedrock Runtime API를 AWS 내부에서 사설로
  호출한다([Amazon Bedrock interface VPC endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)).
- **Route 53 Resolver inbound endpoint**: AWS VPC 밖(Azure)에서 오는 DNS
  질의를 받아 VPC 내부 private DNS로 응답하도록 inbound endpoint를 배치한다
  ([Route 53 Resolver: forwarding inbound DNS queries to your VPC](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries.html)).
- **Azure/사내 DNS 조건부 전달(conditional forwarding)**: Azure DNS Private
  Resolver 또는 사내 DNS에서 Bedrock 도메인을 Route 53 Resolver inbound
  endpoint로 조건부 전달하도록 구성한다.
- **TCP/UDP 53 도달성**: Azure 호출자와 AWS VPN/전용 연결 구간, 그리고
  security group에서 Resolver inbound endpoint까지 TCP/UDP 53 포트가
  허용되어야 DNS 조건부 전달이 동작한다.

## 6. GCP WIF 사전 준비 스크립트

[`scripts/configure-gcp-wif.sh`](./scripts/configure-gcp-wif.sh)는 사설
Vertex 브로커를 위한 **최초 1회(first-time) GCP WIF 설정 템플릿**이다.

- 필수 입력(`GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_WIF_POOL_ID`,
  `GCP_WIF_PROVIDER_ID`, `ENTRA_TENANT_ID`, `ENTRA_APPLICATION_ID_URI`,
  `VERTEX_BROKER_PRINCIPAL_OBJECT_ID`)이 하나라도 비어 있으면 `gcloud` 호출
  전에 즉시 실패한다(`: "${VAR:?message}"` 패턴).
- API key, client secret, service-account key JSON 등 어떤 credential도
  스크립트 안에 포함하지 않는다.
- **이 스크립트는 이 세션에서 실행하지 않는다.** `bash -n`으로 구문만
  검증했으며, 실제 GCP 프로젝트에 대한 실행은 프로젝트 소유자가 별도로
  수행해야 한다.
- 반복 배포 또는 자동화 파이프라인에서는 이 스크립트를 그대로 재실행하지
  말고(이미 존재하는 pool/provider에 대해 `gcloud ... create`는 실패한다),
  조직의 GCP IaC(Terraform 등)로 관리한다.

## 7. Bicep 배포 명령

```bash
az deployment group create \
  --resource-group "<resource-group>" \
  --template-file infra/main.bicep \
  --parameters @secure.parameters.json
```

`secure.parameters.json`은 `infra/main.bicepparam`을 기반으로 실제 값을 채운
뒤 커밋하지 않는 로컬/파이프라인 전용 파일이다. 이 저장소는 실제 배포
명령을 실행하지 않으며, 위 명령은 기존 APIM 서비스를 보유한 운영자가 실제
환경에서 실행할 명령을 문서화한 것이다.

## 8. 검증 명령

```bash
./scripts/validate.sh
```

`scripts/validate.sh`는 `az bicep build`와 `az bicep build-params`로
`infra/main.bicep` 및 커밋된 `infra/main.bicepparam` 템플릿의 컴파일을
확인하고, `python3 -m unittest tests/test_gateway_artifacts.py -v`로 정적
아티팩트(OpenAPI/정책 XML/Bicep 리소스 배선) 계약을 검증한다. 모든 검증은
오프라인으로 수행되며 클라우드 리소스를 변경하지 않는다. 스크립트는 자체
project root로 `cd`하므로 repository 밖의 임의 working directory에서 absolute
path로 호출해도 동일하게 동작한다.

## 9. PII, Bedrock, MCP 경계와 한계

### PII(§7 상세는 `third-party-model-integration.md` 참고)

- `common-pii-inbound.xml`은 **inbound(요청)만** 검사한다. Provider의
  streaming 응답 등 **outbound 결과에 대한 안전한 APIM inline 필터링/redaction은
  제공하지 않는다.**
- 보수적으로 잡은 inline gateway 임계값은 **4,096자**다(`maxInlinePiiCharacters`).
  이를 초과하면 **413**을 반환한다.
- Azure Language PII 호출이 실패하거나 예상 스키마가 아니면(타임아웃,
  5xx, 파싱 실패 등) **fail-closed**로 **503**(PII inspection unavailable)을
  반환한다.
- PII entity가 탐지되면 **400**(Sensitive input detected)을 반환한다. 이
  정책은 **redaction을 수행하지 않고 차단만** 한다.
- **Design recommendation**: streaming 출력이나 비정형 대화형 응답의 PII
  통제가 필요하면 APIM inline 정책이 아니라 별도의 Guardrail Service를
  배치할 것을 권장한다.
- Azure Language의 동기 텍스트 분석 API는 문서당 5,120 text elements, 요청당
  최대 5개 문서, 전체 요청 1 MB 한도를 가진다([Data limits for Azure Language](https://learn.microsoft.com/azure/ai-services/language-service/concepts/data-limits)).
  긴 prompt를 이 한도에 맞춰 chunk로 분할하면 chunk 경계에 걸친 PII의 문맥이
  손실될 수 있으므로 overlap window와 재조합 검증이 필요하다.

### Bedrock

- `policies/bedrock.xml`은 Key Vault-backed named value(`ai-hub-bedrock-access-key`,
  `ai-hub-bedrock-secret-key`)로 공급되는 **API key/IAM 사용자 static
  credential**을 사용해 SigV4 서명을 생성한다. 이는 APIM
  [amazon-bedrock-passthrough-llm-api](https://learn.microsoft.com/en-us/azure/api-management/amazon-bedrock-passthrough-llm-api)
  공식 데모 패턴과 동일한 접근이다.
- **Design recommendation**: 이 static-key 패턴은 데모/PoC 수준이며,
  production에서는 단기(short-lived) AWS credential, STS AssumeRole 기반
  federation, 또는 별도 broker를 통한 자격증명 회전을 권장한다.
- 정책은 호출자(caller)의 Entra bearer token을 Bedrock Runtime으로 전달하지
  않도록 `Authorization` 헤더를 SigV4 값으로 **override(치환)**하고, 요청
  경로/쿼리/헤더/본문 해시를 이용해 서명을 생성한다.
- 이 경로 API의 `modelId`는 `^[A-Za-z0-9._:-]{1,256}$`인 foundation 또는
  inference-profile ID만 지원한다. `/`가 포함된 Bedrock ARN/custom model
  ARN은 APIM path-template routing에서 escaped slash를 안정적으로 보존할 수
  없으므로 이 reference operation에서 400으로 거부한다. ARN을 사용해야 하면
  model ID를 header/body로 받는 별도 gateway operation 또는 SigV4 broker를
  설계하고, 그 operation의 encoding/authorization contract를 명시해야 한다.
- `policies/bedrock.xml`은 모델 ID를 한 번 escape한 `wire path`를 실제
  Bedrock 요청에 사용하고, AWS non-S3 SigV4 `CanonicalURI`에는 해당 wire
  path의 각 segment를 한 번 더 escape한 `canonical path`를 사용한다. 예를
  들어 `...-v2:0`은 wire path에서 `...-v2%3A0`, canonical path에서
  `...-v2%253A0`이다. 배포 전에는 대상 region에서 허용된 colon 포함 model
  ID로 staging 요청을 보내 `SignatureDoesNotMatch`가 발생하지 않는지 반드시
  검증한다.

### MCP

- `policies/mcp-resource-server.xml`은 `{{ai-hub-mcp-openid-config}}`로 지정된
  **일반 OIDC discovery**를 사용해 audience를 검증한 뒤, `mcp.invoke`가
  표준 OAuth `scope` 또는 Entra `scp` claim 중 하나에 있는지 확인한다.
- `Authorization` header가 없거나 `validate-jwt` 검증(만료, 서명, issuer,
  audience 등)에 실패하면 정책은 `WWW-Authenticate` header에
  `error="invalid_token"`, `resource_metadata`, `scope="mcp.invoke"`를 담아
  401을 반환한다. 유효한 token에 `mcp.invoke`가 없으면
  `error="insufficient_scope"` challenge와 403을 반환한다. 이로써 MCP client가
  metadata endpoint를 찾아 재인증할 수 있다.
- JWT validation과 scope 검사가 끝난 후 policy는 caller의 gateway-audience
  bearer token을 backend로 **전달하지 않는다**. 대신
  `x-ai-hub-mcp-caller-subject`와 `x-ai-hub-mcp-caller-issuer`를
  `exists-action="override"`로 재생성하고, APIM system-assigned managed
  identity가 `mcpBackendResourceAudience`용 backend token을 `Authorization`
  header에 설정한다. 사설 MCP backend는 network 경계만 신뢰하지 말고 이
  APIM token의 issuer/audience 및 APIM service principal authorization을
  검증한 뒤에만 두 caller header를 object-level authorization에 사용해야 한다.
- 사내 통제 하의 Entra scope-only 호환 프로파일에서는
  `{{ai-hub-mcp-openid-config}}`가 Entra v2 discovery endpoint를 직접
  가리킬 수 있으며, 이때 이 정책은 Entra `scp` claim을 검증한다. 다만 현재
  MCP Authorization 사양이 요구하는 RFC 8707 `resource` 파라미터를 Entra v2
  endpoint가 지원하지 않으므로 **완전한 MCP 표준 준수는 아니다**.
- 표준 준수가 필요한(조직이 통제하지 않는) MCP client를 지원하려면 RFC 8707
  `resource`, discovery, dynamic/pre-registered client registration을 처리하는
  **별도의 MCP 호환 Authorization Server 또는 broker**가 Entra ID 앞단에
  필요하다.

## 10. 참고 자료

전체 출처와 provider별 상세 설계 근거는
[`third-party-model-integration.md`의 §9](./third-party-model-integration.md#9-공식-참고-자료)를
참고한다.
