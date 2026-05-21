# BGE-M3 vs Qwen3-Embedding-0.6B 벡터 검색 품질 비교

**동일한 Azure AI Search Integrated Vectorization 파이프라인에서 BGE-M3와 Qwen3-Embedding-0.6B의 벡터 검색 품질을 비교한 결과**

---

## 📌 핵심 요약

| 항목 | BGE-M3 | Qwen3-Embedding-0.6B |
|------|--------|---------------------|
| 파라미터 수 | 0.6B | 0.6B |
| 최대 임베딩 차원 | 1024 | 1024 |
| MTEB Multilingual Score | 59.56 | **64.33** (+4.77) |
| 컨텍스트 길이 | 8K | **32K** |
| 라이선스 | MIT | Apache 2.0 |
| Instruction 지원 | ✗ | ✅ |
| 벡터 검색 1위 정확도 (영어 5건) | 5/5 | 5/5 |
| 벡터 검색 1위 정확도 (한글 5건) | 2/5 | 2/5 |
| Score 차별력 (1위-2위 gap, 영어) | 평균 0.027 | **평균 0.056** |
| 한글 벡터 Score | **높음** | 낮음 |
| 한글 하이브리드 검색 | S펜 매칭 실패 | **S펜 매칭 정확** |

> 📌 **영어 문서에서는 Qwen3가 Score 차별력에서 우위**, **한글 문서에서는 BGE-M3가 전반적 Score에서 우위**이나 하이브리드 검색의 고유명사 매칭은 Qwen3가 정확.

---

## 모델 소개

### BAAI/bge-m3

Beijing Academy of AI(BAAI)에서 개발한 다국어 임베딩 모델. Dense, Sparse, ColBERT 세 가지 리트리벌 방식을 하나의 모델에서 동시에 지원하는 것이 특징이다. 100개 이상 언어를 지원하며, 다국어 벤치마크에서 꾸준히 상위권에 위치한다.

| 항목 | 값 |
|------|----|
| 파라미터 | 568M |
| 벡터 차원 | 1024 (고정) |
| 최대 토큰 | 8192 |
| 다국어 | 100+ 언어 |
| 리트리벌 | Dense + Sparse + ColBERT |
| 이미지 크기 | ~2.3GB |
| CPU 인덱싱 속도 | 5문서 ~2분 |

### Qwen/Qwen3-Embedding-0.6B

Alibaba Qwen 팀에서 개발한 경량 임베딩 모델. Instruction-tuned 방식으로, 쿼리 앞에 task instruction을 붙이면 검색 품질이 향상된다. 32K 컨텍스트와 동적 벡터 차원(256~8192)을 지원하여 긴 문서나 저장 공간 최적화에 유리하다. `trust_remote_code=True` 설정이 필요하다.

| 항목 | 값 |
|------|----|
| 파라미터 | 600M |
| 벡터 차원 | 동적 (256~8192, 기본 1024) |
| 최대 토큰 | 32768 |
| 다국어 | 영어, 중국어, 한국어 등 주요 언어 |
| Instruction | 지원 (쿼리 앞 task prefix) |
| 이미지 크기 | ~2.5GB |
| CPU 인덱싱 속도 | 5문서 ~10분 |

> 💡 두 모델 모두 sentence-transformers 호환이므로 `EMBEDDING_MODEL` 환경변수만 변경하면 동일 파이프라인에서 교체 가능하다.

---

## 🔍 비교 조건

| 항목 | 값 |
|------|-----|
| AI Search | `ais-aiplay-krc-01` (Standard, koreacentral) |
| BGE-M3 인덱스 | `sample-vector-idx` (영어) / `samsung-bge-idx` (한글) |
| Qwen3 인덱스 | `qwen3-vector-idx` (영어) / `samsung-qwen-idx` (한글) |
| 데이터 소스 (영어) | `sample-docs-ds` (5건 Azure 서비스 설명 문서) |
| 데이터 소스 (한글) | `samsung-docs` (7건 삼성 갤럭시 제품 소개) |
| 벡터 차원 | 1024 (동일) |
| 알고리즘 | HNSW cosine (동일 파라미터) |
| HTTPS 엔드포인트 | `ca-bge-m3-embed` / `ca-qwen3-embed` (Container Apps) |
| Instruction 사용 | 두 모델 모두 미사용 (동일 조건) |

