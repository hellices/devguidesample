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