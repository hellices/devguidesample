"""Embedding API for Azure AI Search Custom Web API Skill.

Exposes:
- POST /api/embed  — vectorization (Custom Web API Skill contract)
- POST /api/chunk  — text chunking  (Custom Web API Skill contract)

Supports any sentence-transformers compatible model via EMBEDDING_MODEL env var.
"""

import logging
import os
import re
import time

from fastapi import FastAPI, Request
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

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


def _split_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by sentence boundaries.

    Splits on sentence-ending punctuation, then greedily packs sentences
    into chunks up to chunk_size characters with overlap characters of
    trailing context carried over to the next chunk.
    Falls back to word-boundary splitting for text without punctuation.
    """
    if not text or not text.strip():
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    # If no sentence split occurred (no punctuation), fall back to word boundaries
    if len(sentences) == 1 and len(sentences[0]) > chunk_size:
        words = sentences[0].split()
        sentences = []
        current = ""
        for w in words:
            if current and len(current) + len(w) + 1 > chunk_size:
                sentences.append(current)
                current = w
            else:
                current = f"{current} {w}".strip() if current else w
        if current:
            sentences.append(current)

    chunks: list[str] = []
    current = ""

    for sent in sentences:
        if current and len(current) + len(sent) + 1 > chunk_size:
            chunks.append(current)
            # overlap: keep tail of current chunk, snap to word boundary
            if overlap > 0:
                tail = current[-overlap:]
                word_boundary = tail.find(" ")
                if word_boundary != -1:
                    tail = tail[word_boundary + 1:]
                current = tail + " " + sent
            else:
                current = sent
        else:
            current = f"{current} {sent}".strip() if current else sent

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


@app.post("/api/chunk")
def chunk(req: SkillRequest):
    """Custom Web API Skill contract endpoint for text chunking.

    Input  data field: {"text": "...", "chunkSize": 500, "overlap": 100}
    Output data field: {"chunks": ["chunk1", "chunk2", ...]}

    chunkSize and overlap are optional overrides for env defaults.
    """
    results = []
    for v in req.values:
        text = v.data.get("text", "")
        size = v.data.get("chunkSize", CHUNK_SIZE)
        ovlp = v.data.get("overlap", CHUNK_OVERLAP)
        chunks = _split_text(text, chunk_size=size, overlap=ovlp)
        results.append({
            "recordId": v.recordId,
            "data": {"chunks": chunks},
            "errors": None,
            "warnings": None,
        })
    return {"values": results}


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
