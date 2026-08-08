import ast
import unittest
from pathlib import Path

import bot
import music_track_identity


MOVED_FUNCTION_NAMES = (
    "get_track_identity_keys",
    "get_track_video_id",
    "get_video_id",
    "normalize_track_key",
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
                "urllib.parse",
            },
        )
