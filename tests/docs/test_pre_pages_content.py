from __future__ import annotations

from dataclasses import FrozenInstanceError
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

import pytest
import yaml

from scripts.docs.pre_pages import AuditFormatError, git_text, load_inventory
from scripts.docs.pre_pages_content import (
    DocumentPreservation,
    MarkdownStructure,
    StructureFinding,
    audit_document_content,
    compare_markdown,
    extract_markdown_structure,
    write_content_review_json,
)


ROOT = Path(__file__).parents[2]
BASELINE_PATH = PurePosixPath("old/guide.md")
CURRENT_PATH = PurePosixPath("docs/services/service/topic/index.md")
REASON = (
    "Preserved in docs/services/service/topic/samples/evidence/README.md "
    "under Historical commands; the canonical guide now links to that evidence."
)


def fingerprint(category: str, value: str) -> str:
    return sha256(f"{category}\0{value}".encode("utf-8")).hexdigest()


def compare(baseline: str, current: str, reviewed=None) -> DocumentPreservation:
    return compare_markdown(
        BASELINE_PATH, CURRENT_PATH,
        extract_markdown_structure(baseline), extract_markdown_structure(current),
        reviewed or {},
    )


def test_front_matter_does_not_supply_title_or_content() -> None:
    body = "# 실제 제목\n\n한글 본문."
    assert extract_markdown_structure("\ufeff---\ntitle: metadata\nextra: ignored\n---\n" + body) == (
        extract_markdown_structure(body)
    )
    assert extract_markdown_structure("---\ntitle: metadata\n---\n").title == ""


def test_inline_links_keep_labels_not_destinations_or_titles() -> None:
    first = extract_markdown_structure(
        '# 제목\n\n[공식 문서](https://example.com/a_(b) "title") 및 [예제](../old.md).'
    )
    second = extract_markdown_structure(
        "# 제목\n\n[공식 문서](./new.md) 및 [예제](https://example.org/sample)."
    )
    assert first.prose == second.prose == ("공식 문서 및 예제.",)
    assert first.local_link_labels == ("예제",)
    assert second.local_link_labels == ("공식 문서",)


def test_reference_links_and_images_use_definitions_not_definition_prose() -> None:
    structure = extract_markdown_structure(
        "# Title\n\n[Guide][g] and [More][] and [Short].\n\n![Diagram][img]\n\n"
        "[g]: ../guide.md\n[More]: https://example.com\n[Short]: #details\n"
        '[img]: ../images/plot.svg "Caption"\n'
    )
    assert structure.prose == ("Guide and More and Short.",)
    assert structure.local_link_labels == ("Guide", "Short")
    assert structure.images == ("Diagram\nplot.svg",)


def test_comments_and_generated_wrappers_do_not_hide_their_markdown_content() -> None:
    plain = "# 제목\n\n본문.\n\n## 다음\n\n내용."
    wrapped = (
        '<!-- draft\nhidden -->\n<div class="dg-article" markdown="1">\n'
        '# 제목\n\n본문.<!-- hidden -->\n\n<section class="dg-content">\n'
        "## 다음\n\n내용.\n</section>\n</div>"
    )
    assert extract_markdown_structure(plain) == extract_markdown_structure(wrapped)


def test_html_comments_ignore_fake_fences_but_not_inline_code_literals() -> None:
    structure = extract_markdown_structure(
        "Before `<!-- literal -->` after.\n\n<!--\n```sh\nnot code\n```\n-->\n\nKept."
    )
    assert structure.prose == ("Before <!-- literal --> after.", "Kept.")
    assert structure.code == ()


def test_whitespace_line_endings_list_and_heading_numbers_normalize() -> None:
    first = "# 1. 제목\r\n\r\n단어   둘\r\n이어짐.\r\n\r\n2. 항목\r\n3) 다음\r\n\r\n## 2.3 절"
    second = "# 9) 제목\n\n단어 둘 이어짐.\n\n1) 항목\n8. 다음\n\n## 10.4. 절"
    assert extract_markdown_structure(first) == extract_markdown_structure(second)
    assert extract_markdown_structure(first).prose == ("단어 둘 이어짐.", "1. 항목", "1. 다음")


