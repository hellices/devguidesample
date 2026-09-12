"""memray-leak-profiling demo — 의도적인 메모리 누수를 가진 가짜 LLM agent 서비스.

/chat 요청마다 "plan → tool 호출 → 답변 합성" 파이프라인을 흉내 낸다.
이때 모듈 전역 저장소 2곳이 요청마다 계속 자라기만 하고 절대 비워지지 않는다
(세션별 컨텍스트 스냅샷 + 전역 툴 트레이스 아카이브).
운영에서 흔한 "무한 캐시" 누수 패턴이며, 이 데모의 memray 프로파일링 대상이다.

누수 지점이 플레임그래프에서 잘 보이도록 할당 함수를 분리해 두었다:
  - _remember_turn_context()  : 턴당 ~100KB 를 영구 보관 (누수 1)
  - _archive_tool_trace()     : 툴 호출당 ~16KB 를 영구 보관 (누수 2)
  - _synthesize_answer()      : 임시 할당 후 해제되는 정상 코드 (대조군)
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

CONTEXT_CHUNKS = int(os.getenv("LEAK_CONTEXT_CHUNKS", "48"))
CONTEXT_CHUNK_CHARS = int(os.getenv("LEAK_CONTEXT_CHUNK_CHARS", "2048"))
TOOL_PAYLOAD_CHARS = int(os.getenv("LEAK_TOOL_PAYLOAD_CHARS", "16384"))

app = FastAPI(title="leaky-agent", version="1.0.0")

# ---------------------------------------------------------------------------
# THE LEAK: 요청마다 append 되지만 어디서도 만료/축출되지 않는 전역 저장소.
# ---------------------------------------------------------------------------
_SESSION_MEMORY: dict[str, list[dict[str, Any]]] = {}
_TOOL_TRACE_ARCHIVE: list[dict[str, Any]] = []


class ChatRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    message: str = "hello"


def _random_text(chars: int) -> str:
    # 매 호출 고유한 문자열을 싸게 만든다 (interning 방지 + CPU 절약)
    return os.urandom((chars + 1) // 2).hex()[:chars]


def _remember_turn_context(session_id: str, message: str) -> dict[str, Any]:
    """턴 컨텍스트 스냅샷(~100KB)을 만들어 세션 메모리에 '영구' 보관한다."""
    chunks = [
        f"[ctx:{session_id}:{i}] " + _random_text(CONTEXT_CHUNK_CHARS)
        for i in range(CONTEXT_CHUNKS)
    ]
    entry = {
        "turn": len(_SESSION_MEMORY.get(session_id, [])),
        "message": message,
        "context_snapshot": chunks,
        "ts": time.time(),
    }
    _SESSION_MEMORY.setdefault(session_id, []).append(entry)
    return entry


def _archive_tool_trace(session_id: str, tool: str) -> str:
    """가짜 툴을 호출하고 전체 응답 페이로드(~16KB)를 전역 아카이브에 보관한다."""
    payload = _random_text(TOOL_PAYLOAD_CHARS)
    _TOOL_TRACE_ARCHIVE.append(
        {
            "session_id": session_id,
            "tool": tool,
            "payload": payload,
            "ts": time.time(),
        }
    )
    return payload[:64]  # agent 가 실제로 쓰는 건 앞부분 요약뿐


def _synthesize_answer(message: str, tool_previews: list[str]) -> str:
    """정상 코드(대조군): 임시 할당은 요청이 끝나면 모두 해제된다."""
    scratch = [_random_text(1024) for _ in range(32)]
    digest = f"{len(scratch)} scratch notes considered"
    return f"agent> re: {message[:40]!r} | tools={len(tool_previews)} | {digest}"


@app.post("/chat")
def chat(req: ChatRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    entry = _remember_turn_context(req.session_id, req.message)
    previews = [
        _archive_tool_trace(req.session_id, tool)
        for tool in ("web_search", "doc_summarize")
    ]
    time.sleep(0.01)  # LLM 이 생각하는 척
    answer = _synthesize_answer(req.message, previews)
    return {
        "session_id": req.session_id,
        "turn": entry["turn"],
        "answer": answer,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
    }


def _rss_mb() -> float:
    try:
        with open("/proc/self/status") as f:  # Linux (파드 안)
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except FileNotFoundError:  # macOS 로컬 실행
        import resource

        return round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 1
        )
    return -1.0


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict[str, Any]:
    history_entries = sum(len(v) for v in _SESSION_MEMORY.values())
    return {
        "rss_mb": _rss_mb(),
        "sessions": len(_SESSION_MEMORY),
        "history_entries": history_entries,
        "tool_traces": len(_TOOL_TRACE_ARCHIVE),
    }
