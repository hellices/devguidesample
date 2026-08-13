import re
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
BRIEFING = REPO_ROOT / "monitor" / "azure-sre-agent.md"
OFFICIAL_SVGS = {
    "incident-response-flow.svg",
    "root-cause-analysis.svg",
    "agent-reasoning-flow.svg",
    "memory-unified-search.svg",
    "memory-auto-learning.svg",
    "custom-skill-flow.svg",
    "diagnose-azure-services.svg",
    "notification-paths.svg",
    "incident-platform-flow.svg",
    "knowledge-sources.svg",
    "run-modes-comparison.svg",
    "permission-flow.svg",
}
OFFICIAL_PNGS = {
    "azure-sre-agent-networking-vnet.png",
    "portal-sub-agent-canvas-full.png",
    "managed-connectors-icon-grid.png",
    "operations-hub-overview-tab.png",
}
OFFICIAL_ASSETS = OFFICIAL_SVGS | OFFICIAL_PNGS


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


def test_briefing_does_not_document_localization_style_sources():
    text = BRIEFING.read_text()

    for marker in (
        "한국어 문체와 용어",
        "Microsoft Korean Localization Style Guide",
        "aka.ms/korean-styleguide",
        "Microsoft Writing Style Guide",
    ):
        assert marker not in text, marker


def test_briefing_covers_adoption_critical_product_topics():
    text = BRIEFING.read_text()

    for heading in (
        "## 도입 전에 확인해야 할 사전 조건",
        "## 비용은 어떻게 발생하나요?",
        "## 보안과 데이터는 어떻게 보호되나요?",
        "## 인시던트 대응 외에 무엇을 자동화할 수 있나요?",
        "## 에이전트가 한 일을 어떻게 감사하나요?",
    ):
        assert heading in text, heading

    for topic in (
        "Azure Agent Unit",
        "Korea Central",
        "리전은 변경할 수 없습니다",
        "Agent Hooks",
        "예약 작업",
        "빠른 시작 대응 계획",
        "customEvents",
        "80개",
    ):
        assert topic in text, topic

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/pricing-billing",
        "https://learn.microsoft.com/azure/sre-agent/supported-regions",
        "https://learn.microsoft.com/azure/sre-agent/security-overview",
        "https://learn.microsoft.com/azure/sre-agent/data-privacy",
        "https://learn.microsoft.com/azure/sre-agent/agent-hooks",
        "https://learn.microsoft.com/azure/sre-agent/scheduled-tasks",
        "https://learn.microsoft.com/azure/sre-agent/audit-agent-actions",
        "https://learn.microsoft.com/azure/sre-agent/create-and-set-up",
    ):
        assert source in text, source


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
        "custom-skill-flow.svg": "## 팀에 맞게 어떻게 확장하나요?",
    }
    for image, heading in expected.items():
        assert image in text
        assert heading in text

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/incident-response",
        "https://learn.microsoft.com/azure/sre-agent/root-cause-analysis",
        "https://learn.microsoft.com/azure/sre-agent/agent-reasoning",
        "https://learn.microsoft.com/azure/sre-agent/memory",
        "https://learn.microsoft.com/azure/sre-agent/skills",
    ):
        assert source in text


OFFICIAL_IMAGE_ALT_KEYWORDS = {
    "incident-response-flow.svg": ("경고", "조사", "근본 원인"),
    "root-cause-analysis.svg": ("근거", "가설", "근본 원인"),
    "agent-reasoning-flow.svg": ("맥락", "추론", "승인"),
    "memory-unified-search.svg": ("과거", "문서", "검색"),
    "memory-auto-learning.svg": ("조사", "학습"),
    "custom-skill-flow.svg": ("스킬", "도구", "에이전트"),
}


def official_image_alt_texts() -> dict[str, str]:
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]*assets/official/([^)]+))\)")
    return {
        match.group(3): match.group(1)
        for match in pattern.finditer(BRIEFING.read_text())
    }


def test_official_images_describe_themselves_in_alt_text():
    alt_texts = official_image_alt_texts()

    assert set(alt_texts) == set(OFFICIAL_IMAGE_ALT_KEYWORDS)
    for name, keywords in OFFICIAL_IMAGE_ALT_KEYWORDS.items():
        alt = alt_texts[name]
        assert len(alt) >= 40, (name, alt)
        for keyword in keywords:
            assert keyword in alt, (name, keyword)


