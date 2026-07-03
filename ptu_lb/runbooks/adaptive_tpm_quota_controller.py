#!/usr/bin/env python3
"""
Adaptive TPM Quota Controller (Python / Azure Automation Python 3 runbook)
==========================================================================

목적
----
Korea / UK 2개 Foundry(gpt) 배포가 나눠 쓰는 **Reserved TPM quota 총량**을,
각 리전의 실제 사용률(utilization)에 맞게 **재분배**하도록 자동 조정한다.

핵심 설계 결정 (중요)
--------------------
* 두 배포 capacity 의 합은 사용자가 Reservation 한 총량(RESERVED_TOTAL_TPM)을
  **어떤 시점에도 초과할 수 없다.** 초과하는 증설 요청은 거부된다.
* 따라서 리전을 독립으로 올리지 않고, 고정된 Reserved 총량을 트래픽 비율에
  맞춰 재분배한다:
    - 필요량 합이 총량 이하면 각자 need 만 배정(나머지는 미할당 버퍼)
    - 필요량 합이 총량을 초과하면(경합) 소비 TPM 비율로 비례 배분
* **감축 먼저, 증설 나중**: 총량이 꽉 찬 상태에서 증설을 먼저 하면 실패하므로,
  잉여 리전을 먼저 감축해 headroom 을 확보한 뒤 증설한다.
* **loss 최소화**: 증설은 우선 미할당 버퍼로 충당(무손실)하고, 부족할 때만
  잉여를 회수하되 감축·증설을 같은 사이클에서 연속 처리한다.
* 리전 최소 보장(MIN_CAPACITY)은 Reserved 총량의 25% 로 유지한다.
* capacity 단위와 TPM 의 매핑은 TPM_PER_CAPACITY_UNIT 로 명시한다.

채운 갭
-------
1. 실제 actuation: azure-mgmt-cognitiveservices 로 배포 sku.capacity 를 실제 갱신
2. 상태 추적(폐루프): 실행 시 배포의 현재 capacity 를 SDK 로 읽어 기준값으로 사용
3. 쿨다운: ScaleAction 이력에서 리전별 마지막 실제 변경 시각을 확인해 재조정 차단
4. 실 메트릭 경로: TrafficWindow(Table) 에서 리전별 최근 N 윈도우를 읽어 이동평균
5. 총량 제약: 두 리전 합 ≤ Reserved 총량, 감축→증설 순서로 불변식 보장
6. az CLI 제거: Azure SDK(Table/mgmt) 사용 → Automation Python 샌드박스에서 동작

인증
----
* DefaultAzureCredential 사용.
    - 로컬: `az login` 세션(AzureCliCredential)을 자동 사용
    - Azure Automation: 시스템 할당 관리 ID(ManagedIdentityCredential)를 자동 사용
* 필요한 RBAC:
    - Storage: "Storage Table Data Contributor" (TrafficWindow 읽기 / 이력 쓰기)
    - Foundry: "Cognitive Services Contributor" (배포 capacity 갱신)

로컬 실행 예시
-------------
    pip install -r requirements.txt
    python adaptive_tpm_quota_controller.py --dry-run          # 계산만
    python adaptive_tpm_quota_controller.py                    # 실제 조정
"""

from __future__ import annotations

import argparse
import math
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from azure.identity import DefaultAzureCredential
from azure.data.tables import TableServiceClient
from azure.mgmt.cognitiveservices import CognitiveServicesManagementClient


# ---------------------------------------------------------------------------
# 설정 (운영 시 환경변수/파라미터로 외부화 권장)
# ---------------------------------------------------------------------------

SUBSCRIPTION_ID = "2cf925b6-80cb-4567-abda-5ccd3010aab5"
RESOURCE_GROUP = "ptu-lb"
STORAGE_ACCOUNT = "ptulb59018sa"

TRAFFIC_TABLE = "TrafficWindow"
DECISION_TABLE = "ControlDecision"
ACTION_TABLE = "ScaleAction"

