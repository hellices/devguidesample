#!/usr/bin/env python3
"""mixed.sh 스냅샷에서 Pod 준비 결과, 노드 구성, 요청 대비 할당 비율, 시간당 비용을 계산합니다.

출력: scenario,run,ready_big,ready_mem,ready_small,all_ready_s,nodes,skus,vcpu_alloc,mem_alloc_gib,
      cpu_request_ratio,mem_request_ratio,usd_per_hour
usd_per_hour는 노드 SKU 중 하나라도 가격 파일에 없으면 unknown입니다.
"""
import json
import sys
from pathlib import Path

from k8sutil import qty, ts


d, scenario, run, sel, prices_file = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
t0 = ts((d / "t0").read_text().strip())
key, _, val = sel.partition("=")
if not Path(prices_file).is_file():
    sys.exit(f"가격 파일이 없습니다: {prices_file}")
prices = json.loads(Path(prices_file).read_text())
pods = json.loads((d / "pods.json").read_text())["items"]
nodes = [n for n in json.loads((d / "nodes.json").read_text())["items"]
         if n["metadata"]["labels"].get(key) == val
         and any(c["type"] == "Ready" and c["status"] == "True" for c in n["status"]["conditions"])]

ready = {"big": 0, "mem": 0, "small": 0}
last, req_cpu, req_mem, all_ready = None, 0.0, 0.0, True
for p in pods:
    kind = p["metadata"]["labels"].get("kind")
    r = p["spec"]["containers"][0]["resources"]["requests"]
    if p["spec"].get("nodeName"):  # 노드에 배치된 Pod만 할당 비율에 포함
        req_cpu += qty(r["cpu"])
        req_mem += qty(r["memory"])
    c = [x for x in p["status"].get("conditions", []) if x["type"] == "Ready" and x["status"] == "True"]
    if c:
        ready[kind] += 1
        t = ts(c[0]["lastTransitionTime"])
        last = t if last is None or t > last else last
    else:
        all_ready = False

skus, cpu, mem, cost, unpriced = {}, 0.0, 0.0, 0.0, set()
for n in nodes:
    sku = n["metadata"]["labels"].get("node.kubernetes.io/instance-type", "?")
    skus[sku] = skus.get(sku, 0) + 1
    cpu += qty(n["status"]["capacity"]["cpu"])
    mem += qty(n["status"]["capacity"]["memory"])
    if sku in prices:
        cost += prices[sku]
    else:
        unpriced.add(sku)
if unpriced:
    print(f"가격 없는 SKU: {' '.join(sorted(unpriced))}", file=sys.stderr)

print(",".join([
    scenario, run, str(ready["big"]), str(ready["mem"]), str(ready["small"]),
    str(round((last - t0).total_seconds())) if all_ready and last else "not-all-ready",
    str(len(nodes)), " ".join(f"{k}x{v}" for k, v in sorted(skus.items())),
    str(round(cpu)), str(round(mem / 2**30, 1)),
    f"{req_cpu / cpu:.2f}" if cpu else "", f"{req_mem / mem:.2f}" if mem else "",
    "unknown" if unpriced else f"{cost:.3f}",
]), flush=True)
