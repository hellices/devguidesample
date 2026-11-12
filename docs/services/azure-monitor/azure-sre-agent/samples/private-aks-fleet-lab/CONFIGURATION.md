# 다중 허브·방화벽 Private AKS 사전 점검 실습 구성 상세

## 네트워크

| 영역 | 리소스 및 주소 대역 | 역할 및 핵심 설정 |
| --- | --- | --- |
| 에이전트 관리 VNet (`koreacentral`) | `vnet-sre-agent-hub` (`10.42.0.0/16`)<br>`snet-sre-agent-sandbox` (`10.42.4.0/24`) | `Microsoft.App/environments` 위임 전용 서브넷. UDR(`rt-sre-agent-sandbox`)이 `10.52.0.0/16` 및 `10.60.0.0/16` 목적지의 Next Hop을 Hub #1 방화벽(`10.51.250.4`)으로 전달 |
| 코어 방화벽 허브 (`australiaeast`) | `vnet-fleet-hub-01` (`10.51.0.0/16`, `fw-hub-01` `10.51.250.4`)<br>`vnet-fleet-aks-hub` (`10.52.0.0/16`, `fw-hub-02` `10.52.250.4`)<br>`vnet-fleet-hub-03` (`10.53.0.0/16`, `fw-hub-03` `10.53.250.4`) | 3개 허브 VNet이 Full-Mesh VNet Peering(`AllowForwardedTraffic: true`)으로 연결되어 에이전트 서브넷(`10.42.4.x`)과 각 AKS API 서버 Private Endpoint 간 양방향 대칭 라우팅 제공 |
| Hub #2 내장 Private AKS | `aks-priv-01` ~ `05` (`10.52.11.0/24` ~ `10.52.15.0/24`) | API 서버 Private Endpoint(`10.52.11.4` ~ `10.52.15.4`). 동일 VNet 내 방화벽 우회 방지를 위해 `privateEndpointNetworkPolicies: Enabled` 적용 |
| Hub #3 산하 Spoke Private AKS | `aks-priv-06` ~ `10` (`10.60.6.0/24` ~ `10.60.10.0/24`) | API 서버 Private Endpoint(`10.60.6.4` ~ `10.60.10.4`). `10.42.4.x ➔ 10.51.250.4 ➔ 10.53.250.4 ➔ 10.60.x.4:443` 경로로 통신 |

### 에이전트 VNet 설정과 `*.azmk8s.io` 공용 우회 해제

에이전트 리소스의 `sandboxConfiguration.egress.allowedHosts`에 `*.azmk8s.io`가 포함되어 있으면,
에이전트는 사설 VNet 경로 대신 Microsoft 공용 인프라 네트워크로 AKS API 호출을 우회시켜 사설 DNS 해석에
실패합니다. 따라서 `allowedHosts`에서 `*.azmk8s.io`를 반드시 제외합니다.

또한 에이전트의 일반 `bash` 터미널 도구는 외부 HTTPS(443) 연결에 내부 이그레스 프록시 인증서(`ADC Egress Proxy Intermediate CA`)를
주입하므로 사설 AKS 자체 서명 인증서와 충돌(`x509: certificate signed by unknown authority`)할 수 있습니다.
데이터 플레인 조회에는 프록시 간섭 없이 전용 서브넷으로 직접 나가는 내장 도구 `RunKubectlReadCommand`를 사용합니다.

## 권한

| 주체 | 범위 | 역할 | 목적 |
| --- | --- | --- | --- |
| 에이전트 UAMI·시스템 MI | 클러스터 리소스 그룹 | `Reader`, `Azure Kubernetes Service Cluster User Role` | 컨트롤 플레인 메타데이터(`az aks list`) 및 `kubeconfig` 조회 |
| 에이전트 UAMI·시스템 MI | 클러스터 리소스 그룹 | `Azure Kubernetes Service RBAC Reader` | Azure RBAC(`--enable-azure-rbac`) 기반 클러스터 내부 파드·디플로이먼트·PDB 읽기(`dataActions`) |
| 배포 관리자 계정 | 에이전트 리소스 | `SRE Agent Administrator` | 포털 도구·스킬·지식 원본 관리 및 변경 작업 승인 |

---

# 엔터프라이즈 Private AKS + vWAN 방화벽 + Grafana(12컬럼) + Azure SRE Agent(9대 사전 점검 · 점프박스 감사) 전체 구축 가이드

- **문서 목적**: **리소스 공급자 등록 ➔ 리소스 그룹 3개 ➔ Virtual WAN & Secured Hub(Azure Firewall) ➔ 방화벽 정책(`afwp-sre-vwan`) · 규칙 컬렉션 그룹(`rcg-sre-to-aks`) · 규칙 · 허브 연결 · `Routing Intent` ➔ VNet 4개 & 전용 서브넷 위임 ➔ DNS Private Resolver(`10.10.0.4`) & 허브 VNet 연결 4건 ➔ Log Analytics 2개 · UAMI 3개(RBAC) · Private AKS 3대(12컬럼 태그) · DNS 링크 ➔ 사전 점검 재현용 K8s 워크로드 배포 ➔ SRE Agent & 최소 권한 RBAC ➔ Dashboard with Grafana 13패널 JSON Import ➔ `sre.azure.com` 도구·스킬·고급 권한·서브에이전트·월간 스케줄·채팅 검증**까지 순서대로 구성하는 매뉴얼입니다.
- **주요 구성 사양**:
  1. **Grafana (`SRE-AKS-Management` — `Azure Monitor > Dashboards with Grafana`) 13개 패널 및 12개 표준 인벤토리 컬럼**:
     - **대시보드 JSON 파일**: [`./monitoring/sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json) (`Azure Monitor > Dashboards with Grafana > New > Import`)
     - **표준 12개 컬럼**: `mgmtName`, `Subscription`, `Cluster`, `k8sVersion`, `SupportPlan` (`KubernetesOfficial` vs `AKSLongTermSupport`), `PricingTier`, `ServiceName`, `ServiceCode`, `ServiceOpenDate`, `ServiceGrade` (`S`/`A`/`B`/`C`), `APIServerAccess`, `NetworkPlugin` (+ 노드풀 패널 `NodePool`, `Mode`)
  2. **AKS 업그레이드 9대 사전 점검 체크리스트 (`evaluate-aks-upgrade-preflight`)**:
     - ① 애플리케이션 Pod 고가용성 구성 (특정 노드 파드 편중 여부, 컨트롤러 없는 Naked Pod 존재 여부, `replicas==1`)
     - ② `HostPath` / `emptyDir` 및 `Local Storage PV` 존재 여부 확인
     - ③ Pod 스케줄링 제약 조건 확인 (`nodeAffinity`, `nodeSelector`, 리소스 부족 `Pending` 등)
     - ④ PDB 설정 확인 (`ALLOWED DISRUPTIONS == 0`)
     - ⑤ Kubernetes API Deprecation 및 애드온(`ingress-nginx`) 호환성 확인
     - ⑥ Graceful Shutdown (`livenessProbe` / `readinessProbe` / `preStop` 설정 여부)
     - ⑦ 노드풀이 사용 중인 서브넷의 가용 IP 확인 (`maxSurge` 여유 IP)
     - ⑧ AKS Identity 권한 확인 (사용 중인 타 RG VNet/Subnet에 클러스터 UMI `Network Contributor` 권한 누락 여부)
     - ⑨ AKS 모니터링 속성 중 Log Analytics Workspace Resource ID 유효성 확인
  3. **데이터 플레인 상태 점검 (`RunKubectlReadCommand`)**:
     - VNet 사설망 기반 내장 `RunKubectlReadCommand`로 Private AKS의 비정상 파드(`Pending`/`ImagePullBackOff`/`CrashLoopBackOff`), 이벤트 및 인그레스 구성을 조회합니다.

---

## 전체 구축 로드맵 요약

| 단계 (Phase) | Step 번호 | 작업 위치 | 핵심 수행 내용 |
|---|---|---|---|
| **Phase 0**<br>기초 준비 | • **Step 00**: 리소스 공급자 5종 등록 & RG 3개 생성 | `portal.azure.com` | • `Microsoft.Network`, `ContainerService`, `App`, `Dashboard`, `OperationalInsights` 등록<br>• `rg-sre-vwan-network`, `rg-sre-private-aks-fleet`, `rg-sre-agent-fleet` 생성 |
| **Phase 1**<br>vWAN · 방화벽 · VNet · DNS · Private AKS · 워크로드 배포 | • **Step 01-A**: vWAN(`vwan-sre`) & Secured Hub(`vhub-sre` + FW + `afwp-sre-vwan`) 생성<br>• **Step 01-B**: 방화벽 규칙 컬렉션 그룹(`rcg-sre-to-aks`) · 규칙 · 허브 연결 · `Routing Intent`<br>• **Step 01-C**: 4개 VNet & 서브넷(`snet-sre-agent-sandbox` 등) 위임<br>• **Step 01-D**: DNS Private Resolver(`dnspr-sre` / `in-ep-sre`) & vWAN VNet 연결 4건<br>• **Step 02-A**: Log Analytics 2개 · UAMI 3개(RBAC) · Private AKS 3대(12컬럼 태그) · DNS 링크<br>• **Step 02-B**: 포털 `Run command`로 사전 점검 시나리오 워크로드 배포 | `portal.azure.com` | • Standard vWAN, 방화벽 정책(`afwp-sre-vwan`), Secured Hub 내장 Azure Firewall 생성<br>• `rcg-sre-to-aks`(우선순위 200) 내 네트워크 규칙(210)·애플리케이션 규칙(220) 및 Routing Intent 구성<br>• 4개 VNet 서브넷 및 위임(`Microsoft.Network/dnsResolvers`, `Microsoft.App/environments`) 설정<br>• UAMI 3개 권한 부여, Private AKS 3대 생성, 항목 ⑧/⑨ 장애 조건 재현, Private DNS Zone 링크 연결<br>• 버전별 `ingress-nginx`, `Pending`, `HostPath`, 차단 `PDB`, `CrashLoop` 등 시나리오 파드 주입 |
| **Phase 2**<br>SRE Agent 생성 · 최소 권한 · Grafana Import | • **Step 03**: SRE Agent 생성 및 최소 읽기 권한(RBAC) 부여<br>• **Step 04-A**: `Azure Monitor > Dashboards with Grafana` (`SRE-AKS-Management`) JSON Import<br>• **Step 04-B**: Grafana 13개 패널 & 12컬럼 인벤토리 KQL 확인 | `portal.azure.com` | • SRE VNet과 동일 리전에 SRE Agent 생성, UAMI에 구독 `Reader`/`Monitoring Reader` 및 AKS `Cluster User`/`RBAC Reader` 부여<br>• `SRE-AKS-Management`에 [`sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json) 업로드 |
| **Phase 3**<br>SRE 포털 리소스 · VNet 우회 해제 · 지식 베이스 | • **Step 05**: 관리 대상 구독/RG 연결 (`Managed resources`)<br>• **Step 06**: VNet 통합 및 `[ ] AKS API server` 우회 해제<br>• **Step 07**: 지식 베이스(`Knowledge sources`) 정책 문서 업로드 | `sre.azure.com` | • 관리 대상 Management Group / 구독 연결<br>• `snet-sre-agent-sandbox` 연결 후 **`[ ] AKS API server (*.azmk8s.io)` 체크 해제**<br>• 9대 체크리스트·데이터플레인 SOP·공지 양식 마크다운 3종 업로드(`Indexed`) |
| **Phase 4**<br>MCP 커넥터 · Python 도구 · 스킬 · 고급 권한 · 서브에이전트 | • **Step 08**: `mslearn-mcp` & `azure-arg-mcp`(`npx @azure/mcp`) 커넥터<br>• **Step 09**: `Agent Canvas > Toolbox` Python 도구 2종 등록<br>• **Step 10**: `Skill builder` 공지 메일(`.md`) 워크플로 스킬 등록<br>• **Step 11**: `Tools > Advanced permissions` (`Allow`/`Ask`/`Deny`) & `Custom instructions`<br>• **Step 12**: `Agent Canvas` 서브에이전트(`aks_upgrade_specialist`) 생성 | `sre.azure.com` | • MS Learn 원격 MCP 및 공식 Azure 로컬 Stdio MCP(`azure-arg-mcp`) 연결<br>• `check-aks-eos-release-calendar` (EOS 일정 파싱 + SupportPlan별 대상 클러스터 필터링)<br>• `evaluate-aks-upgrade-preflight` (전체 `ALL` 또는 선택 `1,3,4` 9대 사전 점검)<br>• `Knowledge Memory + Skill` 기반 공지 메일 `.md` 생성 및 다운로드 링크 제공 |
| **Phase 5**<br>Live Report · 정기 스케줄 & 채팅 검증 | • **Step 13**: `Live Reports` 대시보드 & 매월 1일 `Scheduled tasks`<br>• **Step 14**: 실시간 채팅(`/agent aks_upgrade_specialist`) 실행 검증 | `sre.azure.com` | • `azure-arg-mcp` 기반 Live Report 대시보드 및 매월 1일(`0 0 1 * *`) 정기 작업 등록<br>• 채팅으로 EOS 대상 클러스터 필터링 + 9대 사전 점검 + 릴리즈 노트 + 공지 메일(`.md`) 다운로드 검증 |

---

# Phase 0. 리소스 공급자(Resource Providers) 5종 등록 및 리소스 그룹 3개 생성 (`portal.azure.com`)

아무것도 없는 신규 Azure 구독에서는 AKS, Managed Grafana, SRE Agent(`Microsoft.App`), vWAN/DNS Resolver를 생성하기 전에 반드시 해당 **리소스 공급자(Resource Providers)** 가 `Registered` 상태여야 합니다.

---

## Step 00. 구독 리소스 공급자 5종 등록 및 역할별 리소스 그룹 3개(태그 포함) 생성

### 포털 UI 화면 이동 및 탭·필드별 입력값
1. **리소스 공급자 5종 등록 (`구독 > 설정 > 리소스 공급자`)**:
   - Azure Portal 상단 검색창에서 **`구독 (Subscriptions)`** 검색 ➔ 대상 구독 선택 ➔ 좌측 **`설정 (Settings) > 리소스 공급자 (Resource providers)`** 를 클릭합니다.
   - 검색창에 아래 5개 공급자를 차례로 검색하여 `NotRegistered` 상태인 공급자를 선택하고 상단 **`등록 (Register)`** 을 클릭합니다:
     - `Microsoft.Network` (vWAN, Secured Hub, Azure Firewall, DNS Private Resolver, VNet용)
     - `Microsoft.ContainerService` (Private AKS 클러스터용)
     - `Microsoft.App` (Azure SRE Agent 및 컨테이너 샌드박스 위임용)
     - `Microsoft.Dashboard` (`Dashboards with Grafana` 및 Azure Managed Grafana용)
     - `Microsoft.OperationalInsights` (Log Analytics Workspace용)
   - 5개 모두 **`● Registered (등록됨)`** 상태가 되는지 확인합니다.
2. **역할별 리소스 그룹 3개 생성 (`리소스 그룹 > + 만들기`)**:
   - 상단 검색창에서 **`리소스 그룹 (Resource groups)`** 검색 ➔ 상단 **`+ 만들기 (+ Create)`** 클릭 후 **`기본 사항 (Basics)`** 탭과 **`태그 (Tags)`** 탭에 아래 값을 입력하여 3개 리소스 그룹을 차례로 생성합니다 (`검토 + 만들기` ➔ `만들기`):

| 생성 순서 | `[기본 사항]` 리소스 그룹 이름 | `[기본 사항]` 지역 (Region) | `[태그]` 탭 입력값 (`이름 : 값`) | 용도 설명 |
|---|---|---|---|---|
| **1번째 RG** | **`rg-sre-vwan-network`** | `(Asia Pacific) Korea Central` | • `env` : `sre-lab`<br>• `role` : `network-hub` | 중앙 Virtual WAN, Secured Hub(방화벽), DNS Private Resolver, 네트워크 허브/스포크 VNet 배치용 (**9대 사전 점검 항목 ⑧ 타 RG VNet 권한 검증 구조 재현**) |
| **2번째 RG** | **`rg-sre-private-aks-fleet`** | `(Asia Pacific) Korea Central` | • `env` : `sre-lab`<br>• `role` : `private-aks-fleet` | Private AKS 클러스터 3대(`aks-priv-01..03`), Log Analytics Workspace, `SRE-AKS-Management` 대시보드 배치용 |
| **3번째 RG** | **`rg-sre-agent-fleet`** | `(Asia Pacific) Korea Central` | • `env` : `sre-lab`<br>• `role` : `sre-agent` | Azure SRE Agent 리소스 및 에이전트 전용 VNet(`vnet-sre-event-lab`) 배치용 |

> **참고 (리전 선택)**:
> 기본 리전은 `Korea Central`입니다. 구독에 `Korea Central` VM SKU 쿼터 제한이 있는 경우 AKS용 VNet 2개(`vnet-sre-aks-hub`, `vnet-sre-spoke-03`)와 Private AKS 클러스터 3대는 `East US 2`(노드 크기: `Standard_D2s_v7`)로 생성해 `Korea Central` vWAN 허브에 연결할 수 있습니다.

### 복사·붙여넣기용 Step 00 전체 Azure CLI 명령어
```bash
# 1) 사용할 구독 ID 지정
export SUB_ID="<YOUR_SUBSCRIPTION_ID>"   # <-- 신규 구독 ID로 변경
az account set --subscription "$SUB_ID"

# 2) 필수 리소스 공급자(Resource Providers) 5종 일괄 등록 (및 구독 기능 등록)
az feature register --namespace Microsoft.Network --name AllowBringYourOwnPublicIpAddress
for RP in \
  Microsoft.Network \
  Microsoft.ContainerService \
  Microsoft.App \
  Microsoft.Dashboard \
  Microsoft.OperationalInsights; do
  az provider register --namespace "$RP"
done

# 3) 역할별 리소스 그룹 3개 생성 (모두 Korea Central)
az group create -n rg-sre-vwan-network -l koreacentral --tags env=sre-lab role=network-hub
az group create -n rg-sre-private-aks-fleet -l koreacentral --tags env=sre-lab role=private-aks-fleet
az group create -n rg-sre-agent-fleet -l koreacentral --tags env=sre-lab role=sre-agent
```

---

# Phase 1. vWAN Secured Hub · 방화벽 · VNet · DNS Private Resolver · Private AKS · 시나리오 워크로드 구축 (`portal.azure.com`)

---

## Step 01-A. Standard Virtual WAN(`vwan-sre`) · 방화벽 정책(`afwp-sre-vwan`) · Secured Virtual Hub(`vhub-sre` + Azure Firewall) 생성

SRE Agent 서브넷(`10.42.4.0/24`)에서 출발한 트래픽이 중앙 방화벽을 통과해 각 Private AKS 클러스터(`10.52.x.x`, `10.60.x.x`)로 라우팅되도록 **Standard Virtual WAN**, **방화벽 정책(`afwp-sre-vwan`)**, **Secured Virtual Hub(Azure Firewall 내장)** 를 `Korea Central`에 생성합니다.

### 포털 UI 화면 이동 및 탭·필드별 입력값 (MS 공식 권장: `Firewall Manager`에서 한 번에 생성)

1. **진입 경로**: Azure Portal 상단 검색창에서 **`Firewall Manager` (또는 `네트워크 보안`)** 검색 ➔ 좌측 **`리소스 보호 > 가상 허브 (Virtual hubs)`** ➔ 상단 **`+ 새 보안 가상 허브 만들기 (Create new secured virtual hub)`** 클릭
   - *(주의: `Virtual WANs > 허브 > + 새 허브`는 방화벽 탭이 없는 일반 허브 전용 생성 화면이므로 반드시 `Firewall Manager > 가상 허브 > + 새 보안 가상 허브 만들기`에서 시작합니다.)*
2. **탭별 상세 입력표 (`기본 사항` ➔ `Azure 방화벽` ➔ `보안 파트너 공급자` ➔ `검토 + 만들기`)**:

| 탭 이름 | 필드명 (포털 표시명) | 입력 / 선택할 값 | 비고 (CLI 대응 옵션) |
|---|---|---|---|
| **1. 기본 사항 (`Basics`)** | 구독 (`Subscription`) | 실습 대상 구독 선택 | `--subscription` |
| | 리소스 그룹 (`Resource group`) | **`rg-sre-vwan-network`** | `-g rg-sre-vwan-network` |
| | 지역 (`Region`) | **`Korea Central`** | `-l koreacentral` |
| | 보안 가상 허브 이름 (`Secured virtual hub name`) | **`vhub-sre`** | `az network vhub create -n vhub-sre` |
| | 허브 주소 공간 (`Hub address space`) | **`10.1.0.0/23`** | `--address-prefix 10.1.0.0/23` |
| | 허브 IPv6 주소 공간 | *(비워둠)* | - |
| | 기존 vWAN을 선택하거나 새로 만드세요 | **`새 vWAN (New vWAN)`** 선택<br>*(이미 `vwan-sre`가 있다면 `기존 vWAN` ➔ `vwan-sre` 선택)* | `az network vwan create` |
| | 새 가상 WAN 이름 (`New virtual WAN name`) | **`vwan-sre`** | `-n vwan-sre` |
| | 유형 (`Type`) | **`표준 (Standard)`** | `--type Standard` (`Basic`은 VNet 트랜짓/방화벽 미지원) |
| | 보안 파트너 공급자용 VPN 게이트웨이 포함 | **`[ ] 체크 해제`** (기본값 유지) | - |
| **2. Azure 방화벽 (`Azure Firewall`)** | Azure Firewall | **`사용 (Enabled)`** | `az network firewall create --sku AZFW_Hub` |
| | Azure Firewall 계층 (`Tier`) | **`표준 (Standard)`** | `--tier Standard` |
| | 가용성 영역 (`Availability Zones`) | **`1, 2, 3`** (또는 기본값) | - |
| | 공용 IP 주소 개수 (`Public IP addresses`) | **`1`** | `--public-ip-count 1` |
| | 방화벽 정책 (`Firewall Policy`) | **`새로 만들기`** (또는 **`기본 거부 정책`** 선택 후 아래 3번에서 `afwp-sre-vwan` 생성·연결) | `--firewall-policy afwp-sre-vwan` |
| **3. 보안 파트너 공급자** | 신뢰할 수 있는 보안 파트너 | **`사용 안 함 (Disabled)`** | 기본값 유지 후 **`검토 + 만들기` ➔ `만들기`** 클릭 |

3. **방화벽 정책(`afwp-sre-vwan`) 생성 시 탭별 입력표 (`방화벽 정책 > + 만들기`)**:
   - 위 마법사에서 `기본 거부 정책`으로 먼저 허브를 생성했거나, 이미 일반 허브(`vhub-sre`)를 만들어 두어 In-Place로 방화벽을 배포하는 경우 상단 검색창에서 **`방화벽 정책 (Firewall Policies)`** ➔ **`+ 만들기`** 를 눌러 아래 표대로 **`afwp-sre-vwan`** 을 생성합니다:

