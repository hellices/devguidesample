# Azure AI Search 버전 기반 재색인의 Eventual Consistency 이슈

## 개요

"새 버전 업로드 → 이전 버전 검색 후 삭제" 방식으로 Azure AI Search 인덱스를 주기적으로 갱신하는 파이프라인에서 **문서 개수 불일치** 또는 **일부 문서 누락**이 간헐적으로 발생하는 사례와 해결 방안을 정리한 문서입니다.

이 현상은 버그가 아니라 Lucene 기반 분산 검색 서비스인 Azure AI Search의 쓰기 전파 및 쿼리 평가 방식에서 비롯되는 **예상 가능한 동작**입니다.

---

## 문제 상황

각 `system_name`(또는 테넌트 / 파티션 키) 단위로 다음 4단계를 주기적으로 실행하는 적재 파이프라인을 가정합니다.

```
Step 1. 현재 version 에 해당하는 문서 정리        (재실행 대비 cleanup)
Step 2. version = CURRENT 로 N건 신규 업로드
Step 3. version < CURRENT 인 문서 search → delete
Step 4. 검증: count(system_name = X) == N
```

다음과 같은 증상이 간헐적으로 발생합니다.

- **Step 3 검색**이 실제 존재하는 이전 버전 문서보다 적게 반환되어 **구 버전 문서가 살아남음**
- **Step 4 카운트**가 업로드한 수와 불일치 (적게 나오거나 훨씬 많이 나오기도 함)
- **동일 인덱스 / 동일 쿼리**를 반복해도 replica 수가 2 이상이면 실행마다 숫자가 다르게 나옴

---

## 원인 분석

### 1. 쓰기는 "전파 완료"가 아닌 "접수 완료" 시점에 응답

인덱싱(upload / merge / delete)은 클라이언트 관점에서 **비동기**이며, `201/200` 응답은 프라이머리가 수락했다는 의미일 뿐 모든 replica가 새 세그먼트로 병합해 검색 가능해졌다는 뜻이 **아닙니다**. Microsoft는 이를 **Near-Real-Time (NRT)** 으로 부르며, 문서 단위 **read-your-writes 보장은 replica 전체에 걸쳐서는 존재하지 않습니다**.

### 2. 명시적 정렬 없는 pagination은 강한 일관성을 보장하지 않음

공식 문서 요지:

> `$skip` 또는 continuation token을 사용하는 검색은 **페이지 요청 사이 인덱스가 변경되지 않는다**고 가정한다. 인덱스가 바뀌면 결과에 **중복이나 누락**이 발생할 수 있다. 결정적 pagination이 필요하면 정렬 가능한 필드(보통 key)를 선택하고 이후 요청에서 `id gt '…'` 와 같이 **range filter**를 사용하라.

즉 정렬을 지정하지 않은 `search(filter=...)` 는 동일 쿼리의 동시 호출과 **다른 문서 집합**을 반환해도 규격에 어긋나지 않습니다. Step 3에서 pagination으로 순회하는 동안 한쪽 replica에서 세그먼트 병합이 일어나면 **문서가 건너뛰거나 두 번 카운트**될 수 있습니다.

### 3. `get_count()` 는 근사값

> `@odata.count` 는 필터에 일치하는 **근사(approximate)** 문서 수를 반환한다. 마지막 1건까지 정확하도록 설계되어 있지 않다.

재현 실험에서도 쓰기가 집중되는 동안 count와 실제 순회 결과가 **수만 건 단위로 차이**가 나다가 쓰기가 잠잠해지면 수렴하는 양상을 반복적으로 확인했습니다.

### 4. Multi-replica 간 상태 차이

여러 replica가 쿼리를 처리할 때 각 replica는 자신의 세그먼트로부터 term 통계(IDF 등)를 계산합니다. 대량 삭제 직후에는 replica 간 상태가 달라 **같은 필터라도 반환되는 문서가 달라질 수 있습니다**.

### 5. 삭제는 즉시 물리 제거되지 않음 (tombstone)

Lucene은 삭제된 문서를 비트맵으로 표시만 해두고 이후 세그먼트 병합 시점에 실제로 제거합니다. 그 사이에는

