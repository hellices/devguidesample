"""Contract tests for the repository README's lab index.

The root README is where someone arriving at this repository looks first,
so a lab that can actually be deployed and run has to be reachable from
there. These tests keep that index honest as labs are added: every runnable
lab is listed exactly once, every link resolves, and the columns a reader
uses to decide whether to start (cost, time) are filled in.

A "runnable lab" is defined the same way the repository already
distinguishes one: a directory with its own `azure.yaml`, i.e. something
`azd up` can provision. Documentation-only guides are not labs and are not
listed here.
"""
import re
from functools import lru_cache
from pathlib import Path


REPO_ROOT = Path(__file__).parents[4]
README = REPO_ROOT / "README.md"

LAB_SECTION_HEADING = "## 🧪 실습 랩"

# Directories that are never scanned for labs: build output, virtual
# environments, and the worktrees this repository's own workflow creates.
IGNORED_PARTS = {
    ".git",
    ".worktrees",
    ".venv",
    "node_modules",
    "__pycache__",
}


@lru_cache(maxsize=1)
def runnable_labs():
    """Every directory an operator can provision with `azd up`.

    Cached: this walks the whole repository, and every test below needs the
    same answer.
    """
    labs = []
    for azure_yaml in REPO_ROOT.rglob("azure.yaml"):
        relative = azure_yaml.relative_to(REPO_ROOT)
        if IGNORED_PARTS & set(relative.parts):
            continue
        labs.append(relative.parent)
    return tuple(sorted(labs))


def lab_section():
    text = README.read_text()
    assert LAB_SECTION_HEADING in text, (
        "the README has no lab index; a reader cannot find what is runnable"
    )
    start = text.index(LAB_SECTION_HEADING)
    rest = text[start + len(LAB_SECTION_HEADING):]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def linked_paths(section):
    """Every relative Markdown link target in the section."""
    return re.findall(r"\]\((?!https?://)([^)#]+)", section)


def test_every_runnable_lab_is_listed():
    labs = runnable_labs()
    assert labs, "no runnable lab found; the discovery rule is wrong"

    section = lab_section()
    for lab in labs:
        assert str(lab) in section, (
            "{0} can be provisioned but is missing from the README index".format(lab)
        )


def test_a_lab_is_listed_only_once():
    """A duplicated row is how an index starts drifting from reality."""
    section = lab_section()
    for lab in runnable_labs():
        rows = [
            line
            for line in section.splitlines()
            if line.startswith("|") and str(lab) in line
        ]
        assert len(rows) == 1, (lab, rows)


def test_every_link_in_the_index_resolves():
    section = lab_section()
    targets = linked_paths(section)
    assert targets, "the index lists no navigable entry"
    for target in targets:
        assert (REPO_ROOT / target.strip()).exists(), target


def test_each_row_states_the_cost_and_the_time_commitment():
    """Both labs cost money and take time; a reader decides on those two
    facts before opening anything."""
    section = lab_section()
    header = next(line for line in section.splitlines() if line.startswith("|"))
    for column in ("소요", "과금"):
        assert column in header, column

    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not set(line) <= set("|- ")
    ][1:]
    assert rows, "the index has a header but no entries"
    for row in rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert all(cells), row


def test_the_index_explains_how_to_add_a_lab():
    """The list only stays current if the next person knows it exists."""
    section = lab_section()
    assert "azure.yaml" in section, (
        "the section must state what qualifies as a lab, so a new one is added here"
    )
