# HDInsight Kafka Consumer Lag — 비율 축소 실증 테스트 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 이 계획은 코드가 아니라 **Azure 운영 런북**이므로 각 Task는 TDD 대신 "명령 실행 → 기대 출력 확인 → 결과 기록" 사이클을 따른다.

**Goal:** 기존 HDInsight Kafka 테스트베드에서 consumer lag를 재현하고, 부하·브로커 사이징을 비율로 조절해 "lag 1분 이내 회복"이 가능함을 실측 데이터로 증명한다.

**Architecture:** 클러스터는 프라이빗이므로 모든 Kafka 작업은 동일 VNet 안의 `vm-kafka-loadgen`에서 `az vm run-command invoke`로 실행한다. 부하 생성/소비는 전용 클라이언트 VM(perf-test)으로 브로커에서 격리하고, 모니터링은 기존 Prometheus+Grafana(`vm-monitoring`)로 관측한다. Baseline→Arm A(부하 축소)를 핵심 증명으로 실행하고, Arm B(브로커 RAM)는 시간·예산 게이트로 진행한다.

**Tech Stack:** Azure HDInsight 5.1 (Kafka 3.2.0), Apache Kafka perf-test CLI, Prometheus + Grafana, `az cli` / `az vm run-command`.

## Global Constraints

- 구독: `95933ae5-0201-4a21-a1fc-8051a7437982` (contoso / ME-MngEnvMCAP310512-inhwanhwang-3)
- 리소스 그룹: `rg-krafton-kafka-dev-jpe` (japaneast)
- 클러스터: `krafton-kafka-hdi-68944` (현재 3×`Standard_D4ads_v5` 워커=브로커, 16 GB RAM, 데이터디스크 2/노드)
- Ambari(내부에서만): `https://krafton-kafka-hdi-68944.azurehdinsight.net`, 계정 `admin` / `KfkBDQPfW9NyC6!7`
- 로드젠 VM: `vm-kafka-loadgen` (현재 `Standard_B2s`, 부하생성용으로 `Standard_D8s_v5`로 리사이즈)
- 모니터링 VM: `vm-monitoring` (Prometheus + Grafana), 매니지드 Grafana `grafana-krafton-68944`
- 예산: **오늘 1일, $1000 이내.** money보다 HDInsight 재생성 시간이 실질 제약. 각 Arm 종료 후 유휴 VM은 즉시 deallocate.
- 프라이빗 클러스터 → 외부에서 브로커 접속 불가. **반드시** `az vm run-command invoke -n vm-kafka-loadgen` 경유.
- 결과는 `docs/superpowers/reports/2026-07-15-hdinsight-kafka-lag-results.md` 리빙 문서에 Arm별로 갱신(한눈에 보이는 표 중심).
- 테스트 토픽: `lag-test`, 파티션 30, RF 2 (프로덕션 180파티션/18브로커 = 브로커당 10 → 3브로커 테스트베드 = 30파티션으로 브로커당 10 동일).
- 각 명령 실행 위치는 명시(로컬 `az` vs 로드젠 VM `run-command`).

---

## 축소 매핑 요약 (왜 이 테스트가 유효한가)

| 지표 | 프로덕션 | 테스트베드 | 매핑 |
|---|---|---|---|
| 브로커 수 | 18 | 3 | k=6 축소 |
| 브로커당 RAM | 32 GB | 16 GB | 캐시 1/2 → 부하도 1/2로 맞춰 ρ 보존 |
| 브로커당 리더 파티션 | 10 | 10 | 동일 (30파티션/3브로커) |
| per-broker page cache | ~20 GB | ~10 GB | — |
| T_cache 목표 | ~8분 | ~8분 | per-broker 유입률을 `cache/8min`으로 설정 |
| 테스트베드 총 목표 produce율 | — | ~10GB/8min×3 ≈ **60 MB/s** | 로드젠에서 `--throughput`으로 고정 |

핵심: per-broker `ρ = 유입률/캐시`를 프로덕션과 맞추면, 3브로커 테스트베드가 18브로커 중 브로커 1대의 캐시 축출 동역학을 재현한다. Baseline에서 T_cache급(수 분) lag를 유발하고, 부하를 낮추면(Arm A) 회복<1분이 되는 임계를 찾는다.

---

## Phase 0 — 환경 준비

### Task 0.1: 모니터링·로드젠 VM 기동 및 로드젠 리사이즈

**Files:** 없음 (Azure 작업)

- [ ] **Step 1: 구독 고정**

로컬 실행:
```bash
az account set --subscription 95933ae5-0201-4a21-a1fc-8051a7437982
```

