import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot
import music_namuwiki_parsing


CORE_PARSING_MOVED_NAMES = (
    "NamuWikiLyricsError",
    "NamuWikiPageBlockedError",
    "extract_namuwiki_lyrics_from_html",
    "extract_namuwiki_lyrics_from_namumark",
    "lyrics_are_primarily_korean",
    "parse_namuwiki_html_tables",
)


NAMUWIKI_HTML_FIXTURE = """
<html>
  <body>
    <table class="wiki-table">
      <tbody>
        <tr>
          <th>일본어 원문</th>
          <th>일본어 독음</th>
          <th>한국어 번역<sup>[1]</sup></th>
        </tr>
        <tr>
          <td>泥濘 鳴鳴</td>
          <td>でいねい めいめい</td>
          <td><div>진창에서 울리는 노랫소리</div></td>
        </tr>
        <tr>
          <td>礼を持って</td>
          <td>れいをもって</td>
          <td>예를 갖추어 다시 걸어가</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""
NAMUWIKI_NAMUMARK_FIXTURE = """
||<tablewidth=100%><rowbgcolor=#222> '''일본어 원문''' || '''일본어 독음''' || '''한국어 번역''' ||
|| 泥濘 鳴鳴 || でいねい めいめい || 진창에서 울리는 노랫소리 ||
|| 礼を持って || れいをもって || 예를 갖추어 다시 걸어가 ||
"""
NAMUWIKI_EXPECTED_LYRICS = (
    "泥濘 鳴鳴\n"
    "でいねい めいめい\n"
    "진창에서 울리는 노랫소리\n\n"
    "礼を持って\n"
    "れいをもって\n"
    "예를 갖추어 다시 걸어가"
)
class MusicNamuWikiParsingTests(unittest.TestCase):
    def test_bot_reexports_moved_parsing_names(self) -> None:
        for name in CORE_PARSING_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_parsing.__file__).read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertEqual(
            imported_modules,
            {
                "__future__",
                "dataclasses",
                "html",
                "html.parser",
                "re",
                "typing",
            },
        )

    def test_page_blocked_error_preserves_inheritance(self) -> None:
        self.assertTrue(
            issubclass(
                music_namuwiki_parsing.NamuWikiPageBlockedError,
                music_namuwiki_parsing.NamuWikiLyricsError,
            )
        )

    def test_korean_script_detection_uses_letter_ratio(self) -> None:
        self.assertTrue(music_namuwiki_parsing.lyrics_are_primarily_korean("가a"))
        self.assertFalse(music_namuwiki_parsing.lyrics_are_primarily_korean("가ab"))
        self.assertFalse(music_namuwiki_parsing.lyrics_are_primarily_korean("123 !"))

    def test_html_parser_errors_are_wrapped(self) -> None:
        parser = MagicMock()
        parser.feed.side_effect = ValueError("broken table")
        with (
            patch.object(
                music_namuwiki_parsing,
                "NamuWikiHTMLTableParser",
                return_value=parser,
            ),
            self.assertRaisesRegex(
                music_namuwiki_parsing.NamuWikiLyricsError,
                "Could not parse NamuWiki HTML: broken table",
            ),
        ):
            music_namuwiki_parsing.parse_namuwiki_html_tables("<table>")

    def test_html_and_namumark_wrappers_feed_tables_to_selector(self) -> None:
        html_tables = [[[]]]
        namumark_tables = [[["cell"]]]
        with (
            patch.object(
                music_namuwiki_parsing,
                "parse_namuwiki_html_tables",
                return_value=html_tables,
            ),
            patch.object(
                music_namuwiki_parsing,
                "parse_namumark_tables",
                return_value=namumark_tables,
            ),
            patch.object(
                music_namuwiki_parsing,
                "extract_namuwiki_lyrics_from_tables",
                side_effect=["html lyrics", "namumark lyrics"],
            ) as select,
        ):
            self.assertEqual(
                music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(
                    "<table>"
                ),
                "html lyrics",
            )
            self.assertEqual(
                music_namuwiki_parsing.extract_namuwiki_lyrics_from_namumark(
                    "|| cell ||"
                ),
                "namumark lyrics",
            )

        self.assertEqual(
            [call.args[0] for call in select.call_args_list],
            [html_tables, namumark_tables],
        )


    def test_rendered_html_preserves_source_reading_and_translation(self) -> None:
        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(
                NAMUWIKI_HTML_FIXTURE
            ),
            NAMUWIKI_EXPECTED_LYRICS,
        )

    def test_namumark_preserves_source_reading_and_translation(self) -> None:
        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_namumark(
                NAMUWIKI_NAMUMARK_FIXTURE
            ),
            NAMUWIKI_EXPECTED_LYRICS,
        )

    def test_headerless_interleaved_html_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        <table>
          <tr><th>합창</th></tr>
          <tr><td>
            持ち合った<br>
            모치앗타<br>
            서로가 가진 건<br>
            それぞれ<br>
            소레조레<br>
            제각각 달랐지만<br>
            視線は違えど<br>
            시센와 치가에도<br>
            바라보는 곳은 달라도<br>
            掛け合わせるわ 今<br>
            카케아와세루와 이마<br>
            지금 서로의 마음을 포개
          </td></tr>
        </table>
        """

        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_interleaved_html_across_rows_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        <table>
          <tr><th>勇者</th></tr>
          <tr><td>[ 가사 보기 ]</td></tr>
          <tr><td>持ち合った</td></tr>
          <tr><td>모치앗타</td></tr>
          <tr><td>서로가 가진 건</td></tr>
          <tr><td>それぞれ</td></tr>
          <tr><td>소레조레</td></tr>
          <tr><td>제각각 달랐지만</td></tr>
          <tr><td>視線は違えど</td></tr>
          <tr><td>시센와 치가에도</td></tr>
          <tr><td>바라보는 곳은 달라도</td></tr>
          <tr><td>掛け合わせるわ 今</td></tr>
          <tr><td>카케아와세루와 이마</td></tr>
          <tr><td>지금 서로의 마음을 포개</td></tr>
        </table>
        """

        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_multiline_namumark_cell_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        ||<tablewidth=100%> {{{#!wiki style="text-align: center"
        持ち合った
        모치앗타
        서로가 가진 건
        それぞれ
        소레조레
        제각각 달랐지만
        視線は違えど
        시센와 치가에도
        바라보는 곳은 달라도
        掛け合わせるわ 今
        카케아와세루와 이마
        지금 서로의 마음을 포개
        }}} ||
        """

        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_namumark(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_headerless_readings_without_translation_are_rejected(
        self,
    ) -> None:
        source = """
        <table><tr><td>
          持ち合った<br>모치앗타<br>
          それぞれ<br>소레조레<br>
          視線は違えど<br>시센와 치가에도<br>
          掛け合わせるわ 今<br>카케아와세루와 이마
        </td></tr></table>
        """

        self.assertIsNone(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source)
        )

    def test_short_metadata_translation_is_not_mistaken_for_lyrics(self) -> None:
        source = """
        <table>
          <tr><th>항목</th><th>번역</th></tr>
          <tr><td>제목</td><td>진창 울음</td></tr>
        </table>
        """

        self.assertIsNone(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source)
        )

    def test_long_bilingual_metadata_is_not_mistaken_for_lyrics(self) -> None:
        source = """
        <table>
          <tr><th>원문</th><th>한국어 번역</th></tr>
          <tr>
            <td>Official description for the song and its release.</td>
            <td>
              이 문서는 곡의 발매 정보와 제작 배경을 설명하는 문서이며
              실제 가사 내용은 수록되어 있지 않습니다.
            </td>
          </tr>
        </table>
        """

        self.assertIsNone(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source)
        )

    def test_repeated_lyrics_lines_are_preserved(self) -> None:
        source = """
        <table>
          <tr><th>원문</th><th>한국어 번역</th></tr>
          <tr><td>repeat</td><td>같은 후렴을 다시 불러</td></tr>
          <tr><td>repeat</td><td>같은 후렴을 다시 불러</td></tr>
        </table>
        """

        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(source),
            (
                "repeat\n"
                "같은 후렴을 다시 불러\n\n"
                "repeat\n"
                "같은 후렴을 다시 불러"
            ),
        )

