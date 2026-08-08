import ast
import unittest
from pathlib import Path

import bot
import music_namumark_tables


MOVED_NAMES = (
    "NAMUMARK_FOOTNOTE_RE",
    "NAMUMARK_LINK_RE",
    "NAMUMARK_RUBY_RE",
    "NAMUMARK_STYLE_PREFIX_RE",
    "clean_namumark_cell",
    "parse_namumark_tables",
)


class MusicNamuMarkTablesTests(unittest.TestCase):
    def test_bot_reexports_moved_namumark_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namumark_tables, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namumark_tables.__file__).read_text(
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
            {"__future__", "music_namuwiki_interleaved", "re"},
        )

    def test_clean_cell_preserves_existing_markup_removal(self) -> None:
        value = (
            "<rowbgcolor=#222> '''[ruby(泥濘, ruby=でいねい)]'''[br]"
            "[[노래|鳴鳴]][* 각주] [목차]"
        )
        self.assertEqual(
            music_namumark_tables.clean_namumark_cell(value),
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
            music_namumark_tables.parse_namumark_tables(source),
            [
                [["제목", "값"], ["첫째", "둘째"]],
                [["다른", "표"]],
            ],
        )

    def test_parse_multiline_row_preserves_cell_newlines(self) -> None:
        source = "|| 원문\n계속 || 번역 ||"
        self.assertEqual(
            music_namumark_tables.parse_namumark_tables(source),
            [[["원문\n계속", "번역"]]],
        )
