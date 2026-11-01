---
name: private-aks-upgrade-preflight
description: Fast 30-60s Private AKS version upgrade target identification, release-note analysis via MS Learn MCP, and 7-point preflight scoring over Multi-Hub Firewall UDR routes.
---

## 고속 실행 절차 (한 턴당 30~60초 완료 규칙)

### 1. 업그레이드 대상 자동 식별 요청 시 (도구 호출 최대 3회)
1. `RunAzCliReadCommands`로 아래 **단일 명령 1회**만 실행하여 다중 클러스터의 컨트롤 플레인·노드풀 버전과 전원 상태를 한 번에 가져온다:
   `az aks list -g <RG_NAME> --query "sort_by(@,&name)[].{Cluster:name,CP:currentKubernetesVersion,NP:agentPoolProfiles[0].currentOrchestratorVersion,Power:powerState.code,State:provisioningState}" -o table`
2. 업그레이드 가능 버전 확인은 대표 클러스터 1대(`az aks get-upgrades -g <RG_NAME> -n <CLUSTER_01> -o table`)에 대해서만 **1회** 실행한다 (전체 클러스터에 반복 실행 금지).
3. EOL 및 우선순위 등급(`P0`: 1.34 이하 또는 장애 파드 보유, `P1`: 1.35.x 또는 CP/NP 버전 불일치, `P2`: 1.36.4 정상)을 즉시 표로 매핑해 출력한다.

### 2. 버전별 변경사항 분석 요청 시 (도구 호출 최대 2회)
1. `mslearn-mcp_microsoft_docs_search`를 **1회** 호출해 목표 버전 릴리즈 노트를 검색하고, 필요 시 상위 문서 1건만 `microsoft_docs_fetch`로 읽는다 (추가 반복 검색 금지).
2. 버전 간 주요 변경사항(1.37 LocalDNS 조건부 활성화 및 UDP/TCP 53 요구사항, `ama-metrics` 네임스페이스 Secret 권한 등), Deprecated API, 노드풀 Surge/Drain/PDB 영향도를 한국어 표로 정리한다.

### 3. 업그레이드 7대 사전 점검 요청 시 (클러스터당 `kubectl` 1회 복합 호출)
1. `verify-multihub-firewall-udr-route`를 대상 클러스터들에 병렬로 1회씩 호출한다.
2. `RunKubectlReadCommand`는 클러스터마다 `get pods`, `get deploy`, `get pdb`를 나누어 부르지 말고, 반드시 **`kubectl get pods,deploy,pdb -n <ns>` 단일 복합 명령으로 클러스터당 1회만** 호출한다.
3. 확인된 수치(`unhealthy_pod_count`, `single_replica_deployments`, `blocking_pdb_count`)를 `evaluate-aks-upgrade-preflight`에 전달해 점수(0~100점)와 `READY` / `CONDITIONAL` / `BLOCKED` 판정 및 조치 CLI를 표로 출력한다.
