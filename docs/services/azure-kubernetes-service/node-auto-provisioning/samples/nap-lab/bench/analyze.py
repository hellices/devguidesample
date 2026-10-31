#!/usr/bin/env python3
"""bench.sh 스냅샷에서 단계별 시간(초)을 계산해 CSV 한 줄을 출력합니다.

decision_s           확장 결정: CAS ScaledUpGroup('setting group') 또는 TriggeredScaleUp 중 이른 시각 / NAP NodeClaim 생성
vm_launched_s        NAP NodeClaim Launched(VM 생성 API 완료). CAS는 측정하지 않음
first_node_ready_s   첫 워크로드 노드 Ready
last_node_ready_s    마지막 워크로드 노드 Ready
all_pods_ready_s     모든 inflate Pod Ready
wave_latency_s       WAVES 사용 시 wave별 '추가 → 해당 Pod 모두 Ready' 시간
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def ts(value):
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    if "." in value:
        head, tail = value.split(".", 1)
        tz = tail[tail.index("+"):] if "+" in tail else "+00:00"
        value = head + tz
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def cond(obj, ctype):
    for c in obj.get("status", {}).get("conditions", []) or []:
        if c.get("type") == ctype:
            return c
    return None


def secs(t, t0):
    return "" if t is None else str(round((t - t0).total_seconds()))


def main():
    d, scenario, run, node_sel = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    t0 = ts((d / "t0").read_text().strip())
    key, _, val = node_sel.partition("=")
    load = lambda n: json.loads((d / n).read_text())["items"]

    pods = [p for p in load("pods.json") if p["metadata"].get("labels", {}).get("app") == "inflate"]
    nodes = [n for n in load("nodes.json") if n["metadata"].get("labels", {}).get(key) == val]
    claims = [c for c in load("nodeclaims.json") if ts(c["metadata"]["creationTimestamp"]) >= t0]
    events = load("events.json")

    ready_nodes = []
    for n in nodes:
        c = cond(n, "Ready")
        if c and c["status"] == "True" and ts(c["lastTransitionTime"]) >= t0:
            ready_nodes.append((ts(c["lastTransitionTime"]), n))
    ready_times = sorted(t for t, _ in ready_nodes)
    skus = {}
    for _, n in ready_nodes:
        sku = n["metadata"]["labels"].get("node.kubernetes.io/instance-type", "?")
        skus[sku] = skus.get(sku, 0) + 1

    def ev_time(e):
        return ts(e.get("eventTime") or e.get("firstTimestamp") or e.get("lastTimestamp"))

    def is_cas_decision(e):
        msg = e.get("message") or ""
        return e.get("reason") == "TriggeredScaleUp" or (
            e.get("reason") == "ScaledUpGroup" and msg.startswith("Scale-up: setting group"))

    cas = [ev_time(e) for e in events if is_cas_decision(e) and ev_time(e) and ev_time(e) >= t0]
    decision = min(cas) if cas else (min(ts(c["metadata"]["creationTimestamp"]) for c in claims) if claims else None)
    launched = [ts(cond(c, "Launched")["lastTransitionTime"]) for c in claims if cond(c, "Launched")]

    pod_ready = []
    for p in pods:
        c = cond(p, "Ready")
        if c and c["status"] == "True":
            pod_ready.append((ts(p["metadata"]["creationTimestamp"]), ts(c["lastTransitionTime"])))
    # timeout으로 일부 Pod만 Ready인 실행은 완료 시간으로 기록하지 않습니다.
    all_ready = max(r for _, r in pod_ready) if pods and len(pod_ready) == len(pods) else None

    wave_lat = ""
    wf = d / "waves"
    if wf.exists():
        waves = [(ts(line.split()[0]), int(line.split()[1])) for line in wf.read_text().split("\n") if line.strip()]
        pod_ready.sort()
        out, prev = [], 0
        for wt, cum in waves:
            batch = pod_ready[prev:cum]
            out.append(str(round((max(r for _, r in batch) - wt).total_seconds())) if batch else "")
            prev = cum
        wave_lat = "/".join(out)

    # 축소: scale_in_start부터 VM이 모두 제거된 시각(SCALE_IN_COUNT) 또는 Ready 워크로드 노드 0개 시각까지
    scale_in = ""
    if (d / "scale_in_start").exists() and (d / "scale_in_end").exists():
        s0 = ts((d / "scale_in_start").read_text().strip())
        scale_in = str(round((ts((d / "scale_in_end").read_text().strip()) - s0).total_seconds()))

    row = [
        scenario, run, str(len(pods)), secs(decision, t0), secs(min(launched) if launched else None, t0),
        secs(ready_times[0] if ready_times else None, t0), secs(ready_times[-1] if ready_times else None, t0),
        secs(all_ready, t0), str(len(ready_nodes)), " ".join(f"{k}x{v}" for k, v in sorted(skus.items())),
        scale_in, wave_lat,
    ]
    print(",".join(row), flush=True)


if __name__ == "__main__":
    main()