def test_nfkc_preserves_korean_text() -> None:
    structure = extract_markdown_structure("# １． 제목\n\nＡＢＣ １２３ 한글")
    assert structure.title == "제목"
    assert structure.prose == ("ABC 123 한글",)


def test_underscores_in_identifiers_are_not_emphasis_or_redaction() -> None:
    structure = extract_markdown_structure("LAB_RESOURCE_GROUP and x__y__z with _emphasis_.")
    assert structure.prose == ("LAB_RESOURCE_GROUP and x__y__z with emphasis.",)


def test_inline_code_is_literal_not_a_link_or_html_wrapper() -> None:
    structure = extract_markdown_structure("Run `[label](../real.md)` and `**literal** <span>`.")
    assert structure.prose == ("Run [label](../real.md) and **literal** <span>.",)
    assert not structure.local_link_labels


def test_heading_years_are_not_removed_as_list_numbering() -> None:
    assert extract_markdown_structure("## 2026 findings").headings == ("2026 findings",)


def test_setext_headings_have_the_same_text_as_atx_headings() -> None:
    assert extract_markdown_structure("제목\n===\n\n절\n---\n\n본문") == (
        extract_markdown_structure("# 제목\n\n## 절\n\n본문")
    )


def test_code_language_is_fingerprinted() -> None:
    result = compare("```bash\nrun\n```", "```text\nrun\n```")
    assert result.missing == (StructureFinding("code", fingerprint("code", "bash\nrun"), "bash\nrun"),)


def test_code_indentation_and_internal_spaces_are_semantic() -> None:
    before = "```python\nif True:\n    print('a  b')\n```"
    after = "```python\nif True:\n  print('a b')\n```"
    assert len(compare(before, after).missing) == 1
    assert extract_markdown_structure(before).code == ("python\nif True:\n    print('a  b')",)


def test_code_line_endings_trailing_spaces_and_fence_style_normalize() -> None:
    assert compare("```sh\r\nrun  \r\nnext\r\n```", "~~~~sh\nrun\nnext\n~~~~").status == "preserved"


def test_fences_protect_comments_markdown_and_shorter_fences_inside_code() -> None:
    structure = extract_markdown_structure(
        "````md\n# literal\n<!-- keep -->\n[x](../a.md)\n```python\nprint(1)\n```\n````"
    )
    assert structure.code == ("md\n# literal\n<!-- keep -->\n[x](../a.md)\n```python\nprint(1)\n```",)
    assert not structure.title and not structure.prose and not structure.local_link_labels


def test_unterminated_fence_does_not_discard_historical_evidence() -> None:
    assert extract_markdown_structure("```text\nlast observation").code == ("text\nlast observation",)


def test_table_separators_are_ignored_but_all_rows_remain() -> None:
    before = "| Header | 값 |\n|:---|---:|\n| A | 10 |\n| B | 20 |\n"
    after = "Header|값\n-----|-----\n A | 10\n B | 20\n"
    assert extract_markdown_structure(before).tables == ("Header | 값", "A | 10", "B | 20")
    assert compare(before, after).status == "preserved"
    result = compare(before, "| Header | 값 |\n|---|---|\n| A | 10 |")
    assert [finding.category for finding in result.missing] == ["tables"]


def test_empty_edge_table_cells_cannot_disappear_without_a_finding() -> None:
    before = "||B|\n|---|---|\n||value|"
    after = "|B|\n|---|\n|value|"
    assert compare(before, after).missing
    assert extract_markdown_structure(before).tables == (" | B", " | value")


def test_table_literal_pipes_are_not_column_delimiters() -> None:
    before = "| A | B |\n|---|---|\n| `x | y` | z |"
    structure = extract_markdown_structure(before)
    assert structure.tables[-1] == r"x \| y | z"
    after = "| A | B |\n|---|---|\n| x | y | z |"
    assert compare(before, after).missing[0].category == "tables"


