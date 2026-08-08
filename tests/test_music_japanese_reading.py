import ast
import unittest
from pathlib import Path

import bot
import music_japanese_reading


MOVED_NAMES = (
    "JAPANESE_READING_RE",
    "annotate_japanese_reading",
    "get_reading_surface_segment_kind",
    "katakana_to_hiragana",
    "normalize_japanese_reading",
    "split_reading_surface",
)


class MusicJapaneseReadingTests(unittest.TestCase):
    def test_bot_reexports_moved_japanese_reading_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_japanese_reading, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_japanese_reading.__file__).read_text(encoding="utf-8")
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
                "functools",
                "music_script_detection",
                "re",
                "unicodedata",
            },
        )

    def test_reading_normalization_converts_katakana_and_whitespace(self) -> None:
        self.assertEqual(
            music_japanese_reading.katakana_to_hiragana("カタカナ"),
            "かたかな",
        )
        self.assertEqual(
            music_japanese_reading.normalize_japanese_reading(
                "カタカナ  \tテスト"
            ),
            "かたかな てすと",
        )

    def test_surface_segmentation_groups_adjacent_character_kinds(self) -> None:
        self.assertEqual(
            music_japanese_reading.split_reading_surface("漢かな ABC!"),
            [
                ("han", "漢"),
                ("anchor", "かな"),
                ("space", " "),
                ("anchor", "ABC"),
                ("optional", "!"),
            ],
        )
        self.assertEqual(
            music_japanese_reading.get_reading_surface_segment_kind("ー"),
            "anchor",
        )

    def test_annotation_aligns_kanji_with_normalized_reading(self) -> None:
        self.assertEqual(
            music_japanese_reading.annotate_japanese_reading("食べる", "タベル"),
            "食(た)べる",
        )
        self.assertEqual(
            music_japanese_reading.annotate_japanese_reading("かな", "カナ"),
            "かな",
        )
