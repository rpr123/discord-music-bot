import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, patch

import bot


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class SearchRoutingTests(unittest.TestCase):
    def test_song_and_auto_seed_use_the_same_youtube_search(self) -> None:
        expected = "ytsearch1:sunfaded music"

        self.assertEqual(bot.resolve_query("sunfaded"), expected)
        self.assertEqual(bot.resolve_query("sunfaded", None), expected)

    def test_album_and_playlist_use_youtube_playlist_search(self) -> None:
        album_url = bot.resolve_query("NewJeans Get Up", "album")
        playlist_url = bot.resolve_query("lofi beats", "playlist")

        self.assertIn("youtube.com/results?", album_url)
        self.assertIn("NewJeans+Get+Up+full+album", album_url)
        self.assertIn("sp=EgIQAw%253D%253D", album_url)
        self.assertIn("lofi+beats", playlist_url)
        self.assertNotIn("full+album", playlist_url)

    def test_youtube_links_are_accepted_without_rewriting(self) -> None:
        regular = "https://www.youtube.com/watch?v=abcdefghijk"
        music = "https://music.youtube.com/watch?v=abcdefghijk"

        self.assertEqual(bot.resolve_query(regular), regular)
        self.assertEqual(bot.resolve_query(music), music)

    def test_non_youtube_links_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            bot.resolve_query("https://example.com/audio")

    def test_playlist_links_are_detected_as_bulk_requests(self) -> None:
        self.assertTrue(
            bot.is_bulk_youtube_url("https://www.youtube.com/playlist?list=PL123")
        )
        self.assertFalse(
            bot.is_bulk_youtube_url(
                "https://www.youtube.com/watch?v=abcdefghijk&list=PL123"
            )
        )
        self.assertFalse(
            bot.is_bulk_youtube_url("https://www.youtube.com/watch?v=abcdefghijk")
        )

    def test_playlist_result_uses_playlist_id(self) -> None:
        result = {"id": "PL1234567890ABCDEFG"}

        self.assertEqual(
            bot.get_playlist_result_url(result),
            "https://www.youtube.com/playlist?list=PL1234567890ABCDEFG",
        )


class AutoRequestParsingTests(unittest.TestCase):
    def test_auto_without_count_uses_default(self) -> None:
        self.assertEqual(
            bot.parse_auto_request("auto: back number"),
            ("back number", bot.DEFAULT_AUTO_TRACKS),
        )

    def test_count_is_written_between_auto_and_colon(self) -> None:
        self.assertEqual(
            bot.parse_auto_request("auto5: back number"),
            ("back number", 5),
        )
        self.assertEqual(
            bot.parse_auto_request("auto 5: back number"),
            ("back number", 5),
        )
        self.assertEqual(
            bot.parse_auto_request("AUTO12 : lofi chill"),
            ("lofi chill", 12),
        )

    def test_count_is_clamped_to_configured_limit(self) -> None:
        self.assertEqual(
            bot.parse_auto_request("auto999: lofi chill"),
            ("lofi chill", bot.MAX_AUTO_TRACKS),
        )

    def test_query_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "곡명이나 아티스트"):
            bot.parse_auto_request("auto:")
        with self.assertRaisesRegex(ValueError, "곡명이나 아티스트"):
            bot.parse_auto_request("auto5:")
        with self.assertRaisesRegex(ValueError, "곡명이나 아티스트"):
            bot.parse_auto_request("auto 5:")

    def test_old_count_syntax_explains_the_new_format(self) -> None:
        with self.assertRaisesRegex(ValueError, "auto 5: 곡명"):
            bot.parse_auto_request("auto:5 back number")

    def test_unrelated_query_is_not_an_auto_request(self) -> None:
        self.assertIsNone(bot.parse_auto_request("automatic playlist"))


