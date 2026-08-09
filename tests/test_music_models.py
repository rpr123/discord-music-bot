import ast
import unittest
from collections import deque
from dataclasses import fields
from pathlib import Path

import bot
import music_models


PUBLIC_IDENTITY_NAMES = (
    "Track",
    "GuildMusicState",
    "remove_queued_track",
    "remove_queued_track_by_id",
    "remove_queued_track_range_by_ids",
    "MAX_PLAYBACK_ATTEMPTS",
    "invalidate_track_stream",
    "requeue_track_after_playback_error",
    "reset_track_playback_attempts",
    "reset_track_playback_state",
)


class MusicModelTests(unittest.TestCase):
    def test_bot_reexports_music_model_names(self) -> None:
        for name in PUBLIC_IDENTITY_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_models, name),
                )
        self.assertEqual(
            bot.AUTOPLAY_HISTORY_SIZE,
            music_models.AUTOPLAY_HISTORY_SIZE,
        )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_models.__file__).read_text(encoding="utf-8")
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
                "asyncio",
                "collections",
                "dataclasses",
                "discord",
                "typing",
                "uuid",
            },
        )

    def test_track_ids_are_unique(self) -> None:
        first = self.make_track("first")
        second = self.make_track("second")

        self.assertNotEqual(first.track_id, second.track_id)

    def test_autoplay_history_deques_have_expected_maxlen(self) -> None:
        state = music_models.GuildMusicState()

        self.assertEqual(
            state.recent_track_keys.maxlen,
            music_models.AUTOPLAY_HISTORY_SIZE,
        )
        self.assertEqual(
            state.recent_video_ids.maxlen,
            music_models.AUTOPLAY_HISTORY_SIZE,
        )

    def test_music_state_mutable_defaults_are_not_shared(self) -> None:
        first = music_models.GuildMusicState()
        second = music_models.GuildMusicState()
        track = self.make_track("queued")

        first.queue.append(track)
        first.recent_track_keys.append("track")
        first.recent_video_ids.append("video")
        first.private_lyrics_messages[track.track_id] = []
        first.queue_cleanup_tasks[1] = object()
        track.manual_subtitles["ko"] = []

        self.assertFalse(second.queue)
        self.assertFalse(second.recent_track_keys)
        self.assertFalse(second.recent_video_ids)
        self.assertFalse(second.private_lyrics_messages)
        self.assertFalse(second.queue_cleanup_tasks)
        self.assertFalse(self.make_track("other").manual_subtitles)

    def test_music_state_locks_and_task_defaults(self) -> None:
        first = music_models.GuildMusicState()
        second = music_models.GuildMusicState()

        self.assertIsNot(first.lock, second.lock)
        self.assertIsNot(first.voice_connect_lock, second.voice_connect_lock)
        self.assertIsNot(first.control_panel_lock, second.control_panel_lock)
        for name in (
            "advance_task",
            "pending_advance_task",
            "noncritical_task",
            "autoplay_task",
            "lyrics_task",
            "empty_channel_task",
            "lyrics_message",
            "lyrics_view",
        ):
            self.assertIsNone(getattr(first, name))

    def test_music_model_field_contract(self) -> None:
        self.assertEqual(
            tuple(field.name for field in fields(music_models.Track)),
            (
                "title",
                "webpage_url",
                "requester",
                "source_url",
                "requester_id",
                "duration",
                "stream_url",
                "thumbnail_url",
                "artist",
                "song_name",
                "uploader",
                "audio_codec",
                "stream_resolved_at",
                "playback_attempts",
                "force_transcode",
                "lyrics",
                "lyrics_loaded",
                "lyrics_source",
                "korean_lyrics",
                "korean_lyrics_loaded",
                "korean_lyrics_source",
                "korean_lyrics_url",
                "namuwiki_lyrics_checked",
                "lyrics_reading",
                "lyrics_reading_loaded",
                "lyrics_reading_source",
                "lyrics_reading_url",
                "korean_lyrics_lock",
                "lyrics_reading_lock",
                "manual_subtitles",
                "subtitle_language",
                "track_id",
            ),
        )
        self.assertEqual(
            tuple(field.name for field in fields(music_models.GuildMusicState)),
            (
                "queue",
                "current",
                "voice",
                "announcement_channel",
                "control_message",
                "control_view",
                "repeat_one",
                "autoplay_enabled",
                "recent_track_keys",
                "recent_video_ids",
                "skip_requested",
                "stop_requested",
                "lock",
                "voice_connect_lock",
                "control_panel_lock",
                "advance_task",
                "pending_advance_task",
                "pending_advance_generation",
                "pending_advance_announce",
                "noncritical_task",
                "autoplay_task",
                "lyrics_task",
                "lyrics_message",
                "lyrics_view",
                "private_lyrics_messages",
                "queue_cleanup_tasks",
                "empty_channel_task",
                "playback_generation",
            ),
        )

    def test_invalid_index_keeps_the_existing_queue(self) -> None:
        tracks = [self.make_track("first"), self.make_track("second")]
        queue = deque(tracks)
        state = bot.GuildMusicState(queue=queue)

        self.assertIsNone(music_models.remove_queued_track(state, -1))
        self.assertIsNone(music_models.remove_queued_track(state, len(tracks)))
        self.assertIs(state.queue, queue)
        self.assertEqual(list(state.queue), tracks)

    def test_copy_error_requeues_track_with_fresh_transcode_state(self) -> None:
        track = self.make_track("retry")
        track.playback_attempts = 1
        track.stream_url = "https://example.test/audio.opus"
        track.stream_resolved_at = 123.0
        state = music_models.GuildMusicState(current=track)

        retrying = music_models.requeue_track_after_playback_error(
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
        track = self.make_track("failed")
        track.playback_attempts = music_models.MAX_PLAYBACK_ATTEMPTS
        track.force_transcode = True
        state = music_models.GuildMusicState(current=track)

        retrying = music_models.requeue_track_after_playback_error(
            state,
            track,
            used_opus_copy=False,
        )

        self.assertFalse(retrying)
        self.assertEqual(list(state.queue), [])
        self.assertIsNone(state.current)
        self.assertEqual(track.playback_attempts, 0)
        self.assertFalse(track.force_transcode)

    @staticmethod
    def make_track(title: str) -> music_models.Track:
        return music_models.Track(
            title=title,
            webpage_url=f"https://example.test/{title}",
            requester="tester",
            source_url=f"https://example.test/{title}",
        )
