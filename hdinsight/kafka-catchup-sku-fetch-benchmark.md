# HDInsight Kafka lag/catch-up 벤치마크 — broker SKU / consumer fetch size

- Date: 2026-07-16 | Region: japaneast | Cluster: `krafton-kafka-hdi-68944` (HDInsight Kafka, broker 3)
- Scope: partition·consumer 수 고정 조건에서 broker VM SKU, consumer fetch size 2개 변수만 스윕. 특정 축소 구성·특정 배포 인스턴스 한정 관측값이며 일반화 결론 아님.
- Base SKU 기준: 고객 운영 worker = D8a_v4 (8 vCPU / 32GB) × 18. 본 테스트 base를 이에 맞춰 D8(32GB)로 두고 D16(64GB)으로의 상향 효과를 주 비교축으로 함(D4는 하위 참고점).

## 1. 측정 동기

- 운영 관찰:
  - partition 수 = consumer pod 수 (1:1 고정 운영).
  - log 50% + partition/consumer 축소 → 정상.
  - log 100% + partition/consumer 증설 → 주간 peak 구간에서 consumer lag 7분 이상.
- 유입 특성: 일 15TB 규모, 야간 무부하 / 주간 특정 시간대 집중. peak 구간에서 순간 유입률 상승.
- 점검 항목: partition·consumer 수 고정 상태에서 아래 2개 변수만으로 소비 상한(C) 완화 여부.
  - `broker VM SKU`
  - `consumer fetch size` (`max.partition.fetch.bytes`, `fetch.max.bytes`)

## 2. lag 메커니즘 (측정 해석 기준)

- 정의: `lag(t) = ∫ (P − C) dt`. P = 순간 produce rate, C = 순간 consume rate.
  - `P ≤ C`: lag 미발생 또는 감소.
  - `P > C`: lag 증가. 증가 기울기 = `P − C`.
  - burst 종료 후 catch-up 속도 = `C − P_잔여`. lag 해소 시간 ≈ `누적 lag ÷ (C − P)`.
- 연속 파이프라인(producer→kafka→consumer 상시)에서 consumer는 log tail(최근 오프셋)을 읽음.
  - tail 데이터가 broker page cache에 상주하면 disk read 비중 낮음.
  - 반대로 유입 P가 커져 consumer가 뒤처지면 read 오프셋이 tail에서 멀어지고, working set이 broker page cache를 초과하면 read가 disk로 내려가 C가 하락.
- 따라서 점검 대상은 **소비 상한 C를 무엇이 제한하며, SKU/fetch 조정이 C를 올리는가**.
- C 제한 후보:
  1. broker fetch 처리 + replication + page cache 적중률 (broker CPU/RAM/disk/network) → broker SKU-up 시 완화 가능.
  2. consumer pod의 per-message 처리 (역직렬화·애플리케이션 로직) → broker SKU-up 무관, pod 증설/파티션 증설 필요.
  3. partition 직렬화 (partition 1 = consumer 1) → partition 증설 필요.

## 3. 스펙 / 측정 구성

| item | value |
|---|---|
| Cluster | HDInsight Kafka, worker(broker) 3 |
| 고객 운영 worker | D8a_v4 (8 vCPU / 32GB) × 18, data disk Standard HDD S30(1TB) × 노드당 4 |
| 테스트 worker SKU | D4 = D4ads_v5 (4 vCPU / 16GB) · **D8 = D8ads_v5 (8 vCPU / 32GB, base)** · D16 = D16ads_v5 (16 vCPU / 64GB) |
| Topic | `cont2`, partition 12, RF 2, `retention.ms=1800000`(30min), `retention.bytes` 무제한 |
| partition : consumer | 12 : 12 (fixed) |
| Producer | `vm-kafka-producer` (별도 VM), 8 parallel `kafka-producer-perf-test` 상시 유입 (record 1KB, acks 1, linger 15ms, batch 256KB, compression none) |
| Consumer(측정) | `vm-kafka-loadgen` (별도 VM), 단일 `kafka-consumer-perf-test`, from-earliest, `--messages 4,000,000` (≈4GB) |
| 지표 | perf 출력의 `fetch.MB.sec` (rebalance 시간 제외한 순수 fetch 구간 처리율) |

