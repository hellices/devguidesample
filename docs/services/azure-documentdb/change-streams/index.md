---
title: Azure DocumentDB change stream을 Airflow DAG로 Parquet에 내리기
description: AKS 위 Airflow DAG가 Azure DocumentDB(vCore) change stream을 주기적으로 읽어 ADLS Gen2에 Parquet으로 쓸 때 이벤트 누락과 중복이 없는지 확인했습니다. 공식 예제가 다루지 않는 부분과 운영 전에 더 확인할 항목도 정리했습니다.
document_type: research
services: [azure-documentdb, azure-storage, azure-kubernetes-service]
technologies: [python, mongodb, airflow, kubernetes]
tags: [evaluate, build, storage]
status: current
verification_status: verified
sources_checked_at: 2026-10-02
published_at: 2026-10-02
official_sources:
  - title: Change streams in Azure DocumentDB
    url: https://learn.microsoft.com/azure/documentdb/change-streams
  - title: AzureCosmosDB/changestream-driver-compatibility
    url: https://github.com/AzureCosmosDB/changestream-driver-compatibility
  - title: Lease Blob
    url: https://learn.microsoft.com/rest/api/storageservices/lease-blob
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

![AKS의 Airflow scheduler가 5분마다 내보내기 파드를 만들면 그 파드가 프라이빗 엔드포인트를 거쳐 DocumentDB change stream을 읽어 ADLS Gen2에 Parquet 청크와 checkpoint를 쓰며 Entra ID 워크로드 ID로 인증하는 구성](images/architecture.svg)

Airflow가 5분마다 `KubernetesPodOperator`로 내보내기 파드를 하나 띄웁니다. 파드는
다음 순서로 동작하고 끝나면 사라집니다.

1. ADLS Gen2의 lock 파일에 lease를 잡고 checkpoint 파일에서 resume token을
   읽습니다. checkpoint가 없으면 현재 시각을 시작 위치로 먼저 저장합니다.
2. 실행을 시작한 시각까지 기록된 이벤트를 읽어 100,000건씩 Parquet 청크로
   올립니다. 청크 파일 이름은 청크 첫 이벤트 바로 앞의 resume token으로 만듭니다.
3. 청크를 올린 뒤 checkpoint를 ETag 조건으로 갱신합니다.

DAG는 `max_active_runs=1`이고 실패하면 세 번까지 재시도합니다. 재시도는 같은
checkpoint에서 같은 이벤트를 읽어 같은 파일 이름으로 덮어씁니다. 첫 실행의
재시도도 저장해 둔 시작 시각부터 다시 읽습니다.

## 결과: 동작하는가

동작합니다. 모든 시나리오에서 생성기가 만든 이벤트가 Parquet 파일에 한 번씩
들어갔고 누락, 중복, 문서별 순서 역전은 0건이었습니다. 단 아래 표의 조건을
지켰을 때입니다.

| 확인 항목 | 결과 |
| --- | --- |
| 5분 주기 지연 | 초당 약 1,000건 쓰기에서 이벤트 기록부터 파일 저장까지 p50 156초, p99 302초 |
| 업로드 직후 장애와 재시도 | 첫 청크를 올리고 checkpoint를 쓰기 전에 파드를 죽여도 재시도 후 중복 0, 누락 0 |
| 400 MB 활성 change log를 넘긴 재개 | DAG를 31분 멈춘 사이 쌓인 문서 본문 2.6 GB 이상의 백로그를 누락 없이 따라잡음. `maxAwaitTimeMS`를 지정하지 않았을 때만 성공 |
| 처리 속도 | 1 KB 문서는 초당 약 13,000–18,000건, 4 KB 문서 백로그는 초당 약 3,600건 |
| 파일 크기 | 이벤트에 실린 문서 크기와 비슷함. update 이벤트에도 문서 전체가 실려 문서 하나가 여러 번 저장됨 |

지켜야 할 조건은 다음과 같습니다.

