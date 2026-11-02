#!/usr/bin/env python3
"""mixed.sh 스냅샷에서 Pod 준비 결과, 노드 구성, 요청 대비 할당 비율, 시간당 비용을 계산합니다.

사용법: analyze_mixed.py <run-dir> <scenario> <run> <nodeSelector key=value> <prices.json> [big mem small]
  big mem small: 워크로드별 기대 replica 수. 생략하면 pods.json에서 종료 중이 아닌 kind별 Pod 수를 씁니다.
  all_ready_s는 kind별 Ready Pod 수가 모두 기대 수와 같을 때만 기록합니다. 기대 수가 모두 0이고 Pod가 없으면 0입니다.
출력: scenario,run,ready_big,ready_mem,ready_small,all_ready_s,nodes,skus,vcpu_alloc,mem_alloc_gib,
      cpu_request_ratio,mem_request_ratio,usd_per_hour
usd_per_hour는 노드 SKU 중 하나라도 가격 파일에 없으면 unknown입니다.
"""
import json
import sys
from pathlib import Path

from k8sutil import qty, ts, vm_removed


if len(sys.argv) not in (6, 9):
    sys.exit("사용법: analyze_mixed.py <run-dir> <scenario> <run> <nodeSelector key=value> <prices.json> [big mem small]")
d, scenario, run, sel, prices_file = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
t0 = ts((d / "t0").read_text().strip())
key, _, val = sel.partition("=")
if not Path(prices_file).is_file():
    sys.exit(f"가격 파일이 없습니다: {prices_file}")
prices = json.loads(Path(prices_file).read_text())
pods = json.loads((d / "pods.json").read_text())["items"]
# 종료 중인 Pod는 마지막 Ready=True 조건이 남아 있어도 replica로 세지 않습니다(mixed.sh의 대기 판정과 같음).
live_pods = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
# selector와 일치하는 노드를 구성·용량·비용에 넣습니다. 생성 중인 NotReady 노드는 포함하고,
# CAS가 VM을 삭제한 뒤 NotReady로 남은 node 객체(이전 실행의 잔류 포함)는 제외합니다.
nodes = [n for n in json.loads((d / "nodes.json").read_text())["items"]
         if n["metadata"]["labels"].get(key) == val and not vm_removed(n)]
node_names = {n["metadata"]["name"] for n in nodes}

ready = {"big": 0, "mem": 0, "small": 0}
if len(sys.argv) > 6:
    if not all(a.isascii() and a.isdigit() for a in sys.argv[6:9]):
        sys.exit("기대 replica 수는 big mem small 세 개의 0 이상 정수여야 합니다")
    expected = dict(zip(ready, map(int, sys.argv[6:9])))
else:  # 생성되지 않은 Pod는 알 수 없으므로 스냅샷에 있는 Pod 수를 기대 수로 봅니다.
    expected = dict.fromkeys(ready, 0)
    for p in live_pods:
        expected[p["metadata"]["labels"].get("kind")] += 1
last, req_cpu, req_mem = None, 0.0, 0.0
for p in live_pods:
    kind = p["metadata"]["labels"].get("kind")
    r = p["spec"]["containers"][0]["resources"]["requests"]
    if p["spec"].get("nodeName") in node_names:  # 분모에 넣은 노드에 배치된 Pod만 할당 비율에 포함
        req_cpu += qty(r["cpu"])
        req_mem += qty(r["memory"])
    c = [x for x in p["status"].get("conditions", []) if x["type"] == "Ready" and x["status"] == "True"]
    if c:
        ready[kind] += 1
        t = ts(c[0]["lastTransitionTime"])
        last = t if last is None or t > last else last
# 아직 생성되지 않은 Pod가 있으면 스냅샷의 Pod가 모두 Ready여도 완료로 보지 않습니다.
all_ready = ready == expected
# 기대 수가 모두 0이고 Pod도 없으면 기다릴 Pod가 없으므로 0초에 완료한 것으로 봅니다.
if all_ready and last is None and not live_pods and not any(expected.values()):
    last = t0

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