class TrackIdentityTests(unittest.TestCase):
    def make_identity_track(
        self,
        title: str,
        video_id: str,
        *,
        artist: str | None = None,
        song_name: str | None = None,
        uploader: str | None = None,
    ) -> bot.Track:
        url = f"https://www.youtube.com/watch?v={video_id}"
        return bot.Track(
            title=title,
            webpage_url=url,
            requester="tester",
            source_url=url,
            artist=artist,
            song_name=song_name,
            uploader=uploader,
        )

    def test_mv_and_audio_metadata_share_the_same_song_key(self) -> None:
        mv = self.make_identity_track(
            "back number - Blue Amber (Official Music Video)",
            "aaaaaaaaaaa",
            artist="back number",
            song_name="Blue Amber",
        )
        audio = self.make_identity_track(
            "Blue Amber (Official Audio)",
            "bbbbbbbbbbb",
            artist="back number",
            song_name="Blue Amber",
        )

        self.assertNotEqual(mv.webpage_url, audio.webpage_url)
        self.assertEqual(bot.normalize_track_key(mv), bot.normalize_track_key(audio))

    def test_mv_and_audio_titles_match_without_music_metadata(self) -> None:
        mv = self.make_identity_track(
            "Artist - Same Song (Official MV)",
            "ccccccccccc",
        )
        audio = self.make_identity_track(
            "Artist - Same Song [Official Audio]",
            "ddddddddddd",
        )

        self.assertEqual(bot.normalize_track_key(mv), bot.normalize_track_key(audio))

    def test_topic_audio_matches_a_promotional_mv_title(self) -> None:
        mv = self.make_identity_track(
            "back number - ブルーアンバー 【ドラマ主題歌】",
            "nnnnnnnnnnn",
        )
        topic_audio = self.make_identity_track(
            "ブルーアンバー",
            "ooooooooooo",
            uploader="back number - Topic",
        )

        self.assertEqual(
            bot.normalize_track_key(mv),
            bot.normalize_track_key(topic_audio),
        )

    def test_track_creation_preserves_music_identity_metadata(self) -> None:
        track = bot.make_track_from_info(
            {
                "id": "ppppppppppp",
                "title": "Blue Amber",
                "webpage_url": "https://www.youtube.com/watch?v=ppppppppppp",
                "artist": "back number",
                "track": "Blue Amber",
                "uploader": "back number - Topic",
            },
            "tester",
            "fallback",
        )

        self.assertEqual(track.artist, "back number")
        self.assertEqual(track.song_name, "Blue Amber")
        self.assertEqual(track.uploader, "back number - Topic")

    def test_live_remix_and_cover_remain_distinct_versions(self) -> None:
        studio = self.make_identity_track(
            "Artist - Same Song (Official Audio)",
            "eeeeeeeeeee",
        )
        live = self.make_identity_track(
            "Artist - Same Song (Official Live Video)",
            "fffffffffff",
        )
        remix = self.make_identity_track(
            "Artist - Same Song (Remix)",
            "ggggggggggg",
        )
        cover = self.make_identity_track(
            "Artist - Same Song (Cover)",
            "hhhhhhhhhhh",
        )

        keys = {
            bot.normalize_track_key(studio),
            bot.normalize_track_key(live),
            bot.normalize_track_key(remix),
            bot.normalize_track_key(cover),
        }
        self.assertEqual(len(keys), 4)

    def test_same_title_by_different_artists_remains_distinct(self) -> None:
        first = self.make_identity_track(
            "Same Song (Official Audio)",
            "iiiiiiiiiii",
            artist="First Artist",
            song_name="Same Song",
        )
        second = self.make_identity_track(
            "Same Song (Official Audio)",
            "jjjjjjjjjjj",
            artist="Second Artist",
            song_name="Same Song",
        )

        self.assertNotEqual(
            bot.normalize_track_key(first),
            bot.normalize_track_key(second),
        )

    def test_autoplay_skips_an_audio_duplicate_of_the_current_mv(self) -> None:
        current_mv = self.make_identity_track(
            "Artist - Same Song (Official MV)",
            "kkkkkkkkkkk",
        )
        duplicate_audio = self.make_identity_track(
            "Artist - Same Song (Official Audio)",
            "lllllllllll",
        )
        fresh = self.make_identity_track(
            "Artist - Next Song (Official Audio)",
            "mmmmmmmmmmm",
        )
        state = bot.GuildMusicState(current=current_mv)

        self.assertIs(
            bot.select_autoplay_candidate(state, [duplicate_audio, fresh]),
            fresh,
        )


