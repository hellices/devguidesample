---
title: 멀티 허브 방화벽 뒤의 Private AKS 버전 업그레이드 사전 점검과 파드 장애 진단하기
description: 공용 엔드포인트가 꺼진 Private AKS 플릿이 다중 허브 방화벽 뒤에 분리된 환경에서, VNet 통합 Azure SRE Agent가 컨트롤 플레인(ARM)과 데이터 플레인(TCP 443)을 함께 조회하여 월 단위(4개월) 및 LTS 지원 플랜 기준 EOS 대상을 판별하고, 9대 업그레이드 사전 점검·고객 안내문 파일 다운로드·승인 기반 파드 장애 복구까지 수행하는 과정을 재현합니다.
document_type: lab
services:
  - azure-monitor
  - azure-kubernetes-service
technologies:
  - kubernetes
  - bicep
  - python
  - azure-cli
tags:
  - operate
  - diagnose
  - networking
  - ai-agents
status: verified
verification_status: verified
sources_checked_at: 2026-10-31
official_sources:
  - title: Azure SRE Agent network integration
    url: https://learn.microsoft.com/azure/sre-agent/network-integration
  - title: Configure network controls
    url: https://learn.microsoft.com/azure/sre-agent/configure-network-controls
  - title: Network requirements for Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/network-requirements
  - title: Python tools in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/python-code-execution
  - title: Agent permissions in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/permissions
  - title: Tool access policies in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/tool-access-policies
  - title: Skills in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/skills
  - title: Custom agents in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/sub-agents
  - title: Agent hooks in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/agent-hooks
  - title: Live reports in Azure SRE Agent (preview)
    url: https://learn.microsoft.com/azure/sre-agent/live-reports
  - title: Deploy with infrastructure as code in Azure SRE Agent
    url: https://learn.microsoft.com/azure/sre-agent/deploy-iac
  - title: Create a private Azure Kubernetes Service (AKS) cluster
    url: https://learn.microsoft.com/azure/aks/private-clusters
  - title: Supported Kubernetes versions in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/supported-kubernetes-versions
  - title: Upgrade an Azure Kubernetes Service (AKS) cluster
    url: https://learn.microsoft.com/azure/aks/upgrade-aks-cluster
  - title: Roll out node pool upgrades in Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/upgrade-aks-node-pools-rolling
  - title: Azure virtual network traffic routing
    url: https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview
  - title: Azure Private Endpoint DNS configuration
    url: https://learn.microsoft.com/azure/private-link/private-endpoint-dns
last_verified: 2026-10-31
review_cycle_days: 90
estimated_time: 60m
cost: paid
cleanup_required: true
topic_order: 12
---

# 멀티 허브 방화벽 뒤의 Private AKS 버전 업그레이드 사전 점검과 파드 장애 진단하기

엔터프라이즈 환경에서 다중 허브 VNet(또는 Azure Virtual WAN Secured Hub)과 중앙 방화벽 뒤에
배치된 Private AKS 플릿을 운영할 때는 세 가지 질문이 반복됩니다. 첫째, **외부 공용 API 서버가
닫힌 Private AKS의 파드·이벤트·PDB 상태를 VNet 통합 Azure SRE Agent가 방화벽을 거쳐 직접
읽을 수 있는가**, 둘째, **Standard 지원 플랜과 장기 지원(LTS) 플랜이 혼재된 플릿에서 월 단위
기준으로 실제 업그레이드 대상만 정확히 추려내고 9대 사전 점검을 수십 초 안에 끝낼 수 있는가**,
셋째, **점검 결과를 기반으로 고객 안내문 마크다운 파일을 즉시 다운로드하고 승인 게이트를 거쳐
파드 장애까지 복구할 수 있는가**입니다.

이 실습은 SRE Agent 전용 VNet(`10.42.0.0/16`)과 다중 허브 방화벽 경로, 그리고 서로 다른
Kubernetes 버전과 지원 플랜(`KubernetesOfficial` Standard 대 `AKSLongTermSupport` Premium)을
가진 Private AKS 클러스터(`aks-priv-01` ~ `03`)를 구성해 위 세 가지 질문을 실증합니다.

2026-10-31 Korea Central 및 East US 2 환경에서 실제로 배포해 검증한 결과는 다음과 같습니다.

