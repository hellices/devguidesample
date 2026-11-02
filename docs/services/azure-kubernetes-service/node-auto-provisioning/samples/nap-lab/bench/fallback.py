#!/usr/bin/env python3
"""bench.sh 스냅샷에서 선호 VM 실패 후 대체 VM으로 넘어간 시점(초)을 계산합니다.

사용법: fallback.py <run-dir> <scenario> <run> <fallback-pool-pattern> [nap|cas]
  fallback-pool-pattern: CAS는 대체 VMSS 이름 일부(예: aks-user), NAP는 NodePool 이름(예: fallback)
  분석 모드는 마지막 인수로 지정하고, 생략하면 scenario 접두사(nap-/cas-)로 정합니다.
  first_attempt_s와 failure_seen_s는 선호(대체가 아닌) NodeClaim·VMSS만 봅니다. 선호 VM을 시도하지 않은 실행은
  first_attempt_s가 빈 값입니다. NAP는 스냅샷에 남은 선호 NodeClaim 생성 시각과 선호 NodeClaim 이벤트 시각
  중 가장 이른 값을 first_attempt_s로 씁니다(스냅샷 전에 삭제된 NodeClaim 포함). fallback_node_ready_s는 t0 이후 생성된 대체 노드만 봅니다.
  all_pods_ready_s는 run-dir의 replicas(요청 replica 수)만큼 Pod가 Ready여야 기록합니다.
출력: scenario,run,first_attempt_s,failure_seen_s,fallback_decision_s,fallback_node_ready_s,all_pods_ready_s,failure_message
"""
import json
import re
import sys
from pathlib import Path

from k8sutil import event_time, ts

VMSS = re.compile(r"virtualMachineScaleSets/([^/]+)", re.I)
GROUP = re.compile(r"group (\S+?):? ")
TRIGGERED = re.compile(r"\{(\S+?) \d+->")


