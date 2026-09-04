# AI Hub(LLM Gateway) 구성 검증 및 확장성 검토

> 검토 기준일: 2026-09-03<br>
> 검토 범위: Azure API Management 기반 멀티벤더 LLM Gateway, Azure OpenAI 용량, 멀티클라우드 사설 연결, PII 가드레일, 사내 SSO 기반 MCP 인증·인가

## 1. Executive Summary

실제 Bicep·APIM policy 예제는
[APIM 타사 모델 Gateway 참조 구현](../apim/third-party-model-gateway/README.md)을 참고한다.

현재 검토 대상 구성은 다음과 같다.

```text
Azure OpenAI 계열
AI App → Application Gateway → UTM(IDS/IPS) → APIM → Azure OpenAI/Foundry

Gemini 계열
AI App → Application Gateway → UTM(IDS/IPS) → APIM
       → Azure-GCP Site-to-Site VPN → Vertex AI
```

APIM을 공통 AI Gateway로 사용하고 Azure OpenAI, Vertex AI, 향후 Amazon
Bedrock을 백엔드로 연결하는 방향은 기술적으로 타당하다. 다만 다음 항목은
서로 독립된 확장 축으로 판단해야 한다.

1. APIM Gateway의 처리 용량과 네트워크 격리
2. Azure OpenAI 모델의 TPM/RPM quota와 실제 capacity
3. GCP/AWS까지의 사설 네트워크와 공급자별 인증
4. PII 가드레일과 MCP 사용자·워크로드 인증/인가

핵심 권고는 다음과 같다.

- Azure OpenAI TPM 부족을 이유로 APIM Premium으로 전환하지 않는다.
- 현재 트래픽이 10개 scale unit 이내이고 Full VNet Injection 또는
  Availability Zone이 필수가 아니라면 Standard v2를 우선 유지한다.
- Premium v2와 클래식 Premium을 동일한 SKU로 취급하지 않는다.
- Standard v2에서 Premium v2로의 인플레이스 변경은 공식 변경 매트릭스에
  명시되어 있지 않으므로 신규 인스턴스 기반 병행 전환으로 계획한다.
- Azure-GCP Site-to-Site VPN은 적합한 선택이지만, 운영 구성은 HA VPN,
  BGP, Private Service Connect(PSC), route advertisement, private DNS까지
  포함해야 한다.
- Azure OpenAI에는 모든 모델에 공통인 단일 "구독당 최대 TPM"이 없다.
- 예측 가능한 base load는 Provisioned Throughput, 일시적인 burst는
  Standard spillover로 처리하는 방식을 우선 검토한다.
- APIM의 `llm-content-safety` 정책만으로는 PII를 탐지할 수 없다.
- HTTP 기반 MCP에 사내 Entra SSO를 연계할 수 있다. 다만 최신 MCP가
  요구하는 RFC 8707 `resource`를 Entra v2 endpoint가 지원하지 않으므로,
  표준 준수가 필요하면 호환 Authorization Server 계층이 추가로 필요하다.

## 2. 질문 재구성

원문의 문의사항은 다음 네 영역으로 구분하는 것이 명확하다.

| 영역 | 의사결정 질문 |
|---|---|
| APIM | Standard v2를 언제 Premium v2 또는 클래식 Premium으로 전환하는가? |
| Azure OpenAI | TPM 상한과 증설 기준은 무엇이며 언제 PTU로 전환하는가? |
| 멀티클라우드·가드레일 | Vertex AI/Bedrock 연결은 적합한가? PII는 어디서 차단하는가? |
| MCP | 사내 Entra SSO를 이용한 사용자·워크로드 인증/인가가 가능한가? |

## 3. APIM SKU와 Gateway 확장성

### 3.1 공식 문서에 명시된 기능 차이

Microsoft의 APIM 기능 비교 문서 기준 주요 차이는 다음과 같다.

| 항목 | Standard v2 | Premium v2 | 클래식 Premium |
|---|---:|---:|---:|
| 최대 scale unit | 10 | 30 | 리전당 12 |
| 사설 백엔드 연결 | 지원 | 지원 | 지원 |
| Inbound Private Endpoint | 지원 | 지원 | 지원 |
| Full VNet Injection | 미지원 | 지원 | 지원 |
| Availability Zone | 미지원 | 지원 | 지원 |
| Multi-region deployment | 미지원 | 미지원 | 지원 |
| Self-hosted Gateway | 미지원 | 미지원 | 지원 |
| Backup/Restore | 미지원 | 미지원 | 지원 |

