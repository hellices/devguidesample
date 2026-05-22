"""
Embedding Benchmark Runner (runs inside AKS Pod)

Modes:
  bench-concurrency  — Test various batch/concurrency combos (50 docs)
  push               — Full Push API pipeline (all docs from blob)
  indexer            — Run Indexer pipeline
  compare            — Compare push vs indexer results

All results saved to Azure Blob Storage: bench-docs/results/*.json
"""

import argparse
import asyncio
import json
import os
import re
import time

import httpx
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

# ── Config (from env) ─────────────────────────────────────────────────────────
SEARCH_URL = os.environ.get("SEARCH_URL", "https://ais-aiplay-krc-01.search.windows.net")
SEARCH_API_KEY = os.environ.get("SEARCH_API_KEY", "")
VLLM_EMBED_URL = os.environ.get("VLLM_EMBED_URL", "http://vllm-embedding-svc:8081")
EMBED_SKILL_URI = os.environ.get("EMBED_SKILL_URI", "https://embed.20.249.162.81.nip.io/api/embed")
STORAGE_ACCOUNT = os.environ.get("STORAGE_ACCOUNT", "saidxtest44159")
STORAGE_RG = os.environ.get("STORAGE_RG", "rg-aiplay-krc-01")
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER", "bench-docs")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "Qwen/Qwen3-Embedding-4B")

# Run ID for parallel isolation — set RUN_ID env to run multiple benchmarks side by side
RUN_ID = os.environ.get("RUN_ID", "default")
PUSH_INDEX = os.environ.get("PUSH_INDEX", f"push-bench-{RUN_ID}")
INDEXER_INDEX = os.environ.get("INDEXER_INDEX", f"indexer-bench-{RUN_ID}")
DATA_SOURCE = os.environ.get("DATA_SOURCE", f"bench-ds-{RUN_ID}")
SKILLSET_NAME = os.environ.get("SKILLSET_NAME", f"bench-skillset-{RUN_ID}")
INDEXER_NAME = os.environ.get("INDEXER_NAME", f"bench-indexer-{RUN_ID}")
API_VER = "2024-07-01"
VECTOR_DIM = int(os.environ.get("VECTOR_DIM", "2560"))


def search_headers():
    return {"api-key": SEARCH_API_KEY, "Content-Type": "application/json"}


def get_blob_svc():
    url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net"
    try:
        cred = ManagedIdentityCredential()
        svc = BlobServiceClient(url, credential=cred)
        svc.get_account_information()
        return svc
    except Exception:
        return BlobServiceClient(url, credential=DefaultAzureCredential())


def save_result(blob_svc, name, data):
    container = blob_svc.get_container_client(BLOB_CONTAINER)
    blob_name = f"results/{RUN_ID}/{name}.json"
    container.upload_blob(blob_name, json.dumps(data, indent=2), overwrite=True)
    print(f"  Result saved → {blob_name}", flush=True)


def load_result(blob_svc, name):
    container = blob_svc.get_container_client(BLOB_CONTAINER)
    blob = container.get_blob_client(f"results/{RUN_ID}/{name}.json")
    return json.loads(blob.download_blob().readall())


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_by_sections(content: str, max_chars: int = 2000) -> list[dict]:
    sections = re.split(r'\n(?=##\s)', content)
    chunks = []
    for section in sections:
        section = section.strip()
        if not section or len(section) < 80:
            continue
        header_match = re.match(r'^(#{1,4})\s+(.+)', section)
        section_title = header_match.group(2).strip() if header_match else ""
        if len(section) > max_chars:
            paragraphs = section.split("\n\n")
            current, current_len = [], 0
            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue
                if current_len + len(para) > max_chars and current:
                    chunks.append({"text": "\n\n".join(current), "section": section_title})
                    current, current_len = [para], len(para)
                else:
                    current.append(para)
                    current_len += len(para)
            if current:
                chunks.append({"text": "\n\n".join(current), "section": section_title})
        else:
            chunks.append({"text": section, "section": section_title})
    return chunks


def clean_markdown(text: str) -> str:
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.DOTALL)
    text = re.sub(r'\[!INCLUDE.*?\]', '', text)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r':::image.*?:::', '', text, flags=re.DOTALL)
    return text


