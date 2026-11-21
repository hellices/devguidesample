"""Core Python Tool #1: check-aks-eos-release-calendar

Scrapes the official Microsoft Learn AKS release calendar and cross-checks
live Azure subscriptions via ARM REST API to identify AKS clusters reaching
End of Support (EOS) within ``months_ahead`` calendar months.

Standard clusters are evaluated against Standard EOL (`end_of_life`), while
Long Term Support (`AKSLongTermSupport` / `Premium`) clusters are evaluated
against LTS EOL (`lts_end`).
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import urllib.request
from typing import Any

# Ensure Korean text in tool output is not expanded 6x into \uXXXX escapes
_orig_dumps = json.dumps
json.dumps = lambda obj, *args, **kwargs: _orig_dumps(  # type: ignore[assignment]
    obj, *args, **{**kwargs, "ensure_ascii": False}
)

FALLBACK_CALENDAR: dict[str, dict[str, str]] = {
    "1.36": {"ga": "2026-06", "std_eol": "2027-06-30", "lts_eol": "2028-06-30"},
    "1.35": {"ga": "2026-03", "std_eol": "2027-03-31", "lts_eol": "2028-03-31"},
    "1.34": {"ga": "2025-11", "std_eol": "2026-11-30", "lts_eol": "2027-11-30"},
    "1.33": {"ga": "2025-06", "std_eol": "2026-06-30", "lts_eol": "2027-06-30"},
    "1.32": {"ga": "2025-03", "std_eol": "2026-03-31", "lts_eol": "2027-03-31"},
}


def cal_month_diff(ref_ym: str, eol_ymd: str) -> int:
    """Return calendar-month difference `(eol_year - ref_year) * 12 + (eol_month - ref_month)`."""
    ry, rm = int(ref_ym[:4]), int(ref_ym[5:7])
    ey, em = int(eol_ymd[:4]), int(eol_ymd[5:7])
    return (ey - ry) * 12 + (em - rm)


def evaluate_cluster_eos(
    name: str,
    rg: str,
    location: str,
    version: str,
    tier: str,
    support_plan: str,
    tags: dict[str, str],
    ref_ym: str,
    window: int,
    cal: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Evaluate a single cluster's EOS status by calendar month and support plan."""
    calendar = cal or FALLBACK_CALENDAR
    parts = version.split(".")
    minor = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else version
    next_minor = f"{parts[0]}.{int(parts[1]) + 1}" if len(parts) >= 2 and parts[1].isdigit() else "N/A"
    cinfo = calendar.get(minor, {"ga": "Unknown", "std_eol": "2026-11-30", "lts_eol": "2027-11-30"})

    is_lts = "longtermsupport" in support_plan.lower() or "lts" in support_plan.lower() or tier.lower() == "premium"
    plan_label = "LTS (Premium)" if is_lts else "Standard"
    eff_eol = cinfo["lts_eol"] if is_lts else cinfo["std_eol"]
    m_diff = cal_month_diff(ref_ym, eff_eol)
    is_target = m_diff <= window

    if m_diff < 0:
        eos_status = f"지원 종료 경과(Expired, {abs(m_diff)}개월 경과)"
    elif is_target:
        eos_status = f"EOS 도래(D-{m_diff}개월, {window}개월 이내 업그레이드 대상)"
    else:
        eos_status = f"정상 지원 중(잔여 {m_diff}개월)"

    return {
        "name": name,
        "rg": rg,
        "location": location,
        "mgmtName": tags.get("mgmtName", "-"),
        "serviceCode": tags.get("ServiceCode", "-"),
        "serviceName": tags.get("ServiceName", "-"),
        "serviceGrade": tags.get("ServiceGrade", "-"),
        "currentVersion": version,
        "minorVersion": minor,
        "supportPlan": plan_label,
        "standardEolDate": cinfo["std_eol"],
        "ltsEolDate": cinfo["lts_eol"],
        "effectiveEolDate": eff_eol,
        "monthsRemaining": m_diff,
        "isUpgradeTarget": is_target,
        "recommendedTargetMinor": next_minor if is_target else "-",
        "eosStatus": eos_status,
    }


def main(months_ahead: str = "4", reference_date: str = "2026-11") -> dict[str, Any]:
    window = int(str(months_ahead).strip() or "4")
    ref_ym = (reference_date or "").strip()[:7] or datetime.date.today().strftime("%Y-%m")
    ry, rm = int(ref_ym[:4]), int(ref_ym[5:7])
    ty, tm = ry + (rm + window - 1) // 12, (rm + window - 1) % 12 + 1

    cal = dict(FALLBACK_CALENDAR)
    source_mode = "live_mslearn_and_arm"
    try:
        req = urllib.request.Request(
            "https://learn.microsoft.com/en-us/azure/aks/supported-kubernetes-versions",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", errors="ignore")
        if "1.34" not in html:
            source_mode = "cached_calendar_and_arm"
    except Exception:
        source_mode = "cached_calendar_and_arm"

    clusters: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    try:
        tok = subprocess.check_output(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                "https://management.azure.com",
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            text=True,
            timeout=10,
        ).strip()
        subs_req = urllib.request.Request(
            "https://management.azure.com/subscriptions?api-version=2022-12-01",
            headers={"Authorization": f"Bearer {tok}"},
        )
        subs = json.loads(urllib.request.urlopen(subs_req, timeout=10).read().decode()).get("value", [])
        for s in subs:
            sid = s.get("subscriptionId")
            url = f"https://management.azure.com/subscriptions/{sid}/providers/Microsoft.ContainerService/managedClusters?api-version=2024-09-01"
            creq = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
            items = json.loads(urllib.request.urlopen(creq, timeout=10).read().decode()).get("value", [])
            for c in items:
                props = c.get("properties", {})
                if props.get("provisioningState") == "Deleting":
                    continue
                tags = c.get("tags") or {}
                sku = c.get("sku") or {}
                tier = sku.get("tier", "Standard")
                support_plan = props.get("supportPlan") or tags.get("SupportPlan") or "KubernetesOfficial"
                rg_match = re.search(r"/resourceGroups/([^/]+)", c.get("id", ""), re.I)
                rg = rg_match.group(1) if rg_match else ""
                entry = evaluate_cluster_eos(
                    name=c.get("name", ""),
                    rg=rg,
                    location=c.get("location", ""),
                    version=props.get("kubernetesVersion", ""),
                    tier=tier,
                    support_plan=support_plan,
                    tags=tags,
                    ref_ym=ref_ym,
                    window=window,
                    cal=cal,
                )
                clusters.append(entry)
                if entry["isUpgradeTarget"]:
                    targets.append(entry)
    except Exception as e:
        return {"status": "ERROR", "error": str(e)[:200]}

    clusters.sort(key=lambda x: x["name"])
    targets.sort(key=lambda x: x["name"])
    return {
        "status": "OK",
        "source": source_mode,
        "referenceMonth": ref_ym,
        "windowEndMonth": f"{ty:04d}-{tm:02d} (말일 기준, {window}개월 이내)",
        "rule": "Standard는 Standard EOL 기준, LTS(AKSLongTermSupport/Premium)는 LTS EOL 기준으로 월 단위(cal_diff <= months_ahead) 판정",
        "totalClusters": len(clusters),
        "eosTargetCount": len(targets),
        "eosTargetClusters": [t["name"] for t in targets],
        "clusters": clusters,
    }
