#!/usr/bin/env python3
"""Retry-spiral reproduction: modest fixed task rate -> connection avalanche.

Each task (e.g. one app request needing 1 INSERT):
  connect (timeout T) -> INSERT -> close
  on connect timeout/failure: retry up to R times (typical app/driver behavior)

Offered load is SMALL (default 80 tasks/s = issue burst rate) but in-flight
connections = rate x latency, so as connect latency degrades, concurrent
connection attempts snowball. Completed inserts stay ~tens/s (matching the
production query log) while sessions pile into the thousands.

Usage: retry_spiral.py <tasks_per_sec> <duration_s> [conn_timeout_s] [retries]
"""
import os, random, sys, threading, time
from collections import Counter
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")

RATE = float(sys.argv[1]) if len(sys.argv) > 1 else 80.0
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 600
CONN_TIMEOUT = int(sys.argv[3]) if len(sys.argv) > 3 else 5
RETRIES = int(sys.argv[4]) if len(sys.argv) > 4 else 2
MAX_INFLIGHT = 1500  # per-process client-side cap (OS limits)

DSN = (f"host={HOST} port=5432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require "
       f"connect_timeout={CONN_TIMEOUT}")

HOT_NS = ["ns:0", "ns:1", "ns:2"]
stats = Counter(); lock = threading.Lock(); stop = threading.Event()
inflight = [0]

def task():
    with lock: inflight[0] += 1
    try:
        for attempt in range(RETRIES + 1):
            if stop.is_set(): return
            try:
                t0 = time.time()
                conn = psycopg2.connect(DSN)
                dt = time.time() - t0
                conn.autocommit = True
                try:
                    with conn.cursor() as cur:
                        ns = random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"
                        cur.execute('INSERT INTO "public"."store_stream" (scope, seq, key, record, event_ms, part_month) '
                                    "VALUES (%s,%s,%s,%s,%s,%s)",
                                    (ns, random.randrange(10**15), 'k', psycopg2.Binary(os.urandom(1200)),
                                     int(time.time()*1000), '2026-07-01'))
                    with lock:
                        stats['insert_ok'] += 1
                        stats['conn_ms_sum'] += int(dt*1000)
                finally:
                    conn.close()
                return
            except psycopg2.OperationalError:
                with lock: stats['conn_fail_retry'] += 1
                # immediate retry (typical naive app behavior)
        with lock: stats['task_gave_up'] += 1
    finally:
        with lock: inflight[0] -= 1

threading.stack_size(512*1024)
t0 = time.time()
gen_interval = 1.0 / RATE
next_t = time.time()
last_ok = 0
next_report = t0 + 20

while time.time() - t0 < DURATION and not stop.is_set():
    now = time.time()
    if now >= next_t:
        next_t += gen_interval
        with lock: cur_if = inflight[0]
        if cur_if < MAX_INFLIGHT:
            threading.Thread(target=task, daemon=True).start()
        else:
            with lock: stats['client_saturated'] += 1
    else:
        time.sleep(min(0.005, next_t - now))
    # periodic report (monotonic schedule)
    if now >= next_report:
        next_report += 20
        with lock:
            c = dict(stats); ifl = inflight[0]
        ok = c.get('insert_ok', 0)
        avg = c.get('conn_ms_sum', 0)//max(ok, 1)
        print(f"[{int(now-t0):4d}s] inflight={ifl:5d} insert_rate={(ok-last_ok)/20:6.1f}/s "
              f"ok={ok} retries={c.get('conn_fail_retry',0)} gaveup={c.get('task_gave_up',0)} "
              f"client_sat={c.get('client_saturated',0)} avg_conn_ms={avg}", flush=True)
        last_ok = ok

stop.set()
print("SPIRAL_DONE", dict(stats), "inflight_final", inflight[0], flush=True)
