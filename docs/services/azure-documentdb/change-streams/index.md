---
title: Azure DocumentDB change stream을 Python으로 AKS에서 검증하기
description: 프라이빗 엔드포인트 뒤의 Azure DocumentDB(vCore) 클러스터에서 PyMongo change stream의 지원 범위, 재개, 중복 처리와 지연을 AKS consumer로 측정합니다.
document_type: lab
services: [azure-documentdb, azure-kubernetes-service]
technologies: [python, mongodb, kubernetes, bicep]
tags: [build, evaluate]
status: verified
verification_status: verified
sources_checked_at: 2026-10-02
official_sources:
  - title: Change streams in Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/change-streams
  - title: $changeStream (Azure DocumentDB aggregation operator)
    url: https://learn.microsoft.com/documentdb/query/operators/aggregation/$changestream
  - title: Use Azure Private Link in Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/how-to-private-link
  - title: Compute and storage configurations for Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/compute-storage
  - title: Release notes for Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/release-notes
  - title: Microsoft.DocumentDB mongoClusters (Bicep reference)
    url: https://learn.microsoft.com/azure/templates/microsoft.documentdb/2026-06-01/mongoclusters
  - title: AzureCosmosDB/changestream-driver-compatibility
    url: https://github.com/AzureCosmosDB/changestream-driver-compatibility
last_verified: 2026-10-02
review_cycle_days: 90
estimated_time: 90m
cost: paid
cleanup_required: true
---

# Azure DocumentDB change stream을 Python으로 AKS에서 검증하기

Azure DocumentDB(이전 이름 Azure Cosmos DB for MongoDB vCore)는 MongoDB
change stream을 제공합니다. 다만 지원 범위가 MongoDB 서버와 다르므로 코드를
옮기기 전에 실제 클러스터에서 확인해야 합니다. 이 실습은 PyMongo consumer를 AKS에
띄우고 프라이빗 엔드포인트로 클러스터에 연결해 다음 네 가지를 측정합니다.

- 어떤 옵션과 이벤트 필드가 실제로 동작하는가
- 파드를 죽였다 살려도 이벤트가 빠지지 않는가
- 중복이 생기는 지점은 어디이고 어떻게 흡수하는가
- 초당 1,000건 쓰기에서 지연은 얼마인가

상시 consumer 대신 Airflow DAG가 주기마다 change stream을 읽어 ADLS Gen2에
Parquet으로 쓰는 방식은 [Airflow DAG로 Parquet 적재](airflow-parquet/index.md)에서
측정했습니다.

## 목표

- 프라이빗 엔드포인트만 열린 DocumentDB 클러스터와 AKS를 Bicep으로 배포합니다.
- `probe.py`로 change stream 옵션별 동작을 확인합니다.
- 생성기가 만든 이벤트와 sink에 기록된 이벤트를 `verify.py`로 대조해 누락,
  중복, 순서 역전과 지연을 숫자로 남깁니다.

## 사전 조건

- Azure 구독에서 리소스 그룹을 만들 수 있는 권한
- Azure CLI, `kubectl`, `envsubst`
- 이 저장소의 [python-aks sample](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-documentdb/change-streams/samples/python-aks/README.md)

이 문서의 결과는 2026-10-02에 아래 환경에서 측정했습니다.

| 항목 | 값 |
| --- | --- |
| 리전 | East US 2 |
| DocumentDB | M30(2 vCore, 8 GiB), shard 1개, 스토리지 32 GiB, 고가용성 끔, 서버 버전 7.0.0 |
| 네트워크 | 공용 액세스 끔, 프라이빗 엔드포인트(`privatelink.mongocluster.cosmos.azure.com`, 포트 10260) |
| AKS | Kubernetes 1.35, Standard_D4s_v6 노드, Azure CNI overlay |
| 클라이언트 | Python 3.12, PyMongo 4.18.2 |

## 비용과 안전 경계

- 클러스터, AKS 노드, ACR과 프라이빗 엔드포인트는 실행하는 동안 과금됩니다.
  측정이 끝나면 바로 리소스 그룹을 삭제합니다.
- 관리자 비밀번호와 연결 문자열은 Kubernetes Secret에만 넣습니다. sample의
  `.env`는 `.gitignore` 대상이며 커밋하지 않습니다.
