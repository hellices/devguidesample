#!/usr/bin/env python3
"""bench.sh 스냅샷에서 선호 VM 실패 후 대체 VM으로 넘어간 시점(초)을 계산합니다.

사용법: fallback.py <run-dir> <scenario> <run> <fallback-pool-pattern>
  fallback-pool-pattern: CAS는 대체 VMSS 이름 일부(예: aks-user), NAP는 NodePool 이름(예: fallback)
출력: scenario,run,first_attempt_s,failure_seen_s,fallback_decision_s,fallback_node_ready_s,all_pods_ready_s,failure_message
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def ts(v):
    if not v:
        return None
    v = v.replace("Z", "+00:00")
    if "." in v:
        head, tail = v.split(".", 1)
        v = head + (tail[tail.index("+"):] if "+" in tail else "+00:00")
    return datetime.fromisoformat(v).astimezone(timezone.utc)


def main():
    d, scenario, run, pattern = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    t0 = ts((d / "t0").read_text().strip())
    load = lambda n: json.loads((d / n).read_text())["items"]
    sec = lambda t: "" if t is None else str(round((t - t0).total_seconds()))
    et = lambda e: ts(e.get("eventTime") or e.get("firstTimestamp") or e.get("lastTimestamp"))
    events = [e for e in load("events.json") if et(e) and et(e) >= t0]
    claims = [c for c in load("nodeclaims.json") if ts(c["metadata"]["creationTimestamp"]) >= t0]

    first = fail = fb = None
    msg = ""
    if claims:  # NAP
        first = min(ts(c["metadata"]["creationTimestamp"]) for c in claims)
        fbs = [ts(c["metadata"]["creationTimestamp"]) for c in claims
               if c["metadata"]["labels"].get("karpenter.sh/nodepool") == pattern]
        fb = min(fbs) if fbs else None
        bad = [e for e in events if e["involvedObject"].get("kind") == "NodeClaim"
               and e.get("type") == "Warning"]
        if bad:
            b = min(bad, key=et)
            fail, msg = et(b), (b.get("reason") or "") + ": " + (b.get("message") or "")
    else:  # CAS
        ups = sorted((e for e in events if e.get("reason") == "ScaledUpGroup"
                      and (e.get("message") or "").startswith("Scale-up: setting group")), key=et)
        first = et(ups[0]) if ups else None
        fbs = [et(e) for e in ups if pattern in (e.get("message") or "")]
        fb = min(fbs) if fbs else None
        bad = [e for e in events if e.get("reason") in ("FailedToScaleUpGroup", "ScaleUpFailed")
               or "failed" in (e.get("message") or "").lower() and e.get("reason", "").startswith("Scale")]
        if bad:
            b = min(bad, key=et)
            fail, msg = et(b), (b.get("reason") or "") + ": " + (b.get("message") or "")

    ready = []
    for n in load("nodes.json"):
        c = [x for x in n["status"].get("conditions", []) if x["type"] == "Ready"]
        if c and c[0]["status"] == "True" and ts(c[0]["lastTransitionTime"]) >= t0:
            ready.append(ts(c[0]["lastTransitionTime"]))
    pods = []
    for p in load("pods.json"):
        if p["metadata"].get("labels", {}).get("app") != "inflate":
            continue
        c = [x for x in p["status"].get("conditions", []) if x["type"] == "Ready" and x["status"] == "True"]
        if c:
            pods.append(ts(c[0]["lastTransitionTime"]))
    msg = re.sub(r"/subscriptions/[^/]+", "/subscriptions/<subscription-id>", msg)
    msg = msg.replace(",", ";").replace("\n", " ")[:200]
    print(",".join([scenario, run, sec(first), sec(fail), sec(fb), sec(min(ready) if ready else None),
                    sec(max(pods) if pods else None), msg]))


if __name__ == "__main__":
    main()