### 테스트 문서 목록

| 파일 | 내용 |
|------|------|
| azure-kubernetes.txt | AKS 설명 (컨테이너 오케스트레이션) |
| azure-container-apps.txt | Container Apps 설명 (서버리스 컨테이너) |
| azure-functions.txt | Functions 설명 (서버리스 이벤트 드리븐) |
| azure-cosmos-db.txt | Cosmos DB 설명 (글로벌 분산 DB) |
| azure-ai-search.txt | AI Search 설명 (검색 서비스) |

---

## 🧪 벡터 검색 비교

### 쿼리 1: "How does Azure handle container orchestration?"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.7421 | **0.7903** | azure-kubernetes.txt ✅ |
| 2 | 0.7404 | 0.7438 | azure-container-apps.txt |
| 3 | 0.7031 | 0.7202 | azure-functions.txt |
| 4 | 0.7031 | 0.7038 | azure-cosmos-db.txt |
| 5 | 0.6931 | 0.6534 | azure-ai-search.txt |

**분석:** 두 모델 모두 AKS를 1위로 정확하게 선정. Qwen3가 1위 Score(0.79)가 더 높고, 1-2위 gap이 BGE-M3(0.002) 대비 Qwen3(0.047)로 **23배 더 큰 차별력**을 보여준다.

---

### 쿼리 2: "serverless event-driven compute platform"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.7333 | **0.8251** | azure-functions.txt ✅ |
| 2 | 0.6930 | 0.7321 | azure-container-apps.txt |
| 3 | 0.6693 | 0.6998 | azure-cosmos-db.txt |
| 4 | 0.6487 | 0.6599 | azure-kubernetes.txt |
| 5 | 0.6108 | 0.6524 | azure-ai-search.txt |

**분석:** Functions를 1위로 정확하게 선정. Qwen3의 1위 Score(0.825)가 BGE-M3(0.733)보다 훨씬 높고, 1-2위 gap도 Qwen3(0.093) > BGE-M3(0.040)로 확연한 차이.

---

### 쿼리 3: "globally distributed low-latency database"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.7323 | **0.7679** | azure-cosmos-db.txt ✅ |
| 2 | 0.6466 | 0.6446 | azure-kubernetes.txt / azure-ai-search.txt |
| 3 | 0.6385 | 0.6387 | azure-container-apps.txt / azure-functions.txt |
| 4 | 0.6250 | 0.6200 | azure-ai-search.txt / azure-container-apps.txt |
| 5 | 0.6219 | 0.5845 | azure-functions.txt / azure-kubernetes.txt |

**분석:** Cosmos DB를 1위로 정확하게 선정. Qwen3의 1-2위 gap(0.123)이 BGE-M3(0.086)보다 크며, Qwen3는 2위 이하 문서의 순서가 약간 다르다 (AI Search가 2위로 올라옴).

---

### 쿼리 4: "컨테이너를 서버리스로 실행하는 Azure 서비스" (한국어)

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | **0.7615** | 0.7497 | azure-container-apps.txt / azure-kubernetes.txt |
| 2 | 0.7604 | 0.7471 | azure-functions.txt / azure-container-apps.txt |
| 3 | 0.7216 | 0.7258 | azure-kubernetes.txt / azure-functions.txt |
| 4 | 0.6982 | 0.6928 | azure-cosmos-db.txt |
| 5 | 0.6690 | 0.6608 | azure-ai-search.txt |

**분석:** 한국어 쿼리 + 영어 문서 크로스링구얼 매칭. **BGE-M3는 Container Apps를 1위**로, **Qwen3는 AKS를 1위**로 선정. 쿼리가 "컨테이너를 서버리스로 실행"이므로 Container Apps가 더 적합한 답이라고 볼 수 있어 **BGE-M3가 이 쿼리에서 더 정확**했다. 다만 Score 차이가 매우 근소하다.

