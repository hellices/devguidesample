from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil

import pytest
import yaml

from scripts.docs import pre_pages_content
from scripts.docs.content import load_document
from scripts.docs.pre_pages import AuditFormatError, BaselineDocument, git_text, load_inventory, validate_reviewed_changes
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


def structure_evidence(
    value: str = "Replacement.", category: str = "prose", count: int = 1,
    path: str = str(CURRENT_PATH),
) -> dict:
    return {"kind": "structure", "path": path, "category": category, "fingerprint": fingerprint(category, value), "count": count}


def approval(reason=REASON, missing_count=1, evidence=None) -> dict:
    return {
        "missing_count": missing_count, "reason": reason,
        "evidence": [structure_evidence()] if evidence is None else evidence,
    }


def proof_file(repo: Path, text: str = "Replacement.", path: str = str(CURRENT_PATH)) -> Path:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    return file


def compare(baseline: str, current: str, reviewed=None, *, repo_root=None) -> DocumentPreservation:
    return compare_markdown(
        BASELINE_PATH, CURRENT_PATH,
        extract_markdown_structure(baseline), extract_markdown_structure(current),
        reviewed or {},
        **({"repo_root": repo_root} if repo_root is not None else {}),
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


@pytest.mark.parametrize("fence", ["```", "~~~"])
@pytest.mark.parametrize("prefix", ["> ", "> > ", "  >> "])
def test_quoted_fences_keep_language_newlines_indentation_and_surrounding_prose(
    fence: str, prefix: str,
) -> None:
    text = (
        f"{prefix}Before.\n\n{prefix}{fence}python\n"
        f"{prefix}if ready:\n{prefix}    print('two  spaces')\n"
        f"{prefix}\n{prefix}> literal code prefix\n{prefix}{fence}\n\n{prefix}After."
    )
    structure = extract_markdown_structure(text)
    assert structure.code == ("python\nif ready:\n    print('two  spaces')\n\n> literal code prefix",)
    assert structure.prose == ("Before.", "After.")


def test_quoted_fence_inside_indented_list_container() -> None:
    structure = extract_markdown_structure(
        "- Example:\n\n  > ```bash\n  > run first\n  >   run second\n  > ```\n\nAfter."
    )
    assert structure.code == ("bash\nrun first\n  run second",)
    assert structure.prose == ("- Example:", "After.")


def test_quoted_code_does_not_consume_prose_after_its_container_ends() -> None:
    structure = extract_markdown_structure("> ```sh\n> run\n\nOutside paragraph.")
    assert structure.code == ("sh\nrun",)
    assert structure.prose == ("Outside paragraph.",)


def test_splitting_the_real_argocd_redis_command_changes_its_code_fingerprint() -> None:
    path = ROOT / "docs/services/azure-kubernetes-service/argocd-image-updater-acr/index.md"
    text = path.read_text(encoding="utf-8")
    command = "kubectl set image deployment/argocd-redis redis=redis:8.2.3-alpine -n argocd"
    assert f"> {command}" in text
    broken = text.replace(f"> {command}", "> kubectl set image\n> deployment/argocd-redis redis=redis:8.2.3-alpine -n argocd")
    result = compare(text, broken)
    assert StructureFinding("code", fingerprint("code", f"bash\n{command}"), f"bash\n{command}") in result.missing


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


def test_reviewed_exception_applies_only_to_the_exact_fingerprint(tmp_path: Path) -> None:
    proof_file(tmp_path)
    result = compare("Removed.\n\nOther.", "Replacement.", {"prose": {fingerprint("prose", "Removed."): approval()}}, repo_root=tmp_path)
    assert [finding.excerpt for finding in result.reviewed] == ["Removed."]
    assert [finding.excerpt for finding in result.missing] == ["Other."]


def test_reviewed_status_requires_no_unreviewed_missing_structure(tmp_path: Path) -> None:
    proof_file(tmp_path)
    result = compare("Removed.", "Replacement.", {"prose": {fingerprint("prose", "Removed."): approval()}}, repo_root=tmp_path)
    assert result.status == "reviewed"
    assert not result.missing and len(result.reviewed) == 1


def test_wrong_exception_category_is_stale_not_a_cross_category_approval() -> None:
    with pytest.raises(AuditFormatError, match="stale"):
        compare("## Heading", "", {"prose": {fingerprint("headings", "Heading"): approval()}})


def test_stale_exception_is_an_inventory_error_even_after_a_block_is_restored() -> None:
    with pytest.raises(AuditFormatError, match="stale"):
        compare("Kept.", "Kept.", {"prose": {fingerprint("prose", "Kept."): approval()}})


@pytest.mark.parametrize("reason", ["", " ", None, "updated", "not needed", "Preserved in sample README."])
def test_exceptions_reject_empty_or_generic_reasons(reason: object) -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(reason)}})


