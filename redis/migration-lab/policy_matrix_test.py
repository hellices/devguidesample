#!/usr/bin/env python3
"""clusteringPolicy × 클라이언트 조합별 명령 호환성 실측.

  python3 policy_matrix_test.py --host <amr>.<region>.redis.azure.net \
      --port 10000 --password <key> --policy OSSCluster --repeat 3 \
      --report results/policy-matrix-oss.json

같은 명령 집합을 (비클러스터 클라이언트 / 클러스터 클라이언트) 두 가지로 실행해
무엇이 통과하고 무엇이 실패하는지를 기록합니다. 가이드 2절과 3절의 근거 데이터입니다.

키는 두 종류를 씁니다.
  - 서로 다른 슬롯에 떨어지는 키 (크로스 슬롯)
  - 해시 태그로 같은 슬롯에 모은 키 (대조군)
같은 명령이 슬롯 배치에 따라 어떻게 갈리는지 보려는 것입니다.
"""
import argparse
import json
import ssl
import sys
import time
import traceback

import redis
from redis.cluster import RedisCluster
from redis.crc import key_slot

# 단일 키 쓰기 케이스에서 보낼 키 개수. 왕복 지연이 그대로 곱해지므로 작게 잡습니다.
SOLO_KEYS = 50


def build_cases(tag):
    """(이름, 등급, 실행함수) 목록. tag가 참이면 해시 태그로 같은 슬롯에 모읍니다."""

    def k(name):
        return "{hs}:" + name if tag else "pm:" + name

    A, B, C = k("a"), k("b"), k("c")
    SA, SB, SD = k("sa"), k("sb"), k("sd")
    ZA, ZB, ZD = k("za"), k("zb"), k("zd")
    LA, LB = k("la"), k("lb")
    BA, BB, BD = k("ba"), k("bb"), k("bd")
    HA, HB, HD = k("ha"), k("hb"), k("hd")
    XA, XB = k("xa"), k("xb")
    GA, GD = k("ga"), k("gd")
    RA, RB = k("ra"), k("rb")

    def setup(r):
        # 픽스처는 반드시 단일 키 명령으로만 만듭니다.
        # MSET/DEL 같은 다중 키 명령을 쓰면 클러스터 클라이언트에서 setup 자체가
        # 크로스 슬롯으로 죽어, 뒤이은 케이스의 실패 원인이 "픽스처가 없어서"인지
        # "명령이 막혀서"인지 구분할 수 없게 됩니다.
        # 케이스마다 다시 부르므로 파이프라인으로 묶습니다. 순차로 보내면
        # 왕복 지연(이 랩에서 180ms)이 곱해져 실행 시간이 수십 분이 됩니다.
        p = r.pipeline(transaction=False)
        for key in (SD, ZD, LA, LB, BD, HD, XA, XB, GA, GD, RA, RB,
                    k("cp"), k("n1"), k("n2"), k("so"), SA, SB, ZA, ZB):
            p.delete(key)
        for key, val in ((A, "1"), (B, "2"), (C, "3"), (BA, "abc"), (BB, "abd"),
                         (RA, "rename-me"), (k("d1"), "x"), (k("d2"), "x"),
                         (k("u1"), "x"), (k("u2"), "x")):
            p.set(key, val)
        p.sadd(SA, "x", "y")
        p.sadd(SB, "y", "z")
        p.zadd(ZA, {"x": 1, "y": 2})
        p.zadd(ZB, {"y": 3, "z": 4})
        p.rpush(LA, "1", "2", "3")
        p.rpush(LB, "9")
        p.pfadd(HA, "u1", "u2")
        p.pfadd(HB, "u2", "u3")
        p.xadd(XA, {"f": "1"})
        p.xadd(XB, {"f": "1"})
        p.geoadd(GA, (127.0, 37.5, "seoul"))
        p.execute()

    def set_many(r):
        # 단일 키 쓰기가 정책×클라이언트 조합에서 그대로 되는지 봅니다.
        # 파이프라인으로 묶지 않습니다 — MOVED가 어느 시점에 나는지가 관측 대상입니다.
        for i in range(SOLO_KEYS):
            r.set(k("solo:%d" % i), "1")
        return SOLO_KEYS

    cases = [
        # (이름, 등급, 함수)
        ("단일 키 SET ×%d" % SOLO_KEYS, "단일키", set_many),

        ("MGET",            "허용목록", lambda r: r.mget([A, B, C])),
        ("MSET",            "허용목록", lambda r: r.mset({A: "1", B: "2"})),
        ("EXISTS(다중)",     "허용목록", lambda r: r.exists(A, B, C)),
        ("TOUCH(다중)",      "허용목록", lambda r: r.touch(A, B, C)),
        ("UNLINK(다중)",     "허용목록", lambda r: r.unlink(k("u1"), k("u2"))),
        ("DEL(다중)",        "허용목록", lambda r: r.delete(k("d1"), k("d2"))),

        ("SUNION",          "목록밖", lambda r: r.sunion([SA, SB])),
        ("SINTER",          "목록밖", lambda r: r.sinter([SA, SB])),
        ("SDIFF",           "목록밖", lambda r: r.sdiff([SA, SB])),
        ("SUNIONSTORE",     "목록밖", lambda r: r.sunionstore(SD, [SA, SB])),
        ("SMOVE",           "목록밖", lambda r: _must(r.smove(SA, SB, "x"), "SMOVE")),
        ("ZUNIONSTORE",     "목록밖", lambda r: r.zunionstore(ZD, [ZA, ZB])),
        ("ZINTERSTORE",     "목록밖", lambda r: r.zinterstore(ZD, [ZA, ZB])),
        ("ZDIFF",           "목록밖", lambda r: r.zdiff([ZA, ZB])),
        ("RENAME",          "목록밖", lambda r: r.rename(RA, RB)),
        ("COPY",            "목록밖", lambda r: _must(r.copy(A, k("cp")), "COPY")),
        ("RPOPLPUSH",       "목록밖", lambda r: r.rpoplpush(LA, LB)),
        ("LMOVE",           "목록밖", lambda r: r.lmove(LA, LB, "LEFT", "RIGHT")),
        ("BLPOP(다중키)",    "목록밖", lambda r: r.blpop([LA, LB], timeout=1)),
        ("LMPOP(다중키)",    "목록밖", lambda r: r.lmpop(2, LA, LB, direction="LEFT")),
        ("BITOP",           "목록밖", lambda r: r.bitop("AND", BD, BA, BB)),
        ("PFMERGE",         "목록밖", lambda r: r.pfmerge(HD, HA, HB)),
        ("PFCOUNT(다중)",    "목록밖", lambda r: r.pfcount(HA, HB)),
        ("MSETNX",          "목록밖", lambda r: _must(r.msetnx({k("n1"): "1", k("n2"): "2"}), "MSETNX")),
        ("SORT ... STORE",  "목록밖", lambda r: r.sort(LA, store=k("so"), alpha=True)),
        ("GEOSEARCHSTORE",  "목록밖", lambda r: r.geosearchstore(
            GD, GA, longitude=127.0, latitude=37.5, radius=500, unit="km")),
        ("LCS",             "목록밖", lambda r: r.lcs(BA, BB)),
        ("XREAD(다중키)",    "목록밖", lambda r: r.xread({XA: "0", XB: "0"}, count=1)),
        ("MULTI/EXEC",      "목록밖", lambda r: _multi(r, A, B)),
        ("EVAL(다중 KEYS)",  "목록밖", lambda r: r.eval("return 1", 2, A, B)),
    ]
    return setup, cases, [A, B, C]


