# Private AKS 버전 관리(EOL) 우선순위(P0/P1/P2) 정책 및 7대 사전 점검 기준

## 1. Kubernetes 버전별 지원 종료(EOL) 일정 및 P0 / P1 / P2 업그레이드 우선순위 등급표

모든 Private AKS 클러스터는 아래 기준표에 따라 `P0`, `P1`, `P2` 중 하나의 등급으로 분류한다.

| 우선순위 등급 | 분류 조건 (현재 K8s 버전 또는 상태) | 커뮤니티 마이너 버전 지원 종료(EOL) 일정 | 권장 목표 버전 | 조치 기한 및 운영 지침 |
|---|---|---|---|---|
| **P0 (Urgent / 즉시 조치 대상)** | • 현재 마이너 버전이 `1.34` 이하(`1.34.x`, `1.33.x` 등)인 클러스터<br>• 또는 클러스터 내부에 `ImagePullBackOff` / `CrashLoopBackOff` 비정상 파드가 존재하는 상태 | • `1.34`: 2026-11-30 (LTS: 2027-11-30)<br>• `1.33`: 지원 종료 | `1.35.9` 경유 ➔ `1.36.4` | 즉시 조치 (1주 이내)<br>지원 종료 임박 대상이므로 최우선 업그레이드 수행 (단, 비정상 파드가 있으면 선행 복구 후 업그레이드) |
| **P1 (Planned / 계획 업그레이드 대상)** | • 현재 마이너 버전이 `1.35.x`인 클러스터<br>• 또는 컨트롤 플레인 버전(`1.37.0`)과 노드풀 버전(`1.36.4`)이 불일치(Version Skew)하는 클러스터 | • `1.35`: 2027-03-31 (LTS: 2028-03-31) | `1.36.4` 또는 노드풀 `1.37.0` 동기화 | 계획 조치 (1개월 이내)<br>차기 정기 점검 윈도우에 업그레이드 또는 노드풀 버전 동기화 수행 |
| **P2 (Pre-check / 사전 호환성 점검 및 카나리 대상)** | • 현재 컨트롤 플레인과 노드풀이 모두 안정 버전인 `1.36.x`(`1.36.4`)로 일치하는 클러스터 | • `1.36`: 2027-06-30<br>• `1.37`: 2027-10-31 | `1.37.0` | 사전 점검 대상 (분기 내)<br>차기 `1.37.0` 전환을 대비하여 7대 사전 점검 체크리스트를 수행하고 카나리 검증 진행 |

## 2. Private AKS 업그레이드 9대 사전 점검 체크리스트 (`PASS` / `FAIL` 기준)

하나라도 `FAIL`이 있으면 전체 판정(`overallStatus` / `verdict`)을 `FAIL`로 표기하고 선행 조치를 안내한다.

1. **`1_pod_ha` — 애플리케이션 Pod 고가용성 구성 (`PASS` / `FAIL`)**: 컨트롤러(`ownerReferences`)가 없는 Naked Pod 존재 여부, 단일 레플리카(`replicas: 1`) 또는 모든 레플리카가 단일 노드(`nodeName`)에 편중 배치된 워크로드, 비정상 파드 존재 여부 점검 (`kube-system` 등 시스템 네임스페이스 및 `DaemonSet`/`Job` 제외).
2. **`2_local_storage` — `hostPath` / `emptyDir` 및 Local Storage PV 존재 여부 (`PASS` / `FAIL`)**: 비-DaemonSet 파드의 `volumes[].hostPath`·`emptyDir` 사용 여부 및 클러스터 내 `spec.local` / `spec.hostPath` PV 존재 여부 점검.
3. **`3_scheduling_constraints` — Pod 스케줄링 제약 조건 (`PASS` / `FAIL`)**: `nodeSelector`, `requiredDuringSchedulingIgnoredDuringExecution` NodeAffinity 등으로 인해 노드 드레인 시 이동 가능한 대체 노드가 부족한 파드 점검.
4. **`4_pdb_disruptions` — PDB 설정 확인 (`PASS` / `FAIL`)**: `status.disruptionsAllowed == 0`인 `PodDisruptionBudget` 존재 여부 점검.
5. **`5_api_deprecation` — Kubernetes API Deprecation 확인 (`PASS` / `FAIL`)**: 타깃 K8s 버전에서 제거된 `apiVersion`(`last-applied-configuration` 어노테이션, Helm Secret, 또는 `apiserver_requested_deprecated_apis` 메트릭) 존재 여부 점검.
6. **`6_graceful_shutdown` — Graceful Shutdown 설정 여부 (`PASS` / `FAIL`)**: 컨테이너(K8s 1.29+ 네이티브 사이드카 포함)의 `livenessProbe`, `readinessProbe`, `lifecycle.preStop`(`exec`/`httpGet`/`sleep`) 설정 여부 점검.
7. **`7_subnet_ips` — 노드풀 서브넷 가용 IP 확인 (`PASS` / `FAIL`)**: CNI 모드(Overlay vs Node Subnet) 및 `maxSurge` 기준 필요 IP 대비 서브넷 잔여 IP 충족 여부(`90%` 이하 사용) 점검.
8. **`8_uami_permissions` — AKS Identity(UAMI) 권한 확인 (`PASS` / `FAIL`)**: 클러스터 Control Plane UAMI가 사용 중인 VNet/Subnet(및 UDR)에 `Network Contributor` 권한을 보유하고 있는지 점검.
9. **`9_mdc_law_reference` — AKS MDC / Monitoring의 Log Analytics Workspace ID 확인 (`PASS` / `FAIL`)**: `securityProfile.defender.logAnalyticsWorkspaceResourceId` 등이 이미 삭제된(`404 ResourceNotFound`) 워크스페이스를 참조하고 있지 않은지 점검.

## 3. 파드 장애 유형별 권장 복구 가이드 기준

- **`ImagePullBackOff` / `ErrImagePull`**: 직전 정상 이미지(`docker.io/library/nginx:1.25-alpine`)로 롤백하는 `kubectl set image` 명령 제시 및 반영 후 파드 상태 재검증.
- **`CrashLoopBackOff`**: 비정상 시작 커맨드(`command`/`args`) 확인 후 정상 엔트리포인트(`["nginx", "-g", "daemon off;"]`)로 복구하는 `kubectl patch deployment` 명령 제시 및 재검증.
