#!/usr/bin/env python3
"""E1/E2/E3 hypothesis tester. All via PgBouncer 6432 (production-faithful path).
Modes:
  reads   - E1: session-store read mix (kv point GET, sorted_set range, log tail) + write mix at recorded ratio
  churn   - E2: short-lived connect/one-query/disconnect loops (TLS handshake cost)
  prefix  - E3: scope LIKE 'prefix%' scans (text_pattern_ops index usage evidence)
"""
import os, random, string, sys, threading, time
from collections import Counter
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
def dsn(port=6432):
    return (f"host={HOST} port={port} "
            f"user={USER} dbname={DB} password={PASS} sslmode=require")

MODE = sys.argv[1]
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 480
WORKERS = int(sys.argv[3]) if len(sys.argv) > 3 else 60

stats = Counter(); lock = threading.Lock(); stop = threading.Event()
HOT_NS = ["ns:0", "ns:1", "ns:2"]

def pick_ns():
    return random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"

# --- E1 read ops (session-store access patterns implied by the schema) ---
def r_kv_get(cur):
    # point lookup on hot key -> TOAST detoast of 1.8KB value
    cur.execute('SELECT value FROM "public"."store_kv" WHERE scope=%s AND key=%s',
                (pick_ns(), f"hotkey:{random.randrange(5000)}"))
    cur.fetchall()

def r_kv_get_month(cur):
    # point lookup with part_month (partition-pruned)
    cur.execute('SELECT value FROM "public"."store_kv" WHERE scope=%s AND key=%s AND part_month=%s',
                (pick_ns(), f"k:2026-07:{random.randrange(9000000)}", '2026-07-01'))
    cur.fetchall()

def r_ss_range(cur):
    # ZRANGEBYSCORE equivalent -> uses (scope, score, member) index
    lo = random.random() * 900000
    cur.execute('SELECT member, score FROM "public"."store_sorted_set" '
                'WHERE scope=%s AND score BETWEEN %s AND %s ORDER BY score LIMIT 100',
                (pick_ns(), lo, lo + 10000))
    cur.fetchall()

def r_log_tail(cur):
    # stream tail read
    cur.execute('SELECT seq, record FROM "public"."store_stream" '
                'WHERE scope=%s AND part_month=%s ORDER BY seq DESC LIMIT 50',
                (pick_ns(), '2026-07-01'))
    cur.fetchall()

def r_offsets_get(cur):
    cur.execute('SELECT consumed_seq FROM "public"."store_stream_offsets" WHERE scope=%s',
                (f"ns:{random.randrange(4744457)}",))
    cur.fetchall()

READ_OPS = [(30,'kv_get',r_kv_get),(15,'kv_get_month',r_kv_get_month),
            (25,'ss_range',r_ss_range),(20,'log_tail',r_log_tail),(10,'offsets_get',r_offsets_get)]

def w_kv_upsert(cur):
    cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s) '
                "ON CONFLICT (scope, key, part_month) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
                (pick_ns(), f"hotkey:{random.randrange(5000)}", psycopg2.Binary(os.urandom(1800))))

# --- E3 prefix ops ---
def p_kv_prefix(cur):
    cur.execute('SELECT scope, key FROM "public"."store_kv" '
                "WHERE scope LIKE %s LIMIT 200", (f"ns:{random.randrange(100)}%",))
    cur.fetchall()

def p_ss_prefix_del_sim(cur):
    # scope-prefix listing on sorted_set (cleanup scan pattern)
    cur.execute('SELECT scope, member FROM "public"."store_sorted_set" '
                "WHERE scope LIKE %s LIMIT 200", (f"ns:{random.randrange(100)}%",))
    cur.fetchall()

def p_offsets_prefix(cur):
    cur.execute('SELECT scope, consumed_seq FROM "public"."store_stream_offsets" '
                "WHERE scope LIKE %s LIMIT 500", (f"ns:{random.randrange(1000)}%",))
    cur.fetchall()

PREFIX_OPS = [(40,'kv_prefix',p_kv_prefix),(30,'ss_prefix',p_ss_prefix_del_sim),(30,'off_prefix',p_offsets_prefix)]

def run_persistent(ops, write_ratio=0.0):
    weights = [w for w,_,_ in ops]
    conn = None
    while not stop.is_set():
        try:
            if conn is None or conn.closed:
                conn = psycopg2.connect(dsn()); conn.autocommit = True
            with conn.cursor() as cur:
                if write_ratio and random.random() < write_ratio:
                    w_kv_upsert(cur); k = 'kv_upsert'
                else:
                    _, k, fn = random.choices(ops, weights=weights)[0]
                    fn(cur)
            with lock: stats[k] += 1
        except Exception as e:
            with lock: stats['err:'+type(e).__name__] += 1
            if conn is not None:
                try: conn.close()
                except Exception: pass
            time.sleep(0.5); conn = None

def run_churn():
    # connect -> 1 light query -> disconnect (TLS handshake each time)
    while not stop.is_set():
        try:
            conn = psycopg2.connect(dsn()); conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute('SELECT consumed_seq FROM "public"."store_stream_offsets" WHERE scope=%s',
                            (f"ns:{random.randrange(4744457)}",))
                cur.fetchall()
            conn.close()
            with lock: stats['churn_cycle'] += 1
        except Exception as e:
            with lock: stats['err:'+type(e).__name__] += 1
            time.sleep(0.2)

target = {'reads': lambda: run_persistent(READ_OPS, write_ratio=0.3),
          'prefix': lambda: run_persistent(PREFIX_OPS),
          'churn': run_churn}[MODE]

t0 = time.time()
threads = [threading.Thread(target=target, daemon=True) for _ in range(WORKERS)]
for t in threads: t.start()
last = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(30)
        with lock: cur = dict(stats)
        tot = sum(v for k,v in cur.items() if not k.startswith('err'))
        print(f"[{int(time.time()-t0):5d}s] qps={(tot-last)/30:7.1f} {cur}", flush=True)
        last = tot
finally:
    stop.set()
    print(f"{MODE.upper()}_DONE", dict(stats), flush=True)