def _must(value, name):
    """반환값이 거짓이면 예외로 올립니다.

    COPY/MSETNX/SMOVE는 조건이 안 맞으면 예외 대신 거짓을 돌려줍니다.
    그대로 두면 "예외가 안 났으니 성공"으로 잘못 기록됩니다.
    """
    if not value:
        raise RuntimeError("%s returned %r (실행은 됐지만 조건 불충족)" % (name, value))
    return value


def _multi(r, a, b):
    pipe = r.pipeline(transaction=True)
    pipe.get(a)
    pipe.get(b)
    return pipe.execute()


ADMIN_CASES = [
    ("SELECT 1",                  lambda r: r.execute_command("SELECT", 1)),
    ("SWAPDB 0 1",                lambda r: r.execute_command("SWAPDB", 0, 1)),
    ("ROLE",                      lambda r: r.execute_command("ROLE")),
    ("FAILOVER ABORT",            lambda r: r.execute_command("FAILOVER", "ABORT")),
    ("CONFIG GET maxmemory",      lambda r: r.execute_command("CONFIG", "GET", "maxmemory")),
    ("CONFIG SET notify-keyspace-events",
     lambda r: r.execute_command("CONFIG", "SET", "notify-keyspace-events", "KEA")),
    ("REPLICAOF NO ONE",          lambda r: r.execute_command("REPLICAOF", "NO", "ONE")),
    ("INFO commandstats",         lambda r: r.execute_command("INFO", "commandstats")),
    ("DBSIZE",                    lambda r: r.dbsize()),
]