NAMUMARK_MOVED_NAMES = (
    "NAMUMARK_FOOTNOTE_RE",
    "NAMUMARK_LINK_RE",
    "NAMUMARK_RUBY_RE",
    "NAMUMARK_STYLE_PREFIX_RE",
    "clean_namumark_cell",
    "parse_namumark_tables",
)


class MusicNamuMarkTablesTests(unittest.TestCase):
    def test_bot_reexports_moved_namumark_names(self) -> None:
        for name in NAMUMARK_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_clean_cell_preserves_existing_markup_removal(self) -> None:
        value = (
            "<rowbgcolor=#222> '''[ruby(泥濘, ruby=でいねい)]'''[br]"
            "[[노래|鳴鳴]][* 각주] [목차]"
        )
        self.assertEqual(
            music_namuwiki_parsing.clean_namumark_cell(value),
            "泥濘\n鳴鳴",
        )

    def test_parse_tables_preserves_rows_and_table_boundaries(self) -> None:
        source = (
            "|| 제목 || 값 ||\r\n"
            "|| 첫째 || 둘째 ||\r\n"
            "표 사이 본문\r\n"
            "|| 다른 || 표 ||\r\n"
        )
        self.assertEqual(
            music_namuwiki_parsing.parse_namumark_tables(source),
            [
                [["제목", "값"], ["첫째", "둘째"]],
                [["다른", "표"]],
            ],
        )

    def test_parse_multiline_row_preserves_cell_newlines(self) -> None:
        source = "|| 원문\n계속 || 번역 ||"
        self.assertEqual(
            music_namuwiki_parsing.parse_namumark_tables(source),
            [[["원문\n계속", "번역"]]],
        )