Standard v2와 Premium v2의 VNet Integration은 사설 백엔드에 접근하기
위한 outbound 기능이다. VNet Integration만 적용하면 gateway, management
plane, developer portal은 계속 공용 접근 경로를 가진다. Standard v2는
별도의 inbound Private Endpoint를 지원하므로, 필요한 경우 public network
access 제한과 함께 구성할 수 있다.

Premium v2의 VNet Injection은 inbound와 outbound gateway 트래픽을 VNet에
격리할 수 있다. Microsoft는 Premium v2 gateway가 전용 App Service
Environment에서 실행된다고 명시한다.

### 3.2 처리량 판단 기준

APIM의 scale unit은 고정 호출 한도가 아니라 대략적인 capacity planning
단위이다. Microsoft는 실제 처리량과 지연시간이 다음 요소에 따라 크게
달라진다고 명시한다.

- 동시 연결 수와 요청률
- 적용된 정책의 종류와 개수
- 요청·응답 크기
- backend latency
- 장시간 유지되는 streaming 연결

따라서 TPS 하나만으로 SKU를 결정하면 안 된다. JWT 검증, body parsing,
token counting, 외부 `send-request`, Content Safety, logging 등 실제 운영
정책을 포함한 부하 시험이 필요하다.

### 3.3 Standard v2 유지 조건

다음 조건을 충족하면 Standard v2를 우선 유지한다.

- 10개 scale unit 안에서 목표 처리량과 지연시간을 만족한다.
- Full VNet Injection이 필수 보안 요건이 아니다.
- Availability Zone이 필수 가용성 요건이 아니다.
- Multi-region APIM 또는 Self-hosted Gateway가 필요하지 않다.
- Inbound Private Endpoint와 outbound VNet Integration으로 네트워크 요구를
  충족할 수 있다.

### 3.4 Premium 계열 검토 조건

**Premium v2**는 다음 요구가 있을 때 검토한다.

- Full VNet Injection
- Availability Zone
- Standard v2의 10개 unit을 초과하는 용량
- 전용 gateway compute
- 여러 gateway custom domain

**클래식 Premium**은 다음 요구가 있을 때 검토한다.

- 하나의 APIM 서비스에 대한 multi-region deployment
- Self-hosted Gateway
- Backup/Restore 등 Premium v2가 지원하지 않는 클래식 기능

### 3.5 Standard v2에서 Premium v2로의 전환

공식 APIM 업그레이드 문서는 다음 변경만 명시한다.

- Developer, Basic, Standard, Premium 등 클래식 tier 사이의 변경
- Basic v2와 Standard v2 사이의 변경

Standard v2에서 Premium v2로의 인플레이스 변경은 지원 변경 매트릭스에
명시되어 있지 않다. 따라서 Microsoft가 대상 구독과 리전에 별도 전환
기능을 제공한다고 확인하기 전에는 다음 병행 마이그레이션을 기준으로
계획한다.

1. 신규 Premium v2 인스턴스 생성
2. API, policy, product, Named Value, 인증서, custom domain 이전
3. 실제 AI 정책을 포함한 병행 부하 시험
4. Application Gateway backend 또는 DNS 전환
5. rollback 기간 운영
6. 기존 Standard v2 종료

## 4. Application Gateway, UTM, APIM 경로

현재 계층 구조는 사용할 수 있지만, LLM streaming에서는 중간 hop이 장애와
지연의 원인이 될 수 있다.

다음 항목을 운영 전 검증한다.

- SSE 및 chunked response가 buffering되지 않는지
- Application Gateway와 UTM의 idle timeout이 최대 생성 시간보다 긴지
- UTM TLS inspection이 streaming 연결을 중단하지 않는지
- prompt, image, document의 요청 크기 제한
- 응답 크기 제한
- 비대칭 라우팅
- SNAT 포트 고갈
- TLS 재암호화와 인증서 신뢰
- prompt와 completion 원문 logging 여부

