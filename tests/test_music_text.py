import ast
import unittest
from pathlib import Path

import bot
import music_text
from music_models import Track


MOVED_NAMES = (
    "DISCORD_EMBED_FIELD_LIMIT",
    "format_duration",
    "make_queue_line",
    "make_track_link",
    "requester_label",
    "single_line",
    "truncate_option_text",
    "truncate_text",
)


def make_track(
    title: str = "Example Song",
    *,
    duration: int | None = 65,
    requester_id: int | None = None,
) -> Track:
    return Track(
        title=title,
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        requester_id=requester_id,
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        duration=duration,
    )


class MusicTextTests(unittest.TestCase):
    def test_bot_reexports_moved_text_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(getattr(bot, name), getattr(music_text, name))

    def test_module_depends_only_on_music_models(self) -> None:
        source = Path(music_text.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertEqual(imported_modules, {"__future__", "music_models"})

    def test_duration_and_requester_formatting_contract(self) -> None:
        self.assertEqual(music_text.format_duration(None), "live")
        self.assertEqual(music_text.format_duration(65), "1:05")
        self.assertEqual(music_text.format_duration(3661), "1:01:01")
        self.assertEqual(music_text.requester_label(make_track()), "tester")
        self.assertEqual(
            music_text.requester_label(make_track(requester_id=123)),
            "<@123>",
        )

    def test_link_queue_and_truncation_contract(self) -> None:
        track = make_track("  Example\n Song  ")

        self.assertEqual(music_text.single_line(track.title), "Example Song")
        self.assertEqual(music_text.truncate_text("abcd", 3), "ab…")
        self.assertEqual(
            music_text.make_track_link(track),
            "[Example Song](https://www.youtube.com/watch?v=abcdefghijk)",
        )
        self.assertEqual(music_text.make_queue_line(2, track), "2. Example Song - 1:05")
        self.assertEqual(music_text.truncate_option_text("abcd", 3), "ab…")