class CommandSurfaceTests(unittest.TestCase):
    def test_search_commands_are_message_only(self) -> None:
        command_names = {command.name for command in bot.bot.tree.get_commands()}

        self.assertTrue(
            {"play", "playalbum", "playplaylist", "playauto"}.isdisjoint(command_names)
        )
        self.assertEqual(
            command_names,
            {
                "setupmusic",
                "join",
                "pause",
                "resume",
                "skip",
                "stop",
                "queue",
                "remove",
                "nowplaying",
                "leave",
            },
        )


class MusicChannelConfigTests(unittest.TestCase):
    def test_legacy_channel_config_is_migrated_with_control_message_id(self) -> None:
        original_channels = dict(bot.configured_music_channels)
        original_messages = dict(bot.configured_control_messages)
        original_autoplay = dict(bot.configured_autoplay_enabled)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "music_channels.json"
                config_path.write_text('{"123": 456}\n', encoding="utf-8")

                with (
                    patch.object(bot, "MUSIC_CHANNELS_FILE", config_path),
                    patch.object(bot, "MUSIC_CHANNEL_ID", None),
                ):
                    bot.load_music_channel_config()
                    self.assertEqual(bot.get_music_channel_id(123), 456)
                    self.assertIsNone(bot.get_control_message_id(123))
                    self.assertFalse(bot.get_autoplay_enabled(123))

                    bot.set_control_message_id(123, 789)
                    saved = json.loads(config_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        saved["123"],
                        {"channel_id": 456, "control_message_id": 789},
                    )

                    bot.set_autoplay_enabled(123, True)
                    saved = json.loads(config_path.read_text(encoding="utf-8"))
                    self.assertTrue(saved["123"]["autoplay_enabled"])

                    bot.configured_music_channels.clear()
                    bot.configured_control_messages.clear()
                    bot.configured_autoplay_enabled.clear()
                    bot.load_music_channel_config()
                    self.assertEqual(bot.get_music_channel_id(123), 456)
                    self.assertEqual(bot.get_control_message_id(123), 789)
                    self.assertTrue(bot.get_autoplay_enabled(123))
        finally:
            bot.configured_music_channels.clear()
            bot.configured_music_channels.update(original_channels)
            bot.configured_control_messages.clear()
            bot.configured_control_messages.update(original_messages)
            bot.configured_autoplay_enabled.clear()
            bot.configured_autoplay_enabled.update(original_autoplay)


class MusicControlPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_autoplay_refill(state)
        bot.music_states.clear()

    async def test_idle_panel_becomes_playing_without_creating_another_message(self) -> None:
        class Guild:
            id = 321

        class Channel:
            id = 654
            guild = Guild()

            def __init__(self) -> None:
                self.send = AsyncMock()

        class Message:
            id = 987

            def __init__(self, channel: Channel) -> None:
                self.channel = channel
                self.edit = AsyncMock()

        channel = Channel()
        message = Message(channel)
        channel.send.return_value = message
        state = bot.GuildMusicState()
        bot.music_states[321] = state

        with (
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "get_control_message_id", return_value=None),
            patch.object(bot, "set_control_message_id") as save_message_id,
        ):
            await bot.update_control_panel(321, state, channel=channel)

            self.assertIs(state.control_message, message)
            channel.send.assert_awaited_once()
            save_message_id.assert_called_once_with(321, message.id)
            idle_view = channel.send.await_args.kwargs["view"]
            autoplay_button = next(
                item
                for item in idle_view.children
                if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
            )
            self.assertFalse(autoplay_button.disabled)
            self.assertTrue(
                all(
                    item.disabled
                    for item in idle_view.children
                    if item.custom_id != bot.AUTOPLAY_BUTTON_CUSTOM_ID
                )
            )

            state.current = make_track("playing")
            state.autoplay_enabled = True
            await bot.update_control_panel(321, state, channel=channel)

        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        playing_view = message.edit.await_args.kwargs["view"]
        self.assertTrue(all(not item.disabled for item in playing_view.children))
        autoplay_button = next(
            item
            for item in playing_view.children
            if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
        )
        self.assertEqual(autoplay_button.label, "자동재생: 켜짐")
        self.assertEqual(autoplay_button.style, bot.discord.ButtonStyle.success)

    async def test_saved_panel_message_is_fetched_instead_of_duplicated(self) -> None:
        class Guild:
            id = 111

        class Channel:
            id = 222
            guild = Guild()

            def __init__(self) -> None:
                self.fetch_message = AsyncMock()
                self.send = AsyncMock()

        class Message:
            id = 333

            def __init__(self, channel: Channel) -> None:
                self.channel = channel
                self.edit = AsyncMock()

        channel = Channel()
        message = Message(channel)
        channel.fetch_message.return_value = message
        state = bot.GuildMusicState()

        with (
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "get_control_message_id", return_value=message.id),
        ):
            result = await bot.update_control_panel(111, state, channel=channel)

        self.assertIs(result, message)
        channel.fetch_message.assert_awaited_once_with(message.id)
        channel.send.assert_not_awaited()
        message.edit.assert_awaited_once()

    async def test_autoplay_button_toggles_state_and_schedules_refill(self) -> None:
        guild_id = 444
        state = bot.get_state(guild_id)
        state.current = make_track("seed")
        view = bot.MusicControlView(guild_id)
        button = next(
            item
            for item in view.children
            if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
        )
        interaction = object()

        with (
            patch.object(bot, "set_autoplay_enabled") as save_setting,
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(view, "edit_panel", new=AsyncMock()) as edit_panel,
        ):
            await button.callback(interaction)

        self.assertTrue(state.autoplay_enabled)
        save_setting.assert_called_once_with(guild_id, True)
        schedule_refill.assert_called_once_with(guild_id)
        edit_panel.assert_awaited_once_with(interaction)

        with (
            patch.object(bot, "set_autoplay_enabled") as save_setting,
            patch.object(bot, "cancel_autoplay_refill") as cancel_refill,
            patch.object(view, "edit_panel", new=AsyncMock()) as edit_panel,
        ):
            await button.callback(interaction)

        self.assertFalse(state.autoplay_enabled)
        save_setting.assert_called_once_with(guild_id, False)
        cancel_refill.assert_called_once_with(state)
        edit_panel.assert_awaited_once_with(interaction)


