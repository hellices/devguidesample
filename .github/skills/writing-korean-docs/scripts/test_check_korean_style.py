"""Regression tests for check_korean_style.py.

Run from the repository root:
    python -m unittest discover -v -s .github/skills/writing-korean-docs/scripts
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import check_korean_style as checker

FILLER = "\n\n".join(f"{n}번째 문단은 설정을 확인한다. 값을 저장한다." for n in range(1, 30))


def analyze(markdown: str) -> checker.Report:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "doc.md"
        path.write_text(markdown, encoding="utf-8")
        return checker.analyze(path, checker.Thresholds())


def flagged(report: checker.Report) -> set[str]:
    return {finding.split("=")[0] for finding in report.findings}


class SentenceHeadingTest(unittest.TestCase):
    def test_noun_headings_are_not_sentences(self) -> None:
        for heading in ("개요", "✅ 개요", "바다", "필요", "토큰 갱신 필요", "주요 지표", "람다 함수"):
            with self.subTest(heading=heading):
                report = analyze(f"# {heading}\n\n본문이다.\n")
                self.assertEqual(report.metrics["sentence_headings"], 0)

    def test_predicate_endings_are_sentences(self) -> None:
        for heading in (
            "제목은 본문의 핵심 내용을 요약합니다",
            "키 속성입니다",
            "두 경로를 분리해서 본다",
            "캐시가 적중한다",
            "설정을 바꿨다",
            "값이 있다",
            "권한이 없다",
            "AGIC와 AGFC는 다르다",
            "단순 모델로는 부족하다",
            "IP 제한 용도가 아니다",
            "쓰지 않는다",
            "설정을 확인하세요",
            "값이 있어요",
            "결과가 같죠",
        ):
            with self.subTest(heading=heading):
                report = analyze(f"# {heading}\n\n본문이다.\n")
                self.assertEqual(report.metrics["sentence_headings"], 1)

    def test_empty_atx_heading_does_not_take_next_line(self) -> None:
        report = analyze("#\n따라서, 설정한다.\n\n## 개요\n\n본문이다.\n")
        self.assertEqual(report.metrics["sentence_headings"], 0)
        # The line after the empty heading stays prose.
        self.assertEqual(report.metrics["adverb_comma"], 1)

    def test_closing_hashes_follow_site_renderer(self) -> None:
        # MkDocs renders "# 처리한다#" as the heading "처리한다", so it is a sentence heading.
        for heading in ("# 처리한다#", "# 처리한다 #"):
            with self.subTest(heading=heading):
                report = analyze(f"{heading}\n\n본문이다.\n")
                self.assertEqual(report.metrics["sentence_headings"], 1)

    def test_space_before_hash_is_text_on_site(self) -> None:
        # MkDocs renders "   ## 구성: 세부 정보" as a paragraph, not a heading.
        for indent in (1, 2, 3):
            with self.subTest(indent=indent):
                report = analyze(" " * indent + "## 구성: 세부 정보\n\n본문이다.\n")
                self.assertEqual(report.metrics["colon_headings"], 0)
        # The visible text is prose, so its comma is counted.
        report = analyze("   ## 따라서, 설정한다\n\n본문이다.\n")
        self.assertEqual(report.metrics["adverb_comma"], 1)
        # A top-level sentence heading indented three spaces is not a heading either.
        report = analyze("   # 설치합니다\n\n본문이다.\n")
        self.assertEqual(report.metrics["sentence_headings"], 0)
        self.assertEqual(report.metrics["formal_endings"], 0)

    def test_headings_inside_containers_follow_site_renderer(self) -> None:
        rendered = (
            "> ## 설치합니다.\n",
            "> 본문이다.\n> ## 설치합니다.\n",
            "- ## 설치합니다.\n",
            "1. ## 설치합니다.\n",
            "> - ## 설치합니다.\n",
            '!!! note "참고"\n    본문이다.\n    ## 설치합니다.\n',
            "- 항목이다.\n\n    ## 설치합니다.\n",
            "- 항목이다.\n\n    - ## 설치합니다.\n",
        )
        for text in rendered:
            with self.subTest(text=text):
                report = analyze("# 제목\n\n" + text)
                self.assertEqual(report.metrics["sentence_headings"], 1)
                # The heading is not counted again as a "~니다" prose sentence.
                self.assertEqual(report.metrics["formal_endings"], 0)
        # The site shows these as text, not headings.
        for text in ("1) ## 설치합니다.\n", "- 항목이다.\n  ## 설치합니다.\n", "- 항목이다.\n    ## 설치합니다.\n"):
            with self.subTest(text=text):
                report = analyze("# 제목\n\n" + text)
                self.assertEqual(report.metrics["sentence_headings"], 0)
                # The line is checked as prose instead of being dropped.
                self.assertEqual(report.metrics["formal_endings"], 1)

    def test_four_space_indent_is_not_a_heading(self) -> None:
        report = analyze("# 제목\n\n본문이다.\n\n    ## 구성: 세부 정보\n\n본문이다.\n")
        self.assertEqual(report.metrics["colon_headings"], 0)

    def test_setext_headings_are_headings(self) -> None:
        report = analyze(
            "따라서, 설정합니다\n===\n\n본문이다.\n\n"
            "애플리케이션에 의해 저장됩니다\n---\n\n본문이다.\n"
        )
        self.assertEqual(report.metrics["sentence_headings"], 2)
        # Heading text is left out of the prose checks.
        self.assertEqual(report.metrics["adverb_comma"], 0)
        self.assertEqual(report.metrics["translationese"], 0)

    def test_setext_needs_a_single_line_block_on_site(self) -> None:
        # MkDocs renders a longer paragraph followed by "---" as a paragraph and a rule.
        for text in ("첫 줄이다.\n결과: 지연\n---\n", "첫 줄이다.\n결과: 지연\n===\n"):
            with self.subTest(text=text):
                report = analyze("# 제목\n\n" + text)
                self.assertEqual(report.metrics["colon_headings"], 0)
                self.assertEqual(report.metrics["plain_endings"], 1)

    def test_setext_headings_inside_containers(self) -> None:
        for text in (
            "> 결과: 지연 시간\n> ---\n",
            "> 본문이다.\n>\n> 결과: 지연\n> ===\n",
            "- 항목이다.\n\n    결과: 지연\n    ---\n",
            '!!! note "참고"\n    결과: 지연\n    ---\n',
        ):
            with self.subTest(text=text):
                self.assertEqual(analyze("# 제목\n\n" + text).metrics["colon_headings"], 1)
        # The underline must be in the same block quote as the title.
        report = analyze("# 제목\n\n> 결과: 지연\n> 둘째 줄이다.\n> ---\n")
        self.assertEqual(report.metrics["colon_headings"], 0)

    def test_thematic_break_is_not_setext_heading(self) -> None:
        report = analyze("# 제목\n\n본문이다.\n\n---\n\n본문이다.\n")
        self.assertEqual(report.metrics["sentence_headings"], 0)

    def test_link_label_and_emphasis_are_normalized(self) -> None:
        report = analyze("# [설정합니다.](#setup)\n\n## **캐시를 끕니다**\n\n본문이다.\n")
        self.assertEqual(report.metrics["sentence_headings"], 2)


class ConnectiveCommaTest(unittest.TestCase):
    def test_nouns_ending_in_go_are_not_connective(self) -> None:
        report = analyze("사고, 대응 절차를 확인한다. 재고, 주문, 참고, 로고 항목을 본다.\n")
        self.assertEqual(report.metrics["connective_comma"], 0)
        self.assertNotIn("connective_comma_per_100_sentences", flagged(report))

    def test_connective_endings_are_counted(self) -> None:
        report = analyze(
            "설정을 바꾸고, 다시 배포한다. 값이 있으며, 로그도 남는다. 지원하지만, 느리다.\n"
        )
        self.assertEqual(report.metrics["connective_comma"], 3)


class FencedCodeTest(unittest.TestCase):
    def test_inner_fence_does_not_close_longer_fence(self) -> None:
        text = (
            "# 펜스\n\n````markdown\n```bash\n따라서, 실행한다.\n```\n하지만, 코드다.\n````\n\n"
            "그리고, 본문이다.\n"
        )
        # Only the prose after the matching four-backtick fence is counted.
        self.assertEqual(analyze(text).metrics["adverb_comma"], 1)

    def test_fences_inside_quote_and_list_marker_are_code(self) -> None:
        text = (
            "# 펜스\n\n> ```text\n> 따라서, 코드다.\n> ```\n\n"
            "- ```text\n  그리고, 코드다.\n  ```\n  설명이다. 그리고, 본문이다.\n"
        )
        self.assertEqual(analyze(text).metrics["adverb_comma"], 1)

    def test_top_level_indented_fence_is_not_a_fence(self) -> None:
        text = f"# 펜스\n\n본문이다.\n\n    ```\n    코드 줄\n\n그리고, 본문이다.\n\n{FILLER}\n"
        self.assertEqual(analyze(text).metrics["adverb_comma"], 1)

    def test_indented_code_block_is_code(self) -> None:
        text = "# 코드\n\n본문이다.\n\n    되어진다.\n    따라서, 코드다.\n\n    이어지는 코드다.\n\n본문이다.\n"
        report = analyze(text)
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["adverb_comma"], 0)
        self.assertEqual(report.findings, [])

    def test_indented_line_continues_paragraph(self) -> None:
        report = analyze("# 문단\n\n설정을 확인하는 방법은\n    따라서, 문단의 연속이다.\n")
        self.assertEqual(report.metrics["adverb_comma"], 1)

    def test_indented_code_after_thematic_break_is_code(self) -> None:
        report = analyze("# 코드\n\n본문이다.\n\n---\n    되어진다.\n\n본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 0)

    def test_thematic_break_is_not_a_bullet(self) -> None:
        for rule in ("* * *", "- - -"):
            with self.subTest(rule=rule):
                report = analyze(f"# 구분선\n\n설명이다.\n\n{rule}\n\n다음 설명이다.\n")
                self.assertEqual(report.metrics["bullet_line_ratio"], 0)
                self.assertNotIn("bullet_line_ratio", flagged(report))

    def test_list_continuation_is_not_code(self) -> None:
        report = analyze("# 목록\n\n- 첫 항목이다.\n\n    따라서, 항목의 둘째 문단이다.\n")
        self.assertEqual(report.metrics["adverb_comma"], 1)

    def test_fence_nested_in_list_and_admonition_is_code(self) -> None:
        text = (
            "# 펜스\n\n*   항목이다.\n    ```yaml\n    그리고, 코드다.\n    ```\n\n"
            '??? example "예시"\n    설명이다.\n\n    ```yaml\n    그러나, 코드다.\n    ```\n\n그리고, 본문이다.\n'
        )
        # Only the prose after both fences close is counted.
        self.assertEqual(analyze(text).metrics["adverb_comma"], 1)


class EndingTest(unittest.TestCase):
    def test_polite_endings_are_not_plain(self) -> None:
        for second in ("확인하죠.", "값이 있어요.", "다시 돼요."):
            with self.subTest(second=second):
                report = analyze(f"# 종결\n\n설정합니다. {second}\n")
                self.assertEqual(report.metrics["formal_endings"], 2)
                self.assertEqual(report.metrics["plain_endings"], 0)
                self.assertNotIn("minority_ending_ratio", flagged(report))


class QuoteTest(unittest.TestCase):
    def test_quoted_examples_do_not_count_as_endings(self) -> None:
        text = '# 인용\n\n본문은 합니다체로 씁니다. 예시 문구는 "파일을 저장한다. 다음 파일을 읽는다."입니다.\n'
        report = analyze(text)
        self.assertEqual(report.metrics["plain_endings"], 0)
        self.assertNotIn("minority_ending_ratio", flagged(report))

    def test_apostrophes_do_not_open_quotes(self) -> None:
        report = analyze("# 따옴표\n\ndon't 때문에 번역투에 의해 user's 값을 설명합니다.\n")
        self.assertEqual(report.metrics["translationese"], 1)


class DashTest(unittest.TestCase):
    def test_dash_inside_multiline_quote_is_not_counted(self) -> None:
        report = analyze("# 대시\n\n“처리한다 —\n계속한다.”\n\n본문이다.\n")
        self.assertEqual(report.metrics["em_dash"], 0)
        self.assertNotIn("em_dash_per_100_sentences", flagged(report))

    def test_dash_in_prose_is_counted(self) -> None:
        report = analyze("# 대시\n\n처리한다 —\n계속한다.\n")
        self.assertEqual(report.metrics["em_dash"], 1)


class HtmlCommentTest(unittest.TestCase):
    def test_comment_opener_inside_code_is_code(self) -> None:
        text = (
            "# 주석\n\n```html\n<!-- sample\n```\n\n"
            "파일이 애플리케이션에 의해 저장된다.\n\n<!-- end -->\n"
        )
        self.assertEqual(analyze(text).metrics["translationese"], 1)

    def test_comment_opener_in_inline_code_is_code(self) -> None:
        text = "# 주석\n\n`<!--`로 시작한다. 파일이 사용자에 의해 저장된다. <!-- 끝 -->\n"
        self.assertEqual(analyze(text).metrics["translationese"], 1)

    def test_comment_in_block_quote_ends_with_the_quote(self) -> None:
        text = "# 주석\n\n> <!--\n> 숨김\n\n본문은 작업이 수행되어진다.\n\n-->\n"
        self.assertEqual(analyze(text).metrics["translationese"], 1)

    def test_comment_in_list_item_stays_open(self) -> None:
        # The site renderer keeps this comment open inside the list item.
        text = "# 주석\n\n- 항목이다.\n  <!--\n  작업이 수행되어진다.\n  -->\n\n본문이다.\n"
        report = analyze(text)
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["plain_endings"], 2)

    def test_comment_block_is_removed(self) -> None:
        text = "# 주석\n\n<!--\n```\n되어진다.\n-->\n\n본문이다. 그리고, 센다.\n"
        report = analyze(text)
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["adverb_comma"], 1)


class LinkTargetTest(unittest.TestCase):
    def test_target_with_balanced_parentheses_is_removed(self) -> None:
        report = analyze("# 링크\n\n[설명](https://example.test/a_(b)/되어진다) 본문이다. 그리고, 센다.\n")
        self.assertEqual(report.metrics["translationese"], 0)
        # The text after the closing parenthesis is still prose.
        self.assertEqual(report.metrics["adverb_comma"], 1)
        self.assertEqual(report.metrics["plain_endings"], 2)

    def test_destination_with_spaces_follows_site_renderer(self) -> None:
        # MkDocs renders "[설명](작업을 수행한다.)" as a link that shows only "설명".
        report = analyze("# 링크\n\n[설명](작업을 수행한다.) 본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["plain_endings"], 1)

    def test_unmatched_bracket_is_not_a_link(self) -> None:
        report = analyze("# 링크\n\n조건](작업을 수행한다.) 뒤에 본문이 있다.\n")
        self.assertEqual(report.metrics["translationese"], 1)

    def test_whitespace_blank_line_resets_open_bracket(self) -> None:
        report = analyze("# 링크\n\n열린 [괄호가 있다.\n  \n조건](작업이 수행되어진다.) 본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 1)

    def test_link_target_does_not_cross_whitespace_blank_line(self) -> None:
        report = analyze("# 링크\n\n[레이블](열린 대상\n \t\n작업이 수행되어진다.) 본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 1)

    def test_angle_target_is_removed(self) -> None:
        report = analyze("# 링크\n\n[가](<a/되어진다 b>) 본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["plain_endings"], 1)

    def test_parenthesis_in_quoted_title_does_not_change_depth(self) -> None:
        # MkDocs renders both as links whose titles hold the parenthesis. A
        # leftover '"' would pair with the later quote and hide "그리고,".
        for target in ('https://example.test "하는 것이 중요하다 ("', '/b "제목 )"'):
            with self.subTest(target=target):
                report = analyze(f'# 링크\n\n[설명]({target}) 본문이다. 그리고, "인용" 센다.\n')
                self.assertEqual(report.metrics["translationese"], 0)
                self.assertEqual(report.metrics["adverb_comma"], 1)
                self.assertEqual(report.metrics["plain_endings"], 2)

    def test_escaped_parenthesis_target_is_removed(self) -> None:
        report = analyze("# 링크\n\n[나](c\\)/되어진다) 본문이다.\n")
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["plain_endings"], 1)


class LinkReferenceTest(unittest.TestCase):
    def test_reference_definitions_are_not_prose(self) -> None:
        text = (
            "# 참조\n\n본문은 합니다체로 씁니다.\n\n"
            "[ref]: /target (것이 중요하다.)\n"
            "[next]: <a b>\n  \"되어진다.\"\n"
        )
        report = analyze(text)
        self.assertEqual(report.metrics["translationese"], 0)
        self.assertEqual(report.metrics["plain_endings"], 0)
        self.assertEqual(report.findings, [])

    def test_reference_syntax_inside_paragraph_is_prose(self) -> None:
        report = analyze("# 참조\n\n문단 중간이다.\n[a]: /b (것이 중요하다.)\n")
        self.assertEqual(report.metrics["translationese"], 1)


class ThresholdTest(unittest.TestCase):
    def test_threshold_uses_unrounded_value(self) -> None:
        # One bold in 499 prose characters is 2.004 per 1,000, above 2.0, but
        # rounds to 2.0 for display.
        report = analyze("# 굵게\n\n**강조** " + "가" * 494 + "이다.\n")
        self.assertEqual(report.prose_chars, 499)
        self.assertEqual(report.metrics["bold_per_1000_chars"], 2.0)
        self.assertIn("bold_per_1000_chars", flagged(report))


class TableTest(unittest.TestCase):
    def test_table_ends_at_admonition(self) -> None:
        text = "# 표\n\n| a | b |\n|---|---|\n| 1 | 2 |\n!!! note\n    작업이 수행되어진다.\n"
        self.assertEqual(analyze(text).metrics["translationese"], 1)

    def test_short_delimiter_cells_form_a_table(self) -> None:
        # GFM and the site's Markdown renderer accept one hyphen per delimiter cell.
        report = analyze("# 표\n\n옵션 | 설명\n- | -\n접속 | 그리고, 셀이다.\n\n본문이다.\n")
        self.assertEqual(report.metrics["adverb_comma"], 0)
        self.assertGreater(report.metrics["table_line_ratio"], 0)

    def test_table_without_outer_pipes_is_not_prose(self) -> None:
        text = "# 표\n\n항목 | 설명\n--- | ---\n접속 | 그리고, 셀이다.\n\n본문이다.\n"
        report = analyze(text)
        self.assertEqual(report.metrics["adverb_comma"], 0)
        self.assertGreater(report.metrics["table_line_ratio"], 0)

    def test_pipe_in_prose_is_not_a_table(self) -> None:
        report = analyze("# 표\n\n명령은 a | b 형태다. 그리고, 이 쉼표는 센다.\n")
        self.assertEqual(report.metrics["adverb_comma"], 1)


class ContainerTableTest(unittest.TestCase):
    def test_tables_inside_containers_are_not_prose(self) -> None:
        for text in (
            "> | 항목 | 설명 |\n> | --- | --- |\n> | 결론적으로 | 그리고, 값 |\n",
            "> > | 항목 | 설명 |\n> > |---|---|\n> > | 결론적으로 | 그리고, 값 |\n",
            "- 목록이다.\n\n    | 항목 | 설명 |\n    | --- | --- |\n    | 결론적으로 | 그리고, 값 |\n",
            '!!! note "참고"\n    | 항목 | 설명 |\n    | --- | --- |\n    | 결론적으로 | 그리고, 값 |\n',
        ):
            with self.subTest(text=text):
                report = analyze("# 표\n\n" + text + "\n본문이다.\n")
                self.assertEqual(report.metrics["signature_phrases"], 0)
                self.assertEqual(report.metrics["adverb_comma"], 0)

    def test_lazy_line_continues_quoted_table(self) -> None:
        # MkDocs renders the unquoted line as another row of the quoted table.
        report = analyze("# 표\n\n> | 항목 | 설명 |\n> | --- | --- |\n결론적으로, 셀이다.\n\n본문이다.\n")
        self.assertEqual(report.metrics["signature_phrases"], 0)
        self.assertEqual(report.metrics["plain_endings"], 1)


class ScanFormatTest(unittest.TestCase):
    def test_result_section_markup_is_not_counted(self) -> None:
        text = (
            "---\ndocument_type: research\n---\n\n# 결과\n\n## 결과 1: 단건 레이턴시\n\n"
            "| GPU | mean |\n|---|---|\n| A10 | **3.97 ms** |\n\n"
            "**분석:**\n- **A10 1.4× 우위** — 절대값은 한 자릿수 ms\n\n"
            "> ⚠️ **측정 범위**: 임베딩 구간만 측정했다.\n\n"
            f"{FILLER}\n"
        )
        report = analyze(text)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.metrics["report_colon_headings"], 1)

    def test_repeated_conclusion_boxes_are_flagged(self) -> None:
        text = (
            "# 설계\n\n**결론**: 흐름은 손으로만 기록됐다.\n\n본문이다.\n\n"
            "**정리**: 코드가 문서를 이겼다.\n"
        )
        self.assertIn("bold_label_lines", flagged(analyze(text)))


class IterMarkdownTest(unittest.TestCase):
    def test_overlapping_paths_are_listed_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.md").write_text("# 가\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.md").write_text("# 나\n", encoding="utf-8")
            files = checker.iter_markdown(
                [str(root / "sub" / "b.md"), folder, str(root / "a.md"), f"{folder}/./a.md"]
            )
            self.assertEqual(
                [f.resolve() for f in files],
                [(root / "sub" / "b.md").resolve(), (root / "a.md").resolve()],
            )


class ExampleFilesTest(unittest.TestCase):
    def test_before_fails_and_after_passes(self) -> None:
        here = Path(__file__).parent / "examples"
        limits = checker.Thresholds()
        self.assertTrue(checker.analyze(here / "before.md", limits).findings)
        self.assertFalse(checker.analyze(here / "after.md", limits).findings)


if __name__ == "__main__":
    unittest.main()
