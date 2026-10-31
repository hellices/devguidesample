#!/usr/bin/env python3
"""bench.sh 스냅샷에서 선호 VM 실패 후 대체 VM으로 넘어간 시점(초)을 계산합니다.

사용법: fallback.py <run-dir> <scenario> <run> <fallback-pool-pattern>
  fallback-pool-pattern: CAS는 대체 VMSS 이름 일부(예: aks-user), NAP는 NodePool 이름(예: fallback)
  failure_seen_s는 선호(대체가 아닌) NodeClaim·VMSS의 실패만, fallback_node_ready_s는 대체 노드만 봅니다.
출력: scenario,run,first_attempt_s,failure_seen_s,fallback_decision_s,fallback_node_ready_s,all_pods_ready_s,failure_message
"""
import json
import re
import sys
from pathlib import Path

from k8sutil import ts

VMSS = re.compile(r"virtualMachineScaleSets/([^/]+)", re.I)
GROUP = re.compile(r"group (\S+?):? ")


def main():
    d, scenario, run, pattern = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    t0 = ts((d / "t0").read_text().strip())
    load = lambda n: json.loads((d / n).read_text())["items"]
    sec = lambda t: "" if t is None else str(round((t - t0).total_seconds()))
    et = lambda e: ts(e.get("eventTime") or e.get("firstTimestamp") or e.get("lastTimestamp"))
    events = [e for e in load("events.json") if et(e) and et(e) >= t0]
    claims = [c for c in load("nodeclaims.json") if ts(c["metadata"]["creationTimestamp"]) >= t0]
    pool = lambda c: c["metadata"].get("labels", {}).get("karpenter.sh/nodepool")

    first = fail = fb = None
    msg = ""
    if claims:  # NAP
        first = min(ts(c["metadata"]["creationTimestamp"]) for c in claims)
        fbs = [ts(c["metadata"]["creationTimestamp"]) for c in claims if pool(c) == pattern]
        fb = min(fbs) if fbs else None
        # 선호 NodeClaim의 경고만 실패로 봅니다. 실패한 NodeClaim은 스냅샷 전에 삭제될 수 있으므로
        # 스냅샷에 없으면 이름 접두사(<NodePool>-)가 대체 NodePool이 아닌 것을 선호로 봅니다.
        known = {c["metadata"]["uid"]: pool(c) != pattern for c in claims}
        known.update({c["metadata"]["name"]: pool(c) != pattern for c in claims})

        def preferred(o):
            hit = known.get(o.get("uid"), known.get(o.get("name")))
            return hit if hit is not None else not (o.get("name") or "").startswith(pattern + "-")

        bad = [e for e in events if e["involvedObject"].get("kind") == "NodeClaim"
               and e.get("type") == "Warning" and preferred(e["involvedObject"])]
        if bad:
            b = min(bad, key=et)
            fail, msg = et(b), (b.get("reason") or "") + ": " + (b.get("message") or "")
    else:  # CAS
        ups = sorted((e for e in events if e.get("reason") == "ScaledUpGroup"
                      and (e.get("message") or "").startswith("Scale-up: setting group")), key=et)
        first = et(ups[0]) if ups else None
        fbs = [et(e) for e in ups if pattern in (e.get("message") or "")]
        fb = min(fbs) if fbs else None

        def group(e):
            m = GROUP.search(e.get("message") or "")
            return m.group(1) if m else None

        # 실패 이벤트는 최초 선호 ScaledUpGroup의 그룹만 봅니다. 이번 실행에 선호 그룹 확장 이벤트가
        # 없으면(이전 실행 backoff 등) 대체 그룹이 아닌 그룹의 실패를 선호 VM 실패로 봅니다.
        pref = next((g for g in map(group, ups) if g and pattern not in g), None)
        is_pref = (lambda g: g == pref) if pref else (lambda g: g is not None and pattern not in g)
        bad = [e for e in events if (e.get("reason") in ("FailedToScaleUpGroup", "ScaleUpFailed")
               or "failed" in (e.get("message") or "").lower() and e.get("reason", "").startswith("Scale"))
               and is_pref(group(e))]
        if bad:
            b = min(bad, key=et)
            fail, msg = et(b), (b.get("reason") or "") + ": " + (b.get("message") or "")

    ready = []
    for n in load("nodes.json"):
        # 대체 노드만: NAP는 NodePool label, CAS는 providerID의 VMSS 이름으로 판별합니다.
        if claims:
            if n["metadata"].get("labels", {}).get("karpenter.sh/nodepool") != pattern:
                continue
        else:
            vmss = VMSS.search(n.get("spec", {}).get("providerID") or "")
            if not vmss or pattern not in vmss.group(1):
                continue
        c = [x for x in n["status"].get("conditions", []) if x["type"] == "Ready"]
        if c and c[0]["status"] == "True" and ts(c[0]["lastTransitionTime"]) >= t0:
            ready.append(ts(c[0]["lastTransitionTime"]))
    pods, targets = [], 0
    for p in load("pods.json"):
        if p["metadata"].get("labels", {}).get("app") != "inflate":
            continue
        targets += 1
        c = [x for x in p["status"].get("conditions", []) if x["type"] == "Ready" and x["status"] == "True"]
        if c:
            pods.append(ts(c[0]["lastTransitionTime"]))
    # timeout으로 일부 Pod만 Ready인 실행은 완료 시간으로 기록하지 않습니다.
    all_ready = max(pods) if pods and len(pods) == targets else None
    msg = re.sub(r"/subscriptions/[^/]+", "/subscriptions/<subscription-id>", msg)
    msg = msg.replace(",", ";").replace("\n", " ")[:200]
    print(",".join([scenario, run, sec(first), sec(fail), sec(fb), sec(min(ready) if ready else None),
                    sec(all_ready), msg]))


if __name__ == "__main__":
    main()