- 에이전트 위임 서브넷(`10.42.4.0/24`)의 UDR Next Hop을 허브 방화벽으로 지정하고 DNS Private
  Resolver(`10.232.2.4`)에 각 Private AKS의 `*.privatelink.eastus2.azmk8s.io` 사설 DNS 영역을
  연결하자, 에이전트 샌드박스에서 다중 허브 방화벽을 경유해 Private AKS API 서버(`:443`)까지
  단일 홉으로 도달했습니다.
- `check-aks-eos-release-calendar` 도구가 Microsoft Learn 공식 릴리스 캘린더와 실시간 ARM 인벤토리를
  대조해 향후 4개월(월 단위 말일 기준, `2026-11` 기준 `2027-03-31`까지) 이내 EOS가 도래하는
  `aks-priv-02`(`1.35.9`, Standard, `2027-03-31` 만료)만 업그레이드 대상으로 정확히 선별하고,
  LTS 플랜이 적용된 `aks-priv-03`(`1.34.12`, LTS 만료 `2027-11-30`, 잔여 12개월)과 `aks-priv-01`(`1.36.4`,
  Standard 만료 `2027-06-30`, 잔여 7개월)은 대상에서 제외했습니다.
- `evaluate-aks-upgrade-preflight` 도구가 컨트롤 플레인(ARM)과 데이터 플레인(Kubernetes REST API)을
  결합해 **9대 업그레이드 사전 점검**(서브넷 잔여 IP, UAMI 권한, 비정상·단일 파드, 로컬 스토리지,
  스케줄링 제약, PDB 드레인 차단, 지원 중단 API, Graceful Shutdown, Defender 삭제된 워크스페이스 참조)을
  단일 호출로 평가하고, `ensure_ascii=False` 직렬화로 한글 유니코드 6배 팽창(`\uXXXX`)과 앞부분
  잘림(Head-Truncation)을 방지했습니다.
- 에이전트가 작업 디렉터리(`./aks-upgrade-notice.md`)에 생성한 5개 섹션 고객 안내문은 채팅 화면의
  `[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)` 링크를 통해 브라우저에서
  원클릭으로 내려받을 수 있으며, **고급 사용 권한(`Allow` / `Ask` / `Deny`)** 승인 후 파드 장애와
  단일 레플리카 결함을 즉시 복구하고 해당 항목만 부분 재검증(`check_items="3,7,8"`)해 `PASS` 전환을
  확인했습니다.

## 멀티 허브 방화벽과 사설 DNS를 통과해 Private AKS 데이터 플레인에 도달한다

![멀티 허브 방화벽과 Private DNS Zone을 거쳐 3개 허브의 Private AKS 클러스터를 점검하는 아키텍처](images/multihub-aks-architecture.svg)

Azure SRE Agent를 **Azure VNet 모드**로 배포하면 에이전트의 추론 엔진과 Python·CLI 실행
샌드박스는 `Microsoft.App/environments`로 위임된 전용 서브넷(`10.42.4.0/24`) 안에서 실행됩니다.
다른 허브 VNet에 있는 Private AKS API 서버로 패킷이 흘러가고 방화벽 감사 로그에 기록되려면
네 가지 네트워크·권한 조건이 동시에 맞아야 합니다.

1. **사설 DNS 영역 연결과 DNS Private Resolver 지정:** 각 Private AKS가 생성한
   `*.privatelink.<region>.azmk8s.io` 사설 DNS 영역에 DNS VNet과 SRE Agent VNet의 Virtual
   Network Link를 추가하고, SRE Agent 네트워크 제어에서 **Use VNet private DNS**를 켭니다.
2. **`*.azmk8s.io` 기본 우회(Bypass) 제거:** SRE Agent VNet 통합의 `allowedHosts` 목록에
   `*.azmk8s.io`가 남아 있으면 요청이 사용자 VNet과 방화벽을 건너뛰고 공용 플랫폼 경로로
   빠집니다. 사설 라우팅을 강제하려면 `allowedHosts`에서 `*.azmk8s.io`를 제거합니다.
3. **Private Endpoint 서브넷 정책 활성화:** Private Endpoint가 배치된 서브넷에서
   `privateEndpointNetworkPolicies: Enabled`를 설정해야 출발지 UDR(`VirtualAppliance` →
   허브 방화벽 사설 IP)이 건너뛰어지지 않고 방화벽 체인을 통과합니다.
