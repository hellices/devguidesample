import importlib.util
import json
import re
import sys
from io import BytesIO
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "capture_agent.py"


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("capture_agent", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __enter__(self):
        return BytesIO(json.dumps({"value": []}).encode())

    def __exit__(self, exc_type, exc_value, traceback):
        return False


def test_snapshot_redacts_sensitive_data_before_persistence():
    capture_agent = load_module()

    snapshot = capture_agent.build_snapshot(
        captured_at="2026-08-13T05:00:00Z",
        source_file="thread-snapshots/0001.json",
        threads=[{"authorization": "Bearer thread-secret"}],
        thread={"accessToken": "thread-access-token"},
        messages=[
            {
                "content": (
                    "Authorization: Bearer message-secret; "
                    "InstrumentationKey=11111111-1111-1111-1111-111111111111; "
                    "AccountKey=storage-account-secret; "
                    "https://logic.example/callback?sig=sas-signature-secret&x=1; "
                    "https://ca-lab.example.koreacentral.azurecontainerapps.io/api/orders"
                )
            }
        ],
    )
    serialized = json.dumps(snapshot)

    for sensitive in (
        "thread-secret",
        "thread-access-token",
        "message-secret",
        "11111111-1111-1111-1111-111111111111",
        "storage-account-secret",
        "sas-signature-secret",
        "azurecontainerapps.io",
    ):
        assert sensitive not in serialized
    assert "[REDACTED]" in serialized
    assert "[CONTAINER_APP_FQDN]" in serialized
    assert snapshot["captured_at"] == "2026-08-13T05:00:00Z"
    assert snapshot["source_file"] == "thread-snapshots/0001.json"


def test_data_plane_get_sends_supplied_bearer_token(monkeypatch):
    capture_agent = load_module()
    observed = {}

    def fake_urlopen(request, timeout):
        observed["authorization"] = request.get_header("Authorization")
        observed["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    result = capture_agent.data_plane_get(
        "https://agent.example",
        "/api/v1/threads",
        "actual-access-token",
    )

    assert result == {"value": []}
    assert observed == {
        "authorization": "Bearer actual-access-token",
        "timeout": 30,
    }


def test_data_plane_get_treats_network_failure_as_transient(monkeypatch):
    capture_agent = load_module()

    def fake_urlopen(request, timeout):
        raise capture_agent.urllib.error.URLError("temporary failure in name resolution")

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    try:
        capture_agent.data_plane_get(
            "https://agent.example", "/api/v1/threads", "token"
        )
    except capture_agent.TransientApiError as exc:
        assert exc.retry_after >= 1
    else:
        raise AssertionError("network failure must raise TransientApiError")


def test_data_plane_get_treats_timeout_as_transient(monkeypatch):
    capture_agent = load_module()

    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    try:
        capture_agent.data_plane_get(
            "https://agent.example", "/api/v1/threads", "token"
        )
    except capture_agent.TransientApiError as exc:
        assert exc.retry_after >= 1
    else:
        raise AssertionError("timeout must raise TransientApiError")


def test_capture_agent_avoids_runtime_only_new_union_syntax():
    """Scripts must import on the interpreter the README assumes (`python3`).

    PEP 604 unions in runtime-evaluated annotations break Python 3.9, which is
    the default `python3` on current macOS.
    """
    source = MODULE_PATH.read_text()
    annotation_lines = [
        line
        for line in source.splitlines()
        if line.lstrip().startswith("def ") or ": " in line
    ]

    union_annotation = re.compile(r":\s*[A-Za-z_][\w.\[\], ]*\s\|\s")
    for line in annotation_lines:
        assert not union_annotation.search(line), line
    assert "-> " not in "".join(
        line for line in annotation_lines if " | " in line.split("->")[-1]
    )

    assert "from __future__ import annotations" in source or "Union" in source


def test_data_plane_get_propagates_client_errors(monkeypatch):
    capture_agent = load_module()

    def fake_urlopen(request, timeout):
        raise capture_agent.urllib.error.HTTPError(
            "https://agent.example/api/v1/threads", 404, "Not Found", {}, None
        )

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    try:
        capture_agent.data_plane_get(
            "https://agent.example", "/api/v1/threads", "token"
        )
    except capture_agent.TransientApiError:
        raise AssertionError("client errors must not be treated as transient")
    except capture_agent.urllib.error.HTTPError as exc:
        assert exc.code == 404
    else:
        raise AssertionError("client errors must propagate")


def test_network_failures_are_reported_before_retrying(capsys, monkeypatch):
    capture_agent = load_module()

    def fake_urlopen(request, timeout):
        raise capture_agent.urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    try:
        capture_agent.data_plane_get(
            "https://agent.example", "/api/v1/threads", "token"
        )
    except capture_agent.TransientApiError:
        pass

    assert "name resolution failed" in capsys.readouterr().err


def test_consecutive_network_failures_stop_the_capture(monkeypatch, capsys):
    capture_agent = load_module()

    def fake_urlopen(request, timeout):
        raise capture_agent.urllib.error.URLError("name resolution failed")

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    for _ in range(capture_agent.MAX_CONSECUTIVE_NETWORK_FAILURES - 1):
        try:
            capture_agent.data_plane_get("https://agent.example", "/api/v1/threads", "t")
        except capture_agent.TransientApiError:
            pass

    try:
        capture_agent.data_plane_get("https://agent.example", "/api/v1/threads", "t")
    except capture_agent.TransientApiError:
        raise AssertionError("repeated network failures must stop being transient")
    except RuntimeError as exc:
        assert "network" in str(exc).lower()
    else:
        raise AssertionError("repeated network failures must raise")

    capture_agent.reset_network_failures()


def test_reachable_http_errors_reset_the_network_failure_counter(monkeypatch):
    capture_agent = load_module()
    capture_agent.reset_network_failures()
    state = {"mode": "network"}

    def fake_urlopen(request, timeout):
        if state["mode"] == "network":
            raise capture_agent.urllib.error.URLError("temporary blip")
        raise capture_agent.urllib.error.HTTPError(
            "https://agent.example/api/v1/threads", 503, "Service Unavailable", {}, None
        )

    monkeypatch.setattr(capture_agent.urllib.request, "urlopen", fake_urlopen)

    for _ in range(capture_agent.MAX_CONSECUTIVE_NETWORK_FAILURES - 1):
        try:
            capture_agent.data_plane_get("https://agent.example", "/api/v1/threads", "t")
        except capture_agent.TransientApiError:
            pass

    # The endpoint answered with HTTP 503, so it is reachable.
    state["mode"] = "http"
    try:
        capture_agent.data_plane_get("https://agent.example", "/api/v1/threads", "t")
    except capture_agent.TransientApiError:
        pass

    state["mode"] = "network"
    try:
        capture_agent.data_plane_get("https://agent.example", "/api/v1/threads", "t")
    except capture_agent.TransientApiError:
        pass
    except RuntimeError as exc:
        raise AssertionError(f"counter was not reset after a reachable response: {exc}")

    capture_agent.reset_network_failures()
