import hashlib
import re
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
OFFICIAL_ASSETS = {"dynamic-threshold-preview-chart.png"}
# To update this digest, download RAW_MEDIA and run:
# shasum -a 256 monitor/assets/official/dynamic-threshold-preview-chart.png
EXPECTED_ASSET_SHA256 = "4688901b73dff95c47d6d87c6d73f774dcb613fec38b757d1a76953df098636c"


def test_brief_uses_the_local_official_chart():
    text = BRIEF.read_text()

    assert ASSET.is_file()
    assert {path.name for path in ASSET.parent.iterdir()} == OFFICIAL_ASSETS

    actual_sha256 = hashlib.sha256(ASSET.read_bytes()).hexdigest()
    assert actual_sha256 == EXPECTED_ASSET_SHA256, (
        f"official chart SHA-256 changed: expected {EXPECTED_ASSET_SHA256}, "
        f"got {actual_sha256}; download {RAW_MEDIA} and verify the replacement "
        "before updating EXPECTED_ASSET_SHA256"
    )
    assert "assets/official/dynamic-threshold-preview-chart.png" in text
    assert RAW_MEDIA not in text
    linked_chart = re.search(
        rf"\[!\[(?P<alt>[^\]]+)\]"
        rf"\(assets/official/dynamic-threshold-preview-chart\.png\)\]"
        rf"\({re.escape(ARTICLE)}\)",
        text,
    )
    assert linked_chart
    alt = linked_chart.group("alt")
    assert len(alt) >= 40
    assert "dynamic threshold" in alt.lower()
    assert f"Source: [Create a Log Search alert rule with dynamic threshold]({ARTICLE})" in text


def test_official_chart_is_a_valid_1000_by_598_png():
    assert ASSET.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(ASSET) as image:
        assert image.format == "PNG"
        assert image.size == (1000, 598)