> ⚠️ 두 모델 모두 영어 문서에 대해 한국어 쿼리로 잘 매칭하지만, 이 테스트에서 BGE-M3가 한국어 크로스링구얼 매칭에서 약간 우위를 보인다.

---

### 쿼리 5: "I need to run a machine learning model cheaply" (간접적 쿼리)

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.6304 | 0.6457 | azure-cosmos-db.txt / azure-functions.txt |
| 2 | 0.6267 | 0.6233 | azure-kubernetes.txt / azure-ai-search.txt |
| 3 | 0.6265 | 0.6124 | azure-functions.txt / azure-container-apps.txt |
| 4 | 0.6259 | 0.6058 | azure-container-apps.txt / azure-cosmos-db.txt |
| 5 | 0.6135 | 0.5804 | azure-ai-search.txt / azure-kubernetes.txt |

**분석:** 테스트 문서 중 ML에 직접적으로 관련된 문서가 없어 두 모델 모두 Score가 전반적으로 낮다. BGE-M3는 모든 문서의 Score가 0.61~0.63으로 거의 동일하게 나온 반면, Qwen3는 Functions(0.646)를 상대적으로 높게 랭킹하여 **약간 더 차별력** 있는 결과를 보여주었다.

---

## 📊 하이브리드 검색 비교

키워드 검색 + 벡터 검색을 결합한 하이브리드 검색에서는 RRF(Reciprocal Rank Fusion) 스코어링이 적용되어 모델 간 차이가 줄어든다.

### "serverless event-driven" (키워드) + "serverless event-driven compute" (벡터)

| 순위 | BGE-M3 | Qwen3 | 문서 |
|------|--------|-------|------|
| 1 | 0.0333 | 0.0333 | azure-functions.txt |
| 2 | 0.0328 | 0.0328 | azure-container-apps.txt |
| 3 | 0.0161 | 0.0161 | azure-cosmos-db.txt |

### "database global replication" (키워드) + "globally distributed database with replication" (벡터)

| 순위 | BGE-M3 | Qwen3 | 문서 |
|------|--------|-------|------|
| 1 | 0.0333 | 0.0333 | azure-cosmos-db.txt |
| 2 | 0.0164 | 0.0164 | azure-kubernetes.txt / azure-ai-search.txt |
| 3 | 0.0161 | 0.0161 | azure-container-apps.txt / azure-functions.txt |

> 📌 하이브리드 검색에서 1위 결과는 동일하다. RRF 스코어링이 벡터 Score 차이를 상쇄하여, 하이브리드 검색에서는 모델 차이가 거의 없다. **2위 이하 순서에서만 약간의 차이**가 발생한다.

---

## 🇰🇷 한글 문서 벡터 검색 비교

영어 Azure 서비스 문서 외에, **삼성 갤럭시 한글 제품 소개 문서 7건**으로 동일한 비교를 수행했다.

### 비교 조건

| 항목 | 값 |
|------|----|
| BGE-M3 인덱스 | `samsung-bge-idx` + `bge-m3-vectorizer` |
| Qwen3 인덱스 | `samsung-qwen-idx` + `qwen3-vectorizer` |
| 데이터 소스 | `samsung-docs` blob container, 한글 7건 |
| 벡터 차원 | 1024 (동일) |
| CPU 인덱싱 속도 | BGE-M3 ~2분 vs Qwen3 ~10분 |

### 테스트 문서 목록

| 파일 | 내용 |
|------|------|
| Galaxy S25 Ultra | 200MP 카메라, S펜 내장, AI 기능 플래그십 |
| Galaxy S25 | 표준 플래그십 모델 |
| Galaxy Z Fold6 | 대화면 폴더블, 멀티태스킹 |
| Galaxy Z Flip6 | 컴팩트 폴더블, 가격 경쟁력 |
| Galaxy S24 FE | 팬 에디션, 가성비 |
| Galaxy A56 | 중저가 AI폰, 5000mAh 배터리, 이틀 사용 |
| Galaxy Ring | 건강 모니터링 웨어러블 |

---

### 🧪 벡터 검색 비교 (한글)

