"""Adapter for reranking — TEI /rerank → AI Search compatible response."""

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

TEI_URL = os.getenv("TEI_URL", "http://localhost:8080")

app = FastAPI(title="Reranker Adapter")
client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(base_url=TEI_URL, timeout=60.0)


@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.aclose()


class RerankRequest(BaseModel):
    query: str
    documents: list[str]


@app.get("/health")
async def health():
    try:
        r = await client.get("/health")
        return {"status": "ok", "tei_status": r.status_code}
    except httpx.ConnectError:
        return {"status": "degraded", "tei_status": "unreachable"}


@app.post("/api/rerank")
async def rerank(req: RerankRequest):
    """Rerank documents using TEI cross-encoder."""
    r = await client.post(
        "/rerank",
        json={
            "query": req.query,
            "texts": req.documents,
            "return_text": False,
        },
    )
    r.raise_for_status()
    results = r.json()
    return {"results": [{"index": item["index"], "score": item["score"]} for item in results]}
