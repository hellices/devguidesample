import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


MODULE_PATH = Path(__file__).parents[1] / "render_storyboard.py"


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("render_storyboard", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_timeline():
    return [
        {
            "event_id": "alert-1",
            "timestamp": "2026-08-12T08:07:56Z",
            "state": "alert-fired",
            "title": "HTTP 500 alert",
            "summary": "Sev2 alert fired",
            "source": "azure-monitor",
            "source_file": "alert.json",
        },
        {
            "event_id": "thread-1",
            "timestamp": "2026-08-12T08:07:58Z",
            "state": "thread-created",
            "title": "SRE thread",
            "summary": "Review-mode thread created",
            "source": "sre-agent",
            "source_file": "0001.json",
        },
        {
            "event_id": "evidence-1",
            "timestamp": "2026-08-12T08:08:56Z",
            "state": "investigating",
            "title": "Evidence",
            "summary": "120 failed requests and FAILURE_MODE=http500",
            "source": "sre-agent",
            "source_file": "0001.json",
        },
        {
            "event_id": "conclusion-1",
            "timestamp": "2026-08-12T08:10:21Z",
            "state": "conclusion",
            "title": "Root cause",
            "summary": "Revision 0000010 enabled injected HTTP 500.",
            "source": "sre-agent",
            "source_file": "0001.json",
        },
    ]


def test_storyboard_has_ordered_explanatory_and_actual_frames(tmp_path):
    storyboard = load_module()

    outputs = storyboard.render_storyboard(
        scenario="s1",
        timeline=sample_timeline(),
        output_dir=tmp_path,
        ticket_url="https://github.com/hellices/devguidesample/issues/123",
        email_preview="s1-email-preview.png",
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert [frame["badge"] for frame in manifest["frames"]] == [
        "SCENARIO",
        "EXPECTATION",
        "ACTUAL",
        "ACTUAL",
        "ACTUAL",
        "ACTUAL",
        "OPERATIONAL OUTPUT",
    ]
    assert len(list(tmp_path.glob("*.png"))) == 7
    assert "Ticket" in manifest["frames"][-1]["body"]
    assert "Email" in manifest["frames"][-1]["body"]

    with Image.open(tmp_path / "investigation-guide.gif") as image:
        assert image.n_frames == 7
        assert image.size == (1280, 720)
    assert outputs["gif"].endswith("investigation-guide.gif")


def test_storyboard_rejects_unknown_scenario(tmp_path):
    storyboard = load_module()

    try:
        storyboard.render_storyboard(
            scenario="s4",
            timeline=sample_timeline(),
            output_dir=tmp_path,
        )
    except ValueError as exc:
        assert "unknown scenario" in str(exc)
    else:
        raise AssertionError("unknown scenario was accepted")


def test_storyboard_renders_missing_agent_states(tmp_path):
    storyboard = load_module()
    incomplete = [sample_timeline()[0]]

    storyboard.render_storyboard(
        scenario="s1",
        timeline=incomplete,
        output_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    actual_bodies = [
        frame["body"]
        for frame in manifest["frames"]
        if frame["badge"] == "ACTUAL"
    ]
    assert any("생성되지 않음" in body for body in actual_bodies)
    assert any("수집되지 않음" in body for body in actual_bodies)
    assert (tmp_path / "investigation-guide.gif").exists()


def test_storyboard_preserves_explicit_missing_state_deadline(tmp_path):
    storyboard = load_module()
    incomplete = [
        sample_timeline()[0],
        {
            "event_id": "thread-not-created",
            "timestamp": "2026-08-12T08:27:56Z",
            "state": "thread-not-created",
            "title": "Thread not created",
            "summary": "No matching thread before capture ended.",
            "source": "capture",
            "source_file": "thread-snapshots/0045.json",
        },
        {
            "event_id": "investigation-missing",
            "timestamp": "2026-08-12T08:27:56Z",
            "state": "investigation-missing",
            "title": "Investigation missing",
            "summary": "No investigation evidence before capture ended.",
            "source": "capture",
            "source_file": "thread-snapshots/0045.json",
        },
        {
            "event_id": "conclusion-missing",
            "timestamp": "2026-08-12T08:27:56Z",
            "state": "conclusion-missing",
            "title": "Conclusion missing",
            "summary": "No conclusion before capture ended.",
            "source": "capture",
            "source_file": "thread-snapshots/0045.json",
        },
    ]

    storyboard.render_storyboard(
        scenario="s1",
        timeline=incomplete,
        output_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "08:27:56Z" in serialized
    assert "thread-snapshots/0045.json" in serialized


def test_storyboard_sanitizes_sensitive_timeline_content(tmp_path):
    storyboard = load_module()
    unsafe = sample_timeline()
    unsafe[2]["summary"] += (
        " AccountKey=abc123 "
        "preferred_username=user@contoso.com "
        "https://logic.example/path?sig=verylongcallbacksigrandomvalue"
    )

    storyboard.render_storyboard(
        scenario="s1",
        timeline=unsafe,
        output_dir=tmp_path,
    )

    manifest = (tmp_path / "manifest.json").read_text()
    assert "abc123" not in manifest
    assert "user@contoso.com" not in manifest
    assert "verylongcallbacksigrandomvalue" not in manifest
    assert "[REDACTED]" in manifest


def test_storyboard_hides_resource_ids_and_thread_internals(tmp_path):
    storyboard = load_module()
    timeline = sample_timeline()
    timeline[0]["title"] = (
        "/subscriptions/95933ae5-0201-4a21-a1fc-8051a7437982/"
        "resourceGroups/rg/providers/Microsoft.Insights/"
        "scheduledQueryRules/alert-sre-lab-s1-http500"
    )
    timeline[1]["summary"] = (
        "Thread status: {'actionsStatus': {'hasCriticalActions': False}}"
    )

    storyboard.render_storyboard(
        scenario="s1",
        timeline=timeline,
        output_dir=tmp_path,
    )

    manifest = (tmp_path / "manifest.json").read_text()
    assert "95933ae5-0201-4a21-a1fc-8051a7437982" not in manifest
    assert "Thread status:" not in manifest
    assert "alert-sre-lab-s1-http500" in manifest