def main():
    d, scenario, run, pattern = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
    # 스냅샷에 남은 NodeClaim 유무로 추정하지 않습니다. 실패한 NodeClaim이 모두 삭제된 NAP 실행도 NAP로 분석합니다.
    mode = sys.argv[5] if len(sys.argv) > 5 else scenario.split("-", 1)[0]
    if mode not in ("nap", "cas"):
        sys.exit(f"분석 모드를 정할 수 없습니다(nap|cas 인수 또는 nap-/cas- scenario 필요): {scenario}")
    nap = mode == "nap"
    t0 = ts((d / "t0").read_text().strip())
    load = lambda n: json.loads((d / n).read_text())["items"]
    sec = lambda t: "" if t is None else str(round((t - t0).total_seconds()))
    et = lambda e: event_time(e, t0)   # 이전 실행에서 합쳐진 반복 이벤트는 이번 실행 발생 시각으로 봅니다.
    events = [e for e in load("events.json") if et(e) and et(e) >= t0]
    claims = [c for c in load("nodeclaims.json") if ts(c["metadata"]["creationTimestamp"]) >= t0]
    pool = lambda c: c["metadata"].get("labels", {}).get("karpenter.sh/nodepool")

    first = fail = fb = None
    msg = ""
    if nap:
        fbs = [ts(c["metadata"]["creationTimestamp"]) for c in claims if pool(c) == pattern]
        fb = min(fbs) if fbs else None
        # 선호 NodeClaim의 경고만 실패로 봅니다. 실패한 NodeClaim은 스냅샷 전에 삭제될 수 있으므로
        # 스냅샷에 없으면 이름 접두사(<NodePool>-)로 NodePool을 정합니다. 'fallback'과 'fallback-spot'처럼
        # 접두사가 겹치면 가장 긴 NodePool 이름을 씁니다. nodepools.json이 없는 이전 스냅샷은
        # NodeClaim label에 보이는 NodePool 이름만 후보로 씁니다.
        known = {c["metadata"]["uid"]: pool(c) != pattern for c in claims}
        known.update({c["metadata"]["name"]: pool(c) != pattern for c in claims})
        if (d / "nodepools.json").exists():
            names = {p["metadata"]["name"] for p in load("nodepools.json")}
        else:
            names = {p for c in load("nodeclaims.json") if (p := pool(c))}
        names.add(pattern)

        def preferred(o):
            hit = known.get(o.get("uid"), known.get(o.get("name")))
            if hit is not None:
                return hit
            name = o.get("name") or ""
            owner = max((n for n in names if name.startswith(n + "-")), key=len, default=None)
            return owner != pattern

        bad = [e for e in events if e["involvedObject"].get("kind") == "NodeClaim"
               and e.get("type") == "Warning" and preferred(e["involvedObject"])]
        if bad:
            b = min(bad, key=et)
            fail, msg = et(b), (b.get("reason") or "") + ": " + (b.get("message") or "")
        # 일부 선호 NodeClaim만 스냅샷 전에 삭제될 수 있으므로 남은 NodeClaim 생성 시각과
        # 선호 NodeClaim 이벤트 시각을 모두 모아 가장 이른 값을 시도 시각으로 씁니다.
        tries = [ts(c["metadata"]["creationTimestamp"]) for c in claims if pool(c) != pattern]
        tries += [et(e) for e in events if e["involvedObject"].get("kind") == "NodeClaim"
                  and preferred(e["involvedObject"])]
        first = min(tries, default=None)
    else:  # CAS
        def group(e):
            m = (GROUP if e.get("reason") != "TriggeredScaleUp" else TRIGGERED).search(e.get("message") or "")
            return m.group(1) if m else None

        # 확장 결정은 ScaledUpGroup("setting group")과 Pod의 TriggeredScaleUp 중 이른 쪽입니다.
        # 이전 실행에서 생긴 같은 이벤트에 합쳐진 재발생은 event_time이 lastTimestamp로 읽습니다.
        ups = sorted((e for e in events if e.get("reason") == "ScaledUpGroup"
                      and (e.get("message") or "").startswith("Scale-up: setting group")
                      or e.get("reason") == "TriggeredScaleUp"), key=et)
        fbs = [et(e) for e in ups if (g := group(e)) and pattern in g]
        fb = min(fbs) if fbs else None

        # 대체 그룹의 확장은 선호 시도가 아닙니다. 선호 그룹이 backoff로 시도되지 않았으면 빈 값입니다.
        first = next((et(e) for e in ups if (g := group(e)) and pattern not in g), None)

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
        if nap:
            if n["metadata"].get("labels", {}).get("karpenter.sh/nodepool") != pattern:
                continue
        else:
            vmss = VMSS.search(n.get("spec", {}).get("providerID") or "")
            if not vmss or pattern not in vmss.group(1):
                continue
        # 이전 실행에서 남은 노드가 t0 뒤 다시 Ready로 바뀐 경우는 이번 실행의 대체 노드로 세지 않습니다.
        if ts(n["metadata"]["creationTimestamp"]) < t0:
            continue
        c = [x for x in n["status"].get("conditions", []) if x["type"] == "Ready"]
        if c and c[0]["status"] == "True" and ts(c[0]["lastTransitionTime"]) >= t0:
            ready.append(ts(c[0]["lastTransitionTime"]))
    pods, targets = [], 0
    for p in load("pods.json"):
        # 이전 실행에서 남은 Pod와 t0 이전 Ready 전환은 이번 실행 결과로 세지 않습니다.
        if p["metadata"].get("labels", {}).get("app") != "inflate" or ts(p["metadata"]["creationTimestamp"]) < t0:
            continue
        targets += 1
        c = [x for x in p["status"].get("conditions", []) if x["type"] == "Ready" and x["status"] == "True"]
        if c and ts(c[0]["lastTransitionTime"]) >= t0:
            pods.append(ts(c[0]["lastTransitionTime"]))
    # timeout으로 일부 Pod만 Ready이거나 Pod가 요청 replica 수만큼 생기지 않은 실행은 완료 시간으로 기록하지 않습니다.
    # replicas 파일이 없는 이전 스냅샷은 t0 이후 생성된 Pod 수를 요청 수로 봅니다.
    rf = d / "replicas"
    want = int(rf.read_text().strip()) if rf.exists() else targets
    all_ready = max(pods) if pods and len(pods) == targets >= want else None
    msg = re.sub(r"/subscriptions/[^/]+", "/subscriptions/<subscription-id>", msg)
    msg = msg.replace(",", ";").replace("\n", " ")[:200]
    print(",".join([scenario, run, sec(first), sec(fail), sec(fb), sec(min(ready) if ready else None),
                    sec(all_ready), msg]))


if __name__ == "__main__":
    main()