- 생성기는 지정한 데이터베이스(`cslab`)의 `orders` 컬렉션에 직접 씁니다.
  운영 클러스터를 대상으로 실행하지 않습니다.
- 이 문서에 나오는 리소스 이름과 레지스트리 주소는 가상 값입니다.

## 배포

sample 디렉터리에서 실행합니다.

```bash
RG=rg-docdb-changestream
az group create -n $RG -l eastus2
az deployment group create -g $RG -f infra/main.bicep \
  -p adminPassword="$ADMIN_PASSWORD"

ACR=docdbcsacrexample
az acr build -r $ACR -t cslab:v1 app/
az aks get-credentials -g $RG -n aks-docdbcs

kubectl create namespace cslab
kubectl -n cslab create secret generic docdb --from-literal=uri="$MONGO_URI"
```

`main.bicep`은 VNet, `Microsoft.DocumentDB/mongoClusters` 클러스터(M30, shard 1개),
프라이빗 엔드포인트와 사설 DNS 영역, ACR, AKS를 만듭니다. 프라이빗 엔드포인트의
group ID는 `MongoCluster`입니다. Learn은 프라이빗 엔드포인트로 연결할 때
`mongodb+srv` 형식의 연결 문자열을 쓰라고 안내합니다. AKS 파드에서는 클러스터
호스트 이름이 사설 DNS 영역을 거쳐 프라이빗 IP로 확인됩니다.

감시할 컬렉션은 consumer보다 먼저 만듭니다. 컬렉션이 없으면 `watch()`가
`NamespaceNotFound`(code 26)로 실패합니다.

```bash
export IMAGE=docdbcsacrexample.azurecr.io/cslab:v1
envsubst < k8s/toolbox.yaml | kubectl apply -f -
kubectl -n cslab exec cs-toolbox -- python -c \
  "from common import *; get_database(get_client('setup')).create_collection('orders')"
envsubst < k8s/consumer.yaml | kubectl apply -f -
```

## 시나리오 실행

모든 시나리오는 `k8s/job.yaml`에 `SCRIPT`와 매개변수를 넣어 Job으로 실행합니다.

| 실행 | 스크립트와 매개변수 | 목적 |
| --- | --- | --- |
| probe | `SCRIPT=probe.py` | 옵션, 이벤트 필드, 재개 방식과 오류 코드 확인 |
| r1 | `generator.py`, `DOCS=10000` | 기본 정합성과 지연 |
| r2 | `generator.py`, `DOCS=100000`, 실행 중 consumer 파드 반복 삭제 | 재시작 후 누락 여부 |
| r3 | `generator.py`, `DOCS=100000`, consumer에 `FAULT_EXIT_AFTER_WRITE=200` 설정 | sink 쓰기와 checkpoint 사이에서 프로세스가 죽을 때의 중복 |
| r4 | `generator.py`, `RATE=1000`, 5분 | 초당 1,000건에서의 지연 |

생성기는 문서마다 insert와 update를 한 번씩 실행합니다. 10번째 문서마다
replace, 5번째 문서마다 delete를 더합니다. 따라서 문서 10,000개는 이벤트
23,000건이 됩니다. 쓰기는 모두 `w=majority`입니다.

```bash
JOB_NAME=gen-r4 SCRIPT=generator.py RUN_ID=r4 DOCS=300000 WORKERS=16 RATE=1000 \
  envsubst < k8s/job.yaml | kubectl apply -f -
# 생성기가 끝나고 consumer가 따라잡은 뒤
JOB_NAME=verify-r4 SCRIPT=verify.py RUN_ID=r4 DOCS=0 WORKERS=0 RATE=0 \
  envsubst < k8s/job.yaml | kubectl apply -f -
kubectl -n cslab logs job/verify-r4
```

consumer는 다음 방식으로 동작합니다.

- `collection.watch(full_document="updateLookup", max_await_time_ms=1000)`로 열고
  `try_next()`로 읽습니다.
- 이벤트를 최대 200건씩 sink 컬렉션에 `bulk_write`한 뒤 resume token을
  `_cs_checkpoints`에 저장합니다. 대기 중에는 post-batch resume token을 저장합니다.
