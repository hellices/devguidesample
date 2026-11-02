"""bench 분석 스크립트가 함께 쓰는 Kubernetes 시각·Quantity 파서입니다."""
import re
from datetime import datetime, timezone
from decimal import ROUND_UP, Decimal

_TS = re.compile(r"(\d{4}-\d{2}-\d{2})[Tt](\d{2}:\d{2}:\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})")
_QTY = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E)?")
_SUFFIX = {
    "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60,
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "": 1,
    "k": Decimal("1e3"), "M": Decimal("1e6"), "G": Decimal("1e9"), "T": Decimal("1e12"),
    "P": Decimal("1e15"), "E": Decimal("1e18"),
}
_MILLI = Decimal("1e-3")


def ts(value):
    """RFC 3339 시각을 UTC datetime으로 바꿉니다. 소수 초는 마이크로초(6자리)까지 유지합니다.

    RFC 3339처럼 T/Z 구분자는 소문자(t/z)도 받습니다. 시간대(Z 또는 ±hh:mm)가 없으면 ValueError입니다.
    """
    if not value:
        return None
    m = _TS.fullmatch(value.strip())
    if not m:
        raise ValueError(f"RFC 3339 시각이 아닙니다: {value!r}")
    date, clock, frac, tz = m.groups()
    frac = "." + (frac + "000000")[:6] if frac else ""
    tz = "+00:00" if tz in ("Z", "z") else tz
    return datetime.fromisoformat(f"{date}T{clock}{frac}{tz}").astimezone(timezone.utc)


def event_time(e, t0):
    """이벤트 발생 시각입니다. 기본은 eventTime 또는 firstTimestamp입니다.

    Kubernetes는 반복 이벤트를 count와 lastTimestamp로 합치므로 이전 실행에서 처음 생긴 이벤트가
    이번 실행(t0 이후)에 다시 발생했으면 lastTimestamp를 이번 실행의 발생 시각으로 씁니다.
    events.k8s.io 방식으로 series(count, lastObservedTime)에 합쳐진 이벤트도 같은 규칙으로 lastObservedTime을 씁니다.
    """
    first = ts(e.get("eventTime") or e.get("firstTimestamp") or e.get("lastTimestamp"))
    last = ts(e.get("lastTimestamp"))
    if first and last and (e.get("count") or 1) > 1 and first < t0 <= last:
        return last
    series = e.get("series") or {}
    observed = ts(series.get("lastObservedTime"))
    if first and observed and (series.get("count") or 1) > 1 and first < t0 <= observed:
        return observed
    return first


def qty(value):
    """Kubernetes Quantity(binary/decimal SI, 지수 표기)를 기본 단위 float로 바꿉니다.

    decimal SI 접미사·지수 표기·접미사 없음 값이 milli(1e-3)보다 세밀하면 0에서 먼 쪽으로 1e-3 단위로 올립니다
    (예: 0.0001 → 0.001, 1500u → 0.002). Kubernetes가 CPU를 1m보다 세밀하게 다루지 않는 것과 맞춥니다.
    binary 접미사(Ki, Mi 등) 값은 바꾸지 않습니다.
    """
    m = _QTY.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"Kubernetes Quantity가 아닙니다: {value!r}")
    num, suffix = m.group(1), m.group(2) or ""
    if suffix.endswith("i"):
        return float(Decimal(num) * _SUFFIX[suffix])
    if suffix[:1] in ("e", "E") and len(suffix) > 1:
        v = Decimal(num + suffix)
    else:
        v = Decimal(num) * _SUFFIX[suffix]
    if v.as_tuple().exponent < -3:
        v = v.quantize(_MILLI, rounding=ROUND_UP)
    return float(v)


def vm_removed(node):
    """CAS가 삭제를 시작해 VM이 없어졌거나 없어지는 중인 node 객체면 True입니다.

    CAS는 삭제할 노드에 ToBeDeletedByClusterAutoscaler taint를 붙이고, VM이 삭제되면 node 객체가
    NotReady로 몇 분 더 남습니다. 두 조건을 모두 만족하는 객체만 제외하므로 생성 중이라 NotReady인
    노드와 삭제 표시만 되고 아직 Ready인 노드는 비용·용량에 남습니다.
    """
    ready = any(c["type"] == "Ready" and c["status"] == "True" for c in node["status"].get("conditions", []))
    marked = any(t.get("key") == "ToBeDeletedByClusterAutoscaler" for t in node["spec"].get("taints", []))
    return marked and not ready
