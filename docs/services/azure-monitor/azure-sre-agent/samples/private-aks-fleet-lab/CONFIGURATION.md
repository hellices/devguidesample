# 다중 허브·방화벽 Private AKS 사전 점검 실습 구성 상세

이 문서는 [다중 허브 Private AKS 업그레이드 사전 점검 실습](../../private-aks-multihub-preflight/index.md)의
네트워크 라우팅, 사설 DNS, 데이터 평면 RBAC, 그리고 **다중 클러스터 조회 시간을 4~20분에서
21~96초로 줄인 설계 결정과 실측 근거**를 정리한 참고 자료입니다.

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

## 다중 클러스터 조회 지연(4~20분) 원인 분석 및 30~60초 고속화 설계

초기 가이드 프롬프트를 그대로 실행했을 때 단일 클러스터 조회(`25~30초`)와 달리 다중 클러스터 점검에서는
한 턴당 **3분 38초 ~ 9분 25초(인프라 변경 포함 시 최대 20분 12초)** 가 소요되었습니다. 메시지 타임스탬프 전수 분석으로
확인한 5대 병목 원인과 해결 설계는 다음과 같습니다.

| 병목 원인 | 초기 동작 (최적화 전) | 고속화 설계 (최적화 후) | 설계 구분 |
| --- | --- | --- | --- |
| 1. N+1 개별 CLI / `kubectl` 반복 호출 | 10대 클러스터에 `az aks get-upgrades`·`nodepool list`를 개별 호출(`azCli` 23회)하고, `get pods`·`deploy`·`pdb`를 분리 호출(`kubectl` 27~34회) | `az aks list --query ...` **단 1회 배치 호출(3초)** 로 10대 버전을 모두 수집하고, 클러스터당 `kubectl get pods,deploy,pdb -n <ns>` **1회 복합 호출**로 통합 | 근본적 아키텍처 개선 (Best Practice) |
| 2. 도구 출력 앞부분 잘림(Head-Truncation) 재조회 | SRE Agent 런타임은 도구 출력이 약 1.5~2KB를 넘으면 **앞부분을 절단**함. 잘린 앞쪽 데이터를 다시 얻으려고 에이전트가 느린 CLI 쿼리를 3~4회 재실행(+60~140초) | `evaluate_aks_upgrade_preflight.py` 등 모든 Python 도구가 불필요한 공백·장문 배열을 빼고 **900자 이하 압축 JSON**만 반환하도록 설계 | 근본적 아키텍처 개선 (도구 단 Projection) |
| 3. 장기 인프라 변경의 동기식 `sleep` 대기 | 노드풀 추가·증설·업그레이드 시 VMSS 프로비저닝 완료(5~15분)까지 한 턴 안에서 `sleep`과 `az aks show`를 수십 회 폴링 | 장기 실행 작업은 `--no-wait` 비동기 트리거(15초 내 반환)와 사후 상태 확인 턴으로 분리 | 근본적 아키텍처 개선 (비동기 분리) |
| 4. `/agent` 슬래시 호출 시 자식 Subagent 이중 위임 | Workspace 모드(`adc: true`)에서 `/agent` 슬래시 입력 시 내부 `Task` 자식 에이전트를 생성해 2분 이상 대기 후 메인 에이전트가 또 재요약(+45초) | `@aks_fleet_specialist:` 직접 멘션 호출 및 지침에 `자식 Task 서브에이전트 중복 생성 금지` 명시 | 프리뷰 플랫폼 Workaround |
| 5. 무제한 MCP / Memory 검색 루프 | 한 턴 안에서 `mslearn` MCP를 19회, `SearchMemory`를 9회까지 반복 호출(+90~150초) | 지침과 스킬에 한 턴당 `SearchMemory` 최대 1회, `mslearn` MCP 최대 1~2회 상한 명시 | 프리뷰 플랫폼 Workaround |

### 전/후 실측 시간 비교 (Korea Central 에이전트 ➔ Australia East 10대 사설 AKS)

| 시나리오 단계 | 최적화 전 실측 (메시지 수) | 최적화 후 실측 (메시지 수) | 단축률 |
| --- | ---: | ---: | ---: |
| 1단계: 10대 사설 AKS 버전·EOL·우선순위 식별 | `218.5s ~ 246.2s` (47~69개) | **`24.6s` (7개)** | **-89%** |
| 2단계: K8s `1.36 → 1.37` 변경사항(`mslearn` MCP) 분석 | `156.2s` (34개, MCP 19회) | **`21.2s` (5개, MCP 1회)** | **-86%** |
| 3단계: 3대 사설 AKS 방화벽(`TCP 443`) + `kubectl` + 7대 채점 | `249.6s ~ 389.9s` (56~71개) | **`96.4s` (13개)** | **-62~75%** |