def test_image_fingerprints_include_alt_and_basename_not_parent_path() -> None:
    first = "![한글 그림](../old/plot.svg?raw=true)"
    same = '![한글 그림](images/plot.svg "caption")'
    assert compare(first, same).status == "preserved"
    assert extract_markdown_structure(first).images == ("한글 그림\nplot.svg",)
    assert compare(first, "![다른 그림](images/plot.svg)").missing[0].category == "images"
    assert compare(first, "![한글 그림](images/other.svg)").missing[0].category == "images"


def test_linked_and_html_images_are_extracted_without_markup_prose() -> None:
    md = "[![Chart](images/plot.svg)](https://example.com)"
    html = '<img width="900" alt="Chart" src="../plot.svg" />'
    assert extract_markdown_structure(md).images == extract_markdown_structure(html).images
    assert not extract_markdown_structure(md).prose
    assert not extract_markdown_structure(html).prose


def test_unquoted_html_image_attributes_keep_the_alt_and_filename() -> None:
    baseline = "<img alt=diagram src=images/before.svg>"
    assert extract_markdown_structure(baseline).images == ("diagram\nbefore.svg",)
    assert compare(baseline, "<img alt=diagram src=images/after.svg>").missing


@pytest.mark.parametrize(
    ("category", "block", "value"),
    [
        ("title", "# Title", "Title"),
        ("headings", "## Heading", "Heading"),
        ("prose", "Historical observation.", "Historical observation."),
        ("code", "```bash\nrun\n```", "bash\nrun"),
        ("tables", "| Row | 20 |\n|---|---|", "Row | 20"),
        ("images", "![Evidence](images/proof.png)", "Evidence\nproof.png"),
        ("local_link_labels", "[Sample](../sample.md)", "Sample"),
    ],
)
def test_each_removed_structure_has_its_own_category_and_exact_fingerprint(
    category: str, block: str, value: str,
) -> None:
    result = compare(block, "")
    assert StructureFinding(category, fingerprint(category, value), value[:160]) in result.missing
    assert result.status == "missing"


def test_duplicate_historical_structures_require_matching_multiplicity() -> None:
    result = compare("Repeated.\n\nRepeated.\n\nRepeated.", "Repeated.\n\nRepeated.")
    assert len(result.missing) == 1
    assert result.missing[0].fingerprint == fingerprint("prose", "Repeated.")


def test_reviewed_exception_applies_only_to_the_exact_fingerprint() -> None:
    result = compare("Removed.\n\nOther.", "", {"prose": {fingerprint("prose", "Removed."): REASON}})
    assert [finding.excerpt for finding in result.reviewed] == ["Removed."]
    assert [finding.excerpt for finding in result.missing] == ["Other."]


def test_reviewed_status_requires_no_unreviewed_missing_structure() -> None:
    result = compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): REASON}})
    assert result.status == "reviewed"
    assert not result.missing and len(result.reviewed) == 1


def test_wrong_exception_category_is_stale_not_a_cross_category_approval() -> None:
    with pytest.raises(AuditFormatError, match="stale"):
        compare("## Heading", "", {"prose": {fingerprint("headings", "Heading"): REASON}})


def test_stale_exception_is_an_inventory_error_even_after_a_block_is_restored() -> None:
    with pytest.raises(AuditFormatError, match="stale"):
        compare("Kept.", "Kept.", {"prose": {fingerprint("prose", "Kept."): REASON}})


@pytest.mark.parametrize("reason", ["", " ", None, "updated", "not needed", "Preserved in sample README."])
def test_exceptions_reject_empty_or_generic_reasons(reason: object) -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): reason}})


def test_a_path_alone_does_not_make_a_generic_updated_reason_specific() -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        compare(
            "Removed.", "",
            {"prose": {fingerprint("prose", "Removed."): "Updated docs/services/service/topic/index.md."}},
        )