HEADER_MOVED_NAMES = (
    "best_namuwiki_header_column",
    "namuwiki_reading_header_score",
    "namuwiki_source_header_score",
    "namuwiki_translation_header_score",
)


class MusicNamuWikiHeaderTests(unittest.TestCase):
    def test_bot_reexports_moved_namuwiki_header_names(self) -> None:
        for name in HEADER_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_header_scores_preserve_specificity_and_normalization(self) -> None:
        self.assertEqual(
            music_namuwiki_parsing.namuwiki_translation_header_score(
                "한국어 번역"
            ),
            100,
        )
        self.assertEqual(
            music_namuwiki_parsing.namuwiki_translation_header_score("번역"),
            70,
        )
        self.assertEqual(
            music_namuwiki_parsing.namuwiki_source_header_score("일본어_원문"),
            100,
        )
        self.assertEqual(
            music_namuwiki_parsing.namuwiki_reading_header_score("요미가나"),
            70,
        )
        self.assertEqual(
            music_namuwiki_parsing.namuwiki_reading_header_score("작사"),
            0,
        )

    def test_best_column_uses_score_exclusions_and_later_tie(self) -> None:
        row = ["번역", "원문", "한국어 번역", "번역"]
        scorer = music_namuwiki_parsing.namuwiki_translation_header_score

        self.assertEqual(
            music_namuwiki_parsing.best_namuwiki_header_column(
                row, scorer, set()
            ),
            2,
        )
        self.assertEqual(
            music_namuwiki_parsing.best_namuwiki_header_column(
                row, scorer, {2}
            ),
            3,
        )
        self.assertIsNone(
            music_namuwiki_parsing.best_namuwiki_header_column(
                ["원문", "작사"],
                scorer,
                set(),
            )
        )


HTML_TABLE_MOVED_NAMES = (
    "NAMUWIKI_IGNORED_HTML_TAGS",
    "NAMUWIKI_VOID_HTML_TAGS",
    "NamuWikiHTMLTableParser",
    "_NamuWikiHTMLTableContext",
)


def parse_tables(source: str) -> list[list[list[str]]]:
    parser = music_namuwiki_parsing.NamuWikiHTMLTableParser()
    parser.feed(source)
    parser.close()
    return parser.tables


class MusicNamuWikiHTMLTablesTests(unittest.TestCase):
    def test_bot_reexports_moved_html_table_names(self) -> None:
        for name in HTML_TABLE_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_parser_preserves_cells_breaks_and_colspan(self) -> None:
        source = (
            "<table><tr><th colspan='2'>제목</th></tr>"
            "<tr><td>원문<br>계속</td><td>번역</td></tr></table>"
        )
        self.assertEqual(
            parse_tables(source),
            [[["제목", ""], ["원문\n계속", "번역"]]],
        )

    def test_parser_ignores_non_content_tags_and_file_images(self) -> None:
        source = (
            "<table><tr><td>앞<script>숨김</script>뒤"
            "<img alt='파일:표지'><img alt='음표'></td></tr></table>"
        )
        self.assertEqual(parse_tables(source), [[["앞뒤음표"]]])

    def test_parser_preserves_nested_table_boundaries(self) -> None:
        source = (
            "<table><tr><td>바깥<table><tr><td>안쪽</td></tr></table>"
            "계속</td></tr></table>"
        )
        self.assertEqual(
            parse_tables(source),
            [[["안쪽"]], [["바깥계속"]]],
        )


INTERLEAVED_MOVED_NAMES = (
    "extract_interleaved_namuwiki_groups",
    "extract_interleaved_namuwiki_lyrics",
    "normalize_namuwiki_table_text",
)