- [ ] **Step 2: 로드젠 VM을 D8s_v5로 리사이즈 (deallocated 상태에서)**

로컬 실행:
```bash
az vm resize -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --size Standard_D8s_v5
```
Expected: VM 정의가 `Standard_D8s_v5`로 갱신 (deallocated라 즉시 반영).

- [ ] **Step 3: 모니터링·로드젠 VM 기동**

로컬 실행:
```bash
az vm start -g rg-krafton-kafka-dev-jpe -n vm-monitoring
az vm start -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen
```
Expected: 두 VM 모두 `VM running`.

- [ ] **Step 4: 전원 상태 확인**

로컬 실행:
```bash
az vm list -g rg-krafton-kafka-dev-jpe -d --query "[].{name:name,size:hardwareProfile.vmSize,power:powerState}" -o table
```
Expected: `vm-kafka-loadgen  Standard_D8s_v5  VM running`, `vm-monitoring ... VM running`.

### Task 0.2: 로드젠 VM에 Kafka 클라이언트 설치 + 브로커 검색

**Files:** 없음 (로드젠 VM 내부 구성)

- [ ] **Step 1: JDK + Kafka 3.2.0 클라이언트 설치**

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
set -e
if [ ! -d /opt/kafka ]; then
  sudo apt-get update -y -qq
  sudo apt-get install -y -qq openjdk-11-jre-headless wget
  cd /opt
  sudo wget -q https://archive.apache.org/dist/kafka/3.2.0/kafka_2.12-3.2.0.tgz
  sudo tar xzf kafka_2.12-3.2.0.tgz
  sudo mv kafka_2.12-3.2.0 kafka
fi
/opt/kafka/bin/kafka-topics.sh --version
java -version 2>&1 | head -1
' --query "value[0].message" -o tsv
```
Expected: `3.2.0` 및 java 버전 출력. (설치 최초 1회 수 분 소요.)

- [ ] **Step 2: Ambari에서 브로커 호스트 검색 → bootstrap 문자열 생성**

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
CL=$(curl -s -u "admin:KfkBDQPfW9NyC6!7" "https://krafton-kafka-hdi-68944.azurehdinsight.net/api/v1/clusters" | python3 -c "import sys,json;print(json.load(sys.stdin)[\"items\"][0][\"Clusters\"][\"cluster_name\"])")
BROKERS=$(curl -s -u "admin:KfkBDQPfW9NyC6!7" "https://krafton-kafka-hdi-68944.azurehdinsight.net/api/v1/clusters/$CL/services/KAFKA/components/KAFKA_BROKER" | python3 -c "import sys,json;d=json.load(sys.stdin);print(\",\".join(h[\"HostRoles\"][\"host_name\"]+\":9092\" for h in d[\"host_components\"]))")
echo "CLUSTER=$CL"
echo "BOOTSTRAP=$BROKERS"
echo "$BROKERS" | sudo tee /opt/kafka/bootstrap.txt
' --query "value[0].message" -o tsv
```
Expected: `BOOTSTRAP=wn0-...:9092,wn1-...:9092,wn2-...:9092` 3개. `/opt/kafka/bootstrap.txt` 저장.

- [ ] **Step 3: 브로커 연결 확인**

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server "$BS" 2>&1 | head -5
' --query "value[0].message" -o tsv
```
Expected: 각 브로커가 응답(`... (id: 100X rack: ...)`). 실패 시 NSG/포트 9092 확인.

### Task 0.3: 테스트 토픽 생성 + 모니터링 확인

**Files:** 없음

- [ ] **Step 1: `lag-test` 토픽 생성 (30 파티션, RF 2)**

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BS" --create --if-not-exists --topic lag-test --partitions 30 --replication-factor 2 --config retention.ms=129600000 --config max.message.bytes=1000000 --config segment.bytes=1073741824
/opt/kafka/bin/kafka-topics.sh --bootstrap-server "$BS" --describe --topic lag-test | head -3
' --query "value[0].message" -o tsv
```
Expected: `Topic: lag-test PartitionCount: 30 ReplicationFactor: 2`.

