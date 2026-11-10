# Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습 sample

[Event Hubs 지표 수집 방식 비교 topic](../../index.md)의 `azd` sample입니다. Event Hubs
Dedicated cluster(1 CU)와 그 안의 workload namespace, AKS의 VictoriaMetrics, 그리고
OpenTelemetry Collector Contrib·consumer lag exporter·Grafana OSS를 실행하는 Gateway VM을
배포합니다. 실제 배포 기록, 측정값과 배포 중 수정한 오류는 [실습 문서](../../lab/index.md)에
있습니다.

`EVENTHUBS_SKU`의 기본값은 `Dedicated`입니다. Dedicated cluster는 만든 뒤 4시간 동안
삭제할 수 없고 그동안 CU 시간 단위로 과금되므로, `azd down`은 cluster 생성 4시간 뒤에
실행합니다. `azd env set EVENTHUBS_SKU Premium`이면 cluster 대신 Premium 1 PU namespace를
만들고, 이때 `EXISTING_DEDICATED_CLUSTER_RESOURCE_ID`로 기존 cluster 지표를 함께 수집할 수
있습니다. 템플릿은 그 cluster에 Gateway identity의 Monitoring Reader를 할당하므로 배포자에게
해당 cluster의 역할 할당 권한이 필요합니다.

## 실행 순서

```bash
azd env new <env-name> --subscription <subscription-id> --location koreacentral
azd env set EVENTHUBS_LOCATION koreasouth   # Event Hubs만 다른 리전에 둘 때(cluster 지원 리전 확인)
# azd env set EVENTHUBS_SKU Premium          # cluster 대신 Premium 1 PU
azd up                                       # provision + hooks + workload
./scripts/run-scenario.sh                    # baseline 5분, 부하 10분, 회복
./scripts/collect-evidence.sh                # probe → build → verify → capture
azd down --purge --force                     # cluster 생성 4시간 뒤. postdown이 resource group 삭제까지 확인
```

필요한 도구는 Azure CLI, Azure Developer CLI, `kubectl`, `kubelogin`, Helm,
Python 3.10 이상(`venv`), Node.js 20 이상, OpenSSL, `ssh-keygen`입니다. 로그인한
주체는 구독에서 역할 할당을 만들 수 있어야 합니다.

## 구성

| 경로 | 용도 |
|---|---|
| `azure.yaml` | azd project와 lifecycle hook입니다. `services`가 없으므로 `azd deploy`는 `postdeploy`만 실행합니다. |
| `infra/main.bicep` | 구독 범위 진입점, resource group, hook이 쓰는 output입니다. |
| `infra/modules/foundation.bicep` | VNet, ACR, private endpoint 뒤의 Storage·Key Vault, identity, container 범위 역할입니다. |
| `infra/modules/messaging.bicep` | Dedicated cluster와 그 안의 namespace(또는 Premium namespace), telemetry Standard namespace, namespace·cluster Diagnostic Settings, Event Hubs 데이터 역할, Monitoring Reader입니다. |
| `infra/modules/compute.bicep` | AKS(Workload Identity, Azure RBAC), internal load balancer용 subnet 역할, Gateway VM입니다. |
| `scripts/azd-configure.sh` | `preprovision`: 구독·provider 확인, operator egress `/32`, 비밀 생성입니다. |
| `scripts/azd-postprovision.sh` | `postprovision`: kubeconfig, federated credential, ACR build, VictoriaMetrics, Run Command로 Gateway 번들 적용입니다. `GATEWAY_ONLY=true`이면 Gateway만 다시 적용합니다. |
| `scripts/azd-deploy.sh` | `postdeploy`: Workload Identity를 쓰는 producer와 slow consumer입니다. |
| `scripts/run-scenario.sh` | lag 상승·회복 시나리오와 UTC 경계를 `evidence/<env>/scenario.json`에 남깁니다. |
| `scripts/collect-evidence.sh` | agent 대시보드 workflow와 Azure Monitor 분 단위 대조입니다. |
| `scripts/cleanup-external.sh`, `scripts/verify-cleanup.sh` | `predown`, `postdown`입니다. |
| `gateway/render_collector.py` | 4개 source × 2개 전달 경로 Collector 구성, Dedicated·fallback profile입니다. |
| `gateway/compose.yaml`, `gateway/bootstrap.sh` | digest를 고정한 Gateway runtime과 Run Command bootstrap입니다. |
| `k8s/` | Operator values, VMSingle, VMAgent, VMStaticScrape, workload입니다. |
| `workloads/` | producer, slow consumer, checkpoint 기반 lag exporter image입니다. |
| `agent/` | `probe.py`, `build_dashboard.py`, `publish_dashboard.py`, `verify_panels.py`, `capture.mjs`, Azure Monitor 분 단위 대조 `compare_azure_monitor.py`입니다. Grafana는 Gateway가 만든 인증서를 고정한 HTTPS로만 접속합니다. |
| `tests/` | Bicep, hook, Collector 구성, lag 계산, 대시보드의 계약·단위 테스트입니다. |

## fallback exporter 전환

`azuremonitorreceiver` 대신 `webdevops/azure-metrics-exporter`를 쓰는 경로를 확인할
때 실행합니다.

```bash
ENABLE_API_RECEIVER=false ENABLE_FALLBACK_EXPORTER=true GATEWAY_ONLY=true azd hooks run postprovision
GATEWAY_ONLY=true azd hooks run postprovision   # 기본 receiver로 복구
```

## 테스트

```bash
python -m pytest tests -q
```

`.azure/`, `evidence/`, `agent/node_modules/`는 로컬 상태이므로 커밋하지 않습니다.
