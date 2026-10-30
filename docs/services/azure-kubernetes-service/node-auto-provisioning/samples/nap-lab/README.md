# CAS·NAP 확장 실측과 전환 리허설

같은 네트워크(Azure CNI Overlay + Cilium)와 같은 VM 크기로 VMSS Cluster
Autoscaler 클러스터(`aks-cas`)와 NAP 클러스터(`aks-nap`)를 만들고,
1 vCPU를 요청하는 Pod 20개의 확장·축소 시간을 기록합니다. 이어서 `aks-cas`를
NAP로 전환하면서 요청 실패 수를 확인합니다.

## 준비

- Azure CLI 2.76 이상, `kubectl`
- 대상 리전에 약 80 vCPU 여유 quota(시스템 풀 4노드 + 실측 노드)
- 리전에서 사용할 수 있는 VM 크기를 `SYS_SKU`, `USER_SKU`로 지정합니다. 기본값은
  `Standard_D4ds_v6`입니다.

## 실행

```bash
export RG=rg-aks-autoscale-lab LOC=eastus2
./infra/create-clusters.sh

# NAP 전용 실측 NodePool: 고정 SKU와 D 계열 자유 선택
kubectl --context aks-nap apply -f manifests/nodepool-fixed.yaml -f manifests/nodepool-flex.yaml

# 시나리오, replica 수, 반복 횟수, (선택) nodeSelector
HEADER=1 ./bench/bench.sh aks-cas cas-d4 20 3 > results/cas.csv
HEADER=1 ./bench/bench.sh aks-nap nap-fixed-d4 20 3 bench=fixed > results/nap-fixed.csv
./bench/bench.sh aks-nap nap-flex 20 3 bench=flex > results/nap-flex.csv

# CAS → NAP 전환 리허설 (aks-cas 대상)
./migrate/in-place.sh | tee results/migration.log
kubectl --context aks-cas -n migrate logs deploy/client > results/probe.log
```

`bench.sh`는 워크로드 노드(`kubernetes.azure.com/mode=user`)가 0개가 될 때까지
기다린 뒤 시작합니다. CAS는 기본 profile에서 축소까지 약 20분이 걸리므로 CAS
시나리오가 가장 오래 걸립니다.

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/scale-out.csv` | 시나리오별 첫 노드 Ready, 전체 Pod Ready, 노드 수·SKU, 축소 완료 시간(초) |
| `results/migration-timeline.md` | 전환 단계별 시각과 요청 실패 수 |

## 정리

```bash
./infra/delete.sh
```

리소스 그룹 삭제가 끝나면 `az group exists -n $RG`가 `false`를 반환합니다.