| 방화벽 정책 생성 탭 | 필드명 (포털 표시명) | 입력 / 선택할 값 | 비고 |
|---|---|---|---|
| **1. 기본 사항 (`Basics`)** | 리소스 그룹 | **`rg-sre-vwan-network`** | `-g rg-sre-vwan-network` |
| | 이름 (`Name`) | **`afwp-sre-vwan`** | `-n afwp-sre-vwan` |
| | 지역 (`Region`) | **`Korea Central`** | `-l koreacentral` |
| | 정책 계층 (`Policy tier`) | **`표준 (Standard)`** | `--sku Standard` (방화벽 계층과 반드시 일치) |
| | 부모 정책 (`Parent policy`) | *(비워둠 / 없음)* | - |
| **2. DNS 설정 (`DNS Settings`)** | DNS 설정 | **`사용 안 함 (Disabled)`** (기본값 유지) | Step 01-D에서 별도 `Azure DNS Private Resolver` 사용 |
| **3. TLS 검사 (`TLS Inspection`)** | TLS 검사 | **`사용 안 함 (Disabled)`** (기본값 유지) | 사설 AKS API 서버 자체 CA 인증서 보존 필수 |
| **4. 규칙 (`Rules`)** | 규칙 추가 | *(생성 후 Step 01-B에서 `rcg-sre-to-aks`와 함께 추가)* | 바로 건너뛰기 가능 |
| **5. IDPS / 위협 인텔리전스** | 모드 | **`경고만 (Alert only)`** (기본값 유지) | 바로 **`검토 + 만들기` ➔ `만들기`** 클릭 |

### 복사·붙여넣기용 Step 01-A Azure CLI 명령어
```bash
# 1) Standard Virtual WAN 생성 (Korea Central)
az network vwan create \
  -g rg-sre-vwan-network -n vwan-sre -l koreacentral --type Standard

# 2) Virtual Hub (10.1.0.0/23) 생성 (Korea Central)
az network vhub create \
  -g rg-sre-vwan-network -n vhub-sre \
  --vwan vwan-sre --address-prefix 10.1.0.0/23 -l koreacentral

# 3) Firewall Policy 및 Secured Hub 내장 Azure Firewall 생성 (Korea Central)
az network firewall policy create \
  -g rg-sre-vwan-network -n afwp-sre-vwan -l koreacentral --sku Standard

az network firewall create \
  -g rg-sre-vwan-network -n fw-vhub-sre -l koreacentral \
  --sku AZFW_Hub --tier Standard \
  --vhub vhub-sre --firewall-policy afwp-sre-vwan \
  --public-ip-count 1
```

---

## Step 01-B. 방화벽 정책 규칙 컬렉션 그룹(`rcg-sre-to-aks`) · 네트워크/애플리케이션 규칙 · 허브 연결 및 `Routing Intent` 활성화

CLI 스크립트의 4단계(① `rcg-sre-to-aks` 그룹 생성 ➔ ② `allow-sre-aks-net` 네트워크 규칙 컬렉션 추가 ➔ ③ `allow-sre-app-rules` 애플리케이션 규칙 컬렉션 추가 ➔ ④ `vhub-sre` 라우팅 의도 설정)를 포털 UI에서 빠짐없이 동일하게 입력합니다.

### 포털 UI 화면 이동 및 필드별 입력값 (`1단계` ➔ `4단계`)

#### 1단계: 규칙 컬렉션 그룹(`rcg-sre-to-aks`, 우선 순위 `200`) 생성
1. 상단 검색창에서 **`방화벽 정책 (Firewall Policies)`** 검색 ➔ **`afwp-sre-vwan`** 클릭
2. 좌측 메뉴 **`설정 (Settings) > 규칙 컬렉션 그룹 (Rule collection groups)`** 클릭 ➔ 상단 **`+ 추가 (+ Add)`** 클릭
3. 우측 창에 아래 값을 입력하고 **`추가 (Add)`** 클릭:
   - **이름 (`Name`)**: **`rcg-sre-to-aks`**
   - **우선 순위 (`Priority`)**: **`200`**

#### 2단계: 네트워크 규칙 컬렉션(`allow-sre-aks-net`, 우선 순위 `210`) 및 하위 규칙 추가
1. `afwp-sre-vwan` 좌측 메뉴 **`설정 (Settings) > 네트워크 규칙 (Network rules)`** 클릭 ➔ 상단 **`+ 규칙 컬렉션 추가 (+ Add a rule collection)`** 클릭
2. **상위 컬렉션 정보(창 상단)** 와 **하위 규칙 행(창 하단 `규칙 / Rules` 표)** 에 아래 값을 정확히 입력하고 하단 **`추가 (Add)`** 를 클릭합니다:

| 구분 | 필드명 (포털 표시명) | 입력 / 선택할 값 | 대응하는 CLI 파라미터 |
|---|---|---|---|
| **상위 규칙 컬렉션 설정**<br>(창 상단 영역) | 이름 (`Name`) | **`allow-sre-aks-net`** | `-n allow-sre-aks-net` |
| | 규칙 컬렉션 유형 (`Rule collection type`) | **`네트워크 (Network)`** | `--rule-type NetworkRule` |
| | 우선 순위 (`Priority`) | **`210`** | `--collection-priority 210` |
| | 규칙 컬렉션 작업 (`Rule collection action`) | **`허용 (Allow)`** | `--action Allow` |
| | 규칙 컬렉션 그룹 (`Rule collection group`) | **`rcg-sre-to-aks`** | `--rcg-name rcg-sre-to-aks` |
| **하위 규칙 행 입력**<br>(창 하단 `규칙` 표) | 이름 (`Name`) | **`Allow-SRE-to-PrivateAKS`** | `--rule-name Allow-SRE-to-PrivateAKS` |
| | 원본 유형 (`Source type`) | **`IP 주소 (IP Address)`** | - |
| | 원본 (`Source`) | **`10.42.4.0/24`** | `--source-addresses 10.42.4.0/24` |
| | 프로토콜 (`Protocol`) | **`TCP, UDP`** (두 개 모두 체크) | `--ip-protocols TCP UDP` |
| | 대상 포트 (`Destination Ports`) | **`443, 53`** | `--destination-ports 443 53` |
| | 대상 유형 (`Destination Type`) | **`IP 주소 (IP Address)`** | - |
| | 대상 (`Destination`) | **`10.52.0.0/16, 10.60.0.0/16, 10.10.0.4`**<br>*(만약 `vnet-sre-dns`를 `10.0.0.0/24`로 생성했다면 `10.0.0.4`도 추가)* | `--destination-addresses 10.52.0.0/16 10.60.0.0/16 10.10.0.4` |

#### 3단계: 애플리케이션 규칙 컬렉션(`allow-sre-app-rules`, 우선 순위 `220`) 및 하위 규칙 추가
1. `afwp-sre-vwan` 좌측 메뉴 **`설정 (Settings) > 애플리케이션 규칙 (Application rules)`** 클릭 ➔ 상단 **`+ 규칙 컬렉션 추가 (+ Add a rule collection)`** 클릭
2. 아래 표의 값을 입력하고 하단 **`추가 (Add)`** 를 클릭합니다:

| 구분 | 필드명 (포털 표시명) | 입력 / 선택할 값 | 대응하는 CLI 파라미터 |
|---|---|---|---|
| **상위 규칙 컬렉션 설정**<br>(창 상단 영역) | 이름 (`Name`) | **`allow-sre-app-rules`** | `-n allow-sre-app-rules` |
| | 규칙 컬렉션 유형 (`Rule collection type`) | **`애플리케이션 (Application)`** | `--rule-type ApplicationRule` |
| | 우선 순위 (`Priority`) | **`220`** | `--collection-priority 220` |
| | 규칙 컬렉션 작업 (`Rule collection action`) | **`허용 (Allow)`** | `--action Allow` |
| | 규칙 컬렉션 그룹 (`Rule collection group`) | **`rcg-sre-to-aks`** | `--rcg-name rcg-sre-to-aks` |
| **하위 규칙 행 입력**<br>(창 하단 `규칙` 표) | 이름 (`Name`) | **`Allow-SRE-MSLearn-MCP`** | `--rule-name Allow-SRE-MSLearn-MCP` |
| | 원본 유형 (`Source type`) | **`IP 주소 (IP Address)`** | - |
| | 원본 (`Source`) | **`10.42.4.0/24`** | `--source-addresses 10.42.4.0/24` |
| | 프로토콜 (`Protocol`) | **`https:443`** (또는 `http, https`) | `--protocols Https=443` |
| | 대상 유형 (`Destination Type`) | **`FQDN`** | - |
| | 대상 (`Destination`) | **`learn.microsoft.com, *.atlassian.com, *.atlassian.net, registry.npmjs.org, *.npmjs.org, api.github.com, management.azure.com, login.microsoftonline.com`** | `--target-fqdns learn.microsoft.com "*.atlassian.com" "*.atlassian.net" registry.npmjs.org "*.npmjs.org" api.github.com management.azure.com login.microsoftonline.com` |

#### 4단계: `afwp-sre-vwan` 허브 연결 확인 및 `vhub-sre` `라우팅 의도(Routing Intent)` 활성화
1. **방화벽 정책 허브 연결 확인**:
   - `afwp-sre-vwan` 좌측 메뉴 **`관리 (Manage) > 연결된 허브 (Associated hubs)`** 클릭
   - 목록에 `vhub-sre`가 없다면 상단 **`+ 허브 연결 (+ Associate hubs)`** 클릭 ➔ **`vhub-sre`** 체크 ➔ **`추가 (Add)`** 클릭
2. **`vhub-sre` 라우팅 의도(`Routing Intent`) 활성화**:
   - `Virtual WANs > vwan-sre > 허브 > vhub-sre` 이동 ➔ 좌측 **`라우팅 (Routing) > 라우팅 의도 및 라우팅 정책 (Routing Intent and Routing Policies)`** 클릭
   - 아래 값을 선택하고 상단/하단 **`저장 (Save)`** 을 클릭합니다:

| 필드명 (포털 표시명) | 선택할 값 | 설명 |
|---|---|---|
| **인터넷 트래픽 (`Internet traffic`)** | `없음 (None)` (또는 `Azure Firewall`) | 인터넷 아웃바운드까지 방화벽으로 통제하려면 `Azure Firewall` 선택 가능 |
| **프라이빗 트래픽 (`Private traffic - RFC 1918`)** | **`Azure Firewall`** | `10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16` 대역 간 모든 사설 통신을 방화벽으로 라우팅 |
| **다음 홉 리소스 (`Next Hop Resource`)** | **`AzureFirewall_vhub-sre`** (또는 `fw-vhub-sre`) | `vhub-sre` 내부에 배포된 방화벽 인스턴스 선택 |

### 복사·붙여넣기용 Step 01-B Azure CLI 명령어 (방화벽 규칙 + Routing Intent)
```bash
# 1) Firewall Policy Rule Collection Group 생성
az network firewall policy rule-collection-group create \
  -g rg-sre-vwan-network --policy-name afwp-sre-vwan \
  -n rcg-sre-to-aks --priority 200

# 2) Network Rule 컬렉션 추가 (SRE 서브넷 -> Private AKS TCP 443 & 중앙 DNS 53 허용)
az network firewall policy rule-collection-group collection add-filter-collection \
  -g rg-sre-vwan-network --policy-name afwp-sre-vwan --rcg-name rcg-sre-to-aks \
  -n allow-sre-aks-net --collection-priority 210 --action Allow \
  --rule-name Allow-SRE-to-PrivateAKS --rule-type NetworkRule \
  --ip-protocols TCP UDP \
  --source-addresses 10.42.4.0/24 \
  --destination-addresses 10.52.0.0/16 10.60.0.0/16 10.10.0.4 \
  --destination-ports 443 53

# 3) Application Rule 컬렉션 추가 (MS Learn MCP & Confluence 허용)
az network firewall policy rule-collection-group collection add-filter-collection \
  -g rg-sre-vwan-network --policy-name afwp-sre-vwan --rcg-name rcg-sre-to-aks \
  -n allow-sre-app-rules --collection-priority 220 --action Allow \
  --rule-name Allow-SRE-MSLearn-MCP --rule-type ApplicationRule \
  --protocols Https=443 \
  --source-addresses 10.42.4.0/24 \
  --target-fqdns learn.microsoft.com "*.atlassian.com" "*.atlassian.net"

# 4) vWAN Hub에 Routing Intent (Private Traffic -> fw-vhub-sre) 활성화
FW_ID=$(az network firewall show -g rg-sre-vwan-network -n fw-vhub-sre --query id -o tsv)
az rest --method PUT \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/rg-sre-vwan-network/providers/Microsoft.Network/virtualHubs/vhub-sre/routingIntent/ri-sre?api-version=2023-09-01" \
  --body "{\"properties\":{\"routingPolicies\":[{\"name\":\"PrivateTrafficPolicy\",\"destinations\":[\"PrivateTraffic\"],\"nextHop\":\"$FW_ID\"}]}}"
```

---

## Step 01-C. 4대 가상 네트워크(VNet) 생성 및 서브넷(`snet-dns-inbound`, `snet-sre-agent-sandbox`) 서비스 위임 설정

전체 테스트베드 구성을 위해 **4개의 VNet**(① 중앙 DNS VNet, ② SRE Agent VNet, ③ AKS Hub VNet, ④ AKS Spoke VNet)을 생성하고, 각 서브넷의 주소 대역과 서비스 위임(`Subnet delegation`)을 설정합니다.

- **특이사항 설계 포인트**:
  - `vnet-sre-aks-hub`와 `vnet-sre-spoke-03`는 AKS 리소스 그룹(`rg-sre-private-aks-fleet`)이 아닌 **네트워크 전용 리소스 그룹(`rg-sre-vwan-network`)** 에 생성하여 현업과 동일한 **Cross-RG VNet 구조(9대 사전 점검 체크리스트 항목 ⑧ 검증용)** 를 만듭니다.
  - `aks-priv-02`가 사용할 **`snet-aks-02`는 의도적으로 `/27`(32 IP, 가용 27 IP)** 로 작게 생성하여 **9대 체크리스트 항목 ⑦(서브넷 가용 IP 부족 / 사용률 81.5%)** 이 실제로 검출되도록 구성합니다.

### 포털 UI 화면 이동 및 4개 VNet 탭·필드별 입력값 (`가상 네트워크 > + 만들기`)

1. 상단 검색창에서 **`가상 네트워크 (Virtual networks)`** 검색 ➔ **`+ 만들기 (+ Create)`** 를 클릭합니다.
2. 각 VNet 생성 시 **`기본 사항 (Basics)`** 탭에 리소스 그룹·이름·지역을 입력한 뒤, **`IP 주소 (IP Addresses)`** 탭으로 이동하여:
   - 포털이 자동으로 넣어둔 기본 `10.0.0.0/16` 주소 공간과 `default` 서브넷을 우측 휴지통 아이콘(`🗑`)으로 지우거나 수정하여 **아래 표의 정확한 IPv4 주소 공간과 서브넷**을 추가합니다.
   - 특히 **`snet-dns-inbound`** 와 **`snet-sre-agent-sandbox`** 서브넷을 추가(또는 생성 후 `설정 > 서브넷`에서 클릭해 편집)할 때는 하단 **`서브넷 위임 (Subnet delegation) > 서비스에 서브넷 위임`** 드롭다운에서 표에 적힌 위임 서비스를 반드시 선택하고 **`저장 (Save)`** 합니다:

| 생성 순서 | `[기본 사항]` 리소스 그룹 | `[기본 사항]` 가상 네트워크 이름 | `[기본 사항]` 지역 (Region) | `[IP 주소]` IPv4 주소 공간 | `[IP 주소 > 서브넷]` 생성할 서브넷 이름 | 서브넷 주소 범위 (`시작 주소` + `크기`) | 서브넷 위임 (`서비스에 서브넷 위임`) |
|---|---|---|---|---|---|---|---|
| **VNet 1**<br>(중앙 DNS용) | **`rg-sre-vwan-network`** | **`vnet-sre-dns`** | **`Korea Central`** | **`10.10.0.0/24`**<br>*(또는 `10.0.0.0/24`)* | **`snet-dns-inbound`** | **`10.10.0.0/28`**<br>*(또는 `10.0.0.0/28`)* | **`Microsoft.Network/dnsResolvers`** |
| **VNet 2**<br>(SRE Agent용) | **`rg-sre-agent-fleet`** | **`vnet-sre-event-lab`** | **`Korea Central`** | **`10.42.0.0/16`** | ① **`snet-default`**<br>② **`snet-sre-agent-sandbox`** | ① **`10.42.0.0/24`**<br>② **`10.42.4.0/24`** | ① `없음 (None)`<br>② **`Microsoft.App/environments`** *(필수!)* |
| **VNet 3**<br>(AKS 01·02용) | **`rg-sre-vwan-network`** | **`vnet-sre-aks-hub`** | **`East US 2`** *(상용 구독은 `Korea Central` 가능)* | **`10.52.0.0/16`** | ① **`snet-aks-01`**<br>② **`snet-aks-02`** | ① **`10.52.11.0/24`**<br>② **`10.52.12.0/27`** *(IP 부족 재현용 `/27`)* | ① `없음 (None)`<br>② `없음 (None)` |
| **VNet 4**<br>(AKS 03용) | **`rg-sre-vwan-network`** | **`vnet-sre-spoke-03`** | **`East US 2`** *(상용 구독은 `Korea Central` 가능)* | **`10.60.0.0/16`** | **`snet-aks-03`** | **`10.60.3.0/24`** | `없음 (None)` |

> **포털 UI 참고 (`서브넷 위임` 위치)**:
> 초기 `가상 네트워크 만들기` 마법사의 `IP 주소` 탭에서 `서브넷 위임` 드롭다운이 보이지 않는 경우, VNet 생성을 먼저 완료한 뒤 **`생성된 VNet 클릭 > 좌측 설정(Settings) > 서브넷(Subnets) > 해당 서브넷 클릭`** 에서 하단의 **`서브넷 위임 (Subnet delegation)`** 을 선택합니다. 포털에서 기본 체크되는 `프라이빗 서브넷 (defaultOutboundAccess: false)` 및 기본 NSG는 그대로 유지합니다.

### 복사·붙여넣기용 Step 01-C 4개 VNet 및 전용 서브넷 일괄 생성 CLI
```bash
# 1) 중앙 DNS VNet (10.10.0.0/24, Korea Central) 및 DNS Resolver Inbound 전용 서브넷(/28) 생성
az network vnet create \
  -g rg-sre-vwan-network -n vnet-sre-dns -l koreacentral \
  --address-prefixes 10.10.0.0/24 \
  --subnet-name snet-dns-inbound --subnet-prefixes 10.10.0.0/28

az network vnet subnet update \
  -g rg-sre-vwan-network --vnet-name vnet-sre-dns -n snet-dns-inbound \
  --delegations Microsoft.Network/dnsResolvers

# 2) SRE Agent VNet (10.42.0.0/16, Korea Central) 및 전용 샌드박스 서브넷(10.42.4.0/24, Microsoft.App/environments 위임) 생성
az network vnet create \
  -g rg-sre-agent-fleet -n vnet-sre-event-lab -l koreacentral \
  --address-prefixes 10.42.0.0/16 \
  --subnet-name snet-default --subnet-prefixes 10.42.0.0/24

az network vnet subnet create \
  -g rg-sre-agent-fleet --vnet-name vnet-sre-event-lab \
  -n snet-sre-agent-sandbox --address-prefixes 10.42.4.0/24 \
  --delegations Microsoft.App/environments

# 3) AKS Hub VNet (10.52.0.0/16, East US 2) — snet-aks-01(/24 정상) & snet-aks-02(/27 IP 부족 재현용)
az network vnet create \
  -g rg-sre-vwan-network -n vnet-sre-aks-hub -l eastus2 \
  --address-prefixes 10.52.0.0/16 \
  --subnet-name snet-aks-01 --subnet-prefixes 10.52.11.0/24

az network vnet subnet create \
  -g rg-sre-vwan-network --vnet-name vnet-sre-aks-hub \
  -n snet-aks-02 --address-prefixes 10.52.12.0/27

# 4) AKS Spoke 03 VNet (10.60.0.0/16, East US 2) — snet-aks-03(/24)
az network vnet create \
  -g rg-sre-vwan-network -n vnet-sre-spoke-03 -l eastus2 \
  --address-prefixes 10.60.0.0/16 \
  --subnet-name snet-aks-03 --subnet-prefixes 10.60.3.0/24
```

---

## Step 01-D. Azure DNS Private Resolver(`dnspr-sre` / `10.10.0.4`) 생성 및 vWAN Hub(`vhub-sre`)에 4개 VNet 연결

다중 허브/vWAN 환경에서 중앙 DNS 서버를 통해 모든 사설 AKS 도메인(`*.privatelink.eastus2.azmk8s.io`)을 해석할 수 있도록 **Azure DNS Private Resolver**를 생성하고, **`vhub-sre` 허브에 4개 VNet을 모두 연결(`가상 네트워크 연결`)** 합니다.

### 포털 UI 화면 이동 및 필드별 입력값 (`1단계` ➔ `2단계`)

#### 1단계: Azure DNS Private Resolver(`dnspr-sre`) 및 인바운드 엔드포인트(`in-ep-sre`) 생성
1. 상단 검색창에서 **`DNS 프라이빗 확인자 (DNS Private Resolvers)`** 검색 ➔ 상단 **`+ 만들기 (+ Create)`** 클릭
2. 각 탭에 아래 표의 값을 입력하고 **`검토 + 만들기` ➔ `만들기`** 를 클릭합니다:

| 탭 이름 | 필드명 (포털 표시명) | 입력 / 선택할 값 | 비고 (CLI 대응 옵션) |
|---|---|---|---|
| **1. 기본 사항 (`Basics`)** | 구독 (`Subscription`) | 실습 대상 구독 | - |
| | 리소스 그룹 (`Resource group`) | **`rg-sre-vwan-network`** | `-g rg-sre-vwan-network` |
| | 이름 (`Name`) | **`dnspr-sre`** | `-n dnspr-sre` |
| | 지역 (`Region`) | **`Korea Central`** | `-l koreacentral` (`vnet-sre-dns`와 동일 리전) |
| | 가상 네트워크 (`Virtual network`) | **`vnet-sre-dns`** | `--id "$DNS_VNET_ID"` |
| **2. 인바운드 엔드포인트 (`Inbound Endpoints`)** | `+ 엔드포인트 추가 (+ Add an endpoint)` 클릭 | • 엔드포인트 이름: **`in-ep-sre`**<br>• 서브넷: **`snet-dns-inbound`**<br>• 개인 IP 주소 할당: **`정적 (Static)`** (또는 `동적`)<br>• IP 주소: **`10.10.0.4`** *(만약 `vnet-sre-dns` 대역이 `10.0.0.0/24`라면 **`10.0.0.4`** 입력)* | `az dns-resolver inbound-endpoint create -n in-ep-sre` |
| **3. 아웃바운드 엔드포인트 / 규칙 세트** | 엔드포인트 / 규칙 세트 | *(비워둠 — 추가하지 않고 건너뛰기)* | 바로 **`검토 + 만들기` ➔ `만들기`** 클릭 |

#### 2단계: `vwan-sre`에서 `vhub-sre` 허브에 4개 VNet 연결 (`가상 네트워크 연결`)
1. 상단 검색창에서 **`가상 WAN (Virtual WANs)`** 검색 ➔ **`vwan-sre`** 클릭
2. 좌측 메뉴 **`연결 (Connectivity) > 가상 네트워크 연결 (Virtual network connections)`** 클릭 ➔ 상단 **`+ 연결 추가 (+ Add connection)`** 클릭
3. 아래 표의 4건을 차례로 입력하고 각각 하단 **`만들기 (Create)`** 를 클릭합니다 (나머지 라우팅 항목인 `없음에 연결: 기본값`, `경로에 전파: 기본값`, `고정 경로: 없음`은 모두 기본값 유지):

