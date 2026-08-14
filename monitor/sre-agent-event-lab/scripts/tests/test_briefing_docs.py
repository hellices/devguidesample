import re
import unicodedata
from collections import Counter
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
OFFICIAL_ASSET_PREFIX = "sre-agent-event-lab/assets/official/"


def windows_after(text: str, anchor: str, size: int = 500) -> list:
    """Return a text window following each occurrence of `anchor`.

    Used to check that groups of related keywords appear close together
    (i.e. in the same sentence/paragraph), without pinning the test to one
    exact, invented sentence.
    """
    windows = []
    start = 0
    while True:
        idx = text.find(anchor, start)
        if idx == -1:
            break
        windows.append(text[idx : idx + size])
        start = idx + 1
    return windows


UNICODE_PUNCTUATION_CATEGORIES = {"Pc", "Pd", "Pe", "Pf", "Pi", "Po", "Ps"}


def strip_code(markdown: str) -> str:
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    return re.sub(r"`[^`]*`", "", markdown)


def _is_unicode_punctuation(char) -> bool:
    return char is not None and unicodedata.category(char) in UNICODE_PUNCTUATION_CATEGORIES


def _is_unicode_whitespace(char) -> bool:
    return char is None or char.isspace()


_THEMATIC_BREAK = re.compile(r" {0,3}(?:\*[ \t]*){3,}")


def _is_list_bullet_marker(line: str, match) -> bool:
    """True when `match` is a CommonMark ``*`` list bullet, not a delimiter run.

    A single ``*`` starts a list item (and is never an emphasis delimiter)
    when it sits at up to 3 spaces of line indentation and is followed by
    whitespace or the end of the line — e.g. ``* 항목`` or ``  * item``.
    """
    if match.group() != "*":
        return False
    if not re.fullmatch(r" {0,3}", line[: match.start()]):
        return False
    after = line[match.end() : match.end() + 1]
    return after in ("", " ", "\t")


def unrendered_emphasis_markers(markdown: str) -> list:
    """Emphasis runs GitHub prints literally instead of rendering as bold/italic.

    Implements the CommonMark left/right-flanking delimiter rules. A closing
    ``**`` that follows punctuation and is glued to a letter — the common
    Korean pattern ``**굵게(bold)**을`` where a particle follows the marker —
    is not right-flanking, so it can never close emphasis and GitHub shows the
    raw asterisks to the reader. This is a general rule check, not a check for
    one known sentence.

    Block-level ``*`` markers — a list bullet (``* 항목``) or a thematic break
    line (``***``, ``* * *``) — are CommonMark structure, not inline emphasis
    delimiters, so they are excluded from the scan before it runs.
    """
    offenders = []
    for number, line in enumerate(strip_code(markdown).splitlines(), start=1):
        if _THEMATIC_BREAK.fullmatch(line):
            continue
        open_runs = []
        for match in re.finditer(r"\*+", line):
            if _is_list_bullet_marker(line, match):
                continue
            before = line[match.start() - 1] if match.start() else None
            after = line[match.end()] if match.end() < len(line) else None
            left_flanking = not _is_unicode_whitespace(after) and (
                not _is_unicode_punctuation(after)
                or _is_unicode_whitespace(before)
                or _is_unicode_punctuation(before)
            )
            right_flanking = not _is_unicode_whitespace(before) and (
                not _is_unicode_punctuation(before)
                or _is_unicode_whitespace(after)
                or _is_unicode_punctuation(after)
            )
            if right_flanking and open_runs:
                open_runs.pop()
            elif left_flanking:
                open_runs.append(match)
            else:
                offenders.append((number, match.group(), line.strip()))
        offenders.extend((number, run.group(), line.strip()) for run in open_runs)
    return offenders


def emphasis_glued_to_hangul(markdown: str) -> list:
    """Closing ``**`` markers immediately followed by a Hangul letter/particle."""
    pattern = re.compile(r"[^\s*]\*{1,2}[가-힣]")
    return [
        match.group()
        for match in pattern.finditer(strip_code(markdown))
        if _is_unicode_punctuation(match.group()[0])
    ]


