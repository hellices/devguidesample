# Event Hubs 용량 단위(TU·PU·CU) 벤치마크 및 OTel + VictoriaMetrics 모니터링 샘플

파이프(`|`) 구분자 기반 1 KB 게임 텔레메트리(T-Log) 워크로드를 생성하여 Azure Event Hubs의 티어별 용량 단위(`Standard TU`, `Premium PU`, `Dedicated CU`) 스케일링 특성을 실측하고 `OpenTelemetry Collector Contrib` + `VictoriaMetrics` + `Grafana`로 실효 용량 사용률(Effective Capacity Utilization %)과 Consumer Group Lag·OTel 큐 적체를 모니터링하는 실행 샘플입니다.

## 디렉터리 구조

```text
cu-benchmark-and-otel-vm-stack/
├── sample.yml
├── README.md
├── infra/
│   ├── main.bicep              # Standard(TU) / Premium(PU) / Dedicated(CU) 조건부 배포 템플릿
│   └── deploy.sh               # 프로비저닝, Dedicated 4시간 최소 과금 가드레일, 리소스 정리 스크립트
├── benchmark/
│   ├── requirements.txt        # azure-eventhub, confluent-kafka, matplotlib, numpy
│   ├── load_generator.py       # AMQP 5671 및 Kafka 9093 SASL_SSL 부하 생성·측정기
│   └── plot_results.py         # 실측 JSON 기반 4종 비교 차트(.png) 렌더러
├── results/
│   ├── trials.jsonl            # 실험별 원시 측정 레코드 (비식별화 완료)
│   ├── summary.json            # 집계 요약 및 시계열 데이터
│   └── charts/                 # 문서에 게시(publish)되는 4종 PNG 그래프
└── monitoring/
    ├── docker-compose.yml      # 로컬 검증용 OTel Collector + VictoriaMetrics + Grafana 스택
    ├── otel-collector-config.yaml
    ├── victoriametrics/
    │   └── vmcluster-aks.yaml  # 운영 AKS용 vminsert / vmstorage / vmselect 분산 매니페스트
    └── grafana/
        └── dashboards/
            └── eventhubs-cu-utilization.json
```

## 과금 및 쿼터 주의사항

- **Dedicated 클러스터(`Microsoft.EventHub/clusters`) 최소 4시간 과금 잠금**: Dedicated 클러스터는 생성 시점부터 최소 4시간 동안 삭제할 수 없으며 최소 4시간 사용 요금이 부과됩니다.
- **Dual-Track 실행 모델**:
  - **기본 실행(Track 1)**: `Standard (1·2·4 TU)`와 `Premium (1·2·4 PU, Dedicated와 동일한 격리 CPU/메모리 구조)` 네임스페이스를 배포하여 하드 스로틀링(`ServerBusy`) 유무, 파티션 병목(`4 vs 16 vs 32`), Kafka Gzip 압축 효율을 저비용으로 즉시 재현하고 삭제합니다.
  - **Dedicated 실측 실행(Track 2)**: `--include-dedicated` 플래그와 `CONFIRM_DEDICATED_4H_BILLING=yes` 환경변수를 명시하여 `koreacentral` 리전에 Dedicated 클러스터(`1 CU -> 2 CU -> 4 CU -> 8 CU`)와 토픽(`telemetry-p4`, `p16`, `p32`, `p64`, `p128`, `p256`)을 배포하고 동일 리전(`koreacentral`)의 고대역폭 멀티프로세스 부하 생성기에서 `1 CU(최대 379.7 MB/s) -> 2 CU(최대 473.8 MB/s) -> 4 CU(최대 828.7 MB/s) -> 8 CU(최대 1,000.2 MB/s)` 포화 수렴 및 브로커 `CPU (Role=Gateway, Backend)` 한계를 측정합니다.

## 실행 방법

### 1. 인프라 배포

```bash
cd docs/services/azure-event-hubs/dedicated-cu-scaling-and-monitoring/samples/cu-benchmark-and-otel-vm-stack

# Track 1: Standard + Premium 네임스페이스 배포 (koreacentral / koreasouth)
./infra/deploy.sh deploy

# Track 2 (선택): Dedicated 클러스터 포함 배포 (4시간 최소 과금 동의 필요)
CONFIRM_DEDICATED_4H_BILLING=yes ./infra/deploy.sh deploy --include-dedicated
```

### 2. 부하 생성 및 그래프 렌더링

```bash
python3 -m venv /tmp/eh-bench-venv
/tmp/eh-bench-venv/bin/pip install -r benchmark/requirements.txt

# 4대 실험 실행 및 results/trials.jsonl, results/summary.json 생성 (각 시행 30초, 스케일링 후 15초 안정화 대기)
/tmp/eh-bench-venv/bin/python benchmark/load_generator.py \
  --resource-group rg-eh-cu-bench-kr \
  --standard-namespace <standardNamespaceName> \
  --premium-namespace <premiumNamespaceName> \
  --trial-duration 30 \
  --settle-seconds 15

# Dedicated 클러스터(Track 2)까지 함께 측정하는 경우
/tmp/eh-bench-venv/bin/python benchmark/load_generator.py \
  --resource-group rg-eh-cu-bench-kr \
  --standard-namespace <standardNamespaceName> \
  --premium-namespace <premiumNamespaceName> \
  --dedicated-cluster <dedicatedClusterName> \
  --dedicated-namespace <dedicatedNamespaceName> \
  --trial-duration 35 \
  --settle-seconds 15

# 4종 비교 차트 생성 (results/charts/*.png)
/tmp/eh-bench-venv/bin/python benchmark/plot_results.py
```

### 3. 모니터링 스택 실행 (Docker Compose)

```bash
cd monitoring
docker compose up -d
# Grafana 접속: http://localhost:3000 (기본 대시보드 자동 로드)
```

### 4. 리소스 정리 (필수)

```bash
./infra/deploy.sh cleanup
rm -rf /tmp/eh-bench-venv
```
