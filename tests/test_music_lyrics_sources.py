import ast
import unittest
from pathlib import Path

import bot
import music_lyrics_sources


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
    "VTT_TAG_RE",
    "VTT_TIMESTAMP_LINE_RE",
    "YouTubeSubtitleError",
    "extract_json3_lyrics",
    "extract_vtt_lyrics",
    "get_manual_subtitle_candidates",
    "get_subtitle_candidates",
    "normalize_subtitle_text",
    "select_korean_manual_subtitle",
    "select_manual_subtitle",
)


class MusicLyricsSourcesTests(unittest.TestCase):
    def test_bot_reexports_moved_lyrics_source_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_lyrics_sources, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_lyrics_sources.__file__).read_text(encoding="utf-8")
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
                "html",
                "json",
                "music_models",
                "music_search_scoring",
                "re",
                "unicodedata",
            },
        )

    def test_candidates_ignore_malformed_and_unsupported_formats(self) -> None:
        candidates = music_lyrics_sources.get_subtitle_candidates(
            {
                "ja": [
                    {"ext": "srt", "url": "https://example.test/unsupported"},
                    None,
                    {"ext": "JSON3", "url": "https://example.test/json3"},
                    {"ext": "vtt", "url": ""},
                ],
                "en": "not-a-list",
            }
        )

        self.assertEqual(
            candidates,
            [("ja", "json3", "https://example.test/json3", 30)],
        )

    def test_title_aliases_include_full_and_split_script_variants(self) -> None:
        self.assertEqual(
            music_lyrics_sources.get_lyrics_title_aliases(
                "らしさ - Rashisa"
            ),
            {"らしさ rashisa", "らしさ", "rashisa"},
        )
