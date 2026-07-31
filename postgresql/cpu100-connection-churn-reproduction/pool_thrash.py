#!/usr/bin/env python3
"""Pool thrashing simulation: pools EXIST but still churn connections.
Mimics HikariCP-style config gone wrong: minIdle=0 (or low), short idleTimeout,
bursty traffic. Every burst the pool must open fresh connections (TLS+fork),
every quiet period it evicts them.

Each "instance" = pool with max_size conns. Cycle:
  burst phase (burst_s): all workers demand conns -> pool opens up to max -> writes
  quiet phase: idleTimeout expires -> pool closes idle conns down to min_idle
Usage: pool_thrash.py <instances> <max_size> <min_idle> <duration_s>
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
       f"user={USER} dbname={DB} password={PASS} sslmode=require connect_timeout=15")

INSTANCES = int(sys.argv[1]); MAX_SIZE = int(sys.argv[2])
MIN_IDLE = int(sys.argv[3]); DURATION = int(sys.argv[4])
BURST_S = 4.0; PERIOD_S = 12.0   # §6.2 burst shape

HOT_NS = ["ns:0", "ns:1", "ns:2"]
def pick_ns():
    return random.choice(HOT_NS) if random.random() < 0.55 else f"ns:{3+random.randrange(100000)}"

stats = Counter(); lock = threading.Lock(); stop = threading.Event()

class ThrashPool:
    """min_idle..max_size pool with aggressive idle eviction (the misconfig)."""
    def __init__(self):
        self.idle = []; self.n_open = 0; self.lk = threading.Lock()
    def get(self):
        with self.lk:
            if self.idle:
                return self.idle.pop()
            if self.n_open >= MAX_SIZE:
                return None
            self.n_open += 1
        try:
            c = psycopg2.connect(DSN); c.autocommit = True
            with lock: stats['conn_opened'] += 1
            return c
        except Exception as e:
            with self.lk: self.n_open -= 1
            with lock: stats['err:'+type(e).__name__] += 1
            return None
    def put(self, c):
        with self.lk: self.idle.append(c)
    def evict(self):
        with self.lk:
            keep = self.idle[:MIN_IDLE]; drop = self.idle[MIN_IDLE:]
            self.idle = keep; self.n_open -= len(drop)
        for c in drop:
            try: c.close()
            except Exception: pass
        if drop:
            with lock: stats['conn_evicted'] += len(drop)

def one_write(cur):
    cur.execute('INSERT INTO "public"."store_stream_offsets" (scope, consumed_seq) VALUES (%s,%s) '
                'ON CONFLICT (scope) DO UPDATE SET consumed_seq = GREATEST("public"."store_stream_offsets".consumed_seq, EXCLUDED.consumed_seq)',
                (pick_ns(), random.randrange(10**8)))

def instance(idx):
    p = ThrashPool()
    t0 = time.time()
    while not stop.is_set():
        phase = (time.time() - t0) % PERIOD_S
        if phase < BURST_S:
            # burst: hammer with MAX_SIZE parallel demands
            def burst_worker():
                c = p.get()
                if c is None:
                    with lock: stats['pool_exhausted'] += 1
                    return
                try:
                    with c.cursor() as cur:
                        for _ in range(random.randrange(2, 6)):
                            one_write(cur)
                    with lock: stats['writes'] += 1
                    p.put(c)
                except Exception as e:
                    with lock: stats['err:'+type(e).__name__] += 1
                    try: c.close()
                    except Exception: pass
                    with p.lk: p.n_open -= 1
            ts = [threading.Thread(target=burst_worker, daemon=True) for _ in range(MAX_SIZE)]
            for t in ts: t.start()
            for t in ts: t.join(timeout=8)
            time.sleep(0.3)
        else:
            # quiet: idleTimeout fires -> evict down to min_idle
            p.evict()
            time.sleep(0.5)

threading.stack_size(512*1024)
t0 = time.time()
insts = [threading.Thread(target=instance, args=(i,), daemon=True) for i in range(INSTANCES)]
for i, t in enumerate(insts):
    t.start(); time.sleep(0.15)  # stagger phases across instances

last_open = 0
try:
    while time.time() - t0 < DURATION:
        time.sleep(20)
        with lock: cur = dict(stats)
        opened = cur.get('conn_opened', 0)
        rate = (opened - last_open) / 20
        print(f"[{int(time.time()-t0):5d}s] conn_open_rate={rate:6.1f}/s opened={opened} evicted={cur.get('conn_evicted',0)} "
              f"writes={cur.get('writes',0)} exhausted={cur.get('pool_exhausted',0)} "
              f"errs={ {k:v for k,v in cur.items() if k.startswith('err')} }", flush=True)
        last_open = opened
finally:
    stop.set()
    print("THRASH_DONE", dict(stats), flush=True)
