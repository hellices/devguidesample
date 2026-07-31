#!/usr/bin/env python3
"""Direct-5432 connection churn storm: each worker loops
connect(TCP+TLS+fork backend) -> 1 INSERT -> close.
This is what a client WITHOUT pooling does under load.
Usage: churn_storm.py <workers> <duration_s> [host] [ssl]
"""
import os, random, sys, threading, time
from collections import Counter
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
HOST = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("PGHOST", "localhost")
SSL = sys.argv[4] if len(sys.argv) > 4 else "require"
DSN = (f"host={HOST} port=5432 user={USER} dbname={DB} "
       f"password={PASS} sslmode={SSL} connect_timeout=15")

WORKERS = int(sys.argv[1]); DURATION = int(sys.argv[2])
HOT_NS = ["ns:0", "ns:1", "ns:2"]

stats = Counter(); lock = threading.Lock(); stop = threading.Event()

def worker():
    while not stop.is_set():
        try:
            t0 = time.time()
            conn = psycopg2.connect(DSN)
            conn.autocommit = True
            dt_conn = time.time() - t0
            with conn.cursor() as cur:
                ns = random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"
                cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                            'ON CONFLICT (scope) DO UPDATE SET consumed_seq = GREATEST("public"."store_stream_offsets".consumed_seq, EXCLUDED.consumed_seq)',
                            (ns, random.randrange(10**8)))
            conn.close()
            with lock:
                stats['cycles'] += 1
                stats['conn_ms_sum'] += int(dt_conn * 1000)
        except Exception as e:
            with lock: stats['err:' + type(e).__name__] += 1
            time.sleep(0.5)

threading.stack_size(512 * 1024)
t0 = time.time()
threads = [threading.Thread(target=worker, daemon=True) for _ in range(WORKERS)]
for i, t in enumerate(threads):
    t.start()
    if i % 50 == 0: time.sleep(0.5)  # gentle ramp

last = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(20)
        with lock: cur = dict(stats)
        c = cur.get('cycles', 0)
        rate = (c - last) / 20
        avg_ms = cur.get('conn_ms_sum', 0) // max(c, 1)
        errs = {k: v for k, v in cur.items() if k.startswith('err')}
        print(f"[{int(time.time()-t0):5d}s] conn_rate={rate:7.1f}/s avg_conn_ms={avg_ms} total={c} errs={errs}", flush=True)
        last = c
finally:
    stop.set()
    print("CHURN_DONE", dict(stats), flush=True)