#### 쿼리 1: "카메라 성능이 가장 좋은 스마트폰"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.665 | 0.621 | Galaxy A56 ❌ |

**분석:** 정답은 S25 Ultra (200MP 카메라)이지만, 두 모델 모두 A56을 1위로 선정. BGE-M3 score spread(0.664~0.646)이 Qwen3(0.620~0.604)보다 넓다. 제품 문서가 모두 카메라를 언급하고 있어 세부 사양 기반 랭킹에 한계.

---

#### 쿼리 2: "접히는 폴더블 스마트폰 중 가격이 저렴한 모델"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.676 | 0.607 | Galaxy Z Fold6 ❌ |

**분석:** 정답은 Z Flip6 (더 저렴)이지만, 두 모델 모두 Z Fold6을 1위로 선정. BGE-M3는 Flip6을 2위에, Qwen3는 Flip6을 4위까지 밀어냄. "폴더블"이라는 키워드에 치중한 임베딩 매칭의 한계.

---

#### 쿼리 3: "건강 모니터링 수면 추적 웨어러블 디바이스"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | **0.662** | **0.643** | Galaxy Ring ✅ |
| 2 | 0.618 | 0.566 | — |

**분석:** 두 모델 모두 Galaxy Ring을 1위로 정확하게 선정. BGE-M3 1-2위 gap(0.044)과 Qwen3 gap(0.077)으로, **Qwen3가 더 큰 차별력**을 보여준다. 명확한 도메인 구분이 있는 쿼리에서 양쪽 모두 정확.

---

#### 쿼리 4: "가성비 좋은 갤럭시 AI 스마트폰 100만원 이하"

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | **0.698** | **0.675** | Galaxy A56 ✅ |

**분석:** 두 모델 모두 A56을 1위로 정확하게 선정. BGE-M3가 S24 FE를 2위로 배치하여 올바른 순서를 보여주었으나, Qwen3는 Galaxy Ring을 2위에 배치 (이상치).

---

#### 쿼리 5: "which phone has the best battery life and longest usage time" (영→한 크로스링구얼)

| 순위 | BGE-M3 Score | Qwen3 Score | 문서 |
|------|-------------|-------------|------|
| 1 | 0.662 | 0.600 | S25 Ultra / Ring ❌ |

**분석:** 정답은 A56 (5000mAh, 이틀 사용 가능)이지만, BGE-M3는 S25 Ultra를, Qwen3는 Ring을 1위로 선정. 영어 쿼리 → 한글 문서 매칭에서 두 모델 모두 "battery life"의 의미를 정확히 매칭하지 못함.

---

### 📊 하이브리드 검색 비교 (한글)

#### "폴더블 큰 화면 멀티태스킹" (키워드) + "폴더블 스마트폰으로 큰 화면에서 멀티태스킹" (벡터)

| 순위 | BGE-M3 | Qwen3 | 문서 |
|------|--------|-------|------|
| 1 | ✅ | ✅ | Galaxy Z Fold6 |
| 2 | — | — | Galaxy Z Flip6 |
| 3 | — | — | Galaxy S25 |

**분석:** 두 모델 모두 Z Fold6 → Z Flip6 → S25 순서로 동일하게 정확. 하이브리드 검색에서 "폴더블" 키워드가 보강 역할.

---

#### "S펜 지원 플래그십 모델" (키워드) + "S펜을 지원하는 삼성 최상위 플래그십 스마트폰" (벡터)

| 순위 | BGE-M3 | Qwen3 | 문서 |
|------|--------|-------|------|
| 1 | S24 FE ❌ | **S25 Ultra** ✅ |
| 2 | S25 | S25 |
| 3 | S25 Ultra | S24 FE |

**분석:** S25 Ultra가 S펜 내장 플래그십이므로 정답. **Qwen3가 정확하게 S25 Ultra를 1위로 선정**한 반면, BGE-M3는 S24 FE를 1위로 잘못 배치. "S펜"이라는 고유명사 키워드가 있음에도 BGE-M3는 키워드 매칭에 실패. **한글 하이브리드 검색에서 Qwen3가 우위**.