4. **컨트롤 플레인과 데이터 플레인 RBAC 분리 부여:** 에이전트 관리 ID에 ARM 범위의 `Reader`,
   `Azure Kubernetes Service Cluster User Role`뿐 아니라 Kubernetes 데이터 플레인(`dataActions`)을
   허용하는 `Azure Kubernetes Service RBAC Reader`(진단용) 및 승인 후 복구용 역할(`Contributor`,
   `Azure Kubernetes Service RBAC Cluster Admin`)을 부여해야 `403 Forbidden` 없이 조회와 복구가
   실행됩니다.

포털의 **하위 에이전트 작성기(Subagent builder)** 에서도 전담 에이전트(`aks_upgrade_specialist`)에
지침, 스킬(`aks-eol-notice-and-history-workflow`), MCP 도구(`mslearn-mcp`, `azure-arg-mcp`) 및
Python 도구가 결합된 구성을 확인할 수 있습니다.

![SRE Agent 포털의 하위 에이전트 편집기 화면. aks_upgrade_specialist에 지침, 스킬, MCP 커넥터와 Python 도구가 연결되어 있다](images/agent-canvas-topology.png)

네트워크 우회 제거, UDR 라우팅, Grafana 대시보드 및 포털 UI Step 00~14 상세 설정 절차는 샘플의
[구성 상세](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab/CONFIGURATION.md)에 정리했습니다.

## 컨트롤 플레인 조회와 데이터 플레인 조회는 보는 범위가 다르다

![컨트롤 플레인(ARM API)과 데이터 플레인(Private Endpoint TCP 443)이 각각 조회하는 정보 비교](images/controlplane-vs-dataplane-flow.svg)

Private AKS 운영에서 가장 흔한 착오는 `az aks show`가 `Succeeded`를 반환하면 클러스터도
즉시 업그레이드할 수 있다고 판단하는 것입니다. 두 경로가 실제로 볼 수 있는 범위는 다음과 같이
나뉩니다.

| 구분 | 컨트롤 플레인 (ARM / Resource Graph) | 데이터 플레인 (Private Endpoint / K8s REST API · `kubectl`) |
| --- | --- | --- |
| **통신 경로** | `management.azure.com` (공인/플랫폼 경로) | `*.privatelink.<region>.azmk8s.io:443` (VNet · 허브 방화벽 · Private Endpoint) |
| **조회 가능 정보** | 클러스터·노드풀 버전, 지원 플랜(`SupportPlan`), 서브넷 잔여 IP, UAMI 권한, Defender 삭제된 LAW 연결 여부 | 비정상 파드(`CrashLoopBackOff`, `ImagePullBackOff`), 단일 파드(Single Replica), `emptyDir`/`local` PV, `nodeSelector` 불일치, PDB(`disruptionsAllowed: 0`), `preStop`/Probe 누락 |
| **확인 불가능 정보** | 파드 기동 실패, 이미지 풀 오류, PDB 드레인 차단, 로컬 볼륨 유실 위험 | Azure 서브넷 IP 고갈 여부, 구독 범위 업그레이드 카탈로그, UAMI 역할 할당 |
| **필요 RBAC** | `Reader` (`actions`) | `Azure Kubernetes Service Cluster User Role` + `Azure Kubernetes Service RBAC Reader` (`dataActions`) |

따라서 안전한 업그레이드 사전 점검은 반드시 두 평면의 데이터를 한 번에 결합해야 합니다.

## 6대 네이티브 기능을 결합해 조회 지연·유니코드 잘림·파일 다운로드 한계를 해결한다

![업그레이드 사전 점검 파이프라인과 9대 항목 평가 구조](images/upgrade-preflight-pipeline.svg)

모든 작업을 단일 Python 스크립트나 반복적인 `kubectl` 호출로만 처리하면 턴당 4~10분이 걸리고,
SRE Agent Python 실행기의 `json.dumps(result)` 기본 직렬화(`ensure_ascii=True`) 때문에 한글
1글자가 `\uXXXX` 6글자로 팽창해 4,095자 버퍼 제한에서 앞부분이 잘려 나갑니다. 또한 `/tmp/`에
저장한 마크다운 파일은 채팅 UI에서 내려받을 수 없습니다.

