# A10 vs T4 임베딩 추론 벤치마크: BGE-m3-ko + TEI (Azure Spot VM)

**AI Search + Agent 구성(Indexer 미사용, Push API)에서 TEI로 서빙한 dragonkue/BGE-m3-ko의 추론 성능을 A10·T4에서 실측 비교**

> 관련 문서: [GPU vLLM RAG 가이드](03_gpu_vllm_rag_guide.md) | [Custom 임베딩 적재 가이드](01_custom_embedding_guide.md) | [BGE-M3 vs Qwen3 품질 비교](ref_bge_m3_vs_qwen3_comparison.md)
>
> 작성일: 2026-07-22

---

## 📌 핵심 요약

| 항목 | T4 (NC4as_T4_v3) | A10 (NV36ads_A10_v5) | 배율 (A10/T4) |
|------|------------------|----------------------|------|
| 단건 레이턴시 mean | 5.59 ms | **3.97 ms** | 1.4× |
| 단건 레이턴시 p95 | 6.10 ms | **4.38 ms** | 1.4× |
| 최대 처리량 (~500자 청크) | 61 texts/s | **301 texts/s** | **4.9×** |
| 최대 처리량 (~1,000자 청크) | 23 texts/s | **130 texts/s** | **5.5×** |
| 1M 청크(500자) 적재 소요 | 4.5 hr | **0.9 hr** | 5× |

