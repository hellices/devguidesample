# 엔터프라이즈 Private AKS 업그레이드 9대 사전 점검 기준 · 조회 방식 분기 규칙 및 선행 조치 가이드

> ⚠️ **중요 원칙 (하드코딩 금지 — 모든 예시 값은 형식 참고용)**:
> 본 문서에 포함된 버전, 점수, 명령어 인자(`<namespace>`, `<pdb-name>` 등)는 **판정 규칙과 명령어 구문 형태를 설명하기 위한 예시(Example)일 뿐**입니다.
> 에이전트는 절대 문서 내 예시 값을 그대로 결과로 출력하지 않으며, **반드시 실시간 API 도구 호출 결과(실제 클러스터명, 실제 네임스페이스, 실제 리소스명)만 사용**해야 합니다.

---

## 1. 데이터 조회 시 도구 선택 기준 (`3건 이하 kubectl` vs `다중 값 조회 시 Python API 코드 호출`)

사설 AKS 클러스터 및 Azure 리소스 상태를 조회할 때는 호출 횟수와 조회 범위에 따라 반드시 아래 기준을 따른다.

| 조회 상황 | 사용할 조회 방식 | 상세 실행 지침 |
| :--- | :--- | :--- |
| **① EOS 일정 확인 및 9대 사전 점검** | **사전 등록된 Custom Python API 도구 호출**<br>(`check-aks-eos-release-calendar`, `evaluate-aks-upgrade-preflight`) | • 이미 검증된 Python REST API 도구가 1회 호출로 MS Learn 파싱, ARG 조회, 9대 항목(전체 `ALL` 또는 선택 번호 `check_items`) 채점을 수행하므로 최우선 호출한다. |
| **② 3건 이하의 단순·단건 K8s 조회** | **내장 `RunKubectlReadCommand` 도구 호출** | • 특정 파드 1~2개의 상세 이벤트(`kubectl describe pod`), 로그(`kubectl logs`), 단일 리소스 상태 등 **3회 이하의 명령어 호출로 끝나는 경우**에는 내장 `RunKubectlReadCommand`를 직접 호출한다. |
| **③ 4건 이상의 복합 값·다중 클러스터 조회** | **Python REST API 코드 작성 및 일괄 호출** | • 여러 네임스페이스/리소스/클러스터의 값을 교차 비교해야 해서 `kubectl`을 4번 이상 반복 호출해야 하는 경우, 개별 `kubectl`을 여러 번 부르지 말고 **`DefaultAzureCredential`로 ARM 토큰(`https://management.azure.com/.default`) 및 AKS AAD 토큰(`6dae42f8-4368-4678-94ff-3960e28e3630/.default`)을 발급받아 K8s REST API(`https://<privateFQDN>/...`, `verify=False`)를 일괄 조회하는 Python 코드를 작성·호출**한다. |

---

## 2. Private AKS 업그레이드 9대 사전 점검 체크리스트 판정 기준 (총점 100점)

`evaluate-aks-upgrade-preflight(cluster_name, check_items)` 도구는 아래 9가지 항목(평상시 `check_items="ALL"`, 일부 점검 시 `"1,3,4"` 등 번호 지정)을 실시간 Azure ARM REST API 및 VNet 경유 Kubernetes REST API로 평가한다.

