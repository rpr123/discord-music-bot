import ast
import unittest
from pathlib import Path

import bot
import music_lyrics_matching


MOVED_NAMES = (
    "LRC_METADATA_RE",
    "LRC_TIMESTAMP_RE",
    "LYRICS_DURATION_MATCH_TOLERANCE_SECONDS",
    "LYRICS_NATIVE_SCRIPT_MIN_RATIO",
    "LYRICS_NATIVE_SCRIPT_SCORE_WINDOW",
    "QUOTED_TRACK_TITLE_RE",
    "extract_original_lyrics",
    "get_lyrics_search_terms",
    "get_lyrics_title_aliases",
    "lyrics_native_script_ratio",
    "lyrics_record_score",
    "normalize_lyrics_match_text",
    "select_lyrics_record",
)


class MusicLyricsMatchingTests(unittest.TestCase):
    def test_bot_reexports_moved_lyrics_matching_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_lyrics_matching, name),
                )

    def test_module_does_not_import_bot(self) -> None:
        source = Path(music_lyrics_matching.__file__).read_text(encoding="utf-8")
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
                "music_models",
                "music_search_scoring",
                "re",
                "unicodedata",
            },
        )

    def test_title_aliases_include_full_and_split_script_variants(self) -> None:
        self.assertEqual(
            music_lyrics_matching.get_lyrics_title_aliases(
                "らしさ - Rashisa"
            ),
            {"らしさ rashisa", "らしさ", "rashisa"},
        )
