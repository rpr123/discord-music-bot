import ast
import unittest
from collections import deque
from pathlib import Path

import bot
import music_autoplay_policy
import music_track_metadata
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "AUTOPLAY_CANDIDATE_POOL_CAP",
    "AUTOPLAY_QUEUE_TARGET",
    "AUTOPLAY_RETRY_DELAYS_SECONDS",
    "autoplay_can_refill",
    "clear_autoplay_candidate_pool",
    "consume_autoplay_candidate",
    "get_autoplay_excluded_keys",
    "get_autoplay_recent_overlap_counts",
    "get_autoplay_recent_penalty",
    "get_autoplay_refill_candidate_count",
    "get_recent_playbacks",
    "get_autoplay_retry_delay",
    "get_autoplay_seed",
    "remember_autoplay_track",
    "remember_recent_playback",
    "remember_recent_value",
    "replace_autoplay_candidate_pool",
    "select_autoplay_candidate",
    "select_autoplay_candidates",
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
                "music_config",
                "music_models",
                "music_track_metadata",
                "typing",
            },
        )

    def test_remember_recent_value_moves_duplicates_to_the_end(self) -> None:
        values = deque(maxlen=3)
        for value in ("first", "second", "third"):
            music_autoplay_policy.remember_recent_value(
                values,
                value,
                now=0.0,
            )

        music_autoplay_policy.remember_recent_value(values, "first", now=0.0)

        self.assertEqual(
            [entry.value for entry in values],
            ["second", "third", "first"],
        )

    def test_remember_autoplay_track_records_key_and_video_history(self) -> None:
        state = GuildMusicState()
        track = make_track("played")
        now = 100.0

        music_autoplay_policy.remember_autoplay_track(state, track, now=now)

        self.assertEqual(
            [entry.value for entry in state.recent_track_keys],
            [music_track_metadata.normalize_track_key(track)],
        )
        self.assertEqual(
            [entry.value for entry in state.recent_video_ids],
            [music_track_metadata.get_track_video_id(track)],
        )
        expected_expiry = now + music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS
        self.assertEqual(state.recent_track_keys[0].expires_at, expected_expiry)
        self.assertEqual(state.recent_video_ids[0].expires_at, expected_expiry)

    def test_recent_playback_snapshot_is_newest_first_with_display_data(
        self,
    ) -> None:
        state = GuildMusicState()
        first = make_track("First", video_id="aaaaaaaaaaa")
        second = make_track("Second", video_id="bbbbbbbbbbb")

        music_autoplay_policy.remember_recent_playback(
            state,
            first,
            now=10.0,
            played_at=1_700_000_000.0,
        )
        music_autoplay_policy.remember_recent_playback(
            state,
            second,
            now=20.0,
            played_at=1_700_000_100.0,
        )

        entries = music_autoplay_policy.get_recent_playbacks(state, now=20.0)

        self.assertEqual([entry.title for entry in entries], ["Second", "First"])
        self.assertEqual(entries[0].webpage_url, second.webpage_url)
        self.assertEqual(entries[0].played_at, 1_700_000_100.0)
        self.assertEqual(
            entries[0].identity_keys,
            frozenset(music_track_metadata.get_track_identity_keys(second)),
        )
        self.assertEqual(
            entries[0].expires_at,
            20.0 + music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS,
        )

    def test_recent_playback_preserves_repeats_and_overlapping_aliases(self) -> None:
        state = GuildMusicState()
        first = make_track(
            "First display",
            video_id="aaaaaaaaaaa",
            artist="Artist A",
            song_name="Song A",
        )
        second = make_track(
            "Second display",
            video_id="bbbbbbbbbbb",
            artist="Artist B",
            song_name="Song B",
        )
        bridge = make_track(
            "Bridge display",
            video_id="bbbbbbbbbbb",
            artist="Artist A",
            song_name="Song A",
        )
        music_autoplay_policy.remember_recent_playback(state, first, now=1.0)
        music_autoplay_policy.remember_recent_playback(state, second, now=2.0)
        music_autoplay_policy.remember_recent_playback(state, bridge, now=3.0)
        music_autoplay_policy.remember_recent_playback(state, first, now=4.0)

        entries = music_autoplay_policy.get_recent_playbacks(state, now=4.0)
        self.assertEqual(
            [entry.title for entry in entries],
            ["First display", "Bridge display", "Second display", "First display"],
        )

    def test_recent_playback_history_prunes_expired_entries_and_caps_at_fifty(
        self,
    ) -> None:
        state = GuildMusicState()
        tracks = [
            make_track(f"track {index}", video_id=f"{index:011d}")
            for index in range(51)
        ]
        for index, track in enumerate(tracks):
            music_autoplay_policy.remember_recent_playback(
                state,
                track,
                now=float(index),
                played_at=1_700_000_000.0 + index,
            )

        entries = music_autoplay_policy.get_recent_playbacks(state, now=50.0)
        self.assertEqual(len(entries), 50)
        self.assertNotIn("track 0", {entry.title for entry in entries})

        entries = music_autoplay_policy.get_recent_playbacks(
            state,
            now=music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS + 25.0,
        )
        self.assertEqual(
            [entry.title for entry in entries],
            [f"track {index}" for index in range(50, 25, -1)],
        )

    def test_autoplay_history_expires_at_configured_ttl(self) -> None:
        state = GuildMusicState()
        track = make_track("played")
        played_at = 100.0
        track_keys = music_track_metadata.get_track_identity_keys(track)
        ttl = music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS
        music_autoplay_policy.remember_autoplay_track(
            state,
            track,
            now=played_at,
        )

        before_expiry = music_autoplay_policy.get_autoplay_excluded_keys(
            state,
            now=played_at + ttl - 0.001,
        )
        self.assertTrue(track_keys.issubset(before_expiry))

        at_expiry = music_autoplay_policy.get_autoplay_excluded_keys(
            state,
            now=played_at + ttl,
        )
        self.assertTrue(track_keys.isdisjoint(at_expiry))
        self.assertFalse(state.recent_track_keys)
        self.assertFalse(state.recent_video_ids)

    def test_autoplay_history_prunes_only_expired_front_entries(self) -> None:
        state = GuildMusicState()
        old = make_track("old", video_id="aaaaaaaaaaa")
        fresh = make_track("fresh", video_id="bbbbbbbbbbb")
        ttl = music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS
        music_autoplay_policy.remember_autoplay_track(state, old, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, fresh, now=ttl * 0.5)

        excluded = music_autoplay_policy.get_autoplay_excluded_keys(
            state,
            now=ttl * 1.25,
        )

        self.assertTrue(
            music_track_metadata.get_track_identity_keys(old).isdisjoint(excluded)
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(fresh).issubset(excluded)
        )
        self.assertEqual(
            [entry.value for entry in state.recent_track_keys],
            [music_track_metadata.normalize_track_key(fresh)],
        )
        self.assertEqual(
            [entry.value for entry in state.recent_video_ids],
            [music_track_metadata.get_track_video_id(fresh)],
        )

    def test_replaying_track_refreshes_expiry_and_order(self) -> None:
        state = GuildMusicState()
        first = make_track("first", video_id="aaaaaaaaaaa")
        second = make_track("second", video_id="bbbbbbbbbbb")
        ttl = music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS
        music_autoplay_policy.remember_autoplay_track(state, first, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, second, now=ttl * 0.1)
        music_autoplay_policy.remember_autoplay_track(state, first, now=ttl * 0.2)

        self.assertEqual(
            [entry.value for entry in state.recent_track_keys],
            [
                music_track_metadata.normalize_track_key(second),
                music_track_metadata.normalize_track_key(first),
            ],
        )

        excluded = music_autoplay_policy.get_autoplay_excluded_keys(
            state,
            now=ttl * 1.15,
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(second).isdisjoint(excluded)
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(first).issubset(excluded)
        )

    def test_autoplay_history_keeps_only_fifty_most_recent_tracks(self) -> None:
        state = GuildMusicState()
        tracks = [
            make_track(f"track {index}", video_id=f"{index:011d}")
            for index in range(51)
        ]

        for track in tracks:
            music_autoplay_policy.remember_autoplay_track(
                state,
                track,
                now=0.0,
            )

        self.assertEqual(len(state.recent_track_keys), 50)
        self.assertEqual(len(state.recent_video_ids), 50)
        excluded = music_autoplay_policy.get_autoplay_excluded_keys(state, now=0.0)
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(tracks[0]).isdisjoint(excluded)
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(tracks[-1]).issubset(excluded)
        )

    def test_expired_history_still_excludes_current_and_queued_tracks(self) -> None:
        current = make_track("current", video_id="aaaaaaaaaaa")
        queued = make_track("queued", video_id="bbbbbbbbbbb")
        state = GuildMusicState(current=current)
        state.queue.append(queued)
        music_autoplay_policy.remember_autoplay_track(state, current, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, queued, now=0.0)

        excluded = music_autoplay_policy.get_autoplay_excluded_keys(
            state,
            now=music_autoplay_policy.AUTOPLAY_HISTORY_TTL_SECONDS,
        )

        self.assertFalse(state.recent_track_keys)
        self.assertFalse(state.recent_video_ids)
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(current).issubset(excluded)
        )
        self.assertTrue(
            music_track_metadata.get_track_identity_keys(queued).issubset(excluded)
        )

    def test_autoplay_excluded_keys_include_recent_current_and_queue(self) -> None:
        current = make_track("current")
        queued = make_track("queued")
        state = GuildMusicState(current=current)
        state.queue.append(queued)
        music_autoplay_policy.remember_recent_value(
            state.recent_track_keys,
            "song:recent",
            now=0.0,
        )
        music_autoplay_policy.remember_recent_value(
            state.recent_video_ids,
            "abcdefghijk",
            now=0.0,
        )

        excluded = music_autoplay_policy.get_autoplay_excluded_keys(state, now=0.0)

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
        music_autoplay_policy.remember_recent_value(
            state.recent_track_keys,
            music_track_metadata.normalize_track_key(recent_key),
            now=0.0,
        )
        music_autoplay_policy.remember_recent_value(
            state.recent_video_ids,
            "vvvvvvvvvvv",
            now=0.0,
        )
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
                now=0.0,
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
                now=0.0,
            )
        )

    def test_recent_fallback_prefers_fresh_candidate(self) -> None:
        recent = make_track("recent", video_id="aaaaaaaaaaa")
        fresh = make_track("fresh", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(state, recent, now=0.0)

        selected = music_autoplay_policy.select_autoplay_candidate(
            state,
            [recent, fresh],
            allow_recent_fallback=True,
            now=1.0,
        )

        self.assertIs(selected, fresh)

    def test_recent_fallback_uses_latest_matching_identity_expiry(self) -> None:
        first = make_track("first", video_id="aaaaaaaaaaa")
        second = make_track("second", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_recent_value(
            state.recent_track_keys,
            music_track_metadata.normalize_track_key(first),
            now=0.0,
        )
        music_autoplay_policy.remember_autoplay_track(state, second, now=50.0)
        music_autoplay_policy.remember_recent_value(
            state.recent_video_ids,
            "aaaaaaaaaaa",
            now=100.0,
        )
        track_history_before = tuple(state.recent_track_keys)
        video_history_before = tuple(state.recent_video_ids)

        selected = music_autoplay_policy.select_autoplay_candidate(
            state,
            [first, second],
            allow_recent_fallback=True,
            now=101.0,
        )

        self.assertIs(selected, second)
        self.assertEqual(tuple(state.recent_track_keys), track_history_before)
        self.assertEqual(tuple(state.recent_video_ids), video_history_before)

    def test_recent_fallback_never_relaxes_current_queue_or_seed(self) -> None:
        current = make_track("current", video_id="aaaaaaaaaaa")
        queued = make_track("queued", video_id="bbbbbbbbbbb")
        seed = make_track("seed", video_id="ccccccccccc")
        allowed_recent = make_track("allowed", video_id="ddddddddddd")
        state = GuildMusicState(current=current)
        state.queue.append(queued)
        for track in (current, queued, seed, allowed_recent):
            music_autoplay_policy.remember_autoplay_track(state, track, now=0.0)
        seed_keys = music_track_metadata.get_track_identity_keys(seed)

        self.assertIs(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                [current, queued, seed, allowed_recent],
                seed_keys,
                allow_recent_fallback=True,
                now=1.0,
            ),
            allowed_recent,
        )
        self.assertIsNone(
            music_autoplay_policy.select_autoplay_candidate(
                state,
                [current, queued, seed],
                seed_keys,
                allow_recent_fallback=True,
                now=1.0,
            )
        )

    def test_recent_fallback_preserves_source_order_for_equal_expiry(self) -> None:
        first = make_track("first", video_id="aaaaaaaaaaa")
        second = make_track("second", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(state, first, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, second, now=0.0)

        selected = music_autoplay_policy.select_autoplay_candidate(
            state,
            [second, first],
            allow_recent_fallback=True,
            now=1.0,
        )

        self.assertIs(selected, second)

    def test_recent_fallback_allows_two_song_catalog_to_alternate(self) -> None:
        first = make_track("first", video_id="aaaaaaaaaaa")
        second = make_track("second", video_id="bbbbbbbbbbb")
        state = GuildMusicState(current=second)
        music_autoplay_policy.remember_autoplay_track(state, first, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, second, now=1.0)

        selected = music_autoplay_policy.select_autoplay_candidate(
            state,
            [second, first],
            music_track_metadata.get_track_identity_keys(second),
            allow_recent_fallback=True,
            now=2.0,
        )

        self.assertIs(selected, first)

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

    def test_candidate_batch_prefers_all_fresh_then_oldest_recent(self) -> None:
        current = make_track("current", video_id="ccccccccccc")
        hard_excluded = make_track("seed", video_id="sssssssssss")
        recent_old = make_track("recent old", video_id="aaaaaaaaaaa")
        recent_new = make_track("recent new", video_id="bbbbbbbbbbb")
        fresh_first = make_track("fresh first", video_id="ddddddddddd")
        fresh_second = make_track("fresh second", video_id="eeeeeeeeeee")
        state = GuildMusicState(current=current)
        music_autoplay_policy.remember_autoplay_track(state, recent_old, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, recent_new, now=10.0)

        selected = music_autoplay_policy.select_autoplay_candidates(
            state,
            [
                recent_new,
                current,
                hard_excluded,
                recent_old,
                fresh_first,
                fresh_second,
            ],
            music_track_metadata.get_track_identity_keys(hard_excluded),
            limit=10,
            now=20.0,
        )

        self.assertEqual(
            selected,
            [fresh_first, fresh_second, recent_old, recent_new],
        )
        self.assertEqual(
            music_autoplay_policy.select_autoplay_candidates(
                state,
                [fresh_first],
                limit=0,
                now=20.0,
            ),
            [],
        )

    def test_recent_overlap_counts_ignore_hard_exclusions_and_duplicates(
        self,
    ) -> None:
        current = make_track("current", video_id="ccccccccccc")
        seed = make_track("seed", video_id="sssssssssss")
        recent = make_track("recent", video_id="aaaaaaaaaaa")
        recent_alias = make_track("renamed", video_id="aaaaaaaaaaa")
        fresh = make_track("fresh", video_id="fffffffffff")
        state = GuildMusicState(current=current)
        music_autoplay_policy.remember_autoplay_track(state, recent, now=0.0)

        counts = music_autoplay_policy.get_autoplay_recent_overlap_counts(
            state,
            [current, seed, recent, recent_alias, fresh],
            music_track_metadata.get_track_identity_keys(seed),
            now=1.0,
        )

        self.assertEqual(counts, (1, 2))

    def test_recent_overlap_controls_penalty_and_next_fetch_limit(self) -> None:
        cases = (
            (0, 0, 80, 10),
            (2, 10, 80, 10),
            (3, 10, 40, 12),
            (5, 10, 40, 12),
            (6, 10, 10, 15),
            (10, 10, 10, 15),
        )

        for recent, considered, penalty, fetch_limit in cases:
            with self.subTest(recent=recent, considered=considered):
                self.assertEqual(
                    music_autoplay_policy.get_autoplay_recent_penalty(
                        recent,
                        considered,
                    ),
                    penalty,
                )
                self.assertEqual(
                    music_autoplay_policy.get_autoplay_refill_candidate_count(
                        10,
                        recent,
                        considered,
                    ),
                    fetch_limit,
                )

        self.assertEqual(
            music_autoplay_policy.get_autoplay_refill_candidate_count(20, 10, 10),
            20,
        )

    def test_quality_can_outweigh_recent_penalty_without_relaxing_hard_keys(
        self,
    ) -> None:
        recent_official = make_track("official", video_id="aaaaaaaaaaa")
        fresh_cover = make_track("cover", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(
            state,
            recent_official,
            now=0.0,
        )
        setattr(recent_official, "_autoplay_score", 161)
        setattr(fresh_cover, "_autoplay_score", -20)

        selected = music_autoplay_policy.select_autoplay_candidates(
            state,
            [fresh_cover, recent_official],
            limit=2,
            recent_penalty=80,
            now=1.0,
        )

        self.assertEqual(selected, [recent_official, fresh_cover])
        self.assertEqual(
            getattr(recent_official, "_autoplay_selection_score"),
            81,
        )
        self.assertEqual(
            getattr(fresh_cover, "_autoplay_selection_score"),
            -20,
        )
        self.assertIsNone(
            music_autoplay_policy.select_autoplay_candidate(
                GuildMusicState(current=recent_official),
                [recent_official],
                allow_recent_fallback=True,
                recent_penalty=10,
                now=1.0,
            )
        )

    def test_candidate_pool_replace_caps_in_order_and_clear_empties(self) -> None:
        state = GuildMusicState()
        candidates = [make_track(f"candidate {index}") for index in range(8)]

        music_autoplay_policy.replace_autoplay_candidate_pool(state, candidates)

        self.assertEqual(
            list(state.autoplay_candidate_pool),
            candidates[: music_autoplay_policy.AUTOPLAY_CANDIDATE_POOL_CAP],
        )
        state.autoplay_next_fetch_limit = 15
        music_autoplay_policy.clear_autoplay_candidate_pool(state)
        self.assertFalse(state.autoplay_candidate_pool)
        self.assertIsNone(state.autoplay_next_fetch_limit)

    def test_consume_pool_preserves_score_aware_recent_order(self) -> None:
        recent_official = make_track("official", video_id="aaaaaaaaaaa")
        fresh_cover = make_track("cover", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(
            state,
            recent_official,
            now=0.0,
        )
        setattr(recent_official, "_autoplay_score", 161)
        setattr(recent_official, "_autoplay_recent_penalty", 80)
        setattr(fresh_cover, "_autoplay_score", -20)
        setattr(fresh_cover, "_autoplay_recent_penalty", 80)
        music_autoplay_policy.replace_autoplay_candidate_pool(
            state,
            [recent_official, fresh_cover],
        )

        selected = music_autoplay_policy.consume_autoplay_candidate(
            state,
            now=1.0,
        )

        self.assertIs(selected, recent_official)
        self.assertEqual(list(state.autoplay_candidate_pool), [fresh_cover])

    def test_consume_pool_revalidates_hard_exclusions_and_prefers_fresh(
        self,
    ) -> None:
        queued = make_track("queued", video_id="qqqqqqqqqqq")
        seed = make_track("seed", video_id="sssssssssss")
        recent = make_track("recent", video_id="rrrrrrrrrrr")
        fresh = make_track("fresh", video_id="fffffffffff")
        state = GuildMusicState(queue=deque([queued]))
        music_autoplay_policy.remember_autoplay_track(state, recent, now=0.0)
        music_autoplay_policy.replace_autoplay_candidate_pool(
            state,
            [queued, seed, recent, fresh],
        )

        selected = music_autoplay_policy.consume_autoplay_candidate(
            state,
            music_track_metadata.get_track_identity_keys(seed),
            now=1.0,
        )

        self.assertIs(selected, fresh)
        self.assertEqual(list(state.autoplay_candidate_pool), [recent])

    def test_consume_pool_falls_back_to_oldest_recent_candidate(self) -> None:
        recent_old = make_track("recent old", video_id="aaaaaaaaaaa")
        recent_new = make_track("recent new", video_id="bbbbbbbbbbb")
        state = GuildMusicState()
        music_autoplay_policy.remember_autoplay_track(state, recent_old, now=0.0)
        music_autoplay_policy.remember_autoplay_track(state, recent_new, now=10.0)
        music_autoplay_policy.replace_autoplay_candidate_pool(
            state,
            [recent_new, recent_old],
        )

        selected = music_autoplay_policy.consume_autoplay_candidate(
            state,
            now=20.0,
        )

        self.assertIs(selected, recent_old)
        self.assertEqual(list(state.autoplay_candidate_pool), [recent_new])

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