> 주: 테스트는 `Dads_v5`(로컬 NVMe temp + managed data disk), 고객 운영은 `D8a_v4` + S30 HDD로 SKU 세대·disk 구성이 다르다. 절대값 1:1 이식 불가, RAM(page cache) 축의 방향성 참고용.

### 3-1. SKU별 문서화된 I/O 상한 (Azure VM 스펙)

소비 상한을 제한하는 disk·network 경계는 SKU별로 문서화돼 있다. Kafka 소비가 page cache 밖으로 나가 disk read로 내려가면, 아래 **uncached data disk throughput**이 상한이 된다(단, 실제 부착 disk 종류의 한계가 더 낮으면 그쪽이 실효 상한).

테스트 SKU (Dadsv5):

| SKU | vCPU / RAM | uncached disk IOPS / MBps | temp SSD RR MBps | NIC Mbps |
|---|---|---|---|---|
| D4ads_v5 | 4 / 16GB | 6,400 / **144** | 250 | 12,500 |
| D8ads_v5 | 8 / 32GB | 12,800 / **200** | 500 | 12,500 |
| D16ads_v5 | 16 / 64GB | 25,600 / **384** | 1,000 | 12,500 |

고객 운영/상향 축 (Dav4, Premium Storage 미지원 → Standard HDD/SSD):

| SKU | vCPU / RAM | uncached disk IOPS / MBps | NIC Mbps |
|---|---|---|---|
| **D8a_v4 (현재)** | 8 / 32GB | 12,800 / **192** | 8,000 |
| D16a_v4 | 16 / 64GB | 25,600 / **384** | 10,000 |
| D32a_v4 | 32 / 128GB | 51,200 / **768** | 16,000 |

- 부착 disk: HDInsight worker는 Standard HDD **S30**(disk당 500 IOPS / 60 MBps). 노드당 4개면 disk 자체 상한은 약 2,000 IOPS / 240 MBps(순차). random read(파티션 분산 cache-miss fetch)는 **IOPS 바운드**라 순차 MBps보다 훨씬 낮게 걸림.
- 즉 disk-bound 시 실효 상한 = min(VM uncached MBps 상한, 부착 disk 종합 한계). S30 HDD에서는 후자(IOPS)가 지배적.

## 4. 방법 (연속 파이프라인 소비 상한 측정)

- producer VM에서 8 parallel producer를 상시 실행해 유입 P를 지속 발생시킨다(연속 파이프라인 재현).
- 유입이 도는 상태에서, consumer VM에서 단일 `kafka-consumer-perf-test`(from-earliest, 4M msg ≈ 4GB)를 실행해 소비 상한 C를 측정한다.
  - producer와 consumer를 **서로 다른 VM**에서 실행 → 단일 VM CPU/NIC 공유로 인한 측정 아티팩트 배제.
  - 지표는 `fetch.MB.sec` 사용(group rebalance 대기 시간 제외).
- 변수: broker SKU(D4 / D8(base) / D16) × fetch size(`max.partition.fetch.bytes` 1MB / 4MB), 조건별 3회 측정 후 중앙값.
- 각 SKU 클러스터는 측정 전 단일-thread producer로 health check(정상 disk 배포 인스턴스 여부 확인) 후 측정. (D4 76.5 / D8 74.5 / D16 정상 MB/s → 세 배포 모두 정상 disk 확인)

## 5. 측정 범위 한계

- broker 3대 축소 구성. 운영 규모(18 broker, partition 180, pod 240) 절대 재현 아님.
- 측정 consumer는 `kafka-consumer-perf-test`로 byte 처리만 수행 → 운영 rdkafka pod의 애플리케이션 로직(역직렬화·처리) 미포함. 절대 처리량 1:1 비교 불가, broker/디스크/네트워크 측 소비 상한의 경향 참고용.
- **HDInsight worker data disk 성능은 배포 인스턴스마다 편차 존재**(내부 관리 Standard HDD, RG에 비노출). 절대값은 배포 편차를 포함하므로, 개별 수치보다 SKU 간 차수(order of magnitude) 차이를 robust한 관측으로 해석. 단 disk·network 상한은 SKU별로 문서화돼 있어(§3-1) 경계 해석의 기준으로 사용 가능(예: D16 측정치가 문서상 disk 상한을 초과 → cache 서빙 확정, §7).
- 조건별 3회 측정(중앙값). 미고정/미검증 변수: scale-out(partition·broker 증설), disk type, network, producer 특성, pod 처리 CPU.

