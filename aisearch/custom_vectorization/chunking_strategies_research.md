# RAG Chunking 전략 리서치 보고서

**Azure AI Search Custom Web API 파이프라인에서 활용 가능한 최신 Chunking 전략, 프레임워크, 논문 정리**

> 작성일: 2026-05-22 | 관련 문서: [custom_vectorization.md](custom_vectorization.md)

---

## 핵심 요약

> 인용 수: Google Scholar / Semantic Scholar 기준, 2026-05-22 시점. GitHub ★: 같은 날짜 기준.

| # | 전략 | 저자/기관 | 발행년 | 베뉴 | 인용 수 | GitHub ★ | 핵심 아이디어 | 난이도 |
|---|------|----------|--------|------|---------|---------|-------------|------|
| 1 | [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) | Anthropic | 2024 | Blog | — | — | 청크에 문서 맥락 요약을 prepend | 중 |
| 2 | [Late Chunking](https://arxiv.org/abs/2409.04701) | Jina AI (Günther et al.) | 2024 | arXiv (v3 2025-07) | 79 | [512](https://github.com/jina-ai/late-chunking) | 긴 컨텍스트 임베딩 모델로 토큰 임베딩 후 청킹 | 중 |
| 3 | [Dense X Retrieval](https://aclanthology.org/2024.emnlp-main.845/) | Chen et al. | 2023 | **EMNLP 2024** | 111 | — | 문서를 atomic fact 단위로 분해 | 고 |
| 4 | [Evaluating Chunking Strategies](https://www.trychroma.com/research/evaluating-chunking) | Chroma (Smith & Troynikov) | 2024 | Research | — | [489](https://github.com/brandonstarxel/chunking_evaluation) | 임베딩 유사도 기반 경계 탐지 | 중 |
| 5 | [Adaptive Chunking](https://arxiv.org/abs/2603.25333) | Ekimetrics (de Moura Júnior et al.) | 2026 | **LREC 2026** | 0 | [96](https://github.com/ekimetrics/adaptive-chunking) | 문서별 최적 분할 방법 자동 선택 | 중 |
| 6 | [PIC](https://aclanthology.org/2025.findings-acl.422/) | Wang et al. (Tsinghua) | 2025 | **ACL-Findings 2025** | 17 | — | 문서 요약 기반 동적 세그멘테이션 | 중 |
| 7 | [LumberChunker](https://arxiv.org/abs/2406.17526) | Duarte et al. (INESC-ID/CMU) | 2024 | **EMNLP 2024 Findings** | 42 | [106](https://github.com/joaodsmarques/LumberChunker) | LLM이 의미 전환점을 찾아 동적 분할 | 고 |

---

## 1. Contextual Retrieval (Anthropic, 2024-09)

### 개요

Anthropic이 제안한 방법으로, 전통적인 RAG에서 청크가 원본 문서의 맥락을 잃는 문제를 해결한다. 각 청크에 문서 전체를 참고한 짧은 맥락 설명(50~100 토큰)을 prepend한 후 임베딩하고 BM25 인덱스를 생성한다.

### 핵심 메커니즘

```
original_chunk = "The company's revenue grew by 3% over the previous quarter."

contextualized_chunk = "This chunk is from an SEC filing on ACME corp's performance
in Q2 2023; the previous quarter's revenue was $314 million.
The company's revenue grew by 3% over the previous quarter."
```

Claude를 사용한 contextualization 프롬프트:

```
<document>
{{WHOLE_DOCUMENT}}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{{CHUNK_CONTENT}}
</chunk>
Please give a short succinct context to situate this chunk within the overall
document for the purposes of improving search retrieval of the chunk.
Answer only with the succinct context and nothing else.
```

### 성능

- Contextual Embeddings만 적용: top-20 retrieval 실패율 **35% 감소** (5.7% → 3.7%)
- Contextual Embeddings + Contextual BM25: 실패율 **49% 감소** (5.7% → 2.9%)
- Reranking까지 결합: 실패율 **67% 감소** (5.7% → 1.9%)

### Custom Web API 적용 방안

`/api/chunk` 엔드포인트에서 텍스트를 분할한 뒤, 각 청크에 대해 LLM(로컬 또는 API)을 호출하여 맥락 문장을 생성하고 청크 앞에 붙인다. 인덱싱 시간은 늘어나지만 검색 품질이 크게 향상된다. Prompt caching을 활용하면 비용을 절감할 수 있다.

### 참고

- Blog: [Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) (Anthropic, 2024-09-19)
- Cookbook: [Contextual Embeddings Guide](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)

---

## 2. Late Chunking (Jina AI, 2024-09)

### 개요

기존 RAG 파이프라인에서는 문서를 먼저 청크로 나눈 뒤 각 청크를 독립적으로 임베딩한다. 이 과정에서 청크 간 문맥(anaphoric reference 등)이 소실된다. Late Chunking은 **먼저 전체 문서를 긴 컨텍스트 임베딩 모델의 transformer layer에 통과**시켜 토큰 레벨 임베딩을 생성한 후, **그 다음에 청크 경계에 따라 mean pooling**을 적용한다.

### 기존 방식 vs Late Chunking

| | Naive Chunking | Late Chunking |
|---|---|---|
| 경계 정보 필요 | Yes | Yes |
| 경계 사용 시점 | 전처리 단계에서 직접 분할 | Transformer layer 이후 mean pooling 시점 |
| 청크 임베딩 특성 | i.i.d. (독립) | Conditional (문맥 의존적) |
| 인접 청크 맥락 | 소실 (overlap 등 휴리스틱으로 완화) | Long-context 모델이 보존 |

### 성능

BeIR 벤치마크 4개 데이터셋에서 naive chunking 대비 **평균 약 3% relative improvement** (nDCG@10). **문서 길이가 길수록 개선폭이 커짐.** 참조 문맥어(대명사 등)가 분할로 단절되는 문제를 완화함을 실험적으로 입증.

> 전체 문서를 한 번에 임베딩할 수 있는 long-context 모델이 필요하며, 모델 컨텍스트 윈도우를 초과하는 대용량 문서에서는 부분 분할(long late chunking) 전략을 병행해야 한다.

### Custom Web API 적용 방안

`/api/embed` 엔드포인트를 수정하여, 문서 전체(또는 가능한 최대 길이)를 먼저 transformer에 통과시키고, 외부에서 전달받은 청크 경계에 맞춰 mean pooling을 수행하도록 구현한다. jina-embeddings-v3 등 8192 토큰 이상을 지원하는 long-context 임베딩 모델이 필요하다.

### 참고

- Blog: [Late Chunking in Long-Context Embedding Models](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) (Jina AI, 2024-08-23)
- Paper: [arXiv:2409.04701](https://arxiv.org/abs/2409.04701) — Günther, Mohr, Williams, Wang, Xiao (2024, v3 revised 2025-07)
- Code: [github.com/jina-ai/late-chunking](https://github.com/jina-ai/late-chunking)

---

## 3. Proposition-based Chunking — Dense X Retrieval (EMNLP 2024)

### 개요

문서를 passage나 sentence 단위가 아닌 **proposition(명제)** 단위로 분해하여 인덱싱한다. Proposition은 텍스트 내의 atomic expression으로, 각각 하나의 독립적 사실을 포함하며 자기 완결적(self-contained) 자연어 형태로 표현된다.

### 예시

원문:
> "Berlin is the capital and largest city of Germany, with a population of over 3.85 million."

Propositions:
1. "Berlin is the capital of Germany."
2. "Berlin is the largest city of Germany."
3. "Berlin has a population of over 3.85 million."

### 성능

- Passage 단위 대비 retrieval 성능에서 유의미한 개선 (fine-grained 청크가 passage 단위보다 높은 Recall 및 QA 정확도)
- 특히 computation budget이 제한된 상황에서 QA 성능 향상이 두드러짐
- 다만 청크 수가 크게 늘어 **인덱스 크기, 메모리, 지연시간 증가**를 감수해야 하며, 검색 후 연관된 여러 명제 청크를 재조합해 LLM에 전달하는 워크플로우가 필요 (cross-granularity retrieval 전략)

### Custom Web API 적용 방안

`/api/chunk` 엔드포인트에서 LLM을 호출하여 입력 텍스트를 proposition 리스트로 분해한다. 인덱싱 시간과 비용이 증가하지만, 검색 정밀도가 크게 개선된다.

### 참고

- Paper: [arXiv:2312.06648](https://arxiv.org/abs/2312.06648) — Chen et al. "Dense X Retrieval: What Retrieval Granularity Should We Use?" (arXiv 2023-12, EMNLP 2024)
- ACL Anthology: [2024.emnlp-main.845](https://aclanthology.org/2024.emnlp-main.845/) — EMNLP 2024, Miami, pp.15159–15177

---

## 4. Semantic Chunking

### 개요

텍스트를 고정 길이가 아닌 의미적 유사도를 기준으로 분할한다. 문장 단위로 임베딩을 생성한 뒤, 인접 임베딩 간 cosine distance의 불연속점(discontinuity)을 탐지하여 청크 경계를 설정한다.

### 주요 변형

#### 4a. KamradtSemanticChunker (LangChain)

Greg Kamradt가 제안하고 LangChain에 통합된 방법. 슬라이딩 윈도우의 연속 cosine distance에서 95th percentile 이상을 경계로 설정한다.

- 장점: 의미적 경계를 반영
- 한계: 상대적 임계값이므로 큰 코퍼스에서 청크가 과도하게 커질 수 있음

#### 4b. ClusterSemanticChunker (Chroma, 2024-07)

Chroma 리서치팀이 제안. 50토큰 단위 piece들의 임베딩 간 pairwise cosine similarity 합을 최대화하는 **동적 프로그래밍** 접근으로, 전역적으로 최적인 청크 분할을 생성한다.

- 성능: text-embedding-3-large 기준 **Recall 91.3%** (max chunk 400 토큰) — 전체 전략 중 2위
- 한계: 전역 통계에 의존하므로 데이터 추가 시 재계산 필요

#### 4c. LLMSemanticChunker (Chroma, 2024-07)

LLM에게 직접 청킹을 지시하는 방법. 50토큰 단위 piece에 인덱스 태그를 붙여 LLM에 전달하고, 분할 위치를 반환받는다.

- 성능: **Recall 91.9%** — 평가된 전략 중 최고
- 한계: 비용과 지연 시간이 큼 (수십 분 소요 가능)

### Chroma 벤치마크 결과 요약 (text-embedding-3-large, top-5 chunks)

| 전략 | Chunk Size (평균) | Recall | IoU |
|------|------------------|--------|-----|
| RecursiveCharacterText (200, no overlap) | ~137 | 88.1% | 6.9% |
| TokenText (400, overlap 200) | 400 | 88.6% | 2.7% |
| ClusterSemantic (max 400) | ~182 | **91.3%** | 4.5% |
| LLMSemantic (GPT-4o) | ~240 | **91.9%** | 3.9% |
| Kamradt (default) | ~660 | 83.6% | 1.5% |

> RecursiveCharacterTextSplitter는 chunk size 200, overlap 0에서도 **88.1% recall**로 일관되게 좋은 성능을 보여, **기본 선택으로 여전히 유효**하다.

### Custom Web API 적용 방안

`/api/chunk`에서 sentence-transformers 모델을 로드하여 문장 임베딩 기반 불연속점 탐지 로직을 구현한다. 이미 임베딩 API에 모델이 로드되어 있으므로 추가 비용이 적다.

### 참고

- Research: [Evaluating Chunking Strategies for Retrieval](https://www.trychroma.com/research/evaluating-chunking) (Chroma, 2024-07)
- Code: [github.com/brandonstarxel/chunking_evaluation](https://github.com/brandonstarxel/chunking_evaluation)
- LangChain: [SemanticChunker](https://python.langchain.com/docs/how_to/semantic-chunker/)
- Aurelio AI: [semantic-chunkers](https://github.com/aurelio-labs/semantic-chunkers)

---

## 5. Adaptive Chunking (LREC 2026)

### 개요

Ekimetrics 연구팀(de Moura Júnior, Lelong, Blangero)이 제안하여 **LREC 2026**에 채택된 방법이다. 단일 분할 전략을 모든 문서에 일괄 적용하는 기존 접근의 한계를 해결하기 위해, **문서별로 최적의 청킹 방법을 자동 선택**하는 프레임워크를 제시한다.

### 핵심 메커니즘

5가지 내재적(intrinsic) 평가 메트릭을 정의하여 청킹 품질을 측정한다:

| 메트릭 | 설명 |
|--------|------|
| References Completeness (RC) | 공참조 체인(entity–pronoun)이 청크 경계에서 단절되지 않는 비율 |
| Intrachunk Cohesion (ICC) | 청크 내 문장들과 청크 전체 임베딩 간 의미적 유사도 |
| Document Contextual Coherence (DCC) | 각 청크와 주변 문맥 윈도우의 유사도 |
| Block Integrity (BI) | 구조적 블록(문단, 표, 리스트)이 온전히 보존되는 비율 |
| Size Compliance (SC) | 목표 토큰 수 범위 내 청크 비율 |

여러 분할 방법(Recursive, LLM-regex, Page, Semantic 등)으로 청킹한 결과를 이 메트릭들로 평가한 뒤, 문서별로 가장 높은 점수를 받은 방법을 선택한다.

### 성능

법률·기술·사회과학 3개 도메인, 33개 문서(~1.18M 토큰)에서 평가:

| 지표 | Adaptive Chunking | LLM regex (GPT) | LangChain recursive |
|------|-------------------|-----------------|-------------------|
| Retrieval Completeness | **67.7%** | 58.1% | 59.1% |
| Answer Correctness | **78.0%** | 70.1% | 73.3% |
| 성공적으로 답변된 질의 | **65/99** | 49/99 | 49/99 |

프롬프트나 모델 변경 없이 Answer Correctness 기준 약 5~8pp 향상, 성공 질의 수 약 33% 상대적 증가(65 vs 49).

### Custom Web API 적용 방안

`/api/chunk` 엔드포인트에서 여러 분할 전략을 병렬 실행한 뒤, 5가지 메트릭으로 각 결과를 평가하여 최적 분할을 선택한다. 메트릭 계산에 임베딩 모델과 spaCy가 필요하다. 인덱싱 시간이 증가하지만 문서 유형이 다양한 코퍼스에서 효과적이다.

### 참고

- Paper: [arXiv:2603.25333](https://arxiv.org/abs/2603.25333) — de Moura Júnior, Lelong, Blangero (LREC 2026, 2026-03)
- Code: [github.com/ekimetrics/adaptive-chunking](https://github.com/ekimetrics/adaptive-chunking)

---

## 6. PIC — Pseudo-Instruction Chunking (ACL-Findings 2025)

### 개요

Tsinghua University의 Wang et al.이 제안하여 **ACL-Findings 2025**에 발표된 방법이다. **문서 요약을 일종의 "가짜 지시문(pseudo-instruction)"**으로 활용하여, 요약과 의미적으로 밀접한 문장들을 동적으로 그룹화해 청크를 구성한다.

### 핵심 메커니즘

1. 문서당 **1회 LLM 호출**로 핵심 요약(summary)을 생성
2. 각 문장과 요약 간 **코사인 유사도**를 계산
3. 유사도의 **변화점(change point)**을 탐지하여 청크 경계 설정
4. 의미적으로 관련된 문장들이 자연스럽게 그룹화

규칙 기반(고정 길이) 분할의 과소/과대 청크 문제를 완화하면서도, 모든 문장에 LLM 추론을 적용하는 높은 비용을 피한 것이 특징이다.

### 성능

6개 오픈도메인 QA 벤치마크에서 측정:

| 전략 | Hits@5 |
|------|--------|
| Fixed-size | 54.5 |
| Semantic | 56.0 |
| **PIC** | **58.4** |

고정 길이 대비 약 3.9점, 의미 기반 대비 약 2.4점 높은 Hits@5. 추가 학습 없이 Exact Match(QA 정확도)도 향상.

### 장점 / 한계

- **장점**: 문서당 LLM 1회만 호출하여 비용 효율적, 추가 학습 불필요, 문서 핵심 주제에 맞춘 동적 분할
- **한계**: 보편적 의미가 적은 문서(예: 잡다한 로그 데이터)에서는 요약 품질이 낮아 성능 편차 발생 가능

### Custom Web API 적용 방안

`/api/chunk`에서 먼저 Azure OpenAI로 문서 요약을 생성하고, 문장별 임베딩과 요약 임베딩 간 코사인 유사도를 계산한 뒤 변화점 기반으로 청크를 구성한다. 이미 임베딩 모델이 로드되어 있으므로 추가 비용은 LLM 요약 1회뿐이다.

### 참고

- Paper: [Document Segmentation Matters for RAG](https://aclanthology.org/2025.findings-acl.422/) — Wang et al. (ACL-Findings 2025, Vienna, pp.8063–8075)
- DOI: [10.18653/v1/2025.findings-acl.422](https://doi.org/10.18653/v1/2025.findings-acl.422)

---

## 7. LumberChunker (EMNLP 2024 Findings)

### 개요

INESC-ID/IST 및 Carnegie Mellon University의 Duarte et al.이 제안하여 **EMNLP 2024 Findings**에 채택된 **LLM 주도형 동적 세그멘테이션** 방법이다. LLM에게 문서를 읽히고, 연속된 단락들에서 **내용의 의미 전환 지점을 찾아내게 하여** 문서를 동적으로 분할한다.

### 핵심 메커니즘

1. 문서를 단락(paragraph) 단위로 분할하고 각 단락에 ID를 부여
2. 순차적으로 단락을 그룹(G_i)에 추가하며 토큰 수가 임계값(θ ≈ 550토큰)을 초과하면 그룹 완성
3. 그룹을 LLM(Gemini)에 입력하여 **내용이 전환되기 시작하는 단락 ID**를 식별
4. 해당 ID를 다음 그룹의 시작점으로 설정, 이전까지를 하나의 청크로 확정
5. 문서 끝까지 반복

### 성능

자체 벤치마크 **GutenQA** (100권의 서사 도서, 3000 QA 쌍)에서 평가:

- 가장 경쟁력 있는 baseline(Recursive Chunking) 대비 **DCG@20 7.37% 향상** (62.09 vs 54.72)
- Recall@20: 77.92 vs 74.35
- RAG 파이프라인 통합 시 다른 분할법보다 효과적, Gemini 1.5M Pro와도 경쟁 가능

### 장점 / 한계

- **장점**: 서사형 장문(소설, 보고서)에서 문맥 단위 분절이 유리, 동적 청크 크기로 의미적 독립성 확보
- **한계**: 문서당 반복적 LLM 호출 필요 (비동기화 불가), 처리 시간이 Recursive 대비 수천 배 (0.6초 vs 1628초), 구조화된 문서(법률 등)에서는 단순 구조 기반 분할 대비 이점이 제한적

### Custom Web API 적용 방안

문서 수가 적고 서사형·비구조적 문서가 많은 고가치 시나리오에 적합하다. `/api/chunk`에서 Azure OpenAI를 반복 호출하여 의미 전환점을 탐지한다. 대규모 코퍼스에는 비현실적이므로, 문서 유형에 따라 Recursive/Semantic 등과 조건부 조합(Adaptive Chunking 패턴)하는 것이 바람직하다.

### 참고

- Paper: [arXiv:2406.17526](https://arxiv.org/abs/2406.17526) — Duarte, Marques, Graça, Freire, Li, Oliveira (EMNLP 2024 Findings)
- Code: [github.com/joaodsmarques/LumberChunker](https://github.com/joaodsmarques/LumberChunker)

---

## 8. 주요 프레임워크별 Chunking 지원 현황

| 프레임워크 | 지원 전략 | 비고 |
|-----------|----------|------|
| **LangChain** | RecursiveCharacterTextSplitter, TokenTextSplitter, SemanticChunker, MarkdownSplitter, HTMLSplitter | 가장 다양한 splitter 제공 |
| **LlamaIndex** | SentenceSplitter, SemanticSplitterNodeParser, TokenTextSplitter, MarkdownNodeParser | SemanticDoubleMergingSplitter 추가 |
| **Unstructured** | By character, By title, By page, By similarity, Contextual | 문서 구조 파싱 후 청킹. [Docs](https://docs.unstructured.io/) |
| **Chroma** | ClusterSemanticChunker, LLMSemanticChunker | 연구 프로토타입, 벤치마크 코드 공개 |
| **Azure AI Search** | SplitSkill (Built-in), Custom Web API Skill | SplitSkill: pages/sentences 모드 |

---

## 9. Chunk Size 및 Overlap 가이드라인

### Chunk Size 가이드라인

| 목적 | 권장 크기 | 근거 |
|------|----------|------|
| 높은 Recall 우선 | 400~512 토큰 | Recall과 context 균형 |
| 높은 Precision 우선 | 128~256 토큰 | 정밀한 매칭, IoU 향상 |
| 일반적 시작점 | ~250 토큰 (~1000자) | Chroma 벤치마크 기반 |
| BGE-M3 토큰 제한 | 최대 8192 토큰 | 여유있게 2000자(~500토큰) 이내 |

> **질의 유형에 따라 chunk size를 조정해야 한다.** 사실 기반 질의(fact retrieval)에서는 작은 청크(64~256 토큰)가 recall@1을 10~15pp 개선하지만, 서사 이해(narrative comprehension) 질의에서는 큰 청크가 문맥 연속성을 보존하여 유리하다. 또한 검색된 컨텍스트가 약 2500 토큰을 초과하면 LLM 생성 품질이 저하될 수 있다. ([arXiv:2505.21700](https://arxiv.org/abs/2505.21700), [arXiv:2601.14123](https://arxiv.org/abs/2601.14123))

### Overlap에 대하여

Chroma 연구에 따르면, **overlap을 제거해도 recall 감소가 미미**하며 오히려 IoU(토큰 효율성)가 향상된다. 작은 chunk size와 overlap 0 조합이 효율적이다. 다만 small context embedding 모델(all-MiniLM-L6-v2 등)에서는 overlap이 recall 유지에 도움이 된다.

---

## 10. 용어 정리

| 용어 | 설명 |
|------|------|
| IoU (Intersection over Union) | 검색된 토큰과 관련 토큰의 Jaccard 유사도. 토큰 효율성 측정 |
| nDCG@K | 상위 K개 검색 결과의 순위 품질 측정. 높을수록 관련 문서가 상위에 위치 |
| DCG@K | Discounted Cumulative Gain. 순위를 고려한 검색 품질 측정 (정규화되지 않은 버전) |
| Hits@K | 상위 K개 검색 결과 안에 정답이 포함된 비율 |
| BM25 | 어휘 기반(lexical) 검색 랭킹 함수. TF-IDF를 개선하여 정확한 키워드 매칭에 강점 |
| Anaphoric Reference | 대명사(it, the city 등)가 이전 문맥의 개체를 참조하는 현상 |
| Proposition | 텍스트 내의 원자적 표현. 하나의 사실을 독립적으로 전달하는 자기 완결적 문장 |
| Mean Pooling | 토큰 벡터들의 평균으로 문장/청크의 단일 벡터 표현을 생성하는 방법 |
| Pseudo-Instruction | 문서 요약을 가짜 지시문으로 활용하여 청킹 경계를 결정하는 방법 |
