import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
BRIEFING = REPO_ROOT / "monitor" / "azure-sre-agent.md"
OFFICIAL_ASSETS = {
    "incident-response-flow.svg",
    "root-cause-analysis.svg",
    "agent-reasoning-flow.svg",
    "memory-unified-search.svg",
    "memory-auto-learning.svg",
}


def prose_only(markdown: str) -> str:
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"`[^`]+`", "", markdown)
    markdown = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", markdown)
    markdown = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    markdown = re.sub(r"https?://\S+", "", markdown)
    markdown = re.sub(
        r"\b(?:Azure SRE Agent|Azure Monitor|Application Insights|"
        r"Log Analytics|Azure Resource Graph|GitHub|ServiceNow|"
        r"PagerDuty|Microsoft Teams|Outlook|Microsoft Foundry)\b",
        "",
        markdown,
        flags=re.IGNORECASE,
    )
    return markdown


def test_briefing_uses_natural_korean_terms():
    prose = prose_only(BRIEFING.read_text())
    forbidden = (
        r"\balert\b",
        r"\bincident\b",
        r"\bevidence\b",
        r"\broot cause\b",
        r"\bhypothesis\b",
        r"\bresponse plan\b",
        r"\bconnector\b",
        r"\brunbook\b",
        r"\btelemetry\b",
        r"\bmitigation\b",
        r"\bworkflow\b",
        r"\bticket\b",
        r"\bemail\b",
    )

    for pattern in forbidden:
        assert not re.search(pattern, prose, re.IGNORECASE), pattern


def test_briefing_uses_customer_facing_honorific_style():
    prose = prose_only(BRIEFING.read_text())
    explanatory_lines = [
        line.strip()
        for line in prose.splitlines()
        if line.strip()
        and not line.startswith(("#", "|", "-", "*", ">"))
        and not re.match(r"^\d+\.", line.strip())
    ]

    assert any(
        ending in prose for ending in ("합니다.", "있습니다.", "권장합니다.")
    )
    assert not any(re.search(r"(?<!니)다\.$", line) for line in explanatory_lines)


def test_briefing_uses_official_korean_localization_reference():
    text = BRIEFING.read_text()

    assert "Microsoft Korean Localization Style Guide" in text
    assert "https://aka.ms/korean-styleguide" in text


def test_briefing_uses_only_local_images_and_no_storyboards():
    text = BRIEFING.read_text()
    image_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)

    assert image_targets
    assert all(not target.startswith(("http://", "https://")) for target in image_targets)
    assert "storyboard" not in text.lower()
    assert ".gif" not in text.lower()
    for target in image_targets:
        assert (BRIEFING.parent / target).resolve().exists(), target


def test_briefing_distinguishes_product_and_lab_behavior():
    text = BRIEFING.read_text()

    for phrase in (
        "제품에서 기본으로 지원하는 방식",
        "이번 실증에서 사용한 방식",
        "검토 모드",
        "실제 연결하지 않았습니다",
    ):
        assert phrase in text


def test_official_sre_agent_svgs_are_stored_locally():
    asset_dir = (
        REPO_ROOT
        / "monitor"
        / "sre-agent-event-lab"
        / "assets"
        / "official"
    )

    assert {path.name for path in asset_dir.glob("*.svg")} == OFFICIAL_ASSETS
    for name in OFFICIAL_ASSETS:
        svg = (asset_dir / name).read_text()
        assert "<svg" in svg
        assert "learn.microsoft.com" not in svg