- change stream을 열 때 짧은 `maxAwaitTimeMS`를 주지 않습니다. 1초로 두면 큰
  백로그를 재개할 때 code 50으로 실패하고 재시도로도 넘어가지 못했습니다.
- 파일을 먼저 쓰고 checkpoint를 나중에 씁니다. 순서가 반대면 그 사이 장애로
  이벤트를 잃습니다.
- 파일 이름을 resume token으로 정해 재시도가 같은 파일을 덮어쓰게 합니다.
- checkpoint가 없는 첫 실행은 시작 위치를 먼저 저장합니다. 저장하지 않으면 첫
  청크를 쓰다 실패했을 때 재시도가 더 뒤에서 시작해 그 사이 이벤트를 잃습니다.
- 실행이 겹치지 않게 `max_active_runs=1`을 두고 실행 동안 lock 파일 lease를
  잡습니다. checkpoint ETag 조건은 checkpoint만 보호합니다. 이미 올린 파일을 다른
  실행이 짧은 청크로 덮어쓰는 것은 막지 못합니다.
- 감시할 컬렉션을 먼저 만듭니다. 없으면 `watch()`가 code 26으로 실패합니다.

## 공식 예제가 놓친 부분

Learn 문서의 시작 예제(Python, Java, C#, Ruby, Node.js)와
[changestream-driver-compatibility](https://github.com/AzureCosmosDB/changestream-driver-compatibility)
저장소의 sample은 계속 떠 있는 consumer가 이벤트를 출력하는 예제입니다. 기능
확인에는 충분하지만 주기 실행하는 DAG로 옮기면 다음 부분이 문제가 됩니다.

| 공식 예제 | 옮겼을 때의 문제 | 이번 구현 |
| --- | --- | --- |
| 저장소의 `mongo_utils.py`가 resume token을 이벤트마다 로컬 파일 `.resume_token.json`에 씀 | 실행마다 새 파드가 뜨면 파일이 없어 현재 위치부터 읽음. 그 사이 이벤트를 잃음 | checkpoint를 ADLS Gen2 파일로 두고 청크마다 ETag 조건으로 갱신 |
| Python 예제가 대상 컬렉션에 `insert_one`을 한 뒤 token을 저장 | 두 동작 사이에서 프로세스가 죽으면 재시작 후 같은 이벤트가 한 번 더 들어감 | resume token으로 파일 이름을 정해 덮어씀. 상시 consumer는 token을 키로 upsert |
| `for change in stream`처럼 끝없이 읽음 | 배치 실행이 끝나지 않음 | `try_next()`로 읽고 실행 시작 시각 이후 이벤트를 만나면 종료 |
| C# 예제와 저장소의 지원 확인 스크립트가 대기 시간을 1초로 지정 | 큰 백로그 재개에서 code 50(`ExceededTimeLimit`)이 같은 위치에서 반복 | `max_await_time_ms`를 지정하지 않음 |
| 오류가 나면 메시지를 출력하고 끝남 | Learn 제한 사항은 장애 조치 뒤 커서를 다시 열어야 한다고 설명함 | Airflow 재시도가 새 파드에서 checkpoint로 stream을 다시 엶 |
| 감시할 컬렉션이 있다고 가정 | 컬렉션이 없으면 `watch()`가 code 26 | 컬렉션을 먼저 만듦 |

Learn 문서와 다르게 동작했거나 문서에 설명이 없는 부분도 있었습니다. 2026-10-02
기준 M30, shard 1개, 서버 7.0.0 클러스터에서 관찰한 결과입니다.

| 항목 | Learn 문서 | 관찰 결과 |
| --- | --- | --- |
| `maxAwaitTimeMS` | 설명 없음. C# 예제는 1초 | 새 이벤트 대기 시간이 아니라 `getMore` 전체의 실행 제한으로 적용됨 |
| 이벤트 필드 | `_id`, `operationType`, `fullDocument`, `ns`, `documentKey` | 같은 필드에 `wallTime`이 더 있고 `clusterTime`은 없음 |
| replace | 예시 없음 | `operationType: update`로 오고 교체 후 문서 전체가 실림 |
| update의 `fullDocument` | 변경 후 문서 전체를 보여 주는 예시 | `updateLookup` 없이도 포함됨 |
| `updateDescription` | 이벤트 예시가 있음 | 파이프라인이 있든 없든 반환되지 않음 |
| 감시 범위 | 컬렉션 예시만 있음 | `db.watch()`는 code 26. `client.watch()`에 `$match`로 `ns.db`를 거르면 동작 |
| 컬렉션 drop, rename | 설명 없음 | `invalidate` 이벤트 없이 code 26으로 커서 종료 |
| `startAtOperationTime` | 날짜로 `Timestamp`를 만드는 예시 | 날짜로 만든 값은 동작함. 세션의 `operationTime`은 비어 있어 쓸 수 없음 |
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
- **부하와 주기:** 실행 한 번이 주기(5분) 안에 끝나야 지연이 쌓이지 않습니다. 더
  높은 쓰기 속도와 다른 클러스터 tier에서 실행 시간을 다시 잽니다.
- **파일 크기와 압축:** 시험 데이터는 압축되지 않는 랜덤 문자열이었습니다. 실제
  문서로 snappy와 zstd의 크기, 시간, CPU를 비교합니다.
- **다운스트림 처리:** 파일은 이벤트 이력입니다. 문서별 최신 상태 병합, 문서가
  없는 delete 이벤트 처리, JSON 문자열 열 펼치기, 작은 파일 정리를 설계합니다.
- **운영 Airflow:** 차트에 포함된 PostgreSQL 대신 외부 데이터베이스를 쓰고 실패한
  실행에 알림을 겁니다.
- **변경 전 문서가 필요할 때:** pre-image는 지원 요청으로 켠 뒤 저장 공간과 지연
  영향을 측정합니다.

## 시험 범위와 한계

| 항목 | 값 |
| --- | --- |
| 측정일 | 2026-10-02, East US 2 |
| DocumentDB | M30(2 vCore, 8 GiB), shard 1개, 스토리지 32 GiB, 고가용성 끔, 서버 7.0.0, 공용 액세스 끔 |
| AKS | Kubernetes 1.35, Standard_D4s_v6 노드 4개 |
| Airflow | Helm chart 1.22.0, Airflow 3.2.2, `LocalExecutor` |
| 내보내기 파드 | Python 3.12, PyMongo 4.18.2, pyarrow 25.0.1, snappy 압축 |

컬렉션 하나를 하루 동안 측정한 결과입니다. 측정 뒤 리뷰에서 나온 실패 경로를
sample에 반영했습니다. 같은 날 반영한 sample을 새 환경에 다시 배포해 아래 경로를
확인했습니다.

- **첫 실행 시작 위치 저장:** checkpoint 없이 시작한 첫 실행이 현재 시각을 저장하고
  0건으로 끝났습니다. 다음 실행은 그 위치에서 이어 읽었습니다.
- **lock 파일 lease:** 다른 파드가 lease를 잡고 있는 동안 띄운 내보내기는 약 90초
  기다린 뒤 change stream을 열지 않고 실패했습니다.
- **다시 실행한 적재:** 문서 100,000개 적재와 업로드 직후 장애 재시도를 다시
  실행했습니다. 두 경우 모두 이벤트 230,000건이 중복과 누락 없이 들어갔습니다.
- **로컬 fake로만 확인한 경로:** `wallTime`이 없는 이벤트의 파티션 고정과 검증
  스크립트의 순서 역전 실패 처리입니다. 이 클러스터의 이벤트에는 항상 `wallTime`이
  있었고 순서 역전도 생기지 않았습니다.

## 공식 출처

- [Change streams in Azure DocumentDB](https://learn.microsoft.com/azure/documentdb/change-streams)
- [AzureCosmosDB/changestream-driver-compatibility](https://github.com/AzureCosmosDB/changestream-driver-compatibility)
- [Lease Blob](https://learn.microsoft.com/rest/api/storageservices/lease-blob)
