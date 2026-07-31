#!/usr/bin/env python3
"""Pooled-client reproduction: N app instances x M pool size (psycopg2 ThreadedConnectionPool).
Simulates production topology where many app replicas each hold a persistent pool,
totaling ~5000 server sessions. Write-only mix per issue #41 §6.1.

Usage: pooled_client.py <instances> <pool_size> <duration_s> <total_qps>
Each "instance" = one ThreadedConnectionPool(minconn=pool_size, maxconn=pool_size)
with pool_size worker threads doing getconn -> write -> putconn.
"""
import os, random, sys, threading, time
from collections import Counter
import psycopg2
from psycopg2 import pool as pgpool

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
DSN = (f"host={HOST} port=5432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require connect_timeout=20")

INSTANCES = int(sys.argv[1]) if len(sys.argv) > 1 else 10
POOL_SIZE = int(sys.argv[2]) if len(sys.argv) > 2 else 40
DURATION = int(sys.argv[3]) if len(sys.argv) > 3 else 900
TOTAL_QPS = float(sys.argv[4]) if len(sys.argv) > 4 else 1000.0

HOT_NS = ["ns:0", "ns:1", "ns:2"]
def pick_ns():
    return random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"

stats = Counter(); lock = threading.Lock(); stop = threading.Event()
pools_ready = [0]

def one_write(cur, st):
    r = random.random()
    if r < 0.23:
        st['seq'] = st.get('seq', random.randrange(10**9)) + 1
        cur.execute('INSERT INTO "public"."store_stream" (scope, seq, key, record, event_ms, part_month) VALUES (%s,%s,%s,%s,%s,%s)',
                    (pick_ns(), st['seq']*1000+random.randrange(1000), 'k', psycopg2.Binary(os.urandom(1200)),
                     int(time.time()*1000), '2026-07-01')); return 'log_ins'
    elif r < 0.43:
        cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s)',
                    (pick_ns(), f"pk:{random.randrange(10**9)}", psycopg2.Binary(os.urandom(1800)))); return 'kv_ins'
    elif r < 0.61:
        cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                    'ON CONFLICT (scope) DO UPDATE SET consumed_seq = GREATEST("public"."store_stream_offsets".consumed_seq, EXCLUDED.consumed_seq)',
                    (pick_ns(), random.randrange(10**8))); return 'off_ups'
    elif r < 0.78:
        cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s) '
                    'ON CONFLICT (scope, key, part_month) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()',
                    (pick_ns(), f"hotkey:{random.randrange(5000)}", psycopg2.Binary(os.urandom(1800)))); return 'kv_ups'
    elif r < 0.90:
        cur.execute('INSERT INTO "public"."store_sorted_set" (scope, member, score) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',
                    (pick_ns(), f"pm:{random.randrange(10**9)}", random.random()*1e6)); return 'ss_ins'
    else:
        cur.execute('INSERT INTO "public"."store_sorted_set" (scope, member, score) VALUES (%s,%s,%s) '
                    'ON CONFLICT (scope, member, part_month) DO UPDATE SET score=EXCLUDED.score, updated_at=NOW()',
                    (pick_ns(), f"hotmember:{random.randrange(5000)}", random.random()*1e6)); return 'ss_ups'

TOTAL_WORKERS = INSTANCES * POOL_SIZE
PER_WORKER_INTERVAL = TOTAL_WORKERS / TOTAL_QPS  # seconds between ops per worker

def worker(p):
    st = {}
    while not stop.is_set():
        time.sleep(random.expovariate(1.0 / PER_WORKER_INTERVAL))
        if stop.is_set(): break
        conn = None
        try:
            conn = p.getconn()
            conn.autocommit = True
            with conn.cursor() as cur:
                k = one_write(cur, st)
            with lock: stats[k] += 1
        except Exception as e:
            with lock: stats['err:'+type(e).__name__] += 1
            time.sleep(1)
        finally:
            if conn is not None:
                try: p.putconn(conn)
                except Exception: pass

def instance(idx, ramp_delay):
    time.sleep(ramp_delay)
    try:
        # minconn=POOL_SIZE: pools hold all connections persistently (typical prod config)
        p = pgpool.ThreadedConnectionPool(POOL_SIZE, POOL_SIZE, DSN)
        with lock: pools_ready[0] += 1
    except Exception as e:
        with lock: stats['err:pool_init:'+type(e).__name__] += 1
        return
    ts = [threading.Thread(target=worker, args=(p,), daemon=True) for _ in range(POOL_SIZE)]
    for t in ts: t.start()
    while not stop.is_set(): time.sleep(1)

threading.stack_size(512*1024)
t0 = time.time()
RAMP = 120.0
insts = [threading.Thread(target=instance, args=(i, RAMP*i/INSTANCES), daemon=True) for i in range(INSTANCES)]
for t in insts: t.start()

last = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(30)
        with lock: cur = dict(stats); pr = pools_ready[0]
        tot = sum(v for k,v in cur.items() if not k.startswith('err'))
        errs = {k:v for k,v in cur.items() if k.startswith('err')}
        print(f"[{int(time.time()-t0):5d}s] pools={pr}/{INSTANCES} (~{pr*POOL_SIZE} conns) qps={(tot-last)/30:7.1f} total={tot:8d} errs={errs}", flush=True)
        last = tot
finally:
    stop.set()
    print("POOLED_DONE", dict(stats), flush=True)