이 실습은 SRE Agent의 6대 네이티브 기능을 역할별로 분담해 이 문제들을 해결합니다.

| 구성 요소 | 종류 | 역할과 핵심 설계 원리 |
| --- | --- | --- |
| `SRE-AKS-Management` & `azure-arg-mcp` | Grafana 대시보드 & Live Report (`npx @azure/mcp`) | 12개 표준 컬럼(`mgmtName`, `ServiceCode`, `ServiceName`, `ServiceGrade`, `SupportPlan`, `PricingTier` 등) ARG 인벤토리를 **0 AAU**로 실시간 렌더링 |
| `check-aks-eos-release-calendar` | 핵심 Python 도구 #1 (`PythonFunctionTool`) | MS Learn 공식 릴리스 캘린더를 스크래핑하고 **월 단위(`cal_diff <= months_ahead`)** 및 지원 플랜(`Standard`는 Standard EOL, `LTS`는 LTS EOL) 기준으로 업그레이드 대상만 정확히 필터링 |
| `evaluate-aks-upgrade-preflight` | 핵심 Python 도구 #2 (`PythonFunctionTool`) | ARM API와 Private AKS K8s REST API를 결합해 **9대 사전 점검**을 수행. `check_items="ALL"` 전체 점검과 복구 후 특정 항목(`"1,4,9"`, `"3,7,8"`) 부분 재검증을 모두 지원하며 `ensure_ascii=False`로 900자 이하 출력 보장 |
| `mslearn-mcp` | 원격 MCP 커넥터 (`https://learn.microsoft.com/api/mcp`) | 타깃 마이너 버전(`1.35 → 1.36`)의 공식 릴리스 노트와 주요 변경 사항을 실시간 조회 |
| `aks-eol-notice-and-history-workflow` + 지식 문서 3종 | 스킬(`Skill`) + 지식 메모리(`Memory`) | 단순 조회 3건 이하는 내장 `RunKubectlReadCommand`, 다중 값 4건 이상은 Python REST API로 분기하고, `./aks-upgrade-notice.md`(`os.getcwd()`)에 5개 섹션 고객 안내문을 저장해 `/api/files/aks-upgrade-notice.md` 원클릭 다운로드 링크 제공 |
| `Tools > Advanced permissions` & `pre_kubectl_mutation_guard` | 고급 사용 권한(`Allow`/`Ask`/`Deny`) + `PreToolUse` 훅 | 조회 명령은 자동 실행(`Allow`), 파드 이미지·레플리카·워크스페이스 복구는 관리자 1-Click 승인(`Ask`), 클러스터·노드·네임스페이스 삭제는 원천 차단(`Deny`) |

포털의 **도구 > 고급 사용 권한(Advanced permissions)** 과 **기술 작성기(Skill builder)** 화면에서
거버넌스 규칙과 스킬 절차를 확인할 수 있습니다.

![SRE Agent 포털의 고급 사용 권한 화면. Allow, Ask, Deny 규칙으로 읽기 자동 실행과 복구 승인 및 파괴적 명령 차단이 구성되어 있다](images/agent-custom-tools.png)

![SRE Agent 포털의 기술 작성기 화면. aks-eol-notice-and-history-workflow 스킬에 EOS 조회, 9대 사전 점검, 고객 안내문 생성 및 파일 다운로드 절차가 정의되어 있다](images/agent-skill-builder.png)

### 내장 `RunKubectlReadCommand` 상속과 작업 디렉터리(`./`) 파일 다운로드 원리

- **서브에이전트의 코어 런타임 도구 상속:** 포털 UI의 `Choose tools` 팝업은 `stableOnly=true`
  도구만 표시하므로, 코어 런타임 도구인 `RunKubectlReadCommand`, `RunKubectlWriteCommand`,
  `RunInTerminal`은 목록에 나타나지 않습니다. 서브에이전트 `Form` 탭에서 `Tools`를 비워 두어
  글로벌 설정을 자동 상속받거나 `YAML` 탭에서 명시적으로 지정하면 정상 호출됩니다.
- **`/api/files/` 원클릭 다운로드:** 에이전트의 터미널과 도구는 스레드 전용 폴더인
  `tmp/ThreadFiles/<threadId>`(`os.getcwd()`)에서 실행됩니다. 파일을 `/tmp/`가 아닌 현재 작업
  디렉터리(`./aks-upgrade-notice.md`)에 저장하고 채팅 응답에
  `[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)` 링크를 출력하면,
  웹 포털 프런트엔드가 자동으로 `<threadId>`와 Bearer 토큰을 주입해 즉시 파일을 내려받습니다.