def classify(exc):
    """예외를 짧은 라벨로."""
    name = type(exc).__name__
    msg = str(exc).strip().replace("\n", " ")[:160]
    return {"error_type": name, "error": msg}


def run_case(fn, r):
    t0 = time.perf_counter()
    try:
        fn(r)
        return {"ok": True, "ms": round((time.perf_counter() - t0) * 1000, 2)}
    except Exception as exc:  # noqa: BLE001 - 무엇이 나오는지가 측정 대상입니다
        out = {"ok": False, "ms": round((time.perf_counter() - t0) * 1000, 2)}
        out.update(classify(exc))
        return out


def connect(kind, host, port, password, check_hostname=True):
    if kind == "비클러스터":
        return redis.StrictRedis(
            host=host, port=port, password=password, ssl=True,
            ssl_cert_reqs=ssl.CERT_REQUIRED, socket_timeout=15,
            decode_responses=True,
        )
    # OSSCluster에서는 클라이언트가 CLUSTER SLOTS로 받은 **샤드 IP**로 다시 붙습니다.
    # 인증서는 <region>.redis.azure.net 이름으로 발급돼 있어 IP로 검증하면 실패합니다.
    #   SSLCertVerificationError: IP address mismatch,
    #   certificate is not valid for '20.x.x.x'
    # check_hostname=False면 체인 검증은 유지한 채 호스트명 대조만 끕니다.
    return RedisCluster(
        host=host, port=port, password=password, ssl=True,
        ssl_cert_reqs=ssl.CERT_REQUIRED, ssl_check_hostname=check_hostname,
        socket_timeout=15, decode_responses=True,
    )


def probe(r):
    """연결과 기본 정보."""
    out = {}
    try:
        out["ping"] = bool(r.ping())
    except Exception as exc:  # noqa: BLE001
        out["ping"] = False
        out.update(classify(exc))
        return out
    try:
        if isinstance(r, RedisCluster):
            out["nodes"] = len(r.get_nodes())
            out["node_addrs"] = sorted(n.name for n in r.get_nodes())
            out["cluster_enabled"] = 1
            srv = r.info("server", target_nodes=RedisCluster.RANDOM)
        else:
            out["cluster_enabled"] = int(r.info("cluster").get("cluster_enabled", -1))
            srv = r.info("server")
        out["redis_version"] = srv.get("redis_version")
    except Exception as exc:  # noqa: BLE001
        out["probe_error"] = classify(exc)
    return out


