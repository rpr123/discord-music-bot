import ast
import unittest
from pathlib import Path

import bot
import music_subtitles


MOVED_NAMES = (
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


class MusicSubtitleTests(unittest.TestCase):
    def test_bot_reexports_moved_subtitle_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_subtitles, name),
                )

    def test_module_does_not_import_bot(self) -> None:
        source = Path(music_subtitles.__file__).read_text(encoding="utf-8")
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
            {"__future__", "html", "json", "music_models", "re"},
        )

    def test_candidates_ignore_malformed_and_unsupported_formats(self) -> None:
        candidates = music_subtitles.get_subtitle_candidates(
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
