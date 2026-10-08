---
title: Azure DocumentDB change stream을 Airflow DAG로 Parquet에 내리기
description: AKS 위 Airflow DAG가 Azure DocumentDB(vCore) change stream을 주기적으로 읽어 ADLS Gen2에 Parquet으로 쓸 때 이벤트 누락과 중복이 없는지 확인했습니다. 공식 예제가 다루지 않는 부분과 운영 전에 더 확인할 항목도 정리했습니다.
document_type: research
services: [azure-documentdb, azure-storage, azure-kubernetes-service]
technologies: [python, mongodb, airflow, kubernetes]
tags: [evaluate, build, storage]
status: current
verification_status: verified
sources_checked_at: 2026-10-08
published_at: 2026-10-02
official_sources:
  - title: Change streams in Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/change-streams
  - title: Read and read/write privileges with secondary native users
    url: https://learn.microsoft.com/azure/documentdb/secondary-users
  - title: AzureCosmosDB/changestream-driver-compatibility
    url: https://github.com/AzureCosmosDB/changestream-driver-compatibility
  - title: MongoDB Change Streams Specification
    url: https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.md
  - title: Lease Blob
    url: https://learn.microsoft.com/rest/api/storageservices/lease-blob
  - title: Path - Update
    url: https://learn.microsoft.com/rest/api/storageservices/datalakestoragegen2/path/update
  - title: Best practices for using Azure Data Lake Storage
    url: https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-best-practices
---

# Azure DocumentDB change stream을 Airflow DAG로 Parquet에 내리기

Azure DocumentDB(이전 이름 Azure Cosmos DB for MongoDB vCore)의 change stream을
Airflow DAG가 주기적으로 읽어 Parquet 파일로 내리는 방식이 실제로 쓸 만한지
확인했습니다. 질문은 세 가지입니다.

- 이벤트를 빠뜨리거나 두 번 쓰지 않고 파일로 내릴 수 있는가
- 공식 예제를 그대로 옮기면 어디서 문제가 생기는가
- 운영에 올리기 전에 무엇을 더 확인해야 하는가