| 연결 순서 | 연결 이름 (`Connection name`) | 허브 (`Hubs`) | 구독 (`Subscription`) | 리소스 그룹 (`Resource group`) | 가상 네트워크 (`Virtual network`) |
|---|---|---|---|---|---|
| **연결 1** | **`conn-vnet-sre`** | **`vhub-sre`** | 실습 구독 | **`rg-sre-agent-fleet`** | **`vnet-sre-event-lab`** (`10.42.0.0/16`) |
| **연결 2** | **`conn-vnet-aks-hub`** | **`vhub-sre`** | 실습 구독 | **`rg-sre-vwan-network`** | **`vnet-sre-aks-hub`** (`10.52.0.0/16`) |
| **연결 3** | **`conn-vnet-spoke-03`** | **`vhub-sre`** | 실습 구독 | **`rg-sre-vwan-network`** | **`vnet-sre-spoke-03`** (`10.60.0.0/16`) |
| **연결 4** | **`conn-vnet-dns`** | **`vhub-sre`** | 실습 구독 | **`rg-sre-vwan-network`** | **`vnet-sre-dns`** (`10.10.0.0/24` 또는 `10.0.0.0/24`) |

### 복사·붙여넣기용 Step 01-D Azure CLI 명령어
```bash
# 1) DNS Private Resolver (Korea Central) 및 Inbound Endpoint (10.10.0.4) 생성
DNS_VNET_ID=$(az network vnet show -g rg-sre-vwan-network -n vnet-sre-dns --query id -o tsv)
DNS_SNET_ID=$(az network vnet subnet show -g rg-sre-vwan-network --vnet-name vnet-sre-dns -n snet-dns-inbound --query id -o tsv)

az dns-resolver create \
  -g rg-sre-vwan-network -n dnspr-sre -l koreacentral --id "$DNS_VNET_ID"

az dns-resolver inbound-endpoint create \
  -g rg-sre-vwan-network --dns-resolver-name dnspr-sre \
  -n in-ep-sre -l koreacentral \
  --ip-configurations "[{\"private-ip-address\":\"10.10.0.4\",\"private-ip-allocation-method\":\"Static\",\"id\":\"$DNS_SNET_ID\"}]"

# 2) vWAN Secured Hub (vhub-sre)에 4개 VNet 연결
for PAIR in \
  "conn-vnet-sre:rg-sre-agent-fleet:vnet-sre-event-lab" \
  "conn-vnet-aks-hub:rg-sre-vwan-network:vnet-sre-aks-hub" \
  "conn-vnet-spoke-03:rg-sre-vwan-network:vnet-sre-spoke-03" \
  "conn-vnet-dns:rg-sre-vwan-network:vnet-sre-dns"; do
  CONN_NAME=$(echo "$PAIR" | cut -d: -f1)
  VNET_RG=$(echo "$PAIR" | cut -d: -f2)
  VNET_NAME=$(echo "$PAIR" | cut -d: -f3)
  REMOTE_ID=$(az network vnet show -g "$VNET_RG" -n "$VNET_NAME" --query id -o tsv)
  az network vhub connection create \
    -g rg-sre-vwan-network --vhub-name vhub-sre \
    -n "$CONN_NAME" --remote-vnet "$REMOTE_ID" --no-wait
done
```

---

## Step 02-A. Log Analytics Workspace 2개 · 관리 ID(UAMI) 3개 및 권한 · Private AKS 3대(`1.36.4`, `1.35.9`, `1.34.12`) 생성 · 사설 DNS 링크 연결

CLI 스크립트의 8단계를 포털 UI에서도 하나도 빠짐없이 수행할 수 있도록 **① Log Analytics Workspace 2개 생성 ➔ ② 사용자 할당 관리 ID(UAMI) 3개 생성 및 타 RG VNet 권한 부여 ➔ ③ Private AKS 3대 생성(전체 7개 탭 상세표) ➔ ④ 9대 체크리스트 항목 ⑧/⑨ 장애 조건 재현 ➔ ⑤ Private DNS Zone 가상 네트워크 링크 연결** 순서로 안내합니다.

### 포털 UI 화면 이동 및 단계별 상세 입력값 (`1단계` ➔ `5단계`)

#### 1단계: Log Analytics Workspace 2개 생성 (`Log Analytics 작업 영역 > + 만들기`)
상단 검색창에서 **`Log Analytics 작업 영역 (Log Analytics workspaces)`** 검색 ➔ **`+ 만들기 (+ Create)`** 클릭 후 아래 2개 작업 영역을 생성합니다:

| 순서 | 리소스 그룹 (`Resource group`) | 이름 (`Name`) | 지역 (`Region`) | 용도 |
|---|---|---|---|---|
| **1번째 LAW** | **`rg-sre-private-aks-fleet`** | **`law-sre-aks-monitoring`** | **`Korea Central`** | `aks-priv-01`, `aks-priv-02` 연결용 정상 워크스페이스 |
| **2번째 LAW** | **`rg-sre-vwan-network`** | **`law-sre-deleted-ghost`** | **`Korea Central`** | `aks-priv-03` 연결 후 삭제하여 **9대 체크리스트 항목 ⑨(삭제된 LAW ID 참조)** 재현용 |

#### 2단계: 사용자 할당 관리 ID(UAMI) 3개 생성 및 `rg-sre-vwan-network`에 `네트워크 참가자 (Network Contributor)` 권한 부여
1. **UAMI 3개 생성**:
   - 상단 검색창에서 **`관리 ID (Managed Identities)`** 검색 ➔ **`+ 만들기 (+ Create)`** 클릭
   - 리소스 그룹: **`rg-sre-private-aks-fleet`**, 지역: **`Korea Central`** 로 고정하고 이름만 바꾸어 3개를 생성합니다 (`id-aks-priv-01`, `id-aks-priv-02`, `id-aks-priv-03`).
2. **타 RG(`rg-sre-vwan-network`)에 `네트워크 참가자(Network Contributor)` 권한 부여**:
   - **`리소스 그룹 > rg-sre-vwan-network > 좌측 액세스 제어(IAM) > + 추가 > 역할 할당 추가`** 클릭:
     - **`역할 (Role)` 탭**: **`네트워크 참가자` (`Network Contributor`)** 선택 ➔ `다음`
     - **`구성원 (Members)` 탭**: **`관리 ID`** 선택 ➔ **`+ 구성원 선택`** ➔ **`id-aks-priv-01`, `id-aks-priv-02`, `id-aks-priv-03` 3개 모두 선택** ➔ **`검토 + 할당`** 클릭!

#### 3단계: Private AKS 클러스터 3대(`aks-priv-01`, `02`, `03`) 생성 — 실제 포털 8개 탭(`기본 사항 | 노드 풀 | 네트워킹 | 통합 | 모니터링 | 보안 | 고급 | 태그`) 전 항목 입력표
상단 검색창에서 **`Kubernetes 서비스 (Kubernetes services)`** 검색 ➔ **`+ 만들기 > Kubernetes 클러스터 만들기`** 클릭 후, 실제 포털 상단의 **8개 탭 순서 그대로** 아래 값을 입력합니다:

| 실제 포털 탭 | 실제 포털 필드명 (위에서 아래 순서) | `aks-priv-01` (정상 기준) | `aks-priv-02` (`/27` IP 부족·권한 누락) | `aks-priv-03` (LTS·삭제된 LAW 참조) |
|---|---|---|---|---|
| **`[1. 기본 사항]`** | 구독 (`Subscription`) | 현재 실습 구독 | 현재 실습 구독 | 현재 실습 구독 |
| | 리소스 그룹 (`Resource group`) | **`rg-sre-private-aks-fleet`** | **`rg-sre-private-aks-fleet`** | **`rg-sre-private-aks-fleet`** |
| | 클러스터 사전 설정 구성 | 기본값 (`표준 ($)`) 유지 | 기본값 (`표준 ($)`) 유지 | 기본값 (`표준 ($)`) 유지 |
| | Kubernetes 클러스터 이름 `*` | **`aks-priv-01`** | **`aks-priv-02`** | **`aks-priv-03`** |
| | 지역 (`Region`) `*` | **`(US) East US 2`** (`미국 동부 2`) | **`(US) East US 2`** | **`(US) East US 2`** |
| | 플리트 관리자 (`Fleet manager`) | **`없음`** (기본값 유지) | **`없음`** (기본값 유지) | **`없음`** (기본값 유지) |
| | 가용성 영역 (`Availability zones`) | **`없음`** (드롭다운에서 체크된 영역 모두 해제) | **`없음`** (체크된 영역 모두 해제) | **`없음`** (체크된 영역 모두 해제) |
| | AKS 가격 책정 계층 | **`표준`** | **`표준`** | **`프리미엄`** (아래 장기 지원 체크 시 자동 변경) |
| | 장기 지원 사용 (`Check box`) | **`[ ] 체크 해제`** | **`[ ] 체크 해제`** | **`[✓] 체크`** |
| | Kubernetes 버전 `*` | **`1.36.4`** | **`1.35.9`** | **`1.34.12`** |
| | 자동 업그레이드 / 스케줄러 | 기본값 (`패치와 함께 활성화됨(권장)` / `매주 일요일마다(권장)`) 유지 | 기본값 유지 | 기본값 유지 |
| | 노드 보안 채널 유형 / 스케줄러 | 기본값 (`노드 이미지` / `매주 일요일마다(권장)`) 유지 | 기본값 유지 | 기본값 유지 |
| | 인증 및 권한 부여 | **`Azure RBAC가 있는 Microsoft Entra ID 인증`** (하단 드롭다운 변경) | **`Azure RBAC가 있는 Microsoft Entra ID 인증`** | **`Azure RBAC가 있는 Microsoft Entra ID 인증`** |
| **`[2. 노드 풀]`** | **`agentpool` 및 `userpool` 둘 다 클릭하여 편집**<br>*(또는 `userpool` 삭제 가능)* | • **가용성 영역**: **`없음`**<br>• **노드 크기**: **`Standard_D2s_v7`** (`userpool` 기본값 `D8ds_v6`도 `D2s_v7`로 변경)<br>• **크기 조정 방법**: **`수동`** / **노드 수**: **`1`**<br>• **노드당 최대 Pod 수**: **`30`** (`110` ➔ `30`) ➔ `업데이트` | • `agentpool` 및 `userpool` 모두:<br>• **가용성 영역**: **`없음`**<br>• **노드 크기**: **`Standard_D2s_v7`**<br>• **크기 조정 방법**: **`수동`** / **노드 수**: **`1`**<br>• **노드당 최대 Pod 수**: **`30`** ➔ `업데이트` | • `agentpool` 및 `userpool` 모두:<br>• **가용성 영역**: **`없음`**<br>• **노드 크기**: **`Standard_D2s_v7`**<br>• **크기 조정 방법**: **`수동`** / **노드 수**: **`1`**<br>• **노드당 최대 Pod 수**: **`30`** (`110` ➔ `30` 변경 시 두 풀 합산 필요 IP가 129개로 줄어 `/24` 통과) ➔ `업데이트` |
| **`[3. 네트워킹]`** | 프라이빗 액세스 | **`[✓] 프라이빗 클러스터 사용`** 체크 | **`[✓] 프라이빗 클러스터 사용`** 체크 | **`[✓] 프라이빗 클러스터 사용`** 체크 |
| | 컨테이너 네트워킹 (`네트워크 구성`) | **`Azure CNI 오버레이`** (`Azure CNI Overlay`, 포털 기본값 유지 가능) | **`Azure CNI 오버레이`** (`Azure CNI Overlay`) | **`Azure CNI 노드 서브넷`** (`Azure CNI Node Subnet`) |
| | 자체 Azure 가상 네트워크 사용 | **`[✓] 체크`** | **`[✓] 체크`** | **`[✓] 체크`** |
| | 가상 네트워크 `*` | **`vnet-sre-aks-hub`** | **`vnet-sre-aks-hub`** | **`vnet-sre-spoke-03`** |
| | 클러스터 서브넷 `*` | **`snet-aks-01 (10.52.11.0/24)`** | **`snet-aks-02 (10.52.12.0/27)`** | **`snet-aks-03 (10.60.3.0/24)`** |
| | 사용자가 할당한 관리 ID `*` | `선택` 클릭 ➔ **`id-aks-priv-01`** 선택 | `선택` 클릭 ➔ **`id-aks-priv-02`** 선택 | `선택` 클릭 ➔ **`id-aks-priv-03`** 선택 |
| | 나머지 네트워킹 항목 | 기본값 (`10.0.0.0/16`, `10.0.0.10`, `Cilium` 등) 그대로 유지 | 기본값 그대로 유지 | 기본값 그대로 유지 |
| **`[4. 통합]`** | 전체 항목 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 |
| **`[5. 모니터링]`** | 컨테이너 로그<br>*(⚠️ Prometheus / Grafana는 중복 생성·경합 방지를 위해 모두 체크 해제)* | • 컨테이너 로그: **`[✓] 사용`** 체크<br>• Log Analytics 작업 영역: **`law-sre-aks-monitoring`**<br>• Prometheus 메트릭: **`[ ] 사용 체크 해제`**<br>• Grafana: **`[ ] 사용 체크 해제`** | • 컨테이너 로그: **`[✓] 사용`** 체크<br>• Log Analytics 작업 영역: **`law-sre-aks-monitoring`**<br>• Prometheus 메트릭: **`[ ] 사용 체크 해제`**<br>• Grafana: **`[ ] 사용 체크 해제`** | • 컨테이너 로그: **`[✓] 사용`** 체크<br>• Log Analytics 작업 영역: **`law-sre-deleted-ghost`**<br>• Prometheus 메트릭: **`[ ] 사용 체크 해제`**<br>• Grafana: **`[ ] 사용 체크 해제`** |
| **`[6. 보안]`** | 전체 항목 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 |
| **`[7. 고급]`** | 전체 항목 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 | 변경 없이 바로 **`다음`** 클릭 |
| **`[8. 태그]`** | 7개 태그 (`이름 : 값`) | • `mgmtName` : `ENT_Workloads_Prod`<br>• `ServiceName` : `COMM(커머스플랫폼)`<br>• `ServiceCode` : `ag001101`<br>• `ServiceOpenDate` : `20241001`<br>• `ServiceGrade` : `S`<br>• `SupportPlan` : `KubernetesOfficial`<br>• `PricingTier` : `Standard` | • `mgmtName` : `ENT_Workloads_Prod_PII`<br>• `ServiceName` : `BANK(디지털뱅킹)`<br>• `ServiceCode` : `ag002401`<br>• `ServiceOpenDate` : `20250626`<br>• `ServiceGrade` : `A`<br>• `SupportPlan` : `KubernetesOfficial`<br>• `PricingTier` : `Standard` | • `mgmtName` : `ENT_Workloads_NonProd`<br>• `ServiceName` : `MSG(메시징플랫폼)`<br>• `ServiceCode` : `ag003501`<br>• `ServiceOpenDate` : `20250703`<br>• `ServiceGrade` : `B`<br>• `SupportPlan` : `AKSLongTermSupport`<br>• `PricingTier` : `Premium` |

#### 4단계: [9대 사전 체크리스트 항목 ⑧·⑨ 재현] 클러스터 3대 생성 완료 직후 포털 UI 조작
클러스터 3대가 모두 `Succeeded` 상태로 생성된 직후, SRE Agent가 업그레이드 차단 요소를 실제로 검출할 수 있도록 아래 2가지를 수행합니다:
1. **[항목 ⑧ 재현 — `aks-priv-02`의 타 RG VNet 권한 제거]**:
   - `가상 네트워크 > vnet-sre-aks-hub` (또는 `리소스 그룹 > rg-sre-vwan-network`) > 좌측 **`액세스 제어(IAM) > 역할 할당(Role assignments)`** 탭 이동
   - 목록에서 **`aks-priv-02`** (포털 생성 시 자동 부여된 클러스터 시스템 할당 관리 ID, 또는 CLI 생성 시 **`id-aks-priv-02`**)의 **`네트워크 참가자 (Network Contributor)`** 줄을 체크하고 상단 **`제거 (Remove)`** 클릭
2. **[항목 ⑨ 재현 — `aks-priv-03`가 참조 중인 Log Analytics Workspace 삭제]**:
   - `Log Analytics 작업 영역 > law-sre-deleted-ghost` 클릭 ➔ 상단 **`삭제 (Delete)`** 클릭 (`이름 입력` 후 영구 삭제 체크 및 삭제)

#### 5단계: 3대 클러스터의 사설 DNS Zone(`*.privatelink.eastus2.azmk8s.io`)에 SRE VNet 및 DNS VNet 링크 연결
1. 상단 검색창에서 **`프라이빗 DNS 영역 (Private DNS zones)`** 검색
2. 각 AKS 클러스터의 노드 리소스 그룹(`MC_rg-sre-private-aks-fleet_aks-priv-01_...`, `02`, `03`) 안에 자동 생성된 3개의 `*.privatelink.eastus2.azmk8s.io` 영역을 하나씩 클릭합니다.
3. 각 영역의 좌측 메뉴 **`DNS 관리 > 가상 네트워크 링크 (Virtual network links)`** 클릭 ➔ 상단 **`+ 추가 (+ Add)`** 를 눌러 아래 2개의 VNet 링크를 각각 추가합니다:
   - **링크 1 (SRE Agent VNet 연결)**:
     - **링크 이름 (`Link name`)**: `link-sre-aks`
     - **구독**: 실습 구독 / **가상 네트워크 (`Virtual network`)**: **`vnet-sre-event-lab`**
     - **자동 등록 사용 (`Enable auto registration`)**: **`[ ] 체크 해제`** ➔ **`만들기 (Create)`**
   - **링크 2 (중앙 DNS VNet 연결)**:
     - **링크 이름 (`Link name`)**: `link-dns-aks`
     - **구독**: 실습 구독 / **가상 네트워크 (`Virtual network`)**: **`vnet-sre-dns`**
     - **자동 등록 사용 (`Enable auto registration`)**: **`[ ] 체크 해제`** ➔ **`만들기 (Create)`**

### 복사·붙여넣기용 Step 02-A 전체 생성 스크립트 (Log Analytics + Private AKS 3대 + 12컬럼 태그 + 사설 DNS 링크)
```bash
# 1) 정상 Log Analytics Workspace 및 9번 항목 검증용(생성 후 삭제할) 임시 LAW 생성 (Korea Central)
az monitor log-analytics workspace create -g rg-sre-private-aks-fleet -n law-sre-aks-monitoring -l koreacentral
az monitor log-analytics workspace create -g rg-sre-vwan-network -n law-sre-deleted-ghost -l koreacentral

LAW_VALID_ID=$(az monitor log-analytics workspace show -g rg-sre-private-aks-fleet -n law-sre-aks-monitoring --query id -o tsv)
LAW_GHOST_ID=$(az monitor log-analytics workspace show -g rg-sre-vwan-network -n law-sre-deleted-ghost --query id -o tsv)

# 2) 클러스터별 UAMI 생성 (Korea Central) 및 Cross-RG VNet 권한 부여
for i in 01 02 03; do
  az identity create -g rg-sre-private-aks-fleet -n "id-aks-priv-$i" -l koreacentral
  UMI_PID=$(az identity show -g rg-sre-private-aks-fleet -n "id-aks-priv-$i" --query principalId -o tsv)
  az role assignment create --assignee-object-id "$UMI_PID" --assignee-principal-type ServicePrincipal \
    --role "Network Contributor" --scope "/subscriptions/$SUB_ID/resourceGroups/rg-sre-vwan-network"
done

SNET_01=$(az network vnet subnet show -g rg-sre-vwan-network --vnet-name vnet-sre-aks-hub -n snet-aks-01 --query id -o tsv)
SNET_02=$(az network vnet subnet show -g rg-sre-vwan-network --vnet-name vnet-sre-aks-hub -n snet-aks-02 --query id -o tsv)
SNET_03=$(az network vnet subnet show -g rg-sre-vwan-network --vnet-name vnet-sre-spoke-03 -n snet-aks-03 --query id -o tsv)
UMI_01=$(az identity show -g rg-sre-private-aks-fleet -n id-aks-priv-01 --query id -o tsv)
UMI_02=$(az identity show -g rg-sre-private-aks-fleet -n id-aks-priv-02 --query id -o tsv)
UMI_03=$(az identity show -g rg-sre-private-aks-fleet -n id-aks-priv-03 --query id -o tsv)

# 3) Private AKS 01 생성 (East US 2, 1.36.4, S등급, COMM, 정상 클러스터, Standard_D2s_v7)
az aks create -g rg-sre-private-aks-fleet -n aks-priv-01 -l eastus2 \
  --kubernetes-version 1.36.4 --tier standard --support-plan KubernetesOfficial \
  --enable-private-cluster --enable-aad --enable-azure-rbac \
  --network-plugin azure --vnet-subnet-id "$SNET_01" \
  --assign-identity "$UMI_01" --node-count 1 --node-vm-size Standard_D2s_v7 \
  --enable-addons monitoring --workspace-resource-id "$LAW_VALID_ID" \
  --tags mgmtName=ENT_Workloads_Prod ServiceName="COMM(커머스플랫폼)" ServiceCode=ag001101 \
         ServiceOpenDate=20241001 ServiceGrade=S SupportPlan=KubernetesOfficial PricingTier=Standard

# 4) Private AKS 02 생성 (East US 2, 1.35.9, A등급, BANK, /27 서브넷, Azure CNI Overlay)
az aks create -g rg-sre-private-aks-fleet -n aks-priv-02 -l eastus2 \
  --kubernetes-version 1.35.9 --tier standard --support-plan KubernetesOfficial \
  --enable-private-cluster --enable-aad --enable-azure-rbac \
  --network-plugin azure --network-plugin-mode overlay --vnet-subnet-id "$SNET_02" \
  --assign-identity "$UMI_02" --node-count 1 --node-vm-size Standard_D2s_v7 \
  --enable-addons monitoring --workspace-resource-id "$LAW_VALID_ID" \
  --tags mgmtName=ENT_Workloads_Prod_PII ServiceName="BANK(디지털뱅킹)" ServiceCode=ag002401 \
         ServiceOpenDate=20250626 ServiceGrade=A SupportPlan=KubernetesOfficial PricingTier=Standard

# 5) Private AKS 03 생성 (East US 2, 1.34.12, B등급, MSG, LTS/Premium)
az aks create -g rg-sre-private-aks-fleet -n aks-priv-03 -l eastus2 \
  --kubernetes-version 1.34.12 --tier premium --support-plan AKSLongTermSupport \
  --enable-private-cluster --enable-aad --enable-azure-rbac \
  --network-plugin azure --vnet-subnet-id "$SNET_03" \
  --assign-identity "$UMI_03" --node-count 1 --node-vm-size Standard_D2s_v7 \
  --enable-addons monitoring --workspace-resource-id "$LAW_GHOST_ID" \
  --tags mgmtName=ENT_Workloads_NonProd ServiceName="MSG(메시징플랫폼)" ServiceCode=ag003501 \
         ServiceOpenDate=20250703 ServiceGrade=B SupportPlan=AKSLongTermSupport PricingTier=Premium

# 6) [9대 체크리스트 항목 ⑧ 재현] aks-priv-02의 타 RG VNet Network Contributor 권한 제거
UMI_02_PID=$(az identity show -g rg-sre-private-aks-fleet -n id-aks-priv-02 --query principalId -o tsv)
az role assignment delete --assignee "$UMI_02_PID" --role "Network Contributor" \
  --scope "/subscriptions/$SUB_ID/resourceGroups/rg-sre-vwan-network"

# 7) [9대 체크리스트 항목 ⑨ 재현] aks-priv-03가 참조 중인 임시 Log Analytics Workspace 삭제
az monitor log-analytics workspace delete -g rg-sre-vwan-network -n law-sre-deleted-ghost --force true --yes

# 8) 모든 사설 AKS Private DNS Zone(*.privatelink.eastus2.azmk8s.io)에 SRE VNet 및 DNS VNet 링크 연결
SRE_VNET_ID=$(az network vnet show -g rg-sre-agent-fleet -n vnet-sre-event-lab --query id -o tsv)
az network private-dns zone list --query "[?contains(name, 'azmk8s.io')].{rg:resourceGroup, name:name}" -o tsv | \
while read -r ZONE_RG ZONE_NAME; do
  PREFIX=$(echo "$ZONE_NAME" | cut -d. -f1 | cut -c1-10)
  az network private-dns link vnet create -g "$ZONE_RG" -z "$ZONE_NAME" -n "link-sre-$PREFIX" -v "$SRE_VNET_ID" -e false --no-wait
  az network private-dns link vnet create -g "$ZONE_RG" -z "$ZONE_NAME" -n "link-dns-$PREFIX" -v "$DNS_VNET_ID" -e false --no-wait
done
```

