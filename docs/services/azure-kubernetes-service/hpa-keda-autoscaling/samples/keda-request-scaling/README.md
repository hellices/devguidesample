# KEDA 요청 수 기반 확장 실습

NAP가 켜진 AKS 클러스터(`aks-nap`)에서 같은 podinfo 앱과 같은 k6 부하(초당
400건)로 세 가지 요청 기반 확장 패턴을 재현합니다. 클러스터는
`node-auto-provisioning/samples/nap-lab/infra/create-clusters.sh`로 만든 것을
가정합니다.

| 폴더 | 패턴 | KEDA 범위 |
|---|---|---|
| `prometheus/` | Managed Prometheus 요청률 + `prometheus` scaler | KEDA core |
| `http-add-on/` | KEDA HTTP Add-on interceptor + `external-push` | 별도 설치 add-on |
| `agc/` | Application Gateway for Containers `TotalRequests` + `azure-monitor` scaler (`allow-frontend.sh`로 frontend NSG 허용) | KEDA core |

한 Deployment에는 `ScaledObject`를 하나만 둡니다. 다음 패턴으로 넘어가기 전에
이전 `ScaledObject`와 `k6` Job을 삭제합니다.

## 공통 준비

```bash
export RG=rg-aks-autoscale-lab CTX=aks-nap
./infra/enable-addons.sh                # Workload Identity → KEDA → Managed Prometheus → Gateway API·AGC
./infra/setup-keda-identity.sh          # KEDA_CLIENT_ID 출력
kubectl --context $CTX apply -f app/podinfo.yaml
```

AGC add-on은 preview입니다. 처음 사용하는 구독은
`Microsoft.ContainerService/ManagedGatewayAPIPreview`,
`Microsoft.ContainerService/ApplicationLoadBalancerPreview` feature와
`Microsoft.ServiceNetworking`, `Microsoft.NetworkFunction` provider를 먼저 등록합니다.

## 패턴별 실행

각 패턴의 YAML에 있는 `<...>` 값을 실제 값으로 바꿔 적용한 뒤 부하를 줍니다.
자세한 명령은 각 실습 문서에 있습니다.

```bash
./load/watch-replicas.sh > results/<pattern>.csv &
kubectl --context $CTX apply -f load/k6-job.yaml   # TARGET_URL·HOST_HEADER를 패턴에 맞게 수정
```

## 결과 파일

| 파일 | 내용 |
|---|---|
| `results/prometheus-rps.csv` | 경과 초, 원하는 replica, Ready replica, HPA 지표, 워크로드 노드 수 |
| `results/http-add-on-min0.csv` | HTTP Add-on, `minReplicaCount: 0`에서 burst 부하 |
| `results/http-add-on-min1.csv` | HTTP Add-on, `minReplicaCount: 1`에서 같은 부하 |
| `results/http-add-on-cold-start.txt` | 0개에서 첫 응답까지 걸린 시간 |
| `results/azure-monitor-agc.csv` | 같은 형식 |

## 정리

```bash
helm uninstall http-add-on -n kube-system --kube-context $CTX
az group delete -n $RG --yes --no-wait
```
