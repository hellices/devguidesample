# Azure SRE Agent 이벤트 기반 장애 분석 실습

Azure Container Apps에 장애를 세 번 주입하고, Azure Monitor 경고를 받은 Azure SRE Agent가 실제로 조사·결론까지 도달하는지 확인합니다. 제품 개요는 [Azure SRE Agent 소개](../azure-sre-agent.md)를 먼저 읽어 주세요.

> ⚠️ 이 실습은 실제 Azure 리소스를 만들고 **과금**합니다. 끝나면 반드시 [정리](#정리) 절차로 지우세요.

## 결과물

| 산출물 | 위치 |
|---|---|
| 시나리오별 Agent 조사 타임라인(PNG/GIF/Markdown) | `assets/captures/s1`, `s2`, `s3` |
| 원본 API 근거와 실행 상태 | `evidence/`(Git 제외) |
| 시나리오별 10점, 종합 30점 만점 채점 결과 | `evidence/scorecard.json` |

## 비용과 안전 경계

배포가 만드는 과금 대상은 다음과 같습니다. 금액은 구독·지역·사용량에 따라 달라지므로 [Azure 가격 계산기](https://azure.microsoft.com/pricing/calculator/)로 확인하세요.

- Container Apps 환경과 앱 1개(0.5 vCPU / 1Gi, 최소 replica 1이라 유휴 상태에도 과금됩니다)
- Container Registry Basic
- Log Analytics 작업 영역(PerGB2018, 30일 보존)과 Application Insights 수집량
- Storage 계정(Standard_LRS)
- 1분 주기 로그 검색 경고 규칙 3개(평가 주기가 짧을수록 규칙당 단가가 올라갑니다)

Azure SRE Agent는 이 실습이 만들지 않습니다. 미리 만들어 둔 Agent를 사용하며 [별도로 과금](https://azure.microsoft.com/pricing/details/sre-agent/)됩니다.

안전 경계는 스크립트가 강제합니다.

- 현재 azd 환경이 가리키는 구독과 `az account show`의 활성 구독이 다르면 실행을 거부합니다.
- 리소스 그룹에 `purpose=sre-agent-event-lab`과 `azd-env-name=<현재 environment>` 태그가 모두 없으면 거부합니다.
- 한 번에 한 시나리오만 실행하며, 이전 시나리오가 복구·캡처될 때까지 다음 시나리오를 막습니다.
- 응답 계획은 모두 `Review` 모드로 두어 Agent가 승인 없이 변경하지 못하게 합니다.
- `evidence/`에는 비밀 값, 연결 문자열, 액세스 토큰을 저장하지 않습니다.

## 사전 조건

- `az`, `azd`, `jq`, `curl`, `python3`
- `az extension add --name log-analytics` (`az monitor log-analytics query` 제공)
- `az login`과 `azd auth login` — 두 CLI는 자격 증명을 따로 관리합니다.
- 구독 Contributor, 역할 할당을 위한 Owner 또는 User Access Administrator
- Azure SRE Agent를 만들 수 있는 [지원 지역](https://learn.microsoft.com/azure/sre-agent/supported-regions) 접근 권한
- 브라우저에서 `https://sre.azure.com` 및 `*.azuresre.ai` 접근
- Agent에 연결할 GitHub 저장소 권한
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — `app/.venv`를 만드는 `scripts/setup-venv.sh`가 이 도구만 사용하며, 사내 프록시로 구성된 `uv`의 인덱스 설정을 그대로 씁니다. 공개 PyPI로 우회하는 `pip` 폴백은 없습니다.

이 실습의 모든 명령은 아래에서 한 번만 진입하는 이 디렉터리를 기준으로 합니다.

```bash
cd monitor/sre-agent-event-lab
```

로컬 검증만 먼저 해 보려면 다음을 실행합니다.

```bash
./scripts/setup-venv.sh
app/.venv/bin/python -m pytest app -q

bash -n scripts/*.sh
az bicep build --file infra/main.bicep --stdout >/dev/null
```

## azd 환경 만들기

```bash
azd env new sre-event-lab --location koreacentral
```

`--subscription`을 생략하면 azd가 로그인된 계정의 구독 목록에서 고르게 합니다. 특정 구독을 고정하려면 `--subscription <YOUR_SUBSCRIPTION_ID>`를 붙이세요. 리소스 그룹 이름은 지정하지 않으면 `rg-<environment 이름>`이 됩니다.

`.env.example`은 스크립트가 읽는 설정 이름과 허용 기본값만 적어 둔 참고 파일입니다. 값을 바꾸려면 `azd env set <NAME> <VALUE>`로 현재 azd 환경에 저장합니다.

## 배포

```bash
mkdir -p evidence
azd up 2>&1 | tee evidence/deploy.log
```

배포는 두 단계입니다. 로컬 Docker는 필요 없습니다.

1. **provision 단계** — Bicep이 ACR, 워크로드 ID(user-assigned managed identity), 그 ID의 AcrPull 역할 할당, 그리고 공개 placeholder 이미지(80 포트)로 뜨는 Container App까지 만듭니다. 이어지는 postprovision hook(`scripts/azd-postprovision-local.sh`)은 `scripts/setup-venv.sh`로 `app/.venv`만 준비하고(`uv venv` + `uv pip install -r requirements-dev.txt`) Azure를 전혀 건드리지 않습니다. 즉 `azd provision`만 실행하면 앱은 계속 placeholder 상태입니다.
2. **deploy 단계** — postdeploy hook(`scripts/azd-deploy-app.sh`)이 워크로드 ID의 **AcrPull** 할당이 ACR 스코프에 정확히 보일 때까지 최대 5분(`SRE_ACR_PULL_TIMEOUT_SECONDS`) 기다린 뒤에야 ACR 클라우드 빌드 → registry/identity 설정 → ingress 8000 이동 → 이미지 교체 → revision·`/healthz` 확인 순서로 진행합니다. 역할이 끝내 보이지 않으면 아무것도 빌드·교체하지 않고 실패합니다.

`azd up`은 이 두 단계를 순서대로 실행하므로 위 명령 하나로 충분합니다. 단계별로 나눠 실행하거나 다시 실행하려면:

```bash
azd provision           # 인프라 + placeholder + 로컬 venv
azd deploy              # AcrPull 대기 → 빌드 → 이미지 교체 → 헬스체크
azd hooks run postdeploy   # 배포 단계만 다시 실행
```

postprovision 단계가 실패하면 로컬 환경만 실패한 것입니다. `./scripts/setup-venv.sh`로 그 단계를 고친 뒤 `azd deploy`로 앱 배포를 마무리하세요.

성공 조건은 provision 성공, 활성 revision `Healthy`, `/healthz` HTTP 200 세 가지입니다.

## Azure SRE Agent 설정

포털에서만 할 수 있는 설정이 남아 있습니다. 저장소 연결, 지식 문서 업로드, **Azure Monitor incident platform** 연결, `Review` 모드 응답 계획, 역할 할당을 [guides/01-agent-setup.md](guides/01-agent-setup.md)가 순서대로 안내합니다.

기본 실습에는 Logic App bridge를 배포하지 않습니다. 제품 표준 경로는 Azure Monitor를 incident platform으로 연결하는 것이고, 예전 실측에서 쓰던 Action Group + Logic App 인증 경로는 레거시 기록으로만 남아 있습니다([validation-results.md](validation-results.md)).

## 점검과 승인

```bash
./scripts/lab.sh doctor
./scripts/lab.sh baseline
./scripts/lab.sh acknowledge agent-setup
```

`doctor`는 `CHECK<TAB>STATUS<TAB>DETAIL` 한 줄씩 출력하고 `FAIL`이 하나라도 있으면 종료 코드 1을 반환합니다. 저장소 연결, 지식 원본, incident platform, 응답 계획은 공식 안정 API로 읽을 수 없어 항상 `MANUAL`입니다. `Python environment` 행은 `app/.venv`와 Pillow가 캡처(`capture-scenario.sh`)에 쓸 준비가 됐는지 확인하며, `FAIL`이면 `./scripts/setup-venv.sh`를 다시 실행하라고 안내합니다.

`baseline`은 정상 부하를 넣고 Application Insights에 두 요청 종류가 모두 보일 때까지 최대 10분 기다립니다. `acknowledge agent-setup`은 대화형이며, 설정 값을 출력한 뒤 표준 입력으로 정확히 `acknowledge`를 입력해야 기록됩니다.

## 시나리오 실행

각 시나리오 문서는 **수동 실행**을 먼저 설명합니다. `az containerapp update`, `az role assignment delete`처럼 실제로 Azure에 적용되는 명령을 그대로 실행하면서 무엇이 바뀌는지 확인하는 경로입니다. 처음 진행할 때는 이 경로를 권장합니다.

같은 절차를 한 번에 실행하는 지름길도 각 문서 뒤쪽에 있습니다.

```bash
./scripts/lab.sh run s1
./scripts/lab.sh capture s1
./scripts/lab.sh run s2
./scripts/lab.sh capture s2
./scripts/lab.sh run s3
./scripts/lab.sh capture s3
```

`run-scenario.sh`와 `capture-scenario.sh`는 `scripts/common.sh`의 `load_lab_config`로 "명시적 환경 변수 > 현재 `azd env get-value` > 허용된 기본값" 순서로 설정을 읽으므로, 고정된 구독이나 리소스 그룹이 스크립트 안에 없습니다. 진행 상태는 현재 azd 환경에 묶인 `evidence/state.json`에 기록되며 순서를 어기면 실행이 거부됩니다. 순서와 별개로, 어떤 시나리오든 실행이 `running`이나 `failed`로 남아 있으면 세 시나리오 모두 새 실행이 거부됩니다. 세 시나리오는 Container App 하나를 공유하므로, 끝나지 않은 실행 하나가 남은 실습 전체를 막습니다. 수동 실행도 첫 단계에서 `lab_state.py begin-run`을 호출해 같은 게이트를 적용받습니다. 차이는 복구입니다. 지름길은 종료 트랩이 장애를 자동으로 되돌리지만, 수동 실행에서는 복구 명령을 직접 완료해야 합니다.

| 시나리오 | 주입하는 장애 | 안내 문서 |
|---|---|---|
| S1 | HTTP 500 응답 | [guides/02-scenario-s1.md](guides/02-scenario-s1.md) |
| S2 | 주문 API 지연 | [guides/03-scenario-s2.md](guides/03-scenario-s2.md) |
| S3 | Blob 읽기 권한 제거 | [guides/04-scenario-s3.md](guides/04-scenario-s3.md) |

## 결과 확인

```bash
./scripts/lab.sh score
```

채점 기준, 사람이 채워야 하는 판정, 종합 판정 해석은 [guides/05-results.md](guides/05-results.md)에 있습니다.

## 정리

```bash
azd down --purge
```

리소스 그룹 삭제는 azd가 하고, azd가 볼 수 없는 두 가지만 hook이 처리합니다.

- predown hook `scripts/cleanup-external.sh --yes`: `evidence/agent-setup.json`에 기록된 구독 범위 Monitoring Contributor 할당만 제거합니다. 기록된 principal·역할·범위가 실제 할당과 모두 일치할 때만 삭제하고, 하나라도 어긋나면 아무것도 지우지 않습니다.
- postdown hook `scripts/cleanup-external.sh --reset-image-env --yes`: 기록된 `SRE_CONTAINER_IMAGE`와 `SRE_IMAGE_TAG`를 비웁니다. 삭제가 실제로 성공한 뒤에만 실행되어야 하므로 predown이 아니라 postdown입니다.

중요: predown hook은 `azd down`이 삭제 **확인** 프롬프트를 띄우기 **전에** 실행됩니다. 그 프롬프트에서 **취소**해도 이미 제거된 Monitoring Contributor 할당은 돌아오지 않습니다. 리소스 그룹은 남지만 Agent의 구독 범위 권한은 사라진 상태이므로, 계속 쓰려면 역할 할당을 다시 만들고 `evidence/agent-setup.json`을 새 할당 ID로 직접 갱신한 뒤 `./scripts/lab.sh acknowledge agent-setup`을 실행해야 합니다.

hook이 실패해 손으로 다시 실행할 때는 아래를 직접 호출합니다. `--yes` 없이는 계획만 출력합니다.

```bash
./scripts/cleanup-external.sh --yes
./scripts/cleanup-external.sh --reset-image-env --yes
```

azd 환경을 잃어버린 실습을 정리할 때만 `./scripts/cleanup.sh --legacy-delete-resource-group`으로 예전 삭제 경로를 씁니다. 이 경로도 구독 일치와 태그 확인을 거치며, 첫 명령은 dry-run입니다.

## 문제 해결

먼저 `./scripts/lab.sh doctor`를 실행해 어떤 검사가 `FAIL`인지 확인하세요. 각 명령의 실패 처리와 복구 절차는 해당 단계 문서에 있습니다.

| 증상 | 확인할 곳 |
|---|---|
| 배포 후 앱이 응답하지 않음 | `azd env get-value AZURE_CONTAINER_APP_FQDN`으로 FQDN을 확인한 뒤 `/healthz` 호출 |
| Agent가 스레드를 만들지 않음 | [guides/01-agent-setup.md](guides/01-agent-setup.md)의 incident platform·응답 계획 확인 |
| 경고가 발생하지 않음 | 시나리오 문서의 "복구 확인" 절 |
| 채점이 `INCOMPLETE` | [guides/05-results.md](guides/05-results.md)의 수동 판정 절 |

정적 임계값 대신 Dynamic Threshold로 확장하는 설계는 [dynamic-thresholds.md](dynamic-thresholds.md)에 정리해 두었습니다.

## 공식 자료

- [Azure SRE Agent 개요](https://learn.microsoft.com/azure/sre-agent/overview)
- [Complete setup](https://learn.microsoft.com/azure/sre-agent/complete-setup)
- [Automate incident response](https://learn.microsoft.com/azure/sre-agent/automate-incidents)
- [Azure Monitor alerts in Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/azure-monitor-alerts)
- [Incident response plans](https://learn.microsoft.com/azure/sre-agent/incident-response-plans)
