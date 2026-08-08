import ast
import unittest
from pathlib import Path

import bot
import music_script_detection
from music_models import Track


MOVED_NAMES = (
    "HANGUL_RE",
    "JAPANESE_HAN_RE",
    "JAPANESE_KANA_RE",
    "lyrics_are_japanese",
    "lyrics_are_primarily_korean",
)


def make_track(title: str = "Song") -> Track:
    return Track(
        title=title,
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
    )


class MusicScriptDetectionTests(unittest.TestCase):
    def test_bot_reexports_moved_script_detection_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_script_detection, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_script_detection.__file__).read_text(encoding="utf-8")
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

        self.assertEqual(imported_modules, {"__future__", "music_models", "re"})

    def test_japanese_detection_uses_subtitle_language_lyrics_and_title(self) -> None:
        language_track = make_track()
        language_track.subtitle_language = "ja-JP"
        self.assertTrue(
            music_script_detection.lyrics_are_japanese(language_track, "English")
        )

        self.assertTrue(
            music_script_detection.lyrics_are_japanese(
                make_track(),
                "きみの声が聞こえる",
            )
        )
        self.assertTrue(
            music_script_detection.lyrics_are_japanese(
                make_track("カタカナ Song"),
                "English",
            )
        )
        self.assertFalse(
            music_script_detection.lyrics_are_japanese(make_track(), "English")
        )

    def test_korean_detection_uses_letter_ratio_and_handles_empty_text(self) -> None:
        self.assertTrue(music_script_detection.lyrics_are_primarily_korean("가a"))
        self.assertFalse(music_script_detection.lyrics_are_primarily_korean("가ab"))
        self.assertFalse(music_script_detection.lyrics_are_primarily_korean("123 !"))
