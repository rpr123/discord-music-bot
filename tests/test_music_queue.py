import ast
import unittest
from collections import deque
from pathlib import Path

import bot
import music_queue


MOVED_FUNCTION_NAMES = (
    "remove_queued_track",
    "remove_queued_track_by_id",
    "remove_queued_track_range_by_ids",
)


class MusicQueueTests(unittest.TestCase):
    def test_bot_reexports_moved_queue_functions(self) -> None:
        for name in MOVED_FUNCTION_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_queue, name),
                )

    def test_module_does_not_import_bot(self) -> None:
        source = Path(music_queue.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertEqual(
            imported_modules,
            {"__future__", "collections", "music_models"},
        )

    def test_invalid_index_keeps_the_existing_queue(self) -> None:
        tracks = [self.make_track("first"), self.make_track("second")]
        queue = deque(tracks)
        state = bot.GuildMusicState(queue=queue)

        self.assertIsNone(music_queue.remove_queued_track(state, -1))
        self.assertIsNone(music_queue.remove_queued_track(state, len(tracks)))
        self.assertIs(state.queue, queue)
        self.assertEqual(list(state.queue), tracks)

    @staticmethod
    def make_track(title: str) -> bot.Track:
        return bot.Track(
            title=title,
            webpage_url=f"https://example.test/{title}",
            requester="tester",
            source_url=f"https://example.test/{title}",
        )
