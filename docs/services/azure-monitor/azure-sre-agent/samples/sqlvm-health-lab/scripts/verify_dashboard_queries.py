"""Run every dashboard query against the Azure Monitor workspace and report results.

Usage:
    python3 verify_dashboard_queries.py <state.json>

Requires the signed-in Azure CLI user to have Monitoring Data Reader on the
workspace (granted by infra/resources.bicep). Exits non-zero when a panel query
returns no series, unless the panel is listed in EXPECTED_EMPTY.
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SAMPLE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD = SAMPLE_DIR / "monitoring/grafana/sql-server-vm.dashboard.json"
# Panels that legitimately return nothing on a healthy, idle server.
EXPECTED_EMPTY = {
    "문제 DB: 오프라인·로그 재사용 대기",
    "누락 인덱스 제안 (영향 50% 이상)",
    "보유·대기 중인 잠금 (모드·상태별)",
    "대기 중인 잠금 (DB·리소스·모드별)",
    "리소스 유형별 잠금 대기 시간 (초/초)",
    "현재 차단 관계",
    "장시간 실행 요청",
    "로그인 실패 (최근 1시간)",
    "1시간 행 증가량",
}


def az(*args):
    return subprocess.run(["az", *args], check=True, capture_output=True, text=True).stdout.strip()


def query_endpoint(workspace_id):
    workspace = json.loads(az("rest", "--method", "get", "--url",
                              f"https://management.azure.com{workspace_id}?api-version=2023-04-03"))
    return workspace["properties"]["metrics"]["prometheusQueryEndpoint"]


def instant_query(endpoint, token, expr):
    data = urllib.parse.urlencode({"query": expr}).encode()
    request = urllib.request.Request(f"{endpoint}/api/v1/query", data=data,
                                     headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)["data"]["result"]


def panel_queries(dashboard, vm_name):
    for panel in dashboard["panels"]:
        for target in panel.get("targets", []):
            yield panel["title"], target["expr"].replace("$sql_vm", vm_name)


def main(argv):
    state = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    endpoint = query_endpoint(state["monitorWorkspaceId"])
    token = az("account", "get-access-token", "--resource", "https://prometheus.monitor.azure.com",
               "--query", "accessToken", "-o", "tsv")
    dashboard = json.loads(DASHBOARD.read_text(encoding="utf-8"))
    failures = []
    for title, expr in panel_queries(dashboard, state["vmName"]):
        result = instant_query(endpoint, token, expr)
        sample = ", ".join(
            f"{ {k: v for k, v in r['metric'].items() if k not in ('__name__', 'job', 'instance', 'sql_vm', 'microsoft.amwresourceid')} }={r['value'][1]}"
            for r in result[:3])
        print(f"{len(result):>3} series | {title} | {sample[:150]}")
        if not result and title not in EXPECTED_EMPTY:
            failures.append(title)
    if failures:
        print("Panels without data: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
