---
title: "Azure HorizonDB와 PostgreSQL Flexible Server 성능 비교: pgbench 쓰기·읽기와 DiskANN 벡터 검색"
description: 같은 4 vCore 조건의 Azure HorizonDB(미리 보기)와 Azure Database for PostgreSQL flexible server를 AKS의 같은 Pod에서 pgbench TPC-B·읽기 전용 부하와 1,024차원 벡터 20만 건의 적재·DiskANN index 생성·k-NN 검색으로 비교하고, 두 서비스의 저장 구조 차이가 결과에 어떻게 드러나는지 정리합니다.
document_type: research
services: [azure-horizondb, azure-database-for-postgresql]
technologies: [postgresql]
tags: [evaluate, optimize]
status: current
verification_status: needs-review
sources_checked_at: 2026-11-15
official_sources:
  - title: What is Azure HorizonDB (Preview)?
    url: https://learn.microsoft.com/azure/horizondb/overview
  - title: Choose the right vector index for your workload in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-selection-guide
  - title: Scalable vector index with DiskANN in Azure HorizonDB (Preview)
    url: https://learn.microsoft.com/azure/horizondb/ai/vector-index-diskann
  - title: Storage in Azure Database for PostgreSQL flexible server
    url: https://learn.microsoft.com/azure/postgresql/compute-storage/concepts-storage
  - title: What is Azure Database for PostgreSQL?
    url: https://learn.microsoft.com/azure/postgresql/overview
  - title: pgbench
    url: https://www.postgresql.org/docs/17/pgbench.html
published_at: 2026-11-15
topic_order: 3
---

# Azure HorizonDB와 PostgreSQL Flexible Server 성능 비교: pgbench 쓰기·읽기와 DiskANN 벡터 검색

## 비교 결과: 쓰기 처리량은 HorizonDB 우위, 벡터 검색 지연은 Flexible Server 우위 { #summary }

2026-11-15 Korea Central에서 같은 4 vCore 크기의 두 서비스를 같은 클라이언트로 측정했습니다. HorizonDB는
WAL만 저장 계층에 쓰는 구조로, 쓰기 위주 TPC-B에서 처리량이 16–24% 높았고 동시 연결이 많을수록 차이가
커졌습니다. 읽기 전용 부하는 같았고, 1,024차원 벡터 20만 건의 DiskANN 검색은 Flexible Server가 조금 빨랐습니다.

| 부하 | HorizonDB | Flexible Server | 차이 |
|---|---|---|---|
| TPC-B 쓰기, 16 연결(2회 평균) | 2,253 tps · 7.1 ms | 1,946 tps · 8.2 ms | HorizonDB 처리량 +16% |
| TPC-B 쓰기, 64 연결 | 5,115 tps · 12.5 ms | 4,108 tps · 15.6 ms | HorizonDB 처리량 +24% |
| 읽기 전용(`-S`), 32 연결 | 36,757 tps · 0.87 ms | 36,187 tps · 0.88 ms | 같음 |
| `pgbench -i -s 100` 초기 적재(1,000만 행) | 9.6초 | 28.3초 | HorizonDB 약 3배 빠름 |
| 벡터 20만 건 `INSERT ... SELECT` | 19.7초 | 22.3초 | HorizonDB 12% 빠름 |
| DiskANN index 생성(1.6 GB) | 213초 | 225초 | HorizonDB 5% 빠름 |
| k-NN 10건, 8 연결 | 349 qps · 23.0 ms | 416 qps · 19.2 ms | Flexible Server 지연 16% 짧음 |
| 필터(선택도 2%) + k-NN 10건, 8 연결 | 29 qps · 272 ms | 54 qps · 149 ms | Flexible Server 지연 45% 짧음 |

TPC-B 16 연결은 두 번, 나머지는 한 번씩 실행한 결과이며 HorizonDB는 미리 보기입니다. 이 크기와 조건에서의
관찰이므로 일반적인 성능 비율로 해석하지 않습니다.

## 측정 환경: 같은 vCore·메모리, 같은 클라이언트 { #environment }