def test_official_images_do_not_repeat_alt_text_as_body_prose():
    text = BRIEFING.read_text()

    for source_line in (
        "> 출처: [근본 원인 분석]",
        "> 출처: [메모리와 지식 관리]",
        "> 출처: [에이전트 추론과 실행]",
    ):
        assert source_line in text

    for marker in (
        "Azure SRE Agent는 오류 로그를 나열하는 데서 멈추지 않습니다.",
        "Azure SRE Agent는 과거 조사 대화, 사용자가 기억하도록 지정한 내용",
        "에이전트는 이 흐름을 따라 판단합니다.",
        "조사가 완료되면 Azure SRE Agent는 확인한 증상",
    ):
        assert marker not in text, marker


def test_briefing_keeps_processing_time_caveat():
    text = BRIEFING.read_text()

    assert "고정된 처리 시간을 보장하지는 않습니다" in text
    assert "여러 차례 반복" in text


def test_briefing_covers_specialization_and_routing_topics():
    text = BRIEFING.read_text()

    for heading in (
        "## 팀에 맞게 어떻게 확장하나요?",
        "## 인시던트를 담당자에게 어떻게 배분하나요?",
    ):
        assert heading in text, heading

    for topic in (
        "사용자 지정 에이전트",
        "스킬",
        "최대 5개",
        "심각도",
        "영향을 받은 서비스",
        "인시던트 유형",
        "제목",
    ):
        assert topic in text, topic

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/sub-agents",
        "https://learn.microsoft.com/azure/sre-agent/skills",
    ):
        assert source in text, source


def test_briefing_marks_preview_capabilities():
    text = BRIEFING.read_text()

    managed = text.split("관리형 커넥터")[1][:200]
    assert "미리 보기" in managed


def test_official_asset_set_has_16_selected_files():
    asset_dir = (
        REPO_ROOT
        / "monitor"
        / "sre-agent-event-lab"
        / "assets"
        / "official"
    )

    assert len(OFFICIAL_ASSETS) == 16
    assert {path.name for path in asset_dir.glob("*")} == OFFICIAL_ASSETS


def test_official_sre_agent_svgs_are_stored_locally():
    asset_dir = (
        REPO_ROOT
        / "monitor"
        / "sre-agent-event-lab"
        / "assets"
        / "official"
    )

    assert {path.name for path in asset_dir.glob("*.svg")} == OFFICIAL_SVGS
    for name in OFFICIAL_SVGS:
        svg = (asset_dir / name).read_text()
        assert "<svg" in svg
        assert "learn.microsoft.com" not in svg


def test_official_sre_agent_pngs_are_stored_locally():
    asset_dir = (
        REPO_ROOT
        / "monitor"
        / "sre-agent-event-lab"
        / "assets"
        / "official"
    )

    assert {path.name for path in asset_dir.glob("*.png")} == OFFICIAL_PNGS
    for name in OFFICIAL_PNGS:
        header = (asset_dir / name).read_bytes()[:8]
        assert header == b"\x89PNG\r\n\x1a\n", name


def test_all_conceptual_svgs_are_referenced_in_briefing():
    text = BRIEFING.read_text()

    for name in OFFICIAL_SVGS:
        assert f"assets/official/{name}" in text, name


def test_all_selected_official_pngs_are_referenced_in_briefing():
    text = BRIEFING.read_text()

    for name in OFFICIAL_PNGS:
        assert f"assets/official/{name}" in text, name


def test_briefing_covers_private_network_connectivity():
    text = BRIEFING.read_text()

    assert "## 비공개 네트워크에는 어떻게 연결하나요?" in text, "missing VNet heading"

    for topic in (
        "Unrestricted",
        "Limited",
        "Azure VNet",
        "/28",
        "/26",
        "Microsoft.App/environments",
        "Network Contributor",
        "SRE Agent Administrator",
        "Use VNet's private DNS",
        "privatelink.ods.opinsights.azure.com",
        "privatelink.vaultcore.azure.net",
        "ExpressRoute",
        "VPN",
    ):
        assert topic in text, topic

    for limitation in (
        "커넥터 트래픽은 이번 미리 보기에서 VNet을 거치지 않고 공개 인터넷 경로를 사용합니다",
        "이번 미리 보기는 아웃바운드 트래픽만 제어하며 프라이빗 엔드포인트로 들어오는 인바운드 연결은 지원하지 않습니다",
    ):
        assert limitation in text, limitation

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/network-integration",
        "https://learn.microsoft.com/azure/sre-agent/configure-network-controls",
        "https://learn.microsoft.com/azure/sre-agent/network-requirements",
        "https://learn.microsoft.com/azure/sre-agent/allow-list-key-vault-firewall",
    ):
        assert source in text, source
