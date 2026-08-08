import ast
import unittest
from pathlib import Path

import bot
import music_namuwiki_html_tables


MOVED_NAMES = (
    "NAMUWIKI_IGNORED_HTML_TAGS",
    "NAMUWIKI_VOID_HTML_TAGS",
    "NamuWikiHTMLTableParser",
    "_NamuWikiHTMLTableContext",
)


def parse_tables(source: str) -> list[list[list[str]]]:
    parser = music_namuwiki_html_tables.NamuWikiHTMLTableParser()
    parser.feed(source)
    parser.close()
    return parser.tables


class MusicNamuWikiHTMLTablesTests(unittest.TestCase):
    def test_bot_reexports_moved_html_table_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_html_tables, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_html_tables.__file__).read_text(
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
                "html.parser",
                "music_namuwiki_interleaved",
            },
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
