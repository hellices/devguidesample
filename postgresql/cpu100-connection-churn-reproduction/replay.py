#!/usr/bin/env python3
"""Issue #41 traffic replay: query mix per §6.1, bursts per §6.2, via PgBouncer :6432."""
import argparse, os, random, signal, string, sys, threading, time
from collections import Counter

import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")

def dsn(port):
    return (f"host={HOST} port={port} "
            f"user={USER} dbname={DB} password={PASS} sslmode=require")

HOT_NS = ["ns:0", "ns:1", "ns:2"]          # hot scopes (40~70% of traffic)
BUCKET = "2026-07-01"                       # current month partition

def pick_ns():
    # 55% hot (1-3 scopes), 45% long tail
    if random.random() < 0.55:
        return random.choice(HOT_NS)
    return f"ns:{3 + random.randrange(100000)}"

def rand_key(n=24):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))

def payload(size):
    return psycopg2.Binary(os.urandom(size))

# ---- operations (weights = ops/hour from §6.1) ----
def op_log_insert(cur, st):
    ns = pick_ns()
    seq = st["seq"] = st.get("seq", random.randrange(10**9)) + 1
    cur.execute('INSERT INTO "public"."store_stream" (scope, seq, key, record, event_ms, part_month) '
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (ns, seq * 1000 + random.randrange(1000), rand_key(), payload(1200),
                 int(time.time()*1000), BUCKET))

def op_kv_insert(cur, st):
    cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s)',
                (pick_ns(), rand_key(), payload(1800)))

def op_offsets_upsert(cur, st):
    cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                "ON CONFLICT (scope) DO UPDATE SET consumed_seq = GREATEST("
                '"public"."store_stream_offsets".consumed_seq, EXCLUDED.consumed_seq)',
                (pick_ns(), random.randrange(10**8)))

def op_kv_upsert(cur, st):
    key = f"hotkey:{random.randrange(5000)}"
    cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s) '
                "ON CONFLICT (scope, key, part_month) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                (pick_ns(), key, payload(1800)))

def op_ss_insert(cur, st):
    cur.execute('INSERT INTO "public"."store_sorted_set" (scope, member, score) VALUES (%s,%s,%s) '
                "ON CONFLICT (scope, member, part_month) DO NOTHING",
                (pick_ns(), rand_key(), random.random()*1e6))

def op_ss_upsert(cur, st):
    member = f"hotmember:{random.randrange(5000)}"
    cur.execute('INSERT INTO "public"."store_sorted_set" (scope, member, score) VALUES (%s,%s,%s) '
                "ON CONFLICT (scope, member, part_month) DO UPDATE SET score = EXCLUDED.score, updated_at = NOW()",
                (pick_ns(), member, random.random()*1e6))

def op_ss_delete(cur, st):
    cur.execute('DELETE FROM "public"."store_sorted_set" WHERE scope = %s AND member = %s',
                (pick_ns(), f"hotmember:{random.randrange(5000)}"))

def op_seq_counter(cur, st):
    cur.execute("insert into public.seq_counter (id, update_time) select %s, now() "
                "on conflict on constraint seq_counter_pk do update set id = public.seq_counter.id+%s, update_time=now()",
                (1, 1))

OPS = [
    (18220, "log_insert",     op_log_insert),
    (15519, "kv_insert",      op_kv_insert),
    (14371, "offsets_upsert", op_offsets_upsert),
    (13792, "kv_upsert",      op_kv_upsert),
    (9264,  "ss_insert",      op_ss_insert),
    (6040,  "ss_upsert",      op_ss_upsert),
    (2180,  "ss_delete",      op_ss_delete),
    (486,   "seq_counter",       op_seq_counter),
]
WEIGHTS = [w for w, _, _ in OPS]

stats = Counter()
errors = Counter()
lock = threading.Lock()
stop = threading.Event()

def worker(port, rate_fn):
    st = {}
    conn = None
    while not stop.is_set():
        try:
            if conn is None or conn.closed:
                conn = psycopg2.connect(dsn(port))
                conn.autocommit = True
            target = rate_fn()          # per-worker ops/sec right now
            t0 = time.time()
            n = 0
            while time.time() - t0 < 1.0 and not stop.is_set():
                if n >= target:
                    time.sleep(0.02); continue
                w, name, fn = random.choices(OPS, weights=WEIGHTS)[0]
                try:
                    with conn.cursor() as cur:
                        fn(cur, st)
                    with lock: stats[name] += 1
                except psycopg2.Error as e:
                    with lock: errors[type(e).__name__] += 1
                    if conn.closed: conn = None; break
                n += 1
        except Exception as e:
            with lock: errors["conn:" + type(e).__name__] += 1
            time.sleep(1); conn = None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=6432)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--base-rate", type=float, default=150, help="total ops/s baseline")
    ap.add_argument("--burst-rate", type=float, default=600, help="total ops/s during burst")
    ap.add_argument("--burst-secs", type=float, default=4)
    ap.add_argument("--burst-period", type=float, default=12)
    ap.add_argument("--duration", type=int, default=900)
    a = ap.parse_args()

    t_start = time.time()
    def rate_fn():
        phase = (time.time() - t_start) % a.burst_period
        total = a.burst_rate if phase < a.burst_secs else a.base_rate
        return total / a.workers

    threads = [threading.Thread(target=worker, args=(a.port, rate_fn), daemon=True)
               for _ in range(a.workers)]
    for t in threads: t.start()

    last = Counter()
    try:
        while time.time() - t_start < a.duration:
            time.sleep(10)
            with lock:
                cur = Counter(stats); errs = dict(errors)
            delta = sum(cur.values()) - sum(last.values())
            print(f"[{int(time.time()-t_start):4d}s] qps={delta/10:6.1f} total={sum(cur.values()):8d} "
                  f"mix={dict(cur.most_common(4))} errs={errs}", flush=True)
            last = cur
    finally:
        stop.set()
        for t in threads: t.join(timeout=3)
        print("FINAL:", dict(stats), "ERRORS:", dict(errors), flush=True)

if __name__ == "__main__":
    main()