Application Gateway Standard v2의 response buffering은 SSE 전달을 지연시킬
수 있으므로, 별도 가이드인
[Application Gateway SSE 통신 시 Response Buffer 비활성화 가이드](../appgw/sse_response_buffer_disable.md)를
함께 적용한다.

권장 책임 분리는 다음과 같다.

- Application Gateway: WAF, 외부 진입점, L7 routing
- UTM: IDS/IPS와 조직 네트워크 보안 정책
- APIM: 인증, token quota, API/model routing, 정책, 감사
- Guardrail Service: PII와 업무별 데이터 정책
- LLM Provider: 추론 capacity와 provider 기본 safety filter

## 5. Vertex AI와 Bedrock 연동

### 5.1 Vertex AI

Google은 사내 또는 외부 네트워크에서 GenAI API에 접근하는 사설 연결 예제로
HA VPN, Cloud Router/BGP, Google APIs용 PSC endpoint, custom route
advertisement, private DNS를 제시한다.

권장 경로는 다음과 같다.

```text
APIM VNet
  → Azure VPN Gateway
  → 이중 IPsec tunnel/BGP
  → GCP HA VPN + Cloud Router
  → Google APIs용 PSC endpoint
  → Vertex AI
```

Google HA VPN 문서는 99.99% 가용성 SLA 요건으로 HA VPN gateway의 두
interface에 각각 tunnel을 구성하도록 명시한다. 단일 tunnel은 이 요건을
충족하지 않는다.

다음 사항을 확인한다.

- Azure와 GCP CIDR 비중복
- 두 개 이상의 tunnel과 BGP session
- PSC 내부 IP의 Azure 방향 route advertisement
- Vertex AI hostname의 private DNS resolution
- MTU/MSS와 streaming 안정성
- 한 tunnel 장애 시 나머지 경로의 수용 capacity
- tunnel utilization, packet loss, jitter

Site-to-Site VPN 자체는 적절하다. 다만 단일 tunnel이거나 Vertex AI public
endpoint를 VPN 너머로 우회 호출하는 것만으로는 완전한 사설 연결로 보기
어렵다.

Cloud Interconnect 계열은 다음 조건이 측정으로 확인될 때 검토한다.

- VPN 처리량 한계
- 지속적인 packet loss 또는 jitter
- 엄격한 latency·가용성 SLA
- 대규모 멀티모달 데이터 전송
- 인터넷 기반 IPsec을 허용하지 않는 보안 요건

### 5.2 Amazon Bedrock

AWS는 Amazon Bedrock에 대해 AWS PrivateLink 기반 interface VPC endpoint를
공식 지원한다.

```text
APIM
  → Azure-AWS VPN 또는 전용 연결
  → AWS VPC
  → Bedrock Runtime Interface VPC Endpoint
  → Amazon Bedrock
```

사용 API에 따라 다음 endpoint를 구성한다.

- 추론: `bedrock-runtime`
- Agent runtime: `bedrock-agent-runtime`
- Control plane: `bedrock`

Private DNS를 활성화하면 VPC 내부에서는 표준 regional hostname을 사용할
수 있다. Azure처럼 VPC 외부에서 VPN 또는 전용 연결을 통해 호출하는
클라이언트가 같은 private DNS 결과를 사용하려면 다음 hybrid DNS 구성이
추가로 필요하다.

- AWS VPC에 Route 53 Resolver inbound endpoint 배치
- Azure DNS Private Resolver 또는 사내 DNS에서 Bedrock 도메인을 조건부 전달
- VPN/전용 연결과 security group에서 Resolver endpoint의 TCP/UDP 53 허용

또는 VPC endpoint 전용 DNS 이름을 명시적으로 사용한다. 이 구성이 없으면
Azure에서 표준 hostname이 공용 주소로 해석되어 의도한 사설 경로를 우회할
수 있다.

VPC endpoint policy, IAM policy, security group에서는 호출 주체, model,
`InvokeModel`, `InvokeModelWithResponseStream` 등 필요한 범위만 허용한다.

### 5.3 공급자 인증

VPN, PSC, PrivateLink는 네트워크 경로를 보호하지만 API 인증을 대체하지
않는다.

