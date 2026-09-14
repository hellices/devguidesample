import json
from pathlib import Path

import pytest

from scripts.docs.pre_pages import AuditFormatError
from scripts.docs.pre_pages_visibility import AuthoredContent


ORACLE = json.loads((Path(__file__).parent / "fixtures/pre_pages_implied_end_chromium.json").read_text())


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
