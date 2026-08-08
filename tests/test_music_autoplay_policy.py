import ast
import unittest
from pathlib import Path

import bot
import music_autoplay_policy
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "AUTOPLAY_RETRY_DELAYS_SECONDS",
    "autoplay_can_refill",
    "get_autoplay_retry_delay",
    "get_autoplay_seed",
)


def make_track(title: str) -> Track:
    return Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class Voice:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected

    def is_connected(self) -> bool:
        return self.connected


class MusicAutoplayPolicyTests(unittest.TestCase):
    def test_bot_reexports_moved_autoplay_policy_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_autoplay_policy, name),
                )

    def test_module_depends_only_on_music_models(self) -> None:
        source = Path(music_autoplay_policy.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertEqual(imported_modules, {"__future__", "music_models"})

    def test_autoplay_seed_prefers_queue_tail_then_current(self) -> None:
        current = make_track("current")
        first = make_track("first")
        last = make_track("last")
        state = GuildMusicState(current=current)

        self.assertIs(music_autoplay_policy.get_autoplay_seed(state), current)

        state.queue.extend([first, last])
        self.assertIs(music_autoplay_policy.get_autoplay_seed(state), last)

        state.queue.clear()
        state.current = None
        self.assertIsNone(music_autoplay_policy.get_autoplay_seed(state))

    def test_refill_policy_and_retry_delay_bounds(self) -> None:
        state = GuildMusicState(
            voice=Voice(),
            autoplay_enabled=True,
            playback_generation=7,
        )

        self.assertTrue(music_autoplay_policy.autoplay_can_refill(state, 7))
        state.queue.append(make_track("one"))
        self.assertTrue(music_autoplay_policy.autoplay_can_refill(state, 7))
        state.queue.append(make_track("two"))
        self.assertFalse(music_autoplay_policy.autoplay_can_refill(state, 7))

        state.queue.clear()
        self.assertFalse(music_autoplay_policy.autoplay_can_refill(state, 8))
        state.voice.connected = False
        self.assertFalse(music_autoplay_policy.autoplay_can_refill(state, 7))
        state.voice.connected = True
        state.autoplay_enabled = False
        self.assertFalse(music_autoplay_policy.autoplay_can_refill(state, 7))

        delays = music_autoplay_policy.AUTOPLAY_RETRY_DELAYS_SECONDS
        self.assertEqual(music_autoplay_policy.get_autoplay_retry_delay(-1), delays[0])
        self.assertEqual(music_autoplay_policy.get_autoplay_retry_delay(2), delays[2])
        self.assertEqual(music_autoplay_policy.get_autoplay_retry_delay(99), delays[-1])
