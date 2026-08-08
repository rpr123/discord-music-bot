import ast
import unittest
from pathlib import Path

import bot
import music_playback_state
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "MAX_PLAYBACK_ATTEMPTS",
    "invalidate_track_stream",
    "requeue_track_after_playback_error",
    "reset_track_playback_attempts",
    "reset_track_playback_state",
)


def make_track(title: str) -> Track:
    return Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class MusicPlaybackStateTests(unittest.TestCase):
    def test_bot_reexports_moved_playback_state_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_playback_state, name),
                )

    def test_module_depends_only_on_music_models(self) -> None:
        source = Path(music_playback_state.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertEqual(imported_modules, {"__future__", "music_models"})

    def test_copy_error_requeues_track_with_fresh_transcode_state(self) -> None:
        track = make_track("retry")
        track.playback_attempts = 1
        track.stream_url = "https://example.test/audio.opus"
        track.stream_resolved_at = 123.0
        state = GuildMusicState(current=track)

        retrying = music_playback_state.requeue_track_after_playback_error(
            state,
            track,
            used_opus_copy=True,
        )

        self.assertTrue(retrying)
        self.assertEqual(list(state.queue), [track])
        self.assertIsNone(state.current)
        self.assertIsNone(track.stream_url)
        self.assertIsNone(track.stream_resolved_at)
        self.assertEqual(track.playback_attempts, 1)
        self.assertTrue(track.force_transcode)

    def test_final_error_resets_retry_state_without_requeueing(self) -> None:
        track = make_track("failed")
        track.playback_attempts = music_playback_state.MAX_PLAYBACK_ATTEMPTS
        track.force_transcode = True
        state = GuildMusicState(current=track)

        retrying = music_playback_state.requeue_track_after_playback_error(
            state,
            track,
            used_opus_copy=False,
        )

        self.assertFalse(retrying)
        self.assertEqual(list(state.queue), [])
        self.assertIsNone(state.current)
        self.assertEqual(track.playback_attempts, 0)
        self.assertFalse(track.force_transcode)