def table_rows(markdown: str) -> list:
    rows = []
    for line in strip_code(markdown).splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        if re.fullmatch(r"\|[\s:\-|]+\|", line):
            continue
        cells = [
            re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell).replace("**", "").strip()
            for cell in line.strip("|").split("|")
        ]
        if len(cells) >= 2:
            rows.append(cells)
    return rows


def body_sentences(markdown: str, minimum_length: int = 30) -> list:
    """Substantive body sentences, with images, captions and code removed.

    Table cells count as body prose, so a sentence copied between a table row
    and a bullet list is detected. Short labels and fragments are ignored so
    that legitimately repeated table values do not register as duplicates.
    """
    markdown = re.sub(r"```.*?```", "", markdown, flags=re.DOTALL)
    markdown = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", markdown)
    markdown = re.sub(r"<img[^>]*>", "", markdown)

    fragments = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ">")):
            continue
        if re.fullmatch(r"\|[\s:\-|]+\|", line):
            continue
        cells = line.strip("|").split("|") if line.startswith("|") else [line]
        for cell in cells:
            cell = re.sub(r"^[-*+]\s+", "", cell.strip())
            cell = re.sub(r"^\d+\.\s+", "", cell)
            cell = re.sub(r"^\[[ x]\]\s+", "", cell)
            cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", cell)
            cell = cell.replace("**", "").replace("`", "").strip()
            if cell:
                fragments.append(cell)

    sentences = []
    for fragment in fragments:
        for sentence in re.split(r"(?<=다\.)\s+", fragment):
            sentence = re.sub(r"\s+", " ", sentence).strip()
            if len(sentence) >= minimum_length and re.search(r"(다|요)\.$", sentence):
                sentences.append(sentence)
    return sentences


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


def test_briefing_has_no_emphasis_markers_github_renders_literally():
    text = BRIEFING.read_text()

    assert unrendered_emphasis_markers(text) == [], unrendered_emphasis_markers(text)
    assert emphasis_glued_to_hangul(text) == [], emphasis_glued_to_hangul(text)


def test_emphasis_lint_catches_markers_that_commonmark_leaves_literal():
    broken = "이 기능은 **VNet 통합(VNet integration)**을 사용합니다."
    fixed = "이 기능은 **VNet 통합**(VNet integration)을 사용합니다."

    assert unrendered_emphasis_markers(broken), "lint must flag unclosable markers"
    assert emphasis_glued_to_hangul(broken), "lint must flag Hangul-glued markers"
    assert unrendered_emphasis_markers(fixed) == []
    assert emphasis_glued_to_hangul(fixed) == []
    assert unrendered_emphasis_markers("서브넷은 **/28** 이상이어야 합니다.") == []
    assert unrendered_emphasis_markers("**Azure VNet**을 선택합니다.") == []


def test_emphasis_lint_ignores_block_level_star_markers():
    """CommonMark block-level `*` markers are not emphasis delimiters.

    A `*` that starts a list item, or a line of 3+ `*` that forms a
    thematic break, must never be reported as an unclosable emphasis
    delimiter even though it is neither left- nor right-flanking under the
    inline delimiter-run rules.
    """
    assert unrendered_emphasis_markers("* 항목") == []
    assert unrendered_emphasis_markers("  * item") == []
    assert unrendered_emphasis_markers("* item") == []
    assert unrendered_emphasis_markers("***") == []
    assert unrendered_emphasis_markers("* * *") == []


def test_briefing_does_not_repeat_substantive_body_sentences():
    sentences = body_sentences(BRIEFING.read_text())
    counts = Counter(sentences)

    assert len(sentences) >= 100, "duplicate check must inspect the whole briefing"
    repeated = sorted(sentence for sentence, count in counts.items() if count > 1)
    assert repeated == [], repeated


def test_briefing_tables_do_not_repeat_row_labels_in_descriptions():
    offenders = [
        row
        for row in table_rows(BRIEFING.read_text())
        if len(row[0]) >= 8 and row[0] in row[-1]
    ]

    assert offenders == [], offenders


def test_briefing_uses_consistent_private_network_terms():
    text = BRIEFING.read_text()

    assert "비공개 네트워크" in text
    assert "프라이빗 엔드포인트" in text
    for inconsistent in (
        "사설 네트워크",
        "사설 엔드포인트",
        "개인 엔드포인트",
        "전용 엔드포인트",
        "비공개 엔드포인트",
        "프라이빗 네트워크",
    ):
        assert inconsistent not in text, inconsistent


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


