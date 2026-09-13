"""bge-m3-ko embedding benchmark — runs ON the GPU VM against local TEI (no deps, stdlib only).

Scenario A: single-query latency  (AI Search Custom Vectorizer path — always 1 text/call)
Scenario B: batch throughput      (Push API ingestion path — batch x concurrency)
Scenario C: batch throughput with longer chunks — use --chunk-chars 1000

Usage:
    python3 bench_embed_gpu.py --gpu t4 --rounds 5                      # A + B (~500-char chunks)
    python3 bench_embed_gpu.py --gpu t4 --rounds 3 --chunk-chars 1000   # C (~1,000-char chunks)
Output: JSON lines to stdout + summary file /tmp/bench_result_<gpu>.json
"""
import argparse
import json
import math
import statistics as st
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

TEI = "http://127.0.0.1:8080"

# ── Korean sample texts ──────────────────────────────────────────────────────
QUERY = "갤럭시 S24 울트라의 S펜 기능과 배터리 사용 시간은 어떻게 되나요?"  # ~40 chars

CHUNK_BASE = (
    "Azure AI Search는 클라우드 기반의 검색 서비스로, 전문 검색과 벡터 검색, 하이브리드 검색을 모두 지원한다. "
    "인덱서를 사용할 수 없는 구성에서는 Push API를 통해 문서를 직접 적재해야 하며, 이 경우 임베딩 생성은 "
    "외부 GPU 엔드포인트에서 수행된다. BGE-M3 한국어 모델은 1024차원 벡터를 생성하며 최대 8192 토큰을 "
    "처리할 수 있다. 대량 적재 시나리오에서는 배치 크기와 동시성 설정이 전체 처리량을 좌우하는 핵심 요소가 된다. "
    "HNSW 알고리즘 기반의 벡터 인덱스는 코사인 유사도를 사용하고, BM25 키워드 검색과 RRF로 결합하면 "
    "하이브리드 검색이 완성된다. 한국어 형태소 분석기 ko.microsoft를 함께 사용하면 키워드 매칭 품질이 향상된다. "
    "청킹 전략은 문서 구조에 따라 섹션 단위 또는 의미 단위로 선택하며, 청크 하나는 대략 오백 자 내외가 적당하다. "
    "임베딩 처리량은 GPU 아키텍처, 텐서 코어 세대, 메모리 대역폭에 따라 크게 달라지므로 실측이 필수적이다."
)  # ~500 chars

def make_chunks(n: int, chars: int = 500) -> list[str]:
    """Build n chunks of `chars` target length (body) by repeating/truncating CHUNK_BASE.

    A unique suffix (~15-20 chars) is appended AFTER truncation to prevent any
    server-side caching effects, so actual chunk length is `chars` + suffix.
    The measured mean length is reported as `chunk_chars_actual` in results.
    """
    reps = math.ceil(chars / len(CHUNK_BASE))
    body = (CHUNK_BASE * reps)[:chars]
    return [f"{body} (문서 번호 {i}번 청크입니다.)" for i in range(n)]


def post_embed(texts: list[str], timeout: float = 120.0) -> float:
    """POST /embed, return elapsed seconds."""
    body = json.dumps({"inputs": texts, "normalize": True}).encode()
    req = urllib.request.Request(f"{TEI}/embed", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()
    return time.perf_counter() - t0


def scenario_a(n_requests: int = 100) -> dict:
    """Single-query latency, sequential (vectorizer path)."""
    lat = [post_embed([QUERY]) * 1000 for _ in range(n_requests)]
    lat_sorted = sorted(lat)
    return {
        "n": n_requests,
        "mean_ms": round(st.mean(lat), 2),
        "p50_ms": round(lat_sorted[len(lat) // 2], 2),
        "p95_ms": round(lat_sorted[math.ceil(len(lat) * 0.95) - 1], 2),  # nearest-rank p95
        "min_ms": round(lat_sorted[0], 2),
        "max_ms": round(lat_sorted[-1], 2),
    }


def scenario_b(total_texts: int, batch: int, conc: int, chunk_chars: int = 500) -> dict:
    """Batch throughput: total_texts split into batches, sent with `conc` workers."""
    chunks = make_chunks(total_texts, chunk_chars)
    batches = [chunks[i:i + batch] for i in range(0, len(chunks), batch)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=conc) as ex:
        list(ex.map(post_embed, batches))
    wall = time.perf_counter() - t0
    return {
        "total_texts": total_texts, "batch": batch, "concurrency": conc,
        "chunk_chars": chunk_chars,
        "chunk_chars_actual": round(st.mean(len(c) for c in chunks), 1),  # incl. unique suffix
        "wall_s": round(wall, 3),
        "texts_per_s": round(total_texts / wall, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", required=True)
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--chunk-chars", type=int, default=500,
                    help="target chunk length in chars (500=scenario B, 1000=scenario C)")
    args = ap.parse_args()

    # warmup
    for _ in range(5):
        post_embed([QUERY])
    post_embed(make_chunks(32, args.chunk_chars))

    results = {"gpu": args.gpu, "rounds": []}
    B_COMBOS = [(1, 1), (1, 4), (1, 8), (8, 4), (32, 1), (32, 4), (32, 8), (64, 4)]
    TOTAL = 256  # texts per throughput combo

    for r in range(1, args.rounds + 1):
        round_res = {"round": r}
        round_res["single_query"] = scenario_a(100)
        print(json.dumps({"gpu": args.gpu, "round": r, "A": round_res["single_query"]},
                         ensure_ascii=False), flush=True)
        combos = []
        for batch, conc in B_COMBOS:
            res = scenario_b(TOTAL, batch, conc, args.chunk_chars)
            combos.append(res)
            print(json.dumps({"gpu": args.gpu, "round": r, "B": res},
                             ensure_ascii=False), flush=True)
        round_res["throughput"] = combos
        results["rounds"].append(round_res)

    out = f"/tmp/bench_result_{args.gpu}.json"
    with open(out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"saved -> {out}", flush=True)


if __name__ == "__main__":
    main()