## 구독 권한과 로컬 CLI 도구를 준비한다

- Azure SRE Agent를 배포할 수 있는 구독(Korea Central 및 East US 2 지원).
- 리소스 그룹, VNet·방화벽 라우팅, 사설 DNS 영역 연결, 역할 할당을 만들 수 있는 권한(`Owner` 또는
  `Contributor` + `User Access Administrator`).
- 로컬 환경의 Azure CLI(`az`), `kubectl`, `jq`, `curl`, `python3`(3.11 이상).
- 데이터 평면 API(`https://azuresre.ai` 또는 `https://azuresre.dev`) 토큰을
  `az account get-access-token`으로 발급받을 수 있어야 합니다.

## 시간 단위로 과금되는 AKS 노드·방화벽과 에이전트 사용량을 확인한다

| 리소스 | 구성 수량 | 과금 특성 |
| --- | --- | --- |
| Private AKS 클러스터 3대 (`Standard` 2대, `Premium` LTS 1대) | 3개 클러스터 (`aks-priv-01` ~ `03`) | 컨트롤 플레인 티어(Standard / Premium LTS) 및 VM 노드(`Standard_D2s_v7`) 시간 단위 과금 |
| 다중 허브 방화벽 및 DNS Private Resolver | 허브 방화벽 + DNS Resolver | 시간 단위 및 처리 트래픽(GB) 단위 과금 |
| Azure Portal 공유 대시보드 (`SRE-AKS-Management`) 및 Live Report | 대시보드 1개 + Live Report 1개 | ARG 인벤토리 조회는 **0 AAU** (추가 과금 없음) |
| Azure SRE Agent | 1개 에이전트 (`sre-aks-fleet-agent`) | 채팅·자동화 실행 시 Azure Agent Unit(AAU) 사용량 과금 |

