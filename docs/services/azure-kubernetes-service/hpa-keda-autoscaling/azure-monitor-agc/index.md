---
title: AGC 요청 수를 Azure Monitor로 읽어 KEDA로 확장하면 지표 지연으로 첫 확장까지 약 140초 걸린다
description: Application Gateway for Containers의 TotalRequests 메트릭을 KEDA azure-monitor scaler로 조회해 앱 수정 없이 진입점 트래픽으로 확장하고, 반응 시간과 frontend NSG 조건을 측정합니다.
document_type: lab
services: [azure-kubernetes-service, azure-application-gateway-for-containers, azure-monitor]
technologies: [kubernetes, keda]
tags: [build, networking]
status: verified
verification_status: verified
sources_checked_at: 2026-10-30
official_sources:
  - title: Integrations with Kubernetes Event-driven Autoscaling (KEDA) on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/keda-integrations
  - title: Securely scale your applications using the KEDA add-on and workload identity on Azure Kubernetes Service (AKS)
    url: https://learn.microsoft.com/azure/aks/keda-workload-identity
  - title: "Quickstart: Deploy Application Gateway for Containers ALB Controller using AKS Add-on"
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon
  - title: "Quickstart: Create Application Gateway for Containers managed by ALB Controller"
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller
  - title: Application Gateway for Containers components
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-components
  - title: Azure Monitor metrics for Application Gateway for Containers
    url: https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-metrics
  - title: KEDA Azure Monitor scaler
    url: https://keda.sh/docs/2.19/scalers/azure-monitor/
last_verified: 2026-10-30
review_cycle_days: 90
estimated_time: 75m
cost: paid
cleanup_required: true
topic_order: 3
---

# AGC 요청 수를 Azure Monitor로 읽어 KEDA로 확장하면 지표 지연으로 첫 확장까지 약 140초 걸린다

Application Gateway for Containers(AGC)는 frontend가 처리한 요청 수를
`TotalRequests` 플랫폼 메트릭으로 내보냅니다. KEDA core의 `azure-monitor` scaler가
이 값을 Workload Identity로 읽으면 앱에 지표를 추가하지 않고도 진입점 트래픽으로
확장할 수 있습니다. 대신 1분 단위 집계와 게시 지연 때문에 Managed Prometheus
방식보다 첫 확장이 약 75초 늦었습니다.

## 1분 동안 Pod당 3,000건(초당 50건)을 넘으면 replica를 늘린다

| 항목 | 값 |
|---|---|
| 지표 | `Microsoft.ServiceNetworking/trafficControllers` 의 `TotalRequests` (집계 `Total`, 1분 단위, 차원 `Frontend`) |
| scaler | `azure-monitor`, `metricAggregationInterval: "0:1:0"`, `targetValue: "3000"` |
| 인증 | KEDA Workload Identity + AGC 리소스 `Monitoring Reader` |
| 범위 | AGC 전체 요청 수. 여러 앱이 같은 AGC를 쓰면 `metricFilter`로 frontend를 나눕니다. |

## AGC add-on과 KEDA add-on은 모두 Workload Identity를 먼저 요구한다

[Managed Prometheus 실습](../prometheus-rps/index.md)과 같은 클러스터·podinfo·KEDA ID를
사용합니다. AGC add-on은 preview이므로 구독에
`ManagedGatewayAPIPreview`, `ApplicationLoadBalancerPreview` feature와
`Microsoft.ServiceNetworking`, `Microsoft.NetworkFunction` provider를 먼저 등록합니다.
AKS 관리 VNet에서는 add-on이 delegation된 `aks-appgateway` 서브넷과 NSG를 만듭니다.

## 비용은 AGC 리소스, frontend 처리량, 노드에 비례한다

AGC 리소스와 frontend·association, 처리한 요청량, 확장 중 추가되는 노드가 과금
대상입니다. 실습 후 Gateway와 `ApplicationLoadBalancer`를 지우면 ALB Controller가
AGC 리소스를 삭제합니다.

## AGC 생성, frontend NSG 허용, 권한, ScaledObject 순서로 배포한다

```bash
cd samples/keda-request-scaling
MC=$(az aks show -g $RG -n aks-nap --query nodeResourceGroup -o tsv)
SUBNET_ID=$(az network vnet subnet list -g $MC \
  --vnet-name $(az network vnet list -g $MC --query "[0].name" -o tsv) \
  --query "[?name=='aks-appgateway'].id" -o tsv)
sed "s|<alb-subnet-id>|$SUBNET_ID|" agc/gateway.yaml | kubectl apply -f -
kubectl -n demo get gateway web              # PROGRAMMED=True, ADDRESS=<hash>.<zone>.alb.azure.com

./agc/allow-frontend.sh                      # aks-appgateway NSG에 TCP 80·443 inbound 허용

ALB_ID=$(az resource list -g $MC --resource-type Microsoft.ServiceNetworking/trafficControllers --query "[0].id" -o tsv)
az role assignment create --assignee-object-id $(az identity show -g $RG -n id-keda --query principalId -o tsv) \
  --assignee-principal-type ServicePrincipal --role "Monitoring Reader" --scope $ALB_ID
# agc/scaledobject.yaml의 <...> 값을 채워 적용
```