| 번호 | 점검 항목 (`checklistItems` 키) | 배점 | 실시간 API 조회 대상 및 `FAIL` / `WARN` 판정 기준 | 표준 선행 조치 가이드 *(아래 명령어는 구문 예시일 뿐이며 실제 리소스명을 대입할 것)* |
| :---: | :--- | :---: | :--- | :--- |
| **①** | **애플리케이션 Pod 고가용성 구성**<br>(`1_podHaConfig`) | 10점 | • 시스템 네임스페이스 제외 Deployment의 `spec.replicas == 1` 여부<br>• 컨트롤러(`ownerReferences`)가 없는 Naked Pod 존재 여부<br>• `CrashLoopBackOff` / `ImagePullBackOff` 비정상 파드 존재 여부 | • 단일 레플리카 워크로드 다중화:<br>  *(예시)* `kubectl scale deployment/<deploy-name> -n <namespace> --replicas=2`<br>• 비정상 파드 원인 해결 후 재기동 |
| **②** | **`HostPath` / `emptyDir` 및 Local PV 존재 여부**<br>(`2_localStorage`) | 10점 | • 파드 `spec.volumes` 내 노드 로컬 디스크에 종속된 `hostPath` 또는 데이터 유실 위험이 있는 `emptyDir` 마운트 유무 | • 노드 Drain/Reimage 시 로컬 데이터가 초기화되므로 Azure Disk/Files CSI 영구 볼륨으로 전환하거나 캐시 재생성 영향도 사전 확인 |
| **③** | **Pod 스케줄링 제약 조건 확인**<br>(`3_schedulingConstraints`) | 15점 | • `status.phase == "Pending"`이면서 `spec.nodeName`이 할당되지 않은 스케줄링 불가 파드 유무<br>• 파드 CPU Request 합계가 노드 `allocatable.cpu`의 50%를 초과하여 Surge/Drain 시 이동 불가 위험 유무 | • 과도한 CPU/Memory Request 조정 또는 `nodeSelector` / `nodeAffinity` 제약 완화 |
| **④** | **PodDisruptionBudget (PDB) 설정 확인**<br>(`4_pdbConfig`) | 15점 | • `/apis/policy/v1/poddisruptionbudgets`에서 `status.disruptionsAllowed == 0` 인 차단 PDB 존재 여부 (존재 시 노드 Drain 무한 대기 발생) | • 업그레이드 작업 시간 동안 허용 중단 수 완화 (`Ask` 승인 후 실행):<br>  *(예시)* `kubectl patch pdb <pdb-name> -n <namespace> --type=merge -p '{"spec":{"maxUnavailable":1}}'` |
| **⑤** | **Kubernetes API Deprecation 및 애드온 호환성**<br>(`5_apiAndAddonCompat`) | 10점 | • `ingress-nginx` 컨트롤러 구버전(`v1.9.x` 이하) 사용 여부 및 Ingress 리소스 내 `snippet` 어노테이션 사용 여부 | • K8s 업그레이드 전 `ingress-nginx` 컨트롤러를 호환 버전(`v1.10+`/`v1.11+`)으로 선행 업그레이드 및 snippet 제거 |
| **⑥** | **Graceful Shutdown 설정 확인**<br>(`6_gracefulShutdown`) | 10점 | • 애플리케이션 컨테이너에 `readinessProbe` 또는 `lifecycle.preStop` 훅이 누락되어 노드 Drain 시 순단 위험이 있는지 점검 | • Deployment 매니페스트에 `readinessProbe` 및 `preStop` (`sleep 5` 등) 추가 권고 |
| **⑦** | **노드풀 서브넷 가용 IP 확인**<br>(`7_subnetAvailableIps`) | 10점 | • ARM Subnet `addressPrefix` 및 `ipConfigurations` 기준 사용률이 `80%` 이상이거나 잔여 IP가 `10개 미만`인지 점검 | • 업그레이드 Surge 노드 생성 전 서브넷 CIDR 여유 IP 확보 또는 `maxSurge` 조정 |
| **⑧** | **AKS Identity VNet 권한 확인**<br>(`8_aksIdentityVnetRbac`) | 10점 | • 클러스터(특히 타 리소스 그룹의) VNet에 AKS 관리 ID(UAMI/Kubelet Identity)의 `Network Contributor`(`4d97b98b-1d4f-4787-a291-c67834d212e7`) 역할 할당이 존재하는지 점검 | • 누락된 VNet 범위(Scope)에 `Network Contributor` 역할 할당 (`Ask` 승인 후 실행):<br>  *(예시)* `az role assignment create --assignee-object-id <uami-principal-id> --assignee-principal-type ServicePrincipal --role "Network Contributor" --scope <vnet-resource-id>` |
| **⑨** | **MDC / 모니터링 Log Analytics Workspace ID 확인**<br>(`9_mdcLogAnalyticsWorkspaceId`) | 10점 | • `addonProfiles.omsagent.config.logAnalyticsWorkspaceResourceID`에 연결된 워크스페이스가 실제 존재하는지(ARM `HTTP 200` vs `404 NotFound` 유령 참조) 점검 | • 이미 삭제된 워크스페이스를 참조 중인 경우 유효한 Log Analytics Workspace로 재연결하거나 모니터링 애드온 갱신 (`Ask` 승인 후 실행) |

---

## 3. 종합 판정(`verdict`) 기준
- **`READY`**: 점검 점수 `90점 이상`이면서 `FAIL`/`WARN` 특이사항이 `0건`인 상태 (즉시 업그레이드 가능)
- **`CONDITIONAL`**: `FAIL`(차단 요인)은 없으나 `WARN`(단순 권고 항목)만 존재하는 상태 (주의사항 인지 후 업그레이드 진행 가능)
- **`BLOCKED`**: 점검 항목 중 하나라도 `FAIL`이 존재하거나 총점이 `75점 이하`인 상태 (반드시 위 표의 선행 조치를 완료한 뒤 업그레이드 진행)

