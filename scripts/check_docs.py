#!/usr/bin/env python3
"""문서를 올리기 전에 기계로 잡을 수 있는 것만 잡는다.

    python3 scripts/check_docs.py            # 저장소 전체
    python3 scripts/check_docs.py redis/     # 경로 한정
    python3 scripts/check_docs.py --strict   # 문체 경고도 실패로 처리

오류(종료 코드 1)
    깨진 상대 링크 · 없는 앵커 · 중복 앵커 · 표 열 수 불일치 · H1 없음 · 잘못된 용어

경고(기본은 종료 코드에 영향 없음)
    표 셀이 종결어미로 끝남 · 한 문서에 합니다체와 한다체가 섞임

기존 문서 78개 중 상당수가 경고를 안고 있어 기본값은 경고입니다. 새로 쓰거나
크게 고치는 문서에는 `--strict`로 돌려 0건을 맞춰 주세요. 규칙의 근거는 AGENTS.md.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 사람이 쓴 문서가 아닌 곳 — 캡처·근거 산출물은 검사 대상이 아니다
SKIP_DIRS = {"node_modules", "infra", "assets", "evidence"}

# 표기를 하나로 고정한 용어 (저장소 실제 사용 비율에 맞춤)
TERMS = {"디렉토리": "디렉터리", "어플리케이션": "애플리케이션"}
# 틀린 표기를 일부러 적어야 하는 줄 — 규칙 문서의 예시 표 등
IGNORE = "<!-- check-docs:ignore -->"

LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# GitHub 앵커: 소문자화 → 백틱 제거 → 기호 제거 → 공백을 하이픈으로
ANCHOR_STRIP = re.compile(r"[^\w\s\-]", re.UNICODE)
# 이모지 변이 선택자·ZWJ는 GitHub과 처리가 갈려서 비교 전에 양쪽 모두 지운다
INVISIBLE = re.compile(r"[️‍]")
# 셀 안의 `\|`는 열 구분자가 아니다
ESCAPED_PIPE = re.compile(r"\\\|")

POLITE = re.compile(r"(니다|하십시오|세요|주세요)[.!]?$")
PLAIN = re.compile(r"(?<![가-힣])(?:[가-힣]+)다[.!]?$")


def slug(text: str) -> str:
    s = ANCHOR_STRIP.sub("", text.lower().replace("`", "")).replace(" ", "-")
    return INVISIBLE.sub("", s)


def lines_of(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.readlines()


def prose_lines(path: str):
    """코드 펜스를 뺀 (줄번호, 내용, 종류). `<!-- BEGIN:x -->` 블록은 생성물로 표시한다."""
    fence = False
    generated = False
    for no, raw in enumerate(lines_of(path), 1):
        s = raw.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if s.startswith("<!-- BEGIN:"):
            generated = True
            continue
        if s.startswith("<!-- END:"):
            generated = False
            continue
        if s.startswith("|") and s.endswith("|"):
            kind = "table"
        elif s.startswith("#"):
            kind = "heading"
        elif not s:
            kind = "blank"
        else:
            kind = "prose"
        yield no, s, kind, generated


def anchors_of(path: str, cache: dict) -> dict:
    if path in cache:
        return cache[path]
    found: dict[str, int] = {}
    fence = False
    for raw in lines_of(path):
        if raw.startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = HEADING_RE.match(raw)
        if m:
            key = slug(m.group(2).strip())
            found[key] = found.get(key, 0) + 1
    cache[path] = found
    return found


def collect(paths: list[str]) -> list[str]:
    out = []
    for target in paths:
        full = os.path.join(ROOT, target)
        if os.path.isfile(full) and full.endswith(".md"):
            out.append(os.path.relpath(full, ROOT))
            continue
        for base, dirs, files in os.walk(full):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]
            out += [
                os.path.relpath(os.path.join(base, f), ROOT)
                for f in files
                if f.endswith(".md")
            ]
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=["."], help="검사할 경로 (기본: 저장소 전체)")
    ap.add_argument("--strict", action="store_true", help="문체 경고도 실패로 처리")
    args = ap.parse_args()

    docs = collect(args.paths or ["."])
    cache: dict[str, dict] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for rel in docs:
        path = os.path.join(ROOT, rel)
        here = os.path.dirname(path)
        has_h1 = False
        table_block: list[tuple[int, int]] = []
        polite = plain = 0

        def flush_table():
            if len(table_block) > 2:
                width = table_block[1][1]
                for no, cols in table_block:
                    if cols != width:
                        errors.append(
                            f"{rel}:{no} 표 열 수가 {cols}개 — 이 표는 {width}개"
                        )
            table_block.clear()

        for no, s, kind, generated in prose_lines(path):
            if kind == "heading":
                flush_table()
                if s.startswith("# "):
                    has_h1 = True
            elif kind == "table":
                cells = [
                    c.replace("\x00", r"\|").strip()
                    for c in ESCAPED_PIPE.sub("\x00", s).strip("|").split("|")
                ]
                if not generated and not all(set(c) <= set("-: ") for c in cells):
                    for cell in cells:
                        bare = MD_LINK_RE.sub(r"\1", cell).strip().strip("*").strip()
                        if POLITE.search(bare) or PLAIN.search(bare):
                            warnings.append(f"{rel}:{no} 표 셀이 종결어미로 끝남 — {cell[:60]}")
                            break
                table_block.append((no, len(cells)))
            else:
                flush_table()
                if kind == "prose" and not generated:
                    bare = MD_LINK_RE.sub(r"\1", s).strip().strip("*").strip()
                    if POLITE.search(bare):
                        polite += 1
                    elif PLAIN.search(bare):
                        plain += 1

            if IGNORE not in s:
                for wrong, right in TERMS.items():
                    if wrong in s:
                        errors.append(f"{rel}:{no} `{wrong}` → `{right}`")

            for m in LINK_RE.finditer(s):
                target = m.group(2)
                if target.startswith(("http", "mailto", "<", "#!")):
                    continue
                file_part, _, anchor = target.partition("#")
                tp = path if not file_part else os.path.normpath(os.path.join(here, file_part))
                if file_part and not os.path.exists(tp):
                    errors.append(f"{rel}:{no} 링크 대상 없음 — {target}")
                    continue
                if anchor and tp.endswith(".md"):
                    found = anchors_of(tp, cache)
                    anchor = INVISIBLE.sub("", anchor)
                    if anchor not in found:
                        errors.append(f"{rel}:{no} 앵커 없음 — {target}")
                    elif found[anchor] > 1:
                        errors.append(f"{rel}:{no} 앵커가 중복된 제목을 가리킴 — {target}")
        flush_table()

        if not has_h1:
            errors.append(f"{rel}:1 H1(`# 제목`)이 없음")

        minor = min(polite, plain)
        total = polite + plain
        if total >= 10 and minor >= 3 and minor / total > 0.2:
            warnings.append(
                f"{rel} 문체 혼용 — 합니다체 {polite} / 한다체 {plain}. 문서 하나에 하나만 쓰세요"
            )

    for w in warnings:
        print(f"경고  {w}")
    for e in errors:
        print(f"오류  {e}", file=sys.stderr)

    print(f"\n문서 {len(docs)}개 · 오류 {len(errors)}건 · 경고 {len(warnings)}건")
    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