# ── Load docs from blob ──────────────────────────────────────────────────────
def load_docs_from_blob(blob_svc, max_docs=0):
    container = blob_svc.get_container_client(BLOB_CONTAINER)
    docs = []
    for blob in container.list_blobs():
        if blob.name.startswith("results/") or not blob.name.endswith(".md"):
            continue
        content = container.get_blob_client(blob.name).download_blob().readall().decode("utf-8")
        content = clean_markdown(content)
        if len(content) >= 300:
            docs.append({"name": blob.name, "content": content})
        if max_docs and len(docs) >= max_docs:
            break
    docs.sort(key=lambda d: d["name"])
    return docs


# ── Mode 1: bench-concurrency ────────────────────────────────────────────────
async def bench_concurrency(blob_svc, num_docs=50):
    print(f"\n{'='*70}", flush=True)
    print(f"  Concurrency Benchmark — {num_docs} docs  [RUN_ID={RUN_ID}]", flush=True)
    print(f"  vLLM: {VLLM_EMBED_URL}", flush=True)
    print(f"{'='*70}\n", flush=True)

    docs = load_docs_from_blob(blob_svc, max_docs=num_docs)
    all_doc_chunks = []
    for d in docs:
        chunks = chunk_by_sections(d["content"])
        if chunks:
            all_doc_chunks.append([c["text"] for c in chunks])

    total_chunks = sum(len(c) for c in all_doc_chunks)
    print(f"  Loaded: {len(all_doc_chunks)} docs, {total_chunks} chunks\n", flush=True)

    # Warmup
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        for _ in range(3):
            await client.post(
                f"{VLLM_EMBED_URL}/v1/embeddings",
                json={"model": EMBED_MODEL, "input": ["warmup"] * 8},
            )
    print("  Warmup done\n", flush=True)

    configs = [
        (8,  5), (8,  10), (8, 20), (8, 30),
        (16, 5), (16, 10), (16, 20), (16, 30),
        (32, 5), (32, 10), (32, 20), (32, 30),
    ]

    async def run_one(embed_batch, concurrency):
        sem = asyncio.Semaphore(concurrency)
        done = 0
        errors = 0

        async def embed_doc(client, chunks):
            nonlocal done, errors
            async with sem:
                for i in range(0, len(chunks), embed_batch):
                    batch = chunks[i:i+embed_batch]
                    for attempt in range(3):
                        try:
                            r = await client.post(
                                f"{VLLM_EMBED_URL}/v1/embeddings",
                                json={"model": EMBED_MODEL, "input": batch},
                                timeout=120.0,
                            )
                            r.raise_for_status()
                            done += len(batch)
                            break
                        except Exception:
                            if attempt == 2:
                                errors += 1
                            else:
                                await asyncio.sleep(1)

        limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency + 5)
        t0 = time.time()
        async with httpx.AsyncClient(verify=False, limits=limits) as client:
            await asyncio.gather(*[embed_doc(client, c) for c in all_doc_chunks])
        elapsed = time.time() - t0
        return elapsed, done, errors

    results = []
    baseline_cps = None
    print(f"  {'batch':>5} {'conc':>5} {'time':>7} {'c/s':>8} {'speedup':>8} {'err':>4}", flush=True)
    print(f"  {'-'*42}", flush=True)

    for batch, conc in configs:
        elapsed, chunks_done, errs = await run_one(batch, conc)
        cps = chunks_done / elapsed if elapsed > 0 else 0
        if baseline_cps is None:
            baseline_cps = cps
        speedup = cps / baseline_cps if baseline_cps > 0 else 0
        row = {"batch": batch, "conc": conc, "time": round(elapsed, 1),
               "chunks_per_sec": round(cps, 1), "speedup": round(speedup, 2), "errors": errs}
        results.append(row)
        print(f"  {batch:>5} {conc:>5} {elapsed:>6.1f}s {cps:>7.1f} {speedup:>7.2f}x {errs:>4}", flush=True)

    best = max(results, key=lambda r: r["chunks_per_sec"])
    print(f"\n  Best: batch={best['batch']} conc={best['conc']} → {best['chunks_per_sec']} chunks/s ({best['speedup']}x)", flush=True)

    save_result(blob_svc, "bench_concurrency", {
        "num_docs": len(all_doc_chunks), "total_chunks": total_chunks,
        "configs": results, "best": best,
    })
    return best


