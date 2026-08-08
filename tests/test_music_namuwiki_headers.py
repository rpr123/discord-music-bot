import ast
import unittest
from pathlib import Path

import bot
import music_namuwiki_headers


MOVED_NAMES = (
    "best_namuwiki_header_column",
    "namuwiki_reading_header_score",
    "namuwiki_source_header_score",
    "namuwiki_translation_header_score",
)


class MusicNamuWikiHeaderTests(unittest.TestCase):
    def test_bot_reexports_moved_namuwiki_header_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_headers, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_headers.__file__).read_text(encoding="utf-8")
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

        self.assertEqual(imported_modules, {"__future__", "re", "typing"})

    def test_header_scores_preserve_specificity_and_normalization(self) -> None:
        self.assertEqual(
            music_namuwiki_headers.namuwiki_translation_header_score(
                "한국어 번역"
            ),
            100,
        )
        self.assertEqual(
            music_namuwiki_headers.namuwiki_translation_header_score("번역"),
            70,
        )
        self.assertEqual(
            music_namuwiki_headers.namuwiki_source_header_score("일본어_원문"),
            100,
        )
        self.assertEqual(
            music_namuwiki_headers.namuwiki_reading_header_score("요미가나"),
            70,
        )
        self.assertEqual(
            music_namuwiki_headers.namuwiki_reading_header_score("작사"),
            0,
        )

    def test_best_column_uses_score_exclusions_and_later_tie(self) -> None:
        row = ["번역", "원문", "한국어 번역", "번역"]
        scorer = music_namuwiki_headers.namuwiki_translation_header_score

        self.assertEqual(
            music_namuwiki_headers.best_namuwiki_header_column(row, scorer, set()),
            2,
        )
        self.assertEqual(
            music_namuwiki_headers.best_namuwiki_header_column(row, scorer, {2}),
            3,
        )
        self.assertIsNone(
            music_namuwiki_headers.best_namuwiki_header_column(
                ["원문", "작사"],
                scorer,
                set(),
            )
        )