def test_a_path_alone_does_not_make_a_generic_updated_reason_specific() -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        compare(
            "Removed.", "",
            {"prose": {fingerprint("prose", "Removed."): approval("Updated docs/services/service/topic/index.md.")}},
        )


def test_specific_korean_preservation_reasons_are_valid(tmp_path: Path) -> None:
    reason = (
        "docs/services/service/topic/samples/evidence/README.md의 이관 전 조사 명령 절에 "
        "원문을 보존하고 현재 가이드에서 그 역사적 증거로 연결한다."
    )
    proof_file(tmp_path)
    result = compare("Removed.", "Replacement.", {"prose": {fingerprint("prose", "Removed."): approval(reason)}}, repo_root=tmp_path)
    assert result.status == "reviewed"


@pytest.mark.parametrize("key", ["hash", "A" * 64, "g" * 64, "a" * 63, 1])
def test_inventory_rejects_non_sha256_exception_keys(tmp_path: Path, key: object) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["version"] = 2
    data["documents"][0]["reviewed_changes"] = {"prose": {key: approval()}}
    path = tmp_path / "inventory.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AuditFormatError, match="fingerprint"):
        load_inventory(path)


def test_inventory_rejects_unknown_exception_categories(tmp_path: Path) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["version"] = 2
    data["documents"][0]["reviewed_changes"] = {"anything": {"a" * 64: approval()}}
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


def isolated_real_document_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, baseline: str, current: str,
):
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    entry = next(doc for doc in inventory.documents if str(doc.baseline_path) == baseline)
    current_path = tmp_path / current
    shutil.copytree((ROOT / current).parent, current_path.parent)
    monkeypatch.setattr(
        pre_pages_content, "resolve_current_documents",
        lambda repo, manifest: {entry.baseline_path: load_document(current_path, tmp_path / "docs")},
    )
    monkeypatch.setattr(pre_pages_content, "git_text", lambda repo, commit, path: git_text(ROOT, commit, path))
    return replace(inventory, documents=(entry,)), current_path


def test_deleting_current_nginx_fence_invalidates_its_real_baseline_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aifoundry/codex_closednetwork.md",
        "docs/services/microsoft-foundry/codex-closed-network/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    text, removed = re.subn(r"```nginx\n.*?\n```", "", path.read_text(), flags=re.DOTALL)
    assert removed == 1
    path.write_text(text, encoding="utf-8")
    with pytest.raises(AuditFormatError, match="evidence"):
        audit_document_content(tmp_path, inventory)


def test_agent_memory_second_missing_06_link_cannot_reuse_one_occurrence_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "memory/agent-memory/README.md",
        "docs/services/microsoft-foundry/agent-memory/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    text = path.read_text()
    link = "[06. 커머스 적용 설계](commerce/index.md)"
    assert text.count(link) == 1
    path.write_text(text.replace(link, "06. 커머스 적용 설계"), encoding="utf-8")
    with pytest.raises(AuditFormatError, match="missing_count"):
        audit_document_content(tmp_path, inventory)


def test_generic_safety_prefix_does_not_justify_a_deletion() -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        compare("Removed.", "", {
            "prose": {fingerprint("prose", "Removed."): approval("Safety: updated and no longer needed for this content.")},
        })


def test_structured_approvals_and_references_are_deeply_immutable() -> None:
    raw = approval()
    record = BaselineDocument(BASELINE_PATH, PurePosixPath("guides/service/topic/index.md"), {
        "prose": {fingerprint("prose", "Removed."): raw},
    })
    change = record.reviewed_changes["prose"][fingerprint("prose", "Removed.")]
    assert change.missing_count == 1 and change.reason == REASON
    assert change.evidence[0].path == CURRENT_PATH
    raw["evidence"][0]["count"] = 9
    assert change.evidence[0].count == 1
    with pytest.raises(FrozenInstanceError):
        change.missing_count = 2
    with pytest.raises(FrozenInstanceError):
        change.evidence[0].count = 2


def test_bare_reason_strings_are_no_longer_approvals() -> None:
    with pytest.raises(AuditFormatError, match="approval"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): REASON}})


@pytest.mark.parametrize("field", ["missing_count", "reason", "evidence"])
def test_approval_requires_all_binding_fields(field: str) -> None:
    change = approval()
    del change[field]
    with pytest.raises(AuditFormatError, match=field):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): change}})