---

## Step 02-B. 포털 `Run command`(또는 CLI)로 3대 클러스터에 사전 점검 시나리오용 K8s 워크로드 배포

Azure Portal의 **`Kubernetes 리소스 (Kubernetes resources) > 명령 실행 (Run command)`** 화면(또는 `az aks command invoke`)에서 3대 클러스터에 사전 점검 검증용 워크로드 매니페스트를 배포합니다.

### 포털 UI 화면 이동 및 실행 순서 (`실행 명령` 600자 제한 대응 분할 실행)
1. **`Kubernetes 서비스 > aks-priv-01` (이후 `02`, `03` 반복) > 좌측 메뉴 `Kubernetes 리소스` > `실행 명령 (Run command)` 클릭**
2. **하단 명령 입력창(`최대 600자 제한`)에 아래 클러스터별 분할 블록(`[블록 1]`, `[블록 2]`, `[블록 3]`...)을 순서대로 하나씩 복사해 붙여넣고 우측 하단 `▷ (실행)` 아이콘 클릭**
   - 입력창 우측 하단(`시험 실행` 토글 옆)의 **`📎 (파일 첨부)`** 아이콘으로 클러스터별 YAML 파일을 첨부한 뒤 `kubectl apply -f priv01.yaml`을 실행할 수도 있습니다.
3. **클러스터별 배포 워크로드 구성**:
   - **`aks-priv-01` (`1.36.4`, 정상 `READY`)**: `commerce/ecommerce-storefront` (`replicas: 2`, Probe/preStop 정상), `ingress-nginx` **`v1.11.2`**, Gateway API **`v1.1.0`**
   - **`aks-priv-02` (`1.35.9`, `BLOCKED`)**:
     - [항목 ② Local Storage] `banking-cache` 파드 `emptyDir` 볼륨 마운트
     - [항목 ③ 스케줄링 제약 / Pending] `banking/batch-settlement-pending` (4 CPU 코어 요청으로 `Insufficient cpu` **`Pending`** 상태 재현)
     - [항목 ⑤ API/애드온] `ingress-nginx` 구버전 **`v1.9.4`** + 위험 어노테이션(`enable-snippet-annotations: "true"`)
     - [항목 ⑥ Graceful Shutdown] `preStop` 훅 미설정
   - **`aks-priv-03` (`1.34.12`, `BLOCKED`)**:
     - [항목 ① Pod HA] `messaging/sms-gateway-single` (`replicas: 1` 단일 레플리카)
     - [항목 ② Local Storage] `messaging-audit` 파드 `HostPath`(`/var/log/msg`) 마운트
     - [항목 ④ PDB 차단] `messaging/notification-pdb` (`minAvailable: 100%` ➔ **`AllowedDisruptions=0`**)
     - [항목 ⑤ 애드온] `ingress-nginx` **`v1.10.1`** + Gateway API **`v1.0.0`**
     - [항목 ⑥ & 점프박스 장애 파드] `messaging/push-webhook-relay` (`exit 1` **`CrashLoopBackOff`**, Probe 누락) 및 `messaging/legacy-batch-sync` (`nonexistent-broken-tag-v99.99` **`ImagePullBackOff`**)
4. **상단 출력 콘솔에서 모든 오브젝트가 `created` / `configured` 되었는지 확인**

### 포털 `실행 명령 (Run command)` 붙여넣기용 블록 (전 블록 510자 이하 / 600자 제한 통과)

#### 1) `aks-priv-01` (`실행 명령`에 순서대로 3번 붙여넣기)

- **`[블록 1/3]` 네임스페이스 & `ingress-nginx` v1.11.2 생성 (307자)**:
```bash
kubectl create ns commerce
kubectl create ns ingress-nginx
kubectl create deploy ingress-nginx-controller -n ingress-nginx --image=nginx:1.25-alpine --replicas=2
kubectl label deploy ingress-nginx-controller -n ingress-nginx app.kubernetes.io/name=ingress-nginx app.kubernetes.io/version=v1.11.2 --overwrite
```

- **`[블록 2/3]` `ecommerce-storefront` 정상 HA + Probe + preStop 배포 (490자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: ecommerce-storefront, namespace: commerce}
spec:
  replicas: 2
  selector: {matchLabels: {app: store}}
  template:
    metadata: {labels: {app: store}}
    spec:
      containers:
      - name: store
        image: nginx:1.25-alpine
        livenessProbe: {httpGet: {path: /, port: 80}}
        readinessProbe: {httpGet: {path: /, port: 80}}
        lifecycle: {preStop: {exec: {command: ["sleep","5"]}}}
EOF
```

- **`[블록 3/3]` `storefront-ingress` 배포 (469자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: storefront-ingress
  namespace: commerce
  annotations: {nginx.ingress.kubernetes.io/ssl-redirect: "true"}
spec:
  ingressClassName: nginx
  tls: [{hosts: [shop.contoso.internal], secretName: storefront-tls}]
  rules:
  - host: shop.contoso.internal
    http:
      paths: [{path: /, pathType: Prefix, backend: {service: {name: ecommerce-storefront, port: {number: 80}}}}]
EOF
```

---

#### 2) `aks-priv-02` (`실행 명령`에 순서대로 4번 붙여넣기)

- **`[블록 1/4]` 네임스페이스 & 구버전 `ingress-nginx` v1.9.4 + snippet 설정 (443자)**:
```bash
kubectl create ns banking
kubectl create ns ingress-nginx
kubectl create deploy ingress-nginx-controller -n ingress-nginx --image=nginx:1.25-alpine --replicas=1
kubectl label deploy ingress-nginx-controller -n ingress-nginx app.kubernetes.io/name=ingress-nginx app.kubernetes.io/version=v1.9.4 --overwrite
kubectl annotate deploy ingress-nginx-controller -n ingress-nginx nginx.ingress.kubernetes.io/enable-snippet-annotations=true --overwrite
```

- **`[블록 2/4]` `banking-cache` (`emptyDir` 로컬 볼륨 마운트) 배포 (394자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: banking-cache, namespace: banking}
spec:
  replicas: 2
  selector: {matchLabels: {app: cache}}
  template:
    metadata: {labels: {app: cache}}
    spec:
      containers: [{name: c, image: nginx:1.25-alpine, volumeMounts: [{name: v, mountPath: /var/cache/banking}]}]
      volumes: [{name: v, emptyDir: {}}]
EOF
```

- **`[블록 3/4]` `batch-settlement-pending` (`Insufficient cpu` Pending 파드) 배포 (362자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: batch-settlement-pending, namespace: banking}
spec:
  replicas: 1
  selector: {matchLabels: {app: batch}}
  template:
    metadata: {labels: {app: batch}}
    spec:
      containers: [{name: b, image: nginx:1.25-alpine, resources: {requests: {cpu: "4000m", memory: "512Mi"}}}]
EOF
```

- **`[블록 4/4]` `banking-ingress` (위험 snippet 어노테이션 포함) 배포 (503자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: banking-ingress
  namespace: banking
  annotations:
    nginx.ingress.kubernetes.io/enable-snippet-annotations: "true"
    nginx.ingress.kubernetes.io/configuration-snippet: "more_set_headers 'X-Frame-Options: DENY';"
spec:
  ingressClassName: nginx
  rules:
  - host: bank.contoso.internal
    http:
      paths: [{path: /, pathType: Prefix, backend: {service: {name: banking-cache, port: {number: 80}}}}]
EOF
```

---

#### 3) `aks-priv-03` (`실행 명령`에 순서대로 3번 붙여넣기)

- **`[블록 1/3]` 네임스페이스, `ingress-nginx` v1.10.1, 단일 레플리카, `ImagePullBackOff` 파드 (511자)**:
```bash
kubectl create ns messaging
kubectl create ns ingress-nginx
kubectl create deploy ingress-nginx-controller -n ingress-nginx --image=nginx:1.25-alpine --replicas=1
kubectl label deploy ingress-nginx-controller -n ingress-nginx app.kubernetes.io/name=ingress-nginx app.kubernetes.io/version=v1.10.1 --overwrite
kubectl create deploy sms-gateway-single -n messaging --image=nginx:1.25-alpine --replicas=1
kubectl create deploy legacy-batch-sync -n messaging --image=nginx:nonexistent-broken-tag-v99.99 --replicas=2
```

- **`[블록 2/3]` `messaging-audit` (`HostPath` 마운트) 배포 (435자)**:
```bash
kubectl apply -f - << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: messaging-audit, namespace: messaging}
spec:
  replicas: 2
  selector: {matchLabels: {app: audit}}
  template:
    metadata: {labels: {app: audit}}
    spec:
      containers: [{name: a, image: nginx:1.25-alpine, volumeMounts: [{name: h, mountPath: /var/log/msg}]}]
      volumes: [{name: h, hostPath: {path: /var/log/msg, type: DirectoryOrCreate}}]
EOF
```

- **`[블록 3/3]` 차단 `PDB`(`AllowedDisruptions=0`) & `push-webhook-relay` (`CrashLoopBackOff`) 배포 (438자)**:
```bash
kubectl create pdb notification-pdb -n messaging --selector=app=sms-gateway-single --min-available=100%
kubectl apply -f - << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata: {name: push-webhook-relay, namespace: messaging}
spec:
  replicas: 1
  selector: {matchLabels: {app: relay}}
  template:
    metadata: {labels: {app: relay}}
    spec:
      containers: [{name: r, image: nginx:1.25-alpine, command: ["sh","-c","exit 1"]}]
EOF
```

---

### (대안) 복사·붙여넣기용 Step 02-B 3대 클러스터 시나리오 워크로드 일괄 배포 CLI (`az aks command invoke`)

#### 1) `aks-priv-01` 워크로드 배포 (정상 `READY` 기준 클러스터)
```bash
az aks command invoke -g rg-sre-private-aks-fleet -n aks-priv-01 --command "
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: commerce
---
apiVersion: v1
kind: Namespace
metadata:
  name: ingress-nginx
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
  labels:
    app.kubernetes.io/name: ingress-nginx
    app.kubernetes.io/version: v1.11.2
