#!/usr/bin/env python3
"""bench.sh 스냅샷에서 단계별 시간(초)을 계산해 CSV 한 줄을 출력합니다.

decision_s           확장 결정: CAS ScaledUpGroup('setting group') 또는 TriggeredScaleUp 중 이른 시각 / NAP NodeClaim 생성
                     CAS는 대상 노드 providerID의 VMSS(노드를 만든 그룹)를 가리킨 inflate Pod의 TriggeredScaleUp과
                     ScaledUpGroup만 봅니다. 노드를 만들지 못한 그룹(예: quota로 실패한 선호 풀)은 제외합니다.
                     ScaledUpGroup은 이번 실행에 inflate Pod의 TriggeredScaleUp이 가리킨 그룹일 때만 씁니다.
                     NAP는 이번 실행에 생성되어 대상 노드에 연결됐거나, 노드 없이 inflate Pod의
                     Nominated 이벤트(nodeclaim/<이름>)가 가리킨 NodeClaim만 봅니다.
                     이전 실행 이벤트에 합쳐진 반복 이벤트는 lastTimestamp(이번 실행 발생 시각의 상한)를 씁니다.
vm_launched_s        NAP NodeClaim Launched(VM 생성 API 완료). CAS는 측정하지 않음
first_node_ready_s   첫 워크로드 노드 Ready
last_node_ready_s    마지막 워크로드 노드 Ready
all_pods_ready_s     모든 inflate Pod Ready. 실행 디렉터리의 replicas(요청 replica 수)보다 Ready Pod가 적으면 빈 값
wave_latency_s       WAVES 사용 시 wave별 '추가 → 해당 Pod 모두 Ready' 시간
"""
import json
import re
import sys
from pathlib import Path

from k8sutil import event_time, ts

VMSS = re.compile(r"virtualMachineScaleSets/([^/]+)", re.I)
SETTING = re.compile(r"Scale-up: setting group (\S+?):? ")
TRIGGERED = re.compile(r"\{(\S+?) \d+->")
NOMINATED = re.compile(r"nodeclaim/([^\s,]+)")


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
    node_names = {n["metadata"]["name"] for n in nodes}
    events = load("events.json")
    pod_ids = {p["metadata"].get("uid") for p in pods} - {None} | {p["metadata"]["name"] for p in pods}

    def our_pod(o):
        return o.get("kind") == "Pod" and o.get("namespace") == "bench" and (
            o.get("uid") in pod_ids or o.get("name") in pod_ids)

    # 같은 NodePool의 다른 워크로드 NodeClaim은 제외합니다. 노드가 있으면 대상 노드인지로,
    # 노드가 없으면(실패·생성 중) inflate Pod를 그 NodeClaim에 지정한 Karpenter Nominated 이벤트로 판별합니다.
    nominated = {n for e in events if e.get("reason") == "Nominated" and our_pod(e["involvedObject"])
                 for n in NOMINATED.findall(e.get("message") or "")}

    def ours(c):
        node = c.get("status", {}).get("nodeName")
        return node in node_names if node else c["metadata"]["name"] in nominated

    claims = [c for c in load("nodeclaims.json") if ts(c["metadata"]["creationTimestamp"]) >= t0 and ours(c)]

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

    def ev_time(e):  # 이전 실행에서 합쳐진 반복 이벤트는 이번 실행 발생 시각(lastTimestamp)으로 봅니다.
        return event_time(e, t0)

    # CAS: 대상 노드 그룹을 가리킨 inflate Pod의 TriggeredScaleUp과 ScaledUpGroup만 확장 결정으로 봅니다.
    # 노드를 만든 그룹은 대상 노드 providerID의 VMSS로만 정합니다. 실패한 그룹을 가리킨 이벤트는 제외합니다.
    groups = {m.group(1).lower() for n in nodes if (m := VMSS.search(n.get("spec", {}).get("providerID") or ""))}

    # ScaledUpGroup에는 Pod 정보가 없으므로 이번 실행에 inflate Pod의 TriggeredScaleUp이 가리킨 그룹만 받습니다.
    triggered = {g.lower() for e in events if e.get("reason") == "TriggeredScaleUp" and our_pod(e["involvedObject"])
                 and ev_time(e) and ev_time(e) >= t0 for g in TRIGGERED.findall(e.get("message") or "")}

    def is_cas_decision(e):
        msg = e.get("message") or ""
        if e.get("reason") == "TriggeredScaleUp":
            return our_pod(e["involvedObject"]) and any(g.lower() in groups for g in TRIGGERED.findall(msg))
        if e.get("reason") != "ScaledUpGroup":
            return False
        m = SETTING.match(msg)
        return bool(m) and m.group(1).lower() in groups and m.group(1).lower() in triggered

    cas = [ev_time(e) for e in events if is_cas_decision(e) and ev_time(e) and ev_time(e) >= t0]
    decision = min(cas) if cas else (min(ts(c["metadata"]["creationTimestamp"]) for c in claims) if claims else None)
    # Launched는 status가 True일 때만 VM 생성 완료를 뜻합니다(False/Unknown은 실패·재시도 중).
    launched = [ts(cond(c, "Launched")["lastTransitionTime"]) for c in claims
                if (cond(c, "Launched") or {}).get("status") == "True"]

    # (생성 시각, Ready 시각 또는 None). wave는 미준비 Pod를 포함한 전체 대상 Pod로 나눕니다.
    pod_times = []
    for p in pods:
        c = cond(p, "Ready")
        ready_at = ts(c["lastTransitionTime"]) if c and c["status"] == "True" else None
        pod_times.append((ts(p["metadata"]["creationTimestamp"]), ready_at))
    pod_ready = [(c, r) for c, r in pod_times if r is not None]
    # timeout으로 일부 Pod만 Ready이거나 Pod가 요청 replica 수만큼 생기지 않은 실행은 완료 시간으로 기록하지 않습니다.
    # replicas 파일이 없는 이전 스냅샷은 스냅샷의 Pod 수를 요청 수로 봅니다.
    rf = d / "replicas"
    want = int(rf.read_text().strip()) if rf.exists() else len(pods)
    all_ready = max(r for _, r in pod_ready) if pods and len(pod_ready) == len(pods) >= want else None

    wave_lat = ""
    wf = d / "waves"
    if wf.exists():
        waves = [(ts(line.split()[0]), int(line.split()[1])) for line in wf.read_text().split("\n") if line.strip()]
        pod_times.sort(key=lambda x: x[0])
        out, prev = [], 0
        for wt, cum in waves:
            batch = pod_times[prev:cum]
            done = batch and len(batch) == cum - prev and all(r is not None for _, r in batch)
            out.append(str(round((max(r for _, r in batch) - wt).total_seconds())) if done else "")
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