def rendered_image_targets(text: str) -> list:
    """Every image target the briefing actually renders.

    Covers Markdown image syntax and any raw HTML `<img>` fallback, so a file
    can never be shown to a reader without its path being verified.
    """
    markdown_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    html_targets = re.findall(r"<img[^>]*\ssrc=[\"']([^\"']+)[\"']", text)
    return markdown_targets + html_targets


def test_briefing_uses_only_local_images_and_no_storyboards():
    text = BRIEFING.read_text()
    image_targets = rendered_image_targets(text)

    assert image_targets
    assert all(not target.startswith(("http://", "https://")) for target in image_targets)
    assert "storyboard" not in text.lower()
    assert ".gif" not in text.lower()
    for target in image_targets:
        assert (BRIEFING.parent / target).resolve().exists(), target


def test_every_official_asset_is_rendered_as_a_markdown_image():
    text = BRIEFING.read_text()
    markdown_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)
    rendered_official = {
        target.rsplit("/", 1)[-1]
        for target in markdown_targets
        if "assets/official/" in target
    }

    assert rendered_official == OFFICIAL_ASSETS, sorted(
        OFFICIAL_ASSETS - rendered_official
    )
    assert "<img" not in text, "use Markdown image syntax instead of raw HTML"
    for name in OFFICIAL_ASSETS:
        assert f"]({OFFICIAL_ASSET_PREFIX}{name})" in text, name


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
    "incident-response-flow.svg": (
        "0:00",
        "0:30",
        "1:30",
        "3:00",
        "5:00",
        "경고",
        "접수",
        "조사",
        "메트릭",
        "배포",
        "근본 원인",
        "제안",
        "자율",
        "해결",
        "작업 항목",
        "알림",
    ),
    "root-cause-analysis.svg": ("근거", "가설", "근본 원인"),
    "agent-reasoning-flow.svg": ("맥락", "추론", "승인"),
    "memory-unified-search.svg": ("과거", "문서", "검색"),
    "memory-auto-learning.svg": ("조사", "학습"),
    "custom-skill-flow.svg": ("스킬", "도구", "에이전트"),
    "diagnose-azure-services.svg": (
        "Application Insights",
        "Log Analytics",
        "Resource Graph",
        "관리 ID",
    ),
    "notification-paths.svg": ("조치", "작업 항목", "알림"),
    "incident-platform-flow.svg": ("대응 계획", "자동", "지표"),
    "knowledge-sources.svg": ("업로드", "MCP", "지식"),
    "run-modes-comparison.svg": ("검토 모드", "자율 모드", "승인"),
    "permission-flow.svg": ("관리 ID", "RBAC", "승인"),
    "azure-sre-agent-networking-vnet.png": (
        "Unrestricted",
        "Limited",
        "Azure VNet",
        "/28",
        "Microsoft.App/environments",
        "프라이빗 DNS",
        "연결됨",
        "우회",
        "MCP",
        "패키지",
        "코드 저장소",
        "추가 호스트",
    ),
    "portal-sub-agent-canvas-full.png": ("캔버스", "트리거", "도구", "자율"),
    "managed-connectors-icon-grid.png": (
        "Jira",
        "Slack",
        "GitLab",
        "Notion",
        "Asana",
        "Box",
        "Confluence",
        "OneDrive",
        "SharePoint",
        "GitHub",
        "Azure DevOps",
        "Office 365 Users",
        "Viva Engage",
        "Security Copilot",
        "Freshdesk",
        "미리 보기",
    ),
    "operations-hub-overview-tab.png": (
        "Operations Hub",
        "개요",
        "지표",
        "대기 중인 작업",
        "시스템 상태",
        "최근 7일",
        "41",
        "선택",
        "데이터가 없",
    ),
}

FORBIDDEN_ALT_CLAIMS = {
    "managed-connectors-icon-grid.png": ("Salesforce", "Google Drive"),
    "operations-hub-overview-tab.png": (
        "추이",
        "증가",
        "감소",
        "막대",
        "그래프가 그려",
    ),
    "incident-response-flow.svg": ("담당자에게 넘기", "에스컬레이션"),
}