class MusicNamuWikiInterleavedTests(unittest.TestCase):
    def test_bot_reexports_moved_interleaved_names(self) -> None:
        for name in INTERLEAVED_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_table_text_normalization_preserves_single_blank_separators(self) -> None:
        value = " A&nbsp; B\r\n\r\n\u200b\r\n C\tD \n\n"
        self.assertEqual(
            music_namuwiki_parsing.normalize_namuwiki_table_text(value),
            "A B\n\nC D",
        )

    def test_interleaved_groups_and_lyrics_preserve_complete_triplets(self) -> None:
        rows = [
            ["君の声\n키미노 코에\n너의 목소리"],
            ["空へ\n소라에\n하늘로 간다"],
            ["夢を見る\n유메오 미루\n꿈을 꾸고 있어"],
        ]
        table_text = "\n".join(row[0] for row in rows)

        groups, translations, source_count = (
            music_namuwiki_parsing.extract_interleaved_namuwiki_groups(
                table_text
            )
        )

        self.assertEqual(source_count, 3)
        self.assertEqual(
            groups,
            [
                "君の声\n키미노 코에\n너의 목소리",
                "空へ\n소라에\n하늘로 간다",
                "夢を見る\n유메오 미루\n꿈을 꾸고 있어",
            ],
        )
        self.assertEqual(
            translations,
            ["너의 목소리", "하늘로 간다", "꿈을 꾸고 있어"],
        )
        self.assertEqual(
            music_namuwiki_parsing.extract_interleaved_namuwiki_lyrics(rows),
            "\n\n".join(groups),
        )

    def test_incomplete_interleaved_groups_are_rejected(self) -> None:
        rows = [
            ["君の声\n너의 목소리"],
            ["空へ\n하늘로"],
            ["夢を見る\n꿈을 꿔"],
        ]
        self.assertIsNone(
            music_namuwiki_parsing.extract_interleaved_namuwiki_lyrics(rows)
        )


class MusicNamuWikiTableLyricsTests(unittest.TestCase):
    def test_bot_reexports_table_lyrics_selector(self) -> None:
        self.assertIs(
            bot.extract_namuwiki_lyrics_from_tables,
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_tables,
        )

    def test_header_table_preserves_source_reading_and_translation(self) -> None:
        tables = [[
            ["일본어 원문", "일본어 독음", "한국어 번역"],
            ["泥濘 鳴鳴", "でいねい めいめい", "진창에서 울리는 노랫소리"],
            ["礼を持って", "れいをもって", "예를 갖추어 다시 걸어가"],
        ]]
        self.assertEqual(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_tables(
                tables
            ),
            (
                "泥濘 鳴鳴\nでいねい めいめい\n진창에서 울리는 노랫소리\n\n"
                "礼を持って\nれいをもって\n예를 갖추어 다시 걸어가"
            ),
        )

    def test_best_candidate_prefers_more_korean_lyrics(self) -> None:
        short_table = [
            ["원문", "한국어 번역"],
            ["First line", "짧지만 충분한 첫 번째 가사 문장입니다"],
            ["Second line", "두 번째 가사 문장입니다"],
        ]
        long_table = [
            ["원문", "한국어 번역"],
            ["First line", "더 많은 한글을 포함하는 긴 가사 문장입니다"],
            ["Second line", "이 후보가 최종 결과로 선택되어야 합니다"],
        ]
        result = music_namuwiki_parsing.extract_namuwiki_lyrics_from_tables(
            [short_table, long_table]
        )
        self.assertIn("최종 결과로 선택", result or "")

    def test_short_metadata_table_is_rejected(self) -> None:
        tables = [[["원문", "한국어 번역"], ["Title", "설명"]]]
        self.assertIsNone(
            music_namuwiki_parsing.extract_namuwiki_lyrics_from_tables(
                tables
            )
        )


VALIDATION_MOVED_NAMES = (
    "is_usable_namuwiki_lyrics",
    "is_valid_korean_translation",
)


class MusicNamuWikiValidationTests(unittest.TestCase):
    def test_bot_reexports_moved_namuwiki_validation_names(self) -> None:
        for name in VALIDATION_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_korean_translation_thresholds_are_preserved(self) -> None:
        self.assertTrue(
            music_namuwiki_parsing.is_valid_korean_translation(
                "가나다라마바사아\n번역"
            )
        )
        self.assertFalse(
            music_namuwiki_parsing.is_valid_korean_translation(
                "가나다라마바사아"
            )
        )
        self.assertTrue(
            music_namuwiki_parsing.is_valid_korean_translation(
                "가나다라마바사아" + " " * 22
            )
        )

    def test_usable_lyrics_require_structure_foreign_text_and_translation(self) -> None:
        usable = "君\n가나다라마바사아\n\n空\n하늘로 갑니다"
        self.assertTrue(
            music_namuwiki_parsing.is_usable_namuwiki_lyrics(usable)
        )

        self.assertFalse(
            music_namuwiki_parsing.is_usable_namuwiki_lyrics(
                "君\n가나다라마바사아"
            )
        )
        self.assertFalse(
            music_namuwiki_parsing.is_usable_namuwiki_lyrics(
                "가나다라마바사아\n번역\n\n하늘\n한국어 가사"
            )
        )
