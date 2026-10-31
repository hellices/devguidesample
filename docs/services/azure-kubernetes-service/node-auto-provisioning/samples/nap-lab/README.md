# CAS·NAP 확장 단계별 실측과 전환 리허설

같은 네트워크(Azure CNI Overlay + Cilium)와 같은 VM(`Standard_D4ds_v7`, on-demand)으로
VMSS Cluster Autoscaler 클러스터와 NAP 클러스터를 만들고, Pending Pod를 만들어 확장 결정,
VM 생성, 노드 Ready, Pod Ready, 축소 시간을 단계별로 기록합니다. CAS 클러스터를 NAP로
전환하는 리허설도 포함합니다. 모든 단계는 Azure Developer CLI(`azd`)로 실행하며, 모든 CAS
풀은 Regular(on-demand), 모든 NAP NodePool은 `karpenter.sh/capacity-type: on-demand`입니다.

## 준비

- Azure Developer CLI 1.29 이상, Azure CLI 2.76 이상, `kubectl`, Python 3.9 이상
- 대상 리전에 약 100 vCPU quota(시스템 풀 4노드 16 vCPU + 실측 노드). `burst40`은 시스템 풀을
  포함해 96 vCPU를 쓰고, `quota-fallback`·`quota-staleness`는 quota 한도를 넘기도록 구성합니다.

## 클러스터 만들기

```bash
cd docs/services/azure-kubernetes-service/node-auto-provisioning/samples/nap-lab
azd env new nap-lab --location eastus2      # 리소스 그룹 rg-<환경 이름>
azd up
```

- **Bicep(`infra/`):**
  - CAS 클러스터: 시스템 풀 + `user` 풀(`Standard_D4ds_v7`, Regular, 0–10대), autoscaler profile
    `scan-interval=10s`, `scale-down-unneeded-time=1m`, `scale-down-delay-after-add=0m`
  - NAP 클러스터: 시스템 풀 + NAP(`default`·`system-surge` NodePool은 on-demand 전용)
- **postprovision hook:** 두 클러스터의 kubeconfig context(이름 = 클러스터 이름)를 만들고 NAP에
  `manifests/nodepool-fixed.yaml`(`Standard_D4ds_v7` 고정)과 `nodepool-flex.yaml`(v7 D 계열
  32 vCPU 이하)을 적용합니다. 리전 가격 파일이 없으면 `bench/prices.py`로 만듭니다.

`AKS_VERSION`(기본 1.36)과 `AKS_VM_SIZE`(기본 `Standard_D4ds_v7`)는 `azd up` 전에 `azd env set`으로
바꿀 수 있습니다. `AKS_VM_SIZE`는 시스템 풀, CAS `user` 풀, NAP `bench-fixed` NodePool에 함께
적용되어 `scale-out`·`waves`의 같은 VM 비교가 유지됩니다. 다른 실험은 문서의 VM 크기를 그대로 씁니다.

## 실험 실행

`EXPERIMENT` 환경 값에 실험을 공백이나 쉼표로 나열하고 postdeploy hook을 실행합니다.
결과 CSV와 실행별 원본 스냅샷은 `out/<환경 이름>/`에 남습니다.

```bash
azd env set EXPERIMENT "scale-out waves"
azd env set RUNS 3                          # 반복 횟수(일부 실험은 고정)
azd hooks run postdeploy                    # 또는 azd deploy
```

| `EXPERIMENT` | 내용 | 결과 파일 |
|---|---|---|
| `scale-out` | 1 vCPU Pod 20개 burst. CAS `user` 풀 vs NAP `bench-fixed` | `scale-out.csv` |
| `waves` | 30초 간격으로 5개씩 4회 | `scale-out.csv` |
| `large` | 6 vCPU Pod 4개. CAS D4 풀은 확장하지 못함, NAP flex는 큰 VM 선택 | `scale-out.csv` |
| `dealloc` | CAS `--scale-down-mode Deallocate` 풀. 1회차 새 VM, 2회차부터 재시작 | `scale-out.csv` |
| `azurelinux` | AzureLinux 노드 이미지 | `scale-out.csv` |
| `overprovision` | placeholder Pod로 여유 노드 1대를 둔 상태에서 Pod 3개 추가 | `overprovisioning.csv` |
| `quota-fallback` | quota를 넘는 `Standard_D96ds_v7`을 1순위, D4를 대체로 둠 | `quota-fallback.csv` |
| `mixed` | 크기가 다른 Pod 20개(A1). CAS 풀 1개·3개(random, least-waste) vs NAP | `mixed-shapes.csv` |
| `rightsize` | 20 → 3 Pod 축소 후 12분 관찰(A2·B4) | `rightsize-*.csv` |
| `zone1` | 두 쪽 모두 zone 1에만 노드 생성(B1) | `zone1-burst.csv` |
| `burst40` | 2 vCPU VM 40대(B2). CAS는 max 10 풀 4개 + `balance-similar-node-groups` | `burst-40-nodes.csv` |
| `quota-staleness` | 같은 VM 계열 quota를 CAS 풀로 점유했다가 반납(B3) | `quota-staleness.csv` |
| `migration` | CAS 클러스터에서 경로 1 전환 리허설 | `migration.log`, `migration-probe.log` |
| `drift` | `migration` 뒤 NAP drift로 노드 전체 교체, `preStop` 없음 → 있음 | `drift.csv` |