- sink는 resume token의 `_data`를 키로 upsert합니다. 같은 이벤트가 다시 오면
  행을 추가하지 않고 `deliveries`를 1 올립니다.
- 지연은 consumer가 이벤트를 받은 시각에서 생성기가 문서에 기록한
  `updated_at` 또는 `created_at`을 뺀 값입니다.

## 예상 결과

### 옵션과 이벤트 필드

Learn 문서에 나온 동작과 이번 클러스터에서 관찰한 동작을 구분했습니다.
관찰 결과는 M30, shard 1개, 서버 7.0.0 클러스터에서 2026-10-02에 확인한 값입니다.

| 항목 | Learn 문서 | 관찰 결과 |
| --- | --- | --- |
| 이벤트 필드 | insert, update, delete 예시에 `_id`, `operationType`, `fullDocument`, `ns`, `documentKey` | `_id`, `operationType`, `fullDocument`, `ns`, `documentKey`, `wallTime`. `clusterTime`은 없음 |
| replace | 예시 없음 | `operationType: update`로 오고 `fullDocument`에 교체 후 문서 전체가 있음 |
| update의 `fullDocument` | 변경 후 문서 전체를 보여 주는 예시 | 옵션 없이도 포함됨. `updateLookup`, `whenAvailable`, `required` 모두 오류 없이 열림 |
| `updateDescription` | 별도 옵션 예시로 제시. 파이프라인 안의 update에서는 지원하지 않음 | 파이프라인이 있든 없든 반환되지 않음 |
| pre-image | 미리 보기. 지원 요청으로 클러스터에서 켜야 함 | `collMod`는 성공. `whenAvailable`은 `null`, `required`는 code 10065 오류. 지원 요청은 하지 않음 |
| 파이프라인 단계 | `$addFields`, `$match`, `$project`, `$set`, `$unset` | 다섯 개 모두 동작. 목록에 없는 `$replaceRoot`, `$redact`도 오류 없이 동작 |
| 감시 범위 | 컬렉션 예시 | `db.watch()`는 code 26. `client.watch()`에 `ns.db` 조건을 건 `$match`는 동작 |
| 재개 | `resumeAfter`, `startAt`, `startAtOperationTime` 지원 | `resume_after`, `start_after` 동작. 세션의 `operationTime`이 비어 있어 이를 쓴 `start_at_operation_time`은 실패. 현재 시각에서 10분 뺀 `Timestamp`는 동작 |
| 잘못된 resume token | 언급 없음 | code 2(BadValue) |
| `showExpandedEvents` | 지원하지 않음 | code 115(CommandNotSupported) |
| 감시 중인 컬렉션 drop, rename | 언급 없음 | `invalidate` 이벤트 없이 code 26으로 커서 종료 |
| 트랜잭션 | 언급 없음 | 이벤트는 오지만 `txnNumber`, `lsid`는 없음 |
| 큰 문서 | 언급 없음 | 14 MiB 문서의 insert와 update 이벤트 모두 전달됨 |
| 대기 중 resume token | 언급 없음 | 이벤트가 없어도 post-batch resume token이 전진함 |

Learn은 이력 재개에 대해 다음을 설명합니다. 기본 change stream은 400 MB 크기의
활성 change log 안의 이벤트만 읽습니다. PITR 로그와 통합되면 최대 35일 또는 클러스터
초기화 시점 중 이른 쪽까지 재개 범위가 늘어납니다. 이번 실습은 이 범위를 시험하지
않았습니다.

### 정합성과 지연

모든 실행에서 `verify.py`가 보고한 누락, 예상 밖 이벤트, 문서별 순서 역전은
0건이었습니다.

| 실행 | 부하 | 이벤트 | 누락 | 재전달 | 지연 p50 / p99 |
| --- | --- | --- | --- | --- | --- |
| r1 | 문서 10,000개, 속도 제한 없음 | 23,000 | 0 | 0 | 57 / 177 ms |
| r2 | 문서 100,000개, consumer 파드 반복 삭제 | 230,000 | 0 | 0 | 측정 대상 아님 |
| r3 | 문서 100,000개, 200건 쓰기 직후 프로세스 종료를 5회 주입 | 230,000 | 0 | 1,000 | 측정 대상 아님 |
| r4 | 초당 1,000건, 5분 | 299,000 | 0 | 0 | 55 / 123 ms |