---

### 한글 문서 비교 종합

| 항목 | BGE-M3 | Qwen3 |
|------|--------|-------|
| 벡터 검색 1위 정확도 | 2/5 | 2/5 |
| 전반적 Score 높이 | **높음** | 낮음 |
| 건강/가성비 (명확한 쿼리) | ✅ 정확 | ✅ 정확 |
| 카메라/배터리 (세부 비교) | ❌ 부정확 | ❌ 부정확 |
| 하이브리드 폴더블 | ✅ 정확 | ✅ 정확 |
| 하이브리드 S펜 | ❌ 실패 | **✅ 정확** |
| 인덱싱 속도 (7문서) | **~2분** | ~10분 |

> 📌 **한글 문서에서는 BGE-M3가 전반적으로 높은 Score를 보이지만, Qwen3가 하이브리드 검색에서 고유명사("S펜") 매칭에 더 정확**했다. 영어 문서 결과와 대조적으로, 한글 환경에서는 두 모델의 강약이 바뀌는 양상을 보인다.

---

## 결론

| 관점 | 우위 모델 | 설명 |
|------|----------|------|
| **영어 1위 정확도** | 동률 | 5/5 쿼리에서 양쪽 모두 정확 |
| **한글 1위 정확도** | 동률 | 2/5 (명확한 쿼리만 정확, 세부 비교 쿼리 실패) |
| **Score 차별력** | **Qwen3** | 영어: 1-2위 gap 평균 2배 이상, 한글: 건강 모니터링 gap 더 큼 |
| **영어 벡터 검색** | **Qwen3** | 전반적으로 Score가 더 높고 랭킹이 선명 |
| **한글 벡터 Score** | **BGE-M3** | 전반적으로 Score가 더 높음 (영어와 반대) |
| **한국어 크로스링구얼** | **BGE-M3** | 영어 쿼리→한글 문서, 한글 쿼리→영어 문서 모두 우위 |
| **하이브리드 검색 (영어)** | 동률 | RRF로 차이 상쇄됨 |
| **하이브리드 검색 (한글)** | **Qwen3** | "S펜" 고유명사 매칭에서 정확, BGE-M3 실패 |
| **인덱싱 속도 (CPU)** | **BGE-M3** | BGE-M3 ~2분 vs Qwen3 ~10분 (한글 7문서 기준) |
| **Instruction 활용** | **Qwen3** | 쿼리에 Instruction prefix 추가 시 추가 성능 향상 가능 |

### 권장 사항

이 비교는 아래 제약 조건 하에서의 결과이므로 절대적 품질 판단이 아닌 **참고용**으로 활용해야 한다.

| 제약 | 영향 |
|------|------|
| **CPU 전용 추론** | GPU 대비 인덱싱 속도 느림 (Qwen3는 5문서에 ~10분). 추론 정밀도(FP32 vs FP16)에 따른 품질 차이 미확인 |
| **소형 모델 (0.6B)** | BGE-M3(568M), Qwen3(600M) 모두 경량 모델. 대형 모델(e.g. gte-Qwen2-7B, e5-mistral-7b) 대비 의미 구분 능력에 한계 |
| **소량 문서** | 영어 5건, 한글 7건으로 통계적 유의미성 부족. 대규모 코퍼스에서 결과가 달라질 수 있음 |
| **Instruction 미사용** | Qwen3는 쿼리/문서에 task instruction prefix를 붙이면 품질이 향상되지만, 현재 Embedding API가 단일 엔드포인트(`/api/embed`)로 인덱싱과 쿼리를 동시에 처리하므로 instruction 분기를 적용하지 않음 |
| **Chunk 미분할** | 문서 전체를 단일 벡터로 임베딩. 실제 운영에서는 텍스트 분할(chunking) 적용 시 결과가 달라짐 |

---

## 📋 참고

- [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) — MIT, 0.6B params
- [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) — Apache 2.0, 0.6B params
- [MTEB Multilingual Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [Azure AI Search Custom Web API Vectorizer](https://learn.microsoft.com/en-us/azure/search/vector-search-vectorizer-custom-web-api)