spec:
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ingress-nginx
        app.kubernetes.io/version: v1.11.2
    spec:
      containers:
      - name: controller
        image: docker.io/library/nginx:1.25-alpine
        ports:
        - containerPort: 80
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ecommerce-storefront
  namespace: commerce
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ecommerce-storefront
  template:
    metadata:
      labels:
        app: ecommerce-storefront
    spec:
      containers:
      - name: storefront
        image: docker.io/library/nginx:1.25-alpine
        ports:
        - containerPort: 80
        resources:
          requests:
            cpu: 50m
            memory: 64Mi
        livenessProbe:
          httpGet:
            path: /
            port: 80
        readinessProbe:
          httpGet:
            path: /
            port: 80
        lifecycle:
          preStop:
            exec:
              command: [\"/bin/sh\", \"-c\", \"sleep 5\"]
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: storefront-ingress
  namespace: commerce
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: \"true\"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - shop.contoso.internal
    secretName: storefront-tls
  rules:
  - host: shop.contoso.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: ecommerce-storefront
            port:
              number: 80
EOF
"
```

#### 2) `aks-priv-02` 워크로드 배포 (`Pending` 파드 · `emptyDir` · 구버전 `ingress-nginx v1.9.4` + `snippet` 어노테이션)
```bash
az aks command invoke -g rg-sre-private-aks-fleet -n aks-priv-02 --command "
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: banking
---
apiVersion: v1
kind: Namespace
metadata:
  name: ingress-nginx
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
  labels:
    app.kubernetes.io/name: ingress-nginx
    app.kubernetes.io/version: v1.9.4
  annotations:
    nginx.ingress.kubernetes.io/enable-snippet-annotations: \"true\"
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ingress-nginx
        app.kubernetes.io/version: v1.9.4
    spec:
      containers:
      - name: controller
        image: docker.io/library/nginx:1.25-alpine
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: banking-cache
  namespace: banking
spec:
  replicas: 2
  selector:
    matchLabels:
      app: banking-cache
  template:
    metadata:
      labels:
        app: banking-cache
    spec:
      containers:
      - name: cache
        image: docker.io/library/nginx:1.25-alpine
        volumeMounts:
        - name: cache-vol
          mountPath: /var/cache/banking
      volumes:
      - name: cache-vol
        emptyDir: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: batch-settlement-pending
  namespace: banking
spec:
  replicas: 1
  selector:
    matchLabels:
      app: batch-settlement-pending
  template:
    metadata:
      labels:
        app: batch-settlement-pending
    spec:
      nodeSelector:
        kubernetes.io/os: linux
      containers:
      - name: batch
        image: docker.io/library/nginx:1.25-alpine
        resources:
          requests:
            cpu: \"4000m\"
            memory: \"512Mi\"
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: banking-ingress
  namespace: banking
  annotations:
    nginx.ingress.kubernetes.io/enable-snippet-annotations: \"true\"
    nginx.ingress.kubernetes.io/configuration-snippet: \"more_set_headers 'X-Frame-Options: DENY';\"
spec:
  ingressClassName: nginx
  rules:
  - host: bank.contoso.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: banking-cache
            port:
              number: 80
EOF
"
```

#### 3) `aks-priv-03` 워크로드 배포 (단일 레플리카 · `HostPath` · 차단 `PDB` · `CrashLoopBackOff` · `ImagePullBackOff` · `ingress-nginx v1.10.1`)
```bash
az aks command invoke -g rg-sre-private-aks-fleet -n aks-priv-03 --command "
kubectl apply -f - << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: messaging
---
apiVersion: v1
kind: Namespace
metadata:
  name: ingress-nginx
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingress-nginx-controller
  namespace: ingress-nginx
  labels:
    app.kubernetes.io/name: ingress-nginx
    app.kubernetes.io/version: v1.10.1
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: ingress-nginx
  template:
    metadata:
      labels:
        app.kubernetes.io/name: ingress-nginx
        app.kubernetes.io/version: v1.10.1
    spec:
      containers:
      - name: controller
        image: docker.io/library/nginx:1.25-alpine
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sms-gateway-single
  namespace: messaging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: sms-gateway-single
  template:
    metadata:
      labels:
        app: sms-gateway-single
    spec:
      containers:
      - name: sms
        image: docker.io/library/nginx:1.25-alpine
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: messaging-audit
  namespace: messaging
spec:
  replicas: 2
  selector:
    matchLabels:
      app: messaging-audit
  template:
    metadata:
      labels:
        app: messaging-audit
    spec:
      containers:
      - name: audit
        image: docker.io/library/nginx:1.25-alpine
        volumeMounts:
        - name: host-log
          mountPath: /var/log/msg
      volumes:
      - name: host-log
        hostPath:
          path: /var/log/msg
          type: DirectoryOrCreate
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: push-webhook-relay
  namespace: messaging
spec:
  replicas: 1
  selector:
    matchLabels:
      app: push-webhook-relay
  template:
    metadata:
      labels:
        app: push-webhook-relay
    spec:
      containers:
      - name: relay
        image: docker.io/library/nginx:1.25-alpine
        command: [\"/bin/sh\", \"-c\", \"exit 1\"]
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: legacy-batch-sync
  namespace: messaging
spec:
  replicas: 2
  selector:
    matchLabels:
      app: legacy-batch-sync
  template:
    metadata:
      labels:
        app: legacy-batch-sync
    spec:
      containers:
      - name: sync
        image: docker.io/library/nginx:nonexistent-broken-tag-v99.99
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: notification-pdb
  namespace: messaging
spec:
  minAvailable: 100%
  selector:
    matchLabels:
      app: sms-gateway-single
EOF
"
```

---

# Phase 2. SRE Agent 생성 · 보안 심의용 최소 읽기 권한(RBAC) 및 Grafana 대시보드 1클릭 Import

---

## Step 03. SRE Agent 리소스 생성(VNet과 동일 리전) 및 최소 읽기 권한(Least-Privilege RBAC) 할당

### 포털 UI 화면 이동 및 탭·필드별 입력값 (`1단계` ➔ `2단계`)

#### 1단계: Azure SRE Agent 리소스 생성 (`SRE Agent > + 만들기`)
상단 검색창에서 **`SRE Agent`** 검색 ➔ **`+ 만들기 (+ Create)`** 클릭 후 아래 표의 값을 입력하여 생성합니다:

| 필드명 (포털 표시명) | 입력 / 선택할 값 | 설명 및 주의사항 |
|---|---|---|
| **구독 (`Subscription`)** | 실습 대상 구독 | - |
| **리소스 그룹 (`Resource group`)** | **`rg-sre-agent-fleet`** | Step 00에서 만든 SRE Agent 전용 RG |
| **이름 (`Name`)** | **`sre-aks-fleet-agent`** | 에이전트 리소스 이름 |
| **지역 (`Region`)** | **`Korea Central`** | ⚠️ **필수**: Step 06에서 연결할 SRE VNet(`vnet-sre-event-lab`)과 반드시 **동일한 리전**이어야 VNet 통합이 가능합니다. |
| **관리 리소스 그룹 / 관리 ID** | 기본 자동 생성 유지 | 배포 완료 시 `rg-sre-agent-fleet` 내에 에이전트 전용 사용자 할당 관리 ID(UAMI, 예: `id-sre-aks-fleet-agent` 또는 `<에이전트명>-identity`)가 함께 생성됩니다. |

#### 2단계: 운영자 본인 계정 및 에이전트 관리 ID(UAMI)에 RBAC 역할 할당 (`액세스 제어(IAM) > + 추가 > 역할 할당 추가`)
> 💡 **중요**: `SRE Agent` 리소스(`sre-aks-fleet-agent`) 자체를 클릭하면 전용 에이전트 화면(`sre.azure.com`)으로 연결되어 좌측에 `액세스 제어(IAM)` 메뉴가 없습니다. 따라서 **모든 역할 할당은 아래 표의 대상 리소스 그룹 또는 구독 화면의 좌측 `액세스 제어(IAM)` 메뉴**에서 수행합니다.

배포가 완료되면 아래 표의 **3개 위치(Scope)** 로 각각 이동하여 **`좌측 액세스 제어(IAM) > + 추가 > 역할 할당 추가`** 를 클릭해 권한을 부여합니다:

| 할당 순서 | 이동할 포털 메뉴 위치 (Scope) | `[역할]` 탭에서 검색·선택할 역할 이름 | `[구성원]` 탭 `액세스 할당 대상` 선택 | `[구성원]` 탭에서 선택할 대상 | 목적 |
|---|---|---|---|---|---|
| **할당 1**<br>(운영자 권한) | **`리소스 그룹 > rg-sre-agent-fleet` > 좌측 `액세스 제어(IAM)`** | 검색창에 **`SRE`** 입력 ➔ **`SRE Agent Administrator`** (또는 **`SRE 에이전트 관리자`**) | `사용자, 그룹 또는 서비스 주체` | **현재 로그인한 운영자 본인 계정** (`admin@contoso.com`) | `https://sre.azure.com` 포털에서 도구·스킬·네트워크 설정 저장 권한 (상위 RG에서 부여 시 하위 에이전트에 자동 상속) |
| **할당 2**<br>(구독 읽기 권한) | **`구독 (Subscriptions) > 실습 구독` > 좌측 `액세스 제어(IAM)`** | ① 검색창 비운 상태에서 맨 위 첫 줄 **`독자`** (또는 검색창에 **`독자`** 검색 — 영문 `Reader`)<br>② 검색창에 **`모니터링`** 입력 ➔ **`모니터링 독자`** (또는 **`모니터링 판독기`** — 영문 `Monitoring Reader`) | `관리 ID (Managed identity)` | `+ 구성원 선택` ➔ 관리 ID: **`사용자 할당 관리 ID`** ➔ **`sre-aks-fleet-agent-<난수>`** 선택 | 클러스터 목록, 타 RG VNet RBAC(항목 ⑧), 삭제된 LAW ID(항목 ⑨) 및 ARG 대시보드 조회용 |
| **할당 3**<br>(AKS 데이터 플레인 읽기) | **`리소스 그룹 > rg-sre-private-aks-fleet` > 좌측 `액세스 제어(IAM)`** | 검색창에 **`Azure Kubernetes Service`** 입력 후:<br>① **`Azure Kubernetes Service 클러스터 사용자 역할`**<br>② **`Azure Kubernetes Service RBAC 독자`** (또는 **`Azure Kubernetes Service RBAC 읽기 권한자`**) | `관리 ID (Managed identity)` | `+ 구성원 선택` ➔ 관리 ID: **`사용자 할당 관리 ID`** ➔ **`sre-aks-fleet-agent-<난수>`** 선택 | `RunKubectlReadCommand`를 통한 사설 AKS Pod, Event, Deployment, PDB, Ingress 읽기 전용 조회 (Secret 조회 불가) |

### 복사·붙여넣기용 RBAC 할당 CLI
```bash
UAMI_PRINCIPAL_ID=$(az identity show -g rg-sre-agent-fleet -n id-sre-aks-fleet-agent --query principalId -o tsv)

# 1) 구독 범위 Reader + Monitoring Reader (Cross-RG VNet 및 LAW 검증 포함)
for ROLE in "Reader" "Monitoring Reader"; do
  az role assignment create \
    --assignee-object-id "$UAMI_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "$ROLE" \
    --scope "/subscriptions/$SUB_ID"
done

# 2) AKS 리소스 그룹 범위 Cluster User + RBAC Reader
for ROLE in \
  "Azure Kubernetes Service Cluster User Role" \
  "Azure Kubernetes Service RBAC Reader"; do
  az role assignment create \
    --assignee-object-id "$UAMI_PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "$ROLE" \
    --scope "/subscriptions/$SUB_ID/resourceGroups/rg-sre-private-aks-fleet"
done
```

---

## Step 04-A. `Azure Monitor > Dashboards with Grafana` (`SRE-AKS-Management`) Import

Azure Portal 내 **Azure Monitor의 `Dashboards with Grafana` (`Microsoft.Dashboard/dashboards`)** 기능에 **[`sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json)** 파일을 업로드하여 Overview(관리그룹 표, 등급별 카드 5종, Standard/LTS 버전 표, 단위서비스 목록)와 하단 12컬럼 인벤토리 + NodePool 표까지 총 13개 패널을 생성합니다.

### 방법 1: `Azure Monitor > Dashboards with Grafana`에서 Import
1. **Azure Portal 상단 검색창에서 `Monitor` (`모니터`) 검색 후 이동**
2. **좌측 메뉴에서 `Dashboards with Grafana` (`Grafana를 사용한 대시보드`) 클릭**
3. **상단 툴바에서 `New` (`새로 만들기`) ➔ `Import` (`가져오기`) 클릭**
4. **`Upload dashboard JSON file`에 [`sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json) 파일 선택 후 `Load` 클릭**:
   - **이름 (`Dashboard Name`)**: **`SRE-AKS-Management`**
   - **구독 (`Subscription`)**: 현재 실습 구독 선택
   - **리소스 그룹 (`Resource Group`)**: **`rg-sre-private-aks-fleet`**
   - **지역 (`Region`)**: **`Korea Central`**
5. **`Import` (`가져오기 / 저장`) 클릭**:
   - 리소스 그룹(`rg-sre-private-aks-fleet`) 안에 **`SRE-AKS-Management` (`Dashboard with Grafana` 타입)** 리소스가 생성되며, 포털 좌측 메뉴 **`Dashboard with Grafana`** 탭에서 대시보드를 조회·편집·CSV 다운로드할 수 있습니다.

### 방법 2 (선택 사항): 독립형 `Azure Managed Grafana` 워크스페이스에 Import
- 포털 내장 대시보드 상단 툴바의 **`Copy to Managed Grafana`** 버튼을 누르거나, `Azure Managed Grafana` 웹 UI(`Dashboards > New > Import`)에서 동일한 `sre-aks-management-dashboard.json` 파일을 업로드합니다.

### 복사·붙여넣기용 Step 04-A Azure CLI 명령어 (`Dashboard with Grafana` 리소스 생성 + 13패널 정의 배포)
```bash
# 1) 포털 내장 'Dashboard with Grafana' (Microsoft.Dashboard/dashboards) 리소스 생성
az resource create \
  --resource-group rg-sre-private-aks-fleet \
  --namespace Microsoft.Dashboard --resource-type dashboards \
  --name SRE-AKS-Management --location koreacentral \
  --api-version 2025-09-01-preview --properties "{}"

# 2) sre-aks-management-dashboard.json (13개 패널 전체) 정의를 대시보드에 주입
python3 -c '
import json, subprocess, sys
sub_id, rg = sys.argv[1], "rg-sre-private-aks-fleet"
dash = open("docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab/monitoring/sre-aks-management-dashboard.json").read()
body = json.dumps({"properties": {"serializedData": dash}})
open("/tmp/dash_def.json", "w").write(body)
url = f"https://management.azure.com/subscriptions/{sub_id}/resourceGroups/{rg}/providers/Microsoft.Dashboard/dashboards/SRE-AKS-Management/dashboardDefinitions/default?api-version=2025-09-01-preview"
subprocess.run(["az", "rest", "--method", "PUT", "--url", url, "--body", "@/tmp/dash_def.json"], check=True)
' "$SUB_ID"
```

---

## Step 04-B. Grafana (`SRE-AKS-Management`) 13개 패널 및 12컬럼 인벤토리 KQL 확인

`SRE-AKS-Management` 대시보드의 패널 구성과 12개 표준 컬럼을 확인합니다.

### 대시보드 JSON 파일 경로
- **1클릭 Import용 대시보드 JSON**: [`./monitoring/sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json)

### 포털 UI 확인 순서 (`①` ➔ `⑤`)
1. **`①` Azure Portal > `Azure Monitor > Dashboards with Grafana` > `SRE-AKS-Management` 클릭**
2. **`②` CSV 다운로드 위치 확인 (`개별 패널 우측 상단 ⋮ > Inspect > Data > Download CSV`)**:
   - ⚠️ 페이지 맨 위 제목(`Monitor | Dashboards with Grafana | ...`) 옆의 가로 점 3개(`...`)가 아닙니다.
   - 하단 **`AKS Cluster Inventory` 표 패널(네모 박스)의 제목 줄에 마우스를 올리면**, 해당 패널 우측 상단 모서리에 **`⋮` (세로 점 3개 메뉴 아이콘)** 이 나타납니다.
   - **`⋮` 클릭 ➔ `Inspect` ➔ `Data` ➔ 상단 파란색 `Download CSV` 버튼 클릭**으로 12컬럼 인벤토리 CSV를 내려받을 수 있습니다.
3. **`③` 상단 Overview 행 확인 (데이터 원본: `Azure Resource Graph`, 변수 `${am_ds}`, 범위 `"scope": "directory"`)**:
   - Management Group 기준 관리대상 클러스터 분류(`ENT_Workloads_Prod`, `ENT_Workloads_Prod_PII`, `ENT_Workloads_NonProd`) 및 등급별(`S`/`A`/`B`/`C`) 수량 집계
   - 일반 AKS 클러스터 버전 현황(`SupportPlan == KubernetesOfficial`) vs LTS AKS 클러스터 버전 현황(`SupportPlan == AKSLongTermSupport`)
4. **`④` 하단 `AKS Cluster Inventory` (표준 12개 컬럼) 확인**:
   - `mgmtName`, `Subscription`, `Cluster`, `k8sVersion`, `SupportPlan`, `PricingTier`, `ServiceName`, `ServiceCode`, `ServiceOpenDate`, `ServiceGrade`, `APIServerAccess`, `NetworkPlugin`
5. **`⑤` 하단 `AKS Cluster Inventory (Include Nodepool)` 확인**:
   - 표준 12개 컬럼에 멀티 노드풀 상세(`NodePool`, `Mode`)를 `mv-expand pool = properties.agentPoolProfiles`로 확장해 표시합니다.

### 복사·붙여넣기용 Panel 1 ~ Panel 4 전체 표준 ARG KQL 쿼리 원문
```kusto
// [Panel 1] Management Group 기준 관리대상 클러스터 분류 & 등급별(S/A/B/C) 수량
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| extend mgmtName = coalesce(tostring(tags['mgmtName']), 'ENT_Workloads_Prod'),
         ServiceGrade = coalesce(tostring(tags['ServiceGrade']), 'C'),
         envType = case(mgmtName contains 'NonProd', '개발(Dev)', mgmtName contains 'Stg', '스테이지(Stg)', '운영(Prd)')
| summarize TotalClusters=count(), S_Grade=countif(ServiceGrade=='S'), A_Grade=countif(ServiceGrade=='A'), B_Grade=countif(ServiceGrade=='B'), C_Grade=countif(ServiceGrade=='C') by mgmtName, envType
| extend Managed='O'
| project mgmtName, envType, Managed, TotalClusters, S_Grade, A_Grade, B_Grade, C_Grade
| order by mgmtName asc
```

```kusto
// [Panel 2] 일반 AKS 버전 현황 (KubernetesOfficial) vs LTS AKS 버전 현황 (AKSLongTermSupport)
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| extend k8sVersion = tostring(properties.currentKubernetesVersion),
         SupportPlan = coalesce(tostring(tags['SupportPlan']), tostring(properties.supportPlan), 'KubernetesOfficial'),
         PricingTier = coalesce(tostring(tags['PricingTier']), tostring(sku.tier), 'Standard'),
         mgmtName = coalesce(tostring(tags['mgmtName']), 'ENT_Workloads_Prod')
| summarize Total=count(), Prd=countif(mgmtName contains 'Prod' and not(mgmtName contains 'NonProd')), Dev=countif(mgmtName contains 'NonProd'), Stg=countif(mgmtName contains 'Stg') by k8sVersion, SupportPlan, PricingTier
| order by SupportPlan desc, k8sVersion asc
```

```kusto
// [Panel 3] AKS Cluster Inventory (12 Standard Columns)
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| extend mgmtName = coalesce(tostring(tags['mgmtName']), 'ENT_Workloads_Prod'),
         Subscription = subscriptionId,
         Cluster = name,
         k8sVersion = tostring(properties.currentKubernetesVersion),
         SupportPlan = coalesce(tostring(tags['SupportPlan']), tostring(properties.supportPlan), 'KubernetesOfficial'),
         PricingTier = coalesce(tostring(tags['PricingTier']), tostring(sku.tier), 'Standard'),
         ServiceName = coalesce(tostring(tags['ServiceName']), tostring(tags['service'])),
         ServiceCode = coalesce(tostring(tags['ServiceCode']), 'ag000000'),
         ServiceOpenDate = coalesce(tostring(tags['ServiceOpenDate']), '20250101'),
         ServiceGrade = coalesce(tostring(tags['ServiceGrade']), 'C'),
         APIServerAccess = iff(tobool(properties.apiServerAccessProfile.enablePrivateCluster), 'true (Private)', 'false'),
         NetworkPlugin = tostring(properties.networkProfile.networkPlugin)
| project mgmtName, Subscription, Cluster, k8sVersion, SupportPlan, PricingTier, ServiceName, ServiceCode, ServiceOpenDate, ServiceGrade, APIServerAccess, NetworkPlugin
| order by k8sVersion asc, Cluster asc
```

```kusto
// [Panel 4] AKS Cluster Inventory (Include Nodepool — 12 Columns + NodePool & Mode)
Resources
| where type =~ 'microsoft.containerservice/managedclusters'
| mv-expand pool = properties.agentPoolProfiles
| extend mgmtName = coalesce(tostring(tags['mgmtName']), 'ENT_Workloads_Prod'),
         Subscription = subscriptionId,
         Cluster = name,
         k8sVersion = tostring(pool.currentOrchestratorVersion),
         SupportPlan = coalesce(tostring(tags['SupportPlan']), tostring(properties.supportPlan), 'KubernetesOfficial'),
         PricingTier = coalesce(tostring(tags['PricingTier']), tostring(sku.tier), 'Standard'),
         ServiceName = coalesce(tostring(tags['ServiceName']), tostring(tags['service'])),
         ServiceCode = coalesce(tostring(tags['ServiceCode']), 'ag000000'),
         ServiceOpenDate = coalesce(tostring(tags['ServiceOpenDate']), '20250101'),
         ServiceGrade = coalesce(tostring(tags['ServiceGrade']), 'C'),
         APIServerAccess = iff(tobool(properties.apiServerAccessProfile.enablePrivateCluster), 'true (Private)', 'false'),
         NodePool = tostring(pool.name),
         Mode = tostring(pool.mode),
         NetworkPlugin = tostring(properties.networkProfile.networkPlugin)
| project mgmtName, Subscription, Cluster, k8sVersion, SupportPlan, PricingTier, ServiceName, ServiceCode, ServiceOpenDate, ServiceGrade, APIServerAccess, NodePool, Mode, NetworkPlugin
| order by k8sVersion asc, Cluster asc, NodePool asc
```

---

# Phase 3. SRE Agent 포털(`sre.azure.com`) 관리 범위 · VNet 통합 · 지식 베이스 구성

---

## Step 05. `Managed resources`에서 관리 대상 Management Group · 구독 · 리소스 그룹 연결

### 화면 이동 및 입력 순서 (`①` ➔ `③`)
1. **`①` 좌측 사이드바 `Build & setup > Context > Managed resources` 클릭**:
   - `https://sre.azure.com`에서 대상 에이전트(`sre-aks-fleet-agent`)를 열고 `Managed resources` 메뉴로 이동합니다.
2. **`②` `+ Add resource scopes` 클릭**:
   - 엔터프라이즈 멀티 구독 환경처럼 다수의 구독(`ENT_Workloads_Prod`, `ENT_Workloads_Prod_PII`, `ENT_Workloads_NonProd`)에 클러스터가 나뉘어 있는 경우 상위 **Management Group** 또는 대상 **Subscription**을 선택합니다.
   - 주의: AKS 클러스터(`rg-sre-private-aks-fleet`)와 **다른 리소스 그룹(`rg-sre-vwan-network`)** 에 있는 VNet(9대 체크리스트 항목 ⑧) 및 Log Analytics Workspace(항목 ⑨)도 조회할 수 있도록 두 리소스 그룹(또는 상위 구독)을 모두 포함합니다.
3. **`③` 연결된 리소스 목록에서 `Agent Access: Verified` 상태 확인**:
   - `aks-priv-01`, `aks-priv-02`, `aks-priv-03`, `SRE-AKS-Management`, `vnet-sre-aks-hub`, `vnet-sre-spoke-03`가 모두 정상 인식되는지 확인합니다.

---

## Step 06. `Workspace configuration > Networking`에서 VNet 연결 및 `[ ] AKS API server (*.azmk8s.io)` 우회 체크 해제

> **주의사항**:
> SRE Agent에 VNet(`snet-sre-agent-sandbox`)을 연결하더라도, 하단 `Common Azure endpoints`에서 **`[✓] AKS API server (*.azmk8s.io)`** 가 기본 체크되어 있으면 에이전트가 `kubectl` 패킷을 사용자 VNet 대신 공용 인프라망으로 우회시킵니다. 이 체크박스를 반드시 해제합니다.

### 화면 이동 및 입력 순서 (`①` ➔ `⑤`)
1. **`①` 좌측 하단 `Settings > Workspace configuration` 클릭 후 상단 `Networking` 탭 선택**
2. **`②` `Egress mode`에서 세 번째 카드인 `Azure VNet (Private egress via your VNet)` 선택**
3. **`③` `Virtual network`: `vnet-sre-event-lab`, `Subnet`: `snet-sre-agent-sandbox` 선택 및 `[✓] Use VNet's private DNS for resolution` 체크**:
   - `Test connection` 버튼을 눌러 **`● Verified`** 상태를 확인합니다.
4. **`④` `Common Azure endpoints`에서 `[ ] AKS API server (*.azmk8s.io)` 체크 해제**:
   - 체크를 해제하면 모든 `RunKubectlReadCommand` 및 Python 소켓 호출이 `10.42.4.x` 사설 IP를 통해 사용자 VNet 및 vWAN 방화벽을 경유해 Private AKS Private Endpoint(`10.52.11.4`, `10.52.12.4`, `10.60.3.4`)로 전달됩니다.
   - 모든 트래픽이 VNet 방화벽을 경유해야 하는 정책 환경에서는 `Log Analytics`, `Azure Managed Grafana` 항목도 함께 체크 해제할 수 있습니다.
5. **`⑤` 하단 `Save` 버튼 클릭 후, `Trusted CA certificates`에 Private AKS 클러스터 CA 인증서 등록 (`*.azmk8s.io`)**:
   - 사설 AKS API 서버(`*.privatelink.eastus2.azmk8s.io`)는 클러스터별 자체 서명(Self-signed) Kubernetes Root CA 인증서(`CN=ca`)를 사용합니다.
   - Python 도구 샌드박스에서 VNet 경유로 K8s REST API(`https://<privateFQDN>/api/v1/pods` 등)를 직접 호출할 때 SRE Agent 이그레스 프록시가 TLS 인증서를 신뢰하도록, 구독 내 전체 AKS 클러스터를 동적으로 조회하여 `hostPattern: "*.azmk8s.io"`에 CA 인증서를 일괄 등록합니다:
   ```bash
   python3 -c '
   import base64, json, subprocess
   sub = subprocess.check_output(["az", "account", "show", "--query", "id", "-o", "tsv"], text=True).strip()
   ep = "https://sre-aks-fleet-agent--50e381d3.e01924b8.koreacentral.azuresre.ai"
   tok = subprocess.check_output(["az", "account", "get-access-token", "--resource", "https://azuresre.ai", "--query", "accessToken", "-o", "tsv"], text=True).strip()
   clusters = json.loads(subprocess.check_output(["az", "aks", "list", "--subscription", sub, "--query", "[].{rg:resourceGroup, name:name}", "-o", "json"], text=True))
   certs = []
   for item in clusters:
       u = f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{item[\"rg\"]}/providers/Microsoft.ContainerService/managedClusters/{item[\"name\"]}/listClusterUserCredential?api-version=2024-09-01"
       raw = subprocess.check_output(["az", "rest", "-m", "POST", "--url", u, "--query", "kubeconfigs[0].value", "-o", "tsv"], text=True).strip()
       for line in base64.b64decode(raw).decode().splitlines():
           if "certificate-authority-data:" in line:
               certs.append(base64.b64decode(line.split(":", 1)[1].strip()).decode())
   subprocess.run(["curl", "-sS", "-X", "PUT", "-H", f"Authorization: Bearer {tok}", "-H", "Content-Type: application/json", "-d", json.dumps({"hostPattern": "*.azmk8s.io", "certificates": certs}), f"{ep}/api/v2/extendedAgent/workspace/trustedCaCertificates"], check=True)
   '
   ```

---

## Step 07. `Knowledge sources`에 정책 · 공지 메일 템플릿 문서 3종 업로드

### 화면 이동 및 입력 순서 (`①` ➔ `④`)
1. **`①` 좌측 사이드바 `Build & setup > Context > Knowledge sources` 클릭**
2. **`②` 상단 `+ Upload files` 클릭**:
   - 로컬 워크스페이스의 `agent/knowledge/` 폴더에 있는 아래 3개 마크다운 파일을 업로드합니다.
3. **`③` 업로드할 지식 문서 3종 확인**:
   - [`./agent/knowledge/aks-eol-notice-template-and-history.md`](./agent/knowledge/aks-eol-notice-template-and-history.md): **고객 발송용 5개 섹션 공지 메일 마크다운(`.md`) 표준 템플릿** (`[직접 입력: ...]` 링크 자리표시자, 대상 버전 클러스터 전용 필터링 규칙, 섹션 `5-1. SRE 에이전트 사전 점검 상세 결과` 표 양식 정의)
   - [`./agent/knowledge/aks-9point-upgrade-preflight-policy.md`](./agent/knowledge/aks-9point-upgrade-preflight-policy.md): **AKS 업그레이드 9대 사전 점검 항목 정의 · 배점(100점) · 판정 기준(`READY`/`CONDITIONAL`/`BLOCKED`) 및 선행 조치 가이드**
   - [`./agent/knowledge/aks-dataplane-inspection-sop.md`](./agent/knowledge/aks-dataplane-inspection-sop.md): **사설 AKS 데이터플레인 조회 SOP** (`3건 이하 단건 조회 시 RunKubectlReadCommand` vs `4건 이상 다중 리소스 조회 시 DefaultAzureCredential 기반 Python K8s REST API 일괄 호출 표준 코드 예시`)
4. **`④` `Indexing Status`가 `● Indexed (Ready)`로 바뀌었는지 확인**:
   - `Indexed` 상태가 되면 서브에이전트가 `SearchMemory` 도구로 RAG 검색을 수행할 수 있습니다.

---

# Phase 4. MCP 커넥터 · 핵심 Python 도구(2종) · 스킬 · 고급 권한 · 서브에이전트 구성

---

## Step 08. `Connectors`에서 MS Learn 원격 MCP(`mslearn-mcp`) · Azure MCP(`azure-arg-mcp` / `npx`) · Confluence OAuth 커넥터 등록

### 화면 이동 및 입력 순서 (`①` ➔ `⑥`)
1. **`①` 좌측 사이드바 `Build & setup > Extensions > Connectors` 클릭**
2. **`②` 상단 `+ Add connector` 클릭**
3. **`③` [A. 원격 MCP 커넥터] `mslearn-mcp` 등록 (`MCP Server` ➔ `Streamable-HTTP`)**:
   - **이름 (`Name *`)**: `mslearn-mcp`
   - **연결 형식 (`Connection Type *`)**: `Streamable-HTTP`
   - **URL**: `https://learn.microsoft.com/api/mcp`
   - **Authentication**: `None` (또는 빈 Custom headers)
   - 저장하면 `microsoft_docs_search`, `microsoft_docs_fetch`, `microsoft_code_sample_search` 3개 도구가 자동 검색(`Connected`)됩니다.
4. **`④` [B. 로컬 Stdio MCP 커넥터] 공식 Azure MCP 서버 (`azure-arg-mcp` / `npx`) 등록 (Live Report 0 AAU 실시간 ARG 조회용)**:
   - 상단 `+ Add connector` ➔ `MCP Server` 선택 후 아래 표와 같이 **`명령 *`과 `인수`를 반드시 분리**하여 입력합니다:
   - *(VNet 거버넌스 준수: `Workspace configuration > Networking`의 `Package registries > npm`은 체크 해제 상태로 유지하여 VNet 우회를 막고, `Step 01-B`의 vWAN 방화벽 애플리케이션 규칙 `allow-sre-app-rules`에 허용된 `registry.npmjs.org`를 통해 VNet 경유로 패키지를 받아 실행합니다.)*

   | 필드명 (포털 표시명) | 입력 / 선택할 값 | 주의사항 |
   |---|---|---|
   | **이름 (`Name *`)** | **`azure-arg-mcp`** | Live Report 및 에이전트에서 참조할 커넥터 ID |
   | **연결 형식 (`Connection Type *`)** | **`Stdio`** (`로컬 명령 또는 실행 파일 실행`) | 에이전트 컨테이너 내부 프로세스로 구동 |
   | **명령 (`Command *`)** | **`npx`** | ⚠️ 띄어쓰기 없이 실행 파일명 **`npx`** 한 단어만 입력 |
   | **인수 (`Arguments`)** | **`+ 추가`** 버튼을 눌러 **한 줄에 하나씩 총 4줄** 입력:<br>1) **`-y`**<br>2) **`@azure/mcp@latest`**<br>3) **`server`**<br>4) **`start`** | 한 칸에 몰아서 넣지 않고 4개 행으로 분리 입력 |
   | **환경 변수 (`Environment Variables`)** | **`+ 추가`** 버튼을 눌러 **아래 2개 키-값 필수 입력** (미입력 시 `401 CredentialUnavailableException` 발생):<br>1) 키: **`AZURE_TOKEN_CREDENTIALS`** / 값: **`prod`**<br>2) 키: **`AZURE_CLIENT_ID`** / 값: **`66e4b2c7-652e-41fb-bb5f-879d2656c22a`** *(에이전트 UAMI `sre-aks-fleet-agent-...`의 클라이언트 ID)* | `@azure/mcp`는 기본값이 로컬 개발자 인증(`dev`)이므로, 반드시 `AZURE_TOKEN_CREDENTIALS=prod`와 UAMI의 `AZURE_CLIENT_ID`를 지정해야 관리 ID로 인증함 |
   | **관리 ID (`Managed Identity`)** | **`sre-aks-fleet-agent-...` (에이전트 UAMI 선택)** | 에이전트 UAMI의 `독자(Reader)` 권한으로 ARG/ARM 조회 |
   | **활성화할 MCP 도구 선택**<br>(`MCP Tools` 선택 단계) | 전체 73개 중 아래 **3개만 체크**:<br>• **`azure-arg-mcp_arm`** *(Azure Resource Graph KQL 실행기 포함 — 필수!)*<br>• **`azure-arg-mcp_aks`** *(AKS 클러스터·노드풀 상세 조회)*<br>• **`azure-arg-mcp_subscription_list`** *(구독 목록 조회)* | 80개 도구 제한을 넘지 않도록 필요한 3개만 선택 |

5. **`⑤` [C. Managed Connectors] 목록에서 `Confluence` 아이콘 클릭**:
   - 사내 Confluence에 작성된 공지문 마스터 양식 및 사전 체크리스트 페이지를 실시간으로 읽어오기 위해 내장 Confluence 커넥터를 선택합니다.
6. **`⑥` `Sign in with Atlassian (OAuth)` 클릭 후 권한 동의**:
   - 연결이 완료되면 5개 읽기 도구(`Get spaces`, `Get pages within a space`, `Get pages`, `Get page content and metadata`, `Get resources associated to the current user`)가 활성화됩니다.

---

## Step 09. `Agent Canvas > Toolbox` 핵심 Python 도구 2종 등록

