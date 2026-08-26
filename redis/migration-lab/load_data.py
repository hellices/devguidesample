#!/usr/bin/env python3
"""
GB 규모 테스트 데이터 로더.

Azure Cache for Redis에 현실적인 캐시 워크로드를 적재한다. 값 크기와 타입을
섞는 이유는 두 가지다.

1. RDB 압축률이 현실적이어야 export 시간과 blob 크기가 의미를 가진다.
   전부 난수면 압축이 안 되고, 전부 JSON이면 과하게 압축된다.
2. 큰 컬렉션이 있어야 HGETALL 류의 일괄 읽기가 실제로 터지는지 확인할 수 있다.

사용법:
    python3 load_data.py --host <host> --port 6380 --password <key> --target-gb 4
"""

import argparse
import json
import os
import random
import string
import sys
import time
from multiprocessing import Process, Queue

import redis

# 큰 해시의 필드 수. HGETALL로 한 번에 읽으면 클라이언트 메모리가 튀는 크기.
BIG_HASH_FIELDS = 100_000
BIG_HASH_COUNT = 50

PIPELINE_BATCH = 1_000

# TTL을 거는 문자열 키의 비율. 세션·토큰 캐시를 흉내낸 값으로, 마이그레이션이
# TTL을 보존하는지 검증하는 데 쓴다.
TTL_FRACTION = 0.30


def connect(args):
    return redis.StrictRedis(
        host=args.host,
        port=args.port,
        password=args.password,
        ssl=True,
        ssl_cert_reqs="none",
        socket_timeout=60,
        socket_connect_timeout=30,
    )


def compressible_value(size):
    """JSON 형태의 압축 가능한 값. 실제 캐시 페이로드에 가깝다."""
    payload = {
        "id": random.randint(1, 10**9),
        "name": "user_" + "".join(random.choices(string.ascii_lowercase, k=8)),
        "email": "".join(random.choices(string.ascii_lowercase, k=12)) + "@example.com",
        "tags": ["premium", "kr", "active"],
        "note": "x" * max(0, size - 200),
    }
    return json.dumps(payload)