def official_image_alt_texts() -> dict:
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]*assets/official/([^)]+))\)")
    return {
        match.group(3): match.group(1)
        for match in pattern.finditer(BRIEFING.read_text())
    }


def test_official_images_describe_themselves_in_alt_text():
    alt_texts = official_image_alt_texts()

    assert set(OFFICIAL_IMAGE_ALT_KEYWORDS) == OFFICIAL_ASSETS
    assert set(alt_texts) == OFFICIAL_ASSETS
    for name, keywords in OFFICIAL_IMAGE_ALT_KEYWORDS.items():
        alt = alt_texts[name]
        assert alt.strip(), name
        assert len(alt) >= 40, (name, alt)
        assert re.search(r"[가-힣]", alt), (name, alt)
        for keyword in keywords:
            assert keyword in alt, (name, keyword)


def test_operations_hub_alt_text_matches_the_captured_screen_state():
    alt = official_image_alt_texts()["operations-hub-overview-tab.png"]

    assert re.search(r"Operations Hub[^.]{0,40}(선택|강조)", alt), alt
    assert any(
        phrase in alt for phrase in ("선택한 기간", "선택된 기간")
    ), alt
    assert re.search(r"(표시할 )?데이터가 없", alt), alt


def test_incident_response_flow_alt_text_follows_the_diagram_timeline():
    alt = official_image_alt_texts()["incident-response-flow.svg"]

    positions = [alt.find(mark) for mark in ("0:00", "0:30", "1:30", "3:00", "5:00")]
    assert all(position >= 0 for position in positions), alt
    assert positions == sorted(positions), "timeline must be described in order"
    assert re.search(r"(제안|권고)", alt), alt
    assert "자율" in alt, alt
    assert re.search(r"(작업 항목|티켓)", alt), alt


def test_every_rendered_image_has_descriptive_korean_alt_text():
    pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    images = pattern.findall(BRIEFING.read_text())

    assert len(images) == 21, len(images)
    for alt, target in images:
        assert alt.strip(), target
        assert re.search(r"[가-힣]", alt), target


def test_image_alt_text_is_not_repeated_as_body_prose():
    text = BRIEFING.read_text()
    body = re.sub(r"\s+", " ", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text))

    repeated = []
    for alt in re.findall(r"!\[([^\]]*)\]\([^)]*\)", text):
        for sentence in body_sentences(alt):
            if sentence in body:
                repeated.append(sentence)

    assert repeated == [], repeated


def test_official_image_alt_text_does_not_claim_absent_content():
    alt_texts = official_image_alt_texts()

    for name, forbidden in FORBIDDEN_ALT_CLAIMS.items():
        alt = alt_texts[name]
        for claim in forbidden:
            assert claim not in alt, (name, claim)


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
        "업로드한 운영 문서와 MCP로 연결한 외부 지식 원본도 같은 검색 범위에 포함됩니다.",
        "조사를 마친 뒤 에이전트가 선택하는 다음 동작은 조치 실행, 작업 항목 생성, 담당자 알림 세 갈래로 나뉩니다.",
        "사용자 지정 에이전트는 포털의 Agent Canvas 화면에서 만들고 연결합니다.",
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

    connector_windows = windows_after(text, "커넥터")
    assert connector_windows, "missing connector coverage"
    assert any(
        "VNet" in window
        and any(keyword in window for keyword in ("공개 인터넷", "퍼블릭 인터넷", "인터넷 경로"))
        and any(
            keyword in window
            for keyword in ("거치지 않", "통과하지 않", "지나지 않", "라우팅되지 않", "우회")
        )
        for window in connector_windows
    ), (
        "briefing must state that connector traffic uses the public internet "
        "and does not traverse the VNet during preview"
    )

    outbound_windows = windows_after(text, "아웃바운드") + windows_after(text, "인바운드")
    assert outbound_windows, "missing outbound/inbound VNet coverage"
    assert any(
        "아웃바운드" in window
        and "인바운드" in window
        and any(
            keyword in window
            for keyword in ("지원하지 않", "지원되지 않", "지원하지 못", "미지원", "불가")
        )
        for window in outbound_windows
    ), (
        "briefing must state that VNet integration controls outbound traffic only "
        "and that inbound connections via private endpoint are unsupported in preview"
    )

    for source in (
        "https://learn.microsoft.com/azure/sre-agent/network-integration",
        "https://learn.microsoft.com/azure/sre-agent/configure-network-controls",
        "https://learn.microsoft.com/azure/sre-agent/network-requirements",
        "https://learn.microsoft.com/azure/sre-agent/allow-list-key-vault-firewall",
    ):
        assert source in text, source