@pytest.mark.parametrize("count", [0, -1, True, 1.5, "1", None])
def test_missing_count_must_be_a_positive_integer(count: object) -> None:
    with pytest.raises(AuditFormatError, match="missing_count"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(missing_count=count)}})


@pytest.mark.parametrize("references", [[], {}, "current.md", None])
def test_approval_requires_a_nonempty_evidence_sequence(references: object) -> None:
    change = approval()
    change["evidence"] = references
    with pytest.raises(AuditFormatError, match="evidence"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): change}})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "unknown"), ("kind", None), ("category", "unknown"),
        ("fingerprint", "sha"), ("fingerprint", "A" * 64),
        ("count", 0), ("count", -1), ("count", True), ("count", 1.5), ("count", "1"),
        ("path", "/outside.md"), ("path", "../outside.md"), ("path", "a/../outside.md"),
        ("path", "C:/outside.md"), ("path", "a\\outside.md"), ("path", ""),
    ],
)
def test_invalid_structural_reference_fields_are_rejected(field: str, value: object) -> None:
    ref = structure_evidence()
    ref[field] = value
    with pytest.raises(AuditFormatError, match=field):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(evidence=[ref])}})


@pytest.mark.parametrize("field", ["path", "category", "fingerprint", "count", "kind"])
def test_structural_reference_requires_all_fields(field: str) -> None:
    ref = structure_evidence()
    del ref[field]
    with pytest.raises(AuditFormatError, match=field):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(evidence=[ref])}})


@pytest.mark.parametrize("kind", ["structure", "file"])
def test_duplicate_references_are_rejected_even_if_counts_or_hashes_differ(kind: str) -> None:
    if kind == "structure":
        first, second = structure_evidence(), structure_evidence(count=2)
    else:
        first = {"kind": "file", "path": "docs/evidence.bin", "sha256": "a" * 64}
        second = {**first, "sha256": "b" * 64}
    with pytest.raises(AuditFormatError, match="duplicate"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(evidence=[first, second])}})


@pytest.mark.parametrize(
    "reference",
    [
        {"kind": "file", "path": "docs/evidence.bin"},
        {"kind": "file", "path": "docs/evidence.bin", "sha256": "A" * 64},
        {"kind": "file", "path": "../evidence.bin", "sha256": "a" * 64},
        {"kind": "file", "path": "docs/evidence.bin", "sha256": "a" * 64, "count": 1},
    ],
)
def test_invalid_file_evidence_is_rejected(reference: dict) -> None:
    with pytest.raises(AuditFormatError, match="evidence"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(evidence=[reference])}})


@pytest.mark.parametrize(
    "reason",
    [
        "Safety: updated and no longer needed for this content.",
        "Safety: updated during migration and not needed anymore.",
        "Review: this document was revised and approved after migration.",
        "Reason: Safety: Updated and removed because this document is no longer needed.",
        "Preservation: updated docs/services/service/topic/index.md.",
        "안전: 이 내용은 더 이상 필요하지 않아서 업데이트하고 삭제했습니다.",
        "검토: 해당 문서를 최신 내용으로 갱신하고 불필요한 내용을 삭제했습니다.",
        "보존: docs/services/service/topic/index.md 문서의 내용을 업데이트했습니다.",
        "안전: 기존 내용에 대한 검토를 거쳐서 불필요한 부분을 적절하게 삭제했습니다.",
        "사유: 이전 문서의 이관 과정에서 일반적으로 더 이상 쓰이지 않는 항목을 정리했습니다.",
    ],
)
def test_generic_only_reasons_cannot_hide_behind_english_or_korean_prefixes(reason: str) -> None:
    with pytest.raises(AuditFormatError, match="reason"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason)}})


@pytest.mark.parametrize(
    "reason",
    [
        "The nginx reverse-proxy Host header uses the example domain while retaining the upstream port.",
        "Nginx 프록시의 Host 헤더를 예시 도메인으로 치환하고 기존 upstream 포트와 전달 설정을 보존한다.",
    ],
)
def test_concrete_reasons_do_not_need_to_repeat_paths_already_bound_as_evidence(reason: str) -> None:
    parsed = validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason)}})
    assert parsed["prose"][fingerprint("prose", "Removed.")].reason == reason


def test_one_missing_occurrence_approval_cannot_clear_two(tmp_path: Path) -> None:
    proof_file(tmp_path)
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(missing_count=1)}}
    with pytest.raises(AuditFormatError, match="missing_count"):
        compare("Removed.\n\nRemoved.", "Replacement.", reviewed, repo_root=tmp_path)


