import hashlib
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).parents[4]
BRIEF = REPO_ROOT / "monitor" / "azure-monitor-dynamic-thresholds-brief.md"
ASSET = REPO_ROOT / "monitor" / "assets" / "official" / "dynamic-threshold-preview-chart.png"
ARTICLE = "https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-dynamic-thresholds"
RAW_MEDIA = (
    "https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/media/"
    "alerts-dynamic-thresholds/threshold-picture-8bit.png"
)


def test_brief_uses_the_local_official_chart():
    text = BRIEF.read_text()

    assert ASSET.is_file()
    assert (
        hashlib.sha256(ASSET.read_bytes()).hexdigest()
        == "4688901b73dff95c47d6d87c6d73f774dcb613fec38b757d1a76953df098636c"
    )
    assert "assets/official/dynamic-threshold-preview-chart.png" in text
    assert RAW_MEDIA not in text
    assert (
        f"[![Screenshot that shows a metric alert preview chart with dynamic threshold: a blue line for the measured metric, a blue shaded allowed range, and red dots marking values outside that range.](assets/official/dynamic-threshold-preview-chart.png)]({ARTICLE})"
        in text
    )
    assert f"Source: [Create a Log Search alert rule with dynamic threshold]({ARTICLE})" in text


def test_official_chart_is_a_valid_1000_by_598_png():
    assert ASSET.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(ASSET) as image:
        assert image.format == "PNG"
        assert image.size == (1000, 598)
