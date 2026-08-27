#!/usr/bin/env python3
"""
마이그레이션 결과 검증기.

키 개수만 비교하는 검증은 두 가지를 놓친다.

1. 마이그레이션 중 소스에 들어온 쓰기의 유실
   프로브 로그와 타깃을 대조해서 몇 개가, 어느 시점부터 사라졌는지 센다.

2. TTL 유실
   TTL을 안 옮기면 키는 그대로 있으므로 개수 비교는 통과한다. 하지만 만료
   예정이던 세션 키가 영구 키가 되어 메모리를 잠식한다.

사용법:
    python3 verify_migration.py --src-host ... --dst-host ... --probe-log probes.jsonl
"""

import argparse
import getpass
import json
import os
import sys

import redis

SAMPLE_SIZE = 2_000
CHECK_BATCH = 500


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


def check_probe_loss(dst, probe_log, cutover_ms=None):
    """프로브 로그를 타깃과 대조해 유실 구간을 찾는다."""
    probes = []
    with open(probe_log) as f:
        for line in f:
            rec = json.loads(line)
            if "error" not in rec:
                probes.append(rec)

    if not probes:
        return {"error": "프로브 기록 없음"}

    present = []
    missing = []
    stale = []
    for i in range(0, len(probes), CHECK_BATCH):
        batch = probes[i:i + CHECK_BATCH]
        pipe = dst.pipeline(transaction=False)
        for rec in batch:
            # 존재 여부만 보면 "키는 있는데 값이 옛것"인 경우를 놓친다. 프로브 값은
            # 기록된 쓰기 시각 그 자체라서 값까지 대조하면 정확히 판정할 수 있다.
            pipe.get(rec["key"])
        results = pipe.execute()
        for rec, value in zip(batch, results):
            if value is None:
                missing.append(rec)
            elif value.decode() == str(rec["written_at_ms"]):
                present.append(rec)
            else:
                stale.append(rec)

    out = {
        "probes_written": len(probes),
        "probes_present_in_target": len(present),
        "probes_missing_in_target": len(missing),
        "probes_stale_in_target": len(stale),
        "loss_pct": round(100 * (len(missing) + len(stale)) / len(probes), 2),
        "first_write_ms": probes[0]["written_at_ms"],
        "last_write_ms": probes[-1]["written_at_ms"],
    }

    # 값이 남아 있지만 옛것이라면 이전 실행의 잔여 키이거나 복사 시점 이후의
    # 덮어쓰기다. 어느 쪽이든 유실과 같은 결과이므로 별도로 센다.
    if stale:
        out["stale_samples"] = [
            {"key": r["key"], "expected": r["written_at_ms"]} for r in stale[:5]
        ]

    missing = missing + stale
    if missing:
        missing_sorted = sorted(missing, key=lambda r: r["written_at_ms"])
        out["first_missing_ms"] = missing_sorted[0]["written_at_ms"]
        out["last_missing_ms"] = missing_sorted[-1]["written_at_ms"]
        # 유실이 시작된 시점 = 사실상의 스냅샷 경계
        out["loss_window_sec"] = round(
            (out["last_missing_ms"] - out["first_missing_ms"]) / 1000, 1
        )
        if present:
            last_present = max(r["written_at_ms"] for r in present)
            out["last_present_ms"] = last_present

    return out


def check_ttl_preservation(src, dst, sample_size=SAMPLE_SIZE):
    """소스에서 TTL이 있는 키를 표본으로 뽑아 타깃에도 TTL이 남았는지 본다."""
    sampled = []
    cursor = 0
    scanned = 0
    # 전수 조사는 비싸므로 앞쪽 구간을 훑으며 TTL 보유 키를 모은다.
    while len(sampled) < sample_size and scanned < 200_000:
        cursor, keys = src.scan(cursor=cursor, count=1_000)
        scanned += len(keys)
        if keys:
            pipe = src.pipeline(transaction=False)
            for k in keys:
                pipe.pttl(k)
            ttls = pipe.execute()
            for k, t in zip(keys, ttls):
                if t and t > 0:
                    sampled.append((k, t))
                    if len(sampled) >= sample_size:
                        break
        if cursor == 0:
            break

    if not sampled:
        return {"keys_with_ttl_sampled": 0, "note": "TTL 보유 키를 찾지 못함"}

    preserved = 0
    lost = 0
    pipe = dst.pipeline(transaction=False)
    for k, _ in sampled:
        pipe.pttl(k)
    dst_ttls = pipe.execute()
    for (k, src_ttl), dst_ttl in zip(sampled, dst_ttls):
        # -1 = TTL 없음(영구), -2 = 키 없음
        if dst_ttl and dst_ttl > 0:
            preserved += 1
        else:
            lost += 1

    return {
        "keys_with_ttl_sampled": len(sampled),
        "ttl_preserved": preserved,
        "ttl_lost": lost,
        "ttl_loss_pct": round(100 * lost / len(sampled), 2),
    }


def sample_keys(src, sample_size):
    """키스페이스 전체에서 고르게 표본을 뽑는다.

    SCAN 앞부분만 모으면 먼저 적재된 키에 표본이 쏠린다. 마이그레이션 유실은
    보통 뒤쪽에서 생기므로 그런 표본으로는 문제를 못 잡는다. RANDOMKEY는
    키스페이스 전역에서 뽑으므로 이 편향이 없다.
    """
    keys = set()
    attempts = 0
    max_attempts = sample_size * 5
    while len(keys) < sample_size and attempts < max_attempts:
        pipe = src.pipeline(transaction=False)
        batch = min(CHECK_BATCH, max_attempts - attempts)
        for _ in range(batch):
            pipe.randomkey()
        for k in pipe.execute():
            if k is not None:
                keys.add(k)
        attempts += batch
    return list(keys)