- Azure backend에는 APIM Managed Identity를 우선 사용한다.
- GCP에는 Workload Identity Federation 또는 단기 OAuth token을 사용한다.
- AWS에는 IAM role, 단기 자격증명, SigV4를 사용한다.
- 장기 GCP service account key와 AWS access key를 APIM policy에 직접
  저장하지 않는다.
- 불가피한 secret은 Key Vault-backed Named Value로 관리하고 회전한다.

APIM은 Vertex AI API와 Amazon Bedrock 등 외부 AI endpoint를 관리할 수
있다. 여러 provider를 하나의 OpenAI-compatible endpoint로 노출하는 APIM
Unified Model API는 공식 문서상 preview이므로 production 핵심 인터페이스로
채택할 때 preview 지원 정책을 별도로 평가한다.

## 6. Azure OpenAI TPM과 quota 증설

### 6.1 단일 최대 TPM이 없는 이유

모든 Azure OpenAI 모델에 공통인 "구독당 최대 TPM"은 없다. 실제 quota는
다음 조합에 따라 결정된다.

- Azure subscription
- 모델과 모델 버전
- Global, Data Zone, Regional deployment type
- 구독의 quota tier
- 해당 모델에 적용된 quota 관리 방식
- 실제 regional capacity

Microsoft 문서에 따르면 quota 제한의 최상위 범위는 tenant가 아니라 Azure
subscription이다. 2026-05-07 이후 subscription-level quota pool이
단계적으로 도입되었으며, 문서는 Realtime Translate와 Realtime Whisper부터
시작해 다른 모델로 확대한다고 설명한다.

- Global Standard: 같은 모델과 버전이 구독 내 리전 간 quota pool 공유
- Data Zone Standard: 같은 모델과 버전이 data zone별 quota pool 공유

따라서 모든 모델이 이미 같은 방식으로 전환되었다고 가정하지 말고 Foundry
quota 화면 또는 management API에서 대상 모델의 실제 quota scope를
확인한다.

### 6.2 Quota tier와 추가 요청

공식 문서에는 Free와 Tier 1~6이 정의되어 있다. 자동 tier 상승은 Foundry
Models 소비 추세, Microsoft와의 enterprise 관계(EA, MCA-E 등), 결제 이력
등을 고려한다.

추가 quota는 공식 quota request form으로 요청할 수 있다. 승인 시 현재
tier를 유지하면서 quota만 추가될 수도 있다. Microsoft는 모든 요청에
적용되는 고정 승인 산식이나 보장된 절대 상한을 공개하지 않는다.

증설 요청에는 다음 자료를 포함한다.

- 모델, 버전, deployment type, 리전
- 현재 TPM/RPM과 최근 peak 및 p95
- 429 발생량과 업무 영향
- 평균 input/output token과 peak RPM
- 3~6개월 수요 전망
- go-live 일정과 업무 중요도
- DR 및 data residency 요구

다음을 별도로 관리해야 한다.

```text
Quota 승인 ≠ 특정 모델·리전의 실제 capacity 확보
```

## 7. Standard와 Provisioned Throughput 선택

공식 문서의 용도 구분은 다음과 같다.

| 방식 | 과금 | 적합한 트래픽 |
|---|---|---|
| Standard | token 종량제 | 변동하거나 예측하기 어려운 트래픽 |
| Priority Processing | 높은 token 종량제 | 장기 약정 없이 일관된 저지연이 필요한 트래픽 |
| Provisioned | PTU 시간 과금 또는 Reservation | 예측 가능한 고규모·미션 크리티컬 트래픽 |
| Batch | 할인된 token 종량제 | latency 요구가 없는 비동기 대량 작업 |

Microsoft는 "TPM이 얼마 이상이면 PTU로 전환"이라는 고정 기준을 제공하지
않는다. 다음 항목으로 모델별 PTU를 산정해야 한다.

- peak RPM
- 평균 prompt token
- 평균 response token
- 모델별 input TPM/PTU
- output-to-input ratio
- 모델별 cache 영향

권장 절차는 다음과 같다.

