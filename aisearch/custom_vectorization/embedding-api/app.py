"""Embedding API for Azure AI Search Custom Web API Skill.

Exposes a POST /api/embed endpoint that conforms to the
Azure AI Search Custom Web API skill contract.
Supports any sentence-transformers compatible model via EMBEDDING_MODEL env var.
"""

import logging
import os
import time

from fastapi import FastAPI, Request
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

app = FastAPI(title=f"Embedding API ({MODEL_NAME})")
model: SentenceTransformer | None = None


@app.on_event("startup")
def load_model():
    global model
    logger.info("Loading model %s ...", MODEL_NAME)
    t0 = time.time()
    model = SentenceTransformer(MODEL_NAME, trust_remote_code=True)
    logger.info("Model loaded in %.1fs  (dim=%d)", time.time() - t0, model.get_sentence_embedding_dimension())


class SkillInput(BaseModel):
    recordId: str
    data: dict


class SkillRequest(BaseModel):
    values: list[SkillInput]


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/api/embed")
def embed(req: SkillRequest):
    """Custom Web API Skill contract endpoint.

    Input  data field: {"text": "..."}
    Output data field: {"vector": [...]}
    """
    texts = []
    for v in req.values:
        texts.append(v.data.get("text", ""))

    vectors = model.encode(texts, normalize_embeddings=True).tolist()

    results = []
    for v, vec in zip(req.values, vectors):
        results.append({
            "recordId": v.recordId,
            "data": {"vector": vec},
            "errors": None,
            "warnings": None,
        })

    return {"values": results}