## frontend로 초당 400건을 6분간 보낸다

`load/k6-job.yaml`의 `TARGET_URL`을 Gateway 주소(`http://<gateway-address>/`)로
바꿔 클러스터 안에서 실행했습니다.

## 첫 확장은 약 140초, 전체 Ready는 약 345초였다

부하 시작을 0초로 둔 관측값입니다(2026-10-30, AKS 1.36.5, ALB Controller 1.11.7).

| 시점 | AGC + Azure Monitor | 비교: Managed Prometheus |
|---|---|---|
| 첫 확장 | 약 140초 | 약 65초 |
| 목표 replica 도달 | 약 225초 (8개) | 약 130초 (9개) |
| 전체 Ready (NAP 노드 추가 포함) | 약 345초 | 약 245초 |
| 축소 시작 | 부하 종료 후 약 7분 | 부하 종료 후 약 5분 |

- k6 결과: 137,999건, 실패 0건, p99 3.5 ms
- 각 분의 `TotalRequests`는 그 분이 끝나고 약 1–2분 뒤에 조회됐습니다. 그동안 KEDA는
  값을 얻지 못하거나 이전 값을 썼습니다(HPA `TARGETS`가 잠시 비어 보임).
- 축소는 마지막 지표 반영, HPA 300초 안정화 창이 더해져 Prometheus 방식보다 늦었습니다.

## 지표가 늦으므로 급격한 증가보다 지속 트래픽에 맞다

- 앱 코드와 모니터링을 바꾸지 않고 진입점 기준으로 확장할 수 있습니다.
- 몇십 초 안에 반응해야 하는 burst에는 Managed Prometheus나 HTTP Add-on이 적합합니다.
- AGC 하나를 여러 앱이 공유하면 전체 요청 수가 섞이므로 앱별 frontend를 나누고
  `metricFilter: Frontend eq '<frontend-name>'`로 범위를 좁힙니다.

## ScaledObject가 Ready이고 HPA 목표가 분당 요청 수를 따라가면 성공이다

- `kubectl -n demo get scaledobject podinfo`: `READY=True`
- `kubectl -n demo get hpa keda-hpa-podinfo`: 부하 중 `<값>/3k (avg)`
- 부하 중 replica가 `ceil(분당 요청 / 3000)` 근처에 머물고 요청 실패가 없어야 합니다.

## 실습 후 Gateway와 ApplicationLoadBalancer를 먼저 지운다

```bash
kubectl -n demo delete scaledobject podinfo; kubectl -n demo delete triggerauthentication azure-wi
kubectl -n demo delete httproute podinfo; kubectl -n demo delete gateway web
kubectl -n alb-infra delete applicationloadbalancer alb-lab
az group delete -n $RG --yes --no-wait
```

## frontend가 응답하지 않으면 association 서브넷 NSG부터 본다

| 증상 | 원인과 조치 |
|---|---|
| Gateway가 `Programmed=True`인데 frontend 연결이 timeout, `NewConnections` 0 | 2026-04-23 이후 만든 association은 서브넷 NSG를 그대로 적용합니다. add-on이 만든 `aks-appgateway` NSG에는 기본 `DenyAllInBound`만 있어 80·443이 막힙니다. Internet → TCP 80·443 허용 규칙 추가. `AzureLoadBalancer` 허용도 유지 |
| HPA `TARGETS`가 `<unknown>` | KEDA ID에 AGC 리소스 `Monitoring Reader`가 없거나 `resourceURI`·`resourceGroupName`이 노드 리소스 그룹(MC_)이 아님 |
| ALB Controller 로그에 `no Pods found for Service` | 백엔드 Deployment가 0개. azure-monitor scaler는 `minReplicaCount: 1` 이상으로 둠 |

## 공식 참고 자료

- [Integrations with KEDA on AKS](https://learn.microsoft.com/azure/aks/keda-integrations)
- [KEDA add-on and workload identity](https://learn.microsoft.com/azure/aks/keda-workload-identity)
- [Deploy ALB Controller using AKS add-on](https://learn.microsoft.com/azure/application-gateway/for-containers/quickstart-deploy-application-gateway-for-containers-alb-controller-addon)
- [Create AGC managed by ALB Controller](https://learn.microsoft.com/azure/application-gateway/for-containers/quickstart-create-application-gateway-for-containers-managed-by-alb-controller)
- [Application Gateway for Containers components (NSG)](https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-components)
- [Azure Monitor metrics for AGC](https://learn.microsoft.com/azure/application-gateway/for-containers/application-gateway-for-containers-metrics)
- [KEDA Azure Monitor scaler](https://keda.sh/docs/2.19/scalers/azure-monitor/)