# 리전 → Foundry 계정/배포 매핑 (Reserved 총량을 두 리전이 공유)
REGIONS: dict[str, dict[str, str]] = {
    "korea": {"account": "ptufoundrykr001", "deployment": "tpmtest-kr"},
    "uk": {"account": "ptufoundryuk001", "deployment": "tpmtest-uk"},
}

# --- 제어 파라미터 -----------------------------------------------------------
METRIC_WINDOW_MINUTES = 5        # TrafficWindow 1건이 대표하는 시간(분)
SMOOTHING_WINDOWS = 3            # 이동평균에 사용할 최근 윈도우 개수
TPM_PER_CAPACITY_UNIT = 1000     # capacity 1 unit ≈ 1000 TPM (운영값으로 조정)

# Reserved quota 총량(합산 불변) — 두 리전 capacity 합은 이 값을 넘을 수 없다.
RESERVED_TOTAL_TPM = 20000                                           # Reservation 한 총 TPM 상한
TOTAL_CAPACITY_UNITS = RESERVED_TOTAL_TPM // TPM_PER_CAPACITY_UNIT   # capacity 환산(=20)

TARGET_UTIL_HIGH = 0.75          # 이 사용률 초과 → 증설 압력
TARGET_UTIL_LOW = 0.30           # 이 사용률 미만 → 감축(잉여 회수)
AIM_UTIL = 0.60                  # 조정 후 목표로 삼는 사용률(과도한 왕복 방지용 중간값)

MAX_STEP_UNITS = 5               # 1회 조정 최대 capacity 변경폭(단위)
MIN_CAPACITY_RATIO = 0.25        # 리전별 최소 보장 = Reserved 총량의 25%
MIN_CAPACITY = max(1, math.ceil(TOTAL_CAPACITY_UNITS * MIN_CAPACITY_RATIO))  # =5
MAX_CAPACITY = TOTAL_CAPACITY_UNITS - MIN_CAPACITY   # 상대 리전 최소 보장(2리전 가정) =15
COOLDOWN_MINUTES = 20            # 실제 조정 후 재조정 금지 시간(분)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


@dataclass
class RegionResult:
    region: str
    avg_consumed_tpm: float
    current_capacity: int
    utilization: float
    decision: str            # "up" | "down" | "hold"
    target_capacity: int
    reason: str
    cooldown_blocked: bool
    executed: bool
    contention: bool = False
    error: str = ""


# ---------------------------------------------------------------------------
# 메트릭 조회
# ---------------------------------------------------------------------------

def get_recent_windows(table_svc: TableServiceClient, region: str, limit: int) -> list[dict]:
    """리전 파티션의 최근(RowKey 내림차순) limit 개 윈도우를 반환."""
    tc = table_svc.get_table_client(TRAFFIC_TABLE)
    entities = tc.query_entities(
        query_filter="PartitionKey eq @pk",
        parameters={"pk": region},
    )
    rows = list(entities)
    # RowKey 는 ISO8601 타임스탬프 문자열이므로 문자열 정렬 = 시간 정렬
    rows.sort(key=lambda e: e["RowKey"], reverse=True)
    return rows[:limit]


def avg_consumed_tpm(rows: list[dict]) -> float:
    """윈도우별 (inputTokens+outputTokens)/window_minutes 의 평균(분당 소비 TPM)."""
    if not rows:
        return 0.0
    total = 0.0
    for r in rows:
        tokens = float(r.get("inputTokens", 0)) + float(r.get("outputTokens", 0))
        total += tokens / METRIC_WINDOW_MINUTES
    return round(total / len(rows), 2)


# ---------------------------------------------------------------------------
# 배포 capacity 조회/갱신 (실제 actuation)
# ---------------------------------------------------------------------------

def get_deployment_capacity(mgmt: CognitiveServicesManagementClient, account: str, deployment: str) -> int:
    dep = mgmt.deployments.get(RESOURCE_GROUP, account, deployment)
    return int(dep.sku.capacity)


