# Private AKS 통합 운영 및 고속 사전 점검 글로벌 지침

1. **고속 실행(30~60초) 5대 필수 가드레일**:
   - **자식 Subagent 중복 생성 금지**: `@aks_fleet_specialist:` 또는 `/agent`로 호출된 경우 내부 `Task` 서브에이전트를 다시 생성하지 말고 현재 에이전트가 직접 도구를 호출해 즉시 답변한다.
   - **다중 클러스터 버전 일괄 1회 조회**: 클러스터마다 `az aks show`나 `az aks nodepool list`를 개별 호출하지 말고, 반드시 `az aks list -g <RG_NAME> --query "sort_by(@,&name)[].{Cluster:name,CP:currentKubernetesVersion,NP:agentPoolProfiles[0].currentOrchestratorVersion,Power:powerState.code,State:provisioningState}" -o table` **단 1회 호출**로 전체 버전을 수집한다. `az aks get-upgrades`는 대표 클러스터 1대에서만 1회 호출한다.
   - **데이터 플레인(`kubectl`) 클러스터당 1회 복합 호출**: 클러스터 내부 스캔 시 `get pods`, `get deploy`, `get pdb`, `get nodes`를 따로 호출하지 말고, 클러스터당 `kubectl get pods,deploy,pdb -n <ns>` (또는 `-A`) **단 1회 복합 명령**으로 묶어서 실행한다.
   - **검색 횟수 상한**: 한 턴당 `SearchMemory`는 최대 1회, `mslearn-mcp` 공식 문서 도구는 최대 2회(검색 1회 + 문서 조회 1회)까지만 호출한다. 응답 도중 워크스페이스 메모리 파일(`memories/*.md`)을 편집하지 않는다.
   - **장기 실행 작업 비동기 처리**: 노드풀 추가·스케일링·업그레이드(`az aks nodepool add/scale`, `az aks upgrade`)는 채팅 턴 안에서 `sleep`으로 대기하지 말고 `--no-wait` 옵션을 사용해 즉시 반환하거나 권장 CLI로 제시한다.

2. **Private AKS 데이터 플레인(`kubectl`) 표준 도구 규칙**:
   - Private AKS 클러스터 내부(Node, Pod, Deployment, PDB, Event, Log)를 조회할 때는 샌드박스 `bash`나 `az aks command invoke` 대신 내장 도구인 `RunKubectlReadCommand` (`AKSClusterResourceId` 지정)를 사용한다.

3. **언어 및 보고 형식**:
   - 모든 분석 결과와 권장 조치는 간결한 한국어 표(Table) 중심으로 요약 보고한다.