1. 최소 2~4주의 실제 input/output token, RPM, 429, latency 수집
2. Foundry capacity calculator로 1차 산정
3. 대표 트래픽으로 실제 deployment benchmark
4. Standard 비용·429·latency와 PTU 비용 비교
5. 대상 모델과 리전의 quota 및 capacity 확인
6. 소규모 PTU 배포와 부하 시험
7. 안정화 후 Reservation 구매 검토

Microsoft의 최신 sizing 문서도 추정치만 사용하는 것보다 대표 트래픽으로
benchmark할 것을 권고한다.

Azure OpenAI 모델의 권장 운영 패턴은 다음과 같다.

```text
예측 가능한 base load → Provisioned
일시적인 burst         → 같은 Foundry resource의 Standard spillover
```

다른 provider의 Foundry 모델은 동일한 spillover 지원을 제공하지 않을 수
있으므로 모델별 지원 여부를 확인한다.

## 8. PII와 민감정보 가드레일

### 8.1 Content Safety와 PII의 역할

APIM의 `llm-content-safety` 정책은 다음 범주를 검사한다.

- Hate
- SelfHarm
- Sexual
- Violence
- Prompt attack
- Custom blocklist

주민등록번호, 이름, 주소, 계좌번호, 전화번호 등의 범용 PII는 이 정책의 기본
category가 아니다.

Azure Language PII는 text, conversation, native document에서 PII를 식별,
분류, redact하고 entity category, confidence score, redacted result를
반환한다.

### 8.2 권장 처리 흐름

```text
Inbound
  → schema/size 검증
  → PII Detect
  → Block/Redact/Tokenize
  → Prompt Shield/Content Safety
  → LLM

Outbound
  → PII 재검사
  → Block/Mask
  → Client
```

추가 통제는 다음과 같다.

- APIM과 Application Insights에 raw prompt/completion을 기본 저장하지 않는다.
- 필요한 로그는 PII redaction 후 저장한다.
- 복원이 필요한 값은 LLM과 분리된 token vault에 저장한다.
- 주민등록번호와 사업자번호는 regex뿐 아니라 checksum을 적용한다.
- 이름과 주소 등 비정형 PII는 NER 기반 탐지를 병행한다.
- 한국어 사내 데이터로 false positive와 false negative를 측정한다.

단순 text 요청과 낮은 트래픽은 APIM `send-request`로 동기 Text PII API를
호출할 수 있다. 다만 동기 Language API의 현재 입력 한도는 문서당 5,120
text elements, 요청당 최대 5개 문서, 전체 요청 1 MB이다. 이 한도를 넘는
문서는 invalid-document 오류가 발생할 수 있다.

긴 prompt를 분할하면 chunk 경계에 걸친 PII의 문맥이 손실될 수 있으므로
overlap window와 재조합 검증이 필요하다. 복잡한 chat JSON, 긴 prompt,
파일, 멀티모달, 높은 트래픽 또는 엄격한 streaming 통제가 필요하면 비동기
처리 또는 별도 Guardrail Service를 배치하는 편이 운영에 적합하다.

## 9. 사내 SSO 기반 MCP 인증·인가

### 9.1 타당성

HTTP 기반 MCP에 Entra ID 사내 SSO를 연계할 수 있다. 그러나 최신 MCP
Authorization 사양을 그대로 준수하는 범용 MCP Client와 Entra v2 endpoint를
직접 연결하는 구성은 현재 완전 호환되지 않는다.

- Entra ID: 사내 사용자 인증과 SSO를 제공하는 upstream Identity Provider
- MCP 호환 Authorization Server: RFC 8707과 MCP discovery/registration 처리
- APIM 또는 MCP Server: MCP OAuth Resource Server
- MCP Client: OAuth Client

사람 사용자는 Authorization Code + PKCE와 Entra SSO, MFA, Conditional
Access를 적용한다. daemon과 agent workload는 certificate, Managed Identity,
federated credential 또는 Client Credentials를 사용한다. 사용자 SSO와
workload identity를 동일하게 취급하면 안 된다.

### 9.2 최신 MCP Authorization 요구사항

검토 기준일의 MCP `latest` 링크는 2026-07-28 Authorization 사양으로
연결된다. 주요 요구사항은 다음과 같다.

