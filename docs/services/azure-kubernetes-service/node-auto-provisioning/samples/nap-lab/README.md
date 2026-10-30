# CAS·NAP 확장 단계별 실측과 전환 리허설

같은 네트워크(Azure CNI Overlay + Cilium)와 같은 VM(`Standard_D4ds_v7`, on-demand)으로
VMSS Cluster Autoscaler 클러스터(`aks-cas`)와 NAP 클러스터(`aks-nap`)를 만듭니다. 이어서
Pending Pod를 만들어 확장 결정, VM 생성, 노드 Ready, Pod Ready, 축소 시간을 단계별로
기록합니다. `aks-cas`를 NAP로 전환하는 리허설도 포함합니다.

## 준비

- Azure CLI 2.76 이상, `kubectl`, Python 3.9 이상
- 대상 리전에 약 80 vCPU 여유 quota(시스템 풀 4노드 + 실측 노드)
- 리전에서 쓸 수 있는 VM 크기를 `SYS_SKU`, `USER_SKU`로 지정합니다(기본 `Standard_D4ds_v7`).

## 클러스터와 NodePool

```bash
export RG=rg-aks-autoscale-lab LOC=eastus2
./infra/create-clusters.sh      # CAS: scan-interval 10s, scale-down-unneeded-time 1m

# fixed: sku-name Standard_D4ds_v7 / flex: v7 D 계열 32 vCPU 이하 / azurelinux: AzureLinux AKSNodeClass
kubectl --context aks-nap apply -f manifests/nodepool-fixed.yaml \
  -f manifests/nodepool-flex.yaml -f manifests/nodepool-azurelinux.yaml
```

모든 NAP NodePool은 `karpenter.sh/capacity-type: on-demand`와 `kubernetes.io/arch: amd64`를
명시합니다.

## 확장 실측: `bench/bench.sh`

```bash
# bench.sh <context> <scenario> <replicas> <runs> [nodeSelector]
OUT=./out ./bench/bench.sh aks-cas cas-burst 20 3 agentpool=user
OUT=./out ./bench/bench.sh aks-nap nap-burst 20 3 bench=fixed

# 30초 간격으로 5개씩 추가
OUT=./out WAVES="5 5 5 5" WAVE_INTERVAL=30 ./bench/bench.sh aks-nap nap-waves 20 2 bench=fixed

# 6 vCPU Pod: CAS D4 풀은 확장하지 않음, NAP flex는 큰 VM 선택
OUT=./out CPU=6 TIMEOUT=150 ./bench/bench.sh aks-cas cas-large 4 1 agentpool=user
OUT=./out CPU=6 ./bench/bench.sh aks-nap nap-large 4 1 bench=flex

# 축소 완료를 VM 기준으로 기록 (CAS는 VM 삭제 뒤에도 node 객체가 몇 분 남음)
SCALE_IN_COUNT="az vmss list-instances -g <MC_rg> -n <vmss> --query 'length(@)' -o tsv" \
  OUT=./out ./bench/bench.sh aks-cas cas-waves 20 2 agentpool=user
```

실행마다 `OUT/<scenario>/run<n>/`에 Pod·노드·NodeClaim·이벤트 스냅샷을 남기고,
`bench/analyze.py`가 다음 열의 CSV 한 줄을 출력합니다.

| 열 | 의미 |
|---|---|
| `decision_s` | CAS `ScaledUpGroup`(setting group size) 또는 NAP NodeClaim 생성 |
| `vm_launched_s` | NAP NodeClaim `Launched` |
| `first_node_ready_s`, `last_node_ready_s` | 새 워크로드 노드 Ready |
| `all_pods_ready_s` | 모든 Pod Ready |
| `scale_in_s` | 축소 시작부터 VM 0개(`SCALE_IN_COUNT`) 또는 Ready 노드 0개까지 |
| `wave_latency_s` | wave별 추가 → 해당 Pod 모두 Ready |