실습을 마치면 비용이 계속 발생하지 않도록 반드시 [리소스 정리](#lab-cleanup)를 실행합니다.

## deploy.sh로 멀티 허브 인프라와 에이전트 도구를 배포하고 결함을 주입한다

실행 가능한 전체 코드와 Bicep 템플릿, 도구·스킬·지식 문서·Grafana 대시보드 정의는
[samples/private-aks-fleet-lab](https://github.com/hellices/devguidesample/tree/main/docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab)에
있습니다. 포털 UI에서 Step 00부터 Step 14까지 직접 클릭하며 구성하는 상세 가이드는
[CONFIGURATION.md](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab/CONFIGURATION.md)를
참조합니다.

```bash
cd docs/services/azure-monitor/azure-sre-agent/samples/private-aks-fleet-lab

# 1. 단위 테스트 실행 (월 단위 EOS/LTS 판정, 9대 사전 점검 압축 출력, PreToolUse 훅 차단 검증)
python3 -m unittest discover -s tests -v

# 2. 멀티 허브 VNet·방화벽·Private AKS 인프라 배포 및 에이전트 도구·스킬·훅 등록
./scripts/deploy.sh rg-private-aks-fleet koreacentral eastus2

# 3. 이미 배포된 에이전트에 도구·스킬·지식 문서만 다시 반영할 때
./scripts/apply-agent-config.sh
```

배포가 끝나면 대상 클러스터에 사전 점검 결함 시나리오를 심습니다.

```bash
./scripts/seed-faults.sh seed
```

구성된 3대 Private AKS 클러스터와 주입된 시나리오는 다음과 같습니다.

- **`aks-priv-01` (`ENT_Workloads_Prod`, Kubernetes `1.36.4`, `Standard`):**
  Standard 지원 종료일이 `2027-06-30`(기준월 `2026-11` 대비 잔여 7개월)으로 향후 4개월 이내
  EOS 대상이 아닌 정상 운영 대조군입니다.
- **`aks-priv-02` (`ENT_Workloads_Prod_PII`, Kubernetes `1.35.9`, `Standard`):**
  Standard 지원 종료일이 `2027-03-31`(잔여 4개월, `D-4개월`)로 향후 4개월 이내 EOS 업그레이드
  대상입니다. 서브넷이 `/27`(여유 IP 부족)로 설정되어 있고, 삭제된 유령 Log Analytics 워크스페이스
  (`law-sre-deleted-ghost`)가 Defender 프로필에 연결되어 있으며, `prod` 네임스페이스에
  `CrashLoopBackOff`(`order-processor`), `ImagePullBackOff`(`payment-webhook`), 단일 레플리카
  (`inventory-api`, `replicas=1`, PDB 미설정) 결함이 주입되어 있습니다.
- **`aks-priv-03` (`ENT_Workloads_NonProd`, Kubernetes `1.34.12`, `Premium` / `AKSLongTermSupport`):**
  버전 숫자는 `1.34.12`로 가장 낮지만 **LTS(장기 지원)** 플랜이 활성화되어 있어 실제 지원 종료일이
  `2027-11-30`(잔여 12개월)이므로 4개월 EOS 대상에서 제외됩니다.

## 단계별 프롬프트로 EOS 판별·9대 사전 점검·안내문 다운로드·승인 기반 복구를 수행한다

### Step 1: 월 단위(4개월) 및 지원 플랜(Standard 대 LTS) 기준 EOS 대상 클러스터 식별

채팅창을 열고 첫 번째 프롬프트로 `/agent aks_upgrade_specialist`를 호출해 향후 4개월(월 단위
말일 기준) 이내 지원 종료 예정인 클러스터를 식별합니다.

```text
/agent aks_upgrade_specialist check-aks-eos-release-calendar 도구를 months_ahead=4로 실행하여
향후 4개월(월 단위 말일 기준) 이내 지원 종료 예정인 Private AKS 클러스터 현황과
SupportPlan(Standard vs LTS)별 판정 결과를 표로 정리해 줘.
```

![SRE Agent 채팅 Step 1 화면. check-aks-eos-release-calendar 도구가 3대 Private AKS 클러스터의 버전, 지원 플랜, 만료일, 잔여 개월 수를 비교해 aks-priv-02만 업그레이드 대상으로 선별한다](images/chat-step1-version-matrix.png)

에이전트는 `check-aks-eos-release-calendar` 도구를 실행해 일(day) 단위가 아닌 **월 단위(`cal_diff <= 4`)** 로
만료 시점을 계산합니다. 그 결과 버전 숫자가 낮은 `aks-priv-03`(`1.34.12`)은 `LTS (Premium)` 만료일
(`2027-11-30`, 잔여 12개월)을 적용해 제외하고, Standard 만료일(`2027-03-31`, 잔여 4개월)이 도래하는
`aks-priv-02`(`1.35.9 → 1.36`) 1대만 업그레이드 대상으로 정확히 추려냅니다.

### Step 2: 타깃 버전(1.36) 릴리스 노트 조회와 9대 업그레이드 사전 점검 실행

두 번째 프롬프트로 EOS 대상인 `aks-priv-02`에 대해 `mslearn-mcp`로 Kubernetes `1.36` 주요 변경사항을
조회하고, `evaluate-aks-upgrade-preflight` 도구로 9대 사전 점검을 수행한 뒤 고객 안내문(`aks-upgrade-notice.md`)과
다운로드 링크를 생성합니다.

```text
위에서 도출된 EOS 대상 클러스터(aks-priv-02, 1.35.9 -> 1.36)에 대해 mslearn-mcp로
Kubernetes 1.36 릴리스 노트 주요 변경사항을 확인하고, evaluate-aks-upgrade-preflight 도구
(cluster_filter="aks-priv-02", target_version="1.36", check_items="ALL")로 9대 사전 점검을
수행한 뒤, aks-eol-notice-and-history-workflow 스킬 양식에 맞춰 고객 안내문(aks-upgrade-notice.md)과
다운로드 링크를 생성해 줘.
```

![SRE Agent 채팅 Step 2 화면. mslearn-mcp와 evaluate-aks-upgrade-preflight 도구를 호출해 1.36 주요 변경사항과 aks-priv-02의 9대 사전 점검 결과를 분석한다](images/chat-step2-release-notes.png)

에이전트는 컨트롤 플레인과 데이터 플레인을 한 번에 스캔해 `aks-priv-02`의 9대 사전 점검 항목 중
다음 4개 항목에서 `FAIL`(`WARN`)을 검출합니다.

| 점검 번호 및 항목 | 판정 | 검출된 상세 원인 (`aks-priv-02`) |
| --- | --- | --- |
| **#1 서브넷 잔여 IP (`maxSurge`)** | **FAIL** | `/27` 서브넷(가용 27 IP)으로 노드풀 업그레이드 서지 노드 생성 시 `SubnetIsFull` 위험 |
| **#3 비정상·단일 파드** | **FAIL** | `prod/order-processor`(`CrashLoopBackOff`), `prod/payment-webhook`(`ImagePullBackOff`), `prod/inventory-api`(`replicas=1`) 검출 |
| **#6 PDB 드레인 차단 및 미설정** | **FAIL** | `prod/inventory-api` 단일 레플리카 워크로드에 PDB 미설정 |
| **#9 삭제된 Log Analytics 워크스페이스 연결** | **FAIL** | Defender 프로필이 삭제된 `law-sre-deleted-ghost` 워크스페이스를 참조하여 `WorkspaceResourceNotFound` 발생 위험 |

### Step 3: 5개 섹션 고객 안내문 생성 및 원클릭 마크다운 파일 다운로드

동일한 응답 하단에서 에이전트는 지식 베이스 템플릿(`aks-eol-notice-template-and-history.md`)에 맞춰
작성한 5개 섹션 고객 안내문(섹션 5는 실제 업그레이드 대상인 `aks-priv-02`만 포함하며, 서브섹션 5-1에
9대 사전 점검 상세 표 수록)을 출력하고 `./aks-upgrade-notice.md` 파일 다운로드 링크를 제공합니다.

![SRE Agent 채팅 Step 3 화면. 9대 사전 점검 상세 표가 포함된 고객 안내문과 aks-upgrade-notice.md 원클릭 다운로드 링크를 보여 준다](images/chat-step3-preflight-score.png)

채팅 화면의 `[📥 aks-upgrade-notice.md 파일 다운로드](/api/files/aks-upgrade-notice.md)` 링크를 클릭하면
세션 작업 디렉터리에 생성된 마크다운 원본 파일이 로컬 PC로 즉시 다운로드됩니다.

### Step 4: 비정상 파드 심층 진단과 승인 기반 즉시 복구 및 부분 재검증

마지막 프롬프트로 `aks-priv-02`에서 검출된 비정상 파드(`CrashLoopBackOff`, `ImagePullBackOff`)와
단일 레플리카 결함의 원인을 진단하고, 복구 후 점검 항목 `#3, #7, #8`만 빠르게 부분 재검증합니다.

```text
사전 점검에서 발견된 aks-priv-02 클러스터의 비정상 파드(CrashLoopBackOff / ImagePullBackOff) 및
단일 레플리카 원인을 상세 진단하고, 복구 조치를 실행해 정상 Running 상태로 만든 뒤
evaluate-aks-upgrade-preflight(cluster_filter="aks-priv-02", check_items="3,7,8")로 재검증해 줘.
```

![SRE Agent 채팅 파드 진단 및 복구 화면. 비정상 파드 원인을 진단하고 복구 후 점검 항목 3, 7, 8번이 PASS로 전환된 결과를 보여 준다](images/chat-pod-diagnostics.png)

에이전트는 `order-processor`의 비정상 종료 명령(`exit 1`), `payment-webhook`의 존재하지 않는 이미지 태그
(`nginx:nonexistent-tag-999`), `inventory-api`의 단일 레플리카(`replicas=1`)를 정상 이미지(`nginx:1.25-alpine`)와
다중 레플리카(`replicas=2`)로 복구한 뒤, `evaluate-aks-upgrade-preflight(check_items="3,7,8")`를 호출해
워크로드 관련 점검 항목이 모두 `PASS`로 전환된 것을 확인합니다.

## EOS 필터링·9대 사전 점검·파일 다운로드·권한 가드레일이 모두 작동하면 통과한다

| 검증 항목 | 통과 기준 |
| --- | --- |
| 월 단위 EOS 및 LTS 필터링 | `check-aks-eos-release-calendar(months_ahead=4)` 실행 시 `aks-priv-02`(`1.35.9` Standard)만 대상으로 선정되고 `aks-priv-03`(`1.34.12` LTS)과 `aks-priv-01`(`1.36.4` Standard)은 제외됨 |
| 9대 사전 점검 및 부분 재검증 | `evaluate-aks-upgrade-preflight`가 `check_items="ALL"` 및 `"3,7,8"` 부분 재검증을 모두 900자 이하(`ensure_ascii=False`)로 반환 |
| 마크다운 파일 원클릭 다운로드 | `./aks-upgrade-notice.md` 저장 후 `/api/files/<threadId>/aks-upgrade-notice.md`가 HTTP `200`으로 다운로드됨 |
| 워크로드 복구 후 `PASS` 전환 | `prod` 네임스페이스의 파드가 모두 `Running`으로 복구되고 `#3` 점검 항목이 `PASS`로 전환됨 |
| 권한 거버넌스(`Allow`/`Ask`/`Deny`) | 조회는 자동 실행되고, 복구 명령은 승인 게이트를 거치며, 파괴적 삭제 명령은 차단됨 |

## 결함 워크로드와 리소스 그룹을 삭제해 실습을 정리한다 { #lab-cleanup }

주입한 결함 워크로드만 정상 상태로 되돌리려면 `seed-faults.sh reset`을, 전체 실습 리소스 그룹을
삭제하려면 `cleanup.sh`를 실행합니다.

```bash
# 주입한 결함 워크로드를 정상 상태로 복원할 때
./scripts/seed-faults.sh reset

# 전체 실습 리소스 그룹을 삭제할 때
./scripts/cleanup.sh rg-private-aks-fleet
```

`az group exists -n rg-private-aks-fleet`가 `false`를 반환하면 모든 과금 리소스 정리가 완료된
것입니다.

## 공식 참고 자료

- [Azure SRE Agent network integration](https://learn.microsoft.com/azure/sre-agent/network-integration):
  Azure VNet 모드의 아웃바운드 경로, `/27` 이상 `Microsoft.App/environments` 위임 서브넷 요구 사항,
  기본 우회(Bypass) 목록 구성
- [Configure network controls](https://learn.microsoft.com/azure/sre-agent/configure-network-controls):
  VNet 사설 DNS 사용 설정과 Private Endpoint용 사설 DNS 영역 연결 절차
- [Network requirements for Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/network-requirements):
  방화벽 환경에서 허용해야 하는 필수 플랫폼·관찰 가능성 FQDN 및 포트
- [Python tools in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/python-code-execution):
  관리 ID 인증과 샌드박스 실행 제한
- [Agent permissions in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/permissions) 및
  [Tool access policies in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/tool-access-policies):
  관리형 역할과 `Allow` / `Ask` / `Deny` 도구 접근 정책 구성
- [Skills in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/skills),
  [Custom agents in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/sub-agents) 및
  [Agent hooks in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/agent-hooks):
  스킬 지침 구성, 서브에이전트 도구 바인딩, `PreToolUse` 차단 훅 동작
- [Live reports in Azure SRE Agent (preview)](https://learn.microsoft.com/azure/sre-agent/live-reports):
  에이전트 포털 내 실시간 Live Report 대시보드 구성
- [Create a private Azure Kubernetes Service (AKS) cluster](https://learn.microsoft.com/azure/aks/private-clusters):
  Private AKS의 Private Endpoint 및 `privatelink.<region>.azmk8s.io` 사설 DNS 구조
- [Supported Kubernetes versions in Azure Kubernetes Service (AKS)](https://learn.microsoft.com/azure/aks/supported-kubernetes-versions):
  Kubernetes 마이너 버전별 Standard 및 Long Term Support(LTS) 지원 수명 주기와 릴리스 캘린더
- [Upgrade an Azure Kubernetes Service (AKS) cluster](https://learn.microsoft.com/azure/aks/upgrade-aks-cluster) 및
  [Roll out node pool upgrades in Azure Kubernetes Service (AKS)](https://learn.microsoft.com/azure/aks/upgrade-aks-node-pools-rolling):
  순차 마이너 버전 업그레이드 규칙, `maxSurge` 서브넷 IP 요구 사항, PDB 드레인 동작
- [Azure virtual network traffic routing](https://learn.microsoft.com/azure/virtual-network/virtual-networks-udr-overview) 및
  [Azure Private Endpoint DNS configuration](https://learn.microsoft.com/azure/private-link/private-endpoint-dns):
  UDR(`VirtualAppliance`) 경로 지정과 사설 DNS 영역 해석 구조
