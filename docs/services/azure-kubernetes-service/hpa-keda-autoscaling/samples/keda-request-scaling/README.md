# KEDA 요청 수 기반 확장 실습

NAP가 켜진 AKS 클러스터에서 같은 podinfo 앱과 같은 k6 부하(최대 초당 400건)로 세 가지
요청 기반 확장 패턴을 재현합니다. 클러스터, add-on, 권한, 앱 배포와 부하 실행은 모두
Azure Developer CLI(`azd`)로 합니다. 워크로드 노드는 AKS가 만드는 NAP `default`
NodePool(on-demand 전용)에서 만들어지며 spot VM은 쓰지 않습니다.

| 폴더 | 패턴 | KEDA 범위 |
|---|---|---|
| `prometheus/` | Managed Prometheus 요청률 + `prometheus` scaler | KEDA core |
| `http-add-on/` | KEDA HTTP Add-on interceptor + `external-push` | 별도 설치 add-on |
| `agc/` | Application Gateway for Containers `TotalRequests` + `azure-monitor` scaler | KEDA core |

## 준비

- Azure Developer CLI 1.29 이상, Azure CLI 2.76 이상, `kubectl`, Helm 3, Python 3(`python3`)
- 대상 리전에 약 40 vCPU quota(시스템 풀 2노드 + 워크로드 노드)

## 실행

저장소 루트에서 sample 폴더로 이동한 뒤 실행합니다.

```bash
cd docs/services/azure-kubernetes-service/hpa-keda-autoscaling/samples/keda-request-scaling
azd env new keda-lab --location eastus2      # 환경 이름이 리소스 그룹 rg-<환경 이름>이 됩니다
azd up                                        # Bicep 배포 + postprovision hook
```

`azd up`이 하는 일:

1. **Bicep(`infra/`)**
   - **AKS 클러스터:** NAP, Workload Identity, OIDC issuer, KEDA add-on, Azure CNI Overlay + Cilium
   - **Azure Monitor workspace**
   - **KEDA용 관리 ID:** `keda-operator` service account에 대한 federated credential, workspace의 `Monitoring Data Reader` 역할
2. **`hooks/postprovision.sh`**
   - **add-on:** Managed Prometheus를 켭니다. AGC preview에 필요한 CLI extension·provider·feature 등록을 완료까지 기다린 뒤 Gateway API·AGC add-on을 켭니다.
   - **KEDA ID 연결:** `keda-operator`에 관리 ID annotation을 달고 재시작합니다.
   - **앱과 HTTP Add-on:** podinfo·PodMonitor를 배포하고 HTTP Add-on을 Helm으로 설치합니다.
   - **AGC:** Gateway를 만들고 frontend NSG를 허용하며, AGC에 대한 `Monitoring Reader`를 부여합니다.

AGC 실습을 하지 않으면 `azd env set ENABLE_AGC false`를 먼저 실행합니다.

패턴은 `PATTERN` 환경 값으로 고르고 `postdeploy` hook으로 실행합니다. 패턴마다 이전
`ScaledObject`를 지우고 워크로드 노드가 줄어든 뒤 같은 부하를 주며, replica·노드 수를 5초마다
1200초 동안 기록합니다.

```bash
azd env set PATTERN "prometheus-rps http-add-on-min1 http-add-on-min0 http-add-on-cold-start azure-monitor-agc"
azd hooks run postdeploy                      # 결과: out/<환경 이름>/
```

| `PATTERN` | 내용 |
|---|---|
| `prometheus-rps` | Managed Prometheus 요청률 기준 확장 |
| `http-add-on-min1` | HTTP Add-on, `minReplicaCount: 1` |
| `http-add-on-min0` | HTTP Add-on, 0개에서 burst |
| `http-add-on-cold-start` | 0개에서 첫 요청 응답 시간. 기존 노드에 자리가 있을 때 3회, 새 노드가 필요할 때 1회 |
| `azure-monitor-agc` | AGC `TotalRequests` 기준 확장 |

한 Deployment에는 `ScaledObject`를 하나만 둡니다. 기존 HPA가 같은 Deployment를 대상으로
하고 있으면 KEDA admission webhook이 `ScaledObject`를 거부합니다.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/prometheus-rps.csv` | k6 시작 기준 경과 초(음수는 부하 전), 원하는 replica, Ready replica, HPA 지표, 워크로드 노드 수. 클러스터 안의 watcher Job이 5초 간격으로 기록 |
| `results/http-add-on-min0.csv` | HTTP Add-on, `minReplicaCount: 0`에서 burst 부하 |
| `results/http-add-on-min1.csv` | HTTP Add-on, `minReplicaCount: 1`에서 같은 부하 |
| `results/http-add-on-cold-start.txt` | 0개에서 첫 응답까지 걸린 시간(`total`)과 직후 warm 요청 시간(`warm_after`), 초 단위 |
| `results/azure-monitor-agc.csv` | 같은 형식 |
| `results/k6-summary.csv` | 실행별 k6 요약. 계획 요청 수(138,000), 실제 전송 수, 미전송·실패 수, 응답 시간 avg·p95·p99 |

각 결과는 azd로 만든 클러스터에서 패턴마다 1회 실행한 값입니다. `not_sent`는 k6 부하 계획
(1분 ramp-up, 5분 400 RPS, 30초 감소 = 138,000건)에서 실제 `http_reqs`를 뺀
값입니다. 다른 실행의 1건은 arrival-rate 반올림 차이이고, `http-add-on-min0`에서는
응답이 보류되는 동안 VU 한도(`maxVUs: 1000`)가 차서 보내지 못한 요청입니다(k6
`dropped_iterations` 21,934건). 원본 k6 출력은 실행 시 `out/<환경 이름>/<패턴>-k6.txt`에 남습니다.

## 정리

```bash
azd down --purge --force      # 리소스 그룹과 그 안의 클러스터·workspace·관리 ID를 모두 삭제
```