# ── Mode 2: push ─────────────────────────────────────────────────────────────
async def run_push(blob_svc, max_docs=0, embed_batch=16, concurrency=20):
    docs = load_docs_from_blob(blob_svc, max_docs=max_docs)
    print(f"\n{'='*70}", flush=True)
    print(f"  PUSH API Pipeline — {len(docs)} docs  [RUN_ID={RUN_ID}]", flush=True)
    print(f"  embed_batch={embed_batch}, concurrency={concurrency}", flush=True)
    print(f"  index={PUSH_INDEX}, vLLM={VLLM_EMBED_URL}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Create/update index
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        r = await client.put(
            f"{SEARCH_URL}/indexes/{PUSH_INDEX}?api-version={API_VER}",
            json=_index_schema(PUSH_INDEX),
            headers=search_headers(),
        )
        print(f"  Index '{PUSH_INDEX}': {r.status_code}", flush=True)

    sem = asyncio.Semaphore(concurrency)
    stats = {"docs": 0, "chunks": 0, "embed_calls": 0, "embed_time": 0.0, "errors": 0}
    all_index_docs = []
    lock = asyncio.Lock()

    async def embed_texts(client, texts):
        t0 = time.time()
        r = await client.post(
            f"{VLLM_EMBED_URL}/v1/embeddings",
            json={"model": EMBED_MODEL, "input": texts},
            timeout=120.0,
        )
        r.raise_for_status()
        elapsed = time.time() - t0
        data = sorted(r.json()["data"], key=lambda x: x["index"])
        stats["embed_calls"] += 1
        stats["embed_time"] += elapsed
        return [d["embedding"] for d in data]

    async def process_doc(client, doc):
        async with sem:
            try:
                content = doc["content"]
                title_m = re.search(r'^#\s+(.+)', content, re.MULTILINE)
                title = title_m.group(1) if title_m else doc["name"].replace(".md", "")
                doc_id = doc["name"].replace(".md", "").replace("/", "_")

                chunks = chunk_by_sections(content)
                if not chunks:
                    return

                chunk_texts = [c["text"] for c in chunks]
                vectors = []
                for i in range(0, len(chunk_texts), embed_batch):
                    batch = chunk_texts[i:i + embed_batch]
                    for attempt in range(3):
                        try:
                            vecs = await embed_texts(client, batch)
                            vectors.extend(vecs)
                            break
                        except Exception:
                            if attempt == 2:
                                raise
                            await asyncio.sleep(1)

                batch_docs = []
                for i, (cinfo, vec) in enumerate(zip(chunks, vectors)):
                    batch_docs.append({
                        "chunk_id": f"{doc_id}_c{i}",
                        "parent_id": doc_id,
                        "title": title[:200],
                        "section": cinfo.get("section", "")[:200],
                        "chunk": cinfo["text"],
                        "source": doc["name"],
                        "chunkVector": vec,
                        "@search.action": "mergeOrUpload",
                    })

                async with lock:
                    all_index_docs.extend(batch_docs)
                    stats["docs"] += 1
                    stats["chunks"] += len(chunks)

                if stats["docs"] % 200 == 0:
                    elapsed = time.time() - t_start
                    rate = stats["chunks"] / elapsed if elapsed > 0 else 0
                    print(f"    [{elapsed:6.0f}s] {stats['docs']} docs, {stats['chunks']} chunks ({rate:.1f} c/s)", flush=True)
            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 10:
                    print(f"    ERROR {doc['name']}: {e}", flush=True)

    t_start = time.time()
    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency + 5)
    async with httpx.AsyncClient(verify=False, limits=limits) as client:
        tasks = [process_doc(client, d) for d in docs]
        await asyncio.gather(*tasks, return_exceptions=True)

    t_embed = time.time() - t_start
    print(f"\n  Chunk+Embed done: {stats['docs']} docs → {stats['chunks']} chunks in {t_embed:.1f}s", flush=True)

    # Push to index in batches of 500
    print(f"  Pushing {len(all_index_docs)} chunks to index...", flush=True)
    t_push_start = time.time()
    push_ok, push_fail = 0, 0
    async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
        for j in range(0, len(all_index_docs), 500):
            batch = all_index_docs[j:j + 500]
            for attempt in range(3):
                try:
                    r = await client.post(
                        f"{SEARCH_URL}/indexes/{PUSH_INDEX}/docs/index?api-version={API_VER}",
                        json={"value": batch},
                        headers=search_headers(),
                    )
                    if r.status_code < 400:
                        result = r.json()
                        push_ok += sum(1 for v in result.get("value", []) if v.get("statusCode") in (200, 201))
                        push_fail += sum(1 for v in result.get("value", []) if v.get("statusCode") not in (200, 201))
                        break
                    elif attempt == 2:
                        print(f"    Push error batch {j//500+1}: {r.text[:200]}", flush=True)
                except Exception as e:
                    if attempt == 2:
                        print(f"    Push exception batch {j//500+1}: {e}", flush=True)
                    await asyncio.sleep(2)
    t_push = time.time() - t_push_start
    t_total = time.time() - t_start

    results = {
        "method": "push_api",
        "docs": stats["docs"],
        "chunks": stats["chunks"],
        "pushed_ok": push_ok,
        "pushed_fail": push_fail,
        "errors": stats["errors"],
        "embed_batch": embed_batch,
        "concurrency": concurrency,
        "embed_calls": stats["embed_calls"],
        "embed_time_cumulative": round(stats["embed_time"], 1),
        "embed_time_wall": round(t_embed, 1),
        "push_time": round(t_push, 1),
        "total_time": round(t_total, 1),
        "throughput_docs_per_sec": round(stats["docs"] / t_total, 2),
        "throughput_chunks_per_sec": round(stats["chunks"] / t_total, 2),
        "embed_throughput_chunks_per_sec": round(stats["chunks"] / t_embed, 2),
    }

    print(f"\n{'='*70}", flush=True)
    print(f"  Push API Results", flush=True)
    print(f"{'='*70}", flush=True)
    for k, v in results.items():
        if k != "method":
            print(f"  {k:40s}: {v}", flush=True)

    save_result(blob_svc, "push", results)
    return results