| 단계 | 수행 역할 | 담당 SRE Agent 기능 | 핵심 포인트 |
|---|---|---|---|
| **0. 상시 인벤토리 관제** | 12컬럼 AKS 인벤토리 & 버전 현황판 | 📊 **Live Report** + **`azure-arg-mcp` (`npx @azure/mcp`)** | LLM(AAU) 호출 없이 공식 Azure MCP가 ARG KQL로 실시간 렌더링 |
| **1. EOS 버전 및 대상 클러스터 필터링** | MS Learn 릴리스 일정 파싱 + 업그레이드 대상 클러스터 추출 | 🐍 **핵심 Python 도구 1**<br>`check-aks-eos-release-calendar` | `months_ahead=4` 기준 각 클러스터의 `SupportPlan` 종료일(`Standard` vs `LTS`)을 대조해 대상 클러스터만 `targetUpgradeClusters`로 추출 |
| **2. 클러스터 9대 사전 점검** | 대상 클러스터에 대해 9대 항목(전체 `ALL` 또는 선택 `1,3,4` / `7,8,9`) 실시간 채점 | 🐍 **핵심 Python 도구 2**<br>`evaluate-aks-upgrade-preflight` | ARM API + VNet 경유 사설 K8s API를 1회 호출로 점검하여 항목별 `PASS`/`WARN`/`FAIL` 및 특이사항 반환 |
| **3. 버전간 주요 변경사항 수집** | 마이너 버전 구간별 주요 변경사항 실시간 조사 | 🔌 **원격 MCP 커넥터**<br>`mslearn-mcp` | MS Learn 공식 문서에서 서비스 담당자 확인이 필요한 변경사항 발췌 |
| **4. 최종 공지 메일(`.md`) 생성** | Step 07 지식 베이스의 메일 템플릿에 대상 클러스터 + 9대 사전 점검 결과표 + 주요 변경사항을 결합해 `.md` 작성 | 🧠 **Knowledge Memory**<br>+ 📋 **Skill (`Step 10`)** | 에이전트가 지식 문서 양식을 참조해 `./aks-upgrade-notice.md` 파일 저장 및 다운로드 링크 출력 |
| **5. 차단 요인 반자동 조치** | 사전 점검 `FAIL` 항목(차단 PDB, VNet 권한 등) 승인 조치 | 🛡️ **내장 `kubectl` / `az`**<br>+ **`Advanced permissions (Ask)`** | `Allow` / `Ask` / `Deny` 패턴 매칭으로 조회와 관리자 승인 기반 조치 수행 |

> **참고**: 좌측 `Extensions > Tools`는 도구 카탈로그 조회 화면입니다. Python 코드(`def main`)를 입력·수정하고 `Test playground`에서 실행하려면 **`Build & setup > Workflows > Agent Canvas` ➔ `Toolbox` ➔ `+ Create > Tool` (또는 도구 옆 `✎ Edit`)** 경로를 사용합니다.

### 화면 이동 및 입력 순서 (`①` ➔ `⑤`)
1. **`①` 좌측 사이드바 `Build & setup > Workflows > Agent Canvas` 클릭**
2. **`②` 상단 `+ Create > Tool` 클릭 (또는 좌측 `Toolbox` 패널 열기)**
3. **`③` 아래 핵심 Python 도구 2종(+ 선택 네트워크 진단 도구 1종) 등록**:
   - **핵심 도구 1 (`check-aks-eos-release-calendar`)**: MS Learn 공식 AKS 릴리스 일정 실시간 파서 및 `SupportPlan` 기준 업그레이드 대상 클러스터 필터링 (`targetUpgradeClusters`)
   - **핵심 도구 2 (`evaluate-aks-upgrade-preflight`)**: AKS 업그레이드 9대 사전 체크리스트 실시간 평가기 (`check_items="ALL"` 전체 점검 및 `"1,3,4"` / `"7,8,9"` 부분 선택 점검 지원)
   - *(선택) 도구 3 (`verify-multihub-firewall-udr-route`)*: 다중 허브 방화벽 경유 Private AKS TCP 443 & `/livez` 네트워크 도달성 검증기
4. **`④` `Code` 탭에서 아래 Python 코드(`def main(...) -> dict:`) 붙여넣기**
5. **`⑤` `Test playground` (`플레이그라운드 테스트`) 탭에서 각 도구의 입력값으로 검증**

---

### 등록할 핵심 Python 도구 코드 원문 (복사·붙여넣기용)

#### 핵심 도구 1: `check-aks-eos-release-calendar` (MS Learn 공식 릴리스 일정 실시간 파서 + 업그레이드 대상 클러스터 필터링)
- **Name**: `check-aks-eos-release-calendar`
- **Description**: `Dynamically fetches and parses the official Microsoft Learn AKS Kubernetes Release Calendar, queries live Azure Resource Graph (ARG) clusters and live ARM regional patch versions, and filters ONLY the targetUpgradeClusters matching the target/expiring Kubernetes minor version (e.g. 1.34) while excluding other versions.`
- **Parameters** (코드 붙여넣기 시 자동 인식됨):
  - `months_ahead` (`integer`, required: `false`, default: `2`, description: `Months ahead to check for EOS (default 2)`)
  - `target_minor_version` (`string`, required: `false`, default: `""`, description: `Optional specific K8s minor version to filter target clusters (e.g. '1.34'); if omitted, automatically uses the expiring Standard version(s)`)
  - `support_plan` (`string`, required: `false`, default: `ALL`, description: `ALL, KubernetesOfficial, or AKSLongTermSupport`)
  - `reference_date` (`string`, required: `false`, default: `""`, description: `Optional ISO date (YYYY-MM-DD)`)
```python
import calendar
import datetime
import json
import re
import requests
from azure.identity import DefaultAzureCredential

_orig_dumps = json.dumps
json.dumps = lambda obj, **kw: _orig_dumps(obj, **{**kw, "ensure_ascii": False})

def parse_eol_date(text: str):
    s = (text or "").strip()
    if not s or "TBD" in s.upper():
        return None
    nums = [int(x) for x in re.findall(r"\d+", s)]
    if len(nums) >= 2 and 2020 <= nums[0] <= 2035 and 1 <= nums[1] <= 12:
        y, mo = nums[0], nums[1]
        d = nums[2] if (len(nums) >= 3 and 1 <= nums[2] <= 31) else calendar.monthrange(y, mo)[1]
        return datetime.date(y, mo, d).isoformat()
    return None

def eval_status(eol_iso: str, ref_d: datetime.date, months_ahead: int):
    if not eol_iso:
        return None, "TBD"
    # 월 단위로만 계산 (예: 2026-11 기준 4개월 조회 시 4개월 뒤인 2027-03 말일까지 포함)
    cal_diff = (int(eol_iso[:4]) - ref_d.year) * 12 + (int(eol_iso[5:7]) - ref_d.month)
    if cal_diff < 0:
        st = "ALREADY_EOS"
    elif 0 <= cal_diff <= months_ahead:
        st = f"EXPIRING_WITHIN_{months_ahead}M"
    else:
        st = "SUPPORTED"
    return cal_diff, st

def main(months_ahead: int = 4, target_minor_version: str = "", support_plan: str = "ALL", reference_date: str = "") -> dict:
    months_ahead = int(months_ahead if months_ahead is not None else 4)
    ref_d = datetime.date.fromisoformat(reference_date.strip()) if (reference_date and reference_date.strip()) else datetime.date.today()

    # 1. MS Learn 공식 AKS 릴리스 일정 웹페이지 실시간 스크래핑 (표 0: Standard, 표 1: LTS)
    url = "https://learn.microsoft.com/ko-kr/azure/aks/supported-kubernetes-versions"
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.encoding = "utf-8"
    tables = re.findall(r"<table.*?</table>", resp.text, re.S)
    cal = {}
    if len(tables) >= 2:
        for row in re.findall(r"<tr.*?</tr>", tables[0], re.S)[1:]:
            c = [re.sub(r"<.*?>", "", x).strip() for x in re.findall(r"<t[dh].*?>(.*?)</t[dh]>", row, re.S)]
            if len(c) >= 5 and re.match(r"^1\.\d+$", c[0]):
                cal[c[0]] = {"minorVersion": c[0], "aksGa": c[3], "standardEolDate": parse_eol_date(c[4]), "ltsEolDate": None}
        for row in re.findall(r"<tr.*?</tr>", tables[1], re.S)[1:]:
            c = [re.sub(r"<.*?>", "", x).strip() for x in re.findall(r"<t[dh].*?>(.*?)</t[dh]>", row, re.S)]
            if len(c) >= 6 and re.match(r"^1\.\d+$", c[0]):
                entry = cal.setdefault(c[0], {"minorVersion": c[0], "aksGa": c[3], "standardEolDate": parse_eol_date(c[4])})
                entry["ltsEolDate"] = parse_eol_date(c[5])

    # 2. 실시간 Azure Resource Graph (ARG) 클러스터 인벤토리 및 ARM 리전별 패치 버전 조회
    cred = DefaultAzureCredential()
    arm_tok = cred.get_token("https://management.azure.com/.default").token
    hdrs = {"Authorization": f"Bearer {arm_tok}", "Content-Type": "application/json"}
    arg_kql = (
        "resources | where type =~ 'microsoft.containerservice/managedclusters' "
        "| extend mgmtName = coalesce(tostring(tags['mgmtName']), 'ENT_Workloads'), "
        "k8sVersion = tostring(properties.currentKubernetesVersion), "
        "SupportPlan = coalesce(tostring(tags['SupportPlan']), tostring(properties.supportPlan), 'KubernetesOfficial'), "
        "ServiceName = coalesce(tostring(tags['ServiceName']), '-'), "
        "ServiceCode = coalesce(tostring(tags['ServiceCode']), '-'), "
        "ServiceGrade = coalesce(tostring(tags['ServiceGrade']), '-') "
        "| project mgmtName, Subscription=subscriptionId, Cluster=name, location, k8sVersion, SupportPlan, ServiceName, ServiceCode, ServiceGrade "
        "| order by k8sVersion asc, Cluster asc"
    )
    clusters = requests.post(
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01",
        headers=hdrs, json={"query": arg_kql}, timeout=10
    ).json().get("data", [])

    patches = {}
    if clusters:
        sub_id, loc = clusters[0]["Subscription"], clusters[0]["location"]
        vurl = f"https://management.azure.com/subscriptions/{sub_id}/providers/Microsoft.ContainerService/locations/{loc}/kubernetesVersions?api-version=2024-09-01"
        for item in requests.get(vurl, headers=hdrs, timeout=8).json().get("values", []):
            mv = item.get("version")
            pkeys = list((item.get("patchVersions") or {}).keys())
            if mv and pkeys:
                patches[mv] = sorted(pkeys, key=lambda s: [int(x) for x in re.findall(r"\d+", s)])[-1]

    exp_std, exp_lts, rows = [], [], []
    for mv in sorted(cal.keys(), key=lambda x: [int(n) for n in x.split(".")]):
        info = cal[mv]
        minor_num = int(mv.split(".")[1]) + 1
        next_mv = f"1.{minor_num}"
        goal_mv = f"1.{minor_num + 1}"
        next_target = patches.get(next_mv, f"{next_mv}.1")
        goal_target = patches.get(goal_mv, f"{goal_mv}.1")
        goal_eol = (cal.get(goal_mv) or {}).get("standardEolDate")
        sd, sst = eval_status(info.get("standardEolDate"), ref_d, months_ahead)
        ld, lst = eval_status(info.get("ltsEolDate"), ref_d, months_ahead)
        if (sd is not None and sd >= -3) or (ld is not None and ld >= -3):
            rows.append({"v": mv, "next": next_target, "goal": goal_target, "goalEol": goal_eol, "stdEol": info.get("standardEolDate"), "stdMonths": sd, "stdStatus": sst, "ltsEol": info.get("ltsEolDate"), "ltsMonths": ld, "ltsStatus": lst})
        if sst.startswith("EXPIRING"):
            exp_std.append({"version": mv, "eolDate": info.get("standardEolDate"), "monthsRemaining": sd, "nextTarget": next_target, "goalTarget": goal_target, "goalEolDate": goal_eol})
        if lst.startswith("EXPIRING"):
            exp_lts.append({"version": mv, "eolDate": info.get("ltsEolDate"), "monthsRemaining": ld, "nextTarget": next_target})

    plan_filter = (support_plan or "ALL").strip()
    explicit_mv = target_minor_version.strip().lstrip("v") if (target_minor_version and target_minor_version.strip()) else ""

    target_clusters = []
    excluded_clusters = []
    for c in clusters:
        if plan_filter not in ("ALL", c["SupportPlan"]):
            continue
        c_mv = ".".join(c["k8sVersion"].split(".")[:2])
        c_info = cal.get(c_mv, {})
        c_num = int(c_mv.split(".")[1]) if "." in c_mv else 0
        mid_mv, goal_mv = f"1.{c_num + 1}", f"1.{c_num + 2}"
        mid_p, goal_p = patches.get(mid_mv, f"{mid_mv}.1"), patches.get(goal_mv, f"{goal_mv}.1")
        std_eol = c_info.get("standardEolDate")
        lts_eol = c_info.get("ltsEolDate")
        # 핵심: Standard 클러스터는 Standard 종료월 말일 기준, LTS 클러스터는 LTS 종료월 말일 기준으로 월 단위 판정
        eff_eol = lts_eol if c["SupportPlan"] == "AKSLongTermSupport" else std_eol
        eff_months, eff_st = eval_status(eff_eol, ref_d, months_ahead)

        is_expiring = eff_st.startswith("EXPIRING") or eff_st == "ALREADY_EOS"
        is_target = (c_mv == explicit_mv and is_expiring) if explicit_mv else is_expiring

        item = {
            "mgmtName": c["mgmtName"],
            "Subscription": c["Subscription"],
            "Cluster": c["Cluster"],
            "k8sVersion": c["k8sVersion"],
            "SupportPlan": c["SupportPlan"],
            "ServiceName": c["ServiceName"],
            "ServiceCode": c["ServiceCode"],
            "ServiceGrade": c["ServiceGrade"],
            "effectiveEolDate": eff_eol,
            "effectiveMonthsRemaining": eff_months,
            "effectiveStatus": eff_st,
            "sequentialUpgradePath": f"v{c['k8sVersion']} -> v{mid_p} -> v{goal_p}",
            "goalVersion": f"v{goal_p}",
            "goalVersionEolDate": (cal.get(goal_mv) or {}).get("standardEolDate")
        }
        if is_target:
            target_clusters.append(item)
        else:
            excluded_clusters.append({
                "Cluster": c["Cluster"],
                "k8sVersion": c["k8sVersion"],
                "SupportPlan": c["SupportPlan"],
                "effectiveEolDate": eff_eol,
                "effectiveMonthsRemaining": eff_months,
                "effectiveStatus": eff_st,
                "excludeReason": "LTS 지원 종료월 미도래" if c["SupportPlan"] == "AKSLongTermSupport" else "Standard 지원 종료월 여유"
            })

    active_target_mvs = sorted(list({".".join(x["k8sVersion"].split(".")[:2]) for x in target_clusters}))
    return {
        "officialSourceUrl": f"{url}#aks-kubernetes-release-calendar",
        "referenceDate": ref_d.isoformat(),
        "requestedMonthsAhead": months_ahead,
        "targetMinorVersionsWithClusters": active_target_mvs,
        "expiringStandard": exp_std if plan_filter in ("ALL", "KubernetesOfficial") else [],
        "expiringLts": exp_lts if plan_filter in ("ALL", "AKSLongTermSupport") else [],
        "targetUpgradeClusters": target_clusters,
        "excludedClusters": excluded_clusters,
        "releaseCalendar": rows
    }
```
- **플레이그라운드 테스트(`플레이그라운드 테스트` 탭) 입력값별 기대 결과**:
  | 테스트 시나리오 | `months_ahead` | `target_minor_version` | `support_plan` | `reference_date` | 기대 결과 (`테스트 결과` 핵심 확인 포인트 — 클러스터별 SupportPlan 종료일 기준 필터링) |
  |---|---|---|---|---|---|
  | **① 4개월 기준 EOS 대상 클러스터 추출 (기본)** | `4` *(또는 빈칸)* | *(빈칸)* | `ALL` | `2026-11-10` | • **`targetMinorVersionsWithClusters`: `["1.35"]`**<br>• **`targetUpgradeClusters`**: **`aks-priv-02` (`1.35.9`, `KubernetesOfficial`, Standard EOL `2027-03-31`) 딱 1대만 반환**<br>• **`excludedClusters`**: `aks-priv-03`(`1.34.12`이지만 `AKSLongTermSupport`라 LTS 종료일 `2027-11-30` 미도래로 자동 제외) 및 `aks-priv-01`(`1.36.4`, Standard 종료일 `2027-06-30` 여유로 제외) |
  | **② LTS 종료 시점 도래 시(`2027-08-01`) 조회** | `4` | *(빈칸)* | `ALL` | `2027-08-01` | • LTS 종료일(`2027-11-30`)이 4개월 이내로 들어온 시점에는 `aks-priv-03` (`1.34.12`, `AKSLongTermSupport`)이 `targetUpgradeClusters`로 정확히 조회됨 |

---

#### 핵심 도구 2: `evaluate-aks-upgrade-preflight` (실시간 ARM + VNet 경유 Private AKS K8s REST API 9대 사전 체크리스트 평가기)
- **Name**: `evaluate-aks-upgrade-preflight`
- **Description**: `Evaluates a Private AKS cluster in real time against the 9-Point AKS Upgrade Pre-flight Checklist by querying live Azure ARM and live Private AKS Kubernetes REST API over the VNet. Supports checking all 9 items by default (check_items='ALL') or a specific subset of items (e.g. check_items='1,3,4' or '7,8,9').`
- **Parameters**:
  - `cluster_name` (`string`, required: `true`, description: `Target AKS cluster name (e.g. aks-priv-01, aks-priv-02, aks-priv-03)`)
  - `check_items` (`string`, required: `false`, default: `ALL`, description: `'ALL' (default, checks all 1~9 items) or comma-separated item numbers to check selectively (e.g. '1,3,4' or '7,8,9')`)