- 일부 replica 디스크에 **문서가 여전히 존재**하고
- count와 filter가 **삭제 이전 상태로 잠시 보일 수 있습니다**.

Microsoft 재색인 가이드는 프로덕션 파이프라인에서는 `upload`(중복 키 거부) 대신 **`mergeOrUpload`(idempotent)** 사용을 명시적으로 권장합니다.

---

## 해결 방법

요구되는 정확성 수준과 수용 가능한 변경 범위에 따라 선택합니다.

### 옵션 A — 최소 변경 (자가 보정)

"제자리 갱신" 파이프라인을 유지하되 각 단계를 **자가 보정(self-correcting)** 하도록 보강합니다.

1. **`upload` 대신 `merge_or_upload` 사용** — idempotent, 재시도 안전, Microsoft 권장 방식
2. **Step 3 pagination을 결정적으로** — key 필드로 정렬하고, 대량 결과셋은 `$skip` 대신 **range filter**로 순회

   ```
   filter = base_filter + f" and id gt '{last_id}'"
   top    = PAGE_SIZE
   order  = "id asc"
   ```

3. **Step 3 이후 짧은 재검증 루프** — 첫 패스 이후 `count(old_version) > 0` 이면 3회 정도 5–10초 간격으로 재검색+재삭제
4. **`get_count()` 를 정확값으로 가정 금지** — 정확성 검증에는 순회 카운트 또는 저장된 기대값 N을 사용

**재현 실험 결과** (Standard tier, replica 3, partition 3개 × 35,000건 병렬 업로드):

| 지표                                    | `upload` + `order_by` 없음 | `merge_or_upload` + `order_by=id` |
| --------------------------------------- | -------------------------- | --------------------------------- |
| Step 3 에서 구 버전 누락률              | 최대 약 35%                | **0 — 항상 정확**                 |
| 쓰기 중 Count API와 순회 카운트의 차이  | 최대 +22,000 편차          | 여전히 편차 (설계상 근사)         |
| Step 2 재시도 시 실패                   | 가능 (중복 키)             | 0 (idempotent)                    |

### 옵션 B — Blue/Green (Alias) 스왑 (가장 견고)

각 버전을 **불변 인덱스**로 취급하고 alias만 원자적으로 전환합니다.

```
index-v1   ← alias "prod" 가 가리키며 서비스 중
index-v2   ← 트래픽 없이 깨끗하게 새로 적재
(alias)    ← "prod" 를 index-v2 로 repoint
index-v1   ← 일정 유예 시간 후 삭제
```

- 장점: 쓰기/읽기가 같은 인덱스를 건드리지 않아 eventual consistency 영향 0, alias repoint 1회로 롤백, **검색 공백 없음**
- 단점: 전환 중 일시적으로 스토리지 2배, SKU별 인덱스 개수 제한 확인 필요

### 옵션 C — ID 원장(ledger)을 Search 바깥에 유지

alias 도입이 어려운 경우 "무엇을 업로드했는가" 를 검색 서비스와 **분리**합니다.

- 업로드 시점에 `(system_name, version)` 에 해당하는 문서 ID 집합을 별도 저장소(PostgreSQL, Blob, 메타 DB 등)에 영속화
- "이전 버전 삭제" 단계에서는 **저장소에서 ID를 읽어 직접 삭제** (search로 대상 ID를 찾지 않음)

Step 3가 완전히 결정적이 되고 replica lag의 영향을 받지 않습니다.

### 의사결정 매트릭스

| 옵션                | 난이도 | 정확성 | 검색 공백 | 추가 비용             |
| ------------------- | ------ | ------ | --------- | --------------------- |
| A. 자가 보정 방식   | 낮음   | 양호   | 짧게 발생 | 없음                  |
| B. Alias blue/green | 중간   | 최고   | **없음**  | 일시 스토리지 2배     |
| C. 외부 ID 원장     | 중간   | 최고   | 짧게 발생 | 메타데이터 저장소 1개 |

대부분의 팀은 **옵션 A로 시작**하고, 갱신이 사용자 트래픽에 영향을 주는 수준이 되면 **옵션 B로 전환**하는 것이 합리적입니다.

---

## 체크리스트

선택한 옵션과 무관하게 공통으로 적용합니다.

