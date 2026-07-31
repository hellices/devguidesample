#!/usr/bin/env python3
"""Bloat driver: sustained max-rate UPSERTs on store_stream_offsets (+hot kv keys).
Constant client concurrency; if CPU rises over time at constant rate => bloat/autovacuum hypothesis confirmed."""
import os, random, sys, threading, time
from collections import Counter
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
DSN = (f"host={HOST} port=6432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require")

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 3600
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 120

stats = Counter(); lock = threading.Lock(); stop = threading.Event()

def worker():
    conn = None
    while not stop.is_set():
        try:
            if conn is None or conn.closed:
                conn = psycopg2.connect(DSN); conn.autocommit = True
            with conn.cursor() as cur:
                r = random.random()
                if r < 0.60:
                    # GREATEST upsert on existing rows (whole 4.7M range) -> constant row updates
                    ns = f"ns:{random.randrange(4744457)}"
                    cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                                "ON CONFLICT (scope) DO UPDATE SET consumed_seq = GREATEST("
                                '"public"."store_stream_offsets".consumed_seq, EXCLUDED.consumed_seq)',
                                (ns, random.randrange(10**12)))
                    k = 'off_greatest'
                elif r < 0.85:
                    # increment upsert on HOT scopes -> same-row contention like production
                    ns = f"ns:{random.randrange(50)}"
                    cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                                "ON CONFLICT (scope) DO UPDATE SET consumed_seq = "
                                '"public"."store_stream_offsets".consumed_seq + %s RETURNING consumed_seq',
                                (ns, 1, 1))
                    k = 'off_incr_hot'
                else:
                    # kv hot-key upsert (1.8KB payload rewrite -> TOAST+index churn)
                    ns = f"ns:{random.randrange(3)}"
                    cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s) '
                                "ON CONFLICT (scope, key, part_month) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()",
                                (ns, f"hotkey:{random.randrange(5000)}", psycopg2.Binary(os.urandom(1800))))
                    k = 'kv_upsert_hot'
            with lock: stats[k] += 1
        except Exception as e:
            with lock: stats['err:' + type(e).__name__] += 1
            time.sleep(0.5); conn = None

t0 = time.time()
threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
for t in threads: t.start()
last = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(30)
        with lock: cur = dict(stats)
        tot = sum(v for k, v in cur.items() if not k.startswith('err'))
        print(f"[{int(time.time()-t0):5d}s] qps={(tot-last)/30:7.1f} total={tot:9d} {cur}", flush=True)
        last = tot
finally:
    stop.set()
    print("BLOAT_DRIVER_DONE", dict(stats), flush=True)
