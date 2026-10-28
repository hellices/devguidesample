"""Read-only PromQL queries against the Azure Monitor workspace that stores the
SQL Server exporter metrics, invoked by Azure SRE Agent.

The agent's user-assigned managed identity needs Monitoring Data Reader on the
workspace. Results are trimmed so that the agent receives compact JSON.
"""

import time

import requests

try:
    from azure.identity import ManagedIdentityCredential
except ImportError:  # pragma: no cover - the SRE Agent sandbox provides azure-identity
    ManagedIdentityCredential = None

PROMETHEUS_QUERY_ENDPOINT = "@@PROMETHEUS_QUERY_ENDPOINT@@"
AGENT_CLIENT_ID = "@@AGENT_CLIENT_ID@@"
SQL_VM_LABEL = "@@VM_NAME@@"

PROMETHEUS_SCOPE = "https://prometheus.monitor.azure.com/.default"
MAX_SERIES = 50
MAX_LOOKBACK_MINUTES = 7 * 24 * 60
DROPPED_LABELS = {"microsoft.amwresourceid", "job", "instance"}


def _token(credential=None):
    if credential is None:
        if ManagedIdentityCredential is None:
            raise RuntimeError("azure-identity is not installed")
        credential = ManagedIdentityCredential(client_id=AGENT_CLIENT_ID)
    return credential.get_token(PROMETHEUS_SCOPE).token


def validate(promql, lookback_minutes, step_seconds):
    if not promql or len(promql) > 2000:
        raise ValueError("promql must be 1 to 2000 characters")
    if not 0 <= lookback_minutes <= MAX_LOOKBACK_MINUTES:
        raise ValueError(f"lookback_minutes must be between 0 and {MAX_LOOKBACK_MINUTES}")
    if not 30 <= step_seconds <= 3600:
        raise ValueError("step_seconds must be between 30 and 3600")


def _labels(metric):
    return {key: value for key, value in metric.items() if key not in DROPPED_LABELS}


def summarize(result_type, result):
    """Keep labels plus the instant value, or first/last/min/max for range results."""
    series = []
    for item in result[:MAX_SERIES]:
        entry = {"labels": _labels(item.get("metric", {}))}
        if result_type == "matrix":
            values = [float(v) for _, v in item.get("values", []) if v not in ("NaN", "+Inf", "-Inf")]
            if values:
                entry.update(first=values[0], last=values[-1], min=min(values), max=max(values),
                             change=values[-1] - values[0], points=len(values))
        else:
            entry["value"] = item.get("value", [None, None])[1]
        series.append(entry)
    return {"result_type": result_type, "series_total": len(result), "series": series}


def main(promql: str, lookback_minutes: int = 0, step_seconds: int = 300) -> dict:
    try:
        lookback_minutes = int(lookback_minutes or 0)
        step_seconds = int(step_seconds or 300)
        validate(promql, lookback_minutes, step_seconds)
        headers = {"Authorization": f"Bearer {_token()}"}
        if lookback_minutes:
            end = time.time()
            data = {"query": promql, "start": end - lookback_minutes * 60, "end": end, "step": step_seconds}
            url = f"{PROMETHEUS_QUERY_ENDPOINT}/api/v1/query_range"
        else:
            data = {"query": promql}
            url = f"{PROMETHEUS_QUERY_ENDPOINT}/api/v1/query"
        response = requests.post(url, data=data, headers=headers, timeout=60)
        if response.status_code >= 400:
            return {"success": False, "error": f"HTTP {response.status_code}: {response.text[:400]}"}
        payload = response.json()["data"]
        return {"success": True, "promql": promql, "sql_vm_label": SQL_VM_LABEL,
                "lookback_minutes": lookback_minutes,
                **summarize(payload["resultType"], payload["result"])}
    except Exception as exc:  # return a structured error to the agent instead of raising
        return {"success": False, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
