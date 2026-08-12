import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image


MODULE_PATH = Path(__file__).parents[1] / "render_capture.py"


def load_module():
    spec = importlib.util.spec_from_file_location("render_capture", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_timeline():
    states = (
        ("alert-1", "2026-08-12T05:00:00Z", "alert-fired", "Alert fired"),
        ("thread-1", "2026-08-12T05:00:30Z", "thread-created", "Thread created"),
        ("message-1", "2026-08-12T05:01:00Z", "investigating", "Checking logs"),
        ("message-2", "2026-08-12T05:02:00Z", "conclusion", "Root cause found"),
    )
    return [
        {
            "event_id": event_id,
            "timestamp": timestamp,
            "state": state,
            "title": title,
            "summary": title,
            "source": "azure-monitor" if index == 0 else "sre-agent",
            "source_file": f"thread-snapshots/{index:04d}.json",
        }
        for index, (event_id, timestamp, state, title) in enumerate(states, 1)
    ]


def test_render_capture_creates_frames_gif_and_timelines(tmp_path):
    renderer = load_module()

    outputs = renderer.render_capture(sample_timeline(), tmp_path, scenario="s1")

    frames = sorted(tmp_path.glob("*.png"))
    assert len(frames) == 4
    for frame in frames:
        with Image.open(frame) as image:
            assert image.size == (1280, 720)

    with Image.open(tmp_path / "investigation.gif") as gif:
        assert gif.n_frames == 4
        gif.seek(3)
        assert gif.info["duration"] == 3000

    mermaid = (tmp_path / "timeline.mmd").read_text()
    assert "sequenceDiagram" in mermaid
    assert "participant AzureMonitor" in mermaid
    assert "participant SREAgent" in mermaid
    assert outputs["gif"].endswith("investigation.gif")


def test_render_capture_rejects_sensitive_content(tmp_path):
    renderer = load_module()
    timeline = sample_timeline()
    timeline[2]["summary"] = "Authorization: Bearer hidden-token"

    with pytest.raises(ValueError, match="sensitive"):
        renderer.render_capture(timeline, tmp_path, scenario="s1")


def test_command_line_reads_timeline_json(tmp_path):
    renderer = load_module()
    timeline_path = tmp_path / "timeline.json"
    output_dir = tmp_path / "rendered"
    timeline_path.write_text(json.dumps(sample_timeline()))

    exit_code = renderer.main([str(timeline_path), str(output_dir), "--scenario", "s1"])

    assert exit_code == 0
    assert (output_dir / "investigation.gif").exists()


def test_renderer_limits_long_investigations_to_eight_frames(tmp_path):
    renderer = load_module()
    timeline = sample_timeline()
    investigating = timeline[2]
    timeline = timeline[:2] + [
        {
            **investigating,
            "event_id": f"investigation-{index}",
            "timestamp": f"2026-08-12T05:01:{index:02d}Z",
            "summary": f"Investigation step {index}",
        }
        for index in range(12)
    ] + [timeline[-1]]

    renderer.render_capture(timeline, tmp_path, scenario="s1")

    assert len(list(tmp_path.glob("*.png"))) <= 8
    assert all(
        line == line.rstrip()
        for line in (tmp_path / "timeline.mmd").read_text().splitlines()
    )
