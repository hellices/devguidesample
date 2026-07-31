#!/usr/bin/env python3
"""Idle session holder: opens N connections and holds them WITHOUT running queries.
No threads - just sockets kept open. Simulates leaked/oversized pool connections.
Usage: idle_holder.py <num_conns> <duration_s> [ramp_s]
"""
import os, sys, time
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
DSN = (f"host={HOST} port=5432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require connect_timeout=15")

N = int(sys.argv[1])
DURATION = int(sys.argv[2])
RAMP = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

conns = []
t0 = time.time()
errs = 0
for i in range(N):
    try:
        c = psycopg2.connect(DSN)
        conns.append(c)
    except Exception as e:
        errs += 1
        if errs % 50 == 1:
            print(f"[{int(time.time()-t0)}s] connect error #{errs}: {type(e).__name__}", flush=True)
        time.sleep(1)
    if i % 100 == 0:
        print(f"[{int(time.time()-t0)}s] opened {len(conns)}/{N} (errs={errs})", flush=True)
    time.sleep(max(0.0, RAMP/N))

print(f"HOLDING {len(conns)} idle conns (errs={errs})", flush=True)
end = t0 + DURATION
while time.time() < end:
    time.sleep(10)
    # prune dead sockets
    alive = [c for c in conns if c.closed == 0]
    if len(alive) != len(conns):
        print(f"[{int(time.time()-t0)}s] alive={len(alive)}", flush=True)
        conns = alive
print(f"IDLE_DONE held={len(conns)}", flush=True)
for c in conns:
    try: c.close()
    except Exception: pass
