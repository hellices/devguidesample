import json
from pathlib import Path

import pytest

from scripts.docs.pre_pages import AuditFormatError
from scripts.docs.pre_pages_visibility import AuthoredContent
from scripts.docs.pre_pages_visibility import Visibility


ORACLE = json.loads((Path(__file__).parent / "fixtures/pre_pages_implied_end_chromium.json").read_text())
FOURTH_ORACLE = json.loads((Path(__file__).parent / "fixtures/pre_pages_fourth_chromium.json").read_text())


@pytest.mark.parametrize("case", ORACLE["cases"], ids=lambda case: case["id"])
def test_implied_end_visibility_and_parent_match_chromium(case):
    reader = AuthoredContent()
    reader.feed('<main id="fixture">' + case["html"] + "</main>")
    reader.close()

    def find(parent):
        for child in parent.children:
            if not isinstance(child, str):
                if child.attributes.get("id") == "public":
                    return parent, child
                if found := find(child):
                    return found
        return None

    parent, node = find(reader.root)
    assert parent.tag == case["parent"]
    assert node.evidence_visible is case["visible"]


def test_late_first_summary_element_remains_openable_per_chromium():
    case = ORACLE["late_summary"]
    assert case["first_element"] == "p" and case["after_programmatic_click"] and case["after_pointer_click"]
    reader = AuthoredContent()
    reader.feed(case["html"])
    reader.close()
    assert reader.hidden is None
    assert reader.blocks[("p", "before")] == reader.blocks[("p", "after")] == 1


@pytest.mark.parametrize("body", [
    '<p><b hidden><p id="public">Ambiguous formatting adoption',
    '<table><div hidden><tr><td id="public">Ambiguous foster parenting</td></tr></div></table>',
])
def test_unsupported_ambiguous_optional_end_recovery_fails_closed(body):
    reader = AuthoredContent()
    with pytest.raises(AuditFormatError, match="unsupported|ambiguous"):
        reader.feed(body)
        reader.close()


@pytest.mark.parametrize("container", [
    "<table>{body}</table>", "<table><tbody>{body}</tbody></table>",
    "<table><tbody><tr>{body}</tr></tbody></table>",
])
@pytest.mark.parametrize("body", ["<p>text</p>", "<div>text</div>", "text", "&nbsp;", '<a href="fake.html">text</a>'])
def test_table_foster_parenting_flow_or_text_fails_closed(container, body):
    reader = AuthoredContent()
    with pytest.raises(AuditFormatError, match="foster"):
        reader.feed(container.format(body=body))
        reader.close()


@pytest.mark.parametrize("container", [
    "<table><caption>{body}</caption></table>",
    "<table><tbody><tr><td>{body}</td></tr></tbody></table>",
    "<table><tbody><tr><th>{body}</th></tr></tbody></table>",
])
def test_table_cells_and_captions_allow_normal_flow_content(container):
    reader = AuthoredContent()
    reader.feed(container.format(body="<div><p>public</p></div>"))
    reader.close()
    assert reader.blocks[("p", "public")] == 1


@pytest.mark.parametrize("case", FOURTH_ORACLE["css"], ids=lambda case: case["id"])
def test_css_inheritance_and_restoration_match_chromium(case):
    parent = Visibility().descend({"style": "visibility:hidden!important"})
    child = parent.descend({"style": case["style"]})
    assert child.visibility_hidden is not case["visible"]


@pytest.mark.parametrize("tag", FOURTH_ORACLE["raw"])
@pytest.mark.parametrize("slash", ["", "/"])
def test_raw_and_rcdata_markup_never_creates_parent_elements(tag, slash):
    reader = AuthoredContent()
    reader.feed(
        f'<body><p>Before<{tag}{slash}><a href="fake.html">Fake</a><img src="fake.png">'
        f'<h1>Fake heading</h1></{tag}><a href="after.html">After</a></p></body>'
    )
    reader.close()
    assert reader.blocks[("h1", "Fake heading")] == 0
    assert reader.blocks[("img", "")] == 0
    assert reader.links == (["after.html"] if FOURTH_ORACLE["raw"][tag]["after_closing"] else [])


@pytest.mark.parametrize("tag", ["iframe", "noembed", "noframes"])
def test_iframe_and_fallback_text_are_not_parent_authored_content(tag):
    reader = AuthoredContent()
    reader.feed(f"<p>Before<{tag}>Fallback markup and text</{tag}>After</p>")
    reader.close()
    assert reader.blocks[("p", "BeforeAfter")] == 1
    assert not any("Fallback" in text for _, text in reader.blocks)


def test_textarea_rcdata_decodes_entities_without_parsing_the_result():
    reader = AuthoredContent()
    reader.feed('<p><textarea/>&lt;img src="fake.png"&gt;&amp; literal</textarea>After</p>')
    reader.close()
    assert reader.blocks[("p", '<img src="fake.png">& literalAfter')] == 1
    assert reader.blocks[("img", "")] == 0
