#!/usr/bin/env python3
"""
Test script for AI Foundry Chat API with Pyroscope profiling.
Makes multiple concurrent chat requests to generate profiling load.
"""

import asyncio
import aiohttp
import time
import logging
import argparse
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

QUESTIONS = [
    "안녕하세요, 오늘 날씨가 어떤가요?",
    "파이썬 프로그래밍에 대해 설명해주세요.",
    "클라우드 컴퓨팅의 장점은?",
    "머신러닝과 딥러닝의 차이는?",
    "마이크로서비스 아키텍처란?",
    "Kubernetes를 사용하는 이유는?",
    "FastAPI의 특징을 설명해줘.",
    "프로파일링이란 무엇인가요?",
    "Azure NetApp Files의 용도는?",
    "AI Foundry란 무엇인가요?",
]


async def health_check(session: aiohttp.ClientSession, base_url: str) -> bool:
    try:
        async with session.get(f"{base_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status == 200:
                data = await r.json()
                logger.info(f"Health OK: {data}")
                return True
    except Exception as e:
        logger.error(f"Health check failed: {e}")
    return False


async def single_chat(
    session: aiohttp.ClientSession,
    base_url: str,
    message: str,
    idx: int,
) -> dict:
    payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
            {"role": "user", "content": message},
        ],
        "max_tokens": 200,
        "temperature": 0.7,
    }

    t0 = time.perf_counter()
    try:
        async with session.post(
            f"{base_url}/chat",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as r:
            data = await r.json()
            elapsed = (time.perf_counter() - t0) * 1000
            mock = data.get("mock", False)
            preview = data.get("content", "")[:60]
            logger.info(
                f"[{idx:02d}] {'MOCK' if mock else 'REAL'} "
                f"{elapsed:.0f}ms | {preview}..."
            )
            return {"ok": r.status == 200, "latency_ms": elapsed, "mock": mock}
    except Exception as e:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.error(f"[{idx:02d}] ERROR {e}")
        return {"ok": False, "latency_ms": elapsed, "mock": None}


async def run(base_url: str, n: int):
    async with aiohttp.ClientSession() as session:
        if not await health_check(session, base_url):
            logger.error("API not healthy — aborting")
            return

        t_start = time.perf_counter()
        tasks = [
            single_chat(session, base_url, QUESTIONS[i % len(QUESTIONS)], i)
            for i in range(n)
        ]
        results = await asyncio.gather(*tasks)
        total_s = time.perf_counter() - t_start

    ok      = [r for r in results if r["ok"]]
    failed  = [r for r in results if not r["ok"]]
    latencies = [r["latency_ms"] for r in ok]

    print("\n" + "=" * 55)
    print(f"  Requests  : {n}")
    print(f"  Success   : {len(ok)}")
    print(f"  Failed    : {len(failed)}")
    if latencies:
        print(f"  Avg ms    : {sum(latencies)/len(latencies):.1f}")
        print(f"  Min ms    : {min(latencies):.1f}")
        print(f"  Max ms    : {max(latencies):.1f}")
    print(f"  Wall time : {total_s:.2f}s")
    print("=" * 55)
    print("\nProfiles now visible in Pyroscope:")
    print("  kubectl port-forward -n observability svc/pyroscope 4040:4040")
    print("  → http://localhost:4040  (service: ai-foundry-chat)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--requests", type=int, default=10)
    args = parser.parse_args()
    asyncio.run(run(args.url, args.requests))