## 6. 결과 (partition = consumer = 12 고정, 연속 파이프라인)

측정 전 health check(단일-thread producer): D4 76.5 / D8 74.5 / D16 정상 MB/s → 세 배포 인스턴스 모두 정상 disk 배포로 확인.

### 6-1. 소비 상한 C (single perf-consumer, from-earliest, `fetch.MB.sec` 중앙값)

| fetch size | D4 (16GB) | **D8 (32GB, base)** | D16 (64GB) | D8→D16 |
|---|---|---|---|---|
| 1 MB (default) | ~44 | ~48 | ~757 | ~16× |
| 4 MB | ~51 | ~68 | ~788 | ~12× |

- 원시값: D4 fetch1M 44.5/44.4/41.2, fetch4M 50.9/57.6/47.6. **D8 fetch1M 64.7/47.7/42.4, fetch4M 67.6/53.2/75.0.** D16 fetch1M 757/774/754, fetch4M 779/788/791.
- **비선형 관측**: D4→D8(RAM 16→32GB)에서 소비 상한은 거의 불변(44→48, 51→68). D8→D16(32→64GB)에서만 큰 점프. RAM 2배 증가가 항상 비례 개선을 주지 않으며, 특정 임계를 넘는 구간에서만 급등.
- fetch-size 효과(동일 SKU): D4 +16%, D8 +42%, D16 +4%. SKU 상향 대비 작고 일관적이지 않음.

### 6-2. 유입 P (8 parallel producer 합산 유입률, 참고)

| item | D4 (16GB) | D8 (32GB) | D16 (64GB) |
|---|---|---|---|
| producer aggregate (8 parallel) | ~303 | ~521 | ~588 |

- 동일 8-parallel 유입에서 broker 수용 합산 유입률도 SKU에 따라 증가(303 → 521 → 588).

## 7. 관측 경향 (본 조건·본 배포 인스턴스 한정)

- 연속 파이프라인에서 소비 상한 C:
  - D4(16GB) ~44/51, **D8(32GB) ~48/68** MB/s: 유입 P가 소비 오프셋을 tail에서 밀어내 read working set이 page cache 밖으로 나가면 C가 disk read 대역(수십 MB/s)에 머묾. 고객 base와 동일 RAM(32GB)인 D8도 이 구간에 위치.
  - D16(64GB) ~757/788 MB/s: 동일 조건에서 큰 폭 상승.
  - **D8→D16 상향 시 소비 상한이 약 12~16× 상승 관측.**
  - **문서화된 상한 대조로 원인 일부 확인**: D16 측정치 ~757~788 MB/s는 D16ads_v5의 uncached data disk 상한(384 MBps)을 **초과** → 이 처리량은 물리적으로 disk가 아니라 **page cache(RAM)에서 서빙**됐음을 의미(§3-1 표). 반면 D4/D8 측정치(~44~68)는 각 SKU의 disk MBps 상한(144/200)보다 **낮음** → 순차 대역이 아니라 Standard HDD의 **random-read IOPS**에 걸린 disk-bound 상태.
  - 따라서 D8→D16 급등은 "32GB에서는 working set이 cache 밖 → HDD IOPS 바운드 / 64GB에서는 cache 상주 → RAM 속도"로 해석되며, page cache 용량 임계 효과가 지배적. 단 절대 배율은 배포 disk 편차·SKU 세대 차이를 포함하므로 §8 진단으로 운영 환경에서 재확인.
- fetch-size 효과: SKU 상향 대비 작음(D8 1MB→4MB +42%로 상대적으로 크나 절대값은 여전히 disk 대역).
- 7x(≈7min→1min) catch-up 단축을 단일 변수로 단정하지 않음. 본 관측은 "고객 base(32GB)는 disk 대역에 가깝고, 64GB로 상향 시 소비 상한이 크게 오를 수 있다"는 방향성까지. 실효 여부는 §8 진단으로 운영 병목이 broker I/O 측인지 확인 후 판단.