- [ ] **Step 2: Grafana/Prometheus 도달 확인 (모니터링 VM 경유)**

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-monitoring --command-id RunShellScript --scripts '
curl -s -o /dev/null -w "prometheus %{http_code}\n" http://localhost:9090/-/ready
curl -s "http://localhost:9090/api/v1/query?query=kafka_brokers" | head -c 200; echo
curl -s -o /dev/null -w "grafana %{http_code}\n" http://localhost:3000/api/health
' --query "value[0].message" -o tsv
```
Expected: `prometheus 200`, `kafka_brokers` 값 반환, `grafana 200`. (지표 미수집 시 kafka-exporter/JMX 타깃 점검.)

- [ ] **Step 3: 결과 리포트 파일 초기화 (로컬)**

`docs/superpowers/reports/2026-07-15-hdinsight-kafka-lag-results.md` 생성, 아래 "결과 리포트 템플릿" 섹션 내용으로 초기화 후 커밋.
```bash
git add docs/superpowers/reports/2026-07-15-hdinsight-kafka-lag-results.md
git commit -m "docs(hdinsight): init lag test results report

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Phase 1 — Baseline (lag 재현)

### Task 1.1: 부하 프로파일 캘리브레이션 (목표 ~60 MB/s produce)

**Files:** 없음

- [ ] **Step 1: 워밍업 produce로 처리량 상한 확인**

로드젠에서 무제한 produce 30초 → 달성 MB/s 확인. record-size 1MB(프로덕션 max.message 정렬), 하지만 60MB/s = 60 msg/s로는 파티션 분배가 거칠어 record-size 10KB, throughput=6000 msg/s(≈60MB/s)로 설정.

로컬 실행 (run-command):
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
/opt/kafka/bin/kafka-producer-perf-test.sh --topic lag-test --num-records 300000 --record-size 10240 --throughput -1 --producer-props bootstrap.servers=$BS acks=1 compression.type=lz4 2>&1 | tail -2
' --query "value[0].message" -o tsv
```
Expected: `... records/sec, ... MB/sec` — 달성 MB/s 기록. 60MB/s 미달이면 record-size/throughput 조정, 초과 가능하면 60MB/s로 상한.

- [ ] **Step 2: 캘리브레이션 값 기록**

달성 produce율(MB/s), 이를 60MB/s로 고정하기 위한 `--throughput`(msg/s) 값을 리포트 "캘리브레이션" 행에 기록.

### Task 1.2: Baseline 부하 실행 + lag 유발/회복 측정

**Files:** 없음

- [ ] **Step 1: 컨슈머 그룹을 느리게(뒤처짐 유발) 상태로 준비**

컨슈머는 `kafka-consumer-perf-test.sh` 대신, "피크 중 소비율 < produce율"을 만들기 위해 **produce를 먼저 일정량 선적재(backlog) 후 소비 시작**하는 방식으로 lag를 유발한다.

- [ ] **Step 2: Baseline 시나리오 — 60MB/s로 8분 produce, 2분 후 소비 시작**

로컬 실행 (run-command, 백그라운드 produce + 지연 소비). 스크립트가 produce를 nohup으로 띄우고, 120초 뒤 컨슈머를 붙여 lag 곡선을 만든다:
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
GROUP=lag-baseline
# produce ~8분치: 6000 msg/s * 480s = 2.88M, record 10KB
nohup /opt/kafka/bin/kafka-producer-perf-test.sh --topic lag-test --num-records 2880000 --record-size 10240 --throughput 6000 --producer-props bootstrap.servers=$BS acks=1 compression.type=lz4 >/tmp/prod_baseline.log 2>&1 &
echo "producer started pid $!"
sleep 120
# 소비를 produce보다 약간 느리게: 단일 소비프로세스로 시작(파티션 30개를 1 컨슈머가 → 자연 지연)
nohup /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server $BS --topic lag-test --group $GROUP --from-beginning >/tmp/cons_baseline.log 2>&1 &
echo "consumer started pid $!"
' --query "value[0].message" -o tsv
```
Expected: producer/consumer PID 출력.

- [ ] **Step 3: lag 곡선 폴링 (30초 간격, 최대 20분)**

로컬 실행 (run-command 반복). consumer-group describe로 총 lag를 폴링:
```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
for i in $(seq 1 40); do
  TS=$(date +%H:%M:%S)
  LAG=$(/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $BS --describe --group lag-baseline 2>/dev/null | awk "NR>1{s+=\$6} END{print s}")
  echo "$TS total_lag=$LAG"
  sleep 30
done
' --query "value[0].message" -o tsv
```
Expected: lag가 상승(수 분간 backlog 누적) → produce 종료(8분) 후 하강 → 0 복귀. **peak lag**, **produce 종료 시각**, **lag=0 복귀 시각** → 회복시간 산출.

- [ ] **Step 4: Baseline 결과 기록**

peak lag, 회복시간(초), 이 구간의 Grafana(디스크 read MB/s, page cache, under-replicated) 캡처 경로를 리포트 "Baseline" 행에 기록. 회복시간이 수 분급이면 lag 재현 성공.

- [ ] **Step 5: 정리 (그룹/오프셋 리셋)**