def run_client(kind, host, port, password, repeat, check_hostname=True):
    result = {"client": kind, "ssl_check_hostname": check_hostname}
    try:
        r = connect(kind, host, port, password, check_hostname)
        result["connect"] = probe(r)
        if not result["connect"].get("ping"):
            return result
    except Exception as exc:  # noqa: BLE001
        result["connect"] = {"ping": False}
        result["connect"].update(classify(exc))
        return result

    for label, tag in (("크로스슬롯", ""), ("같은슬롯", "tag")):
        setup, cases, keys = build_cases(tag)
        slots = sorted({key_slot(k.encode()) for k in keys})
        block = {"distinct_slots": len(slots)}
        try:
            setup(r)
            block["setup"] = "ok"
        except Exception as exc:  # noqa: BLE001
            block["setup"] = classify(exc)

        rows = []
        for name, tier, fn in cases:
            runs = []
            for _ in range(repeat):
                try:
                    setup(r)
                except Exception:  # noqa: BLE001, S110 - setup 실패는 케이스 결과로 드러납니다
                    pass
                runs.append(run_case(fn, r))
            oks = [x["ok"] for x in runs]
            rows.append({
                "command": name,
                "tier": tier,
                "runs": len(runs),
                "ok_count": sum(oks),
                "stable": len(set(oks)) == 1,
                "verdict": "성공" if all(oks) else ("실패" if not any(oks) else "불안정"),
                "error_type": next((x.get("error_type") for x in runs if not x["ok"]), None),
                "error": next((x.get("error") for x in runs if not x["ok"]), None),
            })
        block["cases"] = rows
        result[label] = block

    admin = []
    for name, fn in ADMIN_CASES:
        runs = [run_case(fn, r) for _ in range(repeat)]
        oks = [x["ok"] for x in runs]
        admin.append({
            "command": name,
            "runs": len(runs),
            "ok_count": sum(oks),
            "verdict": "성공" if all(oks) else ("실패" if not any(oks) else "불안정"),
            "error_type": next((x.get("error_type") for x in runs if not x["ok"]), None),
            "error": next((x.get("error") for x in runs if not x["ok"]), None),
        })
    result["관리명령"] = admin
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=10000)
    ap.add_argument("--password", required=True)
    ap.add_argument("--policy", required=True)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--no-ssl-check-hostname", action="store_true",
                    help="클러스터 클라이언트에서 TLS 호스트명 대조를 끕니다 (체인 검증은 유지). "
                         "OSSCluster는 샤드 IP로 재접속하므로 이 옵션 없이는 연결이 안 됩니다.")
    ap.add_argument("--report")
    args = ap.parse_args()

    report = {
        "clustering_policy": args.policy,
        "host": args.host,
        "port": args.port,
        "repeat": args.repeat,
        "redis_py": redis.__version__,
        "ssl_check_hostname_disabled_for_cluster_client": args.no_ssl_check_hostname,
        "clients": [],
    }
    for kind in ("비클러스터", "클러스터"):
        print(f"\n### {args.policy} × {kind} 클라이언트", flush=True)
        try:
            res = run_client(kind, args.host, args.port, args.password, args.repeat,
                             check_hostname=(kind == "비클러스터") or not args.no_ssl_check_hostname)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            res = {"client": kind, "fatal": traceback.format_exc()[-500:]}
        report["clients"].append(res)

        conn = res.get("connect", {})
        print(f"  연결: ping={conn.get('ping')} cluster_enabled={conn.get('cluster_enabled')}"
              f" {conn.get('error_type', '')} {conn.get('error', '')}")
        for label in ("크로스슬롯", "같은슬롯"):
            blk = res.get(label)
            if not blk:
                continue
            ok = sum(1 for c in blk["cases"] if c["verdict"] == "성공")
            print(f"  {label}: {ok}/{len(blk['cases'])} 성공")
            for c in blk["cases"]:
                if c["verdict"] != "성공":
                    print(f"    ✗ {c['command']:<20} {c['tier']:<6} {c['error_type']}: {c['error']}")
        for c in res.get("관리명령", []):
            mark = "○" if c["verdict"] == "성공" else "✗"
            print(f"  {mark} {c['command']:<36} {c.get('error_type') or ''} {c.get('error') or ''}")

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
        print(f"\n결과 저장: {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
