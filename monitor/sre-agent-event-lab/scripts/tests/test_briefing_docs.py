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


def test_official_images_are_placed_with_sections_and_sources():
    text = BRIEFING.read_text()
    expected = {
        "incident-response-flow.svg": "## 인시던트가 발생하면 어떻게 조사하나요?",
        "root-cause-analysis.svg": "## 근본 원인은 어떻게 찾나요?",
        "agent-reasoning-flow.svg": "## 권한과 승인 절차는 어떻게 제어하나요?",
        "memory-unified-search.svg": "## 과거 경험과 운영 문서는 어떻게 활용하나요?",
        "memory-auto-learning.svg": "## 조사가 끝난 뒤 무엇을 학습하나요?",
    }
    for image, heading in expected.items():
        assert image in text
        assert heading in text

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/incident-response",
        "https://learn.microsoft.com/azure/sre-agent/root-cause-analysis",
        "https://learn.microsoft.com/azure/sre-agent/agent-reasoning",
        "https://learn.microsoft.com/azure/sre-agent/memory",
    ):
        assert source in text


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