```bash
az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts '
BS=$(cat /opt/kafka/bootstrap.txt)
pkill -f kafka-console-consumer || true; pkill -f kafka-producer-perf || true
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server $BS --delete --group lag-baseline 2>&1 | tail -1
' --query "value[0].message" -o tsv
```

---

## Phase 2 — Arm A: 부하 축소 (핵심 증명)

### Task 2.1: 부하 배율별 회복시간 측정 (75% / 50% / 25%)

**Files:** 없음

- [ ] **Step 1: 각 배율 반복 실행 (Baseline과 동일 절차, `--throughput`만 변경)**

75%=4500, 50%=3000, 25%=1500 msg/s. 각 배율마다 Task 1.2의 Step 2~5를 그룹명 `lag-armA-<pct>`로 반복. 스크립트(배율 변수화):
```bash
for PCT in 75 50 25; do
  RATE=$((6000 * PCT / 100))
  GROUP=lag-armA-$PCT
  az vm run-command invoke -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen --command-id RunShellScript --scripts "
BS=\$(cat /opt/kafka/bootstrap.txt)
nohup /opt/kafka/bin/kafka-producer-perf-test.sh --topic lag-test --num-records \$(($RATE*480)) --record-size 10240 --throughput $RATE --producer-props bootstrap.servers=\$BS acks=1 compression.type=lz4 >/tmp/prod_$GROUP.log 2>&1 &
sleep 120
nohup /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server \$BS --topic lag-test --group $GROUP --from-beginning >/tmp/cons_$GROUP.log 2>&1 &
echo started $GROUP rate=$RATE
" --query "value[0].message" -o tsv
  # 이어서 Task 1.2 Step 3 폴링 스크립트를 그룹명만 바꿔 실행, 회복시간 기록, Step 5 정리
done
```
Expected: 배율이 낮아질수록 peak lag↓, 회복시간↓. 어느 배율에서 회복<60초가 되는지 임계 도출.

- [ ] **Step 2: Arm A 결과표 기록 + 임계 부하 도출**

리포트 "Arm A" 표에 배율·produce율(MB/s)·peak lag·회복시간(초) 기록. "회복<1분 임계 부하율" 명시. 프로덕션 환산: 임계 부하율 → "브로커 N대 증설 시 per-broker 유입률 = 임계율" 역산.

- [ ] **Step 3: 커밋**

```bash
git add docs/superpowers/reports/2026-07-15-hdinsight-kafka-lag-results.md
git commit -m "docs(hdinsight): record baseline + arm A load-scaling results

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Phase 3 — Arm B: 브로커 RAM 확대 (게이트 스트레치)

> **게이트:** Phase 0~2 종료 후 남은 시간·예산 확인. HDInsight 재생성 ~20-30분 + 재테스트 ~20분. 여유 있을 때만 진행. 없으면 Phase 4로.

### Task 3.1: 32 GB 브로커로 클러스터 재생성

**Files:**
- Modify: `~/.copilot/session-state/7b4d87cb-701e-412d-b7dc-fce27943d35c/files/hdi-kafka-template-public.json` (workernode vmSize → `Standard_D8a_v4`)

- [ ] **Step 1: 템플릿 워커 SKU를 D8a_v4(32GB)로 변경**

`hdi-kafka-template-public.json`의 `workernode` 역할 `hardwareProfile.vmSize`를 `Standard_D4ads_v5` → `Standard_D8a_v4`로 수정(디스크/카운트 유지). headnode/zk는 유지해 비용 억제.

- [ ] **Step 2: 클러스터 삭제 후 재생성**

로컬 실행:
```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
az deployment group create -g rg-krafton-kafka-dev-jpe -n hdi-armB-$(date +%H%M%S) \
  --template-file ~/.copilot/session-state/7b4d87cb-701e-412d-b7dc-fce27943d35c/files/hdi-kafka-template-public.json
```
Expected: 배포 성공, 클러스터 `Running`. (20-30분 소요.)

- [ ] **Step 3: Task 0.2~0.3 재실행 (브로커 재검색, 토픽 재생성)**

새 브로커 호스트로 `bootstrap.txt` 갱신, `lag-test` 토픽 재생성.

### Task 3.2: Baseline 부하로 Arm B 측정

- [ ] **Step 1: Baseline과 동일 60MB/s 부하 재실행 (그룹 `lag-armB`)**

Task 1.2 절차 그대로, 32GB 브로커에서 실행. Expected: T_cache 2배 → 같은 부하에서 peak lag↓, 회복시간↓.

- [ ] **Step 2: Arm B 결과 기록 + 커밋**

리포트 "Arm B" 행에 기록. Baseline(16GB) 대비 회복시간 개선률 명시.
```bash
git add -A && git commit -m "docs(hdinsight): record arm B broker RAM results

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