# ── Mode 3: indexer ──────────────────────────────────────────────────────────
async def run_indexer(blob_svc, indexer_batch=10, indexer_parallel=10):
    print(f"\n{'='*70}", flush=True)
    print(f"  INDEXER Pipeline  [RUN_ID={RUN_ID}]", flush=True)
    print(f"  batchSize={indexer_batch}, degreeOfParallelism={indexer_parallel}", flush=True)
    print(f"  index={INDEXER_INDEX}, skillset={SKILLSET_NAME}", flush=True)
    print(f"{'='*70}\n", flush=True)

    # Get storage account resource ID for managed identity
    sa_resource_id = os.environ.get("STORAGE_RESOURCE_ID", "")
    if not sa_resource_id:
        print("  ERROR: Set STORAGE_RESOURCE_ID env var", flush=True)
        return

    headers = search_headers()

    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        # 1. Index
        r = await client.put(
            f"{SEARCH_URL}/indexes/{INDEXER_INDEX}?api-version={API_VER}",
            json=_indexer_index_schema(INDEXER_INDEX), headers=headers,
        )
        print(f"  Index: {r.status_code}", flush=True)

        # 2. Data source
        r = await client.put(
            f"{SEARCH_URL}/datasources/{DATA_SOURCE}?api-version={API_VER}",
            json={
                "name": DATA_SOURCE, "type": "azureblob",
                "credentials": {"connectionString": f"ResourceId={sa_resource_id};"},
                "container": {"name": BLOB_CONTAINER},
            }, headers=headers,
        )
        print(f"  DataSource: {r.status_code}", flush=True)
        if r.status_code >= 400:
            print(f"    {r.text[:300]}", flush=True)

        # 3. Skillset
        r = await client.put(
            f"{SEARCH_URL}/skillsets/{SKILLSET_NAME}?api-version={API_VER}",
            json={
                "name": SKILLSET_NAME,
                "skills": [
                    {
                        "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
                        "name": "split-skill", "context": "/document",
                        "textSplitMode": "pages", "maximumPageLength": 2000, "pageOverlapLength": 200,
                        "inputs": [{"name": "text", "source": "/document/content"}],
                        "outputs": [{"name": "textItems", "targetName": "pages"}],
                    },
                    {
                        "@odata.type": "#Microsoft.Skills.Custom.WebApiSkill",
                        "name": "embed-skill", "context": "/document/pages/*",
                        "uri": EMBED_SKILL_URI, "httpMethod": "POST", "timeout": "PT2M",
                        "batchSize": indexer_batch, "degreeOfParallelism": indexer_parallel,
                        "inputs": [{"name": "text", "source": "/document/pages/*"}],
                        "outputs": [{"name": "vector", "targetName": "chunkVector"}],
                    },
                ],
                "indexProjections": {
                    "selectors": [{
                        "targetIndexName": INDEXER_INDEX,
                        "parentKeyFieldName": "parent_id",
                        "sourceContext": "/document/pages/*",
                        "mappings": [
                            {"name": "chunk", "source": "/document/pages/*"},
                            {"name": "chunkVector", "source": "/document/pages/*/chunkVector"},
                            {"name": "title", "source": "/document/metadata_storage_name"},
                        ],
                    }],
                    "parameters": {"projectionMode": "skipIndexingParentDocuments"},
                },
            }, headers=headers,
        )
        print(f"  Skillset: {r.status_code}", flush=True)
        if r.status_code >= 400:
            print(f"    {r.text[:500]}", flush=True)

        # 4. Indexer
        r = await client.put(
            f"{SEARCH_URL}/indexers/{INDEXER_NAME}?api-version={API_VER}",
            json={
                "name": INDEXER_NAME,
                "dataSourceName": DATA_SOURCE,
                "targetIndexName": INDEXER_INDEX,
                "skillsetName": SKILLSET_NAME,
                "parameters": {"batchSize": 10, "configuration": {"dataToExtract": "contentAndMetadata", "parsingMode": "text"}},
                "fieldMappings": [
                    {"sourceFieldName": "metadata_storage_path", "targetFieldName": "chunk_id", "mappingFunction": {"name": "base64Encode"}},
                    {"sourceFieldName": "metadata_storage_name", "targetFieldName": "title"},
                ],
            }, headers=headers,
        )
        print(f"  Indexer: {r.status_code}", flush=True)
        if r.status_code >= 400:
            print(f"    {r.text[:500]}", flush=True)

    # 5. Reset + run
    print(f"\n  Resetting + running indexer...", flush=True)
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        await client.post(f"{SEARCH_URL}/indexers/{INDEXER_NAME}/reset?api-version={API_VER}", headers=headers)
        await asyncio.sleep(2)
        t_start = time.time()
        r = await client.post(f"{SEARCH_URL}/indexers/{INDEXER_NAME}/run?api-version={API_VER}", headers=headers)
        print(f"  Indexer run: {r.status_code}", flush=True)

    # 6. Monitor
    last_items = 0
    while True:
        await asyncio.sleep(10)
        async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
            r = await client.get(f"{SEARCH_URL}/indexers/{INDEXER_NAME}/status?api-version={API_VER}", headers=headers)
        status_data = r.json()
        history = status_data.get("lastResult") or {}
        idx_status = history.get("status", "unknown")
        items_processed = history.get("itemsProcessed", 0)
        items_failed = history.get("itemsFailed", 0)
        elapsed = time.time() - t_start

        if items_processed != last_items:
            rate = items_processed / elapsed if elapsed > 0 else 0
            print(f"    [{elapsed:6.0f}s] processed={items_processed}, failed={items_failed}, rate={rate:.1f} docs/s", flush=True)
            last_items = items_processed

        if idx_status in ("success", "transientFailure", "persistentFailure"):
            break
        if elapsed > 7200:
            print("  TIMEOUT", flush=True)
            break

    t_total = time.time() - t_start

    await asyncio.sleep(5)
    async with httpx.AsyncClient(verify=False, timeout=30.0) as client:
        r = await client.get(f"{SEARCH_URL}/indexes/{INDEXER_INDEX}/docs/$count?api-version={API_VER}", headers=headers)
        chunk_count = int(r.text) if r.status_code == 200 else 0

    results = {
        "method": "indexer", "docs": items_processed, "chunks": chunk_count,
        "errors": items_failed, "indexer_batch": indexer_batch, "indexer_parallel": indexer_parallel,
        "total_time": round(t_total, 1), "status": idx_status,
        "throughput_docs_per_sec": round(items_processed / t_total, 2) if t_total > 0 else 0,
        "throughput_chunks_per_sec": round(chunk_count / t_total, 2) if t_total > 0 else 0,
    }

    print(f"\n{'='*70}", flush=True)
    print(f"  Indexer Results", flush=True)
    print(f"{'='*70}", flush=True)
    for k, v in results.items():
        if k != "method":
            print(f"  {k:40s}: {v}", flush=True)

    save_result(blob_svc, "indexer", results)
    return results


