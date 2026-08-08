import ast
import unittest
from pathlib import Path

import bot
import music_explicit_readings


MOVED_NAMES = (
    "EXPLICIT_READING_BRACKETS",
    "find_explicit_reading_base_start",
    "find_explicit_reading_replacements",
    "protect_explicit_readings",
    "replace_explicit_readings",
)


class FakeToken:
    def __init__(self, surface: str) -> None:
        self._surface = surface

    def surface(self) -> str:
        return self._surface


class FakeTokenizer:
    def tokenize(self, text: str) -> list[FakeToken]:
        return [FakeToken(text)] if text else []


class MusicExplicitReadingsTests(unittest.TestCase):
    def test_bot_reexports_moved_explicit_reading_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_explicit_readings, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_explicit_readings.__file__).read_text(encoding="utf-8")
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
                "music_japanese_reading",
                "music_script_detection",
                "re",
                "unicodedata",
            },
        )

    def test_explicit_reading_brackets_are_normalized(self) -> None:
        tokenizer = FakeTokenizer()
        examples = {
            "運命(サダメ)": "運命(さだめ)",
            "運命《さだめ》": "運命(さだめ)",
            "｜運命【さだめ】": "運命(さだめ)",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(
                    music_explicit_readings.replace_explicit_readings(
                        source,
                        tokenizer,
                    ),
                    expected,
                )

        self.assertEqual(
            music_explicit_readings.replace_explicit_readings(
                "運命(love)",
                tokenizer,
            ),
            "運命(love)",
        )

    def test_protection_uses_an_unused_private_placeholder(self) -> None:
        tokenizer = FakeTokenizer()
        protected_line, replacements = music_explicit_readings.protect_explicit_readings(
            "運命(さだめ)\ue000",
            tokenizer,
        )

        self.assertEqual(protected_line, "\ue001\ue000")
        self.assertEqual(replacements, {"\ue001": "運命(さだめ)"})