class AutoplayTests(unittest.IsolatedAsyncioTestCase):
    class Voice:
        def __init__(self) -> None:
            self.playing = True

        def is_connected(self) -> bool:
            return True

        def is_playing(self) -> bool:
            return self.playing

        def is_paused(self) -> bool:
            return False

    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_autoplay_refill(state)
            if state.advance_task and not state.advance_task.done():
                state.advance_task.cancel()
        await asyncio.sleep(0)
        bot.music_states.clear()

    async def test_refill_adds_exactly_one_new_candidate(self) -> None:
        guild_id = 555
        seed = make_track("seed")
        queued = make_track("queued")
        recent = make_track("recent")
        fresh = make_track("fresh")
        state = bot.get_state(guild_id)
        state.voice = self.Voice()
        state.current = seed
        state.queue.append(queued)
        state.autoplay_enabled = True
        state.recent_track_keys.append(bot.normalize_track_key(recent))

        with (
            patch.object(
                bot,
                "extract_auto_tracks",
                new=AsyncMock(return_value=[queued, seed, recent, fresh]),
            ) as extract,
            patch.object(bot, "update_control_panel", new=AsyncMock()) as update_panel,
        ):
            await bot.refill_autoplay_queue(
                guild_id,
                state.playback_generation,
                seed,
            )

        self.assertEqual(list(state.queue), [queued, fresh])
        extract.assert_awaited_once()
        self.assertEqual(extract.await_args.args[0], queued.webpage_url)
        update_panel.assert_awaited_once_with(guild_id, state)

    async def test_refill_restarts_playback_if_track_ends_during_search(self) -> None:
        guild_id = 556
        seed = make_track("seed")
        fresh = make_track("fresh")
        state = bot.get_state(guild_id)
        voice = self.Voice()
        voice.playing = False
        state.voice = voice
        state.current = seed
        state.autoplay_enabled = True

        async def finish_current_during_search(*args: object) -> list[bot.Track]:
            state.current = None
            return [seed, fresh]

        with (
            patch.object(bot, "extract_auto_tracks", side_effect=finish_current_during_search),
            patch.object(bot, "schedule_play_next") as schedule_next,
        ):
            await bot.refill_autoplay_queue(
                guild_id,
                state.playback_generation,
                seed,
            )

        self.assertEqual(list(state.queue), [fresh])
        schedule_next.assert_called_once_with(guild_id)

    async def test_refill_retries_after_a_search_failure(self) -> None:
        guild_id = 558
        seed = make_track("seed")
        fresh = make_track("fresh")
        state = bot.get_state(guild_id)
        state.voice = self.Voice()
        state.current = seed
        state.autoplay_enabled = True

        with (
            patch.object(
                bot,
                "extract_auto_tracks",
                new=AsyncMock(side_effect=[RuntimeError("temporary"), [seed, fresh]]),
            ) as extract,
            patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep,
            patch.object(bot, "update_control_panel", new=AsyncMock()),
        ):
            await bot.refill_autoplay_queue(
                guild_id,
                state.playback_generation,
                seed,
            )

        self.assertEqual(list(state.queue), [fresh])
        self.assertEqual(extract.await_count, 2)
        sleep.assert_awaited_once_with(bot.AUTOPLAY_RETRY_DELAYS_SECONDS[0])

    def test_autoplay_retry_delay_increases_and_caps(self) -> None:
        self.assertEqual(
            [bot.get_autoplay_retry_delay(index) for index in range(7)],
            [60, 120, 300, 900, 1800, 1800, 1800],
        )

    async def test_only_one_refill_task_runs_and_threshold_is_one_track(self) -> None:
        guild_id = 557
        state = bot.get_state(guild_id)
        state.voice = self.Voice()
        state.current = make_track("seed")
        state.autoplay_enabled = True
        state.queue.extend([make_track("one"), make_track("two")])

        task, created = bot.schedule_autoplay_refill(guild_id)
        self.assertIsNone(task)
        self.assertFalse(created)

        state.queue.pop()
        gate = asyncio.Event()

        async def wait_for_gate(*args: object) -> None:
            await gate.wait()

        with patch.object(bot, "refill_autoplay_queue", side_effect=wait_for_gate):
            first_task, first_created = bot.schedule_autoplay_refill(guild_id)
            second_task, second_created = bot.schedule_autoplay_refill(guild_id)
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertIs(first_task, second_task)
            gate.set()
            await first_task

    async def test_stop_cancels_refill_without_disabling_autoplay(self) -> None:
        state = bot.GuildMusicState(autoplay_enabled=True)
        gate = asyncio.Event()
        state.autoplay_task = asyncio.create_task(gate.wait())

        bot.stop_playback(state)
        await asyncio.sleep(0)

        self.assertTrue(state.autoplay_enabled)
        self.assertIsNone(state.autoplay_task)


class YtdlProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.ytdl_cache.clear()
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None

    async def asyncTearDown(self) -> None:
        bot.ytdl_cache.clear()
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None

    async def test_repeated_query_uses_cache_without_a_second_worker(self) -> None:
        payload = {"id": "cachetest01", "title": "cached result"}
        to_thread = AsyncMock(return_value=payload)

        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YTDL_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(bot, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
            )
            first["title"] = "caller mutation"
            second = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
            )

        to_thread.assert_awaited_once()
        self.assertEqual(second["title"], "cached result")

    async def test_rate_limiter_waits_before_the_next_worker(self) -> None:
        bot.ytdl_last_request_started_at = bot.time.monotonic()
        with (
            patch.object(bot, "YTDL_MIN_INTERVAL_SECONDS", 6.0),
            patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep,
        ):
            await bot.wait_for_ytdl_interval()

        sleep.assert_awaited_once()
        self.assertGreater(sleep.await_args.args[0], 5.0)
        self.assertLessEqual(sleep.await_args.args[0], 6.0)

    async def test_429_opens_circuit_and_blocks_new_worker(self) -> None:
        with patch.object(bot, "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800):
            opened = bot.trip_youtube_circuit(
                RuntimeError("HTTP Error 429: Too Many Requests")
            )

        self.assertTrue(opened)
        self.assertGreater(bot.get_youtube_circuit_retry_after(), 1700)

        to_thread = AsyncMock(return_value={"id": "should-not-run"})
        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            self.assertRaises(bot.YouTubeCircuitOpenError),
        ):
            await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:circuit-open-test",
                "circuit test",
                use_cache=False,
            )

        to_thread.assert_not_awaited()

    def test_only_rate_limit_errors_trip_the_circuit(self) -> None:
        self.assertTrue(
            bot.is_youtube_block_error(RuntimeError("Sign in to confirm you're not a bot"))
        )
        self.assertFalse(bot.is_youtube_block_error(RuntimeError("Video unavailable")))


class LocalMusicTestModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_audio_mode_never_calls_ytdl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "test-tone.ogg"
            audio_path.write_bytes(b"test audio fixture")

            with (
                patch.object(bot, "MUSIC_TEST_AUDIO_FILE", str(audio_path)),
                patch.object(bot, "MUSIC_TEST_BULK_TRACKS", 2),
                patch.object(bot, "extract_ytdl_info", new=AsyncMock()) as extract,
            ):
                single = await bot.extract_track("test song", "tester")
                bulk = await bot.extract_tracks("test album", "tester", "album")
                auto = await bot.extract_auto_tracks("test auto", "tester", 3)

        extract.assert_not_awaited()
        self.assertTrue(single.is_local)
        self.assertEqual(single.stream_url, str(audio_path))
        self.assertEqual(len(bulk), 2)
        self.assertEqual(len(auto), 3)
        self.assertEqual(len({bot.normalize_track_key(track) for track in auto}), 3)


class QueueTests(unittest.TestCase):
    def test_remove_by_id_uses_stable_track_identity(self) -> None:
        first = make_track("first")
        second = make_track("second")
        third = make_track("third")
        state = bot.GuildMusicState(queue=deque([third, first, second]))

        removed = bot.remove_queued_track_by_id(state, second.track_id)

        self.assertIs(removed, second)
        self.assertEqual(list(state.queue), [third, first])


class PlaybackSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_autoplay_refill(state)
            if state.advance_task and not state.advance_task.done():
                state.advance_task.cancel()
        await asyncio.sleep(0)
        bot.music_states.clear()

    async def test_only_one_advance_task_is_scheduled_per_guild(self) -> None:
        gate = asyncio.Event()

        async def fake_play_next(guild_id: int, announce: bool = True) -> None:
            await gate.wait()

        with patch.object(bot, "play_next", side_effect=fake_play_next):
            first_task, first_created = bot.schedule_play_next(123)
            second_task, second_created = bot.schedule_play_next(123)

            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertIs(first_task, second_task)

            gate.set()
            await first_task

    async def test_concurrent_start_requests_only_pop_one_track(self) -> None:
        class FakeVoice:
            def __init__(self) -> None:
                self.play_calls = 0
                self.playing = False

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.play_calls += 1
                self.playing = True

        guild_id = 456
        first = make_track("first")
        second = make_track("second")
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.autoplay_enabled = True
        state.queue.extend([first, second])

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "resolve_track_stream", new=AsyncMock()),
            patch.object(bot.discord, "FFmpegPCMAudio", return_value=object()),
            patch.object(bot.discord, "PCMVolumeTransformer", return_value=object()),
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
        ):
            first_task, first_created = bot.schedule_play_next(guild_id, announce=False)
            second_task, second_created = bot.schedule_play_next(guild_id, announce=False)
            await asyncio.gather(first_task, second_task)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(voice.play_calls, 1)
        self.assertIs(state.current, first)
        self.assertEqual(list(state.queue), [second])
        self.assertIn(bot.normalize_track_key(first), state.recent_track_keys)
        schedule_refill.assert_called_once_with(guild_id)

    async def test_fresh_stream_url_is_reused(self) -> None:
        track = make_track("fresh")
        track.stream_url = "https://example.test/audio"
        track.stream_resolved_at = bot.time.monotonic()

        with patch.object(bot, "extract_ytdl_info", new=AsyncMock()) as extract:
            await bot.resolve_track_stream(track)

        extract.assert_not_awaited()

    async def test_stale_stream_url_is_refreshed(self) -> None:
        track = make_track("stale")
        track.stream_url = "https://example.test/old-audio"
        track.stream_resolved_at = bot.time.monotonic() - bot.STREAM_URL_MAX_AGE_SECONDS
        resolved = {
            "title": "refreshed",
            "webpage_url": track.webpage_url,
            "url": "https://example.test/new-audio",
            "formats": [{}],
        }

        with patch.object(
            bot,
            "extract_ytdl_info",
            new=AsyncMock(return_value=resolved),
        ) as extract:
            await bot.resolve_track_stream(track)

        extract.assert_awaited_once()
        self.assertEqual(track.stream_url, "https://example.test/new-audio")
        self.assertEqual(track.title, "refreshed")

    async def test_extraction_slot_wait_also_times_out(self) -> None:
        with (
            patch.object(bot, "ytdl_semaphore", asyncio.Semaphore(0)),
            patch.object(bot, "YTDL_EXTRACT_TIMEOUT_SECONDS", 0.01),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await bot.extract_ytdl_info({}, "test", "blocked extraction")

    async def test_empty_channel_stops_and_disconnects(self) -> None:
        class Member:
            bot = True

        class Channel:
            id = 999
            members = [Member()]

        class Voice:
            channel = Channel()

            def __init__(self) -> None:
                self.stopped = False
                self.disconnected = False

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return True

            def is_paused(self) -> bool:
                return False

            def stop(self) -> None:
                self.stopped = True

            async def disconnect(self) -> None:
                self.disconnected = True

        guild_id = 789
        voice = Voice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.current = make_track("current")
        state.queue.append(make_track("queued"))

        with (
            patch.object(bot.asyncio, "sleep", new=AsyncMock()),
            patch.object(bot, "show_idle_panel", new=AsyncMock()) as show_idle_panel,
        ):
            await bot.disconnect_from_empty_channel(guild_id, voice.channel.id)

        self.assertTrue(voice.stopped)
        self.assertTrue(voice.disconnected)
        self.assertIsNone(state.voice)
        self.assertIsNone(state.current)
        self.assertEqual(list(state.queue), [])
        show_idle_panel.assert_awaited_once_with(guild_id, state)


if __name__ == "__main__":
    unittest.main()
