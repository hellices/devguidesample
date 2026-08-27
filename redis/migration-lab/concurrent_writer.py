#!/usr/bin/env python3
"""
마이그레이션 중 소스에 계속 쓰기를 넣는 부하 생성기 겸 계측기.

마이그레이션 방식의 진짜 비용은 "복사에 몇 초 걸리나"가 아니라 "복사하는 동안
들어온 쓰기를 잃는가"다. 스냅샷(RDB) 방식과 복사 루프 방식은 둘 다 시작 시점
이후의 쓰기를 놓치는데, 소규모 테스트에서는 복사가 순식간에 끝나서 이 구간이
보이지 않는다. GB 규모에서는 이 구간이 수 분이 된다.

각 프로브 키를 로컬 로그에 남겨두고, 마이그레이션 후 타깃에서 몇 개가
사라졌는지 세면 유실량이 그대로 나온다.

사용법:
    export REDIS_PASSWORD='<key>'
    python3 concurrent_writer.py --host ... --rate 200 --log probes.jsonl
    # 중단: --stop-file 경로에 파일 생성
"""

import argparse
import getpass
import json
import os
import signal
import sys
import time

import redis

_stop = False


def resolve_password(value, env):
    """비밀번호를 명령행 인자로 받으면 셸 히스토리와 ps 출력에 그대로 남는다."""
    return value or os.environ.get(env) or getpass.getpass(f"{env}: ")


def _handle_stop(signum, frame):
    global _stop
    _stop = True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", required=True)
    p.add_argument("--port", type=int, default=6380)
    p.add_argument("--password", help="생략하면 REDIS_PASSWORD 환경 변수, 그것도 없으면 프롬프트")
    p.add_argument("--rate", type=int, default=200, help="초당 쓰기 수")
    p.add_argument("--log", required=True, help="프로브 기록 경로 (jsonl)")
    p.add_argument("--prefix", default="probe",
                   help="프로브 키 접두사. 실행마다 고유값을 주면 이전 실행의 "
                        "잔여 키와 섞이지 않아 유실 측정이 오염되지 않는다.")
    p.add_argument("--stop-file", default="/tmp/writer.stop")
    p.add_argument("--max-seconds", type=int, default=7200)
    args = p.parse_args()

    args.password = resolve_password(args.password, "REDIS_PASSWORD")

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    r = redis.StrictRedis(
        host=args.host,
        port=args.port,
        password=args.password,
        ssl=True,
        ssl_cert_reqs="required",
        socket_timeout=30,
    )
    r.ping()

    if os.path.exists(args.stop_file):
        os.remove(args.stop_file)

    interval = 1.0 / args.rate
    seq = 0
    start = time.time()
    log = open(args.log, "w", buffering=1)

    print(f"쓰기 시작: {args.rate}/s -> {args.host} (접두사 {args.prefix}:)", flush=True)

    while not _stop:
        if os.path.exists(args.stop_file):
            break
        if time.time() - start > args.max_seconds:
            break

        now_ms = int(time.time() * 1000)
        key = f"{args.prefix}:{seq}"
        try:
            r.set(key, str(now_ms))
            log.write(json.dumps({"seq": seq, "key": key, "written_at_ms": now_ms}) + "\n")
            seq += 1
        except Exception as e:
            log.write(json.dumps({"seq": seq, "key": key, "error": str(e)}) + "\n")
            seq += 1

        if seq % (args.rate * 10) == 0:
            elapsed = time.time() - start
            print(f"[{elapsed:6.0f}s] {seq:,} 프로브 기록", flush=True)

        time.sleep(interval)

    log.close()
    elapsed = time.time() - start
    print(f"\n쓰기 종료: {seq:,} 프로브, {elapsed:.1f}s", flush=True)
    print(f"로그: {args.log}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