## 8. SKU 상향 실효 판단 — 지연이 어느 경계에서 나는지 진단

본 벤치의 "D8→D16 급등"은 **broker I/O(page cache 미스 → disk read)가 병목일 때만** SKU 상향이 유효하다는 가설과 일치한다. 따라서 실제 적용 전, lag 발생 구간에 아래 지표로 병목 경계를 먼저 특정한다. 지표 수집 수단은 관련 문서(모니터링·Prometheus/Grafana) 참고.

### 8-1. broker I/O(disk) 바운드인지 — 이러면 SKU 상향 유효

lag 발생 구간에 broker(worker) 노드에서:

| 지표 | 출처 | disk-bound 판정 |
|---|---|---|
| disk read throughput / `%util` / `await` | `iostat -x 1`, node exporter | data disk `%util` 지속 ~100%, `await` 상승, read MB/s가 disk 상한에 붙음 |
| page cache read hit | `free -m`(buff/cache), `/proc/vmstat` `pgmajfault`, `cat /proc/pressure/io` | major fault·IO pressure 증가, buff/cache가 유입 대비 부족 |
| broker 요청 처리 여력 | JMX `kafka.server:RequestHandlerAvgIdlePercent`, `NetworkProcessorAvgIdlePercent` | idle%가 낮음(0에 근접)이지만 CPU util은 100% 아님 → I/O 대기 |
| fetch 지연 | JMX `TotalTimeMs`(Fetch) `LocalTimeMs`/`RemoteTimeMs` | fetch `LocalTimeMs`(disk read 구간) 상승 |
| under-replicated | JMX `UnderReplicatedPartitions` | 0 유지(디스크 포화면 replication도 밀려 >0 가능) |

- 판정: **data disk `%util`≈100% + `await` 상승 + page cache 부족(major fault↑) + CPU는 여유** → read가 disk 상한에 걸린 I/O 바운드. RAM(page cache)·disk 대역이 큰 SKU로 상향하면 완화 기대. 본 벤치의 D8→D16 급등이 이 시나리오에 해당.
- **문서화된 상한과 대조**(§3-1): 관측 disk read MB/s를 (1) VM uncached disk MBps 상한, (2) 부착 disk(S30) 종합 IOPS/MBps와 비교한다.
  - 관측 read가 **부착 HDD IOPS 한계**(S30 노드당 ~2,000 IOPS)에 붙어 있고 MBps는 VM 상한보다 낮음 → **IOPS 바운드**. disk 종류 상향(Premium SSD)·RAM 큰 SKU(cache로 disk 회피)가 유효.
  - 관측 read가 **VM uncached MBps 상한**에 붙음 → VM disk cap 바운드. 상위 SKU(더 큰 MBps 상한)로 상향 유효.
  - 소비 처리량이 **VM disk 상한을 초과**(예: D16 757 > 384) → 이미 page cache 서빙 중. 추가 disk 상향보다 RAM(cache) 확보가 핵심.

### 8-2. broker CPU/network 바운드인지 — 이러면 SKU 상향(코어·NIC) 유효

| 지표 | disk-bound과 구분 |
|---|---|
| broker CPU util | 지속 ~100%이고 disk `%util`은 낮음 → CPU 바운드(압축·TLS·요청 처리) |
| NIC throughput | VM NIC 상한 근접 → network 바운드. 둘 다 큰 SKU에서 상향 |

### 8-3. broker가 아니라 consumer/partition 바운드인지 — 이러면 SKU 상향 무효

| 지표 | 출처 | 판정 |
|---|---|---|
| consumer pod CPU / 처리시간 | pod 메트릭, rdkafka 처리 지연 | pod CPU ~100%인데 broker disk/CPU는 여유 → **pod 처리 병목**. broker SKU 상향 무효, pod/partition scale-out 필요 |
| partition별 lag 분포 | `kafka-consumer-groups --describe`, kafka-exporter | 특정 partition만 lag 편중 → 파티션 skew/직렬화. partition 재분배·증설 필요 |
| broker 자원 여유 여부 | 위 8-1/8-2 지표 | broker disk·CPU·network 모두 여유인데 lag 증가 → 병목은 broker 밖(consumer/partition) |