def test_specific_korean_preservation_reasons_are_valid() -> None:
    reason = (
        "docs/services/service/topic/samples/evidence/README.md의 이관 전 조사 명령 절에 "
        "원문을 보존하고 현재 가이드에서 그 역사적 증거로 연결한다."
    )
    result = compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): reason}})
    assert result.status == "reviewed"


@pytest.mark.parametrize("key", ["hash", "A" * 64, "g" * 64, "a" * 63, 1])
def test_inventory_rejects_non_sha256_exception_keys(tmp_path: Path, key: object) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["documents"][0]["reviewed_changes"] = {"prose": {key: REASON}}
    path = tmp_path / "inventory.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AuditFormatError, match="fingerprint"):
        load_inventory(path)


def test_inventory_rejects_unknown_exception_categories(tmp_path: Path) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["documents"][0]["reviewed_changes"] = {"anything": {"a" * 64: REASON}}
    path = tmp_path / "inventory.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AuditFormatError, match="category"):
        load_inventory(path)


def test_similarity_cannot_approve_even_a_tiny_loss() -> None:
    common = "A detailed retained observation. " * 400
    result = compare(common + "\n\nLost.", common)
    assert result.text_similarity > 0.99
    assert result.status == "missing"
    assert [finding.excerpt for finding in result.missing] == ["Lost."]


def test_finding_excerpts_are_limited_to_160_normalized_characters() -> None:
    text = "단어 " * 200
    finding = compare(text, "").missing[0]
    assert len(finding.excerpt) == 160
    assert finding.fingerprint == fingerprint("prose", text.strip())


def test_public_models_are_frozen() -> None:
    structure = extract_markdown_structure("Text.")
    result = compare("Text.", "")
    for model, field in ((structure, "title"), (result, "status"), (result.missing[0], "category")):
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, "changed")
    assert isinstance(structure, MarkdownStructure)
    assert result.baseline_path == BASELINE_PATH and result.current_path == CURRENT_PATH


def test_json_review_is_deterministic_and_preserves_unicode_and_findings(tmp_path: Path) -> None:
    results = (compare("한글.", ""), compare("Kept.", "Kept."))
    output = tmp_path / "review.json"
    write_content_review_json(output, results)
    original = output.read_bytes()
    write_content_review_json(output, results)
    assert output.read_bytes() == original
    data = json.loads(original)
    assert data["summary"]["documents"] == 2
    assert data["summary"]["missing"] == 1
    assert data["documents"][0]["baseline_path"] == str(BASELINE_PATH)
    assert data["documents"][0]["missing"][0]["excerpt"] == "한글."
    assert "한글".encode() in original


def test_real_repository_has_62_documents_and_no_unreviewed_content_losses() -> None:
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    results = audit_document_content(ROOT, inventory)
    assert len(results) == 62
    assert all((ROOT / result.current_path).is_file() for result in results)
    assert not [(str(result.baseline_path), len(result.missing)) for result in results if result.missing]


def test_historical_reader_map_preserves_all_six_detailed_audience_rows_in_owning_sample() -> None:
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    baseline = git_text(ROOT, inventory.baseline_commit, PurePosixPath("memory/agent-memory/README.md"))
    original_map = baseline.split("## 문서 구성\n", 1)[1].split("\n---", 1)[0]
    topic = ROOT / "docs/services/microsoft-foundry/agent-memory"
    sample = topic / "samples/research-artifacts/README.md"
    restored = extract_markdown_structure(sample.read_text(encoding="utf-8"))
    expected = extract_markdown_structure(original_map)
    assert len(expected.tables) == 7
    assert not (Counter(expected.tables) - Counter(restored.tables))
    assert "문서 구성" in restored.headings
    assert "samples/research-artifacts/README.md#historical-reader-map-pre-pages" in (
        (topic / "index.md").read_text(encoding="utf-8")
    )
    assert "not a current product-support statement" in sample.read_text(encoding="utf-8")