```python
import ipaddress
import json
import re
import requests
import urllib3
from azure.identity import DefaultAzureCredential

urllib3.disable_warnings()
_orig_dumps = json.dumps
json.dumps = lambda obj, **kw: _orig_dumps(obj, **{**kw, "ensure_ascii": False})
SYS_NS = {"kube-system", "kube-public", "kube-node-lease", "gatekeeper-system", "calico-system", "tigera-operator", "azureserviceoperator-system"}

def parse_cpu_m(val: str) -> int:
    s = str(val or "0").strip()
    return int(float(s[:-1])) if s.endswith("m") else int(float(s) * 1000)

def main(cluster_name: str, check_items: str = "ALL") -> dict:
    raw_sel = (check_items or "ALL").strip().upper()
    selected = set(range(1, 10)) if (not raw_sel or raw_sel == "ALL") else {int(x) for x in re.findall(r"[1-9]", raw_sel)}
    if not selected:
        selected = set(range(1, 10))

    cred = DefaultAzureCredential()
    arm_tok = cred.get_token("https://management.azure.com/.default").token
    k8s_tok = cred.get_token("6dae42f8-4368-4678-94ff-3960e28e3630/.default").token
    arm_hdr = {"Authorization": f"Bearer {arm_tok}", "Content-Type": "application/json"}
    k8s_hdr = {"Authorization": f"Bearer {k8s_tok}"}

    q = f"resources | where type =~ 'microsoft.containerservice/managedclusters' and name =~ '{cluster_name}' | project id, name, rg=resourceGroup, sub=subscriptionId, loc=location"
    rows = requests.post(
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01",
        headers=arm_hdr, json={"query": q}, timeout=10
    ).json().get("data", [])
    if not rows:
        return {"error": f"Cluster {cluster_name} not found in ARG"}
    c_meta = rows[0]
    aks = requests.get(f"https://management.azure.com{c_meta['id']}?api-version=2024-09-01", headers=arm_hdr, timeout=10).json()
    props = aks.get("properties", {})
    cv = props.get("currentKubernetesVersion", "")
    fqdn = props.get("privateFQDN", "")
    ap = (props.get("agentPoolProfiles") or [{}])[0]
    subnet_id = ap.get("vnetSubnetID", "")
    node_count = sum(int(p.get("count", 0)) for p in (props.get("agentPoolProfiles") or []))
    cni_overlay = (props.get("networkProfile") or {}).get("networkPluginMode") == "overlay"

    c_mv = ".".join(cv.split(".")[:2])
    next_num = int(c_mv.split(".")[1]) + 1 if "." in c_mv else 0
    next_mv = f"1.{next_num}"
    vurl = f"https://management.azure.com/subscriptions/{c_meta['sub']}/providers/Microsoft.ContainerService/locations/{c_meta['loc']}/kubernetesVersions?api-version=2024-09-01"
    tv = f"{next_mv}.0"
    for vitem in requests.get(vurl, headers=arm_hdr, timeout=8).json().get("values", []):
        if vitem.get("version") == next_mv and vitem.get("patchVersions"):
            tv = sorted(vitem["patchVersions"].keys(), key=lambda s: [int(x) for x in re.findall(r"\d+", s)])[-1]

    score = 100
    remarks, c9 = [], {}

    # 항목 ①~⑥: 선택된 경우에만 VNet 경유 Private AKS Kubernetes REST API 실시간 조회
    if selected & {1, 2, 3, 4, 5, 6}:
        nodes = requests.get(f"https://{fqdn}/api/v1/nodes", headers=k8s_hdr, verify=False, timeout=8).json().get("items", []) if (3 in selected) else []
        pods = requests.get(f"https://{fqdn}/api/v1/pods", headers=k8s_hdr, verify=False, timeout=8).json().get("items", []) if (selected & {1, 2, 3}) else []
        deploys = requests.get(f"https://{fqdn}/apis/apps/v1/deployments", headers=k8s_hdr, verify=False, timeout=8).json().get("items", []) if (selected & {1, 5, 6}) else []
        pdbs = requests.get(f"https://{fqdn}/apis/policy/v1/poddisruptionbudgets", headers=k8s_hdr, verify=False, timeout=8).json().get("items", []) if (4 in selected) else []
        ingresses = requests.get(f"https://{fqdn}/apis/networking.k8s.io/v1/ingresses", headers=k8s_hdr, verify=False, timeout=8).json().get("items", []) if (5 in selected) else []

        max_alloc_cpu = max([parse_cpu_m(n.get("status", {}).get("allocatable", {}).get("cpu", "2")) for n in nodes] or [2000])
        singles, naked_pods, unhealthy_pods, pending_issues, storage_issues, grace_issues = [], [], [], [], [], []
        ing_ver = "미설치"
        snippet_used = False

        for d in deploys:
            ns, dname = d["metadata"]["namespace"], d["metadata"]["name"]
            if ns == "ingress-nginx":
                lbl_v = d["metadata"].get("labels", {}).get("app.kubernetes.io/version")
                img = ((d.get("spec", {}).get("template", {}).get("spec", {}).get("containers") or [{}])[0]).get("image", "")
                ing_ver = lbl_v or (img.split(":")[-1] if ":" in img else "installed")
                continue
            if ns in SYS_NS:
                continue
            rep = int(d.get("spec", {}).get("replicas", 1))
            if rep <= 1 and dname not in ("batch-settlement-pending", "push-webhook-relay"):
                singles.append(f"{ns}/{dname}(replicas={rep})")
            for c in d.get("spec", {}).get("template", {}).get("spec", {}).get("containers", []):
                has_probe = bool(c.get("readinessProbe") or c.get("livenessProbe"))
                has_prestop = bool(((c.get("lifecycle") or {}).get("preStop")))
                if not has_probe or not has_prestop:
                    grace_issues.append(f"{ns}/{dname}")

        for p in pods:
            ns, pname = p["metadata"]["namespace"], p["metadata"]["name"]
            if ns in SYS_NS or ns == "ingress-nginx":
                continue
            phase = p.get("status", {}).get("phase", "")
            if phase == "Succeeded":
                continue
            if not p["metadata"].get("ownerReferences"):
                naked_pods.append(f"{ns}/{pname}")
            for v in p.get("spec", {}).get("volumes", []):
                if "hostPath" in v:
                    hp = v["hostPath"].get("path")
                    storage_issues.append(f"{ns}/{pname}:hostPath({hp})")
                elif "emptyDir" in v and not v.get("name", "").startswith("kube-api-access"):
                    vn = v.get("name")
                    storage_issues.append(f"{ns}/{pname}:emptyDir({vn})")
            req_cpu = sum(parse_cpu_m(c.get("resources", {}).get("requests", {}).get("cpu", "0")) for c in p.get("spec", {}).get("containers", []))
            if (phase == "Pending" and not p.get("spec", {}).get("nodeName")) or req_cpu > max_alloc_cpu:
                pending_issues.append(f"{ns}/{pname}(Unschedulable,reqCpu={req_cpu}m)")
            for cs in p.get("status", {}).get("containerStatuses", []):
                w_reason = ((cs.get("state") or {}).get("waiting") or {}).get("reason", "")
                if w_reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                    unhealthy_pods.append(f"{ns}/{pname}({w_reason})")

        if 1 in selected:
            if singles or naked_pods or unhealthy_pods:
                score -= 10
                detail = ", ".join(dict.fromkeys(singles + naked_pods + unhealthy_pods))
                c9["1_podHaConfig"] = f"FAIL ({detail})"
                remarks.append(f"[①Pod고가용성] {detail}")
            else:
                c9["1_podHaConfig"] = "PASS (replicas>=2, Naked/비정상 파드 0건)"

        if 2 in selected:
            if storage_issues:
                score -= 10
                detail = ", ".join(dict.fromkeys(storage_issues))
                c9["2_localStoragePv"] = f"WARN ({detail})"
                remarks.append(f"[②LocalStorage] {detail}")
            else:
                c9["2_localStoragePv"] = "PASS (HostPath/emptyDir 미사용)"

        if 3 in selected:
            if pending_issues:
                score -= 15
                detail = ", ".join(dict.fromkeys(pending_issues))
                c9["3_schedulingConstraints"] = f"FAIL ({detail})"
                remarks.append(f"[③스케줄링제약] {detail}")
            else:
                c9["3_schedulingConstraints"] = "PASS (Pending 및 리소스 초과 파드 0건)"

        if 4 in selected:
            blocking_pdbs = [
                f"{x['metadata']['namespace']}/{x['metadata']['name']}"
                for x in pdbs
                if x["metadata"]["namespace"] not in SYS_NS and int(x.get("status", {}).get("disruptionsAllowed", 1)) == 0
            ]
            if blocking_pdbs:
                score -= 15
                detail = ", ".join(blocking_pdbs)
                c9["4_pdbConfig"] = f"FAIL (AllowedDisruptions=0: {detail})"
                remarks.append(f"[④PDB차단] AllowedDisruptions=0 ({detail})")
            else:
                c9["4_pdbConfig"] = "PASS (차단 PDB 0건)"

        if 5 in selected:
            for ing in ingresses:
                ann = ing.get("metadata", {}).get("annotations") or {}
                if any("snippet" in k for k in ann.keys()):
                    snippet_used = True
            if "1.9" in ing_ver or snippet_used:
                score -= 10
                c9["5_apiAndAddonCompat"] = f"FAIL (ingress-nginx {ing_ver}, snippet={snippet_used})"
                remarks.append(f"[⑤API/애드온] ingress-nginx {ing_ver} 업그레이드 및 snippet 제거 필요")
            else:
                c9["5_apiAndAddonCompat"] = f"PASS (ingress-nginx {ing_ver} 호환)"

        if 6 in selected:
            if grace_issues:
                score -= 10
                detail = ", ".join(dict.fromkeys(grace_issues))
                c9["6_gracefulShutdown"] = f"WARN (Probe/preStop 미설정: {detail})"
                remarks.append(f"[⑥GracefulShutdown] {detail} Probe/preStop 미설정")
            else:
                c9["6_gracefulShutdown"] = "PASS (Probe 및 preStop 정상)"

    # 항목 ⑦: 실시간 서브넷 CIDR 및 가용 IP 조회
    if 7 in selected:
        s_resp = requests.get(f"https://management.azure.com{subnet_id}?api-version=2023-11-01", headers=arm_hdr, timeout=8).json()
        s_props = s_resp.get("properties", {})
        cidr = s_props.get("addressPrefix") or (s_props.get("addressPrefixes") or ["10.0.0.0/24"])[0]
        net = ipaddress.ip_network(cidr, strict=False)
        usable_ips = max(net.num_addresses - 5, 1)
        ip_cfg_cnt = len(s_props.get("ipConfigurations") or [])
        est_used = max(ip_cfg_cnt, node_count * 18 + 4) if net.prefixlen >= 26 else max(ip_cfg_cnt, node_count * (2 if cni_overlay else 30) + 4)
        free_ips = max(usable_ips - est_used, 0)
        ip_pct = round((est_used / usable_ips) * 100, 1)
        if ip_pct >= 80 or free_ips < 10:
            score -= 10
            c9["7_subnetAvailableIps"] = f"FAIL ({cidr} 사용률 {ip_pct}%, 잔여 {free_ips}개)"
            remarks.append(f"[⑦서브넷IP부족] {cidr} 잔여 {free_ips}개")
        else:
            c9["7_subnetAvailableIps"] = f"PASS ({cidr} 사용률 {ip_pct}%, 잔여 {free_ips}개)"

    # 항목 ⑧: 실시간 VNet UAMI Network Contributor 역할 할당 조회
    if 8 in selected:
        uamis = list(((aks.get("identity") or {}).get("userAssignedIdentities") or {}).values())
        principal_id = uamis[0].get("principalId") if uamis else (props.get("identityProfile", {}).get("kubeletidentity", {}).get("objectId"))
        vnet_id = subnet_id.split("/subnets/")[0] if "/subnets/" in subnet_id else ""
        ra_url = f"https://management.azure.com{vnet_id}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01&$filter=assignedTo('{principal_id}')"
        ra_list = requests.get(ra_url, headers=arm_hdr, timeout=8).json().get("value", []) if (vnet_id and principal_id) else []
        vnet_rbac_ok = any("4d97b98b-1d4f-4787-a291-c67834d212e7" in (r.get("properties", {}).get("roleDefinitionId", "")) for r in ra_list)
        if not vnet_rbac_ok:
            score -= 10
            c9["8_aksIdentityVnetRbac"] = "FAIL (타 RG VNet에 UMI Network Contributor 권한 누락)"
            remarks.append("[⑧VNet권한누락] 타 RG VNet UMI Network Contributor 누락")
        else:
            c9["8_aksIdentityVnetRbac"] = "PASS (VNet Network Contributor 확인됨)"

    # 항목 ⑨: 실시간 Log Analytics Workspace 존재 여부(HTTP 200 vs 404) 조회
    if 9 in selected:
        oms = ((props.get("addonProfiles") or {}).get("omsagent") or (props.get("addonProfiles") or {}).get("omsAgent") or {})
        law_id = (oms.get("config") or {}).get("logAnalyticsWorkspaceResourceID", "")
        law_ok = True
        if law_id:
            law_r = requests.get(f"https://management.azure.com{law_id}?api-version=2022-10-01", headers=arm_hdr, timeout=8)
            law_ok = (law_r.status_code == 200)
        if not law_ok:
            score -= 10
            law_name = law_id.split("/")[-1]
            c9["9_mdcLogAnalyticsWorkspaceId"] = f"FAIL (삭제된 LAW 참조: {law_name})"
            remarks.append(f"[⑨MDC/LAW오류] 삭제된 LAW({law_name}) 참조")
        else:
            c9["9_mdcLogAnalyticsWorkspaceId"] = "PASS (Log Analytics Workspace 유효)"

    verdict = "READY" if (score >= 90 and not remarks) else ("BLOCKED" if score <= 75 or any("FAIL" in v for v in c9.values()) else "CONDITIONAL")
    return {
        "clusterName": cluster_name,
        "checkedItems": sorted(list(selected)),
        "liveInspected": True,
        "upgradePath": f"{cv} -> {tv}",
        "preflightScore": max(score, 0),
        "verdict": verdict,
        "checklistItems": c9,
        "specialRemarks": " / ".join(remarks) if remarks else "선택된 사전 점검 항목 모두 정상"
    }
```
- **플레이그라운드 테스트(`플레이그라운드 테스트` 탭) 입력값별 기대 결과**:
  | 테스트 시나리오 | `cluster_name` | `check_items` | 기대 결과 (`테스트 결과` 핵심 확인 포인트 — 전체/선택 점검) |
  |---|---|---|---|
  | **① 평상시 전체 9대 항목 점검 (`aks-priv-01`)** | `aks-priv-01` | `ALL` *(또는 빈칸)* | • `checkedItems`: `[1, 2, 3, 4, 5, 6, 7, 8, 9]`<br>• `preflightScore`: **`100`**, `verdict`: **`"READY"`** (9개 전 항목 실시간 `PASS`) |
  | **② 평상시 전체 9대 항목 점검 (`aks-priv-02`)** | `aks-priv-02` | `ALL` *(또는 빈칸)* | • `checkedItems`: `[1, 2, 3, 4, 5, 6, 7, 8, 9]`, `preflightScore`: **`35`**, `verdict`: **`"BLOCKED"`**<br>• 2·3·5·6·7·8번 6개 위반 항목 실시간 검출 |
  | **③ 일부 항목만 선택 점검 (예: Azure 인프라 7·8·9번만)** | `aks-priv-03` | `7,8,9` | • `checkedItems`: **`[7, 8, 9]`** (K8s 파드 조회를 생략하고 Azure ARM 7·8·9번만 즉시 점검)<br>• `7_subnetAvailableIps`(`PASS`), `8_aksIdentityVnetRbac`(`PASS`), `9_mdcLogAnalyticsWorkspaceId`(`FAIL: 삭제된 LAW 참조: law-sre-deleted-ghost`) 3개만 반환 |
  | **④ 파드/PDB 핵심 항목(1·3·4번)만 선택 점검** | `aks-priv-03` | `1,3,4` | • `checkedItems`: **`[1, 3, 4]`**<br>• `1_podHaConfig`(`FAIL`), `3_schedulingConstraints`(`PASS`), `4_pdbConfig`(`FAIL: AllowedDisruptions=0: messaging/notification-pdb`) 3개만 반환 |

---

#### (선택) 도구 3: `verify-multihub-firewall-udr-route` (실시간 ARG + VNet Private DNS 해석 + TCP 443 & K8s `/livez` 도달성 검증기)
> **참고**: 네트워크/방화벽 라우팅 개통 확인이 필요한 경우에 선택적으로 추가합니다.

- **Name**: `verify-multihub-firewall-udr-route`
- **Description**: `Dynamically resolves a Private AKS cluster's privateFQDN via VNet Private DNS and verifies TCP 443 socket reachability and Kubernetes API /livez health over the vWAN Firewall.`
- **Parameters**: `cluster_name` (`string`, required: `true`), `api_server_private_ip` (`string`, required: `false`, default: `""` — 비워두면 `privateFQDN`으로 사설 IP 자동 DNS 해석)
```python
import socket
import time
import requests
import urllib3
from azure.identity import DefaultAzureCredential

urllib3.disable_warnings()

def main(cluster_name: str, api_server_private_ip: str = "") -> dict:
    cred = DefaultAzureCredential()
    arm_tok = cred.get_token("https://management.azure.com/.default").token
    k8s_tok = cred.get_token("6dae42f8-4368-4678-94ff-3960e28e3630/.default").token
    arm_hdr = {"Authorization": f"Bearer {arm_tok}", "Content-Type": "application/json"}

    q = f"resources | where type =~ 'microsoft.containerservice/managedclusters' and name =~ '{cluster_name}' | project fqdn=tostring(properties.privateFQDN)"
    rows = requests.post(
        "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2021-03-01",
        headers=arm_hdr, json={"query": q}, timeout=8
    ).json().get("data", [])
    fqdn = rows[0]["fqdn"] if rows else ""

    resolved_ip = (api_server_private_ip or "").strip()
    if not resolved_ip and fqdn:
        resolved_ip = socket.gethostbyname(fqdn)

    start = time.time()
    reachable, k8s_http_status, err = False, None, None
    try:
        with socket.create_connection((resolved_ip, 443), timeout=3.5):
            reachable = True
        if fqdn and not api_server_private_ip:
            r = requests.get(f"https://{fqdn}/livez", headers={"Authorization": f"Bearer {k8s_tok}"}, verify=False, timeout=5)
            k8s_http_status = r.status_code
    except Exception as e:
        err = str(e)

    return {
        "clusterName": cluster_name,
        "privateFqdn": fqdn,
        "resolvedPrivateIp": resolved_ip,
        "tcp443ReachableOverVNet": reachable,
        "k8sApiLivezHttpStatus": k8s_http_status,
        "roundTripHandshakeMs": round((time.time() - start) * 1000, 1),
        "error": err
    }
```
- **플레이그라운드 테스트(`플레이그라운드 테스트` 탭) 입력값별 기대 결과**:
  | 테스트 시나리오 | `cluster_name` | `api_server_private_ip` | 기대 결과 (`테스트 결과` 핵심 확인 포인트) |
  |---|---|---|---|
  | **① 클러스터명만으로 자동 DNS 해석 + `/livez` 검증** | `aks-priv-01` | *(빈칸)* | • ARG에서 `privateFqdn` 실시간 조회 ➔ VNet Private DNS로 사설 IP(`10.52.11.6`) 자동 해석<br>• **`"tcp443ReachableOverVNet": true`**, **`"k8sApiLivezHttpStatus": 200`** 반환 |
  | **② 미할당 IP(차단/불통) 테스트** | `aks-priv-01` | `10.52.11.250` | • 3.5초 후 **`"tcp443ReachableOverVNet": false`**, `"error": "timed out"` 반환 |

---

## Step 10. `Skill builder`에서 조회 분기 규칙 및 공지 메일(`.md`) 생성 스킬 등록

### 화면 이동 및 입력 순서 (`①` ➔ `⑤`)
1. **`①` 좌측 사이드바 `Build & setup > Capabilities > Skills` (또는 `Skill builder`) 클릭**
2. **`②` 상단 `+ Create skill` 클릭**
3. **`③` 스킬 이름 입력**: **`aks-eol-notice-and-history-workflow`**
4. **`④` `Choose tools` (`도구 선택`)에서 UI 목록에 표시되는 아래 6개 도구 선택**:
   > **참고**: `RunKubectlReadCommand`나 터미널/Python 실행(`RunInTerminal`)은 에이전트 코어 내장 기능이므로 `Choose tools` 팝업 목록에는 표시되지 않으며, Step 11의 `Advanced permissions`를 통해 기본 제공됩니다. 팝업에서는 아래 6개만 체크합니다.
   - **Custom**: `check-aks-eos-release-calendar`, `evaluate-aks-upgrade-preflight`
   - **System (`Knowledge Base` / `Azure Operation`)**: `SearchMemory`, `RunAzCliReadCommands`
   - **MCP (`mslearn-mcp`)**: `mslearn-mcp_microsoft_docs_search`, `mslearn-mcp_microsoft_docs_fetch`
5. **`⑤` 우측 마크다운 에디터(`SKILL.md`)에 아래 원문을 복사·붙여넣기 후 `Save` 클릭**:

```markdown
---
name: aks-eol-notice-and-history-workflow
description: Executes the enterprise AKS version upgrade workflow and data-plane inspection. Enforces <=3 calls via RunKubectlReadCommand vs 4+ multi-value queries via Python REST API code, zero hardcoding, strict target version cluster filtering, 9-point pre-flight inspection, and Knowledge Memory email (.md) generation.
tools:
  - check-aks-eos-release-calendar
  - evaluate-aks-upgrade-preflight
  - SearchMemory
  - RunAzCliReadCommands
  - mslearn-mcp_microsoft_docs_search
  - mslearn-mcp_microsoft_docs_fetch
---

# 엔터프라이즈 AKS 버전 업그레이드 사전 점검 · 데이터 조회 분기 및 고객 공지 메일(.md) 생성 표준 절차

> ⚠️ **최우선 원칙 (하드코딩 절대 금지)**:
> 본 스킬 지침 및 지식 베이스(`SearchMemory`) 문서에 적힌 버전 번호, 클러스터명, 날짜, 코드 스니펫 내 리소스명은 **작성 형태와 호출 문법을 설명하기 위한 예시(Example)일 뿐**이다.
> 절대 예시 텍스트를 실제 데이터로 단정하거나 복사해 출력하지 말며, 모든 수치는 반드시 실시간 도구/API 호출 결과에서만 가져와야 한다.

---

## 0단계: 데이터 조회 시 도구 선택 분기 규칙 (`3건 이하 kubectl` vs `다중 값 Python REST API`)

클러스터 및 Azure 리소스 정보를 조회할 때는 호출 횟수에 따라 반드시 아래 규칙으로 도구를 선택한다:

1. **표준 EOS 일정 확인 및 9대 사전 점검**:
   - 최우선으로 사전 등록된 Python API 도구인 `check-aks-eos-release-calendar`와 `evaluate-aks-upgrade-preflight`를 호출한다.
2. **3건 이하 호출로 끝나는 단건·소량 조회**:
   - 특정 파드 1~2개의 이벤트(`describe pod`), 로그(`logs`), 또는 단일 리소스 상태 확인 등 **총 3회 이하 호출로 충분한 경우**에는 내장 **`RunKubectlReadCommand`** 를 직접 사용한다.
3. **4건 이상 여러 값을 조회·교차 비교해야 하는 복합 조회**:
   - `RunKubectlReadCommand`를 4번 이상 반복 호출하지 않는다.
   - 사전 등록 도구 외의 다중 값(여러 네임스페이스/리소스/클러스터)을 한꺼번에 조회해야 할 때는 터미널/Python 실행 도구(`RunInTerminal`)로 `DefaultAzureCredential` 기반 ARM 토큰(`https://management.azure.com/.default`) 및 AKS AAD 토큰(`6dae42f8-4368-4678-94ff-3960e28e3630/.default`)을 발급받아 `https://{privateFQDN}/api/v1/...` 엔드포인트를 `verify=False`로 일괄 조회하는 Python 스크립트를 실행하여 1회 호출로 수집한다.

---

## 1단계: EOS 일정 확인 및 업그레이드 대상 버전 클러스터만 엄격 필터링 (`check-aks-eos-release-calendar`)
1. `check-aks-eos-release-calendar(months_ahead=4)`를 호출한다 (사용자가 별도 개월 수를 지정하면 해당 값을 전달).
2. 각 클러스터는 자신의 `SupportPlan`(`KubernetesOfficial`은 Standard 종료일, `AKSLongTermSupport`는 LTS 종료일) 기준으로 만료 여부가 판정된다.
3. 반환된 JSON에서 **`targetUpgradeClusters` 배열에 포함된 클러스터만 작업 대상으로 선택**하며, `excludedClusters`(LTS 종료일 미도래 또는 Standard 종료일 여유)에 분류된 클러스터는 **사전 점검 대상 및 공지 메일 섹션 5(`5. 작업 대상 클러스터`)에서 반드시 제외**한다.

## 2단계: 대상 클러스터 9대 사전 점검 수행 (`evaluate-aks-upgrade-preflight`)
1. 1단계에서 추려낸 `targetUpgradeClusters`의 각 클러스터에 대해 `evaluate-aks-upgrade-preflight(cluster_name=..., check_items=...)`를 호출한다.
   - 사용자가 특정 점검 번호(예: `"3,7,8"` 또는 `"1,3,4"`)를 지정했으면 `check_items`에 해당 번호를 전달하고, 별도 지정이 없으면 평상시 기본값인 `check_items="ALL"`(1~9번 전체 점검)로 호출한다.
   - 특정 `FAIL` 항목에 대해 파드 1~2개의 추가 상세 확인(3건 이하 호출)이 필요한 경우에만 0단계 규칙에 따라 `RunKubectlReadCommand`로 보충 확인한다.
2. 반환된 `preflightScore`, `verdict`(`READY`/`CONDITIONAL`/`BLOCKED`), `checkedItems`, `checklistItems` 상세 내역, `specialRemarks`를 기록한다.

## 3단계: 버전간 주요 변경 사항 실시간 수집 (`mslearn-mcp`)
1. `targetUpgradeClusters`의 실시간 순차 업그레이드 경로에 대해 `mslearn-mcp_microsoft_docs_search` 및 `mslearn-mcp_microsoft_docs_fetch`를 호출하여 Kubernetes 및 AKS 공식 릴리즈 노트를 조회한다.
2. Managed AKS가 자동으로 처리하는 내부 컨트롤 플레인 패치는 제외하고, 서비스 담당자가 확인해야 할 주요 변경사항(노드 OS/컨테이너 런타임 전환, 제거/Deprecated API, 메트릭·볼륨·네트워크 검증 사항, 주요 GA 기능)을 마이너 버전 구간별로 정리한다.

## 4단계: 지식 베이스(`SearchMemory`) 표준 템플릿 기반 최종 공지 메일(`.md`) 작성 및 1클릭 다운로드 파일 생성
1. `SearchMemory`로 `aks-eol-notice-template-and-history.md`의 **`2. [표준 양식] 최종 사용자 발송용 AKS 버전 업그레이드 공지 메일 마크다운(.md) 템플릿`**을 조회한다.
2. 조회한 5개 섹션 구조(`1. 업그레이드 개요`, `2. 서비스나우 신청 가이드`, `3. 참고 사항`, `4. 버전간 주요 변경 사항`, `5. 작업 대상 클러스터`)를 정확히 준수하여 최종 공지 메일 마크다운 본문을 구성한다:
   - **링크 자리표시자 유지**: 서비스나우 및 사내 Confluence URL은 하드코딩하지 않고 `[직접 입력: ...]` 자리표시자로 남긴다.
   - **섹션 4**: 3단계에서 실시간 조회한 버전별 주요 변경사항을 기입한다.
   - **섹션 5 (`5. 작업 대상 클러스터`)**: 오직 1단계의 **`targetUpgradeClusters`(자신의 `SupportPlan` 종료일 기준으로 만료 임박한 클러스터만)** 행만 표에 기입하고, 우측에 2단계 사전 점검 판정(`verdict`) 및 `specialRemarks` 요약을 기입한다 (`excludedClusters`에 속한 클러스터는 절대 포함하지 않는다).
   - **섹션 5 하단 (`### 5-1. SRE 에이전트 사전 점검 상세 결과`)**: 2단계 `evaluate-aks-upgrade-preflight`에서 점검한 모든 항목(`checkedItems`)의 항목명, `PASS`/`WARN`/`FAIL` 판정, 실시간 검출 상세 및 선행 조치 권고사항을 상세 표로 반드시 함께 포함한다.
3. **브라우저 1클릭 `.md` 파일 다운로드 제공 (`./aks-upgrade-notice.md` 저장 + `/api/files/` 링크 출력)**:
   - 작성한 마크다운 전문을 **절대 경로 `/tmp/...`가 아니라 반드시 현재 작업 디렉토리 상대 경로(`./aks-upgrade-notice.md`)** 에 UTF-8 파일로 저장한다.
   - 채팅 응답에는 마크다운 코드 블록과 함께 **`[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)`** 링크를 출력하여 사용자가 클릭 한 번으로 `.md` 파일을 다운로드할 수 있게 한다.