시험 환경은 이 질문에 답하려고 만든 것입니다. 배포와 실행 절차는 sample
[README](https://github.com/hellices/devguidesample/blob/main/docs/services/azure-documentdb/change-streams/samples/python-aks/README.md)에,
시나리오별 수치는 [측정 상세](measurements/index.md)에 있습니다.

## change stream 소개

change stream은 컬렉션의 변경을 이벤트로 받아 보는 MongoDB 기능입니다. 변경을
찾으려고 컬렉션을 반복해서 조회할 필요가 없습니다. Learn 문서에 나온 DocumentDB의
동작은 다음과 같습니다.

- 이벤트의 `_id`가 resume token입니다. 이 값을 저장했다가 `resumeAfter`로 넘기면
  그 다음 이벤트부터 이어 읽습니다.
- 기본 change stream은 400 MB 활성 change log 안의 이벤트만 읽습니다. PITR 로그와
  통합되면 최대 35일 또는 클러스터 초기화 시점 중 이른 쪽까지 재개할 수 있습니다.
- 파이프라인에는 `$addFields`, `$match`, `$project`, `$set`, `$unset`을 쓸 수
  있습니다. `showExpandedEvents`는 지원하지 않습니다.
- 변경 전 문서(pre-image)와 다중 shard 클러스터 지원은 미리 보기이며 지원
  요청으로 켭니다.

## 확인한 구성

![AKS의 Airflow scheduler가 10분 구간이 닫힐 때마다 내보내기 파드를 만들면 그 파드가 프라이빗 엔드포인트를 거쳐 DocumentDB change stream을 읽어 ADLS Gen2에 Parquet 청크와 checkpoint를 쓰며 Entra ID 워크로드 ID로 인증하는 구성](images/architecture.svg)

Airflow가 매시 2분, 12분, 22분처럼 10분 구간이 닫히고 2분 뒤에
`KubernetesPodOperator`로 내보내기 파드를 하나 띄웁니다. 파드는 다음 순서로
동작하고 끝나면 사라집니다.

1. ADLS Gen2의 lock 파일에 lease를 잡고 checkpoint 파일에서 resume token을
   읽습니다. checkpoint가 없으면 현재 시각을 시작 위치로 먼저 저장합니다.
2. 이벤트를 `wallTime` 기준 10분 구간(UTC)으로 나눠 실행 전에 닫힌 구간만
   읽습니다. 아직 열린 구간의 첫 이벤트를 만나면 쓰지 않고 멈춥니다.
3. 구간마다 Parquet 청크로 올립니다. 한 구간이 압축 전 80 MB(80,000,000바이트)를
   넘으면 그 앞에서 잘라 다음 파일로 넘깁니다. 청크 파일 이름은 구간 시작 시각과 청크 첫
   이벤트 바로 앞의 resume token으로 만듭니다.
4. 올릴 청크 파일 경로를 checkpoint에 먼저 기록합니다. 그 다음 청크 파일에
   lease를 잡고 checkpoint가 자기 기록 그대로인지 확인한 뒤 그 lease ID로
   올립니다. 마지막으로 checkpoint를 ETag 조건으로 갱신합니다.

DAG는 `max_active_runs=1`이고 실패하면 세 번까지 재시도합니다. 재시도는 같은
checkpoint에서 같은 이벤트를 읽어 같은 파일 이름으로 덮어씁니다. 첫 실행의
재시도도 저장해 둔 시작 시각부터 다시 읽습니다.

## 결과: 동작하는가

동작합니다. 모든 시나리오에서 생성기가 만든 이벤트가 Parquet 파일에 한 번씩
들어갔고 누락, 중복, 문서별 순서 역전은 0건이었습니다. 단 아래 표의 조건을
지켰을 때입니다.

| 확인 항목 | 결과 |
| --- | --- |
| 10분 구간 지연 | 초당 약 960건 쓰기에서 이벤트 기록부터 파일 저장까지 p50 454초, p99 722초, 최대 731초 |
| lock lease를 잃은 실행 | 멈춰 있던 실행이 다음 실행 뒤에 같은 파일을 쓰려 하면 업로드가 412로 거부되거나 checkpoint 확인에서 멈춤. 중복 0, 누락 0. 이전 sample은 45,000행 중복 |
| 업로드 직후 장애와 재시도 | 첫 청크를 올리고 checkpoint를 쓰기 전에 파드를 죽여도 재시도 후 중복 0, 누락 0. 50 MB와 80 MB 한도에서 각각 확인 |
| 구간과 크기로 자르기 | 50, 80, 100, 200 MB 한도로 쓴 파일이 모두 구간 하나의 이벤트만 담았고 한도를 넘은 파일은 없음 |
| 400 MB 활성 change log를 넘긴 재개 | DAG를 31분 멈춘 사이 쌓인 문서 본문 2.6 GB 이상의 백로그를 누락 없이 따라잡음. `maxAwaitTimeMS`를 지정하지 않았을 때만 성공. 이전 구성에서 측정 |
| secondary user의 과거 시점 시작 | `readWriteAnyDatabase + clusterAdmin`만 가진 사용자는 `startAtOperationTime`이 code 13. `readAnyDatabase`를 grant하면 같은 사용자가 성공했고 revoke하면 다시 실패 |
| 처리 속도 | 1 KB 문서 10분 구간 하나(약 600,000건)를 32–38초에 씀. 한도를 50–200 MB로 바꿔도 시간은 비슷함 |
| 파일 크기 | 압축 전 80 MB에서 자른 파일이 1 KB 랜덤 채움 문서는 43.7–46.7 MB, 채움 없는 작은 문서는 13.3–13.4 MB. 파일 크기는 한도에 비례함 |
| 내보내기 파드 메모리 | 80 MB 한도에서 최대 RSS 336 MiB. 200 MB 한도는 620 MiB. 측정 파드는 요청 512Mi, 제한 4Gi. Airflow DAG의 파드는 요청 512Mi, 제한 1Gi |

지켜야 할 조건은 다음과 같습니다.

- historical change stream을 열 때 짧은 `maxAwaitTimeMS`를 주지 않습니다. 이
  값은 stream 전체 제한이 아니라 후속 `getMore`의 `maxTimeMS`가 됩니다. 1초로
  두면 큰 백로그를 재개할 때 code 50으로 실패하고 재시도로도 넘어가지 못했습니다.
- secondary user로 `startAtOperationTime`을 쓸 때는 `readAnyDatabase` 역할을
  확인합니다. `readWriteAnyDatabase + clusterAdmin`만 있으면 일반 `watch()`와
  `resumeAfter`는 동작해도 과거 시점 시작은 code 13으로 실패했습니다.
- 파일을 먼저 쓰고 checkpoint를 나중에 씁니다. 순서가 반대면 그 사이 장애로
  이벤트를 잃습니다.
- 파일 이름을 청크 첫 이벤트 바로 앞의 resume token으로 정해 재시도가 같은 파일을
  덮어쓰게 합니다. checkpoint보다 앞서 올라간 파일은 마지막 청크 하나뿐이라 재시도가
  다른 위치에서 잘라도 그 파일을 덮어씁니다. 실행 시각처럼 재시도마다 바뀌는 값을
  파일 이름에 넣으면 다른 파일이 생겨 중복이 됩니다.
- checkpoint가 없는 첫 실행은 시작 위치를 먼저 저장합니다. 저장하지 않으면 첫
  청크를 쓰다 실패했을 때 재시도가 더 뒤에서 시작해 그 사이 이벤트를 잃습니다.
- 실행이 겹치지 않게 `max_active_runs=1`을 두고 실행 동안 lock 파일 lease를
  잡습니다. checkpoint ETag 조건은 checkpoint만 보호합니다. lock lease를 잃은 실행이
  늦게 업로드하면 다음 실행이 쓴 더 짧은 청크를 덮어씁니다. 그래서 올릴 파일
  경로를 checkpoint에 먼저 기록하고 청크 파일에도 lease를 잡아 그 lease ID로
  올립니다. 같은 파일을 쓰는 다음 실행은 자기 기록을 남긴 뒤 lease를 끊습니다.
  이전 실행은 기록 확인에서 멈추거나 업로드가 412로 거부됩니다.
- 감시할 컬렉션을 먼저 만듭니다. 없으면 `watch()`가 code 26으로 실패합니다.

## secondary user로 과거 시점부터 읽기

Learn의 secondary native user 문서는 읽기 전용 사용자에 `readAnyDatabase`,
읽기·쓰기 사용자에 `readWriteAnyDatabase + clusterAdmin`을 지정합니다. 2026-10-08
M25, shard 1개, 서버 8.0 클러스터에서는 후자의 사용자가 일반 `watch()`와
`resumeAfter`는 열었지만 `startAtOperationTime`만 code 13(`Unauthorized`)으로
실패했습니다. 같은 timestamp와 이벤트를 사용한 raw aggregate와 PyMongo 시험에서
built-in 관리자와 `readAnyDatabase` 사용자는 성공했습니다.

기존 읽기·쓰기 사용자에는 built-in 관리자로 역할을 grant할 수 있었습니다.

```javascript
use admin

db.runCommand({
  grantRolesToUser: "cdc_user",
  roles: [
    { role: "readAnyDatabase", db: "admin" }
  ]
})
```

세 역할을 `createUser`에 한꺼번에 주면 code 31, `updateUser`로 역할을 바꾸면 code 2로
실패했습니다. 반면 위 grant는 성공했고 `usersInfo`에 세 역할이 저장됐습니다.
`connectionStatus`에는 추가 역할이 보이지 않았으므로 적용 여부는 아래 명령으로
확인합니다. 기존 client pool도 닫고 새 연결에서 다시 시험합니다.

```javascript
db.runCommand({ usersInfo: "cdc_user" })
```

DocumentDB에서 읽기만 하고 checkpoint와 결과를 외부 저장소에 쓰는 CDC라면
`readAnyDatabase` 전용 사용자가 더 단순합니다. 같은 계정이 DocumentDB 안에
checkpoint나 sink도 써야 하면 읽기·쓰기 역할을 유지하고 `readAnyDatabase`를
grant합니다. rollback은 `revokeRolesFromUser`에 같은 역할을 넘깁니다. 이 역할별
차이는 Learn에 설명되지 않은 관찰 결과이므로 서버 업데이트 뒤 다시 확인합니다.

## 공식 예제가 놓친 부분

Learn 문서의 시작 예제(Python, Java, C#, Ruby, Node.js)와
[changestream-driver-compatibility](https://github.com/AzureCosmosDB/changestream-driver-compatibility)
저장소의 sample은 계속 떠 있는 consumer가 이벤트를 출력하는 예제입니다. 기능
확인에는 충분하지만 주기 실행하는 DAG로 옮기면 다음 부분이 문제가 됩니다.

| 공식 예제 | 옮겼을 때의 문제 | 이번 구현 |
| --- | --- | --- |
| 저장소의 `mongo_utils.py`가 resume token을 이벤트마다 로컬 파일 `.resume_token.json`에 씀 | 실행마다 새 파드가 뜨면 파일이 없어 현재 위치부터 읽음. 그 사이 이벤트를 잃음 | checkpoint를 ADLS Gen2 파일로 두고 청크마다 ETag 조건으로 갱신 |
| Python 예제가 대상 컬렉션에 `insert_one`을 한 뒤 token을 저장 | 두 동작 사이에서 프로세스가 죽으면 재시작 후 같은 이벤트가 한 번 더 들어감 | resume token으로 파일 이름을 정해 덮어씀. 상시 consumer는 token을 키로 upsert |
| `for change in stream`처럼 끝없이 읽음 | 배치 실행이 끝나지 않음 | `try_next()`로 읽고 아직 열린 10분 구간의 이벤트를 만나면 쓰지 않고 종료 |
| Microsoft의 driver compatibility verifier가 대기 시간을 1초로 지정 | verifier는 cursor가 열리는지만 확인하고 바로 닫음. 이 값을 historical consumer에 옮기면 오래 걸리는 `getMore`가 code 50(`ExceededTimeLimit`)으로 끝남 | historical read에는 `max_await_time_ms`를 지정하지 않음 |
| 오류가 나면 메시지를 출력하고 끝남 | Learn 제한 사항은 장애 조치 뒤 커서를 다시 열어야 한다고 설명함 | Airflow 재시도가 새 파드에서 checkpoint로 stream을 다시 엶 |
| 감시할 컬렉션이 있다고 가정 | 컬렉션이 없으면 `watch()`가 code 26 | 컬렉션을 먼저 만듦 |

Learn 문서와 다르게 동작했거나 문서에 설명이 없는 부분도 있었습니다. 2026-10-02
기준 M30, shard 1개, 서버 7.0.0 클러스터에서 관찰한 결과입니다.

| 항목 | Learn 문서 | 관찰 결과 |
| --- | --- | --- |
| `maxAwaitTimeMS` | Learn의 historical 예제에는 없음. 별도 compatibility verifier는 1초 | MongoDB spec대로 `getMore.maxTimeMS`가 됨. DocumentDB가 history를 스캔 중이면 빈 batch 대신 code 50을 반환할 수 있음 |
| 이벤트 필드 | `_id`, `operationType`, `fullDocument`, `ns`, `documentKey` | 같은 필드에 `wallTime`이 더 있고 `clusterTime`은 없음 |
| replace | 예시 없음 | `operationType: update`로 오고 교체 후 문서 전체가 실림 |
| update의 `fullDocument` | 변경 후 문서 전체를 보여 주는 예시 | `updateLookup` 없이도 포함됨 |
| `updateDescription` | 이벤트 예시가 있음 | 파이프라인이 있든 없든 반환되지 않음 |
| 감시 범위 | 컬렉션 예시만 있음 | `db.watch()`는 code 26. `client.watch()`에 `$match`로 `ns.db`를 거르면 동작 |
| 컬렉션 drop, rename | 설명 없음 | `invalidate` 이벤트 없이 code 26으로 커서 종료 |
| `startAtOperationTime` | 날짜로 `Timestamp`를 만드는 예시 | 날짜로 만든 값은 동작함. 세션의 `operationTime`은 비어 있어 쓸 수 없음 |
| secondary user 역할 | 읽기 전용과 읽기·쓰기 역할을 설명하지만 change stream 옵션별 차이는 없음 | `readAnyDatabase`는 과거 시점 시작 성공. `readWriteAnyDatabase + clusterAdmin`은 code 13이고 `readAnyDatabase` grant 뒤 성공 |
| pre-image | 미리 보기. 지원 요청으로 켬 | 지원 요청 없이 `required`로 열면 code 10065 |

옵션별 관찰 전체는 [측정 상세](measurements/index.md)에 있습니다.

## 운영 전에 더 확인할 것

이번 시험에서 다루지 않았거나 숫자로 확인하지 못한 항목입니다.

- **장애 조치:** 시험 클러스터는 고가용성을 껐습니다. 고가용성을 켠 클러스터에서
  실행 중 장애 조치가 나면 태스크가 실패하고 재시도가 이어 읽는지 확인합니다.
- **다중 shard:** 미리 보기 기능입니다. Learn은 전역 순서를 보장하지 않고 단일
  shard에서 다중 shard로 바꾸면 재개할 수 없다고 설명합니다. 파일 안 이벤트 순서에
  기대는 다운스트림 처리를 다시 봐야 합니다.
- **재개 범위를 넘긴 정지:** DAG가 35일 또는 클러스터 초기화 시점보다 오래 멈추면
  저장한 token으로 재개할 수 없습니다. 그때 나는 오류와 전체 재적재 절차를
  정합니다. 마지막 checkpoint 갱신 시각을 모니터링합니다.
- **400 MB 경계:** change log 크기는 조회할 수 없어 문서 본문 크기로 추정했습니다.
  백로그 재개가 PITR 로그를 거쳤는지는 구분하지 못했습니다.
- **서버 업데이트:** `maxAwaitTimeMS`, `updateDescription`처럼 문서와 다르게 동작한
  항목은 서버 버전이 바뀌면 다시 확인합니다.
- **부하와 주기:** 실행 한 번이 구간 길이(10분) 안에 끝나야 지연이 쌓이지
  않습니다. 초당 약 960건에서는 40초 안팎이었습니다. 더 높은 쓰기 속도와 다른
  클러스터 tier에서 실행 시간을 다시 잽니다. 구간이 닫힌 뒤에야 쓰므로 지연은 최대
  구간 길이에 대기 시간(2분)과 실행 시간을 더한 값입니다.
- **파일 크기 규칙:** ADLS 모범 사례는 분석용 파일 크기로 256 MB–100 GB를 권하고
  작은 파일이 많으면 읽기 성능과 트랜잭션 비용이 나빠진다고 설명합니다. sample의
  한도는 압축 전 80 MB이고 시험에서 파일은 47 MB 이하였습니다. 압축이 거의 되지 않는
  문서라면 파일이 80 MB에 가까워집니다. 파일을 50 MB 아래로 지켜야 하면 한도를
  50,000,000으로 둡니다. 한도를 올리면 메모리도 늘어 200 MB에서 620 MiB였습니다.
  쓰기가 적은 구간도 파일이 작아지므로 다운스트림에서 큰 파일로 합치는 작업을
  둡니다.
- **파일 크기와 압축:** 시험 데이터는 압축되지 않는 랜덤 문자열이었습니다. 실제
  문서로 snappy와 zstd의 크기, 시간, CPU를 비교합니다.
- **다운스트림 처리:** 파일은 이벤트 이력입니다. 문서별 최신 상태 병합, 문서가
  없는 delete 이벤트 처리, JSON 문자열 열 펼치기를 설계합니다.
- **운영 Airflow:** 차트에 포함된 PostgreSQL 대신 외부 데이터베이스를 쓰고 실패한
  실행에 알림을 겁니다.
- **변경 전 문서가 필요할 때:** pre-image는 지원 요청으로 켠 뒤 저장 공간과 지연
  영향을 측정합니다.

## 시험 범위와 한계

| 항목 | 값 |
| --- | --- |
| 측정일 | 2026-10-02–03(UTC), East US 2 |
| DocumentDB | M30(2 vCore, 8 GiB), shard 1개, 스토리지 32 GiB, 고가용성 끔, 서버 7.0.0, 공용 액세스 끔 |
| AKS | Kubernetes 1.35, Standard_D4s_v6 노드 4개 |
| Airflow | Helm chart 1.22.0, Airflow 3.2.2, `LocalExecutor` |
| 내보내기 파드 | Python 3.12, PyMongo 4.18.2, pyarrow 25.0.1, snappy 압축 |

컬렉션 하나를 하루 동안 측정한 결과입니다. 처음에는 5분 주기와 100,000건 청크로
측정했습니다. 백로그 재개와 consumer 기준선은 그 구성의 결과입니다. 이후 리뷰에서
나온 실패 경로를 sample에 반영했고 반영한 sample을 새 환경에 다시 배포해 아래 경로를
확인했습니다.

- **첫 실행 시작 위치 저장:** checkpoint 없이 시작한 첫 실행이 현재 시각을 저장하고
  0건으로 끝났습니다. 다음 실행은 그 위치에서 이어 읽었습니다.
- **lock 파일 lease:** 다른 파드가 lease를 잡고 있는 동안 띄운 내보내기는 약 90초
  기다린 뒤 change stream을 열지 않고 실패했습니다.
- **다시 실행한 적재:** 문서 100,000개 적재와 업로드 직후 장애 재시도를 다시
  실행했습니다. 두 경우 모두 이벤트 230,000건이 중복과 누락 없이 들어갔습니다.
- **10분 구간과 50 MB 규칙:** 같은 날 규칙을 바꾼 sample을 다시 새 환경에 배포해
  지연, 재시도, 열린 구간 보류를 측정했습니다. 표의 지연과 처리 속도 값이 이
  측정입니다.
- **한도 비교와 80 MB:** 다음 날 같은 환경에서 내보내기가 행을 Arrow 배치로 옮기게
  바꾸고 한도를 50, 80, 100, 200 MB로 바꿔 파일 크기와 메모리를 쟀습니다. 기본값을
  80 MB로 올린 뒤 Airflow 실행과 업로드 직후 장애 재시도를 다시 확인했습니다. 표의
  자르기, 파일 크기, 메모리, 재시도 값이 이 측정입니다.
- **lock lease를 잃은 실행:** 실행 하나를 첫 업로드 전에 멈추고 lock lease를 잃게 한
  뒤 다음 실행이 같은 파일을 쓰게 했습니다. 이전 sample은 늦은 업로드가 다음 실행의
  청크를 덮어써 후속 실행 뒤 45,000행이 중복됐습니다. 현재 sample은 업로드 직전과 lease
  직전 두 위치에서 모두 늦은 실행이 실패했고 중복과 누락은 0이었습니다.
- **로컬 fake로만 확인한 경로:** `wallTime`이 없는 이벤트의 파티션 고정, 검증
  스크립트의 순서 역전 실패 처리, 재시도가 첫 시도와 다른 위치에서 자르는 경우입니다.
  이 클러스터의 이벤트에는 항상 `wallTime`이 있었고 순서 역전도 생기지 않았습니다.
  Azure에서 재시도는 첫 시도와 같은 한도로 실행해 같은 위치에서 잘랐습니다. 다음
  실행이 업로드를 마치고 checkpoint를 갱신하기 전에 이전 실행이 파일 lease를 끊는
  순서도 fake로만 재현했습니다.

## 공식 출처

- [Change streams in Azure DocumentDB](https://learn.microsoft.com/azure/documentdb/change-streams)
- [AzureCosmosDB/changestream-driver-compatibility](https://github.com/AzureCosmosDB/changestream-driver-compatibility)
- [MongoDB Change Streams Specification](https://github.com/mongodb/specifications/blob/master/source/change-streams/change-streams.md)
- [Lease Blob](https://learn.microsoft.com/rest/api/storageservices/lease-blob)
- [Path - Update](https://learn.microsoft.com/rest/api/storageservices/datalakestoragegen2/path/update)
- [Best practices for using Azure Data Lake Storage](https://learn.microsoft.com/azure/storage/blobs/data-lake-storage-best-practices)

## 더 읽을 문서

이번 sample에 그대로 채택하지 않았지만 구성을 바꿀 때 참고할 문서입니다.

- AKS에 Airflow 배포: [개요](https://learn.microsoft.com/azure/aks/airflow-overview),
  [인프라 만들기](https://learn.microsoft.com/azure/aks/airflow-create-infrastructure),
  [배포](https://learn.microsoft.com/azure/aks/airflow-deploy).
  Key Vault 비밀 연동과 운영 체크리스트가 있습니다.
- [Fabric open mirroring best practices](https://learn.microsoft.com/fabric/mirroring/open-mirroring-best-practices):
  임시 이름으로 올린 뒤 이름을 바꾸는 방식으로 파일을 원자적으로 게시합니다.
- pandas `to_parquet`로 ADLS에 쓰기:
  [Synapse](https://learn.microsoft.com/azure/synapse-analytics/spark/tutorial-use-pandas-spark-pool),
  [Fabric](https://learn.microsoft.com/fabric/data-science/read-write-pandas)
- [`pyarrow.fs.AzureFileSystem`](https://arrow.apache.org/docs/python/generated/pyarrow.fs.AzureFileSystem.html)
- [PyMongo `ChangeStream.try_next`](https://pymongo.readthedocs.io/en/stable/api/pymongo/change_stream.html#pymongo.change_stream.ChangeStream.try_next)