## 최적화 실측

```bash
# CAS: AzureLinux 풀, Deallocate 풀(Managed OS disk 필요)
az aks nodepool add -g $RG --cluster-name aks-cas -n userazl --os-sku AzureLinux \
  --node-vm-size Standard_D4ds_v7 --node-count 0 --enable-cluster-autoscaler --min-count 0 --max-count 10
az aks nodepool add -g $RG --cluster-name aks-cas -n userdea --node-osdisk-type Managed \
  --scale-down-mode Deallocate --node-vm-size Standard_D4ds_v7 --node-count 0 \
  --enable-cluster-autoscaler --min-count 0 --max-count 10
OUT=./out ./bench/bench.sh aks-cas cas-dealloc 20 3 agentpool=userdea   # 1회차 새 VM, 2·3회차 재시작

# placeholder Pod 3개로 여유 노드 1대를 둔 상태에서 Pod 3개 추가
./bench/overprovision.sh aks-cas cas-overprov agentpool=user 2
./bench/overprovision.sh aks-nap nap-overprov bench=fixed 2

# NAP budget을 100%로 올려 축소 시간 비교
kubectl --context aks-nap patch nodepool bench-fixed --type merge \
  -p '{"spec":{"disruption":{"budgets":[{"nodes":"100%"}]}}}'
```

CAS 확장 판단 로그는 클러스터 진단 설정에서 `cluster-autoscaler` 범주를 Log Analytics로
보내면 `AzureDiagnostics | where Category == "cluster-autoscaler"`로 볼 수 있습니다.

## 선호 VM 실패 시 대체 속도

리전 vCPU 한도(100)를 넘는 `Standard_D96ds_v7`을 1순위, `Standard_D4ds_v7`을 대체로 둡니다.

```bash
# CAS: big 풀을 priority expander로 우선 시도
az aks update -g $RG -n aks-cas --cluster-autoscaler-profile expander=priority
az aks nodepool update -g $RG --cluster-name aks-cas -n user --labels bench=q
az aks nodepool add -g $RG --cluster-name aks-cas -n big --node-vm-size Standard_D96ds_v7 \
  --labels bench=q --node-count 0 --enable-cluster-autoscaler --min-count 0 --max-count 2
kubectl --context aks-cas apply -f manifests/cas-priority-expander.yaml

# NAP: weight 100(D96) / weight 10(D4) NodePool
kubectl --context aks-nap apply -f manifests/nodepool-quota-fallback.yaml

OUT=./out ./bench/bench.sh aks-cas cas-quota 20 2 bench=q
OUT=./out ./bench/bench.sh aks-nap nap-quota 20 2 bench=q
python3 bench/fallback.py ./out/cas-quota/run1 cas-quota 1 aks-user   # 대체 VMSS 이름 일부
python3 bench/fallback.py ./out/nap-quota/run1 nap-quota 1 fallback   # 대체 NodePool 이름
```

## CAS → NAP 전환 리허설

```bash
./migrate/in-place.sh | tee results/migration.log
kubectl --context aks-cas -n migrate logs deploy/client > results/probe.log
```

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/scale-out-v7.csv` | v7 on-demand 조건의 시나리오별 단계 시간 |
| `results/overprovisioning.csv` | placeholder가 있을 때 Pod 시작과 placeholder 복구 시간 |
| `results/quota-fallback.csv` | 선호 VM이 quota 초과로 실패할 때 실패 확인·대체 결정·노드·Pod 준비 시간 |
| `results/scale-out-v6-initial.csv` | 첫 측정(v6). 단계별 시간이 없고 CAS 축소를 node 객체 기준으로 재 과대 측정 |
| `results/migration-timeline.md` | 전환 단계별 시각과 요청 실패 수 |

## 정리

```bash
./infra/delete.sh
```

리소스 그룹 삭제가 끝나면 `az group exists -n $RG`가 `false`를 반환합니다.
