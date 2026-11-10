# 엔터프라이즈 Private AKS 점프박스 대체 데이터플레인 조회 SOP (`3건 이하 kubectl` vs `다중 값 Python REST API`)

> ⚠️ **중요 원칙 (하드코딩 금지 — 모든 예시 코드는 형식 참고용)**:
> 본 문서의 명령어와 파이썬 스니펫에 등장하는 버전, 네임스페이스, 어노테이션 이름은 **호출 형태를 설명하기 위한 예시(Example)일 뿐**입니다.
> 에이전트는 절대 예시 텍스트를 실제 조회 결과로 단정해서는 안 되며, **반드시 실시간 조회 결과(실제 클러스터 및 실제 파드/인그레스 상태)만** 보고해야 합니다.

---

## 1. 호출 횟수에 따른 조회 도구 선택 규칙 (필수 준수)

사설 AKS 데이터플레인(Pod, Event, PDB, Ingress, Node 등)을 조회할 때는 **예상 호출 횟수가 3건 이하인지, 4건 이상의 다중 값 조회인지**에 따라 반드시 아래 방식으로 분기한다.

### A. 3건 이하의 단건·소량 조회 ➔ 내장 `RunKubectlReadCommand` 사용
- **적용 대상**:
  - 특정 단일 클러스터에서 파드 1~2개의 상세 상태(`kubectl describe pod`), 컨테이너 로그(`kubectl logs`), 또는 특정 네임스페이스 리소스 목록을 **총 3회 이하의 명령어로 즉시 확인할 수 있는 경우**
- **호출 예시 *(구문 예시일 뿐이며 실제 클러스터·네임스페이스·파드명을 대입할 것)***:
  - `kubectl get pods -n <namespace> -o wide`
  - `kubectl describe pod <pod-name> -n <namespace>`
  - `kubectl logs <pod-name> -n <namespace> --tail=50`

### B. 4건 이상의 다중 값·다중 클러스터 복합 조회 ➔ Python REST API 코드 작성 및 호출
- **적용 대상**:
  - 여러 클러스터(`N대`) 또는 여러 리소스 종류(`pods`, `deployments`, `poddisruptionbudgets`, `ingresses`, `nodes` 등 4개 이상)를 한꺼번에 교차 분석해야 하는 경우
  - `RunKubectlReadCommand`를 4번 이상 반복 호출하면 왕복 지연이 누적되므로, **사전 등록된 Python 도구(`evaluate-aks-upgrade-preflight`)를 호출하거나 아래와 같이 Python REST API 코드를 작성해 1회 실행으로 일괄 조회**한다.
- **사설 AKS Python REST API 일괄 조회 표준 패턴 *(작성 형태 예시)***:
  ```python
  # [예시 코드 형태] 실제 실행 시에는 ARG에서 조회한 실제 privateFQDN과 실시간 API 응답만 사용한다.
  import requests, urllib3
  from azure.identity import DefaultAzureCredential

  urllib3.disable_warnings()
  cred = DefaultAzureCredential()
  arm_tok = cred.get_token("https://management.azure.com/.default").token
  # AKS AAD Server 고정 리소스 ID로 K8s API 토큰 발급
  k8s_tok = cred.get_token("6dae42f8-4368-4678-94ff-3960e28e3630/.default").token
  k8s_hdr = {"Authorization": f"Bearer {k8s_tok}"}

  # VNet 경유 사설 AKS API 서버(https://<privateFQDN>) REST 엔드포인트 일괄 호출
  pods = requests.get(f"https://{private_fqdn}/api/v1/pods", headers=k8s_hdr, verify=False, timeout=8).json().get("items", [])
  pdbs = requests.get(f"https://{private_fqdn}/apis/policy/v1/poddisruptionbudgets", headers=k8s_hdr, verify=False, timeout=8).json().get("items", [])
  ingresses = requests.get(f"https://{private_fqdn}/apis/networking.k8s.io/v1/ingresses", headers=k8s_hdr, verify=False, timeout=8).json().get("items", [])
  ```

---

## 2. 데이터플레인 주요 점검 포인트 (실시간 API 응답 기준)
1. **비정상 파드 및 스케줄링 실패 판별**:
   - **진정한 스케줄링 실패(`Unschedulable Pending`)**: `status.phase == "Pending"`이면서 `spec.nodeName`이 아직 할당되지 않은 파드(`conditions`의 `PodScheduled` 메시지 확인).
   - **컨테이너 기동/이미지 오류**: `spec.nodeName`은 할당되었으나 `status.containerStatuses[].state.waiting.reason`이 `CrashLoopBackOff`, `ImagePullBackOff`, `ErrImagePull`인 파드.
2. **Ingress Controller 및 라우팅 규칙 호환성**:
   - 클러스터 내 설치된 Ingress Controller(`ingress-nginx` 등)의 실제 이미지 태그/버전과 Ingress 리소스의 위험 어노테이션(`snippet` 계열 등) 사용 여부를 실시간 조회하여 업그레이드 호환성을 판별한다.

