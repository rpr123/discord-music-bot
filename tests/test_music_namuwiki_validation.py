import ast
import unittest
from pathlib import Path

import bot
import music_namuwiki_validation


MOVED_NAMES = (
    "is_usable_namuwiki_lyrics",
    "is_valid_korean_translation",
)


class MusicNamuWikiValidationTests(unittest.TestCase):
    def test_bot_reexports_moved_namuwiki_validation_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_validation, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_validation.__file__).read_text(
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
            {"__future__", "music_script_detection", "re"},
        )

    def test_korean_translation_thresholds_are_preserved(self) -> None:
        self.assertTrue(
            music_namuwiki_validation.is_valid_korean_translation(
                "가나다라마바사아\n번역"
            )
        )
        self.assertFalse(
            music_namuwiki_validation.is_valid_korean_translation(
                "가나다라마바사아"
            )
        )
        self.assertTrue(
            music_namuwiki_validation.is_valid_korean_translation(
                "가나다라마바사아" + " " * 22
            )
        )

    def test_usable_lyrics_require_structure_foreign_text_and_translation(self) -> None:
        usable = "君\n가나다라마바사아\n\n空\n하늘로 갑니다"
        self.assertTrue(music_namuwiki_validation.is_usable_namuwiki_lyrics(usable))

        self.assertFalse(
            music_namuwiki_validation.is_usable_namuwiki_lyrics(
                "君\n가나다라마바사아"
            )
        )
        self.assertFalse(
            music_namuwiki_validation.is_usable_namuwiki_lyrics(
                "가나다라마바사아\n번역\n\n하늘\n한국어 가사"
            )
        )