- **쿼리 경로(단건 추론)**: 양쪽 모두 single-digit ms — latency-bound 구간으로, 전체 검색 응답 시간에서 차지하는 비중이 상대적으로 작음
- **적재 경로(배치 추론)**: throughput-bound 구간에서 **본 테스트 환경 기준 A10 처리량이 T4 대비 약 5배 수준으로 측정**. T4는 ~60 texts/s 부근에서 GPU 사용률·전력이 상한에 도달했으며, 본 벤치마크 조건에서는 batch size/concurrency 조정만으로는 유의미한 추가 향상을 확인하지 못함
- 공개 스펙 교차검증 — FP16 Tensor TFLOPS비 1.9×, Flash Attention 지원 차이, 메모리 대역폭 2×가 **주요 원인으로 추정**되며, 공개 스펙 기반 예측 범위(4.3~5.8×)와 실측 결과의 방향성이 일치 → [교차검증 섹션](#교차검증-공개-스펙벤치마크와의-정합성)
- 스케일아웃: 본 측정 조건 기준 **A10 × N ≈ T4 × 5N**(500자) / **× 6N**(1,000자) 수준 — 최소 SKU(NC4as) × N + Internal LB 구성 시 VM 비용만 기준 약 15~18% 절감 가능성 관찰 (500자) → [스케일아웃 전략](#스케일아웃-전략-t4-최소-sku--n--lb)

> ⚠️ **측정 범위**: 본 측정은 **임베딩 생성 구간(TEI `/embed`)만 대상**이며, Azure AI Search 문서 업로드 및 인덱싱 시간은 포함하지 않는다. 실제 End-to-End 적재 시간은 Search 서비스 SKU, 문서 크기, 배치 크기 및 서비스 부하에 따라 달라질 수 있다. 또한 측정값은 모델, 텍스트 길이·토큰 분포, 서빙 엔진 버전, 드라이버 버전, 배치 설정 및 운영 환경에 따라 달라질 수 있다.

---

## 벤치마크 구성

| 항목 | T4 VM | A10 VM |
|------|-------|--------|
| VM SKU | Standard_NC4as_T4_v3 (Spot) | Standard_NV36ads_A10_v5 (Spot) |
| GPU | Tesla T4 16GB GDDR6 (Turing TU104, CC 7.5) | A10-24Q 24GB GDDR6 (Ampere GA102, CC 8.6, full-GPU vGPU 프로필) |
| vCPU / RAM | 4 vCPU / 28GB (16 vCPU 교차검증 완료, 하단 참고) | 36 vCPU / 440GB |
| 드라이버 | 610.43.02 (CUDA) | 570.211.01 (GRID) |
| 리전 / OS | southcentralus / Ubuntu 22.04 Gen2 | 동일 |
| 서빙 엔진 | TEI `turing-1.8` | TEI `86-1.8` |
| 모델 | dragonkue/BGE-m3-ko (XLM-RoBERTa, 568M params, 1024-dim, max 8192 tokens) | 동일 |
| TEI 옵션 | `--max-client-batch-size 128 --auto-truncate`, normalize=true | 동일 |
| 측정 위치 | **VM 내부 localhost 호출** — 네트워크 RTT 변수 제거 | 동일 |

**구성 시 주의사항:**
- NVadsA10v5 시리즈 중 **full-GPU 프로필(NV36ads, A10-24Q 24GB 단독 점유)** 사용. NV6/12/18ads는 GPU fractional 파티션(1/6~1/2) — 본 결과 적용 불가
- T4는 TEI **Turing 전용 이미지(`turing-1.8`) 필수**. Turing은 TEI [experimental 지원](https://github.com/huggingface/text-embeddings-inference#docker-images), Flash Attention 기본 비활성화
- NVIDIA 드라이버는 Azure VM extension `NvidiaGpuDriverLinux`(Microsoft.HpcCompute)로 설치 — GRID/CUDA 자동 판별. A10은 GRID 드라이버 필수 (수동 CUDA 드라이버 설치 시 vGPU 라이선스 실패)
- 실행 스크립트: [bench/](bench/)

> ⚠️ **vCPU 격차(4 vs 36)의 결과 왜곡 여부 교차검증 완료.** T4 VM을 NC16as_T4_v3(16 vCPU)로 리사이즈 후 동일 벤치마크 5라운드 재실행:
> - 500자 최대 처리량 61.0 texts/s (4 vCPU: 61.3) / 1,000자 22.6 (4 vCPU: 23.4) / 단건 5.86ms (4 vCPU: 5.59ms) — **vCPU 4배 증가에도 측정 오차(±3%) 이내**
> - 부하 중 GPU util 100% / CPU idle ~80% → **병목은 GPU 연산(compute-bound), host CPU 무관**
> - 결론: 본 문서의 T4 수치는 NC4as/NC16as 모든 SKU에 동일 적용 가능

### 측정 시나리오

Indexer 미사용 구성의 임베딩 호출 경로 2종:

```
① 쿼리 경로 (실시간):  Agent/AI Search Custom Vectorizer → /embed (항상 단건)
② 적재 경로 (Push API): 앱 → 청킹 → /embed (배치) → AI Search Push
```

| 시나리오 | 입력 | 측정 방식 |
|----------|--------|-----------|
| A. 단건 레이턴시 | 한국어 쿼리 ~40자 | 순차 100회 × 5라운드, mean/p50/p95 |
| B. 배치 처리량 (500자) | 한국어 청크 ~530자 | 256건, batch size × concurrency 8조합 스윕 × 5라운드 |
| C. 배치 처리량 (1,000자) | 한국어 청크 ~1,050자 | 128건, batch=32 / conc=4 × 3라운드 |

---

## 🧪 결과 1: 단건 레이턴시 (Custom Vectorizer 경로)

5라운드 × 100회 = 500회 측정:

| GPU | mean | p50 | p95 | min | max |
|-----|------|-----|-----|-----|-----|
| T4 | 5.59 ms | 5.52 ms | 6.10 ms | 5.34 ms | 8.89 ms |
| A10 | **3.97 ms** | **3.90 ms** | **4.38 ms** | 3.70 ms | 5.57 ms |

**분석:**
- A10 1.4× 우위이나 절대값은 양쪽 모두 single-digit ms
- 하이브리드 검색 E2E 응답 대비 벡터화 비중은 상대적으로 작음 (E2E가 수십 ms급인 저지연 환경이라면 1.6ms 차이의 비중은 커질 수 있음)
- 라운드 간 편차 ±0.1ms — 재현성 확보

## 🧪 결과 2: 배치 처리량 — 500자 청크 (Push API 적재 경로)

5라운드 평균 texts/s (256건 기준):

| batch × concurrency | T4 | A10 | 배율 |
|--------------------|-----|-----|------|
| 1 × 1 | 59.3 | 150.0 | 2.5× |
| 1 × 4 | 60.1 | 202.7 | 3.4× |
| 1 × 8 | 60.4 | 257.1 | 4.3× |
| 8 × 4 | **61.3** | 279.7 | 4.6× |
| 32 × 1 | 60.4 | 271.1 | 4.5× |
| 32 × 4 | 58.4 | 295.5 | 5.1× |
| 32 × 8 | 55.9 | 297.3 | 5.3× |
| 64 × 4 | 55.7 | **301.2** | **5.4×** |

라운드 간 표준편차: T4 ≤2.1, A10 ≤6.1 texts/s (CV ~2%) — 5회 반복 전부 재현.

**분석:**
- **T4: ~60 texts/s 부근에서 상한 도달.** 본 벤치마크 조건에서는 batch/concurrency 조정만으로는 유의미한 추가 향상을 확인하지 못했으며, 64×4에서는 오히려 소폭 하락(스케줄링 오버헤드 추정). 부하 중 `nvidia-smi`: GPU util 100%, power draw 69W/70W(TDP cap 도달), CPU idle 73% → **GPU compute/power 제약으로 판단** (TEI 버전 업그레이드, quantization 등 서빙 스택 차원의 최적화는 본 측정 범위 외)
- **A10: batch=1에서도 concurrency 스케일링 유효**(150→257, TEI dynamic batching 효과), batch 증가 시 ~300 texts/s 포화. 최대 부하에서도 GPU util ≤84% — SM occupancy 여유 잔존
- 격차 요인(추정): Ampere 3세대 Tensor Core(SM당 2× FP16 처리량) + FP16 Tensor 연산비(65 vs 125 TFLOPS) + TEI Flash Attention 지원 차이의 복합

## 🧪 결과 3: 배치 처리량 — 1,000자 청크

3라운드 평균 (batch=32, conc=4):

| GPU | texts/s | 500자 대비 |
|-----|---------|-----------|
| T4 | 23.4 | -62% |
| A10 | **129.7** | -57% |
| 배율 | **5.5×** | |

**분석:**
- 시퀀스 길이 증가 시 배율 5.4× → 5.5×로 확대
- 원인: attention 연산량 O(N²) 스케일링 — 이미 포화 상태인 T4가 더 민감하게 하락
- **장문(1,000자+) 위주 코퍼스일수록 A10 우위 확대**

---

## 교차검증: 공개 스펙·벤치마크와의 정합성

실측 배율(4.9~5.5×)의 타당성을 공개 자료로 검증. **공개 스펙과 실측 결과의 방향성이 일치**하며, 이론 TFLOPS비(1.9×)를 하한선으로 아래 3개 요인이 **주요 원인으로 추정**된다. (TEI 내부 구현, dynamic batching 동작, 드라이버 버전, 토큰 분포 등도 영향 요인이므로 정확한 기여도 분해는 본 측정 범위 외)

### 공식 스펙 비교 (NVIDIA 데이터시트)

| 항목 | T4 | A10 | 배율 |
|------|----|----|------|
| 아키텍처 / Compute Capability | Turing (TU104) / 7.5 | Ampere (GA102) / 8.6 | — |
| FP16 Tensor TFLOPS (dense) | 65 | 125 | **1.9×** |
| 메모리 대역폭 | 300 GB/s | 600 GB/s | **2.0×** |
| TDP | **70 W** | 150 W | 2.1× |
| CUDA 코어 | 2,560 | 9,216 | 3.6× |
| Tensor Core 세대 | 2세대 | 3세대 (SM당 FP16 FMA 2×) | — |

### 실측 배율(4.9~5.5×) > 스펙비(1.9×)의 추정 메커니즘

1. **T4 70W power cap** — 패시브 쿨링·저전력 폼팩터 설계로 70W가 하드 리밋. 지속 배치 부하에서 boost clock 유지 불가 → 이론 peak TFLOPS 미도달 (실측: GPU 100% + 69W/70W 포화 확인). 지속 부하 기준 유효 격차 ~2.5–3×
2. **TEI의 Turing Flash Attention 기본 비활성화** — TEI 공식 README: *"Flash Attention is turned off by default for the Turing image as it suffers from precision issues"*. FlashAttention-2는 `cp.async` 등 Ampere(CC 8.0+) 전용 명령 의존 → Turing 미지원. 결과적으로 T4는 O(N²) HBM 왕복의 standard attention, A10은 SRAM-fused FA 커널로 동작. **시퀀스 길이에 비례해 격차 확대 — 실측 500자 4.9× → 1,000자 5.5× 패턴과 일치**
3. **메모리 대역폭 2×** — BGE-m3(XLM-RoBERTa encoder) 배치 추론은 레이어 간 activation 이동이 지배하는 memory bandwidth-bound 워크로드

곱셈 효과 추정: 1.9× (compute) × ~1.5–2× (FA 유무) × 잔여 대역폭 효과 ≈ **4.3–5.8×** — 실측 4.9~5.5×가 이 범위 안에 있어 방향성이 일치

**단건 1.4×의 정합성** — 단건 추론은 SM under-utilization 상태의 latency-bound 구간. 배치·FA·대역폭 이점 미발현, 세대 간 clock/IPC 차이만 반영 → 1.3~1.5× 예측과 일치.

**vGPU 오버헤드** — NV36ads_A10_v5 = A10 1장 전체(24GB) 단독 점유, time-slicing 없음. A10-24Q 프로필의 paravirtualization 오버헤드 ~5–10% → bare-metal A10 대비 본 실측이 오히려 보수적 수치.

> 참고: BGE-M3 + TEI + T4/A10 조합의 공개 처리량 벤치마크 부재 (MLPerf Inference는 BERT-large, T4↔A100 중심) — 본 실측이 해당 구성의 1차 자료. MLPerf T4↔A100 BERT 추론 격차(8–12×) × A10≈A100의 70–80% 연산 성능으로 유추한 A10↔T4 5–8× 범위와도 부합.

**출처:** [T4 데이터시트](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/tesla-t4/t4-tensor-core-datasheet-951643.pdf) · [A10 데이터시트](https://www.nvidia.com/content/dam/en-zz/Solutions/Data-Center/a10/pdf/a10-datasheet.pdf) · [TEI README (Turing FA 경고)](https://github.com/huggingface/text-embeddings-inference) · [FlashAttention (Turing 미지원)](https://github.com/Dao-AILab/flash-attention) · [NVadsA10_v5 문서](https://learn.microsoft.com/en-us/azure/virtual-machines/sizes/gpu-accelerated/nvadsa10v5-series) · [Ampere 마이크로아키텍처](https://en.wikipedia.org/wiki/Ampere_(microarchitecture))

---

## 스케일아웃 전략: T4 최소 SKU × N + LB

> 현행 운영 기준(A10 × 2, SPOF 없음)을 T4 스케일아웃으로 대체/보완할 경우의 등가 구성·비용·아키텍처 분석. vCPU 교차검증(GPU compute-bound 확인)이 본 전략의 실측 근거 — T4 계열 최소 SKU(NC4as_T4_v3, 4 vCPU)로도 GPU 처리량은 동일하므로 **처리량/달러 최적점 = 최소 SKU × N**.

### 스케일 업/아웃 옵션별 효과

| 방법 | 처리량 효과 | 근거 |
|------|------------|------|
| T4 1장에 TEI 다중 인스턴스 | ❌ 0% | GPU util 100% + 70W TDP cap 포화 (실측) — SM time-slicing 경합만 추가. MPS는 단일 프로세스 미포화 시에만 유효, MIG는 Turing 미지원 |
| 파이프라인 병렬화 (청킹∥임베딩∥푸시) | △ wall time 10~20% 단축 | CPU/GPU/네트워크 자원 비중첩 — producer-consumer 큐로 오버랩. 처리량 상한(임베딩 단계)은 불변 |
| **T4 VM 수평 확장 (N대 + LB)** | ✅ ~선형 (N×60 texts/s) | VM별 독립 GPU — 간섭 없음 |

### 등가 배수: A10 N대 ↔ T4 몇 대?

본 측정 조건 기준 처리량 비(500자 4.9×, 1,000자 5.5×)로 환산한 **산술 등가**:

| 기준 (A10 대수) | 500자 워크로드 | 1,000자 워크로드 |
|----------------|----------------|------------------|
| A10 × 1 (301 texts/s) | **T4 × 5 수준** (305 texts/s) | **T4 × 6 수준** (140 vs 130 texts/s) |
| A10 × 2 (602 texts/s) — 현행 | **T4 × 10 수준** (610 texts/s) | **T4 × 12 수준** (281 vs 259 texts/s) |
| A10 × N | T4 × 5N | T4 × 6N |

> ⚠️ 위 등가는 단일 노드 실측치의 산술 배수다. 실제 환경에서는 LB 분배 편차, 콜드스타트/warmup, Spot eviction, 요청 크기 불균형 등으로 유효 처리량이 이보다 낮아질 수 있으므로 **여유분(+1대 이상) 산정을 권장**한다.

### 비용 비교 — PAYG(정규 VM) 기준

Azure Retail Prices API 조회 (2026-07, southcentralus 기준 — 리전별 단가 상이): NC4as_T4_v3 $0.631/hr, NV36ads_A10_v5 $3.84/hr

| 구성 | 시간당 (southcentralus) | A10 등가 대비 |
|------|------------------------|---------------|
| A10 × 2 (현행) | $7.68/hr | 기준 |
| T4 × 10 (500자 등가) | $6.31/hr | 약 -18% |
| T4 × 12 (1,000자 등가) | $7.57/hr | -1% (사실상 동률) |

> 위 절감률은 **VM 비용만 기준으로 관찰된 수치**다. 부대비용(LB·디스크·NAT)과 노드 수 증가에 따른 운영비(모니터링, 패치, 장애 대응 인력)를 포함한 TCO는 환경별로 재산정이 필요하다.

- 부대비용: Standard LB ~$0.025/hr + OS 디스크(P10급) ~$0.02/hr×N → T4 10대 기준 **+$0.25/hr** → 실질 ~$6.56/hr, VM+부대비용 기준 약 15% 낮음 (Internal LB 구성 — 노드별 Public IP 불필요, 아웃바운드는 NAT Gateway 또는 default outbound로 처리. HF 모델 다운로드 등 이그레스용 NAT Gateway 추가 시 +$0.045/hr)
- 상시 운영이면 1-year Savings Plan/RI 적용 시 30~60% 추가 절감 여지 (양쪽 공통)

### 엔드포인트 아키텍처

TEI는 stateless HTTP(`POST /embed`) — L4 분배로 충분:

```
앱(청킹 파이프라인) ──> Internal Standard LB (:8080) ──> backend pool
                          │ health probe: GET /health (TEI 내장)
                          ├─ vm-t4-01 (NC4as_T4_v3)
                          ├─ vm-t4-02
                          └─ vm-t4-N        # VMSS 구성 시 증감·복구 자동화
```

| 옵션 | 적합도 | 비고 |
|------|--------|------|
| **Internal Standard LB** | ✅ 권장 | L4, 저비용, health probe로 노드 장애 자동 제외 |
| VMSS + LB | ✅ 운영 자동화 | 노드 증감·재생성 자동. Spot 혼용 시 eviction 복구 포함 |
| Application Gateway | △ 과잉 | TLS 종료·L7 라우팅 필요 시에만 — 비용·홉 추가 |
| 클라이언트 사이드 라운드로빈 | △ 적재 전용이면 가능 | 적재 파이프라인이 유일한 클라이언트면 IP 리스트 셔플로 충분 — LB 불요 |

**설계 파라미터:**
- 분배 모드: 기본 5-tuple hash — 배치 요청이 요청 단위로 분산되므로 세션 어피니티 불요 (활성화 시 편중 발생)
- Health probe: TEI `/health` — 모델 로딩(콜드스타트 ~1-2분) 중 자동 제외
- 노드당 최적 부하 유지: batch 8~32 / conc 4 × N대 → 파이프라인 전체 concurrency = 4N
- 노드 장애 시 처리량 (N-1)/N로 우아한 성능 저하 — N≥5면 노드 1대 손실 시에도 80%+ 유지
- 쿼리 경로(Custom Vectorizer) 겸용 가능 — LB 홉 <1ms, 단건 5.6ms 대비 무시 가능

### 전략 판단

| 관점 | T4 × 5N + LB | A10 × N (현행) |
|------|--------------|----------------|
| 시간당 비용 (500자) | ✅ VM 비용 기준 약 -15~18% | — |
| 시간당 비용 (1,000자) | 동률 (6N대 필요) | — |
| 장애 내성 | 노드당 1/5N 손실 | 노드당 1/N 손실 (N≥2면 SPOF 없음) |
| 운영 복잡도 | 관리 포인트 5N (LB·probe·드라이버 패치) | ✅ 관리 포인트 N |
| 스케일 증분 | ✅ 60 texts/s 단위 미세 조정 | 301 texts/s 단위 |

**권장:** 500자 내외 청크 위주 워크로드에서는 **T4 × 5N + Internal LB(+VMSS)** 가 전략적으로 유리 (VM 비용 기준 약 15~18% 절감 가능성 + 미세한 스케일 증분). 장문(1,000자+) 비중이 크면 등가 대수가 6N으로 늘어 비용 이점이 소멸하므로 A10 유지가 합리적. 최종 선택은 운영비를 포함한 TCO와 조직의 운영 역량을 함께 고려해 판단할 것.

---

## 결론 및 권장

| 시나리오 | 권장 GPU | 근거 |
|----------|----------|------|
| 쿼리 벡터화 (실시간 검색 경로) | **둘 다 가능** | 4~6ms — latency-bound, E2E 응답 대비 비중 작음 |
| 대량 초기 적재 (Push API, 데드라인 존재) | **A10** | 본 측정 기준 약 5~5.5× — 1M 청크 기준 0.9hr vs 4.5hr |
| 상시 증분 적재 (소량) | **T4 충분** | 60 texts/s = 21.6만 건/hr — 증분 볼륨 대비 과분 |
| 장문(1,000자+) 위주 코퍼스 | **A10** | 시퀀스 길이 비례 격차 확대 (측정 기준 5.5×) |

> 위 권장은 본 측정 환경(TEI 1.8, dragonkue/BGE-m3-ko, 한국어 텍스트) 기준이며, 실제 결과는 모델·텍스트 길이·서빙 엔진 버전·배치 설정·운영 환경에 따라 달라질 수 있다.

**운영 파라미터:**
- Push 파이프라인 최적점: T4 = batch 8~32 / conc 4 (초과 시 역효과), A10 = batch 32~64 / conc 4~8
- 1M+ 청크 적재: A10 1대 ≈ T4 5대 — 운영 단순성은 A10, 비용·스케일 증분은 T4 스케일아웃 우위 → [스케일아웃 전략](#스케일아웃-전략-t4-최소-sku--n--lb) 참고
- Spot eviction 대비: Push 파이프라인에 retry + checkpoint(마지막 성공 문서 ID) 필수. 본 측정 중 eviction 미발생
- **A10 Spot 수급 주의**: NVadsA10_v5 Spot은 수급 변동성이 크며 특정 시간대에는 할당이 실패할 수 있다. 운영 환경에서는 PAYG 또는 예약 인스턴스(RI/Savings Plan)와의 조합 검토를 권장

---

## 재현 방법

<details>
<summary>인프라 생성 + 벤치마크 실행 명령</summary>

```bash
# 1. Spot VM 생성 (southcentralus, docker+container-toolkit은 cloud-init으로)
az group create -n rg-embed-bench -l southcentralus
az vm create -g rg-embed-bench -n vm-t4-bench --image Ubuntu2204 \
  --size Standard_NC4as_T4_v3 --priority Spot --eviction-policy Deallocate --max-price -1 \
  --admin-username azureuser --ssh-key-values ~/.ssh/embed_bench_key.pub \
  --os-disk-size-gb 128 --nsg-rule NONE --custom-data cloud-init-gpu.yaml
az vm create -g rg-embed-bench -n vm-a10-bench --image Ubuntu2204 \
  --size Standard_NV36ads_A10_v5 --priority Spot --eviction-policy Deallocate --max-price -1 \
  --admin-username azureuser --ssh-key-values ~/.ssh/embed_bench_key.pub \
  --os-disk-size-gb 128 --nsg-rule NONE --custom-data cloud-init-gpu.yaml

# 2. NSG에 내 IP만 SSH 허용 + NVIDIA 드라이버 확장 (GRID/CUDA 자동 판별)
az network nsg rule create -g rg-embed-bench --nsg-name vm-t4-benchNSG -n allow-ssh-myip \
  --priority 100 --source-address-prefixes <MY_IP>/32 --destination-port-ranges 22 --access Allow --protocol Tcp
az vm extension set -g rg-embed-bench --vm-name vm-t4-bench \
  --name NvidiaGpuDriverLinux --publisher Microsoft.HpcCompute --version 1.11
# (a10도 동일)

# 3. TEI 기동 — T4는 turing 태그, A10은 86 태그
sudo docker run -d --gpus all --name tei -p 8080:80 -v /opt/tei-data:/data \
  ghcr.io/huggingface/text-embeddings-inference:turing-1.8 \
  --model-id dragonkue/BGE-m3-ko --max-client-batch-size 128 --auto-truncate   # T4
sudo docker run -d --gpus all --name tei -p 8080:80 -v /opt/tei-data:/data \
  ghcr.io/huggingface/text-embeddings-inference:86-1.8 \
  --model-id dragonkue/BGE-m3-ko --max-client-batch-size 128 --auto-truncate   # A10

# 4. 벤치마크 (VM 내부에서 localhost로 실행 — 네트워크 변수 제거)
python3 bench_embed_gpu.py --gpu t4 --rounds 5                      # 시나리오 A+B (500자)
python3 bench_embed_gpu.py --gpu t4 --rounds 3 --chunk-chars 1000   # 시나리오 C (1,000자)
```

</details>

<details>
<summary>원시 데이터 (5라운드 전체)</summary>

- 단건 레이턴시(mean_ms) 라운드별 — T4: 5.51 / 5.63 / 5.57 / 5.64 / 5.60, A10: 3.88 / 3.95 / 3.95 / 4.09 / 3.98
- 최대 조합(64×4) texts/s 라운드별 — T4: 57.0 / 56.3 / 54.2 / 57.1 / 53.7, A10: 303.4 / 297.5 / 303.4 / 303.1 / 298.4
- 1,000자(32×4) texts/s — T4: 24.2 / 23.4 / 22.7, A10: 128.0 / 131.1 / 130.0
- 부하 중 GPU 상태 — T4: util 100%, power 69W/70W(TDP cap), CPU idle 73% / A10: util ≤84%
- **T4 16 vCPU(NC16as_T4_v3) 교차검증** — 단건 mean_ms: 5.76 / 5.94 / 5.93 / 5.85 / 5.82, 최적 조합 texts/s(500자): 63.6 / 62.3 / 61.8 / 60.6 / 59.9, 1,000자(32×4): 22.5 / 23.0 / 22.3 — 4 vCPU 결과와 오차범위 내 동일. 부하 중 GPU 100% / 62W, CPU idle 80.7%

</details>

---

## 부록: 비용 참고

> Spot 기준 실험 — 가격은 시점·리전 변동성이 커 참고 수준으로만 기재.

- southcentralus, 2026-07: T4(NC4as_T4_v3) Spot $0.183/hr · PAYG $0.631/hr / A10(NV36ads_A10_v5) Spot $0.710/hr · PAYG $3.84/hr
- 1M 청크(500자) 적재 비용: Spot — A10 $0.65 ≈ T4 $0.83 / PAYG — T4 $2.87 < A10 $3.53