- r2에서 파드를 삭제하면 이전 파드가 종료되는 동안 ReplicaSet이 새 파드를
  띄웠습니다. `Recreate` 전략은 롤아웃에만 적용되므로 잠깐 두 consumer가 함께
  읽었지만 upsert 덕분에 sink에 중복 행은 생기지 않았습니다.
- r3의 재전달 1,000건은 5회 × 200건입니다. checkpoint보다 sink 쓰기가 먼저
  끝난 배치를 재시작 후 다시 받은 것입니다. change stream 소비는
  at-least-once이므로 sink가 멱등이어야 합니다.
- r3에서 밀린 이벤트를 따라잡는 속도는 초당 약 6,800건이었습니다.
- 클러스터 CPU는 초당 약 1,000건에서 약 30%, 속도 제한 없이 초당 약 2,900건을
  쓸 때 약 60%였습니다.

## 검증

- `verify.py` 출력의 `missing`, `unexpected`, `per_doc_out_of_order`가 모두 0인지 확인합니다.
- `redelivered_events`는 장애를 주입하지 않은 실행에서 0, r3에서는 주입 횟수 × 배치
  크기와 같아야 합니다.
- `kubectl -n cslab logs deploy/cs-consumer`에서 재시작 직후 `start` 로그의
  `resume` 값이 `true`인지 확인합니다. 저장된 token으로 이어 읽었다는 뜻입니다.

## 정리

```bash
az group delete -n $RG
```

삭제 전에 `kubectl config delete-context`로 로컬 kubeconfig의 AKS 항목도 지웁니다.

## 문제 해결

| 증상 | 원인과 조치 |
| --- | --- |
| `watch()`가 code 26으로 실패 | 컬렉션이 없거나 `db.watch()`를 호출했습니다. 컬렉션을 먼저 만들거나 `client.watch()`와 `$match`를 씁니다 |
| 컬렉션을 지운 뒤 consumer가 반복 실패 | drop과 rename은 `invalidate` 없이 code 26을 반환합니다. 컬렉션을 다시 만들고 새 stream을 엽니다 |
| `start_at_operation_time`에 넘길 값이 없음 | 세션의 `operationTime`이 비어 있습니다. 시각 기반 `Timestamp`를 만들거나 resume token을 저장합니다 |
| `full_document_before_change="required"`가 code 10065로 실패 | pre-image는 미리 보기이며 지원 요청으로 켜야 합니다 |
| 큰 백로그를 재개할 때 code 50 `ExceededTimeLimit`로 반복 실패 | 이 클러스터는 `maxAwaitTimeMS`를 `getMore` 실행 제한으로 적용합니다. 오래된 change log를 읽는 `getMore`는 몇 초 걸릴 수 있습니다. consumer는 `MAX_AWAIT_MS`를 늘리고 직접 작성한 코드는 `max_await_time_ms`를 지정하지 않습니다. [Airflow DAG로 Parquet 적재](airflow-parquet/index.md)에서 측정했습니다 |
| 노드 크기 오류로 AKS 배포 실패 | 구독에서 허용되지 않는 VM 크기입니다. `nodeVmSize` 매개변수를 바꿉니다 |

## 공식 참고 자료

- [Change streams in Azure DocumentDB](https://learn.microsoft.com/azure/documentdb/change-streams)
- [$changeStream](https://learn.microsoft.com/documentdb/query/operators/aggregation/$changestream)
- [Use Azure Private Link in Azure DocumentDB](https://learn.microsoft.com/azure/documentdb/how-to-private-link)
- [Compute and storage configurations](https://learn.microsoft.com/azure/documentdb/compute-storage)
- [Release notes for Azure DocumentDB](https://learn.microsoft.com/azure/documentdb/release-notes)
- [Microsoft.DocumentDB mongoClusters Bicep reference](https://learn.microsoft.com/azure/templates/microsoft.documentdb/2026-06-01/mongoclusters)
- [AzureCosmosDB/changestream-driver-compatibility](https://github.com/AzureCosmosDB/changestream-driver-compatibility)
