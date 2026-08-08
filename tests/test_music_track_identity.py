import ast
import unittest
from collections import deque
from pathlib import Path

import bot
import music_track_identity


MOVED_FUNCTION_NAMES = (
    "get_autoplay_excluded_keys",
    "get_track_identity_keys",
    "get_track_video_id",
    "get_video_id",
    "normalize_track_key",
    "remember_autoplay_track",
    "remember_recent_value",
    "select_autoplay_candidate",
)


class MusicTrackIdentityTests(unittest.TestCase):
    def test_bot_reexports_moved_identity_functions(self) -> None:
        for name in MOVED_FUNCTION_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_track_identity, name),
                )

    def test_module_does_not_import_bot(self) -> None:
        source = Path(music_track_identity.__file__).read_text(encoding="utf-8")
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
                "typing",
                "urllib.parse",
            },
        )

    def test_remember_recent_value_moves_duplicates_to_the_end(self) -> None:
        values = deque(("first", "second", "third"), maxlen=3)

        music_track_identity.remember_recent_value(values, "first")

        self.assertEqual(list(values), ["second", "third", "first"])
