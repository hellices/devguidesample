"""Adapter for Azure AI Search Custom Web API Skill ↔ TEI (Text Embeddings Inference).

Translates between AI Search's Custom Web API Skill contract and TEI's /embed endpoint.
No model loading — all inference is delegated to TEI.
"""

import os

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

TEI_URL = os.getenv("TEI_URL", "http://tei-bge-m3")

app = FastAPI(title="TEI Adapter for AI Search")
client: httpx.AsyncClient | None = None


@app.on_event("startup")
async def startup():
    global client
    client = httpx.AsyncClient(base_url=TEI_URL, timeout=60.0)


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
        return {"status": "ok", "tei_status": r.status_code}
    except httpx.ConnectError:
        return {"status": "degraded", "tei_status": "unreachable"}


@app.post("/api/embed")
async def embed(req: SkillRequest):
    """Custom Web API Skill contract → TEI /embed → Custom Web API response."""
    texts = [v.data.get("text", "") for v in req.values]

    r = await client.post("/embed", json={"inputs": texts, "normalize": True})
    r.raise_for_status()
    vectors = r.json()

    return {"values": [
        {"recordId": v.recordId, "data": {"vector": vec}, "errors": None, "warnings": None}
        for v, vec in zip(req.values, vectors)
    ]}
