"""
AI Foundry Chat API with Pyroscope Profiling
FastAPI app that calls Azure AI Foundry and emits profiles to Pyroscope.
"""

import os
import logging
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# Pyroscope profiling (pyroscope-io)
import pyroscope

# Azure AI Foundry
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
from azure.core.credentials import AzureKeyCredential

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pyroscope — initialize once at module load
# NOTE: pyroscope-io (Python SDK) collects CPU/wall-clock profiles ONLY.
#       Memory/heap profiling is not supported. For Python memory use memray.
# ─────────────────────────────────────────────────────────────────────────────
PYROSCOPE_SERVER = os.getenv(
    "PYROSCOPE_SERVER",
    "http://pyroscope.observability.svc.cluster.local.:4040",
)

pyroscope.configure(
    application_name="ai-foundry-chat",
    server_address=PYROSCOPE_SERVER,
    sample_rate=100,
    tags={
        "service": "ai-foundry-chat",
        "env": "aks",
    },
)
logger.info(f"Pyroscope configured: {PYROSCOPE_SERVER}")

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Foundry Chat + Pyroscope Profiling",
    version="1.0.0",
)

# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str   # "system" | "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    max_tokens: int = 500
    temperature: float = 0.7
    model: Optional[str] = None

class ChatResponse(BaseModel):
    role: str
    content: str
    tokens_used: Optional[int] = None
    latency_ms: float
    mock: bool = False

# ─────────────────────────────────────────────────────────────────────────────
# AI Foundry client (lazy init)
# ─────────────────────────────────────────────────────────────────────────────
_chat_client: Optional[ChatCompletionsClient] = None

def get_chat_client() -> Optional[ChatCompletionsClient]:
    global _chat_client
    if _chat_client is not None:
        return _chat_client

    endpoint = os.getenv("AI_FOUNDRY_ENDPOINT", "").strip()
    api_key  = os.getenv("AI_FOUNDRY_API_KEY", "").strip()

    if not endpoint or not api_key:
        logger.warning("AI_FOUNDRY_ENDPOINT / AI_FOUNDRY_API_KEY not set → mock mode")
        return None

    _chat_client = ChatCompletionsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
    )
    logger.info(f"AI Foundry client ready: {endpoint}")
    return _chat_client


def _to_ai_messages(messages: list[ChatMessage]):
    result = []
    for m in messages:
        if m.role == "system":
            result.append(SystemMessage(content=m.content))
        elif m.role == "assistant":
            result.append(AssistantMessage(content=m.content))
        else:
            result.append(UserMessage(content=m.content))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-foundry-chat", "pyroscope": PYROSCOPE_SERVER}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Single-turn chat. Uses real AI Foundry if configured, else mock."""
    t0 = time.perf_counter()

    client = get_chat_client()
    if client is None:
        last = req.messages[-1].content
        content = f"[MOCK] You said: {last}"
        latency = (time.perf_counter() - t0) * 1000
        return ChatResponse(role="assistant", content=content,
                            tokens_used=None, latency_ms=latency, mock=True)

    try:
        kwargs: dict = dict(
            messages=_to_ai_messages(req.messages),
            max_tokens=req.max_tokens,
            temperature=req.temperature,
        )
        if req.model:
            kwargs["model"] = req.model

        response = client.complete(**kwargs)
        content     = response.choices[0].message.content
        tokens_used = getattr(response.usage, "completion_tokens", None)
        latency     = (time.perf_counter() - t0) * 1000

        logger.info(f"AI Foundry: {len(content)} chars, {tokens_used} tokens, {latency:.1f}ms")
        return ChatResponse(role="assistant", content=content,
                            tokens_used=tokens_used, latency_ms=latency)

    except Exception as exc:
        logger.exception("AI Foundry call failed")
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/status")
def status():
    has_client = get_chat_client() is not None
    return {
        "ai_foundry": "connected" if has_client else "mock_mode",
        "pyroscope_server": PYROSCOPE_SERVER,
        "profiling": "enabled",
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