def set_deployment_capacity(
    mgmt: CognitiveServicesManagementClient, account: str, deployment: str, capacity: int
) -> None:
    """배포 SKU capacity 를 실제로 갱신한다(비동기 → 완료 대기)."""
    dep = mgmt.deployments.get(RESOURCE_GROUP, account, deployment)
    dep.sku.capacity = capacity
    poller = mgmt.deployments.begin_create_or_update(
        RESOURCE_GROUP, account, deployment, dep
    )
    poller.result()


# ---------------------------------------------------------------------------
# 쿨다운 체크
# ---------------------------------------------------------------------------

def is_in_cooldown(table_svc: TableServiceClient, region: str, now: datetime) -> bool:
    """해당 리전의 마지막 '실제 변경' ScaleAction 이 쿨다운 이내면 True."""
    tc = table_svc.get_table_client(ACTION_TABLE)
    actions = list(
        tc.query_entities(
            query_filter="region eq @r",
            parameters={"r": region},
        )
    )
    # 실제 capacity 가 바뀐(=changed=True) 액션만 대상으로 최신 것을 찾는다
    changed = [a for a in actions if str(a.get("changed", "")).lower() == "true"]
    if not changed:
        return False
    changed.sort(key=lambda a: a.metadata["timestamp"], reverse=True)
    last_ts: datetime = changed[0].metadata["timestamp"]
    if last_ts.tzinfo is None:
        last_ts = last_ts.replace(tzinfo=timezone.utc)
    elapsed_min = (now - last_ts).total_seconds() / 60.0
    return elapsed_min < COOLDOWN_MINUTES


# ---------------------------------------------------------------------------
# 공유 상한(Reserved quota) 재분배 로직
# ---------------------------------------------------------------------------

@dataclass
class RegionState:
    region: str
    account: str
    deployment: str
    current: int
    consumed: float
    utilization: float


def need_capacity(consumed_tpm: float) -> int:
    """AIM_UTIL 에서 돌릴 수 있는 capacity 를 역산(리전 최소/최대로 clamp)."""
    if consumed_tpm <= 0:
        return MIN_CAPACITY
    raw = math.ceil(consumed_tpm / (AIM_UTIL * TPM_PER_CAPACITY_UNIT))
    return clamp(raw, MIN_CAPACITY, MAX_CAPACITY)


def compute_targets(states: list[RegionState]) -> tuple[dict[str, int], dict[str, int], bool]:
    """
    Reserved 총량 제약(sum <= TOTAL_CAPACITY_UNITS) 하에서 리전별 목표 capacity 를 산출.

    반환: (targets, needs, contention)
      - needs: 각 리전이 AIM_UTIL 로 돌기 위해 필요한 capacity
      - contention: 총 필요량이 Reserved 총량을 초과(True) → 소비 TPM 비율로 비례 배분
    """
    n = len(states)
    needs = {s.region: need_capacity(s.consumed) for s in states}
    total_need = sum(needs.values())

    if total_need <= TOTAL_CAPACITY_UNITS:
        # 여유 있음: 필요량만 배정하고 남는 건 미할당 버퍼로 둔다(증설은 무손실).
        return dict(needs), needs, False

    # 경합: MIN 을 먼저 보장하고 남은 용량을 소비 TPM 비율로 배분한다.
    rem = TOTAL_CAPACITY_UNITS - n * MIN_CAPACITY
    total_consumed = sum(max(s.consumed, 0.0) for s in states) or 1.0
    targets: dict[str, int] = {}
    for s in states:
        extra = int(rem * max(s.consumed, 0.0) / total_consumed)
        targets[s.region] = clamp(MIN_CAPACITY + extra, MIN_CAPACITY, MAX_CAPACITY)
    # 내림으로 남은 잔여 unit 을 소비가 큰 리전부터 채운다(합이 TOTAL 을 넘지 않게).
    leftover = TOTAL_CAPACITY_UNITS - sum(targets.values())
    for s in sorted(states, key=lambda x: x.consumed, reverse=True):
        while leftover > 0 and targets[s.region] < MAX_CAPACITY:
            targets[s.region] += 1
            leftover -= 1
    return targets, needs, True


