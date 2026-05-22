"""Adapter for Azure AI Search Custom Vectorizer ↔ vLLM.

Translates between AI Search's Custom Web API contract and vLLM's /v1/embeddings endpoint.
Used only at query time (Custom Vectorizer). Push Pipeline calls vLLM directly.
"""

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8081")
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3-Embedding-4B")

app = FastAPI(title="vLLM Adapter for AI Search")
client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(base_url=VLLM_URL, timeout=60.0)


@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.aclose()


class SkillInput(BaseModel):
    recordId: str
    data: dict


class SkillRequest(BaseModel):
    values: list[SkillInput]


@app.get("/health")
async def health():
    try:
        r = await client.get("/health")
        return {"status": "ok", "vllm_status": r.status_code}
    except httpx.ConnectError:
        return {"status": "degraded", "vllm_status": "unreachable"}


@app.post("/api/embed")
async def embed(req: SkillRequest):
    """Custom Vectorizer contract → vLLM /v1/embeddings → Custom Web API response."""
    texts = [v.data.get("text", "") for v in req.values]

    r = await client.post(
        "/v1/embeddings",
        json={"model": MODEL_NAME, "input": texts},
    )
    r.raise_for_status()
    embeddings = sorted(r.json()["data"], key=lambda x: x["index"])

    return {"values": [
        {"recordId": v.recordId, "data": {"vector": e["embedding"]}, "errors": None, "warnings": None}
        for v, e in zip(req.values, embeddings)
    ]}