# ── Mode 4: compare ──────────────────────────────────────────────────────────
def compare_results(blob_svc):
    try:
        push = load_result(blob_svc, "push")
        indexer = load_result(blob_svc, "indexer")
    except Exception as e:
        print(f"  Cannot load results: {e}", flush=True)
        return

    print(f"\n{'='*70}", flush=True)
    print(f"  Push API vs Indexer — Comparison", flush=True)
    print(f"{'='*70}\n", flush=True)
    print(f"  {'Metric':<35s} {'Push API':>15s} {'Indexer':>15s} {'Ratio':>10s}", flush=True)
    print(f"  {'─'*75}", flush=True)

    for label, key, fmt in [
        ("Documents", "docs", "d"), ("Chunks", "chunks", "d"), ("Errors", "errors", "d"),
        ("Total time (s)", "total_time", ".1f"),
        ("Docs/s", "throughput_docs_per_sec", ".2f"),
        ("Chunks/s", "throughput_chunks_per_sec", ".2f"),
    ]:
        p = push.get(key, 0)
        i = indexer.get(key, 0)
        ratio = f"{p/i:.2f}x" if i > 0 else "—"
        print(f"  {label:<35s} {p:>15{fmt}} {i:>15{fmt}} {ratio:>10s}", flush=True)

    save_result(blob_svc, "comparison", {"push": push, "indexer": indexer})