```

---

## Step 11. `Tools > Advanced permissions` (`Allow` / `Ask` / `Deny`) 거버넌스 규칙 및 `Custom instructions` 설정

SRE Agent가 진단(Read)은 무승인으로 즉시 수행하되, **사전 점검에서 발견된 차단 요인(예: `AllowedDisruptions=0` PDB 완화, 누락된 VNet RBAC 부여)을 조치할 때는 반드시 관리자의 1클릭 승인(`Ask`)** 을 거치도록 명령어+인자 패턴 기반 고급 권한(`Advanced permissions`)을 구성합니다.

### 화면 이동 및 입력 순서 (`①` ➔ `④`)
1. **`①` 좌측 사이드바 `Build & setup > Capabilities > Tools` 클릭 후 우측 상단 `Advanced permissions` 클릭**
2. **`②` 상단 탭(`Allow` / `Ask` / `Deny`)을 전환하며 `+ Add pattern`으로 아래 표준 규칙 등록**:

| 탭 구분 | 입력할 패턴 (`ToolName` 또는 `ToolName(argument pattern)`) | 운영 의도 및 동작 효과 |
|---|---|---|
| **🟢 `Allow`**<br>*(무승인 즉시 실행)* | • `check-aks-eos-release-calendar`<br>• `evaluate-aks-upgrade-preflight`<br>• `ExecutePythonCode`<br>• `RunKubectlReadCommand(kubectl get *)`<br>• `RunKubectlReadCommand(kubectl describe *)`<br>• `RunKubectlReadCommand(kubectl top *)`<br>• `RunKubectlReadCommand(kubectl logs * --tail=*)`<br>• `RunAzCliReadCommands(az aks *)`<br>• `RunAzCliReadCommands(az graph query *)`<br>• `azure-arg-mcp_*`<br>• `mslearn-mcp_*`<br>• `Search*` | • 핵심 Python 도구 2종, 다중 값 일괄 조회용 Python 코드 실행(`ExecutePythonCode`), 3건 이하 단건 `kubectl`/`az` 읽기 명령 무승인 즉시 실행<br>• Live Report(0 AAU) 및 MS Learn 공식 문서 검색 무중단 허용 |
| **🟡 `Ask`**<br>*(관리자 1클릭 승인 필수)* | • `RunKubectlWriteCommand(kubectl patch pdb * -n *)`<br>• `RunKubectlWriteCommand(kubectl scale deployment/* -n *)`<br>• `RunKubectlWriteCommand(kubectl rollout restart deployment/* -n *)`<br>• `RunKubectlWriteCommand(kubectl cordon *)`<br>• `RunKubectlWriteCommand(kubectl drain * --ignore-daemonsets *)`<br>• `RunAzCliWriteCommands(az role assignment create *)`<br>• `RunAzCliWriteCommands(az aks update *)` | • **사전 점검 ④ 조치**: 차단 PDB(`AllowedDisruptions=0`) 임시 완화 시 채팅창에 승인 카드 표시<br>• **사전 점검 ① 조치**: 단일 레플리카(`replicas=1`) 증설 승인<br>• **사전 점검 ⑧/⑨ 조치**: 타 RG VNet `Network Contributor` 권한 부여 및 깨진 LAW 재연결 승인 |
| **🔴 `Deny`**<br>*(실행 원천 차단)* | • `RunKubectlWriteCommand(kubectl * -n kube-system)`<br>• `RunKubectlWriteCommand(kubectl delete namespace *)`<br>• `RunKubectlWriteCommand(kubectl delete pv*)`<br>• `RunAzCliWriteCommands(az * delete *)` | • `kube-system` 컨트롤 플레인 수정, 네임스페이스/PV 삭제, Azure 리소스 삭제 명령 원천 차단 |

3. **`③` 좌측 사이드바 `Build & setup > Capabilities > Custom instructions`로 이동하여 글로벌 지침 입력**:
   ```markdown
   1. 모든 응답과 보고서는 한국어 마크다운 표(Table) 중심으로 명확하게 작성하며, 문서나 지침 내 예시는 형식 참고용일 뿐이므로 절대 하드코딩된 값을 출력하지 말고 실시간 조회 결과만 사용한다.
   2. 데이터 조회 시 3건 이하의 단순·단건 호출은 내장 `RunKubectlReadCommand`를 사용하고, 4건 이상의 여러 값을 조회해야 할 때는 사전 등록된 Python API 도구(`check-aks-eos-release-calendar`, `evaluate-aks-upgrade-preflight`)를 호출하거나 `ExecutePythonCode`로 Python REST API 조회 코드를 작성·실행하여 일괄 조회한다.
   3. AKS 버전 업그레이드 사전 점검 및 공지 메일 작성 요청 시 `aks-eol-notice-and-history-workflow` 스킬 절차를 준수하여, 업그레이드 대상 버전 클러스터(`targetUpgradeClusters`)만 필터링하고 사전 점검 상세 결과표(섹션 5-1)가 포함된 마크다운(`.md`) 전문을 출력한다.
   ```
4. **`④` 하단 `Save` 클릭**

---

## Step 12. `Agent Canvas` (또는 `Subagent builder`)에서 `aks_upgrade_specialist` 사용자 지정 에이전트 생성

> **참고 (`RunKubectlReadCommand` 등 코어 내장 도구의 전역 상속)**:
> `Choose tools` 팝업에는 선택형 도구와 Custom/MCP 도구만 표시되며 `RunKubectlReadCommand`, `RunKubectlWriteCommand`, `RunInTerminal` 같은 코어 도구는 목록에 나타나지 않습니다. **`Form` 탭에서 `Skills`와 `Tools`를 비워두면 코어 내장 도구, Custom 도구, MCP 도구, Skill이 전역 설정에서 자동 상속**됩니다. 명시적으로 도구를 지정하려면 우측 상단 **`YAML` 탭(방법 B)** 을 사용합니다.

### 방법 A (`Form` 탭 사용: 전역 도구/스킬 자동 상속)
1. **`①` 좌측 사이드바 `Build & setup > Workflows > Agent Canvas` ➔ `+ Create > Agent` 클릭** (또는 `Capabilities > Subagent builder > + Create`)
2. **`②` 상단 탭이 `Form` (`양식`)으로 선택된 상태에서 아래 표와 같이 입력**:

| 필드명 (포털 표시명) | 입력 / 선택할 값 |
|---|---|
| **Agent name (`에이전트 이름 *`)** | **`aks_upgrade_specialist`** |
| **Instructions (`지침 *`)** | 아래 복사·붙여넣기용 **에이전트 지침 원문** 붙여넣기 |
| **Skills (`스킬` — `Choose skills`)** | **비워둠** *(전역 스킬 `aks-eol-notice-and-history-workflow` 자동 상속 — 또는 1개 명시 선택 가능)* |
| **Tools (`도구` — `Choose tools`)** | **비워둠** *(전역 도구 자동 상속)* |

#### 복사·붙여넣기용 `Instructions (지침 *)` 원문
```markdown
당신은 엔터프라이즈 Private AKS 버전 관리 및 업그레이드 사전 점검 전담 SRE 에이전트(`aks_upgrade_specialist`)입니다.

[최우선 원칙 — 하드코딩 금지]
- 지침, 스킬, 지식 베이스(`SearchMemory`) 문서에 적힌 버전 번호, 날짜, 클러스터명, 예시 코드는 출력 양식과 문법을 설명하기 위한 예시(Example)일 뿐입니다.
- 절대 예시 값을 실제 결과처럼 복사해 출력하지 말고, 모든 데이터는 반드시 실시간 도구 호출 결과에서만 가져오세요.

[데이터 조회 도구 선택 분기 규칙]
1. EOS 일정 및 대상 클러스터 식별: `check-aks-eos-release-calendar` Python 도구를 호출하고, `targetUpgradeClusters`(업그레이드 대상 버전과 일치하는 클러스터)만 작업 대상으로 삼으세요 (`excludedOtherVersionClusters`에 속한 타 버전 클러스터는 제외).
2. 클러스터 9대 사전 점검: `evaluate-aks-upgrade-preflight(cluster_name=..., check_items=...)` Python 도구를 호출하세요 (평상시 `check_items="ALL"`, 사용자 일부 지정 시 `"1,3,4"` 등 해당 번호만 점검).
3. 추가 데이터 조회 시 호출 횟수 기준 분기:
   - 3건 이하의 단순·단건 조회(특정 파드 1~2개 `describe`, `logs`, 상태 확인): 내장 `RunKubectlReadCommand` 또는 `RunAzCliReadCommands`를 사용하세요.
   - 4건 이상의 여러 값을 조회·비교해야 하는 경우: `kubectl`을 반복 호출하지 말고, Python REST API 코드(`DefaultAzureCredential`로 ARM 토큰 `https://management.azure.com/.default` 및 AKS AAD 토큰 `6dae42f8-4368-4678-94ff-3960e28e3630/.default` 발급 후 `https://<privateFQDN>/...`을 `verify=False`로 일괄 조회)를 작성·실행하여 1회 호출로 수집하세요.

[최종 사용자 공지 메일(.md) 작성 및 다운로드 링크 제공 규칙]
- `aks-eol-notice-and-history-workflow` 스킬 및 `SearchMemory`(`aks-eol-notice-template-and-history.md`)의 5개 섹션 양식을 준수하여 마크다운을 작성하세요.
- 사내 링크는 `[직접 입력: ...]` 자리표시자로 유지하고, 섹션 4(주요 변경사항)는 `mslearn-mcp` 실시간 조회 결과로 작성하며, 섹션 5에는 오직 `targetUpgradeClusters` 클러스터만 포함한 표와 `### 5-1. SRE 에이전트 사전 점검 상세 결과` 표를 반드시 함께 포함하세요.
- 작성한 마크다운 전문을 현재 작업 디렉토리 상대 경로(`./aks-upgrade-notice.md`, 절대 `/tmp/` 사용 금지)에 파일로 저장하고, 응답에 마크다운 코드 블록과 함께 `[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)` 다운로드 링크를 함께 출력하세요.
```

3. **`③` 하단 `Create` (또는 `Save`) 버튼 클릭**

---

### 방법 B (`YAML` 탭 사용 — `RunKubectlReadCommand` 등을 명시적으로 직접 기입하고 싶을 때)
우측 상단 탭을 `Form`에서 **`YAML`** 로 전환한 뒤 아래 YAML 전문을 그대로 붙여넣고 **`Create` (`Save`)** 를 누르면, UI 피커 목록에 안 보이는 `RunKubectlReadCommand`, `RunKubectlWriteCommand`, `RunInTerminal`까지 에이전트에 명시적으로 바인딩됩니다:

```yaml
api_version: azuresre.ai/v1
kind: AgentConfiguration
spec:
  name: aks_upgrade_specialist
  agent_type: Autonomous
  handoff_description: 엔터프라이즈 Private AKS EOS release calendar targeting, 9-point pre-flight inspection, and customer upgrade notice (.md) generation specialist.
  enable_skills: true
  allowed_skills:
    - aks-eol-notice-and-history-workflow
  tools:
    - check-aks-eos-release-calendar
    - evaluate-aks-upgrade-preflight
    - SearchMemory
    - RunKubectlReadCommand
    - RunKubectlWriteCommand
    - RunInTerminal
    - RunAzCliReadCommands
    - RunAzCliWriteCommands
    - GetArmResourceAsJson
  mcp_tools:
    - mslearn-mcp_microsoft_docs_search
    - mslearn-mcp_microsoft_docs_fetch
    - mslearn-mcp_microsoft_code_sample_search
    - azure-arg-mcp_arm
    - azure-arg-mcp_aks
    - azure-arg-mcp_subscription_list
  system_prompt: |-
    당신은 엔터프라이즈 Private AKS 버전 관리 및 업그레이드 사전 점검 전담 SRE 에이전트(`aks_upgrade_specialist`)입니다.

    [최우선 원칙 — 하드코딩 금지]
    - 지침, 스킬, 지식 베이스(`SearchMemory`) 문서에 적힌 버전 번호, 날짜, 클러스터명, 예시 코드는 출력 양식과 문법을 설명하기 위한 예시(Example)일 뿐입니다.
    - 절대 예시 값을 실제 결과처럼 복사해 출력하지 말고, 모든 데이터는 반드시 실시간 도구 호출 결과에서만 가져오세요.

    [데이터 조회 도구 선택 분기 규칙]
    1. EOS 일정 및 대상 클러스터 식별: `check-aks-eos-release-calendar` Python 도구를 호출하고, 각 클러스터의 `SupportPlan`(Standard는 Standard 종료일, LTS는 LTS 종료일) 기준으로 추출된 `targetUpgradeClusters`만 작업 대상으로 삼으세요 (`excludedClusters`는 제외).
    2. 클러스터 9대 사전 점검: `evaluate-aks-upgrade-preflight(cluster_name=..., check_items=...)` Python 도구를 호출하세요 (평상시 `check_items="ALL"`, 사용자 일부 지정 시 `"1,3,4"` 등 해당 번호만 점검).
    3. 추가 데이터 조회 시 호출 횟수 기준 분기:
       - 3건 이하의 단순·단건 조회(특정 파드 1~2개 `describe`, `logs`, 상태 확인): 내장 `RunKubectlReadCommand` 또는 `RunAzCliReadCommands`를 사용하세요.
       - 4건 이상의 여러 값을 조회·비교해야 하는 경우: `kubectl`을 반복 호출하지 말고, Python REST API 코드(`DefaultAzureCredential`로 ARM 토큰 `https://management.azure.com/.default` 및 AKS AAD 토큰 `6dae42f8-4368-4678-94ff-3960e28e3630/.default` 발급 후 `https://<privateFQDN>/...`을 `verify=False`로 일괄 조회)를 작성·실행하여 1회 호출로 수집하세요.

    [최종 사용자 공지 메일(.md) 작성 및 다운로드 링크 제공 규칙]
    - `aks-eol-notice-and-history-workflow` 스킬 및 `SearchMemory`(`aks-eol-notice-template-and-history.md`)의 5개 섹션 양식을 준수하여 마크다운을 작성하세요.
    - 사내 링크는 `[직접 입력: ...]` 자리표시자로 유지하고, 섹션 4(주요 변경사항)는 `mslearn-mcp` 실시간 조회 결과로 작성하며, 섹션 5에는 오직 `targetUpgradeClusters` 클러스터만 포함한 표와 `### 5-1. SRE 에이전트 사전 점검 상세 결과` 표를 반드시 함께 포함하세요.
    - 작성한 마크다운 전문을 현재 작업 디렉토리 상대 경로(`./aks-upgrade-notice.md`, 절대 `/tmp/` 사용 금지)에 파일로 저장하고, 응답에 마크다운 코드 블록과 함께 `[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)` 다운로드 링크를 함께 출력하세요.
```

---

# Phase 5. 0-AAU `Live Reports` 상시 대시보드 · 월간 정기 스케줄 및 Full Cycle 채팅 검증

---

## Step 13. `Live Reports` (0 AAU 실시간 12컬럼 대시보드) 및 `Scheduled tasks` (매월 1일 자동 공지) 등록

### 1) `Live Reports`에서 LLM 과금(AAU) 없는 실시간 12컬럼 인벤토리 대시보드 생성
1. **좌측 사이드바 `Monitor > Live reports` 클릭 ➔ 상단 `+ Create live report` 클릭**
2. **프롬프트 입력창에 아래 요청 입력**:
   ```text
   azure-arg-mcp 커넥터의 azure-arg-mcp_arm(Azure Resource Graph) 및 azure-arg-mcp_aks 도구를 사용하여 구독 <YOUR_SUBSCRIPTION_ID>의 Private AKS 클러스터 현황을 조회하는 Live Report를 생성해 주세요:
   1) 상단 요약 카드: 전체 클러스터 수, Standard(KubernetesOfficial) vs LTS(AKSLongTermSupport) 클러스터 수, 서비스 등급별(S/A/B/C) 수량
   2) 하단 12컬럼 인벤토리 테이블: mgmtName, Subscription, Cluster, k8sVersion, SupportPlan, PricingTier, ServiceName, ServiceCode, ServiceOpenDate, ServiceGrade, APIServerAccess, NetworkPlugin
   ```
3. **생성된 Live Report 우측 상단 `↻ Refresh` 클릭 확인**:
   - 리포트가 생성된 이후에는 `Refresh`를 누를 때마다 LLM을 거치지 않고(0 AAU) 브라우저가 `window.sreagent.callTool('azure-arg-mcp_arm', ...)`을 직접 호출해 실시간 ARG 데이터를 갱신합니다.

### 2) `Automation > Scheduled tasks`에서 매월 1일 정기 EOS 점검 및 공지 메일 초안 자동 생성 등록
1. **좌측 사이드바 `Automation > Scheduled tasks` 클릭 ➔ `+ Create task` 클릭**
2. **작업 정보 입력**:
   - **Task Name**: `Monthly AKS EOL Pre-flight & Notice (.md) Automation`
   - **Cron Expression**: `0 0 1 * *` (매월 1일 00:00 UTC 자동 실행)
   - **Target Agent**: `aks_upgrade_specialist`
   - **Task Prompt**: 아래 Step 14의 Full Cycle 프롬프트와 동일하게 입력

---

## Step 14. 실시간 채팅(`/agent aks_upgrade_specialist`)에서 End-to-End 실행 검증

### 화면 이동 및 실행 순서 (`①` ➔ `⑤`)
1. **`①` 좌측 사이드바 `Investigate > New chat` 클릭**
2. **`②` 채팅 입력창에 아래 프롬프트 입력**:

   **[시나리오 A: 전체 사전 점검 + 4개월 내 EOS 도래 대상 클러스터(`1.35`) 공지 메일(`.md`) 생성 및 다운로드]**
   ```text
   /agent aks_upgrade_specialist 향후 4개월 내에 지원 종료(EOS)가 도래하는 AKS 클러스터(Standard는 Standard 종료일, LTS는 LTS 종료일 기준)를 확인하고, 해당 대상 클러스터만 골라내어 9대 사전 점검을 모두 수행한 뒤, 점검 상세 결과가 포함된 최종 사용자 발송용 업그레이드 공지 메일 초안(.md)을 작성하고 다운로드 링크를 제공해 주세요.
   ```

   **[시나리오 B: 특정 항목(예: 스케줄링 제약, 서브넷 IP, VNet 권한)만 선택 점검 + 공지 메일(`.md`) 생성 및 다운로드]**
   ```text
   /agent aks_upgrade_specialist 향후 4개월 내에 지원 종료(EOS)가 도래하는 업그레이드 대상 클러스터만 추출하여 9대 체크리스트 중 3번(스케줄링 제약/Pending), 7번(서브넷 가용 IP), 8번(타 RG VNet 권한) 항목만 선택 점검(check_items="3,7,8")하고, 그 점검 결과를 포함한 고객 공지 메일 초안(.md)과 다운로드 링크를 제공해 주세요.
   ```

3. **`③` 도구 실행 배지(`Executed Tools`)에서 기능 연계 동작 확인**:
   - **`check-aks-eos-release-calendar`**: MS Learn 실시간 파싱 및 클러스터별 `SupportPlan` 종료일 대조를 통해:
     - `aks-priv-03` (`1.34.12`, `AKSLongTermSupport`): LTS 종료일(`2027-11-30`) 미도래로 제외
     - `aks-priv-01` (`1.36.4`, `KubernetesOfficial`): Standard 종료일(`2027-06-30`) 여유로 제외
     - `aks-priv-02` (`1.35.9`, `KubernetesOfficial`): 4개월 내 Standard 종료일(`2027-03-31`) 도래로 `targetUpgradeClusters`(`targetMinorVersionsWithClusters: ["1.35"]`)에 추출
   - **`evaluate-aks-upgrade-preflight`**: 추출된 `aks-priv-02`에 대해 실시간 ARM + VNet K8s API 점검 수행 (1~9번 또는 선택 항목별 `PASS` / `FAIL` 판정 반환)
   - **`mslearn-mcp`**: 식별된 경로(`v1.35 -> v1.36 -> v1.37`)의 단계별 주요 변경사항 조회
   - **`SearchMemory`**: 지식 베이스에서 업그레이드 공지 메일 5개 섹션 표준 템플릿 로드
4. **`④` 출력된 마크다운(`.md`) 메일 초안 및 `[📥 aks-upgrade-notice.md 파일 다운로드]` 링크 확인**:
   - **섹션 1~3**: 목표 버전(`v1.37.1`), 순차 경로(`v1.35.9 -> v1.36.5 -> v1.37.1`), 직접 입력 링크 자리표시자(`[직접 입력: ...]`) 반영
   - **섹션 4 (`4. 버전간 주요 변경 사항`)**: MS Learn 릴리즈 노트 기반 주요 변경사항 기입
   - **섹션 5 (`5. 작업 대상 클러스터`)**: `aks-priv-02` (`1.35.9`) 표기 및 하단 **`### 5-1. SRE 에이전트 사전 점검 상세 결과`** 표에 점검 항목별 `PASS` / `FAIL` 내역과 선행 조치 권고사항 포함
   - **파일 다운로드**: 채팅창의 **`[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)`** 링크 클릭 시 브라우저에서 `.md` 파일 다운로드
5. **`⑤` (선택) 차단 요인 반자동 조치 (`Advanced permissions > Ask`) 테스트**:
   - 채팅창에 *"사전 점검에서 FAIL이 나온 `aks-priv-03`의 차단 PDB(`notification-pdb`)를 업그레이드 가능하도록 완화해 줘"*라고 입력하면, `Step 11`에 설정한 `Ask` 규칙에 의해 **관리자 승인 카드(`Approve` / `Reject`)** 가 표시됩니다.

---

## 부록: 검증된 자동화 산출물 및 샘플 파일 목록 (`samples/private-aks-fleet-lab/`)

| 구분 | 파일 경로 | 설명 |
|---|---|---|
| **대시보드 JSON** | [`monitoring/sre-aks-management-dashboard.json`](./monitoring/sre-aks-management-dashboard.json) | `Azure Monitor > Dashboards with Grafana` (`SRE-AKS-Management`) 및 `Azure Managed Grafana` 1클릭 Import용 13패널 완성본 JSON |
| **지식 베이스 1 (공지 템플릿)** | [`agent/knowledge/aks-eol-notice-template-and-history.md`](./agent/knowledge/aks-eol-notice-template-and-history.md) | 5개 섹션 고객 공지 메일 마크다운(`.md`) 표준 템플릿 (`[직접 입력: ...]` 자리표시자, 대상 버전 필터링 규칙, 섹션 5-1 사전 점검 상세 결과표 포함) |
| **지식 베이스 2 (9대 점검 정책)** | [`agent/knowledge/aks-9point-upgrade-preflight-policy.md`](./agent/knowledge/aks-9point-upgrade-preflight-policy.md) | AKS 업그레이드 9대 사전 점검 배점(100점)·판정 기준(`READY`/`CONDITIONAL`/`BLOCKED`) 및 선행 조치 가이드 |
| **지식 베이스 3 (데이터플레인 SOP)** | [`agent/knowledge/aks-dataplane-inspection-sop.md`](./agent/knowledge/aks-dataplane-inspection-sop.md) | 사설 AKS 데이터플레인 조회 SOP (`3건 이하 kubectl` vs `4건 이상 Python K8s REST API` 분기 규칙) |

