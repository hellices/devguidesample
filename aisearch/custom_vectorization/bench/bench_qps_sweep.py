"""Open-loop QPS sweep against local TEI /embed (query-path saturation test).

Fixed arrival rate per stage (uniform schedule), stdlib only.
Measures per-request latency (p50/p95/p99), error rate; GPU util/power sampled in parallel.

Run on the GPU VM (localhost TEI). Adjust STAGES for coarse/fine sweeps, e.g.:
  round 1: [5, 10, 20, 30, 40, 50, 55, 60, 65, 70]
  round 2: [100, 150, 200, 250, 300, 350, 400, 450, 500]
  round 3 (knee refinement): [180, 200, 210, 220, 230, 240, 260]
"""
import concurrent.futures as cf
import json, math, subprocess, threading, time, urllib.request

URL = "http://localhost:8080/embed"
QUERY = "지난 분기 반도체 수출 실적과 주요 고객사별 매출 비중을 요약해줘"  # ~40자
STAGES = [5, 10, 20, 30, 40, 50, 55, 60, 65, 70]
DURATION = 30  # s per stage

def one_request():
    body = json.dumps({"inputs": QUERY}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return (time.perf_counter() - t0) * 1000, None
    except Exception as e:
        return (time.perf_counter() - t0) * 1000, str(e)[:60]

def pctl(v, p):
    if not v: return None
    s = sorted(v)
    return s[max(0, math.ceil(len(s) * p) - 1)]

gpu_samples = []
stop_gpu = threading.Event()
def gpu_poll():
    while not stop_gpu.is_set():
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw",
                 "--format=csv,noheader,nounits"], text=True).strip()
            u, p = out.split(", ")
            gpu_samples.append((time.time(), float(u), float(p)))
        except Exception:
            pass
        stop_gpu.wait(1.0)

threading.Thread(target=gpu_poll, daemon=True).start()

results = []
with cf.ThreadPoolExecutor(max_workers=400) as pool:
    for qps in STAGES:
        # warm gap between stages
        time.sleep(3)
        n = qps * DURATION
        interval = 1.0 / qps
        t_start = time.perf_counter()
        stage_t0 = time.time()
        futs = []
        for i in range(n):
            target = t_start + i * interval
            now = time.perf_counter()
            if target > now:
                time.sleep(target - now)
            futs.append(pool.submit(one_request))
        lats, errs = [], 0
        for f in cf.as_completed(futs):
            ms, err = f.result()
            if err: errs += 1
            else: lats.append(ms)
        stage_t1 = time.time()
        g = [(u, p) for (t, u, p) in gpu_samples if stage_t0 <= t <= stage_t1]
        row = {
            "qps_target": qps,
            "sent": n,
            "ok": len(lats),
            "errors": errs,
            "achieved_qps": round(len(lats) / DURATION, 1),
            "mean_ms": round(sum(lats) / len(lats), 2) if lats else None,
            "p50_ms": round(pctl(lats, 0.50), 2) if lats else None,
            "p95_ms": round(pctl(lats, 0.95), 2) if lats else None,
            "p99_ms": round(pctl(lats, 0.99), 2) if lats else None,
            "max_ms": round(max(lats), 1) if lats else None,
            "gpu_util_mean": round(sum(u for u, _ in g) / len(g), 1) if g else None,
            "gpu_util_max": max(u for u, _ in g) if g else None,
            "power_mean_w": round(sum(p for _, p in g) / len(g), 1) if g else None,
        }
        results.append(row)
        print(json.dumps(row), flush=True)

stop_gpu.set()
with open("/tmp/qps_sweep_result.json", "w") as f:
    json.dump(results, f, indent=1)
print("DONE")