# ── Index schemas ─────────────────────────────────────────────────────────────
def _index_schema(name):
    return {
        "name": name,
        "fields": [
            {"name": "chunk_id", "type": "Edm.String", "key": True, "filterable": True},
            {"name": "parent_id", "type": "Edm.String", "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True, "filterable": True},
            {"name": "section", "type": "Edm.String", "searchable": True},
            {"name": "chunk", "type": "Edm.String", "searchable": True},
            {"name": "source", "type": "Edm.String", "filterable": True},
            {"name": "chunkVector", "type": "Collection(Edm.Single)", "searchable": True,
             "dimensions": VECTOR_DIM, "vectorSearchProfile": "qwen3-profile"},
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw-algo", "kind": "hnsw",
                            "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
            "profiles": [{"name": "qwen3-profile", "algorithm": "hnsw-algo"}],
        },
    }


def _indexer_index_schema(name):
    return {
        "name": name,
        "fields": [
            {"name": "chunk_id", "type": "Edm.String", "key": True, "filterable": True, "analyzer": "keyword"},
            {"name": "parent_id", "type": "Edm.String", "filterable": True},
            {"name": "title", "type": "Edm.String", "searchable": True, "filterable": True},
            {"name": "chunk", "type": "Edm.String", "searchable": True},
            {"name": "chunkVector", "type": "Collection(Edm.Single)", "searchable": True,
             "dimensions": VECTOR_DIM, "vectorSearchProfile": "qwen3-profile"},
        ],
        "vectorSearch": {
            "algorithms": [{"name": "hnsw-algo", "kind": "hnsw",
                            "hnswParameters": {"m": 4, "efConstruction": 400, "efSearch": 500, "metric": "cosine"}}],
            "profiles": [{"name": "qwen3-profile", "algorithm": "hnsw-algo"}],
        },
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Embedding Benchmark (AKS)")
    parser.add_argument("mode", choices=["bench-concurrency", "push", "indexer", "compare"])
    parser.add_argument("--max-docs", type=int, default=int(os.environ.get("MAX_DOCS", "0")))
    parser.add_argument("--embed-batch", type=int, default=int(os.environ.get("EMBED_BATCH", "16")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", "20")))
    parser.add_argument("--indexer-batch", type=int, default=int(os.environ.get("INDEXER_BATCH", "10")))
    parser.add_argument("--indexer-parallel", type=int, default=int(os.environ.get("INDEXER_PARALLEL", "10")))
    parser.add_argument("--bench-docs", type=int, default=int(os.environ.get("BENCH_DOCS", "50")))
    args = parser.parse_args()

    blob_svc = get_blob_svc()

    if args.mode == "bench-concurrency":
        await bench_concurrency(blob_svc, num_docs=args.bench_docs)
    elif args.mode == "push":
        await run_push(blob_svc, args.max_docs, args.embed_batch, args.concurrency)
    elif args.mode == "indexer":
        await run_indexer(blob_svc, args.indexer_batch, args.indexer_parallel)
    elif args.mode == "compare":
        compare_results(blob_svc)


if __name__ == "__main__":
    asyncio.run(main())
