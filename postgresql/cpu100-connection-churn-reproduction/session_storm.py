#!/usr/bin/env python3
"""Reproduce production evidence: ~5000 PostgreSQL sessions, write-only workload (§6.1 mix).
Direct 5432 connections (session count is server-side evidence, so bypassing pgbouncer pool).
Most sessions idle; each does a write every --idle seconds on hot scopes.
Usage: session_storm.py <num_conns> <duration_s> <mean_idle_s>
"""
import os, random, sys, threading, time
from collections import Counter
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
DSN = (f"host={HOST} port=5432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require "
       f"connect_timeout=20")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4800
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 900
IDLE = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0

HOT_NS = ["ns:0", "ns:1", "ns:2"]
def pick_ns():
    return random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"

stats = Counter(); lock = threading.Lock(); stop = threading.Event()
connected = [0]

def one_write(cur, st):
    r = random.random()
    if r < 0.23:
        st['seq'] = st.get('seq', random.randrange(10**9)) + 1
        cur.execute('INSERT INTO "public"."store_stream" (scope, seq, key, record, event_ms, part_month) VALUES (%s,%s,%s,%s,%s,%s)',
                    (pick_ns(), st['seq']*1000+random.randrange(1000), 'k', psycopg2.Binary(os.urandom(1200)),
                     int(time.time()*1000), '2026-07-01')); return 'log_ins'
    elif r < 0.43:
        cur.execute('INSERT INTO "public"."store_kv" (scope, key, value) VALUES (%s,%s,%s)',
                    (pick_ns(), f"sk:{random.randrange(10**9)}", psycopg2.Binary(os.urandom(1800)))); return 'kv_ins'
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
                    (pick_ns(), f"sm:{random.randrange(10**9)}", random.random()*1e6)); return 'ss_ins'
    else:
        cur.execute('INSERT INTO "public"."store_sorted_set" (scope, member, score) VALUES (%s,%s,%s) '
                    'ON CONFLICT (scope, member, part_month) DO UPDATE SET score=EXCLUDED.score, updated_at=NOW()',
                    (pick_ns(), f"hotmember:{random.randrange(5000)}", random.random()*1e6)); return 'ss_ups'

def worker(delay):
    time.sleep(delay)  # ramp
    st = {}
    conn = None
    while not stop.is_set():
        try:
            if conn is None or conn.closed:
                conn = psycopg2.connect(DSN); conn.autocommit = True
                with lock: connected[0] += 1
            time.sleep(random.expovariate(1.0/IDLE))
            if stop.is_set(): break
            with conn.cursor() as cur:
                k = one_write(cur, st)
            with lock: stats[k] += 1
        except Exception as e:
            with lock:
                stats['err:'+type(e).__name__] += 1
                if conn is not None: connected[0] -= 1
            conn = None
            time.sleep(2)

threading.stack_size(512*1024)
t0 = time.time()
RAMP = 180.0
threads = []
for i in range(N):
    t = threading.Thread(target=worker, args=(RAMP*i/N,), daemon=True)
    t.start(); threads.append(t)
    if i % 500 == 0: time.sleep(0.05)

last = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(30)
        with lock: cur = dict(stats); c = connected[0]
        tot = sum(v for k,v in cur.items() if not k.startswith('err'))
        errs = {k:v for k,v in cur.items() if k.startswith('err')}
        print(f"[{int(time.time()-t0):5d}s] conns={c:5d} qps={(tot-last)/30:7.1f} total={tot:8d} errs={errs}", flush=True)
        last = tot
finally:
    stop.set()
    print("STORM_DONE", dict(stats), flush=True)