def incompressible_value(size):
    """난수 바이트. 직렬화된 바이너리 캐시 엔트리를 흉내낸다."""
    return os.urandom(size // 2).hex()


def make_value(size):
    # 캐시 페이로드는 보통 구조화된 텍스트가 많으므로 압축 가능한 쪽에 가중치를 둔다.
    return compressible_value(size) if random.random() < 0.7 else incompressible_value(size)


def load_strings(args, worker_id, count, progress):
    r = connect(args)
    pipe = r.pipeline(transaction=False)
    written = 0
    for i in range(count):
        key = f"cache:string:{worker_id}:{i}"
        value = make_value(random.randint(500, 1500))
        # 실제 캐시는 상당수 키에 TTL이 걸려 있다. TTL이 있는 키를 섞어야
        # 마이그레이션이 TTL을 보존하는지 검증할 수 있다. TTL을 잃으면 키 개수
        # 비교는 통과하면서 만료 예정 키가 영구 키로 남는다.
        if random.random() < TTL_FRACTION:
            pipe.set(key, value, ex=random.randint(3_600, 86_400))
        else:
            pipe.set(key, value)
        if (i + 1) % PIPELINE_BATCH == 0:
            pipe.execute()
            written += PIPELINE_BATCH
            progress.put(("string", PIPELINE_BATCH))
    if count % PIPELINE_BATCH:
        pipe.execute()
        progress.put(("string", count % PIPELINE_BATCH))


def load_hashes(args, worker_id, count, progress):
    r = connect(args)
    pipe = r.pipeline(transaction=False)
    for i in range(count):
        key = f"cache:hash:{worker_id}:{i}"
        mapping = {f"f{j}": make_value(100) for j in range(10)}
        pipe.hset(key, mapping=mapping)
        if (i + 1) % PIPELINE_BATCH == 0:
            pipe.execute()
            progress.put(("hash", PIPELINE_BATCH))
    if count % PIPELINE_BATCH:
        pipe.execute()
        progress.put(("hash", count % PIPELINE_BATCH))


def load_lists(args, worker_id, count, progress):
    r = connect(args)
    pipe = r.pipeline(transaction=False)
    for i in range(count):
        key = f"cache:list:{worker_id}:{i}"
        pipe.rpush(key, *[make_value(100) for _ in range(20)])
        if (i + 1) % 200 == 0:
            pipe.execute()
            progress.put(("list", 200))
    pipe.execute()
    progress.put(("list", count % 200))


def load_zsets(args, worker_id, count, progress):
    r = connect(args)
    pipe = r.pipeline(transaction=False)
    for i in range(count):
        key = f"cache:zset:{worker_id}:{i}"
        pipe.zadd(key, {f"member{j}": random.random() * 1000 for j in range(30)})
        if (i + 1) % 200 == 0:
            pipe.execute()
            progress.put(("zset", 200))
    pipe.execute()
    progress.put(("zset", count % 200))


def load_big_hashes(args, progress):
    """일괄 읽기가 위험한 큰 해시. 마이그레이션 스크립트의 청크 처리를 강제한다."""
    r = connect(args)
    for i in range(BIG_HASH_COUNT):
        key = f"cache:bighash:{i}"
        for chunk_start in range(0, BIG_HASH_FIELDS, 5_000):
            mapping = {
                f"f{j}": make_value(100)
                for j in range(chunk_start, min(chunk_start + 5_000, BIG_HASH_FIELDS))
            }
            r.hset(key, mapping=mapping)
        progress.put(("bighash", 1))


def reporter(progress, total_expected):
    counts = {}
    done = 0
    start = time.time()
    last_print = 0
    while True:
        item = progress.get()
        if item is None:
            break
        kind, n = item
        counts[kind] = counts.get(kind, 0) + n
        done += n
        now = time.time()
        if now - last_print > 5:
            elapsed = now - start
            rate = done / elapsed if elapsed else 0
            pct = 100 * done / total_expected if total_expected else 0
            print(
                f"[{elapsed:6.0f}s] {done:,}/{total_expected:,} ({pct:5.1f}%) "
                f"{rate:,.0f} items/s  {counts}",
                flush=True,
            )
            last_print = now


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=6380)
    p.add_argument("--password", required=True)
    p.add_argument("--target-gb", type=float, default=4.0)
    p.add_argument("--workers", type=int, default=8)
    args = p.parse_args()

    r = connect(args)
    r.ping()
    print(f"연결 성공: {args.host}:{args.port}", flush=True)

    # 목표 용량을 타입별 키 개수로 환산한다. 문자열이 대부분의 용량을 차지하고
    # 나머지 타입은 마이그레이션 로직의 타입 처리를 검증하는 용도로 섞는다.
    target_bytes = args.target_gb * 1024**3
    string_bytes = target_bytes * 0.60
    string_count = int(string_bytes / 1100)   # 평균 값 1KB + 키/오버헤드
    hash_count = int(target_bytes * 0.15 / 1200)
    list_count = int(target_bytes * 0.10 / 2200)
    zset_count = int(target_bytes * 0.10 / 2000)

    total = string_count + hash_count + list_count + zset_count + BIG_HASH_COUNT
    print(
        f"계획: strings={string_count:,} hashes={hash_count:,} "
        f"lists={list_count:,} zsets={zset_count:,} bighash={BIG_HASH_COUNT} "
        f"(총 {total:,} 키, 목표 {args.target_gb}GB)",
        flush=True,
    )

    progress = Queue()
    rep = Process(target=reporter, args=(progress, total))
    rep.start()

    start = time.time()
    procs = []
    for w in range(args.workers):
        procs.append(Process(target=load_strings, args=(args, w, string_count // args.workers, progress)))
        procs.append(Process(target=load_hashes, args=(args, w, hash_count // args.workers, progress)))
        procs.append(Process(target=load_lists, args=(args, w, list_count // args.workers, progress)))
        procs.append(Process(target=load_zsets, args=(args, w, zset_count // args.workers, progress)))
    procs.append(Process(target=load_big_hashes, args=(args, progress)))

    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join()

    progress.put(None)
    rep.join()

    elapsed = time.time() - start
    info = r.info("memory")
    dbsize = r.dbsize()
    print("\n=== 적재 완료 ===", flush=True)
    print(f"소요 시간   : {elapsed:.1f}s", flush=True)
    print(f"키 개수     : {dbsize:,}", flush=True)
    print(f"used_memory : {info['used_memory_human']}", flush=True)
    print(f"평균 처리량 : {dbsize / elapsed:,.0f} keys/s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