def test_briefing_covers_official_vnet_operational_details():
    text = BRIEFING.read_text()

    for topic in (
        "추가 호스트",
        "*.example.com",
        "미리 설치",
        "pip",
        "NuGet",
        "Packages",
        "azuresre.ai",
        "sre.azure.com",
        "management.azure.com",
        "login.microsoftonline.com",
        "Zscaler",
        "WebSocket",
    ):
        assert topic in text, topic

    disconnect_windows = windows_after(text, "연결을 해제")
    assert disconnect_windows, "missing VNet disconnect guidance"
    assert any(
        any(keyword in window for keyword in ("모드", "Unrestricted", "Limited"))
        for window in disconnect_windows
    ), "briefing must state that the VNet must be disconnected before switching modes"
    assert any(
        "서브넷" in window for window in disconnect_windows
    ), "briefing must state that changing the subnet requires disconnecting the VNet"

    host_windows = windows_after(text, "추가 호스트")
    assert any(
        any(keyword in window for keyword in ("인프라 네트워크", "공개 인터넷"))
        for window in host_windows
    ), "briefing must state where additional hosts are routed"
    assert any(
        "패키지" in window
        and "커넥터" in window
        and any(keyword in window for keyword in ("자동으로 허용", "자동 허용"))
        for window in host_windows
    ), (
        "briefing must state that configured packages and connectors "
        "auto-allow their own hosts"
    )

    package_windows = windows_after(text, "미리 설치")
    assert any(
        any(keyword in window for keyword in ("레지스트리", "패키지 관리자", "토글"))
        for window in package_windows
    ), "briefing must present preinstalled packages as an alternative to registry access"


def test_briefing_explains_official_reasons_for_network_control():
    text = BRIEFING.read_text()

    exfiltration_windows = windows_after(text, "데이터 유출")
    assert exfiltration_windows, "briefing must state the data exfiltration risk"
    assert any(
        any(keyword in window for keyword in ("인터넷", "조직 밖", "외부로"))
        for window in exfiltration_windows
    ), "data exfiltration risk must be explained, not just named"

    injection_windows = windows_after(text, "프롬프트 인젝션")
    assert injection_windows, "briefing must state the prompt injection risk"
    assert any(
        any(keyword in window for keyword in ("조작", "악의", "공격"))
        for window in injection_windows
    ), "prompt injection risk must be explained, not just named"

    bypass_windows = windows_after(text, "토글")
    assert any(
        any(keyword in window for keyword in ("과도기", "임시", "한시적"))
        and any(keyword in window for keyword in ("FQDN", "호스트 이름"))
        and any(
            keyword in window
            for keyword in ("대신하지", "대체하지", "영구적인 해결책은 아닙니다")
        )
        for window in bypass_windows
    ), (
        "briefing must present infra network toggles as a transitional tool that "
        "does not replace hostname-aware or FQDN-based egress filtering"
    )


def test_briefing_describes_official_network_blocked_call_behavior():
    text = BRIEFING.read_text()

    blocked_windows = windows_after(text, "차단") + windows_after(text, "경로가 없")
    assert any(
        any(keyword in window for keyword in ("네트워크 오류", "연결에 실패", "시간 초과"))
        and any(keyword in window for keyword in ("조사 결과", "조사 내용", "보고"))
        for window in blocked_windows
    ), (
        "briefing must state that a blocked outbound call surfaces as a normal "
        "network error the agent reports in its investigation output"
    )
    assert any(
        any(keyword in window for keyword in ("이어", "계속"))
        and any(keyword in window for keyword in ("완전하지 않", "불완전"))
        for window in blocked_windows
    ), (
        "briefing must state that the agent continues with reachable data and "
        "reports an incomplete investigation when a critical source is blocked"
    )