def plan_region(state: RegionState, target: int, contention: bool) -> tuple[str, int, str]:
    """
    목표치를 dead-band/스텝 제한으로 완충해 이번 사이클의 planned capacity 를 만든다.
    반환: (decision, planned, reason)
    """
    within_band = TARGET_UTIL_LOW <= state.utilization <= TARGET_UTIL_HIGH
    if within_band and not contention:
        # 편안한 구간이고 경합도 없음 → 불필요한 왕복(churn) 방지 위해 유지
        return "hold", state.current, f"util {state.utilization:.2%} in dead-band"

    delta = clamp(target - state.current, -MAX_STEP_UNITS, MAX_STEP_UNITS)
    planned = state.current + delta
    tag = f"util {state.utilization:.2%} -> target {target} (contention={contention})"
    if planned > state.current:
        return "up", planned, tag
    if planned < state.current:
        return "down", planned, tag
    return "hold", state.current, f"util {state.utilization:.2%} bounded, no change"


# ---------------------------------------------------------------------------
# 이력 기록
# ---------------------------------------------------------------------------

def _date_pk(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _row_key(now: datetime, region: str) -> str:
    return f"{now.strftime('%Y%m%dT%H%M%S%f')}-{region}-{uuid.uuid4().hex[:8]}"


def write_decision(table_svc: TableServiceClient, now: datetime, res: RegionResult) -> None:
    tc = table_svc.get_table_client(DECISION_TABLE)
    tc.create_entity({
        "PartitionKey": _date_pk(now),
        "RowKey": _row_key(now, res.region),
        "region": res.region,
        "utilization": res.utilization,
        "avgConsumedTpm": res.avg_consumed_tpm,
        "capacityBefore": res.current_capacity,
        "capacityTarget": res.target_capacity,
        "decision": res.decision,
        "reason": res.reason,
        "cooldownBlocked": res.cooldown_blocked,
        "executed": res.executed,
    })


def write_action(table_svc: TableServiceClient, now: datetime, res: RegionResult, duration_ms: int) -> None:
    tc = table_svc.get_table_client(ACTION_TABLE)
    changed = res.executed and res.target_capacity != res.current_capacity
    tc.create_entity({
        "PartitionKey": _date_pk(now),
        "RowKey": _row_key(now, res.region),
        "region": res.region,
        "requestPayload": f"{res.region} capacity {res.current_capacity} to {res.target_capacity}",
        "capacityBefore": res.current_capacity,
        "capacityTarget": res.target_capacity,
        "changed": changed,
        "responseStatus": 200 if not res.error else 500,
        "success": res.error == "",
        "errorMessage": res.error,
        "durationMs": duration_ms,
    })


# ---------------------------------------------------------------------------
# 메인 제어 사이클
# ---------------------------------------------------------------------------

def run_cycle(dry_run: bool) -> list[RegionResult]:
    now = datetime.now(timezone.utc)
    cred = DefaultAzureCredential()

    table_svc = TableServiceClient(
        endpoint=f"https://{STORAGE_ACCOUNT}.table.core.windows.net",
        credential=cred,
    )
    mgmt = CognitiveServicesManagementClient(cred, SUBSCRIPTION_ID)

    # --- Phase 1: 상태 수집 (리전별 현재 capacity + 이동평균 사용률) --------------
    states: list[RegionState] = []
    for region, cfg in REGIONS.items():
        account, deployment = cfg["account"], cfg["deployment"]
        current = get_deployment_capacity(mgmt, account, deployment)
        rows = get_recent_windows(table_svc, region, SMOOTHING_WINDOWS)
        consumed = avg_consumed_tpm(rows)
        provisioned = current * TPM_PER_CAPACITY_UNIT
        util = round(consumed / provisioned, 4) if provisioned > 0 else 0.0
        states.append(RegionState(region, account, deployment, current, consumed, util))

    # --- Phase 2: 목표 산출(총량 제약) + dead-band/스텝/쿨다운 완충 ---------------
    targets, _needs, contention = compute_targets(states)

    results: dict[str, RegionResult] = {}
    planned_map: dict[str, int] = {}
    for s in states:
        decision, planned, reason = plan_region(s, targets[s.region], contention)

        cooldown_blocked = False
        if decision != "hold" and is_in_cooldown(table_svc, s.region, now):
            cooldown_blocked = True
            planned = s.current
            decision = "hold"
            reason += " | blocked by cooldown"

        planned_map[s.region] = planned
        results[s.region] = RegionResult(
            region=s.region,
            avg_consumed_tpm=s.consumed,
            current_capacity=s.current,
            utilization=s.utilization,
            decision=decision,
            target_capacity=planned,   # 실제 적용 후 갱신될 수 있음
            reason=reason,
            cooldown_blocked=cooldown_blocked,
            executed=False,
            contention=contention,
        )

    # --- Phase 3: 총량 제약 실행 (감축 먼저 → 증설은 남은 headroom 한도) ----------
    free = TOTAL_CAPACITY_UNITS - sum(s.current for s in states)
    durations: dict[str, int] = {s.region: 0 for s in states}

    def _apply(st: RegionState, new_cap: int, res: RegionResult) -> int:
        start = datetime.now(timezone.utc)
        try:
            if not dry_run:
                set_deployment_capacity(mgmt, st.account, st.deployment, new_cap)
            res.target_capacity = new_cap
            res.executed = (not dry_run) and (new_cap != st.current)
        except Exception as exc:  # noqa: BLE001 - 기록 후 다음 리전 진행
            res.error = str(exc)[:500]
            res.target_capacity = st.current
        return int((datetime.now(timezone.utc) - start).total_seconds() * 1000)

    # 3-1) 감축(donor) 먼저 → headroom 확보 (loss 없이 여유 리전에서 회수)
    for s in states:
        res = results[s.region]
        planned = planned_map[s.region]
        if not res.cooldown_blocked and planned < s.current:
            durations[s.region] = _apply(s, planned, res)
            if not res.error:
                free += s.current - res.target_capacity

    # 3-2) 증설(recipient): 사용률 높은 리전부터, 남은 headroom 한도로만
    for s in sorted(states, key=lambda x: x.utilization, reverse=True):
        res = results[s.region]
        planned = planned_map[s.region]
        if res.cooldown_blocked or planned <= s.current:
            continue
        inc = min(planned - s.current, free)
        if inc <= 0:
            res.decision = "hold"
            res.reason += " | no headroom (Reserved 총량 소진)"
            continue
        new_cap = s.current + inc
        durations[s.region] = _apply(s, new_cap, res)
        if not res.error:
            free -= (res.target_capacity - s.current)
            if res.target_capacity < planned:
                res.reason += f" | headroom-limited to {res.target_capacity}"

    # --- Phase 4: 이력 기록 (판단/액션 모두 남겨 관측 가능하게) -------------------
    for s in states:
        res = results[s.region]
        write_decision(table_svc, now, res)
        write_action(table_svc, now, res, durations[s.region])

    return [results[s.region] for s in states]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Adaptive TPM quota controller (Reserved 총량 공유 재분배)")
    parser.add_argument("--dry-run", action="store_true", help="계산/기록만 하고 실제 capacity 는 바꾸지 않음")
    args = parser.parse_args(argv)

    results = run_cycle(dry_run=args.dry_run)

    print(f"=== Adaptive TPM Quota Controller (dryRun={args.dry_run}) ===")
    total_after = 0
    for r in results:
        total_after += r.target_capacity
        print(
            f"[{r.region}] consumedTpm={r.avg_consumed_tpm} "
            f"capacity={r.current_capacity}->{r.target_capacity} util={r.utilization:.2%} "
            f"decision={r.decision} contention={r.contention} "
            f"cooldown={r.cooldown_blocked} executed={r.executed} "
            f"reason='{r.reason}'"
            + (f" error='{r.error}'" if r.error else "")
        )
    print(f"total capacity after={total_after}/{TOTAL_CAPACITY_UNITS} (Reserved cap)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