- 실험에 필요한 CAS 풀은 실험 안에서 만들고 끝나면 지웁니다. 노드 풀 10개·VMSS 10대 제한
  정책이 있는 구독에서도 실행할 수 있게 하려는 것입니다.
- `migration`은 CAS 클러스터에 NAP를 켜므로 CAS 실험을 모두 끝낸 뒤 실행합니다. `drift`는
  그 다음에 실행합니다.
- `quota-fallback`과 `quota-staleness`의 결과는 구독의 VM 계열·리전 quota에 따라 달라집니다.

### 스크립트를 직접 실행할 때

hook은 다음 스크립트를 호출합니다. azd 환경 값(`azd env get-values`)을 export하면 같은
명령을 직접 실행할 수 있습니다.

```bash
eval "$(azd env get-values)"; export AZURE_RESOURCE_GROUP CAS_CLUSTER_NAME NAP_CLUSTER_NAME AZURE_LOCATION
# bench.sh <kube-context> <scenario> <replicas> <runs> [nodeSelector]
OUT=./out ./bench/bench.sh "$NAP_CLUSTER_NAME" nap-burst 20 3 bench=fixed
```

`bench/analyze.py`가 실행마다 다음 열의 CSV 한 줄을 출력합니다.

| 열 | 의미 |
|---|---|
| `decision_s` | CAS `TriggeredScaleUp`과 `ScaledUpGroup`(setting group size) 중 이른 이벤트 또는 NAP NodeClaim 생성 |
| `vm_launched_s` | NAP NodeClaim `Launched=True` |
| `first_node_ready_s`, `last_node_ready_s` | 새 워크로드 노드 Ready |
| `all_pods_ready_s` | 모든 Pod Ready. 하나라도 Ready가 아니면 빈 값 |
| `scale_in_s` | 축소 시작부터 VM 0개(`SCALE_IN_COUNT`) 또는 Ready 노드 0개까지. timeout이면 빈 값 |
| `wave_latency_s` | wave별 추가 → 해당 wave Pod 모두 Ready |

CAS 확장 판단 로그는 클러스터 진단 설정에서 `cluster-autoscaler` 범주를 Log Analytics로
보내면 `AzureDiagnostics | where Category == "cluster-autoscaler"`로 볼 수 있습니다.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/scale-out-v7.csv` | v7 on-demand 조건의 시나리오별 단계 시간 |
| `results/scale-out-azd-rerun.csv` | `azd`로 새로 만든 클러스터에서 `EXPERIMENT=scale-out`을 다시 실행한 결과(3회씩) |
| `results/overprovisioning.csv` | placeholder가 있을 때 Pod 시작과 placeholder 복구 시간 |
| `results/quota-fallback.csv` | 선호 VM이 quota 초과로 실패할 때 실패 확인·대체 결정·노드·Pod 준비 시간 |
| `results/migration-timeline.md` | `EXPERIMENT="migration drift"` 전환 단계별 시각, drift 교체 시간과 요청 실패 수 |
| `results/prices-eastus2.json` | 비용 계산에 쓴 v7 VM 시간당 가격(2026-10-31) |
| `results/mixed-shapes.csv` | A1 혼합 Pod 배치·노드 구성·노드 용량 대비 요청 비율(`*_request_ratio`)·비용 |
| `results/rightsize-*.csv` | A2·B4 축소 후 30초 간격 노드 구성·비용·이동 Pod 수 |
| `results/zone1-burst.csv` | B1 같은 zone 확장 단계 시간 |
| `results/burst-40-nodes.csv` | B2 40대 확장 단계 시간과 정책 거부 기록 |
| `results/quota-staleness.csv` | B3 quota 점유·반납 후 NAP가 고른 NodePool. `recorded_s`는 이전 스크립트가 확인용 NodeClaim 정리 뒤 기록한 시각, `probe_s_est`는 스크립트 순서로 역산한 선택 확인 시각(±5초) |
| `results/nap-nodeclaim-phases.csv` | NAP burst·zone 1·40대 실측의 NodeClaim별 zone과 생성·`Launched`·`Registered`·`Initialized` 시각(실행 시작 기준 초). `bench.sh` 스냅샷의 `nodeclaims.json`에서 계산 |
| `results/cas-node-object-linger.csv` | CAS 축소 노드별 `ScaleDown` → `NodeNotReady` → node 객체 삭제(`DeletingNode`) 간격(초). 여러 CAS 실측 스냅샷의 Node 이벤트에서 계산 |
| `results/cas-dealloc-pod-scheduling.csv` | Deallocate 풀 실측의 Pod별 노드 Ready·Pod 배치·Pod Ready 시각(실행 시작 기준 초). `pods.json`·`nodes.json`에서 계산 |

## 정리

```bash
azd down --purge --force
```