## Phase 4 — 결과 종합 및 정리

### Task 4.1: 결론·프로덕션 권고 작성

- [ ] **Step 1: 리포트 "결론" 섹션 작성**

- Baseline에서 재현된 lag(peak/회복) → 프로덕션 7분과 자릿수 정합 확인
- Arm A: 회복<1분 임계 부하율 X% → 프로덕션 환산 "브로커 18→N대 증설 또는 유입률 X% 절감"
- Arm B(수행 시): RAM 2배 → 회복시간 Y% 개선 → "브로커 RAM 상향" 정량 효과
- 최소 비용 권고: 컨슈머 증설 무효(파티션 180 상한), 유효 레버는 [브로커 증설 / RAM↑ / 디스크 tier↑]

- [ ] **Step 2: Arm C/D 후속 안내 명시**

Arm C(Premium SSD, HDInsight 디스크 지원 확인 필요)·Arm D(AKS+실제 rdkafka fetch 튜닝)는 오늘 예산·시간 밖 → 후속 실행 항목으로 리포트에 명시.

- [ ] **Step 3: 최종 커밋 + push**

```bash
git add -A
git commit -m "docs(hdinsight): finalize lag scaled-test results and prod recommendation

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
git push origin main
```

### Task 4.2: 비용 정리 (teardown)

- [ ] **Step 1: 유휴 VM deallocate**

로컬 실행:
```bash
az vm deallocate -g rg-krafton-kafka-dev-jpe -n vm-kafka-loadgen
az vm deallocate -g rg-krafton-kafka-dev-jpe -n vm-monitoring
```
Expected: 두 VM `deallocated`.

- [ ] **Step 2: 클러스터 존치 여부 확인 (사용자 결정)**

HDInsight는 정지 불가(비용 지속). 후속 Arm C/D 미실행 시 사용자에게 `teardown.sh` 실행 여부 확인. 무단 삭제 금지.

---

## 결과 리포트 템플릿 (`docs/superpowers/reports/2026-07-15-hdinsight-kafka-lag-results.md` 초기 내용)

```markdown
# HDInsight Kafka Lag 축소 실증 테스트 — 결과

- 실행일: 2026-07-15 | 리전: japaneast | 클러스터: krafton-kafka-hdi-68944
- 목표: consumer lag "1분 이내 회복" 가능성 실증

## 한눈에 보기

| Arm | 구성 | 부하(produce) | Peak lag | 회복시간 | 판정 |
|---|---|---|---|---|---|
| 캘리브레이션 | 16GB×3 | 상한 측정 | — | — | ⏳ |
| Baseline | 16GB×3 | 60 MB/s (100%) | — | — | ⏳ |
| Arm A-75 | 16GB×3 | 45 MB/s (75%) | — | — | ⏳ |
| Arm A-50 | 16GB×3 | 30 MB/s (50%) | — | — | ⏳ |
| Arm A-25 | 16GB×3 | 15 MB/s (25%) | — | — | ⏳ |
| Arm B | 32GB×3 | 60 MB/s (100%) | — | — | ⏳ |

판정: ✅ 회복<60s / ⚠️ 1-3분 / ❌ >3분 / ⏳ 미실행

## Arm별 상세
(각 Arm: 실행 시각, produce 로그 요약, lag 폴링 원자료, Grafana 캡처 경로)

## 결론 및 프로덕션 권고
(Phase 4에서 작성)

## 후속 (오늘 범위 밖)
- Arm C: Premium SSD 디스크 tier — HDInsight 지원 확인 후
- Arm D: AKS + 실제 rdkafka fetch 파라미터 튜닝
```

---

## Self-Review 체크

- **Spec 커버리지:** spec §3 테스트베드→Phase 0, §3.1 실행위치(VM)→Phase 0~2, §4 매트릭스 Baseline/A/B→Phase 1~3, C/D→Phase 4 후속 명시, §5 측정지표→lag 폴링+Grafana, §6 절차→Phase 순서, §7 제약(재생성 비용·teardown)→Phase 3 게이트+4.2. 커버됨.
- **범위:** 오늘/$1000 현실 반영 — Baseline+Arm A 보장, Arm B 게이트, C/D 후속. Money보다 시간이 제약임을 명시.
- **실행 모델 일관성:** 모든 Kafka 작업 `vm-kafka-loadgen` run-command 경유, bootstrap.txt 재사용. 그룹명 규칙 `lag-<arm>` 일관.