- HTTP transport는 OAuth 기반 Authorization 사양을 사용한다.
- STDIO transport는 이 HTTP Authorization 사양을 사용하지 않는다.
- MCP Server는 Protected Resource Metadata(RFC 9728)를 제공한다.
- OAuth 또는 OIDC authorization server discovery를 지원한다.
- Authorization Code 흐름에 PKCE를 적용한다.
- authorization과 token 요청에 RFC 8707 `resource`를 포함한다.
- MCP resource를 intended audience로 하는 token인지 검증한다.
- 인증이 필요하거나 token이 잘못되면 401을 반환한다.
- scope가 부족하면 403을 반환한다.
- Client ID Metadata Documents가 권장된다.
- Dynamic Client Registration은 최신 사양에서 deprecated compatibility
  option이다.
- 사전 등록된 client ID는 유효한 registration mechanism이다.

반면 Microsoft Entra v2 authorization endpoint는 대상 API를 `scope`로
지정하며 RFC 8707 `resource`를 지원 파라미터로 정의하지 않는다. Entra v2
요청에 `resource`를 넣으면 실패한다. 따라서 APIM에서 발급된 token을
검증하는 것만으로 이 authorization handshake의 차이가 해결되지는 않는다.

### 9.3 권장 구현

```text
MCP Client
  → MCP 호환 Authorization Server
      → Entra ID: 사용자 SSO
  → APIM: MCP resource용 token 검증 및 operation/tool 1차 인가
  → MCP Server: 객체·문서·행 단위 최종 인가
  → 사내 API 또는 Data Source
```

1. MCP endpoint가 Protected Resource Metadata를 제공한다.
2. MCP Client가 MCP 호환 Authorization Server의 metadata를 조회한다.
3. Authorization Server가 Entra ID를 upstream IdP로 사용해 사내 SSO를
   수행한다.
4. MCP Client는 canonical MCP URI를 `resource` parameter에 포함한다.
5. 호환 Authorization Server는 `resource`를 검증하고 MCP resource
   audience에 바인딩된 access token을 발급한다.
6. APIM은 token의 issuer, audience, expiry, client ID, scope 또는 role을
   검증한다. Entra token을 직접 사용하는 폐쇄형 구현에서는
   `validate-azure-ad-token`을 사용할 수 있지만, 이는 scope-only Entra
   흐름을 따르므로 최신 MCP의 RFC 8707 요구사항을 완전히 충족하지 않는다.
7. scope와 app role을 APIM operation 또는 MCP tool allowlist에 매핑한다.
8. MCP backend에서 문서, 프로젝트, 고객, 행 단위 권한을 재검증한다.
9. downstream 사내 API에 사용자 위임이 필요하면 Authorization Server 또는
   backend에서 적절한 token exchange/OBO를 적용한다.
10. 외부 LLM에는 사용자의 SSO token을 전달하지 않고 provider별 backend
   credential을 사용한다.

권장안은 Entra ID를 upstream SSO IdP로 사용하면서, MCP의 RFC 8707
`resource`, discovery, client registration을 처리하는 호환 Authorization
Server 또는 broker를 두는 것이다.

조직이 통제하는 MCP Client와 Server만 사용하는 폐쇄형 환경에서는 Entra
App Registration과 `scope` 기반 흐름을 사용할 수 있으나, 이 경우 최신 MCP
Authorization 완전 준수가 아닌 사내 호환 프로파일임을 명시해야 한다.
Entra v1의 `resource` 파라미터를 RFC 8707 호환으로 간주해서도 안 된다.

최종 PoC에서 다음 지원 여부를 확인한다.

- RFC 9728 Protected Resource Metadata
- OAuth/OIDC metadata discovery
- PKCE
- RFC 8707 `resource`
- pre-registered client ID
- scope challenge와 401/403 처리

## 10. 단계별 실행 로드맵

### 1단계: 현황 측정

- APIM unit, `CPU Percentage of Gateway`, `Memory Percentage of Gateway`,
  p95/p99 latency 수집
- 앱별 input/output token, RPM, 429, backend latency 수집
- Application Gateway와 UTM의 SSE, timeout, buffering 검증
- GCP tunnel, BGP, PSC, DNS 구성 확인

### 2단계: 단기 개선