| 항목 | Azure HorizonDB | Azure Database for PostgreSQL flexible server |
|---|---|---|
| 버전 | PostgreSQL 17.11(HorizonDB 빌드) | PostgreSQL 17.11 |
| compute | pool 1개, Intel 1세대 4 vCore, node 1개, HA 없음 | Memory Optimized `Standard_E4ds_v5`(4 vCore, 32 GiB), HA 없음 |
| 메모리 | vCore당 8 GB(32 GB), `shared_buffers` 19,297 MB | 32 GiB, `shared_buffers` 8 GB |
| 저장소 | WAL 전용 서비스와 data 저장 fleet, 크기·IOPS 설정 없음 | Premium SSD 512 GiB(프로비저닝 2,300 IOPS, burst 3,500) |
| 벡터 확장 | `vector` 0.8.7, `pg_diskann` 0.7.6 | `vector`, `pg_diskann` 0.6.6 |
| 접속 | public endpoint, TLS | public access, TLS |

클라이언트는 같은 지역 AKS의 `postgres:17` Pod(1 vCPU 요청) 하나이며, `pgbench` 17.12로 두 서버에 차례로 부하를
보냈습니다. 측정하는 동안 MovieLog의 부하 생성기는 멈췄고, 두 서버 모두 연결 풀러 없이 직접 접속했습니다.

## 쓰기 처리량: WAL만 쓰는 저장 구조 { #write }

TPC-B는 계좌 잔액 갱신과 이력 INSERT를 한 transaction으로 반복하는 쓰기 위주 부하입니다. scale 100이라
`pgbench_accounts`는 1,000만 행이고 foreign key를 포함했습니다.

```bash
pgbench -i -s 100 -q --foreign-keys bench
pgbench -c 16 -j 4 -T 120 -n bench     # 64 connections: -c 64 -j 8
pgbench -S -c 32 -j 4 -T 60 -n bench   # read-only
```

HorizonDB 문서는 compute가 WAL만 저장 계층에 보내고 data page는 쓰지 않는다고 설명합니다. checkpoint·dirty page
기록·full page write·백업은 저장 계층이 맡으므로, 쓰기 증폭이 줄고 DB 크기와 상관없이 쓰기 지연이 일정합니다.
Flexible Server는 Linux VM 안의 container에서 엔진이 돌고, data 파일은 동기식 3중 로컬 복제되는 Azure 저장소에
있어 엔진이 WAL과 data page를 모두 그 저장소(이번 구성은 2,300 IOPS로 프로비저닝된 512 GiB Premium SSD)에 씁니다. 쓰기 처리량 차이는 연결이 16개에서 64개로 늘 때 16%에서 24%로 커졌고, COPY 위주의 초기
적재는 약 3배 차이가 났습니다. 읽기 전용 부하는 데이터가 두 서버의 메모리에 모두 들어가 차이가 없었습니다.

## 벡터 적재와 검색: 1,024차원 20만 건과 DiskANN { #vector }

임의 값으로 만든 1,024차원 벡터 20만 건과 범주 열(`cat`, 50개 값)을 같은 SQL로 넣고 DiskANN 코사인 index를
만들었습니다. 질의 벡터는 테이블의 임의 행을 씁니다.

```sql
CREATE TABLE v (id bigint PRIMARY KEY, cat int, e vector(1024));
INSERT INTO v SELECT g, g % 50,
  (SELECT array_agg(random()::real - 0.5) FROM generate_series(1, 1024) WHERE g > 0)::vector
FROM generate_series(1, 200000) g;
CREATE INDEX v_diskann ON v USING diskann (e vector_cosine_ops);

CREATE INDEX v_cat ON v (cat);
```

두 pgbench 스크립트를 각각 `pgbench -n -c 8 -f <script> bench` 형식으로 8 연결에서 실행했습니다.

```text
-- knn.sql: k-NN
\set id random(1, 200000)
SELECT id FROM v ORDER BY e <=> (SELECT e FROM v WHERE id = :id) LIMIT 10;

-- knn-filter.sql: k-NN with a 2% filter
\set id random(1, 200000)
\set c random(0, 49)
SELECT id FROM v WHERE cat = :c ORDER BY e <=> (SELECT e FROM v WHERE id = :id) LIMIT 10;
```

