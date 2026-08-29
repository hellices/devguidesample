#!/usr/bin/env python3
"""루트 README.md의 인덱스 블록을 저장소 구조에서 다시 만든다.

README의 `<!-- BEGIN:categories -->` / `<!-- BEGIN:labs -->` 마커 사이만 바꾸고
나머지 서술은 건드리지 않는다. 문서를 추가해도 README를 손으로 고칠 필요가 없다.

    python3 scripts/gen_index.py           # README.md 갱신
    python3 scripts/gen_index.py --check   # 어긋나면 종료 코드 1 (CI용)

대표 문서는 이 순서로 고른다.
    1. `<카테고리>/README.md`
    2. 같은 카테고리의 다른 문서를 2개 이상 링크하는 문서 (얕은 경로 우선)
    3. 없으면 `—`

2번에 걸릴 문서가 없다는 것은 그 카테고리가 아직 묶음이 아니라 낱개 문서 모음이라는
뜻이다. 묶음으로 정리할 때 README.md를 두면 1번으로 잡힌다 — AGENTS.md 참조.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "README.md")

# 문서가 아닌 디렉터리 — 인덱스에서 뺀다
SKIP_DIRS = {"infra", "oryx-test", "scripts", "node_modules"}

LINK_RE = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)]*)?\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def read(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.readlines()


def iter_docs() -> list[str]:
    """저장소 상대 경로로 된 문서 목록. 루트 README와 지침 파일은 뺀다."""
    docs = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        for name in files:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(base, name), ROOT)
            if os.sep not in rel:  # 루트의 README.md, AGENTS.md, CLAUDE.md
                continue
            docs.append(rel)
    return sorted(docs)


def title_of(rel: str) -> str:
    """H1을 제목으로 쓴다. 없으면 파일명."""
    fence = False
    for line in read(os.path.join(ROOT, rel)):
        if line.startswith("```"):
            fence = not fence
            continue
        if not fence and line.startswith("# "):
            return MD_LINK_RE.sub(r"\1", line[2:].strip()).replace("|", r"\|")
    return os.path.basename(rel)


def lead_of(rel: str) -> str:
    """H1 다음의 첫 산문 문단에서 첫 문장을 뽑는다."""
    fence = False
    seen_h1 = False
    for line in read(os.path.join(ROOT, rel)):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if s.startswith("# "):
            seen_h1 = True
            continue
        if not seen_h1 or not s or s.startswith(("#", ">", "|", "-", "*", "!", "<")):
            continue
        s = MD_LINK_RE.sub(r"\1", s)
        head = re.split(r"(?<=다)\.\s", s)[0].rstrip(".")
        return head.replace("|", r"\|")
    return ""


def out_degree(rel: str, universe: set[str]) -> int:
    """같은 카테고리 안에서 이 문서가 링크하는 다른 문서의 수."""
    here = os.path.dirname(rel)
    cat = rel.split(os.sep)[0]
    targets = set()
    fence = False
    for line in read(os.path.join(ROOT, rel)):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        for m in LINK_RE.finditer(line):
            tgt = os.path.normpath(os.path.join(here, m.group(1)))
            if tgt in universe and tgt != rel and tgt.split(os.sep)[0] == cat:
                targets.add(tgt)
    return len(targets)


def pick_entry(cat: str, docs: list[str], universe: set[str]) -> str:
    readme = f"{cat}{os.sep}README.md"
    if readme in universe:
        return readme
    ranked = sorted(
        ((out_degree(d, universe), d) for d in docs),
        key=lambda x: (x[1].count(os.sep), -x[0], x[1]),
    )
    for deg, doc in ranked:
        if deg >= 2:
            return doc
    return ""


def categories_table(docs: list[str]) -> str:
    universe = set(docs)
    rows = ["| 카테고리 | 문서 | 들어가는 곳 |", "|---|---:|---|"]
    for cat in sorted({d.split(os.sep)[0] for d in docs}):
        mine = [d for d in docs if d.split(os.sep)[0] == cat]
        entry = pick_entry(cat, mine, universe)
        link = f"[{title_of(entry)}]({entry.replace(os.sep, '/')})" if entry else "—"
        rows.append(f"| [`{cat}`]({cat}/) | {len(mine)} | {link} |")
    return "\n".join(rows)


def labs_table() -> str:
    """azure.yaml을 가진 디렉터리를 실습 랩으로 본다."""
    labs = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
        if "azure.yaml" in files and "README.md" in files:
            labs.append(os.path.relpath(base, ROOT))
    if not labs:
        return "아직 등록된 랩이 없습니다."
    rows = ["| 랩 | 무엇을 확인하나 |", "|---|---|"]
    for lab in sorted(labs):
        rel = os.path.join(lab, "README.md")
        path = rel.replace(os.sep, "/")
        rows.append(f"| [{title_of(rel)}]({path}) | {lead_of(rel)} |")
    return "\n".join(rows)


def splice(text: str, marker: str, body: str) -> str:
    begin, end = f"<!-- BEGIN:{marker} -->", f"<!-- END:{marker} -->"
    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end), re.DOTALL
    )
    if not pattern.search(text):
        raise SystemExit(f"README.md에 {begin} … {end} 마커가 없습니다")
    return pattern.sub(f"{begin}\n{body}\n{end}", text)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="갱신 대신 어긋남만 검사")
    args = ap.parse_args()

    docs = iter_docs()
    with open(README, encoding="utf-8") as fh:
        before = fh.read()

    after = splice(before, "categories", categories_table(docs))
    after = splice(after, "labs", labs_table())

    if before == after:
        print("README.md 인덱스가 최신입니다.")
        return 0
    if args.check:
        print("README.md 인덱스가 저장소 구조와 어긋납니다.", file=sys.stderr)
        print("`python3 scripts/gen_index.py`를 실행하고 결과를 커밋하세요.", file=sys.stderr)
        return 1
    with open(README, "w", encoding="utf-8") as fh:
        fh.write(after)
    print("README.md 인덱스를 갱신했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