### 8-4. 결정 흐름

1. lag 구간에 broker disk `%util`/`await`, page cache, CPU, NIC, `RequestHandlerAvgIdlePercent`를 동시 수집.
2. **disk 또는 CPU/NIC가 broker에서 포화** → broker SKU 상향(RAM·코어·disk/NIC 대역) 유효 후보. 본 벤치 D8→D16 결과가 이 근거.
3. **broker 자원은 여유인데 pod CPU 포화 / 특정 partition lag 편중** → SKU 상향 무효. pod·partition scale-out.
4. 상향 전/후 동일 지표를 재수집해 소비 상한 C 상승·lag 해소 시간 단축을 실측 검증(본 벤치는 절대값 이식 불가, 방향성 근거).

## 9. 해석 시 주의

- 본 결과의 C는 broker/disk/network 측 소비 상한이며, 운영 rdkafka pod의 per-record 처리 상한은 별도.
- D8→D16 급등은 문서화된 disk 상한 대조로 **page cache(RAM) 임계 효과가 지배적**임을 확인(D16 측정 757 > D16 uncached disk 384 MBps, §7·§3-1). 다만 배포별 disk 편차·SKU 세대 차이가 절대 배율에 섞이므로 운영 환경에서는 §8 진단으로 병목 위치를 특정한 뒤 상향 결정.
- 절대 수치는 배포 인스턴스 disk 편차 및 SKU 세대·disk 구성 차이(테스트 Dads_v5 vs 고객 D8a_v4+S30)를 포함. 재현 시 값이 달라질 수 있으므로 SKU 간 상대 차이·방향성을 우선 참고.
- 고객이 Dav4 계열 내에서 상향하면 disk MBps 상한은 D8a_v4 192 → D16a_v4 384 → D32a_v4 768로 배가되나, **Dav4는 Premium Storage 미지원**이라 부착 disk가 Standard HDD/SSD로 제한된다. disk-bound(IOPS)가 병목이면 SKU 상향과 함께 **disk 종류 상향(Premium SSD 지원 계열, 예: Dasv5)** 검토가 더 직접적일 수 있음.
- 병목 위치에 따라 유효 레버가 다름: broker I/O 병목 → SKU-up(RAM·disk·NIC) + fetch size 상향 / pod 처리 병목 → pod·partition scale-out(broker SKU 무관).

## 10. 후속 측정 후보 (미검증)

- scale-out(partition·pod·broker 동시 증설) catch-up 영향.
- 운영 rdkafka pod 로직 포함 end-to-end 측정.
- 다수 client에서 broker-side C 정밀화, 배포 인스턴스 반복 측정으로 disk 편차 정량화.
- disk type(Premium SSD v2 등), network, producer 특성 영향.

## 11. Teardown

- Cluster `krafton-kafka-hdi-68944`: deleted (D4·D8·D16 각 테스트 후 재생성/삭제).
- VM `vm-kafka-producer`, `vm-kafka-loadgen`, `vm-jumpbox`, `vm-monitoring`: deallocated/삭제.

```bash
az hdinsight delete -g rg-krafton-kafka-dev-jpe -n krafton-kafka-hdi-68944 --yes
# 전체 정리: az group delete -n rg-krafton-kafka-dev-jpe --yes
```

- 재현 아티팩트: worker SKU별 private template(`hdi-priv-Standard_D4ads_v5.json`, `hdi-priv-Standard_D8ads_v5.json`, `hdi-priv-Standard_D16ads_v5.json`), 연속 파이프라인 harness(producer VM 8-parallel flood + consumer VM single perf-consumer, fetch size 스윕).

## 관련 문서

- [`../monitor/hdinsight-kafka-monitoring.md`](../monitor/hdinsight-kafka-monitoring.md) — HDInsight Kafka 모니터링 개요(Azure Monitor·Log Analytics·Ambari·진단설정).
- [`../monitor/hdinsight-kafka-prometheus-grafana.md`](../monitor/hdinsight-kafka-prometheus-grafana.md) — Prometheus + Grafana broker JMX·kafka-exporter(partition별 lag) 대시보드 구성.
