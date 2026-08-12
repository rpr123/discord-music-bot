import ast
import unittest
from collections import deque
from pathlib import Path

import bot
import music_autoplay_policy
import music_track_metadata
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "AUTOPLAY_QUEUE_TARGET",
    "AUTOPLAY_RETRY_DELAYS_SECONDS",
    "autoplay_can_refill",
    "get_autoplay_excluded_keys",
    "get_autoplay_retry_delay",
    "get_autoplay_seed",
    "remember_autoplay_track",
    "remember_recent_value",
    "select_autoplay_candidate",
)


def make_track(
    title: str,
    *,
    video_id: str | None = None,
    artist: str | None = None,
    song_name: str | None = None,
    uploader: str | None = None,
) -> Track:
    video_id = video_id or f"{title:0<11}"[:11]
    url = f"https://www.youtube.com/watch?v={video_id}"
    return Track(
        title=title,
        webpage_url=url,
        requester="tester",
        source_url=url,
        artist=artist,
        song_name=song_name,
        uploader=uploader,
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

    def test_module_dependencies_are_limited(self) -> None:
        source = Path(music_autoplay_policy.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertEqual(
            imported_modules,
            {
                "__future__",
                "music_models",
                "music_track_metadata",
                "typing",
            },
        )

    def test_remember_recent_value_moves_duplicates_to_the_end(self) -> None:
        values = deque(("first", "second", "third"), maxlen=3)

        music_autoplay_policy.remember_recent_value(values, "first")

        self.assertEqual(list(values), ["second", "third", "first"])

    def test_remember_autoplay_track_records_key_and_video_history(self) -> None:
        state = GuildMusicState()
        track = make_track("played")

        music_autoplay_policy.remember_autoplay_track(state, track)

        self.assertEqual(
            list(state.recent_track_keys),
            [music_track_metadata.normalize_track_key(track)],
        )
        self.assertEqual(
            list(state.recent_video_ids),
            [music_track_metadata.get_track_video_id(track)],
        )

    def test_autoplay_excluded_keys_include_recent_current_and_queue(self) -> None:
        current = make_track("current")
        queued = make_track("queued")
        state = GuildMusicState(current=current)
        state.queue.append(queued)
        state.recent_track_keys.append("song:recent")
        state.recent_video_ids.append("abcdefghijk")

        excluded = music_autoplay_policy.get_autoplay_excluded_keys(state)

        self.assertIn("song:recent", excluded)
        self.assertIn("video:abcdefghijk", excluded)
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(current).issubset(excluded)
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(queued).issubset(excluded)
        )

    def test_select_autoplay_candidate_respects_all_exclusions_and_order(
        self,
    ) -> None:
        recent_key = make_track("recent key")
        recent_video = make_track("recent video", video_id="vvvvvvvvvvv")
        current = make_track("current")
        queued = make_track("queued")
        extra = make_track("extra")
        first_valid = make_track("first valid")
        second_valid = make_track("second valid")
        state = GuildMusicState(current=current)
        state.queue.append(queued)
        state.recent_track_keys.append(
            music_track_metadata.normalize_track_key(recent_key)
        )
        state.recent_video_ids.append("vvvvvvvvvvv")
        extra_excluded = music_track_metadata.get_track_identity_keys(extra)
        candidates = [
            recent_key,
            recent_video,
            current,
            queued,
            extra,
            first_valid,
            second_valid,
        ]

        self.assertIs(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                candidates,
                extra_excluded,
            ),
            first_valid,
        )

        all_excluded = set(extra_excluded)
        all_excluded.update(
            music_track_metadata.get_track_identity_keys(first_valid)
        )
        all_excluded.update(
            music_track_metadata.get_track_identity_keys(second_valid)
        )
        self.assertIsNone(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                candidates,
                all_excluded,
            )
        )

    def test_autoplay_skips_an_audio_duplicate_of_the_current_mv(self) -> None:
        current_mv = make_track(
            "Artist - Same Song (Official MV)",
            video_id="kkkkkkkkkkk",
        )
        duplicate_audio = make_track(
            "Artist - Same Song (Official Audio)",
            video_id="lllllllllll",
        )
        fresh = make_track(
            "Artist - Next Song (Official Audio)",
            video_id="mmmmmmmmmmm",
        )
        state = GuildMusicState(current=current_mv)

        self.assertIs(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                [duplicate_audio, fresh],
            ),
            fresh,
        )

    def test_autoplay_skips_recent_videos_when_metadata_changes(self) -> None:
        played_first = make_track(
            "First Artist - First Song",
            video_id="aaaaaaaaaaa",
            artist="First Artist",
            song_name="First Song",
        )
        played_second = make_track(
            "Second Artist - Second Song",
            video_id="bbbbbbbbbbb",
            artist="Second Artist",
            song_name="Second Song",
        )
        rediscovered_first = make_track(
            "First Song (Official Audio)",
            video_id="aaaaaaaaaaa",
            uploader="Archive Channel",
        )
        rediscovered_second = make_track(
            "Second Song (Official Audio)",
            video_id="bbbbbbbbbbb",
            uploader="Another Channel",
        )
        fresh = make_track(
            "Third Artist - Third Song",
            video_id="ccccccccccc",
        )
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(state, played_first)
        music_autoplay_policy.remember_autoplay_track(state, played_second)

        self.assertNotEqual(
            music_track_metadata.normalize_track_key(played_first),
            music_track_metadata.normalize_track_key(rediscovered_first),
        )
        self.assertNotEqual(
            music_track_metadata.normalize_track_key(played_second),
            music_track_metadata.normalize_track_key(rediscovered_second),
        )
        self.assertIs(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                [rediscovered_first, rediscovered_second, fresh],
            ),
            fresh,
        )

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
        self.assertEqual(music_autoplay_policy.AUTOPLAY_QUEUE_TARGET, 2)
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
