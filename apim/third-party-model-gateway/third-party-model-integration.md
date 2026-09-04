# 타사 모델(Gemini/Anthropic/Bedrock/Vertex) 및 MCP 통합 가이드

이 문서는 `apim/third-party-model-gateway/`의 Bicep/policy 예제가 채택한
아키텍처 결정과 그 근거를 공식 문서 링크와 함께 정리한다. 배포/검증 절차와
파일 목록은 [`README.md`](./README.md)를 참고한다.

각 항목은 **Documented fact**(공식 문서가 명시적으로 규정하는 사실)와
**Design recommendation**(공식 문서가 강제하지 않지만 이 참조 구현이
선택한 설계 판단)을 구분해서 표기한다.

## 1. Provider-native passthrough 대 Unified Model API preview

- **Documented fact**: Azure API Management는
  [genai-gateway-capabilities](https://learn.microsoft.com/en-us/azure/api-management/genai-gateway-capabilities)에서
  Azure OpenAI 외에 여러 LLM provider를 위한 policy와 backend 기능을
  제공하며, 그 중
  [Unified Model API](https://learn.microsoft.com/en-us/azure/api-management/unified-model-api)는
  여러 provider를 하나의 OpenAI-compatible 요청/응답 스키마로 노출하는
  기능으로, 문서 상단에 **preview**로 명시되어 있다.
- **Design recommendation**: 이 참조 구현은 Gemini, Anthropic, Bedrock,
  Vertex 각각에 대해 **provider-native passthrough**(공식 API의 원본
  요청/응답 스키마를 그대로 노출)를 baseline으로 채택한다. 이유는 다음과
  같다.
  1. Unified Model API는 preview 단계이므로 production SLA·지원 정책이
     GA 기능과 다를 수 있다.
  2. Gemini `generateContent`, Anthropic `messages`, Bedrock `converse`,
     Vertex `generateContent`는 이미 각 provider의 공식 문서와 SDK가
     대상으로 하는 원본 스키마이므로, 이를 그대로 통과시키면 provider
     SDK/문서와의 호환성을 별도 매핑 없이 유지할 수 있다.
  3. 하나의 통합 스키마로 정규화하면 provider별 고유 기능(예: Anthropic의
     `anthropic-version` 헤더 protocol, Bedrock의 SigV4 서명, Vertex의
     project/location 경로 매개변수)을 흡수하는 변환 계층이 추가로
     필요해지고, 그 변환 계층 자체가 이 preview 기능에 종속된다.
  - preview 기능을 채택하려는 조직은 Microsoft의 preview 지원 정책과 GA
    전환 일정, breaking change 이력을 별도로 검토해야 한다.

## 2. Gemini Developer API 구성과 Key Vault API key 처리

- **Documented fact**: Gemini Developer API의 콘텐츠 생성 endpoint는
  `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
  형태이며, API key는 `x-goog-api-key` 헤더로 전달한다
  ([Gemini API reference: models.generateContent](https://ai.google.dev/api/generate-content#v1beta.models.generateContent)).
- 이 구현의 `policies/gemini.xml`은 다음을 수행한다.
  1. 공통 fragment(`ai-hub-client-auth`, `ai-hub-rate-limit`,
     `ai-hub-pii-inbound`)를 순서대로 적용해 호출자 Entra JWT를 검증하고,
     rate limit을 적용하고, inbound PII를 검사한다.
  2. 호출자가 보낸 `Authorization` 헤더를 백엔드로 전달하기 전에
     삭제(`exists-action="delete"`)한다.
  3. Key Vault-backed named value `{{ai-hub-gemini-api-key}}`
     (`geminiApiKeySecretIdentifier` 매개변수로 참조되는 Key Vault secret)의
     값을 `x-goog-api-key` 헤더에 설정한다.
  4. 고정 backend `ai-hub-gemini`(`https://generativelanguage.googleapis.com`)로
     라우팅한다.
- **Design recommendation**: API key는 named value의 `secret: true` +
  `keyVault.secretIdentifier`로만 참조하고, Bicep 파라미터 파일이나 policy
  XML에 평문으로 기록하지 않는다. Key rotation은 Key Vault에서 secret
  버전을 교체하는 것으로 처리하고 APIM 재배포를 요구하지 않도록 운영한다.

## 3. Anthropic Messages API 구성과 `anthropic-version` 헤더

- **Documented fact**: Anthropic
  [Messages API](https://docs.anthropic.com/en/api/messages)는
  `POST https://api.anthropic.com/v1/messages`를 사용하며, 인증은
  `x-api-key` 헤더, API 버전 협상은 필수 `anthropic-version` 헤더(예:
  `2023-06-01`)로 수행한다.
- `policies/anthropic.xml`은 공통 fragment 적용 후 호출자 `Authorization`
  헤더를 삭제하고, `x-api-key`를 named value
  `{{ai-hub-anthropic-api-key}}`로 설정하며, `anthropic-version` 헤더가
  호출자로부터 이미 지정되지 않은 경우(`exists-action="skip"`)에만
  `2023-06-01`을 기본값으로 채운 뒤 고정 backend `ai-hub-anthropic`
  (`https://api.anthropic.com`)으로 라우팅한다.
- **Design recommendation**: `anthropic-version`을 `skip` 방식으로 처리해
  호출자가 더 최신 버전을 명시적으로 요청하면 그 값을 존중하되, 지정하지
  않은 호출자에게는 알려진 안정 버전을 강제해 provider 측 breaking change로
  인한 예기치 않은 실패를 줄인다.

## 4. Amazon Bedrock passthrough, APIM SigV4, PrivateLink, hybrid DNS

- **Documented fact**: APIM
  [amazon-bedrock-passthrough-llm-api](https://learn.microsoft.com/en-us/azure/api-management/amazon-bedrock-passthrough-llm-api)
  문서와 [AI-Gateway aws-bedrock lab](https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/aws-bedrock)은
  APIM이 SigV4를 직접 계산해 Bedrock Runtime 요청에 서명하고, AWS access
  key/secret key를 API key 유사 named value로 관리하는 패턴을 공식
  데모/샘플로 제시한다.
- `policies/bedrock.xml`은 이 패턴을 구현한다.
  1. 공통 fragment(인증/rate limit/PII)를 적용한다.
  2. 매칭된 `modelId` 경로 매개변수로부터 캐노니컬 backend 경로
     `/model/{modelId}/converse`를 계산하고, 쿼리 매개변수를 SigV4
     캐노니컬 규칙(개별 값 인코딩 후 encoded key/value로 정렬)에 따라
     재구성한다.
  3. 원본 요청 바이트에서 SHA-256 payload hash를 한 번만 계산해
     `X-Amz-Content-Sha256`과 서명 계산에 동일하게 사용한다.
  4. `rewrite-uri`가 사용하는 것과 **동일한 변수**로 캐노니컬 요청을
     구성해 서명이 실제 전달되는 요청과 어긋나지 않도록 한다.
  5. `AWS4-HMAC-SHA256` 알고리즘으로 `Authorization` 헤더를 직접 생성하고,
     `ai-hub-bedrock-region` named value로 지정된 region의
     `bedrock-runtime.{region}.amazonaws.com` backend로 라우팅한다.
  6. 호출자 `Authorization`(Entra bearer token)은 백엔드 서명 계산 전
     격리되며, Bedrock 인증에는 재사용되지 않는다.
- **Design recommendation**: named value로 관리되는 정적 AWS access
  key/secret key는 공식 데모 패턴과 동일하지만 **production 권장 방식이
  아니다**. Production에서는 단기(short-lived) credential, AWS STS
  AssumeRole federation, 또는 별도 credential 발급 broker를 사용해 장기
  static key 노출 표면을 줄이는 것을 권장한다.
- **네트워크(Documented fact)**: AWS는 Amazon Bedrock에 대해
  [Interface VPC endpoint(AWS PrivateLink)](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)를
  공식 지원한다. VPC 외부(Azure)에서 이 사설 endpoint의 DNS 결과를
  사용하려면 [Route 53 Resolver inbound endpoint](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries.html)를
  AWS 측에 배치하고, Azure DNS Private Resolver 또는 사내 DNS에서 Bedrock
  도메인을 이 inbound endpoint로 조건부 전달(conditional forwarding)해야
  하며, VPN/전용 연결 구간과 security group에서 TCP/UDP 53 트래픽이
  허용되어야 한다.

## 5. Vertex AI 사설 브로커, WIF 근거, HA VPN/BGP/PSC/private DNS

- **Design recommendation(구현 선택)**: `infra/main.bicep`이 참조하는 policy
  파일 `policies/vertex.xml`은 공용 Vertex AI(`aiplatform.googleapis.com`)를
  직접 호출하지 않고, **사설 Vertex 브로커**(`ai-hub-vertex-broker` backend,
  `vertexBrokerUrl`)만 호출한다. Bicep은 `vertexBrokerUrl`이 공용 Vertex
  호스트를 가리키면 `fail()`로 배포 자체를 중단시켜 이 경계를 강제한다.
  **이 브로커가 Azure managed identity와 Google WIF를 모두 소유**하며, APIM
  자체는 GCP
  자격증명이나 토큰 교환 로직을 갖지 않는다. 즉 "production APIM 단독
  토큰 교환"은 이 참조 구현이 채택한 방식이 **아니며**, 토큰 교환은 항상
  브로커 내부에서 수행된다.
- **Documented fact(WIF)**:
  [Workload identity federation with other clouds](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds)는
  Microsoft Entra ID를 외부 identity provider로 사용하는 WIF 구성에서
  다음을 요구/제시한다.
  - OIDC issuer는 `https://sts.windows.net/{tenant-id}` 형태다.
  - `--allowed-audiences`는 신뢰할 Entra application(리소스)의 식별자
    (application ID URI)로 제한한다.
  - attribute mapping `google.subject=assertion.sub`로 Entra 토큰의 `sub`
    claim을 WIF principal subject로 매핑한다.
  - 이렇게 매핑된 principal(브로커의 Entra managed identity object ID
    기반 subject)에 `roles/aiplatform.user`와 같은 GCP IAM role을 바인딩해
    장기 GCP service-account key 없이 Vertex AI를 호출하게 한다.
  - 최초 설정 절차는 [`scripts/configure-gcp-wif.sh`](./scripts/configure-gcp-wif.sh)로
    문서화되어 있으며, 이 스크립트는 최초 1회 부트스트랩용이므로 반복
    실행 시 이미 존재하는 pool/provider에 대해 실패한다. **Design
    recommendation**: 반복 배포·환경 복제에는 조직의 GCP IaC(Terraform
    `google_iam_workload_identity_pool`/`_provider` 리소스 등)로 이
    설정을 idempotent하게 관리할 것을 권장한다.
  - 이 WIF 신뢰 관계는 "브로커의 Entra managed identity가 GCP에서 어떤
    principal로 인식되는가"만 정의한다. 브로커가 실제로 이 identity로
    토큰을 획득해 Vertex AI를 호출하는 구현(HTTP client, 토큰 캐싱, 재시도
    등)은 브로커 서비스 자체의 책임이며 이 저장소가 제공하는 범위가
    아니다.
- **네트워크(Documented fact)**: Google은
  [HA VPN 개요](https://cloud.google.com/network-connectivity/docs/vpn/concepts/overview)에서
  99.99% 가용성 SLA를 위해 HA VPN gateway의 두 interface 각각에 tunnel을
  구성하도록 요구하며, Cloud Router 기반 BGP로 경로를 동적 교환한다. Google
  API(Vertex AI 포함)를 VPC 내부 IP로 노출하려면
  [Private Service Connect(PSC) endpoint](https://cloud.google.com/vpc/docs/configure-private-service-connect-apis)를
  구성하고, 그 내부 IP를 Azure 방향으로 route 광고하며, Vertex AI hostname이
  이 사설 IP로 resolve되도록 private DNS를 구성해야 한다.
- **Design recommendation**: [AI-Gateway gemini-models lab](https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/gemini-models)의
  구성 패턴을 참고해 APIM에서 provider-native Gemini/Vertex 요청 스키마를
  유지하되, Vertex 호출 경로만 사설 브로커로 우회시키는 방식을 채택했다.

## 6. 공통 Entra 호출자 인증과 rate limiting

- `policies/common-client-auth.xml`(fragment)은 모든 provider API의
  `<inbound>`에서 `<include-fragment>`로 재사용되며, `validate-jwt`로
  다음을 검증한다.
  - `openid-config`: `https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration`
  - `audiences`: named value `{{ai-hub-entra-audience}}`
  - `required-claims`: `scp` claim에 `{{ai-hub-required-scope}}`(기본값
    `ai.invoke`) 포함
- `policies/common-rate-limit.xml`(fragment)은 `rate-limit-by-key`를
  검증된 JWT의 `oid` claim(고유 사용자/서비스 principal ID)을 counter key로
  사용해 호출자별로 적용하며, `oid`가 없는 예외적 토큰에는 안정적인
  fallback(`"unknown"`)을 사용한다.
- **Design recommendation**: `oid` 기반 rate limit은 사용자/서비스 principal
  단위로 공정하게 처리량을 배분하지만, 다수의 호출이 동일 `oid`(예: 공유
  service principal)로 이루어지는 배치/자동화 워크로드에는 추가로 요청
  단위 또는 API key 단위 rate limit을 병행하는 것을 고려한다.

## 7. PII policy 동작과 한계

`policies/common-pii-inbound.xml`은 Azure Language의 동기 PII entity
recognition API(`/language/:analyze-text`)를 `send-request`로 호출한다.

- **Documented fact(동작)**:
  1. **Inbound(요청)만** 검사한다. Provider 응답(특히 streaming 출력)에
     대한 outbound 검사/redaction은 이 fragment에 포함되어 있지 않다.
  2. 요청 본문 길이가 `{{ai-hub-max-inline-pii-characters}}`(기본값
     **4,096자**, 보수적으로 설정된 inline gateway 임계값)를 초과하면
     즉시 **413**(Input exceeds inline PII inspection limit)을 반환한다.
  3. Language API 호출이 실패하거나(HTTP 상태 200이 아님), 응답이 예상
     스키마(`kind == "PiiEntityRecognitionResults"`, `errors` 배열이
     비어 있음, `documents` 배열에 `id == "request"` 문서가 존재하고
     `entities` 배열을 가짐)를 만족하지 않으면 **fail-closed**로
     **503**(PII inspection unavailable)을 반환한다. 이는 응답 파싱
     예외, 누락된 필드, 빈 결과 모두를 포함한다.
  4. 정상 응답에서 `entities` 배열이 비어 있지 않으면(PII 탐지됨)
     **400**(Sensitive input detected)을 반환한다. 이 fragment는
     **redaction을 수행하지 않고 요청을 차단**할 뿐이며, provider로 전달될
     JSON 요청 본문 자체를 변형하지 않는다.
- **Design recommendation**: Streaming 응답이나 provider 출력에 대한 PII
  통제, 또는 안전한 inline redaction이 필요한 경우 APIM inline policy로
  이를 구현하려 하지 말고 **별도의 Guardrail Service**(비동기 처리, 별도
  검사·마스킹 파이프라인)를 배치할 것을 권장한다. APIM inline policy는
  streaming 청크 단위 응답을 안전하게 가로채 redact하는 기능을 제공하지
  않는다.
- **Documented fact(입력 한도)**:
  [Data limits for Azure Language](https://learn.microsoft.com/azure/ai-services/language-service/concepts/data-limits)에
  따르면 동기 텍스트 분석 API는 문서당 **5,120 text elements**, 요청당
  최대 **5개 문서**, 전체 요청 **1 MB** 한도를 가진다.
- **Design recommendation**: 이 한도를 넘는 긴 prompt를 여러 chunk로
  분할해 순차 검사하면 chunk 경계에 걸쳐 있는 PII 개체의 문맥이 손실될 수
  있으므로, chunk 간 overlap window를 두고 검사 후 결과를 재조합해
  검증하는 절차가 필요하다.

## 8. MCP 호환성과 authorization-server 경계

- `policies/mcp-resource-server.xml`은 `Authorization` 헤더가 없으면 RFC
  9728 스타일의 `WWW-Authenticate` challenge(메타데이터 URL 참조 포함)와
  함께 401을 먼저 반환한 뒤, `validate-jwt`로 `{{ai-hub-mcp-openid-config}}`
  (일반 OIDC discovery URL)를 이용해 audience
  `{{ai-hub-mcp-resource-audience}}`와 scope `mcp.invoke`를 검증한다.
- `policies/mcp-metadata.xml`은 `.well-known/oauth-protected-resource/{apiPathPrefix}/mcp`
  경로에서 `resource`, `authorization_servers`, `scopes_supported`,
  `bearer_methods_supported`를 담은 [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728.html)
  Protected Resource Metadata JSON을 반환한다.
- **Documented fact**: 이 구성은 Entra v2 endpoint를 직접 검증하는
  `validate-azure-ad-token` 정책이 아니라 **일반 OIDC discovery**를
  사용하므로, `{{ai-hub-mcp-openid-config}}`가 가리키는 대상이 실제로는
  Entra ID를 upstream identity provider로 사용하되 RFC 8707 `resource`
  파라미터, MCP discovery, client registration을 처리할 수 있는 **MCP 호환
  Authorization Server**여야 한다. [MCP Authorization
  사양](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)은
  authorization request에 [RFC 8707](https://www.rfc-editor.org/rfc/rfc8707.html)의
  `resource` 파라미터를 사용하도록 요구하지만, Microsoft Entra v2
  authorization endpoint 자체는 `resource` 파라미터를 지원 파라미터로
  정의하지 않으므로, Entra v2를 직접 이 역할에 사용하면 이 요구사항을
  완전히 준수하지 못한다.
- **Design recommendation**: 조직이 통제하는 MCP client와 server만
  사용하는 폐쇄형 환경에서는 이 저장소의 구성처럼 **Entra scope-only
  호환 프로파일**(사내 Entra App Registration + `scp` claim 검증)을 사용할
  수 있으나, 이는 **사내 호환 프로파일**일 뿐 현재 MCP 사양이 요구하는
  RFC 8707 완전 준수는 아니라는 점을 명시해야 한다. 표준 준수가 필요한
  외부/범용 MCP client를 지원하려면 RFC 8707 `resource`, discovery,
  client registration을 처리하는 별도의 MCP 호환 Authorization Server 또는
  broker를 Entra ID 앞단에 두어야 한다.

## 9. 공식 참고 자료

### Microsoft / Azure

- [AI gateway capabilities in Azure API Management](https://learn.microsoft.com/en-us/azure/api-management/genai-gateway-capabilities)
- [Azure OpenAI-compatible LLM API in API Management](https://learn.microsoft.com/en-us/azure/api-management/openai-compatible-llm-api)
- [Amazon Bedrock passthrough LLM API in API Management](https://learn.microsoft.com/en-us/azure/api-management/amazon-bedrock-passthrough-llm-api)
- [Unified Model API in API Management](https://learn.microsoft.com/en-us/azure/api-management/unified-model-api)

### Azure Samples

- [AI-Gateway: gemini-models lab](https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/gemini-models)
- [AI-Gateway: aws-bedrock lab](https://github.com/Azure-Samples/AI-Gateway/tree/main/labs/aws-bedrock)

### Google Cloud

- [Workload identity federation with other clouds](https://cloud.google.com/iam/docs/workload-identity-federation-with-other-clouds)
- [Access Google APIs through Private Service Connect endpoints](https://cloud.google.com/vpc/docs/configure-private-service-connect-apis)
- [HA VPN overview](https://cloud.google.com/network-connectivity/docs/vpn/concepts/overview)

### Google AI / Gemini

- [Gemini API reference: models.generateContent](https://ai.google.dev/api/generate-content#v1beta.models.generateContent)

### AWS

- [Amazon Bedrock interface VPC endpoints (AWS PrivateLink)](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
- [Route 53 Resolver: forwarding inbound DNS queries to your VPC](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries.html)

### Anthropic

- [Messages API](https://docs.anthropic.com/en/api/messages)

### Model Context Protocol

- [MCP Specification: Authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization)

### IETF

- [RFC 8707: Resource Indicators for OAuth 2.0](https://www.rfc-editor.org/rfc/rfc8707.html)
- [RFC 9728: OAuth 2.0 Protected Resource Metadata](https://www.rfc-editor.org/rfc/rfc9728.html)