def test_exact_missing_occurrence_count_is_accepted(tmp_path: Path) -> None:
    proof_file(tmp_path)
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(missing_count=2)}}
    result = compare("Removed.\n\nRemoved.", "Replacement.", reviewed, repo_root=tmp_path)
    assert not result.missing and len(result.reviewed) == 2


def test_approvals_cannot_skip_current_evidence_verification_by_omitting_repo_root() -> None:
    with pytest.raises(AuditFormatError, match="repo_root"):
        compare("Removed.", "Replacement.", {"prose": {fingerprint("prose", "Removed."): approval()}})


@pytest.mark.parametrize("mutation", ["delete", "change", "duplicate"])
def test_structure_evidence_is_reread_and_checked_on_every_comparison(
    tmp_path: Path, mutation: str,
) -> None:
    file = proof_file(tmp_path)
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval()}}
    assert compare("Removed.", "Replacement.", reviewed, repo_root=tmp_path).status == "reviewed"
    if mutation == "delete":
        file.unlink()
    else:
        file.write_text("Changed." if mutation == "change" else "Replacement.\n\nReplacement.")
    with pytest.raises(AuditFormatError, match="evidence"):
        compare("Removed.", "Replacement.", reviewed, repo_root=tmp_path)


def test_evidence_occurrence_count_requires_the_exact_current_multiplicity(tmp_path: Path) -> None:
    file = proof_file(tmp_path, "Replacement.\n\nReplacement.")
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[structure_evidence(count=2)])}}
    assert compare("Removed.", file.read_text(), reviewed, repo_root=tmp_path).status == "reviewed"
    file.write_text("Replacement.")
    with pytest.raises(AuditFormatError, match="count"):
        compare("Removed.", file.read_text(), reviewed, repo_root=tmp_path)


@pytest.mark.parametrize("mutation", ["change", "delete"])
def test_binary_file_evidence_requires_the_exact_current_sha256(tmp_path: Path, mutation: str) -> None:
    path = tmp_path / "evidence.bin"
    original = b"\x00\xffhistorical capture"
    path.write_bytes(original)
    ref = {"kind": "file", "path": "evidence.bin", "sha256": sha256(original).hexdigest()}
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[ref])}}
    assert compare("Removed.", "", reviewed, repo_root=tmp_path).status == "reviewed"
    if mutation == "delete":
        path.unlink()
    else:
        path.write_bytes(b"\x00changed")
    with pytest.raises(AuditFormatError, match="evidence"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


@pytest.mark.parametrize("kind", ["structure", "file"])
def test_evidence_cannot_escape_the_repository_through_a_symlink(tmp_path: Path, kind: str) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    outside.write_text("Replacement.")
    (tmp_path / "link.md").symlink_to(outside)
    ref = structure_evidence(path="link.md") if kind == "structure" else {
        "kind": "file", "path": "link.md", "sha256": sha256(outside.read_bytes()).hexdigest(),
    }
    with pytest.raises(AuditFormatError, match="outside"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(evidence=[ref])}}, repo_root=tmp_path)


def test_subscription_row_approval_binds_the_subscription_not_an_unrelated_public_ip_row() -> None:
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    entry = next(d for d in inventory.documents if str(d.baseline_path) == "monitor/otel-monitor-setup.md")
    baseline = extract_markdown_structure(git_text(ROOT, inventory.baseline_commit, entry.baseline_path))
    row = next(row for row in baseline.tables if row.startswith("구독 |"))
    change = entry.reviewed_changes["tables"][fingerprint("tables", row)]
    assert any(
        ref.kind == "structure" and ref.category == "tables"
        and ref.fingerprint == fingerprint("tables", "구독 | <subscription-id>")
        for ref in change.evidence
    )


def test_each_historical_sre_thread_approval_binds_its_corresponding_scenario() -> None:
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    entry = next(d for d in inventory.documents if str(d.baseline_path) == "monitor/sre-agent-event-lab/validation-results.md")
    baseline = extract_markdown_structure(git_text(ROOT, inventory.baseline_commit, entry.baseline_path))
    threads = [value for value in baseline.prose if value.startswith("- Agent thread:")]
    assert len(threads) == 3
    for scenario, value in enumerate(threads, 1):
        change = entry.reviewed_changes["prose"][fingerprint("prose", value)]
        assert any(
            ref.kind == "structure" and ref.category == "prose"
            and ref.fingerprint == fingerprint("prose", f"- Agent thread: <agent-thread-id-s{scenario}>")
            for ref in change.evidence
        )