- Standard v2 autoscale 적용
- 앱·부서별 APIM token limit 및 quota 적용
- prompt/completion raw logging 차단
- 입력·출력 PII 검사 PoC
- GCP 단일 tunnel이면 HA tunnel과 BGP 구성

### 3단계: 용량 및 보안 검증

- 운영 정책을 포함한 APIM 부하 시험
- PTU calculator와 representative benchmark 실행
- Provisioned base load와 Standard spillover 시험
- MCP Client OAuth 호환성 PoC

### 4단계: 조건 충족 시 전환

- Full VNet Injection, AZ, 10유닛 초과 시 Premium v2 병행 마이그레이션
- Multi-region 또는 Self-hosted Gateway 필요 시 클래식 Premium 검토
- VPN 한계가 측정되면 Interconnect 또는 전용 연결 검토
- 안정적인 PTU 사용량이 확인된 후 Reservation 구매

## 11. 최종 의사결정표

| 질문 | 권고 |
|---|---|
| 지금 APIM Premium으로 전환해야 하는가? | 기능 또는 부하 시험 근거가 없다면 Standard v2 유지 |
| TPM 증가가 Premium 전환 사유인가? | 아니요. APIM capacity와 모델 quota는 별개 |
| Standard v2에서 Premium v2로 바로 변경하는가? | 공식 변경 경로가 명시되지 않았으므로 신규 인스턴스 기반 병행 전환 |
| GCP S2S VPN이 적절한가? | 적절함. 단, HA VPN+BGP+PSC+route+private DNS 필요 |
| Azure OpenAI 최대 TPM은 얼마인가? | 공통 최대치 없음. 구독·모델·버전·배포 유형별 조회 필요 |
| 언제 PTU로 전환하는가? | 예측 가능한 지속 부하, latency 요구, 비용 비교와 benchmark 결과로 결정 |
| Content Safety가 PII를 제거하는가? | 아니요. Azure Language PII 또는 별도 Guardrail 필요 |
| MCP에 사내 SSO를 적용할 수 있는가? | 가능. 최신 MCP 완전 준수에는 Entra 앞의 RFC 8707 호환 Authorization Server 계층 필요 |

## 12. 공식 참고자료

### Azure API Management

- [Azure API Management v2 tiers overview](https://learn.microsoft.com/azure/api-management/v2-service-tiers-overview)
- [Feature-based comparison of API Management tiers](https://learn.microsoft.com/azure/api-management/api-management-features)
- [Upgrade and scale an API Management instance](https://learn.microsoft.com/azure/api-management/upgrade-and-scale)
- [AI gateway capabilities in API Management](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities)
- [LLM content safety policy](https://learn.microsoft.com/azure/api-management/llm-content-safety-policy)
- [Validate Microsoft Entra token policy](https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy)
- [Capacity metrics for API Management](https://learn.microsoft.com/azure/api-management/api-management-capacity)

### Microsoft Foundry and Azure OpenAI

- [Azure OpenAI quotas and limits](https://learn.microsoft.com/azure/foundry/openai/quotas-limits)
- [Provisioned throughput](https://learn.microsoft.com/azure/foundry/openai/concepts/provisioned-throughput)
- [Determine PTU sizing for a workload](https://learn.microsoft.com/azure/foundry/openai/how-to/provisioned-throughput-sizing)
- [Azure Language PII detection](https://learn.microsoft.com/azure/ai-services/language-service/personally-identifiable-information/overview)
- [Data limits for Azure Language](https://learn.microsoft.com/azure/ai-services/language-service/concepts/data-limits)

### Google Cloud and AWS

- [Google Cloud HA VPN topologies](https://cloud.google.com/network-connectivity/docs/vpn/concepts/topologies)
- [Access Google APIs through Private Service Connect endpoints](https://cloud.google.com/vpc/docs/configure-private-service-connect-apis)
- [Amazon Bedrock interface VPC endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/vpc-interface-endpoints.html)
- [Route 53 Resolver inbound endpoints](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/resolver-forwarding-inbound-queries.html)

### MCP

- [Latest MCP Authorization specification](https://modelcontextprotocol.io/specification/latest/basic/authorization)
- [Microsoft identity platform authorization code flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-auth-code-flow)