- **적재와 index 생성** — 두 서비스가 비슷했고 HorizonDB가 5–12% 빨랐습니다. index 크기는 둘 다 1,606 MB였습니다.
- **k-NN 검색** — 두 서비스 모두 `Index Scan using v_diskann`을 썼습니다. 평균 지연은 Flexible Server 19.2 ms,
  HorizonDB 23.0 ms였습니다. 데이터와 index가 메모리에 들어가는 크기라 저장 구조보다 compute 차이가 드러난 것으로 봅니다.
- **필터 결합 검색** — 두 서비스의 실행 계획이 달랐습니다.
  - HorizonDB의 `pg_diskann` 0.7.6은 advanced filtering 경로 `DiskANNFilteredScan`(전략 `Filter(BitmapHeapScan) -> Vector`)을
    골라, 조건에 맞는 행을 먼저 모은 뒤 거리를 계산했습니다.
  - Flexible Server의 0.6.6은 DiskANN index를 탐색하면서 조건을 거르는 후필터 계획을 썼습니다.
  - 선택도 2%에서는 후필터가 더 빨랐습니다. HorizonDB에서 `diskann.enable_filter_hook`을 끄면 후필터 계획으로 바뀌었고,
    단건 실행 시간은 53.7 ms였습니다.

Learn의 HorizonDB index 선택 기준은 DiskANN이 데이터 대부분을 SSD에 두어 메모리를 적게 쓰고, 연속 INSERT, 1천만 행을
넘는 규모, 필터 결합 검색에 맞는다고 설명합니다. 이번 20만 건은 메모리에 들어가는 크기라 그 장점이 드러나는 조건이
아니었습니다.

## 서비스 선택 기준: 부하 유형별 비교 { #interpretation }

| 상황 | 이번 측정과 문서가 가리키는 쪽 |
|---|---|
| 쓰기가 많고 동시 연결이 많은 OLTP | HorizonDB. 쓰기 처리량이 16–24% 높았고, 저장 계층이 checkpoint·백업 I/O를 맡습니다. |
| 대량 적재(COPY, 초기 이관) | HorizonDB. 1,000만 행 초기 적재가 약 3배 빨랐습니다. |
| 읽기 위주, 데이터가 메모리에 들어감 | 차이 없음. 비용과 지원 기능(GA 여부, HA, 백업 보존 기간)으로 고릅니다. |
| 메모리에 들어가는 규모의 벡터 검색 | 비슷함. 필터 결합 검색은 선택도에 따라 계획이 달라지므로 `EXPLAIN`으로 확인합니다. |
| 읽기 확장, 빠른 failover | HorizonDB 문서는 replica가 같은 저장소를 공유해 복제 없이 빠르게 추가되고 failover도 빠르다고 설명합니다. 이번에는 측정하지 않았습니다. |

HorizonDB는 미리 보기라 다음 제약이 있습니다. 운영 요구 사항이 여기에 걸리면 성능과 상관없이 Flexible Server가 맞습니다.

- 백업 보존 기간 7일 고정(Flexible Server는 최대 35일)
- 지역 간 read replica, 고객 관리 키, 내장 PgBouncer, VNet injection 미지원(Flexible Server는 내장 PgBouncer와 VNet 통합 지원)

## 측정 한계: 실행 횟수 · 데이터 분포 · compute 세대 { #limitations }

- 실행 횟수가 적고(대부분 1회) 분산을 재지 않았습니다.
- 벡터는 임의 값이라 실제 임베딩의 분포와 다르고, recall은 측정하지 않았습니다.
- HorizonDB의 compute 세대(Intel 1세대)와 Flexible Server `E4ds_v5`의 CPU가 달라, CPU 위주 부하의 차이에는 compute
  차이가 섞여 있습니다.
- 비용은 비교하지 않았습니다. HorizonDB는 compute(core hour)·사용 저장소·백업 저장소로, Flexible Server는 compute·
  프로비저닝한 저장소·IOPS로 과금합니다.
