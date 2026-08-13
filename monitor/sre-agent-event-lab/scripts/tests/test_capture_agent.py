import importlib.util
import json
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
