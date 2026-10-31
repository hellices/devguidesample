"""bench 분석 스크립트가 함께 쓰는 Kubernetes 시각·Quantity 파서입니다."""
import re
from datetime import datetime, timezone
from decimal import Decimal

_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?")
_QTY = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))([eE][+-]?\d+|Ki|Mi|Gi|Ti|Pi|Ei|n|u|m|k|M|G|T|P|E)?")
_SUFFIX = {
    "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60,
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "": 1,
    "k": Decimal("1e3"), "M": Decimal("1e6"), "G": Decimal("1e9"), "T": Decimal("1e12"),
    "P": Decimal("1e15"), "E": Decimal("1e18"),
}


def ts(value):
    """RFC 3339 시각을 UTC datetime으로 바꿉니다. 소수 초는 마이크로초(6자리)까지 유지합니다."""
    if not value:
        return None
    m = _TS.fullmatch(value.strip())
    if not m:
        raise ValueError(f"RFC 3339 시각이 아닙니다: {value!r}")
    head, frac, tz = m.groups()
    frac = "." + (frac + "000000")[:6] if frac else ""
    tz = "+00:00" if tz in (None, "Z") else tz
    return datetime.fromisoformat(head + frac + tz).astimezone(timezone.utc)


def qty(value):
    """Kubernetes Quantity(binary/decimal SI, 지수 표기)를 기본 단위 float로 바꿉니다."""
    m = _QTY.fullmatch(str(value).strip())
    if not m:
        raise ValueError(f"Kubernetes Quantity가 아닙니다: {value!r}")
    num, suffix = m.group(1), m.group(2) or ""
    if suffix[:1] in ("e", "E") and len(suffix) > 1:
        return float(Decimal(num + suffix))
    return float(Decimal(num) * _SUFFIX[suffix])
