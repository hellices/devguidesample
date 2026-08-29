#!/usr/bin/env python3
"""
SCAN 커서 + 파이프라인 기반 프로그래매틱 마이그레이션.

이전 테스트 스크립트의 세 가지 결함을 고친 버전이다.

1. KEYS * -> SCAN
   KEYS는 O(N) 블로킹 명령이라 수백만 키 인스턴스에서 서버를 멈춘다.
   SCAN은 커서로 조금씩 훑으므로 운영 중에도 안전하다.

2. 타입별 일괄 읽기 -> DUMP/RESTORE
   HGETALL은 큰 해시를 클라이언트 메모리에 통째로 올린다. DUMP는 직렬화된
   페이로드를 그대로 옮기므로 타입에 무관하고 메모리도 덜 쓴다.

3. TTL 유실 -> PTTL 보존
   TTL을 안 옮기면 세션 키가 영구 키가 된다. 조용히 발생하는 데이터 손상이라
   키 개수만 비교하는 검증으로는 잡히지 않는다.

사용법:
    export SRC_REDIS_PASSWORD='<key>' DST_REDIS_PASSWORD='<key>'
    python3 migrate_scan_copy.py --src-host ... --dst-host ... --report out.json
"""

import argparse
import getpass
import json
import os
import sys
import time

import redis

SCAN_COUNT = 1_000
PIPELINE_SIZE = 500


def resolve_password(value, env):
    """비밀번호를 명령행 인자로 받으면 셸 히스토리와 ps 출력에 그대로 남는다."""
    return value or os.environ.get(env) or getpass.getpass(f"{env}: ")


def connect(host, port, password):
    return redis.StrictRedis(
        host=host,
        port=port,
        password=password,
        ssl=True,
        ssl_cert_reqs="required",
        socket_timeout=120,
        socket_connect_timeout=30,
    )


def migrate(src, dst, report_every=10.0):
    stats = {
        "keys_scanned": 0,
        "keys_restored": 0,
        "keys_with_ttl": 0,
        "restore_errors": 0,
        "error_samples": [],
    }

    start = time.time()
    last_report = start
    cursor = 0

    while True:
        cursor, keys = src.scan(cursor=cursor, count=SCAN_COUNT)
        if keys:
            # 소스에서 페이로드와 TTL을 한 번의 왕복으로 함께 가져온다.
            read_pipe = src.pipeline(transaction=False)
            for key in keys:
                read_pipe.dump(key)
                read_pipe.pttl(key)
            raw = read_pipe.execute()

            write_pipe = dst.pipeline(transaction=False)
            staged = []
            for i, key in enumerate(keys):
                payload = raw[i * 2]
                pttl = raw[i * 2 + 1]
                if payload is None:
                    # SCAN과 DUMP 사이에 만료된 키. 유실이 아니라 정상 동작.
                    continue
                # pttl이 음수면 TTL 없음(-1) 또는 키 없음(-2). RESTORE는 0을 무기한으로 본다.
                ttl_ms = pttl if pttl and pttl > 0 else 0
                if ttl_ms:
                    stats["keys_with_ttl"] += 1
                write_pipe.restore(key, ttl_ms, payload, replace=True)
                staged.append(key)

            if staged:
                results = write_pipe.execute(raise_on_error=False)
                for key, result in zip(staged, results):
                    if isinstance(result, Exception):
                        stats["restore_errors"] += 1
                        if len(stats["error_samples"]) < 5:
                            stats["error_samples"].append(
                                {"key": key.decode(errors="replace") if isinstance(key, bytes) else str(key),
                                 "error": str(result)}
                            )
                    else:
                        stats["keys_restored"] += 1

            stats["keys_scanned"] += len(keys)

        now = time.time()
        if now - last_report >= report_every:
            elapsed = now - start
            rate = stats["keys_scanned"] / elapsed if elapsed else 0
            print(
                f"[{elapsed:7.1f}s] scanned={stats['keys_scanned']:,} "
                f"restored={stats['keys_restored']:,} errors={stats['restore_errors']:,} "
                f"{rate:,.0f} keys/s",
                flush=True,
            )
            last_report = now

        if cursor == 0:
            break

    stats["duration_sec"] = time.time() - start
    stats["started_at_ms"] = int(start * 1000)
    stats["ended_at_ms"] = int(time.time() * 1000)
    return stats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src-host", required=True)
    p.add_argument("--src-port", type=int, default=6380)
    p.add_argument("--src-password", help="생략하면 SRC_REDIS_PASSWORD 환경 변수")
    p.add_argument("--dst-host", required=True)
    p.add_argument("--dst-port", type=int, default=10000)
    p.add_argument("--dst-password", help="생략하면 DST_REDIS_PASSWORD 환경 변수")
    p.add_argument("--flush-target", action="store_true",
                   help="복사 전 타깃을 비운다. 소스는 절대 건드리지 않는다.")
    p.add_argument("--report", help="결과 JSON 경로")
    args = p.parse_args()

    args.src_password = resolve_password(args.src_password, "SRC_REDIS_PASSWORD")
    args.dst_password = resolve_password(args.dst_password, "DST_REDIS_PASSWORD")

    src = connect(args.src_host, args.src_port, args.src_password)
    dst = connect(args.dst_host, args.dst_port, args.dst_password)

    src_info = src.info("memory")
    print(f"소스 : {args.src_host} keys={src.dbsize():,} mem={src_info['used_memory_human']}", flush=True)
    print(f"타깃 : {args.dst_host} keys={dst.dbsize():,}", flush=True)

    if args.flush_target:
        dst.flushall()
        print("타깃 flush 완료", flush=True)

    print("\n[복사 시작]", flush=True)
    stats = migrate(src, dst)

    stats["src_dbsize_after"] = src.dbsize()
    stats["dst_dbsize_after"] = dst.dbsize()

    print("\n=== 복사 완료 ===", flush=True)
    print(f"소요 시간   : {stats['duration_sec']:.1f}s", flush=True)
    print(f"스캔한 키   : {stats['keys_scanned']:,}", flush=True)
    print(f"복원한 키   : {stats['keys_restored']:,}", flush=True)
    print(f"TTL 보존    : {stats['keys_with_ttl']:,}", flush=True)
    print(f"복원 오류   : {stats['restore_errors']:,}", flush=True)
    if stats["error_samples"]:
        print(f"오류 샘플   : {json.dumps(stats['error_samples'], ensure_ascii=False)}", flush=True)
    print(f"소스 키 수  : {stats['src_dbsize_after']:,}", flush=True)
    print(f"타깃 키 수  : {stats['dst_dbsize_after']:,}", flush=True)

    if args.report:
        with open(args.report, "w") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {args.report}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
