from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from collections import Counter
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import unicodedata
from urllib.parse import unquote, urlsplit

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
CHROMIUM_VISIBILITY = json.loads((ROOT / "tests/docs/fixtures/pre_pages_chromium_visibility.json").read_text())
BASELINE_PATH = PurePosixPath("old/guide.md")
CURRENT_PATH = PurePosixPath("docs/services/service/topic/index.md")
REASON_TEMPLATE = (
    "The historical command parameters and execution context are preserved "
    "in the documented replacement procedure at {path}."
)
REASON = REASON_TEMPLATE.format(path=CURRENT_PATH)
_DEFAULT_REASON = object()


class RendererOracle(HTMLParser):
    """Test oracle: collect element semantics from the pinned renderer's HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parents = []
        self.anchor = None
        self.links = []
        self.images = []

    def handle_starttag(self, tag, attributes):
        blocked = any(name in {"script", "style", "code", "pre", "template", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript"} for name in self.parents)
        attrs = {}
        for name, value in attributes:
            attrs.setdefault(name, value or "")
        if not blocked and tag == "a" and "href" in attrs:
            if self.anchor is not None:
                target, parts = self.anchor
                self.links.append(f"{self.normal(''.join(parts))}\n{unicodedata.normalize('NFKC', target)}")
            self.anchor = [attrs["href"], []]
        if not blocked and tag == "img" and "src" in attrs:
            alt = self.normal(attrs.get("alt", ""))
            basename = unicodedata.normalize("NFKC", Path(unquote(urlsplit(attrs["src"]).path)).name)
            self.images.append(f"{alt}\n{basename}")
            if self.anchor is not None:
                self.anchor[1].append(alt)
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.parents.append(tag)

    def handle_startendtag(self, tag, attributes):
        self.handle_starttag(tag, attributes)
        if tag in self.parents:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if self.anchor is not None and not any(tag in {"script", "style", "template", "iframe", "noembed", "noframes", "noscript"} for tag in self.parents):
            self.anchor[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None and not any(name in {"code", "pre", "script", "style", "template"} for name in self.parents):
            target, parts = self.anchor
            self.links.append(f"{self.normal(''.join(parts))}\n{unicodedata.normalize('NFKC', target)}")
            self.anchor = None
        if tag in self.parents:
            del self.parents[len(self.parents) - 1 - self.parents[::-1].index(tag):]

    @staticmethod
    def normal(text):
        return " ".join(unicodedata.normalize("NFKC", text).split())


def renderer_oracle(source: str) -> RendererOracle:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    source = re.sub(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|$)", "", source, count=1, flags=re.DOTALL)
    html = pre_pages_content.create_semantic_renderer().convert(source)
    collector = RendererOracle()
    collector.feed(html)
    collector.close()
    return collector


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], check=True, capture_output=True,
    ).stdout


def track_files(repo: Path, *paths: str) -> None:
    if not (repo / ".git").exists():
        git(repo, "init", "-q")
        git(repo, "config", "user.name", "Evidence Tests")
        git(repo, "config", "user.email", "evidence@example.com")
    git(repo, "add", "--", *paths)
    git(repo, "-c", "commit.gpgsign=false", "commit", "-qm", "Track public evidence")


def fingerprint(category: str, value: str) -> str:
    return sha256(f"{category}\0{value}".encode("utf-8")).hexdigest()


def structure_evidence(
    value: str = "Replacement.", category: str = "prose", count: int = 1,
    path: str = str(CURRENT_PATH),
) -> dict:
    return {"kind": "structure", "path": path, "category": category, "fingerprint": fingerprint(category, value), "count": count}


def approval(reason=_DEFAULT_REASON, missing_count=1, evidence=None, link_change=None) -> dict:
    references = [structure_evidence()] if evidence is None else evidence
    if reason is _DEFAULT_REASON:
        path = references[0].get("path", CURRENT_PATH) if references and isinstance(references[0], dict) else CURRENT_PATH
        reason = REASON_TEMPLATE.format(path=path)
    result = {
        "missing_count": missing_count, "reason": reason,
        "evidence": references,
    }
    if link_change is not None:
        result["link_change"] = link_change
    return result


def proof_file(repo: Path, text: str = "Replacement.", path: str = str(CURRENT_PATH)) -> Path:
    file = repo / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    track_files(repo, path)
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


def test_link_evidence_keeps_normalized_label_and_complete_explicit_destination() -> None:
    structure = extract_markdown_structure(
        '[  가이드 Ａ  ](<../Target/index.md?q=1&amp;lang=ko#Section> "display title")'
    )
    assert structure.links == ("가이드 A\n../Target/index.md?q=1&lang=ko#Section",)


def test_link_evidence_retains_destination_differences_and_multiplicity() -> None:
    structure = extract_markdown_structure(
        "[Same](https://example.com/A?q=1#part) "
        "[Same](https://example.com/A?q=1#part) "
        "[Same](https://example.com/A?q=2#other)"
    )
    assert Counter(structure.links) == {
        "Same\nhttps://example.com/A?q=1#part": 2,
        "Same\nhttps://example.com/A?q=2#other": 1,
    }
    assert fingerprint("links", structure.links[0]) != fingerprint("links", structure.links[2])


def test_links_are_current_evidence_only_not_baseline_destination_comparison() -> None:
    before = extract_markdown_structure("[Guide](../old.md)")
    after = extract_markdown_structure("[Guide](../new.md)")
    assert before.links != after.links
    assert before.prose == after.prose
    assert compare_markdown(BASELINE_PATH, CURRENT_PATH, before, after, {}).status == "preserved"


def test_link_evidence_resolves_full_collapsed_and_shortcut_references() -> None:
    structure = extract_markdown_structure(
        "[Guide][g] [More][] [Short]\n\n"
        "[g]: ../guide.md#setup\n[More]: https://example.com/help\n[Short]: #details"
    )
    assert structure.links == (
        "Guide\n../guide.md#setup", "More\nhttps://example.com/help", "Short\n#details",
    )


def test_link_evidence_excludes_images_comments_and_code_literals() -> None:
    source = (
        "![Image](image.png) [![Logo](logo.svg)](https://example.com)\n\n"
        "![Reference image][asset]\n\n[asset]: image.svg\n\n"
        '<img src="image.png" alt="HTML image">\n\n'
        "`[Literal](literal.md)`\n\n```md\n[Code](code.md)\n```\n\n"
        "<!-- [Hidden](hidden.md) -->\n\n[Visible](visible.md)"
    )
    structure = extract_markdown_structure(source)
    assert structure.links == tuple(renderer_oracle(source).links)


def test_link_evidence_keeps_inline_code_label_text_not_placeholder_tokens() -> None:
    structure = extract_markdown_structure("[`A_B`](../target.md)")
    assert structure.links == ("A_B\n../target.md",)


@pytest.mark.parametrize("text", [
    '<a href="../target.md?a=1&amp;b=2#part"><strong>Guide</strong></a>',
    "<a href='../target.md?a=1&amp;b=2#part'>Guide</a>",
    '<a href="../target.md?a=1&amp;b=2#part">\nGuide\n</a>',
])
def test_link_evidence_recognizes_html_anchors(text: str) -> None:
    assert extract_markdown_structure(text).links == ("Guide\n../target.md?a=1&b=2#part",)


def test_link_evidence_recognizes_explicit_autolinks_but_not_placeholder_tags() -> None:
    structure = extract_markdown_structure("<https://example.com/a#b> <subscription-id>")
    assert structure.links == ("https://example.com/a#b\nhttps://example.com/a#b",)


def test_plain_label_text_is_not_link_evidence() -> None:
    assert extract_markdown_structure("tei-adapter").links == ()


@pytest.mark.parametrize("text", [
    r"\[Adapter](https://example.com/adapter)",
    "\\[Adapter][ref]\n\n[ref]: https://example.com/adapter",
    r"\<https://example.com/adapter>",
    r'\<a href="https://example.com/adapter">Adapter</a>',
])
def test_escaped_link_markup_follows_the_pinned_renderer(text: str) -> None:
    assert extract_markdown_structure(text).links == tuple(renderer_oracle(text).links)


def test_even_backslashes_before_a_link_do_not_escape_its_markup() -> None:
    assert extract_markdown_structure(r"\\[Adapter](target.md)").links == ("Adapter\ntarget.md",)


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
        "docs/services/service/topic/index.md의 이관 전 조사 명령 절에 "
        "원문을 보존하고 현재 가이드에서 그 역사적 증거로 연결한다."
    )
    proof_file(tmp_path)
    result = compare("Removed.", "Replacement.", {"prose": {fingerprint("prose", "Removed."): approval(reason)}}, repo_root=tmp_path)
    assert result.status == "reviewed"


@pytest.mark.parametrize("key", ["hash", "A" * 64, "g" * 64, "a" * 63, 1])
def test_inventory_rejects_non_sha256_exception_keys(tmp_path: Path, key: object) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["version"] = 3
    data["documents"][0]["reviewed_changes"] = {"prose": {key: approval()}}
    path = tmp_path / "inventory.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(AuditFormatError, match="fingerprint"):
        load_inventory(path)


def test_inventory_rejects_unknown_exception_categories(tmp_path: Path) -> None:
    data = yaml.safe_load((ROOT / "scripts/docs/pre_pages_inventory.yml").read_text())
    data["version"] = 3
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


def test_real_repository_preserves_the_62_baseline_documents_with_current_growth() -> None:
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
    topic = Path(*Path(current).parts[:4])
    shutil.copytree(ROOT / topic, tmp_path / topic)
    track_files(tmp_path, topic.as_posix())
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
        first = {"kind": "file", "path": "docs/services/service/topic/evidence.bin", "sha256": "a" * 64}
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
def test_concrete_reasons_must_name_an_exact_evidence_path(reason: str) -> None:
    with pytest.raises(AuditFormatError, match="reason.*path"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason)}})
    reason += f" Evidence: {CURRENT_PATH}."
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
    relative = "docs/services/service/topic/samples/evidence/payload.bin"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    original = b"\x00\xffhistorical capture"
    path.write_bytes(original)
    track_files(tmp_path, relative)
    ref = {"kind": "file", "path": relative, "sha256": sha256(original).hexdigest()}
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
    relative = "docs/services/service/topic/link.md"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)
    track_files(tmp_path, relative)
    ref = structure_evidence(path=relative) if kind == "structure" else {
        "kind": "file", "path": relative, "sha256": sha256(outside.read_bytes()).hexdigest(),
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


def test_removing_real_tei_adapter_link_markup_invalidates_its_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aisearch/custom_vectorization/01_custom_embedding_guide.md",
        "docs/services/azure-ai-search/custom-vectorization/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    link = (
        "[tei-adapter](https://github.com/hellices/devguidesample/tree/main/"
        "docs/services/azure-ai-search/custom-vectorization/samples/implementation/tei-adapter)"
    )
    text = path.read_text()
    assert text.count(link) == 1
    path.write_text(text.replace(link, "tei-adapter"))
    assert (path.parent / "samples/implementation/tei-adapter/app.py").is_file()
    with pytest.raises(AuditFormatError, match="evidence|links"):
        audit_document_content(tmp_path, inventory)


def test_ignored_baseline_snapshot_cannot_substitute_for_current_public_evidence(tmp_path: Path) -> None:
    proof_file(tmp_path)
    (tmp_path / ".gitignore").write_text(".superpowers/\n")
    snapshot = tmp_path / ".superpowers/sdd/baseline.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("Removed.")
    reason = (
        "The historical diagnostic commands are retained in .superpowers/sdd/baseline.md "
        "as replacement evidence for the removed guide section."
    )
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(
        reason, evidence=[structure_evidence("Removed.", path=".superpowers/sdd/baseline.md")],
    )}}
    with pytest.raises(AuditFormatError, match="public|eligible|forbidden|tracked"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


def test_git_metadata_cannot_be_used_as_file_evidence(tmp_path: Path) -> None:
    proof_file(tmp_path)
    metadata = tmp_path / ".git/HEAD"
    ref = {"kind": "file", "path": ".git/HEAD", "sha256": sha256(metadata.read_bytes()).hexdigest()}
    reason = (
        "The current .git/HEAD file is preserved as replacement evidence for the removed "
        "deployment procedure and its execution context."
    )
    with pytest.raises(AuditFormatError, match="public|eligible|forbidden|tracked"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(reason, evidence=[ref])}}, repo_root=tmp_path)


@pytest.mark.parametrize("include_path", [False, True])
@pytest.mark.parametrize("reason", [
    "Safety: this obsolete material is irrelevant and therefore unnecessary.",
    "Nothing significant has changed; approved after review.",
    "Replaced with a suitable equivalent for improved presentation.",
])
def test_rereview_generic_examples_are_rejected_even_with_an_exact_path(reason: str, include_path: bool) -> None:
    if include_path:
        reason += f" Evidence: {CURRENT_PATH}."
    with pytest.raises(AuditFormatError, match="reason"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason)}})


@pytest.mark.parametrize("category", ["prose", "local_link_labels", "title"])
def test_replacement_link_approvals_require_destination_bound_links_evidence(category: str) -> None:
    change = approval(evidence=[structure_evidence("Adapter", category)])
    with pytest.raises(AuditFormatError, match="links"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "Adapter"): change}})


def test_links_cannot_be_used_as_a_baseline_exception_category() -> None:
    with pytest.raises(AuditFormatError, match="category"):
        validate_reviewed_changes({"links": {fingerprint("links", "Adapter\nold.md"): approval()}})


@pytest.mark.parametrize("mutation", ["plain-label", "changed-destination", "changed-fragment"])
def test_exact_current_link_evidence_invalidates_on_markup_or_destination_changes(
    tmp_path: Path, mutation: str,
) -> None:
    current = "[Adapter](https://example.com/adapter#setup)"
    path = proof_file(tmp_path, current)
    change = approval(evidence=[structure_evidence("Adapter\nhttps://example.com/adapter#setup", "links")])
    reviewed = {"local_link_labels": {fingerprint("local_link_labels", "Adapter"): change}}
    assert compare("[Adapter](adapter.md)", current, reviewed, repo_root=tmp_path).status == "reviewed"
    changed = {
        "plain-label": "Adapter",
        "changed-destination": "[Adapter](https://example.com/other#setup)",
        "changed-fragment": "[Adapter](https://example.com/adapter#other)",
    }[mutation]
    path.write_text(changed)
    with pytest.raises(AuditFormatError, match="evidence.*links|links.*count"):
        compare("[Adapter](adapter.md)", changed, reviewed, repo_root=tmp_path)


def test_link_evidence_requires_exact_current_multiplicity(tmp_path: Path) -> None:
    current = "[Adapter](https://example.com/adapter)"
    path = proof_file(tmp_path, current + "\n\n" + current)
    change = approval(missing_count=2, evidence=[
        structure_evidence("Adapter\nhttps://example.com/adapter", "links", count=2),
    ])
    reviewed = {"local_link_labels": {fingerprint("local_link_labels", "Adapter"): change}}
    baseline = "[Adapter](adapter.md)\n\n[Adapter](adapter.md)"
    assert compare(baseline, path.read_text(), reviewed, repo_root=tmp_path).status == "reviewed"
    path.write_text(current + "\n\nAdapter")
    with pytest.raises(AuditFormatError, match="count"):
        compare(baseline, path.read_text(), reviewed, repo_root=tmp_path)


def test_duplicate_link_evidence_is_rejected_even_with_different_counts() -> None:
    first = structure_evidence("Adapter\nhttps://example.com/adapter", "links")
    change = approval(evidence=[first, {**first, "count": 2}])
    with pytest.raises(AuditFormatError, match="duplicate"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "Adapter"): change}})


@pytest.mark.parametrize("count", [0, -1, True, "1"])
def test_link_evidence_counts_must_be_positive_integers(count: object) -> None:
    change = approval(evidence=[structure_evidence("Adapter\nhttps://example.com/adapter", "links", count=count)])
    with pytest.raises(AuditFormatError, match="count"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "Adapter"): change}})


def self_link_approval() -> dict:
    return approval(
        f"The redundant self-link to this same guide is removed; its current title and Files navigation are retained in {CURRENT_PATH}.",
        evidence=[
            structure_evidence("Current guide", "title"),
            structure_evidence("Files", "headings"),
        ],
        link_change="redundant-self-link",
    )


def test_intentionally_removed_self_link_is_bound_to_current_document_identity(tmp_path: Path) -> None:
    current = "# Current guide\n\n## Files\n\nguide.md"
    proof_file(tmp_path, current)
    baseline = current.replace("\nguide.md", "\n[guide.md](guide.md)")
    reviewed = {"local_link_labels": {fingerprint("local_link_labels", "guide.md"): self_link_approval()}}
    assert compare(baseline, current, reviewed, repo_root=tmp_path).status == "reviewed"


@pytest.mark.parametrize("destination", ["other.md", "guide.md#files", "guide.md?view=text"])
def test_self_link_removal_exception_cannot_approve_another_target_or_section(
    tmp_path: Path, destination: str,
) -> None:
    current = "# Current guide\n\n## Files\n\nguide.md"
    proof_file(tmp_path, current)
    baseline = current.replace("\nguide.md", f"\n[guide.md]({destination})")
    with pytest.raises(AuditFormatError, match="self-link"):
        compare(baseline, current, {"local_link_labels": {
            fingerprint("local_link_labels", "guide.md"): self_link_approval(),
        }}, repo_root=tmp_path)


def test_self_link_removal_cannot_bind_only_an_unrelated_document(tmp_path: Path) -> None:
    current = "# Current guide\n\n## Files\n\nguide.md"
    proof_file(tmp_path, current)
    other = "docs/services/service/other/index.md"
    proof_file(tmp_path, current, other)
    change = self_link_approval()
    for reference in change["evidence"]:
        reference["path"] = other
    change["reason"] += f" Identity evidence: {other}."
    with pytest.raises(AuditFormatError, match="self-link.*current|current.*identity"):
        compare(current.replace("\nguide.md", "\n[guide.md](guide.md)"), current, {
            "local_link_labels": {fingerprint("local_link_labels", "guide.md"): change},
        }, repo_root=tmp_path)


def test_self_link_removal_requires_both_title_and_topic_structure() -> None:
    change = self_link_approval()
    change["evidence"] = change["evidence"][:1]
    with pytest.raises(AuditFormatError, match="self-link|identity"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "guide.md"): change}})


def test_self_link_removal_cannot_pretend_an_unrelated_replacement_hyperlink_exists() -> None:
    change = self_link_approval()
    change["evidence"].append(structure_evidence("Other\nother.md", "links"))
    with pytest.raises(AuditFormatError, match="self-link"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "guide.md"): change}})


def test_self_link_removal_requires_a_specific_removal_reason() -> None:
    change = self_link_approval()
    change["reason"] = f"The Nginx Host header retains the example domain and upstream port in {CURRENT_PATH}."
    with pytest.raises(AuditFormatError, match="self-link.*reason|reason.*self-link"):
        validate_reviewed_changes({"local_link_labels": {fingerprint("local_link_labels", "guide.md"): change}})


@pytest.mark.parametrize("category", ["prose", "code", "tables"])
def test_link_change_exemptions_are_invalid_on_non_link_categories(category: str) -> None:
    with pytest.raises(AuditFormatError, match="link_change"):
        validate_reviewed_changes({category: {fingerprint(category, "Removed."): self_link_approval()}})


@pytest.mark.parametrize("tracked", [False, True])
def test_ignored_public_file_is_ineligible_even_if_force_tracked_at_head(tmp_path: Path, tracked: bool) -> None:
    proof_file(tmp_path)
    relative = "docs/services/service/topic/ignored.md"
    path = tmp_path / relative
    path.write_text("Replacement.")
    (tmp_path / ".gitignore").write_text("**/ignored.md\n")
    if tracked:
        git(tmp_path, "add", "-f", "--", relative)
        git(tmp_path, "-c", "commit.gpgsign=false", "commit", "-qm", "Track ignored fixture")
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[structure_evidence(path=relative)])}}
    with pytest.raises(AuditFormatError, match="ignored|HEAD"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


@pytest.mark.parametrize("staged", [False, True])
def test_untracked_or_index_only_public_file_is_not_head_evidence(tmp_path: Path, staged: bool) -> None:
    proof_file(tmp_path)
    relative = "docs/services/service/topic/untracked.md"
    (tmp_path / relative).write_text("Replacement.")
    if staged:
        git(tmp_path, "add", "--", relative)
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[structure_evidence(path=relative)])}}
    with pytest.raises(AuditFormatError, match="HEAD"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


@pytest.mark.parametrize("relative", [
    "README.md", "scripts/snapshot.md", "baseline/guide.md",
    ".devcontainer/README.md.backup", "docs/services/service/topic/.superpowers/snapshot.md",
])
def test_head_tracked_paths_outside_the_explicit_public_allowlist_are_ineligible(
    tmp_path: Path, relative: str,
) -> None:
    proof_file(tmp_path, "Replacement.", relative)
    with pytest.raises(AuditFormatError, match="eligible|public|forbidden"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(
            evidence=[structure_evidence(path=relative)],
        )}}, repo_root=tmp_path)


def test_exact_tracked_devcontainer_readme_is_valid_and_working_tree_mutation_is_detected(tmp_path: Path) -> None:
    relative = ".devcontainer/README.md"
    file = proof_file(tmp_path, "Developer setup commands.", relative)
    ref = {"kind": "file", "path": relative, "sha256": sha256(file.read_bytes()).hexdigest()}
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[ref])}}
    assert compare("Removed.", "", reviewed, repo_root=tmp_path).status == "reviewed"
    file.write_text("Developer commands deleted.")
    with pytest.raises(AuditFormatError, match="evidence.*SHA-256"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


def test_public_tracked_symlink_cannot_resolve_to_a_private_snapshot(tmp_path: Path) -> None:
    proof_file(tmp_path)
    snapshot = tmp_path / ".superpowers/sdd/baseline.md"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("Replacement.")
    relative = "docs/services/service/topic/alias.md"
    (tmp_path / relative).symlink_to(snapshot)
    track_files(tmp_path, relative)
    with pytest.raises(AuditFormatError, match="public|eligible|forbidden|HEAD"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(
            evidence=[structure_evidence(path=relative)],
        )}}, repo_root=tmp_path)


def test_public_symlink_to_public_head_tracked_source_preserves_mutation_checks(tmp_path: Path) -> None:
    target = proof_file(tmp_path)
    relative = "docs/services/service/topic/alias.md"
    (tmp_path / relative).symlink_to(target)
    track_files(tmp_path, relative)
    reviewed = {"prose": {fingerprint("prose", "Removed."): approval(evidence=[structure_evidence(path=relative)])}}
    assert compare("Removed.", "", reviewed, repo_root=tmp_path).status == "reviewed"
    target.write_text("Changed.")
    with pytest.raises(AuditFormatError, match="evidence"):
        compare("Removed.", "", reviewed, repo_root=tmp_path)


def test_worktree_git_pointer_is_not_public_file_evidence(tmp_path: Path) -> None:
    proof_file(tmp_path)
    linked = tmp_path / "linked"
    git(tmp_path, "worktree", "add", "-q", "--detach", str(linked))
    metadata = linked / ".git"
    assert metadata.is_file()
    ref = {"kind": "file", "path": ".git", "sha256": sha256(metadata.read_bytes()).hexdigest()}
    with pytest.raises(AuditFormatError, match="public|eligible|forbidden"):
        compare("Removed.", "", {"prose": {fingerprint("prose", "Removed."): approval(
            "The exact .git worktree pointer is retained as evidence for the removed deployment procedure.",
            evidence=[ref],
        )}}, repo_root=linked)


@pytest.mark.parametrize("mentioned", [
    "docs/services/service/topic/index.md.backup",
    "docs/services/service/topic/index.md/another",
    "docs/services/service/topic/INDEX.md",
])
def test_reason_must_name_an_exact_reference_not_a_prefix_or_different_case(mentioned: str) -> None:
    reason = f"The Nginx Host header retains its example domain and upstream port in {mentioned}."
    with pytest.raises(AuditFormatError, match="reason.*path"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason)}})


def test_devcontainer_path_itself_cannot_make_a_generic_reason_concrete() -> None:
    reference = structure_evidence(path=".devcontainer/README.md")
    reason = "Safety: updated and no longer needed for this content. Evidence: .devcontainer/README.md."
    with pytest.raises(AuditFormatError, match="reason"):
        validate_reviewed_changes({"prose": {fingerprint("prose", "Removed."): approval(reason, evidence=[reference])}})


def test_real_tei_link_cannot_be_forged_inside_a_span_attribute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aisearch/custom_vectorization/01_custom_embedding_guide.md",
        "docs/services/azure-ai-search/custom-vectorization/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    destination = (
        "https://github.com/hellices/devguidesample/tree/main/docs/services/azure-ai-search/"
        "custom-vectorization/samples/implementation/tei-adapter"
    )
    link = f"[tei-adapter]({destination})"
    source = path.read_text()
    assert source.count(link) == 1
    path.write_text(source.replace(link, f'<span data-link="{link}">tei-adapter</span>'))
    with pytest.raises(AuditFormatError, match="evidence.*links|links.*count"):
        audit_document_content(tmp_path, inventory)


def test_real_s1_escaped_image_invalidates_its_current_image_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "monitor/sre-agent-event-lab/validation-results.md",
        "docs/services/azure-monitor/azure-sre-agent/validation-results/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    image = "![S1 SRE Agent investigation](images/s1-investigation.gif)"
    source = path.read_text()
    assert source.count(image) == 1
    path.write_text(source.replace(image, "\\" + image))
    with pytest.raises(AuditFormatError, match="evidence.*images|images.*count"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize("attribute", [
    'data-link="[Fake](https://example.com/fake)"',
    "data-link='[Fake](https://example.com/fake)'",
    "data-link=[Fake](https://example.com/fake)",
    'data-image="![Fake](images/fake.png)"',
    "data-image=![Fake](images/fake.png)",
    'data-auto="<https://example.com/fake>"',
    'data-reference="[Fake][ref]"',
])
@pytest.mark.parametrize("tag", ["span", "custom-widget"])
def test_markdown_evidence_is_never_scanned_inside_html_attributes(tag: str, attribute: str) -> None:
    text = f"<{tag} {attribute}>Visible</{tag}>\n\n[ref]: https://example.com/fake"
    structure = extract_markdown_structure(text)
    assert structure.links == ()
    assert structure.images == ()


def test_attribute_reference_definitions_cannot_create_links_outside_the_tag() -> None:
    structure = extract_markdown_structure(
        '<span data-definition="\n[ref]: https://example.com/fake\n">Visible</span>\n\n[ref]'
    )
    assert structure.links == ()


def test_attribute_markdown_blocks_are_masked_before_structure_extraction() -> None:
    structure = extract_markdown_structure(
        '<span data-body="\n\n## Fake heading\n\n```sh\nfake command\n```\n\n'
        '| Fake | Table |\n|---|---|\n">Visible</span>'
    )
    assert not structure.headings and not structure.code and not structure.tables


@pytest.mark.parametrize("tag", [
    "script", "style", "code", "pre", "textarea", "title", "xmp", "iframe",
    "noembed", "noframes", "template",
])
def test_raw_or_code_html_containers_do_not_supply_markdown_or_nested_html_evidence(tag: str) -> None:
    structure = extract_markdown_structure(
        f'<{tag}>[Fake](https://example.com/fake) ![Fake](images/fake.png)\n\n'
        '<a href="https://example.com/fake">Fake</a><img alt="Fake" src="images/fake.png">\n\n'
        f'```sh\nfake command\n```\n</{tag}>\n\n[Real](real.md)'
    )
    assert structure.links == ("Real\nreal.md",)
    assert structure.images == () and structure.code == ()


def test_genuine_html_anchor_uses_rendered_nested_text_and_real_href_only() -> None:
    structure = extract_markdown_structure(
        '<a data-link="[Fake](fake.md)" href="actual.md?x=1&amp;y=2#part">'
        '<span title="![Fake](fake.png)">Read</span> <strong>now</strong>'
        '<script>[Ghost](ghost.md)</script><style>![Ghost](ghost.png)</style>'
        '</a>'
    )
    assert structure.links == ("Read now\nactual.md?x=1&y=2#part",)
    assert structure.images == ()


def test_html_anchor_text_is_not_reinterpreted_as_markdown() -> None:
    structure = extract_markdown_structure(
        '<a href="actual.md"><span>**literal**</span><code>[Text](not-a-link.md)</code></a>'
    )
    assert structure.links == ("literal[Text](not-a-link.md)\nactual.md",)
    assert structure.images == ()


def test_genuine_html_image_uses_actual_alt_and_src_not_attribute_markdown() -> None:
    structure = extract_markdown_structure(
        '<img data-link="[Fake](fake.md)" data-image="![Fake](fake.png)" '
        'alt="**Literal** [label](not-link.md)" src="images/actual.png">'
    )
    assert structure.links == ()
    assert structure.images == ("**Literal** [label](not-link.md)\nactual.png",)


def test_html_anchor_and_image_attributes_keep_first_duplicate_values() -> None:
    structure = extract_markdown_structure(
        '<a href="first.md" href="second.md">Actual</a> '
        '<img alt="First" alt="Second" src="images/first.png" src="images/second.png">'
    )
    assert structure.links == ("Actual\nfirst.md",)
    assert structure.images == ("First\nfirst.png",)


def test_genuine_html_image_alt_text_labels_its_anchor() -> None:
    source = (
        '<a href="target.md"><img src="images/actual.png" alt="Actual" data-link="[Fake](fake.md)"></a>'
    )
    structure = extract_markdown_structure(source)
    expected = renderer_oracle('<a href="target.md"><img src="images/actual.png" alt="Actual"></a>')
    assert structure.links == tuple(expected.links)
    assert structure.images == ("Actual\nactual.png",)


@pytest.mark.parametrize("slashes", range(5))
@pytest.mark.parametrize("style", ["inline", "reference", "collapsed", "shortcut"])
def test_image_openers_obey_escape_parity_for_all_markdown_styles(slashes: int, style: str) -> None:
    image = {
        "inline": "![Alt](images/picture.png)",
        "reference": "![Alt][image]",
        "collapsed": "![Alt][]",
        "shortcut": "![Alt]",
    }[style]
    definitions = "\n\n[image]: images/picture.png\n[Alt]: images/picture.png"
    structure = extract_markdown_structure("\\" * slashes + image + definitions)
    assert structure.images == (("Alt\npicture.png",) if slashes % 2 == 0 else ())


@pytest.mark.parametrize("slashes", range(4))
@pytest.mark.parametrize("image", ["![Alt](images/picture.png)", "![Alt][asset]"])
def test_nested_linked_image_escape_parity(slashes: int, image: str) -> None:
    text = "[" + "\\" * slashes + image + "](target.md)\n\n[asset]: images/picture.png"
    structure = extract_markdown_structure(text)
    assert structure.images == (("Alt\npicture.png",) if slashes % 2 == 0 else ())
    assert structure.links == tuple(renderer_oracle(text).links)


def test_escaped_image_bang_leaves_an_ordinary_link_not_an_image() -> None:
    structure = extract_markdown_structure(r"\![Alt](images/picture.png)")
    assert structure.images == ()
    assert structure.links == ("Alt\nimages/picture.png",)


@pytest.mark.parametrize("tag", ["noscript", "plaintext"])
def test_additional_raw_html_containers_do_not_supply_evidence(tag: str) -> None:
    structure = extract_markdown_structure(
        f'<{tag}>[Fake](fake.md) ![Fake](fake.png) <a href="fake.md">Fake</a></{tag}>'
    )
    assert structure.links == () and structure.images == ()


def test_html_tag_tokens_inside_markdown_image_alt_or_destination_do_not_emit_elements() -> None:
    source = (
        '![Outer <img alt="Fake" src="fake.png">](outer.png) '
        '[Actual](<img>)'
    )
    structure = extract_markdown_structure(source)
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


def test_html_anchor_attributes_cannot_forge_a_closing_tag_or_child_image() -> None:
    structure = extract_markdown_structure(
        '<a href="actual.md" data-close="</a><img alt=\'Fake\' src=\'fake.png\'>">'
        '<span data-link="[Fake](fake.md)">Actual</span></a>'
    )
    assert structure.links == ("Actual\nactual.md",)
    assert structure.images == ()


def test_html_anchor_text_decodes_entities_once() -> None:
    structure = extract_markdown_structure('<a href="actual.md">&amp;lt;literal&amp;gt;</a>')
    assert structure.links == ("&lt;literal&gt;\nactual.md",)


def test_html_text_cannot_collide_with_inline_code_placeholder_tokens() -> None:
    marker = "\ue0000\ue001"
    structure = extract_markdown_structure(f'`Expected` <a href="actual.md">{marker}</a>')
    assert structure.links == (f"{marker}\nactual.md",)


@pytest.mark.parametrize("tag", ["script", "style", "code", "pre", "textarea", "noscript"])
def test_nonvoid_html_slash_does_not_expose_raw_content_to_markdown(tag: str) -> None:
    structure = extract_markdown_structure(
        f'<{tag}/>[Fake](fake.md) ![Fake](fake.png)</{tag}>\n\n[Real](real.md)'
    )
    assert structure.links == ("Real\nreal.md",)
    assert structure.images == ()


def test_self_closing_syntax_on_nonvoid_anchor_children_keeps_actual_rendered_text() -> None:
    structure = extract_markdown_structure(
        '<a href="actual.md"/>Actual<script/>[Hidden](hidden.md)</script> text</a>'
    )
    assert structure.links == ("Actual text\nactual.md",)
    assert structure.images == ()


@pytest.mark.parametrize("title", [
    "", ' "valid quoted title"', " 'valid single-quoted title'", " (valid parenthesized title)",
    " arbitrary unquoted trailing description",
])
@pytest.mark.parametrize("image", [False, True])
def test_semantic_reference_definitions_match_the_pinned_renderer(title: str, image: bool) -> None:
    marker = "!" if image else ""
    source = f"{marker}[Capture][ref]\n\n[ref]: capture.gif{title}"
    oracle = renderer_oracle(source)
    structure = extract_markdown_structure(source)
    assert structure.links == tuple(oracle.links)
    assert structure.images == tuple(oracle.images)
    expected_local = tuple(link.partition("\n")[0] for link in oracle.links if not urlsplit(link.partition("\n")[2]).scheme)
    assert structure.local_link_labels == expected_local


@pytest.mark.parametrize("source", [
    '[A](target.md "quoted title")',
    "[A](target.md 'single title')",
    "[A](target.md (parenthesized title))",
    "<https://example.com/a#b>",
    "[![Capture](capture.gif)](details.md)",
    '[Before ![Capture](capture.gif) after](details.md)',
    '<a href="details.md">Before <img src="capture.gif" alt="Capture"> after</a>',
    '<span data-link="[Fake](fake.md)">Plain</span>',
    '<code>[Fake](fake.md) ![Fake](fake.gif)</code>',
    '<script>[Fake](fake.md) ![Fake](fake.gif)</script>',
    '<style>[Fake](fake.md) ![Fake](fake.gif)</style>',
    r"\![Capture](capture.gif)",
    "`[Fake](fake.md) ![Fake](fake.gif)`",
    "`literal ``` ![Capture](capture.gif) tail`",
])
def test_semantic_elements_are_derived_from_renderer_output(source: str) -> None:
    oracle = renderer_oracle(source)
    structure = extract_markdown_structure(source)
    assert structure.links == tuple(oracle.links)
    assert structure.images == tuple(oracle.images)


@pytest.mark.parametrize(("source", "expected"), [
    ("`literal ``` ![Capture](capture.gif) tail`", "literal ``` ![Capture](capture.gif) tail"),
    ("``literal ` one ``` two``", "literal ` one ``` two"),
    ("```literal `` short ```` long```", "literal `` short ```` long"),
    ("` line one\nline  two `", "line one line  two"),
    ("``  padded  ``", " padded "),
    ("`   `", "   "),
])
def test_source_code_spans_use_exact_delimiter_runs_and_commonmark_whitespace(source: str, expected: str) -> None:
    structure = extract_markdown_structure(source)
    assert structure.prose == (expected,)
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


@pytest.mark.parametrize("source", [
    "`unmatched ![Capture](capture.gif)",
    "``unmatched `short` ![Capture](capture.gif)",
    "````unmatched ```short``` ![Capture](capture.gif)",
    "````",
])
def test_unmatched_code_span_runs_follow_renderer_image_visibility(source: str) -> None:
    structure = extract_markdown_structure(source)
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


def test_source_code_span_masks_pipes_until_an_exact_closer() -> None:
    source = "`literal ```\n| A | B |\n tail`"
    structure = extract_markdown_structure(source)
    assert structure.title == "" and structure.headings == () and structure.tables == ()
    assert structure.prose == ("literal ``` | A | B |  tail",)


def test_unmatched_inline_code_does_not_cross_real_heading_or_paragraph_boundaries() -> None:
    source = "`unmatched\n## Heading\n\n![Visible](capture.gif) tail`"
    structure = extract_markdown_structure(source)
    assert structure.headings == ("Heading",)
    assert structure.images == tuple(renderer_oracle(source).images)


def test_real_tei_malformed_reference_definition_cannot_replace_the_hyperlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aisearch/custom_vectorization/01_custom_embedding_guide.md",
        "docs/services/azure-ai-search/custom-vectorization/index.md",
    )
    destination = "https://github.com/hellices/devguidesample/tree/main/docs/services/azure-ai-search/custom-vectorization/samples/implementation/tei-adapter"
    old = f"[tei-adapter]({destination})"
    source = path.read_text()
    assert source.count(old) == 1
    changed = source.replace(old, "[tei-adapter][malformed-tei]") + f"\n\n[malformed-tei]: {destination} arbitrary unquoted description\n"
    assert f"tei-adapter\n{destination}" not in renderer_oracle(changed).links
    path.write_text(changed)
    with pytest.raises(AuditFormatError, match="evidence.*links|links.*count"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize("kind", ["image", "link", "code-span"])
def test_real_s1_inline_parser_mutations_cannot_supply_rendered_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "monitor/sre-agent-event-lab/validation-results.md",
        "docs/services/azure-monitor/azure-sre-agent/validation-results/index.md",
    )
    source = path.read_text()
    image = "![S1 SRE Agent investigation](images/s1-investigation.gif)"
    if kind == "image":
        changed = source.replace(image, "![S1 SRE Agent investigation][malformed-s1]") + "\n\n[malformed-s1]: images/s1-investigation.gif arbitrary unquoted description\n"
        assert "S1 SRE Agent investigation\ns1-investigation.gif" not in renderer_oracle(changed).images
    elif kind == "link":
        destination = "https://github.com/hellices/devguidesample/blob/main/docs/services/azure-monitor/azure-sre-agent/samples/event-lab/assets/captures/s1/07-conclusion.png"
        link = f"[결론 frame]({destination})"
        assert source.count(link) == 1
        changed = source.replace(link, "[결론 frame][malformed-s1]") + f"\n\n[malformed-s1]: {destination} arbitrary unquoted description\n"
        assert f"결론 frame\n{destination}" not in renderer_oracle(changed).links
    else:
        assert source.count(image) == 1
        changed = source.replace(image, f"`literal ``` {image} tail`")
        assert "S1 SRE Agent investigation\ns1-investigation.gif" not in renderer_oracle(changed).images
    path.write_text(changed)
    with pytest.raises(AuditFormatError, match="evidence"):
        audit_document_content(tmp_path, inventory)


def test_unrendered_memray_details_reference_is_not_a_historical_hyperlink_loss() -> None:
    inventory = load_inventory(ROOT / "scripts/docs/pre_pages_inventory.yml")
    entry = next(d for d in inventory.documents if str(d.baseline_path) == "aks/memray_leak_profiling.md")
    baseline = git_text(ROOT, inventory.baseline_commit, entry.baseline_path)
    current = (ROOT / "docs/services/azure-kubernetes-service/python-memory-leak-memray/index.md").read_text()
    for source in (baseline, current):
        oracle = renderer_oracle(source)
        assert not any(link.partition("\n")[0] == "Dockerfile" for link in oracle.links)
        assert "Dockerfile" not in extract_markdown_structure(source).local_link_labels
        assert "[Dockerfile](" in source
    assert fingerprint("local_link_labels", "Dockerfile") not in entry.reviewed_changes["local_link_labels"]
    payload = PurePosixPath("docs/services/azure-kubernetes-service/python-memory-leak-memray/samples/memray-leak-profiling/Dockerfile")
    assert any(ref.path == payload for group in entry.reviewed_changes.values() for change in group.values() for ref in change.evidence)


def test_raw_html_attribute_autolinks_do_not_change_a_genuine_anchor() -> None:
    source = '<a data-url="<https://example.com/fake>" href="actual.md">Actual</a>'
    expected = renderer_oracle('<a href="actual.md">Actual</a>')
    structure = extract_markdown_structure(source)
    assert structure.links == tuple(expected.links)


def test_malformed_reference_definition_remains_source_prose() -> None:
    source = "[Capture][ref]\n\n[ref]: capture.gif arbitrary unquoted description"
    structure = extract_markdown_structure(source)
    assert structure.prose == ("[Capture][ref]", "[ref]: capture.gif arbitrary unquoted description")
    assert structure.links == tuple(renderer_oracle(source).links)
    assert structure.images == tuple(renderer_oracle(source).images)


def test_table_code_span_escaped_pipe_is_unescaped_once_after_literal_restoration() -> None:
    source = "| Command | Result |\n|---|---|\n| `ps aux \\| grep MetricsExtension` | present |"
    structure = extract_markdown_structure(source)
    assert structure.tables[-1] == r"ps aux \| grep MetricsExtension | present"
    assert structure.links == tuple(renderer_oracle(source).links)
    assert structure.images == tuple(renderer_oracle(source).images)


def test_real_s1_src_attribute_override_invalidates_the_existing_image_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "monitor/sre-agent-event-lab/validation-results.md",
        "docs/services/azure-monitor/azure-sre-agent/validation-results/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    image = "![S1 SRE Agent investigation](images/s1-investigation.gif)"
    source = path.read_text()
    assert source.count(image) == 1
    changed = source.replace(image, image + '{: src="images/investigation.gif"}')
    path.write_text(changed)
    expected = "S1 SRE Agent investigation\ninvestigation.gif"
    assert expected in renderer_oracle(changed).images
    assert expected in extract_markdown_structure(changed).images
    with pytest.raises(AuditFormatError, match="stale.*images|evidence.*images|images.*count"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize(
    ("source", "links", "images"),
    [
        ('![S1](images/s1-investigation.gif){: src="images/investigation.gif"}', (), ("S1\ninvestigation.gif",)),
        ("[Guide](original.md){href=override.md}", ("Guide\noverride.md",), ()),
        ('[Guide](original.md){: href="override.md#part" .button}', ("Guide\noverride.md#part",), ()),
        ('![Original](images/original.png){alt="Final alt" .photo}', (), ("Final alt\noriginal.png",)),
        ('![Original](images/original.png){: src="images/final.png" alt="Final" .photo}', (), ("Final\nfinal.png",)),
        ('![Original](images/original.png){.photo width="400"}', (), ("Original\noriginal.png",)),
        ('[Guide](original.md){.button #guide title="Visible title"}', ("Guide\noriginal.md",), ()),
        ('[![Original](images/original.png){alt="Final"}](guide.md){href=final.md}', ("Final\nfinal.md",), ("Final\noriginal.png",)),
    ],
)
def test_repository_attribute_lists_define_final_element_semantics(source: str, links: tuple, images: tuple) -> None:
    structure = extract_markdown_structure(source)
    assert structure.links == links
    assert structure.images == images
    oracle = renderer_oracle(source)
    assert structure.links == tuple(oracle.links)
    assert structure.images == tuple(oracle.images)


def test_raw_html_markdown_enabled_block_uses_nested_link_and_image_attributes() -> None:
    source = (
        '<div markdown="1">\n\n'
        '[Guide](original.md){href=final.md}\n\n'
        '![Original](images/original.png){src="images/final.png" alt="Final" .photo}\n\n'
        '</div>'
    )
    structure = extract_markdown_structure(source)
    assert structure.links == ("Guide\nfinal.md",)
    assert structure.images == ("Final\nfinal.png",)
    oracle = renderer_oracle(source)
    assert structure.links == tuple(oracle.links)
    assert structure.images == tuple(oracle.images)


def test_semantic_configuration_accounts_for_every_repository_extension() -> None:
    configured = yaml.safe_load((ROOT / "mkdocs.yml").read_text())["markdown_extensions"]
    site = {}
    for entry in configured:
        if isinstance(entry, str):
            site[entry] = {}
        else:
            site.update(entry)
    config = pre_pages_content.SEMANTIC_MARKDOWN_CONFIG
    exclusions = pre_pages_content.SEMANTIC_MARKDOWN_EXCLUSIONS
    assert {"attr_list", "md_in_html"} <= set(config["extensions"])
    assert set(config["extensions"]) == set(site) - set(exclusions)
    assert set(exclusions) == {"toc", "pymdownx.snippets"}
    assert all(exclusions.values())
    for extension in config["extensions"]:
        for key, value in site[extension].items():
            assert config["extension_configs"][extension][key] == value


def test_safe_semantic_renderer_does_not_execute_snippet_inclusion(tmp_path: Path) -> None:
    include = tmp_path / "not-an-audit-source.md"
    include.write_text("[Included](should-not-be-read.md)\n")
    source = f'--8<-- "{include.as_posix()}"'
    assert "pymdownx.snippets" not in pre_pages_content.SEMANTIC_MARKDOWN_CONFIG["extensions"]
    assert renderer_oracle(source).links == []
    assert extract_markdown_structure(source).links == ()


@pytest.mark.parametrize(("source", "category", "expected"), [
    ("＃ Title", "title", ""),
    ("＃＃ Heading", "headings", ()),
    ("＃＃ Heading", "prose", ("## Heading",)),
    ("｀｀｀text\nLiteral\n｀｀｀", "code", ()),
    ("｀｀｀text\nLiteral\n｀｀｀", "prose", ("```text Literal ```",)),
    ("～" * 3 + "\nLiteral\n" + "～" * 3, "code", ()),
    ("［Guide］(guide.md)", "links", ()),
    ("！[Capture](capture.gif)", "images", ()),
    ("！[Capture](capture.gif)", "links", ("Capture\ncapture.gif",)),
    ("！［Capture］(capture.gif)", "images", ()),
    ("｜ A ｜ B ｜\n｜---｜---｜\n｜ C ｜ D ｜", "tables", ()),
    ("Title\n＝＝＝", "title", ""),
])
def test_unicode_normalization_cannot_manufacture_markdown_syntax(source, category, expected) -> None:
    structure = extract_markdown_structure(source)
    assert getattr(structure, category) == expected
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


@pytest.mark.parametrize(("source", "category", "expected"), [
    ("# Ｔｉｔｌｅ ①", "title", "Title 1"),
    ("## Ｈｅａｄｉｎｇ ①", "headings", ("Heading 1",)),
    ("**Ｔｅｘｔ ①** `ｌｉｔｅｒａｌ`", "prose", ("Text 1 literal",)),
    ("```ｔｅｘｔ\nｃｏｄｅ ①\n```", "code", ("text\ncode 1",)),
    ("| Ａ | Ｂ |\n|---|---|\n| Ｃ｜Ｄ | ① |", "tables", ("A | B", r"C\|D | 1")),
    ("[Ｇｕｉｄｅ ①](guide.md)", "links", ("Guide 1\nguide.md",)),
    ("![Ｃａｐｔｕｒｅ ①](capture.gif)", "images", ("Capture 1\ncapture.gif",)),
    ("![Literal ！［x］](capture.gif)", "images", ("Literal ![x]\ncapture.gif",)),
    ("｀[Ｇｕｉｄｅ](guide.md)｀", "links", ("Guide\nguide.md",)),
])
def test_unicode_normalization_applies_only_to_extracted_text(source, category, expected) -> None:
    assert getattr(extract_markdown_structure(source), category) == expected
    structure = extract_markdown_structure(source)
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


def test_real_s1_fullwidth_exclamation_invalidates_the_existing_image_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "monitor/sre-agent-event-lab/validation-results.md",
        "docs/services/azure-monitor/azure-sre-agent/validation-results/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    image = "![S1 SRE Agent investigation](images/s1-investigation.gif)"
    source = path.read_text()
    assert source.count(image) == 1
    changed = source.replace(image, "！" + image[1:])
    assert "S1 SRE Agent investigation\ns1-investigation.gif" not in renderer_oracle(changed).images
    path.write_text(changed)
    with pytest.raises(AuditFormatError, match="evidence.*images|images.*count"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize("attribute", [
    "hidden", 'hidden="false"', 'aria-hidden="true"',
    'style="display:none"', 'style="visibility:hidden"',
    'style="DISPLAY: /* hidden */ none !important; display: block"',
])
@pytest.mark.parametrize("markdown_enabled", [False, True])
def test_persistently_hidden_source_wrappers_reject_authored_markdown(attribute, markdown_enabled) -> None:
    annotation = ' markdown="1"' if markdown_enabled else ""
    source = f'<section {attribute}{annotation}>\n\n<div markdown="1">\n\n# Title\n\nAuthored prose.\n\n</div>\n\n</section>'
    with pytest.raises(AuditFormatError, match="hidden.*authored|authored.*hidden"):
        extract_markdown_structure(source)


@pytest.mark.parametrize("content", [
    "Authored prose.", "# Title", "```text\nAuthored code.\n```",
    "| A | B |\n|---|---|\n| C | D |", "![Capture](capture.gif)",
])
def test_source_hidden_state_applies_to_all_authored_structures(content) -> None:
    with pytest.raises(AuditFormatError, match="hidden.*authored|authored.*hidden"):
        extract_markdown_structure(f'<div hidden markdown="1">\n\n{content}\n\n</div>')


@pytest.mark.parametrize("wrapper", [
    '<div inert markdown="1">{body}</div>',
    '<details markdown="1"><summary>Read more</summary>{body}</details>',
    '<div style="display:none;display:block" markdown="1">{body}</div>',
    '<div style="visibility:hidden" markdown="1"><div style="visibility:visible" markdown="1">{body}</div></div>',
    '<div style="--display:none;--visibility:hidden" markdown="1">{body}</div>',
    '<div aria-hidden="false" markdown="1">{body}</div>',
])
def test_source_browser_visible_prose_and_openable_details_remain_evidence(wrapper) -> None:
    source = wrapper.format(body="\n\n# Title\n\nAuthored prose.\n\n")
    structure = extract_markdown_structure(source)
    assert structure.title == "Title"
    assert any("Authored prose." in text for text in structure.prose)


def test_source_hidden_examples_in_code_and_noscript_do_not_hide_visible_prose() -> None:
    source = (
        '# Title\n\nAuthored prose.\n\n'
        '`<div hidden>Literal example</div>`\n\n'
        '<noscript><div hidden>No scripting fallback</div></noscript>'
    )
    assert extract_markdown_structure(source).title == "Title"


@pytest.mark.parametrize("attribute", [
    "hidden", 'aria-hidden="true"', 'style="display:none"', 'style="visibility:hidden"',
])
def test_real_foundry_local_hidden_source_body_cannot_pass_preservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attribute: str,
) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aifoundry/foundry_local.md",
        "docs/services/microsoft-foundry/foundry-local-air-gapped/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    source = path.read_text()
    metadata, body = source.split("\n---\n", 1)
    path.write_text(metadata + f'\n---\n\n<div {attribute} markdown="1">\n' + body + "\n</div>\n")
    with pytest.raises(AuditFormatError, match="foundry-local-air-gapped.*hidden|hidden.*foundry-local-air-gapped"):
        audit_document_content(tmp_path, inventory)


def test_hidden_svg_container_cannot_supply_source_authored_text() -> None:
    with pytest.raises(AuditFormatError, match="hidden.*authored"):
        extract_markdown_structure('# Title\n\n<svg hidden><text>Authored diagram label.</text></svg>')


@pytest.mark.parametrize(("source", "category", "expected"), [
    ("| A | B |\n|---|---|\n| C＼｜D | 1 |", "tables", ("A | B", r"C\\\|D | 1")),
    ("![Capture](images/capture？variant.gif)", "images", ("Capture\ncapture?variant.gif",)),
    ("![Capture](images/part／capture.gif)", "images", ("Capture\npart/capture.gif",)),
    ('<a href="ｈｔｔｐｓ：／／example.test/path">Guide</a>', "local_link_labels", ("Guide",)),
])
def test_unicode_cannot_manufacture_extracted_escape_or_url_syntax(source, category, expected) -> None:
    structure = extract_markdown_structure(source)
    assert getattr(structure, category) == expected
    oracle = renderer_oracle(source)
    assert structure.images == tuple(oracle.images)
    assert structure.links == tuple(oracle.links)


@pytest.mark.parametrize("container", ["details", "summary", "ancestor"])
def test_closed_inert_details_cannot_supply_hidden_source_content(container) -> None:
    source = (
        '<details markdown="1"><summary>Cannot open</summary>\n\n'
        '# Title\n\nAuthored prose.\n\n</details>'
    )
    source = f"<div inert>{source}</div>" if container == "ancestor" else source.replace(f"<{container}", f"<{container} inert")
    with pytest.raises(AuditFormatError, match="hidden.*authored"):
        extract_markdown_structure(source)


@pytest.mark.parametrize("container", ["details", "summary", "ancestor"])
def test_open_inert_details_keep_visually_visible_source_content(container) -> None:
    source = (
        '<details open markdown="1"><summary>Already open</summary>\n\n'
        '# Title\n\nAuthored prose.\n\n</details>'
    )
    source = f"<div inert>{source}</div>" if container == "ancestor" else source.replace(f"<{container}", f"<{container} inert")
    structure = extract_markdown_structure(source)
    assert structure.title == "Title"


@pytest.mark.parametrize("case", CHROMIUM_VISIBILITY["css"], ids=lambda case: case["id"])
def test_chromium_css_source_visibility_or_explicit_rejection(case) -> None:
    source = f'<section style="{escape(case["style"], quote=True)}" markdown="1">\n\n# Title\n\nAuthored prose.\n\n</section>'
    if case["audit"] == "visible":
        assert extract_markdown_structure(source).title == "Title"
    else:
        message = "inline CSS" if case["audit"] == "unsupported" else "hidden.*authored"
        with pytest.raises(AuditFormatError, match=message):
            extract_markdown_structure(source)


@pytest.mark.parametrize("case", CHROMIUM_VISIBILITY["disclosures"], ids=lambda case: case["id"])
def test_chromium_summary_descendants_determine_source_openability(case) -> None:
    source = (
        f'<div {case["ancestor"]} markdown="1"><details markdown="1">'
        f'<summary {case["summary"]}><{case["tag"]} {case["child"]}>Open</{case["tag"]}></summary>\n\n'
        '# Title\n\nAuthored prose.\n\n</details></div>'
    )
    if case["audit_open"]:
        assert extract_markdown_structure(source).title == "Title"
    else:
        with pytest.raises(AuditFormatError, match="hidden.*authored"):
            extract_markdown_structure(source)


@pytest.mark.parametrize("style", [
    "display:none;display:blo/**/ck", 'display:none;--note:";display:block;"',
    r"d\69 splay:n\6f ne", "--display:none;display:var(--display)",
])
def test_real_foundry_local_css_rejection_has_source_path(tmp_path, monkeypatch, style) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "aifoundry/foundry_local.md",
        "docs/services/microsoft-foundry/foundry-local-air-gapped/index.md",
    )
    metadata, body = path.read_text().split("\n---\n", 1)
    path.write_text(metadata + f'\n---\n\n<div style="{escape(style, quote=True)}" markdown="1">\n{body}\n</div>')
    with pytest.raises(AuditFormatError, match="foundry-local-air-gapped"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize("svg", [
    '<svg aria-hidden="true"><text>Decorative label</text><path d="M0 0h10v10z"/></svg>',
    '<svg class="md-icon" aria-hidden="true"><title>Icon</title><path d="M0 0h10v10z"/></svg>',
    '<svg><defs><text>Definition, not a painted label</text></defs><path d="M0 0h10v10z"/></svg>',
    '<svg><g aria-hidden="true"><text>Decorative group label</text></g></svg>',
    '<svg><text aria-hidden="true">Decorative text label</text></svg>',
])
def test_decorative_svg_does_not_supply_or_hide_authored_source_content(svg) -> None:
    assert extract_markdown_structure("# Title\n\nAuthored prose.\n\n" + svg).title == "Title"


def test_late_inert_summary_cannot_expose_earlier_source_body() -> None:
    with pytest.raises(AuditFormatError, match="hidden.*authored"):
        extract_markdown_structure(
            '<details markdown="1">\n\n# Title\n\nAuthored prose.\n\n'
            '<summary inert>Cannot open</summary></details>'
        )


@pytest.mark.parametrize("style", CHROMIUM_VISIBILITY["unresolved_css"])
def test_unresolved_inline_css_fails_closed_in_source(style) -> None:
    with pytest.raises(AuditFormatError, match="inline CSS"):
        extract_markdown_structure(
            f'<div style="{escape(style, quote=True)}" markdown="1">\n\n# Title\n\nAuthored prose.\n\n</div>'
        )


@pytest.mark.parametrize("attribute", ['visibility="hidden"', 'display="none"'])
def test_authored_svg_presentation_hiding_is_not_visible_source(attribute) -> None:
    with pytest.raises(AuditFormatError, match="hidden.*authored"):
        extract_markdown_structure(f'<svg><text {attribute}>Authored diagram label</text></svg>')


def test_inline_svg_visibility_overrides_the_presentation_attribute() -> None:
    source = '<svg><text visibility="hidden" style="visibility:visible">Authored diagram label</text></svg>'
    assert extract_markdown_structure(source).prose


@pytest.mark.parametrize("wrapper", [
    '<svg aria-hidden="true" style="display:none"><foreignObject>{content}</foreignObject></svg>',
    '<svg aria-hidden="true"><foreignObject>{content}</foreignObject></svg>',
    '<svg role="presentation"><foreignObject>{content}</foreignObject></svg>',
    '<svg class="md-icon"><foreignObject>{content}</foreignObject></svg>',
    '<svg><defs><foreignObject>{content}</foreignObject></defs></svg>',
    '<svg><g aria-hidden="true"><foreignObject>{content}</foreignObject></g></svg>',
])
def test_excluded_svg_cannot_supply_semantic_link_or_image_evidence(wrapper) -> None:
    content = '<a href="guide.md"><img alt="Capture" src="capture.gif"></a>'
    structure = extract_markdown_structure(wrapper.format(content=content))
    assert structure.images == ()
    assert structure.links == structure.local_link_labels == ()


@pytest.mark.parametrize("image", [
    "![Capture](capture.gif)",
    '<img alt="Capture" src="capture.gif">',
    '<svg width="300" height="200"><foreignObject width="300" height="200"><img alt="Capture" src="capture.gif"></foreignObject></svg>',
])
def test_visible_images_still_supply_exact_evidence_beside_excluded_svg(image) -> None:
    hidden = (
        '<svg aria-hidden="true" style="display:none"><foreignObject>'
        '<img alt="Capture" src="capture.gif"></foreignObject></svg>'
    )
    assert extract_markdown_structure(hidden + "\n\n" + image).images == ("Capture\ncapture.gif",)


def test_excluded_svg_alt_text_cannot_forge_the_surrounding_link_label() -> None:
    source = (
        '<a href="guide.md">Visible'
        '<svg aria-hidden="true" style="display:none"><foreignObject>'
        '<img alt="Hidden" src="capture.gif"></foreignObject></svg></a>'
    )
    structure = extract_markdown_structure(source)
    assert structure.links == ("Visible\nguide.md",)
    assert structure.images == ()


def test_semantic_link_can_use_a_visible_descendant_of_a_hidden_visibility_anchor() -> None:
    source = '<a style="visibility:hidden" href="guide.md"><span style="visibility:visible">Guide</span></a>'
    assert extract_markdown_structure(source).links == ("Guide\nguide.md",)


def test_semantic_link_cannot_use_only_an_inert_descendant_as_evidence() -> None:
    assert extract_markdown_structure('<a href="guide.md"><span inert>Guide</span></a>').links == ()


def test_real_s1_hidden_svg_image_cannot_satisfy_its_preservation_approval(tmp_path, monkeypatch) -> None:
    inventory, path = isolated_real_document_audit(
        tmp_path, monkeypatch, "monitor/sre-agent-event-lab/validation-results.md",
        "docs/services/azure-monitor/azure-sre-agent/validation-results/index.md",
    )
    assert not audit_document_content(tmp_path, inventory)[0].missing
    source = path.read_text()
    image = "![S1 SRE Agent investigation](images/s1-investigation.gif)"
    assert source.count(image) == 1
    hidden = (
        '<svg aria-hidden="true" style="display:none"><foreignObject>'
        '<img alt="S1 SRE Agent investigation" src="images/s1-investigation.gif">'
        '</foreignObject></svg>'
    )
    path.write_text(source.replace(image, hidden))
    with pytest.raises(AuditFormatError, match="evidence.*images|images.*count"):
        audit_document_content(tmp_path, inventory)


@pytest.mark.parametrize("prefix", ["", "<div><summary>Not a direct summary</summary></div>"])
def test_closed_details_without_authored_summary_use_the_native_control(prefix):
    assert extract_markdown_structure(
        f'<details markdown="1">{prefix}\n\n# Title\n\nAuthored prose.\n\n</details>'
    ).title == "Title"


def test_already_open_details_without_summary_keep_visible_source_evidence():
    assert extract_markdown_structure(
        '<details open markdown="1">\n\n# Title\n\nAuthored prose.\n\n</details>'
    ).title == "Title"


def test_source_late_first_summary_element_is_openable():
    structure = extract_markdown_structure(
        '<details markdown="1"><p>before</p><summary>Late</summary>\n\n# Title\n\nAuthored prose.\n\n</details>'
    )
    assert structure.title == "Title"


@pytest.mark.parametrize("html", [
    "<p hidden><p>public",
    "<p hidden><div>public</div>",
    "<ul><li hidden><li>public</ul>",
    "<dl><dt hidden><dd>public</dl>",
    "<table><tbody><tr><td hidden><td>public</table>",
    '<select multiple><option hidden><option>public</select>',
])
def test_source_optional_end_tags_do_not_extend_hidden_ancestors(html):
    assert extract_markdown_structure(html).prose


@pytest.mark.parametrize("source", [
    "<table hidden><p>text</p></table>",
    "<table><tbody><div>text</div></tbody></table>",
    "<table><tbody><tr>text</tr></tbody></table>",
])
def test_source_table_foster_ambiguity_is_an_explicit_error(source):
    with pytest.raises(AuditFormatError, match="foster"):
        extract_markdown_structure(source)


@pytest.mark.parametrize("tag", ["textarea", "xmp", "iframe", "noembed", "noframes", "plaintext"])
def test_source_raw_container_trailing_markup_cannot_be_promoted(tag):
    source = (
        f'<{tag}/><a href="fake.md">Fake</a><img src="fake.png" alt="Fake"></{tag}>'
        '<a href="after.md">After</a>'
    )
    structure = extract_markdown_structure(source)
    assert structure.images == ()
    assert structure.links == (() if tag == "plaintext" else ("After\nafter.md",))


DEFAULT_SUMMARY_ORACLE = json.loads((ROOT / "tests/docs/fixtures/pre_pages_default_summary_chromium.json").read_text())


@pytest.mark.parametrize("case", DEFAULT_SUMMARY_ORACLE["cases"], ids=lambda case: case["id"])
def test_native_summaryless_source_visibility_inherits_blockers(case):
    source = (
        f'<div {case["ancestor"]} markdown="1"><details markdown="1">\n\n'
        '# Title\n\n[Visible link](guide.md)\n\n</details></div>'
    )
    if case["audit_open"]:
        structure = extract_markdown_structure(source)
        assert structure.title == "Title" and structure.links == ("Visible link\nguide.md",)
    else:
        with pytest.raises(AuditFormatError, match="hidden.*authored"):
            extract_markdown_structure(source)


def test_open_summaryless_inert_source_remains_visually_visible():
    structure = extract_markdown_structure(
        '<div inert markdown="1"><details open markdown="1">\n\n# Title\n\nVisible prose.\n\n</details></div>'
    )
    assert structure.title == "Title"
