# Event Hubs OpenTelemetry·VictoriaMetrics 관측 실습 sample

[Event Hubs 지표·consumer lag topic](../../index.md)의 `azd` sample입니다. Event Hubs
Premium namespace, AKS의 VictoriaMetrics, 그리고 OpenTelemetry Collector Contrib·
consumer lag exporter·Grafana OSS를 실행하는 Gateway VM을 배포합니다. 실제 배포
기록, 측정값과 배포 중 수정한 오류는 [실습 문서](../../lab/index.md)에 있습니다.

이 sample은 Event Hubs Dedicated cluster를 만들지 않습니다.
`EXISTING_DEDICATED_CLUSTER_RESOURCE_ID`를 지정하면 기존 cluster를 읽는 수집
profile만 렌더링하며, 이 profile은 runtime 검증을 거치지 않았습니다.

## 실행 순서

```bash
azd env new <env-name> --subscription <subscription-id> --location koreacentral
azd env set EVENTHUBS_LOCATION koreasouth   # 기본 리전에서 Premium 신규 생성이 제한된 경우만
azd up                                       # provision + hooks + workload
./scripts/run-scenario.sh                    # baseline 5분, 부하 10분, 회복
./scripts/collect-evidence.sh                # probe → build → verify → capture
azd down --purge --force                     # predown·postdown이 resource group 삭제까지 확인
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
| `infra/modules/messaging.bicep` | Premium·Standard namespace, Diagnostic Settings, Event Hubs 데이터 역할, Monitoring Reader입니다. |
| `infra/modules/compute.bicep` | AKS(Workload Identity, Azure RBAC), internal load balancer용 subnet 역할, Gateway VM입니다. |
| `scripts/azd-configure.sh` | `preprovision`: 구독·provider 확인, operator egress `/32`, 비밀 생성입니다. |
| `scripts/azd-postprovision.sh` | `postprovision`: kubeconfig, federated credential, ACR build, VictoriaMetrics, Run Command로 Gateway 번들 적용입니다. `GATEWAY_ONLY=true`이면 Gateway만 다시 적용합니다. |
| `scripts/azd-deploy.sh` | `postdeploy`: Workload Identity를 쓰는 producer와 slow consumer입니다. |
| `scripts/run-scenario.sh` | lag 상승·회복 시나리오와 UTC 경계를 `evidence/scenario.json`에 남깁니다. |
| `scripts/collect-evidence.sh` | agent 대시보드 workflow와 Azure Monitor 분 단위 대조입니다. |
| `scripts/cleanup-external.sh`, `scripts/verify-cleanup.sh` | `predown`, `postdown`입니다. |
| `gateway/render_collector.py` | 4개 source × 2개 전달 경로 Collector 구성, Dedicated·fallback profile입니다. |
| `gateway/compose.yaml`, `gateway/bootstrap.sh` | digest를 고정한 Gateway runtime과 Run Command bootstrap입니다. |
| `k8s/` | Operator values, VMSingle, VMAgent, VMStaticScrape, workload입니다. |
| `workloads/` | producer, slow consumer, checkpoint 기반 lag exporter image입니다. |
| `agent/` | `probe.py`, `build_dashboard.py`, `publish_dashboard.py`, `verify_panels.py`, `capture.mjs`입니다. |
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