- [ ] 모든 쓰기에 `merge_or_upload_documents` 사용
- [ ] 배치 크기 **500–1000** 권장
- [ ] SDK의 `429` / `503` 에 대해 지수 백오프 재시도
- [ ] 대량 결과셋 순회 시 **key 정렬 + range filter** (기본 순서 의존 금지)
- [ ] `include_total_count=True` 는 **관측용 지표**로만, 정확성 검증용 아님
- [ ] 검증에는 순회 카운트 또는 로컬에 저장된 기대값과 비교
- [ ] **read throughput은 replica 확장, index 크기는 partition 확장** (혼동 금지)
- [ ] 레이턴시와 `@odata.count` 편차를 대시보드로 관측 (쓰기 집중 시 일시적 편차는 정상 동작)

---

## 결론

- 본 증상은 버그가 아닌 Azure AI Search의 설계된 동작입니다.
- 동시 쓰기 + multi-replica 읽기 환경에서 ① **정렬 없는 pagination**, ② **`merge_or_upload` 대신 `upload`**, ③ **`@odata.count` 를 정확값으로 신뢰** — 이 세 가지가 편차를 증폭시킵니다.
- 대부분의 파이프라인은 `merge_or_upload` 전환 + `order_by="id"`(또는 range-key pagination) + 짧은 재검증 루프만으로 사용자 영향 수준의 문제가 사라집니다.
- 엄격한 정확성이 필요하면 **Alias blue/green 스왑** 또는 **외부 ID 원장**을 채택합니다.

---

## 직접 재현해 보기

자급식 재현 스크립트: [repro.py](./repro.py). Azure AI Search 서비스가 미리 준비되어 있어야 합니다.

```bash
# 1. Azure AI Search 서비스 생성 (35k 문서면 Basic 도 충분.
#    Standard + replica 2~3 이 eventual consistency 를 더 잘 드러냄)
az group create -n rg-aisearch-demo -l <region>
az search service create \
  -g rg-aisearch-demo -n <your-service> \
  --sku standard --replica-count 2 --partition-count 1

# 2. 환경 변수 설정
export AZURE_AI_SEARCH_ENDPOINT="https://<your-service>.search.windows.net"
export AZURE_AI_SEARCH_API_KEY="$(az search admin-key show \
    -g rg-aisearch-demo --service-name <your-service> \
    --query primaryKey -o tsv)"

# 3. venv + SDK 설치
python -m venv .venv && source .venv/bin/activate
pip install azure-search-documents

# 4. 실행 — "original" 5회 + "workaround" 2회를 돌리고 per-cycle 리포트 출력,
#    repro_results.json 저장
python repro.py

# 5. 과금 방지용 정리
az group delete -n rg-aisearch-demo --yes --no-wait
```

환경 변수 튜닝: `DOC_COUNT`(기본 35000), `BATCH_SIZE`(512), `AZURE_AI_SEARCH_INDEX_NAME`(`repro-index`), `SYSTEM_NAME`(`test-system`).

재현 강도를 높이려면:

- `--replica-count` 를 3으로
- `system_name` 값을 여러 개 두고 파이프라인을 **병렬**로 실행
- 스크립트의 `propagation_wait_sec` 을 줄임

수정 효과 확인은 `use_order_by=True`, `use_merge_or_upload=True` 로 재실행하여 비교합니다.

---

## 참고 링크

- [Performance & indexing](https://learn.microsoft.com/azure/search/search-performance-optimization)
- [Indexing for large data sets](https://learn.microsoft.com/azure/search/search-howto-large-index)
- [Pagination / page layout](https://learn.microsoft.com/azure/search/search-pagination-page-layout)
- [Counting matching documents](https://learn.microsoft.com/azure/search/search-pagination-page-layout#total-hits-and-page-counts)
- [Similarity & scoring](https://learn.microsoft.com/azure/search/index-similarity-and-scoring)
- [Update or rebuild an index](https://learn.microsoft.com/azure/search/search-howto-reindex)
- [Index aliases](https://learn.microsoft.com/azure/search/search-how-to-alias)
- [Service limits](https://learn.microsoft.com/azure/search/search-limits-quotas-capacity)
- [Capacity planning](https://learn.microsoft.com/azure/search/search-capacity-planning)
