import importlib.util
import sys
from pathlib import Path

from PIL import Image


MODULE_PATH = Path(__file__).parents[1] / "render_briefing_assets.py"


def load_module():
    sys.path.insert(0, str(MODULE_PATH.parent))
    spec = importlib.util.spec_from_file_location("render_briefing_assets", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def timeline():
    return [
        {
            "state": "alert-fired",
            "timestamp": "2026-08-12T08:07:56Z",
            "summary": "Sev2 alert fired",
        },
        {
            "state": "thread-created",
            "timestamp": "2026-08-12T08:07:58Z",
            "summary": "Review-mode thread created",
        },
        {
            "state": "conclusion",
            "timestamp": "2026-08-12T08:10:21Z",
            "summary": "Root cause confirmed",
        },
    ]


def test_render_briefing_assets_creates_required_files(tmp_path):
    renderer = load_module()

    outputs = renderer.render_assets(timeline(), tmp_path)

    expected = (
        "sre-agent-process.svg",
        "sre-agent-process.png",
        "s1-three-panel.svg",
        "s1-three-panel.png",
        "s1-agent-conclusion.png",
    )
    for name in expected:
        assert (tmp_path / name).exists(), name

    for name in (
        "sre-agent-process.png",
        "s1-three-panel.png",
        "s1-agent-conclusion.png",
    ):
        with Image.open(tmp_path / name) as image:
            assert image.size == (1600, 900)
    assert outputs["process_png"].endswith("sre-agent-process.png")


def test_svg_diagrams_contain_required_korean_labels(tmp_path):
    renderer = load_module()
    renderer.render_assets(timeline(), tmp_path)

    process = (tmp_path / "sre-agent-process.svg").read_text()
    for label in (
        "경고 수신",
        "근거 수집",
        "가설 검증",
        "검토 및 승인",
        "티켓과 알림",
    ):
        assert label in process

    scenario = (tmp_path / "s1-three-panel.svg").read_text()
    for label in ("상황", "Agent 조사", "운영 결과"):
        assert label in scenario


def test_public_assets_do_not_expose_sensitive_identifiers(tmp_path):
    renderer = load_module()
    renderer.render_assets(timeline(), tmp_path)

    serialized = "\n".join(
        path.read_text(errors="ignore") for path in tmp_path.glob("*.svg")
    )
    assert "95933ae5-0201-4a21-a1fc-8051a7437982" not in serialized
    assert "sig=" not in serialized
    assert "Thread status:" not in serialized
