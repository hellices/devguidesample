#!/usr/bin/env python3
"""PgBouncer client-connection storm: hold N idle client conns on :6432
(cheap for postgres backends - pgbouncer multiplexes to small server pool)
while a subset actively writes. Tests single-threaded pgbouncer as CPU bottleneck.
Usage: bouncer_storm.py <idle_conns> <duration_s> [ramp_s]
"""
import os, sys, time
import psycopg2

DIR = os.path.dirname(os.path.abspath(__file__))
HOST = os.environ.get("PGHOST", "localhost")
PASS = os.environ["PGPASSWORD"]
USER = os.environ.get("PGUSER", "pgadmin")
DB = os.environ.get("PGDATABASE", "postgres")
DSN = (f"host={HOST} port=6432 "
       f"user={USER} dbname={DB} password={PASS} sslmode=require connect_timeout=15")

N = int(sys.argv[1]); DURATION = int(sys.argv[2])
RAMP = float(sys.argv[3]) if len(sys.argv) > 3 else 180.0

conns = []
t0 = time.time(); errs = 0
for i in range(N):
    try:
        conns.append(psycopg2.connect(DSN))
    except Exception as e:
        errs += 1
        if errs % 50 == 1: print(f"[{int(time.time()-t0)}s] err#{errs}: {type(e).__name__}: {e}", flush=True)
        time.sleep(0.5)
    if i % 200 == 0: print(f"[{int(time.time()-t0)}s] {len(conns)}/{N} errs={errs}", flush=True)
    time.sleep(max(0.0, RAMP/N))
print(f"HOLDING {len(conns)} pgbouncer client conns (errs={errs})", flush=True)
end = t0 + DURATION
while time.time() < end:
    time.sleep(15)
    alive = [c for c in conns if c.closed == 0]
    if len(alive) != len(conns):
        print(f"[{int(time.time()-t0)}s] alive={len(alive)}", flush=True)
        conns = alive
print(f"BOUNCER_DONE held={len(conns)}", flush=True)