def read_value(conn, keys):
    """타입에 맞는 방식으로 값을 읽어 비교 가능한 형태로 만든다.

    DUMP 바이트 비교는 쓸 수 없다. DUMP 페이로드에는 RDB 버전 푸터가 붙는데
    소스(ACR)와 타깃(AMR)의 Redis 버전이 다르면 값이 같아도 바이트가 달라져
    전부 불일치로 나온다. 그래서 타입별로 실제 값을 읽어 비교한다.

    큰 컬렉션은 전체를 읽으면 클라이언트 메모리가 터지므로 크기만 비교하고
    'sized'로 표시한다.
    """
    tp = conn.pipeline(transaction=False)
    for k in keys:
        tp.type(k)
    types = tp.execute()

    out = {}
    for key, t in zip(keys, types):
        t = t.decode() if isinstance(t, bytes) else t
        try:
            if t == "none":
                out[key] = None
            elif t == "string":
                out[key] = ("string", conn.get(key))
            elif t == "hash":
                n = conn.hlen(key)
                if n > 1_000:
                    out[key] = ("hash", "sized", n)
                else:
                    out[key] = ("hash", tuple(sorted(conn.hgetall(key).items())))
            elif t == "list":
                n = conn.llen(key)
                if n > 1_000:
                    out[key] = ("list", "sized", n)
                else:
                    out[key] = ("list", tuple(conn.lrange(key, 0, -1)))
            elif t == "set":
                n = conn.scard(key)
                if n > 1_000:
                    out[key] = ("set", "sized", n)
                else:
                    out[key] = ("set", tuple(sorted(conn.smembers(key))))
            elif t == "zset":
                n = conn.zcard(key)
                if n > 1_000:
                    out[key] = ("zset", "sized", n)
                else:
                    out[key] = ("zset", tuple(conn.zrange(key, 0, -1, withscores=True)))
            else:
                out[key] = ("unsupported", t)
        except Exception as e:
            out[key] = ("error", str(e))
    return out


def check_value_integrity(src, dst, sample_size=SAMPLE_SIZE):
    """무작위 표본의 값이 실제로 일치하는지 타입별로 확인한다."""
    sample = sample_keys(src, sample_size)
    if not sample:
        return {"error": "소스가 비어 있음"}

    src_vals = read_value(src, sample)
    dst_vals = read_value(dst, sample)

    matched = 0
    mismatched = 0
    absent = 0
    mismatch_samples = []

    for key in sample:
        sv = src_vals.get(key)
        dv = dst_vals.get(key)
        if sv is None:
            # 표본을 뽑은 뒤 소스에서 만료된 키. 유실이 아니다.
            continue
        if dv is None:
            absent += 1
        elif sv == dv:
            matched += 1
        else:
            mismatched += 1
            if len(mismatch_samples) < 5:
                mismatch_samples.append(
                    key.decode(errors="replace") if isinstance(key, bytes) else str(key)
                )

    compared = matched + mismatched + absent
    return {
        "sampled": len(sample),
        "compared": compared,
        "value_identical": matched,
        "value_differs": mismatched,
        "absent_in_target": absent,
        "mismatch_samples": mismatch_samples,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--src-host", required=True)
    p.add_argument("--src-port", type=int, default=6380)
    p.add_argument("--src-password", help="생략하면 SRC_REDIS_PASSWORD 환경 변수")
    p.add_argument("--dst-host", required=True)
    p.add_argument("--dst-port", type=int, default=10000)
    p.add_argument("--dst-password", help="생략하면 DST_REDIS_PASSWORD 환경 변수")
    p.add_argument("--probe-log", help="concurrent_writer.py가 남긴 로그")
    p.add_argument("--report", help="결과 JSON 경로")
    args = p.parse_args()

    args.src_password = resolve_password(args.src_password, "SRC_REDIS_PASSWORD")
    args.dst_password = resolve_password(args.dst_password, "DST_REDIS_PASSWORD")

    src = connect(args.src_host, args.src_port, args.src_password)
    dst = connect(args.dst_host, args.dst_port, args.dst_password)

    result = {
        "src_dbsize": src.dbsize(),
        "dst_dbsize": dst.dbsize(),
        "src_used_memory": src.info("memory")["used_memory_human"],
    }
    try:
        result["dst_used_memory"] = dst.info("memory")["used_memory_human"]
    except Exception as e:
        result["dst_used_memory"] = f"조회 실패: {e}"

    print("=== 키 개수 ===", flush=True)
    print(f"소스: {result['src_dbsize']:,} ({result['src_used_memory']})", flush=True)
    print(f"타깃: {result['dst_dbsize']:,} ({result['dst_used_memory']})", flush=True)
    print(f"차이: {result['src_dbsize'] - result['dst_dbsize']:,}", flush=True)

    if args.probe_log:
        print("\n=== 쓰기 유실 ===", flush=True)
        loss = check_probe_loss(dst, args.probe_log)
        result["write_loss"] = loss
        for k, v in loss.items():
            print(f"{k}: {v}", flush=True)

    print("\n=== TTL 보존 ===", flush=True)
    ttl = check_ttl_preservation(src, dst)
    result["ttl"] = ttl
    for k, v in ttl.items():
        print(f"{k}: {v}", flush=True)

    print("\n=== 값 무결성 (표본) ===", flush=True)
    integrity = check_value_integrity(src, dst)
    result["integrity"] = integrity
    for k, v in integrity.items():
        print(f"{k}: {v}", flush=True)

    if args.report:
        with open(args.report, "w") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {args.report}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
