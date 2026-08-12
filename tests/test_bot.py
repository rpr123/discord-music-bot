import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from discord.ui.view import ViewStore

import bot
import music_discord_display
import music_namuwiki
import music_ytdl
from devtools.local_music_bot import LocalMusicMode


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class SearchExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_search_uses_flat_candidates_and_selector(self) -> None:
        entries = [
            {"id": "first-track", "title": "Game Version", "duration": 120},
            {"id": "second-track", "title": "Full Version", "duration": 240},
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(
                bot,
                "search_youtube_music",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(bot, "extract_ytdl_info", extract),
            patch.object(
                bot,
                "select_youtube_search_result",
                return_value=entries[1],
            ) as select,
        ):
            result = await bot.extract_first_info(
                "sample song",
                f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:sample song",
            )

        self.assertIs(result, entries[1])
        extract.assert_awaited_once_with(
            bot.YTDL_SEARCH_OPTIONS,
            f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:sample song",
            "YouTube search",
            job_kind=bot.YtdlJobKind.USER_REQUEST,
        )
        select.assert_called_once_with("sample song", entries)

    async def test_catalog_song_is_resolved_directly(self) -> None:
        music_results = [
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "artists": [{"name": "CoMETIK"}],
                "duration_seconds": 235,
            }
        ]
        resolved = {
            "id": "CuRIuFRD1zI",
            "title": "泥濘鳴鳴",
            "webpage_url": "https://www.youtube.com/watch?v=CuRIuFRD1zI",
            "artist": "CoMETIK",
        }
        extract = AsyncMock(return_value=resolved)

        with (
            patch.object(
                bot,
                "search_youtube_music",
                new=AsyncMock(return_value=music_results),
            ),
            patch.object(bot, "extract_ytdl_info", extract),
        ):
            result = await bot.extract_first_info(
                "でいねいめいめい",
                f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:"
                "でいねいめいめい",
            )

        self.assertIs(result, resolved)
        extract.assert_awaited_once_with(
            bot.YTDL_OPTIONS,
            "https://www.youtube.com/watch?v=CuRIuFRD1zI",
            "YouTube Music catalog song resolve",
            job_kind=bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_top_album_artist_enriches_youtube_fallback(self) -> None:
        music_results = [
            {
                "category": "Top result",
                "resultType": "album",
                "title": "THE IDOLM@STER SHINY COLORS ECHOES 08",
                "artists": [{"name": "CoMETIK"}],
            }
        ]
        entries = [
            {
                "id": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "duration": 235,
                "channel": "コメティック",
            },
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV",
                "duration": 148,
                "channel": "アイドルマスターチャンネル",
            },
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(
                bot,
                "search_youtube_music",
                new=AsyncMock(return_value=music_results),
            ),
            patch.object(bot, "extract_ytdl_info", extract),
        ):
            result = await bot.extract_first_info(
                "でいねいめいめい",
                f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:"
                "でいねいめいめい",
            )

        self.assertEqual(result["id"], "CuRIuFRD1zI")
        extract.assert_awaited_once_with(
            bot.YTDL_SEARCH_OPTIONS,
            f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:"
            "でいねいめいめい CoMETIK",
            "YouTube search",
            job_kind=bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_direct_url_keeps_full_extraction_options(self) -> None:
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        info = {"id": "abcdefghijk", "title": "Direct song"}
        extract = AsyncMock(return_value=info)
        music_search = AsyncMock()

        with (
            patch.object(bot, "extract_ytdl_info", extract),
            patch.object(bot, "search_youtube_music", new=music_search),
        ):
            result = await bot.extract_first_info(url, url)

        self.assertIs(result, info)
        music_search.assert_not_awaited()
        extract.assert_awaited_once_with(
            bot.YTDL_OPTIONS,
            url,
            "YouTube search",
            job_kind=bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_text_track_defers_stream_resolution_until_playback(self) -> None:
        info = {
            "id": "abcdefghijk",
            "title": "Selected song",
            "duration": 180,
            "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
        }

        with (
            patch.object(
                bot,
                "extract_first_info",
                new=AsyncMock(return_value=info),
            ),
            patch.object(
                bot,
                "resolve_track_stream",
                new=AsyncMock(),
            ) as resolve_stream,
        ):
            track = await bot.extract_track("selected song", "tester")

        resolve_stream.assert_not_awaited()
        self.assertIsNone(track.stream_url)
        self.assertEqual(
            track.source_url,
            "https://www.youtube.com/watch?v=abcdefghijk",
        )

    async def test_auto_fallback_search_uses_flat_options(self) -> None:
        seed = bot.Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        candidate = {
            "id": "candidate01",
            "title": "Candidate Song",
            "duration": 180,
        }
        extract = AsyncMock(return_value={"entries": [candidate]})

        with patch.object(bot, "extract_ytdl_info", extract):
            tracks = await bot.extract_auto_tracks_from_seed(seed, "tester", 2)

        self.assertEqual([track.title for track in tracks], ["Seed Song", "Candidate Song"])
        extract.assert_awaited_once_with(
            bot.YTDL_SEARCH_OPTIONS,
            "ytsearch6:Seed Song radio mix",
            "auto fallback search",
            job_kind=bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_auto_supplemental_search_uses_flat_options(self) -> None:
        seed = bot.Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        supplemental = {
            "id": "candidate01",
            "title": "Candidate Song",
            "duration": 180,
        }
        extract = AsyncMock(
            side_effect=[
                {"entries": [{"id": "abcdefghijk", "title": "Seed Song"}]},
                {"entries": [supplemental]},
            ]
        )

        with patch.object(bot, "extract_ytdl_info", extract):
            tracks = await bot.extract_auto_tracks_from_seed(seed, "tester", 2)

        self.assertEqual([track.title for track in tracks], ["Seed Song", "Candidate Song"])
        self.assertEqual(extract.await_count, 2)
        self.assertEqual(
            extract.await_args_list[0].args[0]["playlistend"],
            2,
        )
        self.assertEqual(
            extract.await_args_list[0].kwargs["job_kind"],
            bot.YtdlJobKind.USER_REQUEST,
        )
        self.assertEqual(extract.await_args_list[1].args[0], bot.YTDL_SEARCH_OPTIONS)
        self.assertEqual(
            extract.await_args_list[1].args[2],
            "auto supplemental search",
        )
        self.assertEqual(
            extract.await_args_list[1].kwargs["job_kind"],
            bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_user_auto_count_is_not_limited_by_background_refill(self) -> None:
        seed = bot.Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=seedtrack01",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=seedtrack01",
        )
        entries = [
            {
                "id": f"track{index:06d}",
                "title": f"Candidate {index}",
                "duration": 180,
            }
            for index in range(24)
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(bot, "MAX_AUTO_TRACKS", 25),
            patch.object(bot, "MAX_BULK_TRACKS", 10),
            patch.object(bot, "AUTOPLAY_REFILL_CANDIDATES", 5),
            patch.object(bot, "extract_ytdl_info", extract),
        ):
            tracks = await bot.extract_auto_tracks_from_seed(seed, "tester", 25)

        self.assertEqual(len(tracks), 25)
        self.assertEqual(extract.await_args.args[0]["playlistend"], 25)
        self.assertEqual(
            extract.await_args.kwargs["job_kind"],
            bot.YtdlJobKind.USER_REQUEST,
        )

    async def test_background_auto_fallback_uses_refill_candidate_count(self) -> None:
        seed = bot.Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": f"track{index:06d}",
                "title": f"Candidate {index}",
                "duration": 180,
            }
            for index in range(4)
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(bot, "AUTOPLAY_REFILL_CANDIDATES", 5),
            patch.object(bot, "extract_ytdl_info", extract),
        ):
            tracks = await bot.extract_auto_tracks_from_seed(
                seed,
                "tester",
                5,
                job_kind=bot.YtdlJobKind.AUTOPLAY,
            )

        self.assertEqual(len(tracks), 5)
        extract.assert_awaited_once_with(
            bot.YTDL_SEARCH_OPTIONS,
            "ytsearch5:Seed Song radio mix",
            "auto fallback search",
            job_kind=bot.YtdlJobKind.AUTOPLAY,
        )

    async def test_playlist_request_uses_bulk_priority(self) -> None:
        url = "https://www.youtube.com/playlist?list=PL1234567890"
        extract = AsyncMock(
            return_value={
                "entries": [
                    {"id": "abcdefghijk", "title": "Playlist Track"},
                ]
            }
        )

        with patch.object(bot, "extract_ytdl_info", extract):
            tracks = await bot.extract_tracks(url, "tester", "playlist")

        self.assertEqual([track.title for track in tracks], ["Playlist Track"])
        extract.assert_awaited_once_with(
            bot.YTDL_PLAYLIST_OPTIONS,
            url,
            "playlist or album search",
            job_kind=bot.YtdlJobKind.PLAYLIST_ALBUM,
        )


class DiscordHttpResilienceTests(unittest.IsolatedAsyncioTestCase):
    def make_server_error(self) -> bot.discord.DiscordServerError:
        response = MagicMock(status=500, reason="Internal Server Error")
        return bot.discord.DiscordServerError(response, "<html>temporary failure</html>")

    async def asyncTearDown(self) -> None:
        bot.music_states.clear()

    async def test_feedback_500_does_not_undo_queued_track(self) -> None:
        class Requester:
            display_name = "tester"
            id = 123

        channel = MagicMock()
        channel.send = AsyncMock(side_effect=self.make_server_error())
        track = make_track("queued")

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "extract_track", new=AsyncMock(return_value=track)),
            self.assertLogs("music-bot", level="WARNING"),
        ):
            result = await bot.enqueue_tracks(987, channel, Requester(), "queued")

        self.assertTrue(result)
        self.assertEqual(list(bot.get_state(987).queue), [track])

class QueueFeedbackLatencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        bot.music_states.clear()

    async def test_queue_feedback_precedes_stream_preparation(self) -> None:
        class Requester:
            display_name = "tester"
            id = 123

        class Voice:
            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        guild_id = 654
        state = bot.get_state(guild_id)
        state.voice = Voice()
        state.autoplay_enabled = True
        track = make_track("queued")
        track.stream_url = None
        initial_response = MagicMock()
        initial_response.edit = AsyncMock()
        channel = MagicMock()
        playback_gate = asyncio.Event()

        async def delayed_playback(
            requested_guild_id: int,
            announce: bool = True,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertFalse(announce)
            await playback_gate.wait()
            state.queue.clear()
            state.current = track

        with (
            patch.object(
                bot,
                "extract_track",
                new=AsyncMock(return_value=track),
            ),
            patch.object(bot, "play_next", new=delayed_playback),
            patch.object(
                bot,
                "delete_message_later",
                new=AsyncMock(),
            ),
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ),
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
        ):
            enqueue_task = asyncio.create_task(
                bot.enqueue_tracks(
                    guild_id,
                    channel,
                    Requester(),
                    "queued",
                    initial_response=initial_response,
                )
            )
            for _ in range(5):
                await asyncio.sleep(0)
                if initial_response.edit.await_count:
                    break

            initial_response.edit.assert_awaited_once()
            self.assertIsNotNone(
                initial_response.edit.await_args.kwargs["embed"]
            )
            self.assertFalse(enqueue_task.done())
            schedule_refill.assert_not_called()

            playback_gate.set()
            result = await enqueue_task

        self.assertTrue(result)
        schedule_refill.assert_not_called()

    async def test_stop_during_search_does_not_enqueue_or_restart_playback(
        self,
    ) -> None:
        class Requester:
            display_name = "tester"
            id = 123

        class Voice:
            def __init__(self) -> None:
                self.playing = True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def stop(self) -> None:
                self.playing = False

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        guild_id = 655
        state = bot.get_state(guild_id)
        state.voice = Voice()
        state.current = make_track("current")
        late_track = make_track("late")
        initial_response = MagicMock()
        initial_response.edit = AsyncMock()
        channel = MagicMock()
        search_started = asyncio.Event()
        release_search = asyncio.Event()

        async def delayed_extract(*args, **kwargs) -> bot.Track:
            search_started.set()
            await release_search.wait()
            return late_track

        enqueue_task = None
        with (
            patch.object(bot, "extract_track", new=delayed_extract),
            patch.object(
                bot,
                "schedule_play_next",
                return_value=(None, False),
            ) as schedule_play_next,
            patch.object(bot, "schedule_autoplay_refill") as schedule_autoplay_refill,
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ),
        ):
            try:
                enqueue_task = asyncio.create_task(
                    bot.enqueue_tracks(
                        guild_id,
                        channel,
                        Requester(),
                        "late song",
                        initial_response=initial_response,
                    )
                )
                await asyncio.wait_for(search_started.wait(), timeout=1)

                original_generation = state.playback_generation
                bot.stop_playback(state, guild_id)

                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)

                release_search.set()
                result = await asyncio.wait_for(enqueue_task, timeout=1)
            finally:
                release_search.set()
                if enqueue_task is not None and not enqueue_task.done():
                    enqueue_task.cancel()
                if enqueue_task is not None:
                    await asyncio.gather(enqueue_task, return_exceptions=True)
                bot.music_states.pop(guild_id, None)

        self.assertFalse(result)
        self.assertEqual(list(state.queue), [])
        self.assertIsNone(state.current)
        self.assertEqual(
            state.playback_generation,
            original_generation + 1,
        )
        schedule_play_next.assert_not_called()
        schedule_autoplay_refill.assert_not_called()
        initial_response.edit.assert_awaited_once_with(
            content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요.",
            embed=None,
            view=None,
        )

    async def test_stop_during_loading_reply_does_not_start_search(
        self,
    ) -> None:
        guild_id = 656
        loading_started = asyncio.Event()
        release_loading = asyncio.Event()

        class Guild:
            id = guild_id

        guild = Guild()

        class Channel:
            id = 1656
            mention = "#voice"

        channel = Channel()

        class FakeMember:
            def __init__(self) -> None:
                self.bot = False
                self.guild = guild
                self.voice = type("MemberVoice", (), {"channel": channel})()
                self.display_name = "tester"
                self.id = 123

        requester = FakeMember()
        channel.members = [requester]

        class Voice:
            def __init__(self) -> None:
                self.channel = channel
                self.playing = True

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def stop(self) -> None:
                self.playing = False

        state = bot.get_state(guild_id)
        state.voice = Voice()
        state.current = make_track("current")
        guild.voice_client = state.voice
        original_generation = state.playback_generation
        late_track = make_track("late")
        loading_message = MagicMock()
        loading_message.edit = AsyncMock()
        message = MagicMock()
        message.author = requester
        message.guild = guild
        message.channel = channel
        message.content = "late song"

        async def delayed_loading_reply(
            content: str,
            **kwargs: object,
        ) -> object:
            self.assertTrue(content)
            self.assertEqual(kwargs["mention_author"], False)
            self.assertEqual(kwargs["silent"], False)
            loading_started.set()
            await release_loading.wait()
            return loading_message

        message.reply = AsyncMock(side_effect=delayed_loading_reply)
        message.delete = AsyncMock()

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        request_task = None
        with (
            patch.object(bot, "bot_shutdown_started", False),
            patch.object(bot.discord, "Member", FakeMember),
            patch.object(bot, "get_music_channel_id", return_value=channel.id),
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(
                music_discord_display,
                "MUSIC_CHANNEL_DELETE_REQUESTS",
                False,
            ),
            patch.object(
                bot,
                "extract_track",
                new=AsyncMock(return_value=late_track),
            ) as extract_track,
            patch.object(
                bot,
                "schedule_play_next",
                return_value=(None, False),
            ) as schedule_play_next,
            patch.object(bot, "schedule_autoplay_refill") as schedule_autoplay_refill,
            patch.object(bot.bot, "process_commands", new=AsyncMock()) as process_commands,
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ),
        ):
            try:
                request_task = asyncio.create_task(bot.on_message(message))
                await asyncio.wait_for(loading_started.wait(), timeout=1)

                bot.stop_playback(state, guild_id)
                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)

                release_loading.set()
                await asyncio.wait_for(request_task, timeout=1)
            finally:
                release_loading.set()
                if request_task is not None and not request_task.done():
                    request_task.cancel()
                if request_task is not None:
                    await asyncio.gather(request_task, return_exceptions=True)
                bot.cancel_empty_channel_disconnect(state)
                bot.music_states.pop(guild_id, None)

        message.reply.assert_awaited_once()
        extract_track.assert_not_awaited()
        schedule_play_next.assert_not_called()
        schedule_autoplay_refill.assert_not_called()
        self.assertFalse(state.queue)
        self.assertIsNone(state.current)
        loading_message.edit.assert_awaited_once_with(
            content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요.",
            embed=None,
            view=None,
        )
        message.delete.assert_not_awaited()
        process_commands.assert_awaited_once_with(message)


class AutoRequestEnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_auto_count_routes_to_auto_extractor_and_enqueues_all_tracks(
        self,
    ) -> None:
        class Requester:
            display_name = "tester"
            id = 123

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        guild_id = 6541
        self.addCleanup(bot.music_states.pop, guild_id, None)
        channel = MagicMock()
        initial_response = MagicMock()
        initial_response.edit = AsyncMock()
        tracks = [make_track("seed"), make_track("related")]

        with (
            patch.object(bot, "MAX_AUTO_TRACKS", 25),
            patch.object(
                bot,
                "extract_auto_tracks",
                new=AsyncMock(return_value=tracks),
            ) as extract_auto_tracks,
            patch.object(bot, "extract_track", new=AsyncMock()) as extract_track,
            patch.object(bot, "extract_tracks", new=AsyncMock()) as extract_tracks,
            patch.object(bot, "schedule_autoplay_refill"),
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ),
        ):
            result = await bot.enqueue_tracks(
                guild_id,
                channel,
                Requester(),
                "back number",
                initial_response=initial_response,
                auto_count=5,
            )

        self.assertTrue(result)
        extract_auto_tracks.assert_awaited_once_with(
            "back number",
            "tester",
            5,
            123,
        )
        extract_track.assert_not_awaited()
        extract_tracks.assert_not_awaited()
        self.assertEqual(list(bot.get_state(guild_id).queue), tracks)


class LegacyAutoMessageTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_auto_message_gives_slash_guidance_without_voice_or_search(
        self,
    ) -> None:
        guild_id = 6542

        class Guild:
            id = guild_id

        class Channel:
            id = 7654

        class FakeMember:
            bot = False

        message = MagicMock()
        message.author = FakeMember()
        message.guild = Guild()
        message.channel = Channel()
        message.content = "auto5: back number"

        with (
            patch.object(bot, "bot_shutdown_started", False),
            patch.object(bot.discord, "Member", FakeMember),
            patch.object(bot, "get_music_channel_id", return_value=message.channel.id),
            patch.object(
                bot,
                "send_music_request_reply",
                new=AsyncMock(return_value=None),
            ) as send_reply,
            patch.object(
                bot,
                "delete_music_request_message",
                new=AsyncMock(),
            ) as delete_request,
            patch.object(bot, "get_state") as get_state,
            patch.object(
                bot,
                "ensure_voice_for_member",
                new=AsyncMock(),
            ) as ensure_voice,
            patch.object(bot, "enqueue_tracks", new=AsyncMock()) as enqueue,
            patch.object(bot, "extract_track", new=AsyncMock()) as extract_track,
            patch.object(
                bot,
                "extract_auto_tracks",
                new=AsyncMock(),
            ) as extract_auto_tracks,
        ):
            await bot.on_message(message)

        send_reply.assert_awaited_once()
        self.assertIs(send_reply.await_args.args[0], message)
        guidance = send_reply.await_args.args[1]
        self.assertIn("/auto", guidance)
        self.assertIn("n:", guidance)
        self.assertIn("곡명:", guidance)
        delete_request.assert_awaited_once_with(message)
        get_state.assert_not_called()
        ensure_voice.assert_not_awaited()
        enqueue.assert_not_awaited()
        extract_track.assert_not_awaited()
        extract_auto_tracks.assert_not_awaited()


class LyricsFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_track_keeps_manual_but_ignores_automatic_caption_metadata(
        self,
    ) -> None:
        track = bot.make_track_from_info(
            {
                "id": "captions001",
                "title": "Captioned song",
                "webpage_url": "https://www.youtube.com/watch?v=captions001",
                "subtitles": {
                    "ja": [{"ext": "json3", "url": "https://example.com/manual"}]
                },
                "automatic_captions": {
                    "en": [{"ext": "json3", "url": "https://example.com/auto-en"}],
                    "ko": [
                        {
                            "ext": "json3",
                            "url": "https://example.com/auto?lang=ja&tlang=ko",
                        }
                    ],
                },
                "language": "ja",
            },
            "tester",
            "https://www.youtube.com/watch?v=captions001",
        )

        self.assertEqual(set(track.manual_subtitles), {"ja"})
        self.assertFalse(hasattr(track, "korean_automatic_subtitles"))
        self.assertEqual(track.subtitle_language, "ja")

    async def test_lrclib_miss_falls_back_to_youtube_manual_subtitles(self) -> None:
        track = make_track("fallback")
        with (
            patch.object(bot, "lookup_track_lyrics", return_value=None),
            patch.object(
                bot,
                "get_youtube_manual_lyrics",
                new=AsyncMock(return_value="manual captions"),
            ) as youtube_lookup,
        ):
            lyrics = await bot.get_track_lyrics(track)

        self.assertEqual(lyrics, "manual captions")
        self.assertEqual(track.lyrics_source, "YouTube 수동 자막")
        youtube_lookup.assert_awaited_once_with(track)

    async def test_lrclib_hit_does_not_request_youtube_subtitles(self) -> None:
        track = make_track("lrclib")
        with (
            patch.object(bot, "lookup_track_lyrics", return_value="lrclib lyrics"),
            patch.object(
                bot,
                "get_youtube_manual_lyrics",
                new=AsyncMock(),
            ) as youtube_lookup,
        ):
            lyrics = await bot.get_track_lyrics(track)

        self.assertEqual(lyrics, "lrclib lyrics")
        self.assertEqual(track.lyrics_source, "LRCLIB")
        youtube_lookup.assert_not_awaited()


class LyricsVariantTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.schedule_private_lyrics_cleanup(state)
            bot.cancel_queue_message_cleanups(state)
        await asyncio.sleep(0)
        bot.music_states.clear()

    def test_variant_view_only_shows_modes_available_for_the_track(self) -> None:
        japanese_track = make_track("Japanese")
        korean_track = make_track("Korean")

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "sudachi_dictionary", MagicMock()),
        ):
            japanese_view = bot.make_lyrics_variant_view(
                100,
                japanese_track,
                "君の声が聞こえる",
            )
            korean_view = bot.make_lyrics_variant_view(
                100,
                korean_track,
                "너의 목소리가 들려",
            )

        self.assertEqual(
            {item.label for item in japanese_view.children},
            {"나무위키 가사", "히라가나 독음"},
        )
        self.assertIsNone(korean_view)

    def test_korean_lyrics_button_accepts_manual_subtitles_without_api_key(
        self,
    ) -> None:
        track = make_track("Japanese")
        track.manual_subtitles = {
            "ko": [{"ext": "json3", "url": "https://example.com/ko"}],
        }

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", False),
            patch.object(bot, "sudachi_dictionary", None),
        ):
            view = bot.make_lyrics_variant_view(
                100,
                track,
                "君の声が聞こえる",
            )

        self.assertIsNotNone(view)
        self.assertEqual(
            {item.label for item in view.children},
            {"한국어 자막"},
        )

    def test_korean_lyrics_button_is_hidden_without_available_source(
        self,
    ) -> None:
        track = make_track("English")

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", False),
            patch.object(bot, "sudachi_dictionary", None),
        ):
            view = bot.make_lyrics_variant_view(
                100,
                track,
                "I can hear your voice",
            )

        self.assertIsNone(view)

    def test_korean_lyrics_button_is_available_for_namuwiki_lookup(self) -> None:
        track = make_track("Foreign song")

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "sudachi_dictionary", None),
        ):
            view = bot.make_lyrics_variant_view(
                100,
                track,
                "I can hear your voice",
            )

        self.assertIsNotNone(view)
        self.assertEqual(
            {item.label for item in view.children},
            {"나무위키 가사"},
        )

    def test_confirmed_namuwiki_miss_hides_the_korean_lyrics_button(
        self,
    ) -> None:
        track = make_track("Foreign song")
        track.namuwiki_lyrics_checked = True

        with patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True):
            self.assertFalse(bot.can_show_korean_lyrics(track, "foreign lyrics"))

    def test_korean_lyrics_button_is_available_when_original_lyrics_are_missing(
        self,
    ) -> None:
        track = make_track("泥濘鳴鳴")
        track.subtitle_language = "ja"

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "sudachi_dictionary", None),
        ):
            view = bot.make_lyrics_variant_view(100, track, "")

        self.assertIsNotNone(view)
        self.assertEqual(
            {item.label for item in view.children},
            {"나무위키 가사"},
        )

    def test_namuwiki_reading_adds_hiragana_button_without_original_lyrics(
        self,
    ) -> None:
        track = make_track("泥濘鳴鳴")
        track.korean_lyrics = (
            "泥濘 鳴鳴\n"
            "でいねい めいめい\n"
            "진창에서 울리는 노랫소리\n\n"
            "礼を持って\n"
            "れいをもって\n"
            "예를 갖추어 다시 걸어가"
        )
        track.korean_lyrics_loaded = True
        track.korean_lyrics_url = "https://namu.wiki/w/example"

        with patch.object(bot, "sudachi_dictionary", None):
            view = bot.make_lyrics_variant_view(100, track, "")

        self.assertIsNotNone(view)
        self.assertEqual(
            {item.label for item in view.children},
            {"나무위키 가사", "히라가나 독음"},
        )

    async def test_namuwiki_hiragana_reading_is_used_without_sudachi(
        self,
    ) -> None:
        track = make_track("泥濘鳴鳴")
        track.korean_lyrics = (
            "泥濘 鳴鳴\n"
            "デイネイ メイメイ\n"
            "진창에서 울리는 노랫소리\n\n"
            "礼を持って\n"
            "れいをもって\n"
            "예를 갖추어 다시 걸어가"
        )
        track.korean_lyrics_url = "https://namu.wiki/w/example"
        namuwiki_lyrics = track.korean_lyrics

        with patch.object(bot, "sudachi_dictionary", None):
            reading = await bot.get_track_hiragana_reading(track)

        self.assertEqual(
            reading,
            "泥濘(でいねい) 鳴鳴(めいめい)\n礼(れい)を持(も)って",
        )
        self.assertEqual(track.korean_lyrics, namuwiki_lyrics)
        self.assertEqual(track.lyrics_reading_source, "나무위키 · 일본어 독음")
        self.assertEqual(track.lyrics_reading_url, track.korean_lyrics_url)

    def test_missing_korean_lyrics_do_not_offer_korean_variant(self) -> None:
        track = make_track("한국 노래")

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "sudachi_dictionary", None),
        ):
            view = bot.make_lyrics_variant_view(100, track, "")

        self.assertIsNone(view)

    async def test_manual_korean_subtitles_are_used_when_namuwiki_misses(
        self,
    ) -> None:
        track = make_track("foreign")
        track.lyrics = "Original lyrics"
        track.lyrics_loaded = True
        track.manual_subtitles = {
            "ko": [{"ext": "json3", "url": "https://example.com/manual"}],
        }

        with (
            patch.object(
                bot,
                "lookup_namuwiki_lyrics",
                return_value=None,
            ),
            patch.object(
                bot,
                "get_selected_youtube_subtitle",
                new=AsyncMock(return_value="사람이 작성한 한국어 자막"),
            ) as subtitle_lookup,
        ):
            lyrics = await bot.get_track_korean_lyrics(track)

        self.assertEqual(lyrics, "사람이 작성한 한국어 자막")
        self.assertEqual(track.korean_lyrics_source, "YouTube 제공 한국어 자막")
        subtitle_lookup.assert_awaited_once_with(
            track,
            ("ko", "json3", "https://example.com/manual"),
            purpose="manual Korean lyrics",
        )

    async def test_automatic_captions_are_never_used_for_korean_lyrics(
        self,
    ) -> None:
        track = bot.make_track_from_info(
            {
                "id": "machine001",
                "title": "Foreign song",
                "webpage_url": "https://www.youtube.com/watch?v=machine001",
                "automatic_captions": {
                    "ko": [
                        {
                            "ext": "json3",
                            "url": "https://example.com/auto?lang=ja&tlang=ko",
                        }
                    ],
                },
                "language": "ja",
            },
            "tester",
            "https://www.youtube.com/watch?v=machine001",
        )

        with (
            patch.object(bot, "lookup_namuwiki_lyrics", return_value=None),
            patch.object(
                bot,
                "get_selected_youtube_subtitle",
                new=AsyncMock(),
            ) as subtitle_lookup,
        ):
            with self.assertRaises(bot.KoreanLyricsError):
                await bot.get_track_korean_lyrics(track)

        subtitle_lookup.assert_not_awaited()

    async def test_korean_lyrics_button_uses_original_response_and_cache(
        self,
    ) -> None:
        guild_id = 101
        track = make_track("foreign")
        track.lyrics = "Original lyrics"
        track.lyrics_loaded = True
        state = bot.get_state(guild_id)
        state.current = track
        first_message = MagicMock()
        first_message.delete = AsyncMock()
        second_message = MagicMock()
        second_message.delete = AsyncMock()
        first_interaction = MagicMock()
        first_interaction.response.send_message = AsyncMock()
        first_interaction.edit_original_response = AsyncMock(
            return_value=first_message
        )
        second_interaction = MagicMock()
        second_interaction.response.send_message = AsyncMock()
        second_interaction.edit_original_response = AsyncMock(
            return_value=second_message
        )
        view = bot.LyricsVariantView.__new__(bot.LyricsVariantView)
        view.guild_id = guild_id
        view.track = track

        with (
            patch.object(
                bot,
                "lookup_namuwiki_lyrics",
                return_value=None,
            ),
            patch.object(
                bot,
                "get_youtube_korean_lyrics",
                new=AsyncMock(
                    return_value=("사람이 작성한 한국어 자막", "YouTube 제공 한국어 자막")
                ),
            ) as request_lyrics,
        ):
            await view.show_korean_lyrics(first_interaction)
            await view.show_korean_lyrics(second_interaction)

        first_interaction.response.send_message.assert_awaited_once_with(
            "가사 정보를 확인하고 있어요...",
            ephemeral=True,
        )
        second_interaction.response.send_message.assert_awaited_once_with(
            "가사 정보를 확인하고 있어요...",
            ephemeral=True,
        )
        first_interaction.edit_original_response.assert_awaited_once()
        second_interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(
            first_interaction.edit_original_response.await_args.kwargs["attachments"],
            [],
        )
        self.assertEqual(
            second_interaction.edit_original_response.await_args.kwargs["attachments"],
            [],
        )
        request_lyrics.assert_awaited_once_with(track)
        first_message.delete.assert_not_awaited()
        second_message.delete.assert_not_awaited()
        self.assertEqual(
            state.private_lyrics_messages[track.track_id],
            [first_message, second_message],
        )

        bot.schedule_private_lyrics_cleanup(state, track.track_id)
        await asyncio.sleep(0)

        first_message.delete.assert_awaited_once_with()
        second_message.delete.assert_awaited_once_with()
        self.assertNotIn(track.track_id, state.private_lyrics_messages)

    async def test_korean_lyrics_button_acknowledges_before_slow_lookup(self) -> None:
        guild_id = 103
        track = make_track("slow foreign")
        state = bot.get_state(guild_id)
        state.current = track
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        message = MagicMock()
        message.delete = AsyncMock()
        interaction.edit_original_response = AsyncMock(return_value=message)
        lookup_started = asyncio.Event()
        lookup_gate = asyncio.Event()
        view = bot.LyricsVariantView.__new__(bot.LyricsVariantView)
        view.guild_id = guild_id
        view.track = track

        async def slow_lookup(requested_track: bot.Track) -> str:
            self.assertIs(requested_track, track)
            lookup_started.set()
            await lookup_gate.wait()
            requested_track.korean_lyrics_source = "나무위키 · 원문·독음·번역"
            requested_track.korean_lyrics_url = "https://namu.wiki/w/test"
            return "원문\n독음\n번역"

        with patch.object(bot, "get_track_korean_lyrics", new=slow_lookup):
            task = asyncio.create_task(view.show_korean_lyrics(interaction))
            await lookup_started.wait()

            interaction.response.send_message.assert_awaited_once_with(
                "가사 정보를 확인하고 있어요...",
                ephemeral=True,
            )
            interaction.edit_original_response.assert_not_awaited()

            lookup_gate.set()
            await task

        interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(
            state.private_lyrics_messages[track.track_id],
            [message],
        )

    async def test_long_korean_lyrics_are_attached_to_original_response(self) -> None:
        guild_id = 104
        track = make_track("long foreign")
        track.korean_lyrics = "원문\n독음\n번역\n\n" * 500
        track.korean_lyrics_loaded = True
        track.korean_lyrics_source = "나무위키 · 원문·독음·번역"
        track.korean_lyrics_url = "https://namu.wiki/w/test"
        state = bot.get_state(guild_id)
        state.current = track
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        message = MagicMock()
        message.delete = AsyncMock()
        interaction.edit_original_response = AsyncMock(return_value=message)
        view = bot.LyricsVariantView.__new__(bot.LyricsVariantView)
        view.guild_id = guild_id
        view.track = track

        await view.show_korean_lyrics(interaction)

        attachments = interaction.edit_original_response.await_args.kwargs[
            "attachments"
        ]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].filename, "lyrics-korean.txt")
        self.assertLess(
            len(
                interaction.edit_original_response.await_args.kwargs[
                    "embed"
                ].description
            ),
            bot.LYRICS_INLINE_LIMIT,
        )
        attachments[0].close()

    async def test_late_private_lyrics_result_is_deleted_after_track_change(
        self,
    ) -> None:
        guild_id = 102
        finished_track = make_track("finished")
        state = bot.get_state(guild_id)
        state.current = make_track("next")
        message = MagicMock()
        message.delete = AsyncMock()

        await bot.register_private_lyrics_message(
            guild_id,
            finished_track,
            message,
        )

        message.delete.assert_awaited_once_with()
        self.assertFalse(state.private_lyrics_messages)


class NamuWikiLyricsTests(unittest.IsolatedAsyncioTestCase):
    EXPECTED_LYRICS = (
        "泥濘 鳴鳴\n"
        "でいねい めいめい\n"
        "진창에서 울리는 노랫소리\n\n"
        "礼を持って\n"
        "れいをもって\n"
        "예를 갖추어 다시 걸어가"
    )
    DOCUMENT = "泥濘鳴鳴"
    PAGE_URL = (
        "https://namu.wiki/w/"
        "%E6%B3%A5%E6%BF%98%E9%B3%B4%E9%B3%B4"
    )

    async def test_namuwiki_lyrics_are_cached_before_youtube_fallback(
        self,
    ) -> None:
        track = make_track(self.DOCUMENT)
        namuwiki_result = (
            self.EXPECTED_LYRICS,
            "나무위키 · 원문·독음·번역",
            self.PAGE_URL,
        )

        with (
            patch.object(
                bot,
                "lookup_namuwiki_lyrics",
                return_value=namuwiki_result,
            ) as namuwiki_lookup,
            patch.object(
                bot,
                "get_youtube_korean_lyrics",
                new=AsyncMock(),
            ) as youtube_lookup,
        ):
            first = await bot.get_track_korean_lyrics(track)
            second = await bot.get_track_korean_lyrics(track)

        self.assertEqual(first, self.EXPECTED_LYRICS)
        self.assertEqual(second, self.EXPECTED_LYRICS)
        self.assertEqual(track.korean_lyrics_url, self.PAGE_URL)
        namuwiki_lookup.assert_called_once_with(track)
        youtube_lookup.assert_not_awaited()

    async def test_transient_namuwiki_failure_is_not_cached(self) -> None:
        track = make_track(self.DOCUMENT)

        with patch.object(
            bot,
            "lookup_namuwiki_lyrics",
            side_effect=bot.NamuWikiLyricsError("request blocked"),
        ) as namuwiki_lookup:
            first = await bot.get_track_namuwiki_lyrics(track)
            second = await bot.get_track_namuwiki_lyrics(track)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertFalse(track.namuwiki_lyrics_checked)
        self.assertEqual(namuwiki_lookup.call_count, 2)

    async def test_confirmed_namuwiki_miss_is_cached(self) -> None:
        track = make_track(self.DOCUMENT)

        with patch.object(
            bot,
            "lookup_namuwiki_lyrics",
            return_value=None,
        ) as namuwiki_lookup:
            first = await bot.get_track_namuwiki_lyrics(track)
            second = await bot.get_track_namuwiki_lyrics(track)

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertTrue(track.namuwiki_lyrics_checked)
        namuwiki_lookup.assert_called_once_with(track)

    async def test_unexpected_namuwiki_failure_still_uses_youtube(
        self,
    ) -> None:
        track = make_track(self.DOCUMENT)
        track.lyrics = "泥濘 鳴鳴"
        track.lyrics_loaded = True

        with (
            patch.object(
                bot,
                "lookup_namuwiki_lyrics",
                side_effect=ValueError("unexpected response"),
            ),
            patch.object(
                bot,
                "get_youtube_korean_lyrics",
                new=AsyncMock(
                    return_value=("유튜브 번역 가사입니다", "YouTube 제공 한국어 자막")
                ),
            ) as youtube_lookup,
        ):
            lyrics = await bot.get_track_korean_lyrics(track)

        self.assertEqual(lyrics, "유튜브 번역 가사입니다")
        youtube_lookup.assert_awaited_once_with(track)

    def test_korean_lyrics_embed_links_to_the_source_document(self) -> None:
        track = make_track(self.DOCUMENT)

        embed = bot.make_lyrics_variant_embed(
            track,
            "나무위키 가사",
            self.EXPECTED_LYRICS,
            "나무위키 · 원문·독음·번역",
            self.PAGE_URL,
        )

        self.assertEqual(embed.url, self.PAGE_URL)
        self.assertEqual(embed.footer.text, "나무위키 · 원문·독음·번역")


class LyricsMessageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_lyrics_publish(state)
            bot.schedule_private_lyrics_cleanup(state)
            bot.cancel_queue_message_cleanups(state)
        await asyncio.sleep(0)
        bot.music_states.clear()
        bot.configured_music_channels.clear()

    def make_channel_and_message(self) -> tuple[MagicMock, MagicMock]:
        channel = MagicMock()
        channel.id = 700
        channel.send = AsyncMock()
        message = MagicMock()
        message.id = 701
        message.channel = channel
        message.edit = AsyncMock(return_value=message)
        message.delete = AsyncMock()
        channel.send.return_value = message
        return channel, message

    async def test_replacing_lyrics_view_restores_new_button_callbacks(
        self,
    ) -> None:
        guild_id = 609
        message_id = 709
        custom_id = "lyrics:korean:replacement-test"
        state = bot.get_state(guild_id)
        previous_view = bot.discord.ui.View(timeout=None)
        previous_view.add_item(
            bot.discord.ui.Button(label="이전", custom_id=custom_id)
        )
        replacement_view = bot.discord.ui.View(timeout=None)
        replacement_button = bot.discord.ui.Button(
            label="새 가사",
            custom_id=custom_id,
        )
        replacement_view.add_item(replacement_button)
        view_store = ViewStore(bot.bot._connection)
        view_store.add_view(previous_view, message_id)
        view_store.add_view(replacement_view, message_id)
        state.lyrics_view = previous_view

        def register_view(
            view: bot.discord.ui.View,
            *,
            message_id: int,
        ) -> None:
            view_store.add_view(view, message_id)

        with patch.object(
            bot.bot,
            "add_view",
            side_effect=register_view,
        ) as add_view:
            bot.replace_lyrics_view(
                state,
                replacement_view,
                message_id=message_id,
            )

        key = (bot.discord.ComponentType.button.value, custom_id)
        self.assertIs(view_store._views[message_id][key], replacement_button)
        add_view.assert_called_once_with(
            replacement_view,
            message_id=message_id,
        )

        bot.replace_lyrics_view(state, None)

    async def test_new_track_edits_the_existing_lyrics_message(self) -> None:
        guild_id = 600
        channel, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.announcement_channel = channel
        first = make_track("first")
        second = make_track("second")
        state.current = first

        await bot.upsert_lyrics_message(guild_id, state, first, "first lyrics")
        state.current = second
        await bot.upsert_lyrics_message(guild_id, state, second, "second lyrics")

        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        edited_embed = message.edit.await_args.kwargs["embed"]
        self.assertIn("second", edited_embed.title)
        self.assertEqual(edited_embed.description, "second lyrics")
        self.assertIs(state.lyrics_message, message)
        message.delete.assert_not_awaited()

    async def test_music_controls_do_not_add_a_lyrics_button(self) -> None:
        guild_id = 605
        view = bot.MusicControlView(guild_id)

        self.assertNotIn("가사", {item.label for item in view.children})

    async def test_missing_lyrics_edits_message_to_unavailable(self) -> None:
        guild_id = 601
        channel, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.announcement_channel = channel
        track = make_track("missing")
        state.current = track

        with (
            patch.object(
                bot,
                "get_track_lyrics",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                bot,
                "get_track_namuwiki_lyrics",
                new=AsyncMock(),
            ) as namuwiki_lookup,
        ):
            await bot.publish_current_lyrics(guild_id, track)

        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        final_embed = message.edit.await_args.kwargs["embed"]
        self.assertEqual(final_embed.description, "미제공")
        final_view = message.edit.await_args.kwargs["view"]
        self.assertIsInstance(final_view, bot.LyricsVariantView)
        self.assertIn("나무위키 가사", {item.label for item in final_view.children})
        self.assertIs(state.lyrics_message, message)
        namuwiki_lookup.assert_not_awaited()

    async def test_missing_original_lyrics_does_not_start_namuwiki_lookup(
        self,
    ) -> None:
        guild_id = 606
        channel, _ = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.announcement_channel = channel
        track = make_track("namuwiki fallback")
        state.current = track

        with (
            patch.object(
                bot,
                "get_track_lyrics",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                bot,
                "get_track_namuwiki_lyrics",
                new=AsyncMock(return_value="원문\n독음\n번역"),
            ) as namuwiki_lookup,
        ):
            await bot.publish_current_lyrics(guild_id, track)

        channel.send.assert_awaited_once()
        namuwiki_lookup.assert_not_awaited()

    async def test_available_original_lyrics_do_not_lookup_namuwiki(
        self,
    ) -> None:
        guild_id = 607
        channel, _ = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.announcement_channel = channel
        track = make_track("original lyrics available")
        state.current = track

        with (
            patch.object(
                bot,
                "get_track_lyrics",
                new=AsyncMock(return_value="lrclib lyrics"),
            ),
            patch.object(
                bot,
                "get_track_namuwiki_lyrics",
                new=AsyncMock(),
            ) as namuwiki_lookup,
        ):
            await bot.publish_current_lyrics(guild_id, track)

        channel.send.assert_awaited_once()
        namuwiki_lookup.assert_not_awaited()

    async def test_long_lyrics_replace_attachment_with_full_utf8_text(self) -> None:
        guild_id = 602
        channel, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.announcement_channel = channel
        track = make_track("long")
        state.current = track
        original_lyrics = "原文の歌詞\n" * 700

        with patch.object(
            bot,
            "get_track_lyrics",
            new=AsyncMock(return_value=original_lyrics),
        ):
            await bot.publish_current_lyrics(guild_id, track)

        channel.send.assert_awaited_once()
        attachments = message.edit.await_args.kwargs["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0].filename, "lyrics.txt")
        self.assertEqual(attachments[0].fp.read().decode("utf-8"), original_lyrics)

    async def test_stop_deletes_the_lyrics_message(self) -> None:
        guild_id = 603
        channel, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        private_lyrics_message = MagicMock()
        private_lyrics_message.delete = AsyncMock()
        state.private_lyrics_messages[state.current.track_id] = [
            private_lyrics_message
        ]
        state.lyrics_message = message
        lyrics_view = MagicMock()
        state.lyrics_view = lyrics_view

        bot.stop_playback(state, guild_id)
        await asyncio.sleep(0)

        message.delete.assert_awaited_once()
        private_lyrics_message.delete.assert_awaited_once_with()
        lyrics_view.stop.assert_called_once_with()
        self.assertIsNone(state.lyrics_message)
        self.assertIsNone(state.lyrics_view)
        self.assertFalse(state.private_lyrics_messages)

    async def test_empty_queue_deletes_the_lyrics_message(self) -> None:
        guild_id = 604
        channel, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.lyrics_message = message

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "show_idle_panel", new=AsyncMock()) as show_idle,
        ):
            await bot.play_next(guild_id)

        message.delete.assert_awaited_once()
        show_idle.assert_awaited_once_with(guild_id, state)
        self.assertIsNone(state.lyrics_message)


class CommandSurfaceTests(unittest.TestCase):
    def test_registered_commands_match_supported_surface(self) -> None:
        command_names = {command.name for command in bot.bot.tree.get_commands()}

        self.assertEqual(
            command_names,
            {
                "auto",
                "setupmusic",
                "remove",
                "leave",
            },
        )

    def test_auto_command_has_required_count_and_song_options(self) -> None:
        command = bot.bot.tree.get_command("auto")

        self.assertIs(command, bot.queue_auto_tracks)
        options = command.to_dict(bot.bot.tree)["options"]
        self.assertEqual(
            [option["name"] for option in options],
            ["n", "곡명"],
        )
        count, query = options
        self.assertTrue(count["required"])
        self.assertEqual(
            count["type"], bot.discord.AppCommandOptionType.integer.value
        )
        self.assertEqual(count["min_value"], 1)
        self.assertEqual(count["max_value"], bot.MAX_AUTO_TRACKS)
        self.assertTrue(query["required"])
        self.assertEqual(
            query["type"], bot.discord.AppCommandOptionType.string.value
        )
        self.assertNotIn("min_value", query)
        self.assertNotIn("max_value", query)


class AutoSlashCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        bot.music_states.clear()

    def make_interaction(self, guild_id: int, channel: object) -> MagicMock:
        guild = MagicMock()
        guild.id = guild_id
        guild.get_channel.return_value = channel
        interaction = MagicMock()
        interaction.guild = guild
        interaction.guild_id = guild_id
        interaction.user = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        return interaction

    async def test_auto_command_defers_privately_and_enqueues_in_configured_channel(
        self,
    ) -> None:
        guild_id = 6543
        channel_id = 7655
        channel = MagicMock()
        channel.send = AsyncMock()
        interaction = self.make_interaction(guild_id, channel)
        loading_message = MagicMock()
        interaction.edit_original_response.return_value = loading_message
        state = bot.get_state(guild_id)
        state.playback_generation = 9

        with (
            patch.object(bot, "get_music_channel_id", return_value=channel_id),
            patch.object(
                bot,
                "ensure_voice_for_member",
                new=AsyncMock(return_value=(True, None)),
            ) as ensure_voice,
            patch.object(
                bot,
                "enqueue_tracks",
                new=AsyncMock(return_value=True),
            ) as enqueue,
        ):
            await bot.queue_auto_tracks.callback(interaction, 5, "back number")

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.guild.get_channel.assert_called_once_with(channel_id)
        self.assertIs(state.announcement_channel, channel)
        ensure_voice.assert_awaited_once_with(interaction.user, state)
        interaction.edit_original_response.assert_awaited_once_with(
            content="곡을 찾고 있어요..."
        )
        enqueue.assert_awaited_once_with(
            guild_id,
            channel,
            interaction.user,
            "back number",
            initial_response=loading_message,
            auto_count=5,
            request_generation=9,
        )

    async def test_auto_command_voice_failure_does_not_enqueue(self) -> None:
        guild_id = 6544
        channel_id = 7656
        channel = MagicMock()
        channel.send = AsyncMock()
        interaction = self.make_interaction(guild_id, channel)
        state = bot.get_state(guild_id)
        error = "먼저 음성 채널에 들어와 주세요."

        with (
            patch.object(bot, "get_music_channel_id", return_value=channel_id),
            patch.object(
                bot,
                "ensure_voice_for_member",
                new=AsyncMock(return_value=(False, error)),
            ) as ensure_voice,
            patch.object(bot, "enqueue_tracks", new=AsyncMock()) as enqueue,
        ):
            await bot.queue_auto_tracks.callback(interaction, 5, "back number")

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.guild.get_channel.assert_called_once_with(channel_id)
        self.assertIs(state.announcement_channel, channel)
        ensure_voice.assert_awaited_once_with(interaction.user, state)
        interaction.edit_original_response.assert_awaited_once_with(content=error)
        enqueue.assert_not_awaited()

    async def test_auto_command_requires_setup_before_voice_or_enqueue(self) -> None:
        guild_id = 6545
        channel = MagicMock()
        interaction = self.make_interaction(guild_id, channel)

        with (
            patch.object(bot, "get_music_channel_id", return_value=None),
            patch.object(bot, "get_state") as get_state,
            patch.object(
                bot,
                "ensure_voice_for_member",
                new=AsyncMock(),
            ) as ensure_voice,
            patch.object(bot, "enqueue_tracks", new=AsyncMock()) as enqueue,
        ):
            await bot.queue_auto_tracks.callback(interaction, 5, "back number")

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        interaction.edit_original_response.assert_awaited_once_with(
            content="먼저 `/setupmusic`으로 음악 신청 채널을 설정해 주세요."
        )
        interaction.guild.get_channel.assert_not_called()
        get_state.assert_not_called()
        ensure_voice.assert_not_awaited()
        enqueue.assert_not_awaited()


class EphemeralResponseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.housekeeping_tasks.clear()
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False

    async def asyncTearDown(self) -> None:
        tasks = list(bot.housekeeping_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bot.housekeeping_tasks.clear()
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        for state in bot.music_states.values():
            bot.cancel_queue_message_cleanups(state)
            bot.schedule_private_lyrics_cleanup(state)
        await asyncio.sleep(0)
        bot.music_states.clear()

    async def test_standard_private_response_uses_managed_expiry(self) -> None:
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.delete_original_response = AsyncMock()

        tasks_before = set(bot.housekeeping_tasks)
        with patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep:
            await bot.send_ephemeral_response(interaction, "완료")
            tasks = bot.housekeeping_tasks - tasks_before
            self.assertEqual(len(tasks), 1)
            await next(iter(tasks))
        await asyncio.sleep(0)

        interaction.response.send_message.assert_awaited_once_with(
            "완료",
            ephemeral=True,
        )
        sleep.assert_awaited_once_with(bot.EPHEMERAL_RESPONSE_DELETE_SECONDS)
        interaction.delete_original_response.assert_awaited_once_with()

    async def test_private_followup_uses_managed_expiry(self) -> None:
        interaction = MagicMock()
        message = MagicMock()
        message.delete = AsyncMock()
        interaction.followup.send = AsyncMock(return_value=message)

        tasks_before = set(bot.housekeeping_tasks)
        with patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep:
            result = await bot.send_ephemeral_followup(interaction, "완료")
            tasks = bot.housekeeping_tasks - tasks_before
            self.assertEqual(len(tasks), 1)
            await next(iter(tasks))
        await asyncio.sleep(0)

        self.assertIs(result, message)
        interaction.followup.send.assert_awaited_once_with(
            "완료",
            ephemeral=True,
            wait=True,
        )
        sleep.assert_awaited_once_with(bot.EPHEMERAL_RESPONSE_DELETE_SECONDS)
        message.delete.assert_awaited_once_with()

    async def test_ephemeral_expiry_tasks_are_cancelled_on_shutdown(self) -> None:
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        message = MagicMock()
        message.delete = AsyncMock()
        interaction.followup.send = AsyncMock(return_value=message)

        await bot.send_ephemeral_response(interaction, "응답", delete_after=60)
        await bot.send_ephemeral_followup(interaction, "후속", delete_after=60)
        tasks = set(bot.housekeeping_tasks)
        self.assertEqual(len(tasks), 2)

        bot.begin_bot_shutdown()
        await bot.shutdown_housekeeping_tasks()

        self.assertTrue(all(task.cancelled() for task in tasks))
        self.assertFalse(bot.housekeeping_tasks)
        interaction.delete_original_response.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_ephemeral_delete_after_none_schedules_nothing(self) -> None:
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        interaction.delete_original_response = AsyncMock()
        message = MagicMock()
        message.delete = AsyncMock()
        interaction.followup.send = AsyncMock(return_value=message)

        await bot.send_ephemeral_response(interaction, "응답", delete_after=None)
        result = await bot.send_ephemeral_followup(
            interaction,
            "후속",
            delete_after=None,
        )

        self.assertIs(result, message)
        self.assertFalse(bot.housekeeping_tasks)
        interaction.response.send_message.assert_awaited_once_with(
            "응답",
            ephemeral=True,
        )
        interaction.followup.send.assert_awaited_once_with(
            "후속",
            ephemeral=True,
            wait=True,
        )
        interaction.delete_original_response.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_queue_response_starts_with_common_expiry(self) -> None:
        guild_id = 701
        interaction = MagicMock()
        interaction.response.send_message = AsyncMock()
        message = MagicMock()
        message.id = 702
        interaction.original_response = AsyncMock(return_value=message)

        with patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup:
            await bot.send_queue_management_response(
                interaction,
                guild_id,
                content="대기열",
            )

        interaction.response.send_message.assert_awaited_once_with(
            "대기열",
            ephemeral=True,
        )
        schedule_cleanup.assert_called_once_with(
            bot.get_state(guild_id),
            message,
            bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
        )

    async def test_rescheduling_queue_cleanup_replaces_previous_timer(
        self,
    ) -> None:
        state = bot.GuildMusicState()
        message = MagicMock()
        message.id = 703
        message.delete = AsyncMock()

        first_task = bot.schedule_queue_message_cleanup(state, message, 60)
        second_task = bot.schedule_queue_message_cleanup(state, message, 0)
        self.assertIsNotNone(first_task)
        self.assertIsNotNone(second_task)

        await second_task
        await asyncio.sleep(0)

        self.assertTrue(first_task.cancelled())
        message.delete.assert_awaited_once_with()
        self.assertNotIn(message.id, state.queue_cleanup_tasks)


class MusicControlPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_autoplay_refill(state)
            if state.control_view is not None:
                bot.discord.ui.View.stop(state.control_view)
        bot.music_states.clear()

    async def test_music_control_views_have_stable_persistent_custom_ids(
        self,
    ) -> None:
        guild_id = 320
        expected_custom_ids = {
            "music:pause_resume",
            "music:skip",
            "music:stop",
            "music:repeat",
            "music:shuffle",
            "music:queue",
            "music:queue_range",
            bot.AUTOPLAY_BUTTON_CUSTOM_ID,
        }
        views = (
            bot.MusicControlView(guild_id),
            bot.MusicControlView(guild_id, disabled=True),
            bot.MusicControlView(guild_id),
        )

        try:
            for view in views:
                custom_ids = [item.custom_id for item in view.children]
                self.assertEqual(len(custom_ids), 8)
                self.assertEqual(set(custom_ids), expected_custom_ids)
                self.assertIsNone(view.timeout)
                self.assertTrue(view.is_persistent())
        finally:
            for view in views:
                bot.discord.ui.View.stop(view)
            bot.music_states.pop(guild_id, None)

    async def test_music_control_view_store_replaces_stable_dispatch_entries(
        self,
    ) -> None:
        guild_id = 321
        same_message_id = 9100
        separate_message_ids = tuple(range(9200, 9204))
        view_store = ViewStore(bot.bot._connection)
        registered_views: list[bot.MusicControlView] = []

        try:
            for message_ids in (
                (same_message_id,) * 4,
                separate_message_ids,
            ):
                counts: list[int] = []
                latest_views: dict[int, bot.MusicControlView] = {}
                for message_id in message_ids:
                    view = bot.MusicControlView(guild_id)
                    registered_views.append(view)
                    latest_views[message_id] = view
                    view_store.add_view(view, message_id)
                    counts.append(len(view_store._views[message_id]))

                self.assertEqual(counts, [8, 8, 8, 8])
                for message_id, view in latest_views.items():
                    dispatch_items = view_store._views[message_id]
                    self.assertIs(view_store._synced_message_views[message_id], view)
                    self.assertTrue(
                        all(item.view is view for item in dispatch_items.values())
                    )
        finally:
            for view in reversed(registered_views):
                bot.discord.ui.View.stop(view)
            bot.music_states.pop(guild_id, None)

    async def test_canonical_control_view_keeps_one_live_dispatch_owner(self) -> None:
        guild_id = 322
        message_id = 9300
        channel = MagicMock(id=9299)
        message = MagicMock(id=message_id, channel=channel)
        state = bot.get_state(guild_id)
        state.current = make_track("canonical-owner")
        state.control_message = message
        previous_view = bot.MusicControlView(guild_id)
        state.control_view = previous_view
        view_store = ViewStore(bot.bot._connection)
        registered_views = [previous_view]
        view_store.add_view(previous_view, message_id)

        def store_view(view: object, *, message_id: int) -> None:
            view_store.add_view(view, message_id)

        async def edit_message(**kwargs: object) -> None:
            view = kwargs["view"]
            registered_views.append(view)
            view_store.remove_message_tracking(message_id)
            view_store.add_view(view, message_id)

        message.edit = AsyncMock(side_effect=edit_message)
        interaction = MagicMock(message=message)
        interaction.response.is_done.return_value = True
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock(side_effect=edit_message)

        try:
            with patch.object(bot.bot, "add_view", side_effect=store_view) as add_view:
                await bot.update_control_panel(guild_id, state, channel=channel)

                first_owner = state.control_view
                self.assertIsNot(first_owner, previous_view)
                self.assertTrue(previous_view.is_finished())
                self.assertEqual(len(view_store._views[message_id]), 8)
                self.assertIs(view_store._synced_message_views[message_id], first_owner)
                self.assertTrue(
                    all(
                        item.view is first_owner
                        for item in view_store._views[message_id].values()
                    )
                )

                self.assertTrue(await first_owner.edit_panel(interaction))

                second_owner = state.control_view
                self.assertIsNot(second_owner, first_owner)
                self.assertTrue(first_owner.is_finished())
                self.assertEqual(len(view_store._views[message_id]), 8)
                self.assertIs(view_store._synced_message_views[message_id], second_owner)
                self.assertTrue(
                    all(
                        item.view is second_owner
                        for item in view_store._views[message_id].values()
                    )
                )
                self.assertEqual(add_view.call_count, 2)
                add_view.assert_any_call(first_owner, message_id=message_id)
                add_view.assert_any_call(second_owner, message_id=message_id)
                message.edit.assert_awaited_once()
                interaction.edit_original_response.assert_awaited_once()
                interaction.response.defer.assert_not_awaited()
        finally:
            for view in reversed(registered_views):
                bot.discord.ui.View.stop(view)
            bot.music_states.pop(guild_id, None)

    async def test_stopped_dispatched_owner_converges_after_canonical_replacement(
        self,
    ) -> None:
        guild_id = 323
        message_id = 9350
        state = bot.get_state(guild_id)
        state.current = make_track("owner-race")
        state.queue.append(make_track("queued"))
        generation = state.playback_generation
        playing = {"value": True}
        voice = MagicMock()
        voice.is_playing.side_effect = lambda: playing["value"]
        voice.is_paused.return_value = False
        voice.stop.side_effect = lambda: playing.__setitem__("value", False)
        state.voice = voice

        channel = MagicMock(id=9349)
        channel.send = AsyncMock()
        voice.channel = channel
        voice.is_connected.return_value = True
        message = MagicMock(id=message_id, channel=channel)
        message.id = message_id
        message.channel = channel
        state.control_message = message
        state.announcement_channel = channel
        dispatched_owner = bot.MusicControlView(guild_id)
        state.control_view = dispatched_owner
        view_store = ViewStore(bot.bot._connection)
        registered_views = [dispatched_owner]
        view_store.add_view(dispatched_owner, message_id)

        update_started = asyncio.Event()
        release_update = asyncio.Event()
        defer_seen = asyncio.Event()
        remote_edits: list[dict[str, object]] = []
        order: list[str] = []

        def store_view(view: object, *, message_id: int) -> None:
            view_store.add_view(view, message_id)

        async def edit_canonical(**kwargs: object) -> None:
            if not remote_edits:
                order.append("update-start")
                update_started.set()
                await release_update.wait()
            else:
                order.append("idle")
            view = kwargs["view"]
            registered_views.append(view)
            view_store.remove_message_tracking(message_id)
            view_store.add_view(view, message_id)
            remote_edits.append(kwargs)

        message.edit = AsyncMock(side_effect=edit_canonical)
        member = MagicMock()
        member.voice = type("MemberVoice", (), {"channel": channel})()
        interaction = MagicMock(message=message, user=member)
        interaction.response.is_done.return_value = False

        async def defer_response() -> None:
            order.append("defer")
            interaction.response.is_done.return_value = True
            defer_seen.set()

        interaction.response.defer = AsyncMock(side_effect=defer_response)
        interaction.edit_original_response = AsyncMock()
        stop_button = next(
            item
            for item in dispatched_owner.children
            if isinstance(item, bot.discord.ui.Button)
            and item.style == bot.discord.ButtonStyle.danger
        )
        tasks: list[asyncio.Task] = []

        try:
            with patch.object(bot.bot, "add_view", side_effect=store_view):
                update_task = asyncio.create_task(
                    bot.update_control_panel(guild_id, state, channel=channel)
                )
                tasks.append(update_task)
                await asyncio.wait_for(update_started.wait(), timeout=1)

                stop_task = asyncio.create_task(stop_button.callback(interaction))
                tasks.append(stop_task)
                await asyncio.wait_for(defer_seen.wait(), timeout=1)
                self.assertTrue(state.control_panel_lock.locked())
                self.assertFalse(stop_task.done())
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                self.assertEqual(state.playback_generation, generation + 1)
                voice.stop.assert_called_once_with()
                interaction.edit_original_response.assert_not_awaited()

                release_update.set()
                await asyncio.wait_for(
                    asyncio.gather(update_task, stop_task),
                    timeout=1,
                )

            self.assertEqual(order, ["update-start", "defer", "idle"])
            self.assertEqual(len(remote_edits), 2)
            self.assertNotEqual(remote_edits[0]["embed"].title, bot.IDLE_PANEL_TITLE)
            self.assertEqual(remote_edits[1]["embed"].title, bot.IDLE_PANEL_TITLE)
            final_view = remote_edits[1]["view"]
            self.assertIs(state.control_view, final_view)
            self.assertTrue(dispatched_owner.is_finished())
            self.assertTrue(remote_edits[0]["view"].is_finished())
            self.assertTrue(
                all(
                    child.disabled
                    for child in final_view.children
                    if child.custom_id != bot.AUTOPLAY_BUTTON_CUSTOM_ID
                )
            )
            self.assertEqual(len(view_store._views[message_id]), 8)
            self.assertTrue(
                all(
                    item.view is final_view
                    for item in view_store._views[message_id].values()
                )
            )
            interaction.response.defer.assert_awaited_once_with()
            interaction.edit_original_response.assert_not_awaited()
            self.assertEqual(message.edit.await_count, 2)
            channel.send.assert_not_awaited()
        finally:
            release_update.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            for view in reversed(registered_views):
                bot.discord.ui.View.stop(view)
            bot.cancel_autoplay_refill(state)
            bot.cancel_empty_channel_disconnect(state)
            bot.music_states.pop(guild_id, None)

    async def test_control_view_recovery_cleans_only_abandoned_dispatch_owners(
        self,
    ) -> None:
        view_store = ViewStore(bot.bot._connection)
        registered_views: list[bot.MusicControlView] = []
        response_404 = MagicMock(status=404, reason="Not Found")
        response_500 = MagicMock(status=500, reason="Internal Server Error")

        def make_message(message_id: int, channel: object) -> MagicMock:
            message = MagicMock(id=message_id, channel=channel)
            message.id = message_id
            message.channel = channel
            return message

        def own_view(
            state: bot.GuildMusicState,
            message_id: int,
        ) -> bot.MusicControlView:
            view = bot.MusicControlView(message_id)
            registered_views.append(view)
            state.control_view = view
            view_store.add_view(view, message_id)
            return view

        def make_send(channel: object, message_id: int):
            message = make_message(message_id, channel)

            async def send(**kwargs: object) -> object:
                view = kwargs["view"]
                registered_views.append(view)
                view_store.add_view(view, message_id)
                return message

            channel.send = AsyncMock(side_effect=send)
            return message

        channel_a = MagicMock(id=9400)
        channel_b = MagicMock(id=9500)
        mismatch_state = bot.GuildMusicState()
        mismatch_old = make_message(9401, channel_a)
        mismatch_state.control_message = mismatch_old
        mismatch_owner = own_view(mismatch_state, mismatch_old.id)
        mismatch_new = make_send(channel_b, 9501)

        channel_c = MagicMock(id=9600)
        missing_state = bot.GuildMusicState()
        missing_old = make_message(9601, channel_c)
        missing_state.control_message = missing_old
        missing_owner = own_view(missing_state, missing_old.id)

        async def raise_not_found(**_kwargs: object) -> None:
            view_store.remove_message_tracking(missing_old.id)
            raise bot.discord.NotFound(response_404, "missing panel")

        missing_old.edit = AsyncMock(side_effect=raise_not_found)
        missing_new = make_send(channel_c, 9602)

        channel_d = MagicMock(id=9700)
        failure_state = bot.GuildMusicState()
        failure_old = make_message(9701, channel_d)
        failure_state.control_message = failure_old
        own_view(failure_state, failure_old.id)
        prior_failure_owner = failure_state.control_view

        async def raise_http_error(**_kwargs: object) -> None:
            view_store.remove_message_tracking(failure_old.id)
            raise bot.discord.DiscordServerError(response_500, "edit failed")

        failure_old.edit = AsyncMock(side_effect=raise_http_error)
        channel_d.send = AsyncMock()

        channel_e = MagicMock(id=9750)
        cancelled_state = bot.GuildMusicState()
        cancelled_old = make_message(9751, channel_e)
        cancelled_state.control_message = cancelled_old
        cancelled_owner = own_view(cancelled_state, cancelled_old.id)
        cancelled_error = asyncio.CancelledError("panel edit cancelled")

        async def raise_cancelled(**_kwargs: object) -> None:
            view_store.remove_message_tracking(cancelled_old.id)
            raise cancelled_error

        cancelled_old.edit = AsyncMock(side_effect=raise_cancelled)
        channel_e.send = AsyncMock()

        try:
            with (
                patch.object(bot, "get_control_message_id", return_value=None),
                patch.object(bot, "set_control_message_id"),
                patch.object(bot, "clear_control_message_id"),
                patch.object(
                    bot,
                    "reconcile_control_panel_messages",
                    new=AsyncMock(return_value=None),
                ),
                patch.object(bot, "is_silent_music_channel", return_value=False),
                patch.object(bot.logger, "exception"),
            ):
                mismatch_result = await bot.update_control_panel(
                    9401,
                    mismatch_state,
                    channel=channel_b,
                )
                missing_result = await bot.update_control_panel(
                    9601,
                    missing_state,
                    channel=channel_c,
                )
                failure_result = await bot.update_control_panel(
                    9701,
                    failure_state,
                    channel=channel_d,
                )
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await bot.update_control_panel(
                        9751,
                        cancelled_state,
                        channel=channel_e,
                    )
                self.assertIs(raised.exception, cancelled_error)

            self.assertIs(mismatch_result, mismatch_new)
            self.assertTrue(mismatch_owner.is_finished())
            self.assertNotIn(mismatch_old.id, view_store._views)
            self.assertIs(mismatch_state.control_message, mismatch_new)
            self.assertEqual(len(view_store._views[mismatch_new.id]), 8)
            self.assertTrue(
                all(
                    item.view is mismatch_state.control_view
                    for item in view_store._views[mismatch_new.id].values()
                )
            )

            self.assertIs(missing_result, missing_new)
            self.assertTrue(missing_owner.is_finished())
            self.assertNotIn(missing_old.id, view_store._views)
            self.assertIs(missing_state.control_message, missing_new)
            self.assertEqual(len(view_store._views[missing_new.id]), 8)
            self.assertTrue(
                all(
                    item.view is missing_state.control_view
                    for item in view_store._views[missing_new.id].values()
                )
            )

            self.assertIsNone(failure_result)
            self.assertIs(failure_state.control_message, failure_old)
            self.assertIs(failure_state.control_view, prior_failure_owner)
            self.assertFalse(prior_failure_owner.is_finished())
            channel_d.send.assert_not_awaited()
            self.assertEqual(len(view_store._views[failure_old.id]), 8)
            self.assertTrue(
                all(
                    item.view is prior_failure_owner
                    for item in view_store._views[failure_old.id].values()
                )
            )

            self.assertIs(cancelled_state.control_message, cancelled_old)
            self.assertIs(cancelled_state.control_view, cancelled_owner)
            self.assertFalse(cancelled_owner.is_finished())
            self.assertFalse(cancelled_state.control_panel_lock.locked())
            channel_e.send.assert_not_awaited()
            self.assertEqual(len(view_store._views[cancelled_old.id]), 8)
            self.assertTrue(
                all(
                    item.view is cancelled_owner
                    for item in view_store._views[cancelled_old.id].values()
                )
            )
        finally:
            for view in reversed(registered_views):
                bot.discord.ui.View.stop(view)

    async def test_raw_panel_deletion_releases_only_the_live_dispatch_owner(
        self,
    ) -> None:
        for offset, bulk in enumerate((False, True)):
            with self.subTest(matching="bulk" if bulk else "single"):
                guild_id = 9760 + offset
                message_id = 9860 + offset
                state = bot.get_state(guild_id)
                message = MagicMock(id=message_id)
                message.id = message_id
                owner = bot.MusicControlView(guild_id)
                state.control_message = message
                state.control_view = owner
                view_store = ViewStore(bot.bot._connection)
                view_store.add_view(owner, message_id)
                payload = SimpleNamespace(guild_id=guild_id)
                if bulk:
                    payload.message_ids = {message_id, message_id + 100}
                    handler = bot.on_raw_bulk_message_delete
                else:
                    payload.message_id = message_id
                    handler = bot.on_raw_message_delete

                try:
                    with patch.object(
                        bot,
                        "clear_control_message_id",
                    ) as clear_id:
                        await handler(payload)

                    clear_id.assert_called_once_with(guild_id)
                    self.assertIsNone(state.control_message)
                    self.assertIsNone(state.control_view)
                    self.assertTrue(owner.is_finished())
                    self.assertFalse(state.control_panel_lock.locked())
                    self.assertNotIn(message_id, view_store._views)
                    self.assertNotIn(
                        message_id,
                        view_store._synced_message_views,
                    )
                finally:
                    bot.discord.ui.View.stop(owner)
                    bot.music_states.pop(guild_id, None)

        guild_id = 9780
        message_id = 9880
        state = bot.get_state(guild_id)
        message = MagicMock(id=message_id)
        message.id = message_id
        owner = bot.MusicControlView(guild_id)
        state.control_message = message
        state.control_view = owner
        view_store = ViewStore(bot.bot._connection)
        view_store.add_view(owner, message_id)
        try:
            with patch.object(bot, "clear_control_message_id") as clear_id:
                await bot.on_raw_message_delete(
                    SimpleNamespace(
                        guild_id=guild_id,
                        message_id=message_id + 1,
                    )
                )
                await bot.on_raw_bulk_message_delete(
                    SimpleNamespace(
                        guild_id=guild_id,
                        message_ids={message_id + 2, message_id + 3},
                    )
                )

            clear_id.assert_not_called()
            self.assertIs(state.control_message, message)
            self.assertIs(state.control_view, owner)
            self.assertFalse(owner.is_finished())
            self.assertEqual(len(view_store._views[message_id]), 8)
        finally:
            bot.discord.ui.View.stop(owner)
            bot.music_states.pop(guild_id, None)

        guild_id = 9790
        old_message_id = 9890
        new_message_id = 9891
        state = bot.get_state(guild_id)
        old_message = MagicMock(id=old_message_id)
        old_message.id = old_message_id
        old_owner = bot.MusicControlView(guild_id)
        state.control_message = old_message
        state.control_view = old_owner
        view_store = ViewStore(bot.bot._connection)
        view_store.add_view(old_owner, old_message_id)
        handler_task = None
        test_holds_lock = False

        def store_view(view: object, *, message_id: int) -> None:
            view_store.add_view(view, message_id)

        try:
            await state.control_panel_lock.acquire()
            test_holds_lock = True
            with (
                patch.object(bot, "clear_control_message_id") as clear_id,
                patch.object(bot.bot, "add_view", side_effect=store_view),
            ):
                handler_task = asyncio.create_task(
                    bot.on_raw_message_delete(
                        SimpleNamespace(
                            guild_id=guild_id,
                            message_id=old_message_id,
                        )
                    )
                )
                await asyncio.sleep(0)
                self.assertFalse(handler_task.done())

                new_message = MagicMock(id=new_message_id)
                new_message.id = new_message_id
                new_owner = bot.MusicControlView(guild_id)
                view_store.add_view(new_owner, new_message_id)
                state.control_message = new_message
                bot.replace_control_panel_view(
                    state,
                    new_owner,
                    message_id=new_message_id,
                )

                state.control_panel_lock.release()
                test_holds_lock = False
                await asyncio.wait_for(handler_task, timeout=1)

            clear_id.assert_not_called()
            self.assertIs(state.control_message, new_message)
            self.assertIs(state.control_view, new_owner)
            self.assertFalse(new_owner.is_finished())
            self.assertTrue(old_owner.is_finished())
            self.assertNotIn(old_message_id, view_store._views)
            self.assertEqual(len(view_store._views[new_message_id]), 8)
            self.assertTrue(
                all(
                    item.view is new_owner
                    for item in view_store._views[new_message_id].values()
                )
            )
        finally:
            if test_holds_lock:
                state.control_panel_lock.release()
            if handler_task is not None and not handler_task.done():
                handler_task.cancel()
                await asyncio.gather(handler_task, return_exceptions=True)
            bot.discord.ui.View.stop(old_owner)
            if "new_owner" in locals():
                bot.discord.ui.View.stop(new_owner)
            bot.music_states.pop(guild_id, None)

    async def test_deleted_persistent_callbacks_cannot_recreate_the_panel(
        self,
    ) -> None:
        for offset, action in enumerate(("repeat", "stop")):
            with self.subTest(action=action):
                guild_id = 9795 + offset
                message_id = 9895 + offset
                state = bot.get_state(guild_id)
                state.current = make_track(f"deleted-{action}")
                state.queue.append(make_track("queued"))
                voice = MagicMock()
                voice.is_playing.return_value = True
                voice.is_paused.return_value = False
                state.voice = voice
                channel = MagicMock(id=10_100 + offset)
                channel.send = AsyncMock()
                voice.channel = channel
                voice.is_connected.return_value = True
                message = MagicMock(id=message_id, channel=channel)
                message.id = message_id
                message.channel = channel
                message.edit = AsyncMock()
                state.control_message = message
                state.announcement_channel = channel
                owner = bot.MusicControlView(guild_id)
                state.control_view = owner
                view_store = ViewStore(bot.bot._connection)
                view_store.add_view(owner, message_id)

                clicked_started = asyncio.Event()
                release_clicked = asyncio.Event()
                response = MagicMock(status=500, reason="Internal Server Error")
                clicked_error = bot.discord.DiscordServerError(
                    response,
                    f"{action} clicked edit failed",
                )

                async def fail_clicked_edit(**_kwargs: object) -> None:
                    clicked_started.set()
                    await release_clicked.wait()
                    raise clicked_error

                member = MagicMock()
                member.voice = type("MemberVoice", (), {"channel": channel})()
                interaction = MagicMock(message=message, user=member)
                acknowledged = False

                async def defer_response() -> None:
                    nonlocal acknowledged
                    acknowledged = True

                interaction.response.defer = AsyncMock(side_effect=defer_response)
                interaction.response.is_done.side_effect = lambda: acknowledged
                interaction.edit_original_response = AsyncMock(
                    side_effect=fail_clicked_edit,
                )
                callback_task = None
                raw_task = None
                try:
                    with (
                        patch.object(bot, "get_music_channel_id", return_value=None),
                        patch.object(bot, "get_control_message_id", return_value=None),
                        patch.object(bot, "set_control_message_id") as set_id,
                        patch.object(bot, "clear_control_message_id") as clear_id,
                        patch.object(
                            bot,
                            "reconcile_control_panel_messages",
                            new=AsyncMock(return_value=None),
                        ),
                    ):
                        callback_task = asyncio.create_task(
                            getattr(owner, action).callback(interaction)
                        )
                        await asyncio.wait_for(clicked_started.wait(), timeout=1)
                        self.assertTrue(state.control_panel_lock.locked())

                        raw_task = asyncio.create_task(
                            bot.on_raw_message_delete(
                                SimpleNamespace(
                                    guild_id=guild_id,
                                    message_id=message_id,
                                )
                            )
                        )
                        await asyncio.sleep(0)
                        self.assertFalse(raw_task.done())
                        release_clicked.set()

                        with self.assertRaises(
                            bot.discord.DiscordServerError
                        ) as raised:
                            await asyncio.wait_for(callback_task, timeout=1)
                        self.assertIs(raised.exception, clicked_error)
                        await asyncio.wait_for(raw_task, timeout=1)

                    clear_id.assert_called_once_with(guild_id)
                    set_id.assert_not_called()
                    self.assertIsNone(state.control_message)
                    self.assertIsNone(state.control_view)
                    self.assertTrue(owner.is_finished())
                    self.assertNotIn(message_id, view_store._views)
                    interaction.response.defer.assert_awaited_once_with()
                    interaction.edit_original_response.assert_awaited_once()
                    message.edit.assert_not_awaited()
                    channel.send.assert_not_awaited()
                finally:
                    release_clicked.set()
                    for task in (callback_task, raw_task):
                        if task is not None and not task.done():
                            task.cancel()
                    await asyncio.gather(
                        *(
                            task
                            for task in (callback_task, raw_task)
                            if task is not None
                        ),
                        return_exceptions=True,
                    )
                    bot.discord.ui.View.stop(owner)
                    bot.cancel_autoplay_refill(state)
                    bot.cancel_empty_channel_disconnect(state)
                    bot.music_states.pop(guild_id, None)

    async def test_delete_control_panel_cleans_terminal_results_and_retries_cancel(
        self,
    ) -> None:
        cases = (
            ("success", None),
            (
                "not-found",
                bot.discord.NotFound(
                    MagicMock(status=404, reason="Not Found"),
                    "missing panel",
                ),
            ),
            (
                "http-error",
                bot.discord.DiscordServerError(
                    MagicMock(status=500, reason="Internal Server Error"),
                    "delete failed",
                ),
            ),
        )

        for offset, (label, error) in enumerate(cases):
            with self.subTest(label=label):
                guild_id = 9800 + offset
                message_id = 9900 + offset
                channel = MagicMock(id=10_000 + offset)
                message = MagicMock(id=message_id, channel=channel)
                message.id = message_id
                message.channel = channel
                message.delete = AsyncMock(side_effect=error)
                state = bot.GuildMusicState(control_message=message)
                view = bot.MusicControlView(guild_id)
                state.control_view = view
                view_store = ViewStore(bot.bot._connection)
                view_store.add_view(view, message_id)

                try:
                    with (
                        patch.object(bot, "clear_control_message_id") as clear_id,
                        patch.object(bot.logger, "exception"),
                    ):
                        await bot.delete_control_panel(
                            guild_id,
                            state,
                            channel=channel,
                        )

                    message.delete.assert_awaited_once_with()
                    clear_id.assert_called_once_with(guild_id)
                    self.assertIsNone(state.control_message)
                    self.assertIsNone(state.control_view)
                    self.assertTrue(view.is_finished())
                    self.assertFalse(state.control_panel_lock.locked())
                    self.assertNotIn(message_id, view_store._views)
                    self.assertNotIn(message_id, view_store._synced_message_views)
                finally:
                    bot.discord.ui.View.stop(view)

        guild_id = 9803
        message_id = 9903
        channel = MagicMock(id=10_003)
        message = MagicMock(id=message_id, channel=channel)
        message.id = message_id
        message.channel = channel
        cancelled_error = asyncio.CancelledError("delete cancelled")
        message.delete = AsyncMock(side_effect=(cancelled_error, None))
        state = bot.GuildMusicState(control_message=message)
        view = bot.MusicControlView(guild_id)
        state.control_view = view
        view_store = ViewStore(bot.bot._connection)
        view_store.add_view(view, message_id)

        try:
            with patch.object(bot, "clear_control_message_id") as clear_id:
                with self.assertRaises(asyncio.CancelledError) as raised:
                    await bot.delete_control_panel(
                        guild_id,
                        state,
                        channel=channel,
                    )
                self.assertIs(raised.exception, cancelled_error)
                self.assertIs(state.control_message, message)
                self.assertIs(state.control_view, view)
                self.assertFalse(view.is_finished())
                self.assertFalse(state.control_panel_lock.locked())
                clear_id.assert_not_called()
                self.assertEqual(len(view_store._views[message_id]), 8)
                self.assertTrue(
                    all(
                        item.view is view
                        for item in view_store._views[message_id].values()
                    )
                )

                await bot.delete_control_panel(
                    guild_id,
                    state,
                    channel=channel,
                )

                self.assertEqual(message.delete.await_count, 2)
                clear_id.assert_called_once_with(guild_id)
                self.assertIsNone(state.control_message)
                self.assertIsNone(state.control_view)
                self.assertTrue(view.is_finished())
                self.assertFalse(state.control_panel_lock.locked())
                self.assertNotIn(message_id, view_store._views)
                self.assertNotIn(message_id, view_store._synced_message_views)
        finally:
            bot.discord.ui.View.stop(view)



    def _make_pause_case(self, guild_id: int, action: str):
        state = bot.get_state(guild_id)
        state.current = make_track(f"current-{guild_id}")
        channel = MagicMock(id=7000 + guild_id)
        flags = {"playing": action == "pause", "paused": action == "resume"}
        operations: list[str] = []
        acknowledged = {"done": False}
        voice = MagicMock(channel=channel)
        voice.is_connected.return_value = True
        voice.is_playing.side_effect = lambda: flags["playing"]
        voice.is_paused.side_effect = lambda: flags["paused"]

        def pause_voice() -> None:
            operations.append("pause")
            flags.update(playing=False, paused=True)

        def resume_voice() -> None:
            operations.append("resume")
            flags.update(playing=True, paused=False)

        voice.pause.side_effect = pause_voice
        voice.resume.side_effect = resume_voice
        state.voice = voice
        member = MagicMock()
        member.voice = type("VoiceState", (), {"channel": channel})()
        interaction = MagicMock(
            guild_id=guild_id,
            message=MagicMock(id=8000 + guild_id),
            user=member,
        )
        interaction.response.defer = AsyncMock()
        interaction.response.is_done.side_effect = lambda: acknowledged["done"]
        interaction.response.send_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock(return_value=None)
        return state, voice, flags, operations, acknowledged, interaction

    def _make_skip_case(self, guild_id: int) -> SimpleNamespace:
        state = bot.get_state(guild_id)
        track = make_track(f"skip-{guild_id}")
        state.current = track
        state.playback_generation = 7
        state.skip_requested = False
        channel = MagicMock(id=9000 + guild_id)
        flags = {"connected": True, "playing": True, "paused": False}
        operations: list[str] = []
        acknowledged = {"done": False}
        voice = MagicMock(channel=channel)
        voice.is_connected.side_effect = lambda: flags["connected"]
        voice.is_playing.side_effect = lambda: flags["playing"]
        voice.is_paused.side_effect = lambda: flags["paused"]

        def stop_voice() -> None:
            operations.append(f"stop:{state.skip_requested}")

        voice.stop.side_effect = stop_voice
        state.voice = voice
        member = MagicMock()
        member.voice = type("VoiceState", (), {"channel": channel})()
        interaction = MagicMock(
            data={"custom_id": "skip-contract"},
            guild_id=guild_id,
            message=MagicMock(id=10000 + guild_id),
            user=member,
        )
        interaction.response.defer = AsyncMock()
        interaction.response.is_done.side_effect = lambda: acknowledged["done"]
        interaction.response.send_message = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.followup.send = AsyncMock(return_value=None)
        return SimpleNamespace(
            state=state,
            track=track,
            voice=voice,
            flags=flags,
            operations=operations,
            acknowledged=acknowledged,
            interaction=interaction,
            view=bot.MusicControlView(guild_id),
        )

    async def _assert_component_skip_contract(
        self,
        *,
        first_guild_id: int,
    ) -> None:
        next_guild_id = first_guild_id

        def make_case() -> SimpleNamespace:
            nonlocal next_guild_id
            case = self._make_skip_case(next_guild_id)
            next_guild_id += 1
            return case

        async def invoke(case: SimpleNamespace, *, check: bool = True) -> None:
            if check:
                self.assertTrue(
                    await case.view.interaction_check(case.interaction)
                )
            await case.view.skip.callback(case.interaction)

        def set_final_response(case: SimpleNamespace, side_effect) -> None:
            case.interaction.followup.send.side_effect = side_effect

        def assert_feedback(case: SimpleNamespace, content: str) -> None:
            case.interaction.response.send_message.assert_not_awaited()
            case.interaction.followup.send.assert_awaited_once_with(
                content, ephemeral=True, wait=True
            )
            case.interaction.edit_original_response.assert_not_awaited()

        with patch.object(
            bot,
            "create_housekeeping_task",
            side_effect=lambda coroutine: coroutine.close(),
        ):
            for initial_state in ("voice", "track", "idle"):
                with self.subTest(initial_state=initial_state):
                    case = make_case()
                    if initial_state == "voice":
                        case.state.voice = None
                    elif initial_state == "track":
                        case.state.current = None
                    else:
                        case.flags.update(playing=False, paused=False)
                    await invoke(case, check=False)
                    case.interaction.response.send_message.assert_awaited_once_with(
                        "스킵할 곡이 없어요.", ephemeral=True
                    )
                    case.interaction.response.defer.assert_not_awaited()
                    case.interaction.followup.send.assert_not_awaited()
                    case.interaction.edit_original_response.assert_not_awaited()
                    self.assertFalse(case.state.skip_requested)
                    case.voice.stop.assert_not_called()
                    bot.music_states.pop(case.interaction.guild_id, None)

        case = make_case()

        async def acknowledge() -> None:
            case.operations.append("defer")
            self.assertFalse(case.state.skip_requested)
            case.voice.stop.assert_not_called()
            case.acknowledged["done"] = True

        async def finish_response(*_args: object, **_kwargs: object) -> None:
            case.operations.append("response")
            return None

        case.interaction.response.defer.side_effect = acknowledge
        set_final_response(case, finish_response)
        await invoke(case)
        self.assertEqual(case.operations, ["defer", "stop:True", "response"])
        self.assertTrue(case.state.skip_requested)
        case.voice.stop.assert_called_once_with()
        case.interaction.response.defer.assert_awaited_once_with()
        assert_feedback(case, "다음 곡으로 넘어갈게요.")
        bot.music_states.pop(case.interaction.guild_id, None)

        case = make_case()
        defer_error = bot.discord.DiscordServerError(
            MagicMock(status=500, reason="Internal Server Error"),
            "<html>skip defer failure</html>",
        )
        case.interaction.response.defer.side_effect = defer_error
        with self.assertRaises(bot.discord.DiscordServerError) as raised:
            await invoke(case)
        self.assertIs(raised.exception, defer_error)
        self.assertFalse(case.state.skip_requested)
        case.voice.stop.assert_not_called()
        case.interaction.followup.send.assert_not_awaited()
        case.interaction.edit_original_response.assert_not_awaited()
        bot.music_states.pop(case.interaction.guild_id, None)

        case = make_case()
        defer_started = asyncio.Event()
        release_defer = asyncio.Event()

        async def block_defer() -> None:
            defer_started.set()
            await release_defer.wait()

        case.interaction.response.defer.side_effect = block_defer
        callback_task = asyncio.create_task(invoke(case))
        try:
            await asyncio.wait_for(defer_started.wait(), timeout=1)
            self.assertFalse(case.state.skip_requested)
            case.voice.stop.assert_not_called()
            callback_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(callback_task, timeout=1)
            self.assertTrue(callback_task.cancelled())
            case.interaction.followup.send.assert_not_awaited()
            case.interaction.edit_original_response.assert_not_awaited()
        finally:
            release_defer.set()
            callback_task.cancel()
            await asyncio.gather(callback_task, return_exceptions=True)
            bot.music_states.pop(case.interaction.guild_id, None)

        changed_message = "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요."
        same_channel_message = "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
        for changed_state, expected_message in (
            ("voice", changed_message),
            ("track", changed_message),
            ("generation", changed_message),
            ("member", same_channel_message),
            ("disconnected", same_channel_message),
            ("idle", "스킵할 곡이 없어요."),
        ):
            with self.subTest(changed_state=changed_state):
                case = make_case()
                replacement_voice = None

                async def change_during_defer() -> None:
                    nonlocal replacement_voice
                    case.operations.append("defer")
                    self.assertFalse(case.state.skip_requested)
                    case.voice.stop.assert_not_called()
                    if changed_state == "voice":
                        replacement_voice = MagicMock(
                            channel=MagicMock(id=20000 + case.interaction.guild_id)
                        )
                        replacement_voice.is_connected.return_value = False
                        case.flags["connected"] = False
                        case.state.voice = replacement_voice
                    elif changed_state == "track":
                        case.state.current = make_track("replacement-skip")
                    elif changed_state == "generation":
                        case.state.playback_generation += 1
                    elif changed_state == "member":
                        case.interaction.user.voice.channel = None
                    elif changed_state == "disconnected":
                        case.flags["connected"] = False
                    else:
                        case.flags.update(playing=False, paused=False)
                    case.acknowledged["done"] = True

                async def record_response(
                    *_args: object,
                    **_kwargs: object,
                ) -> None:
                    case.operations.append("response")
                    return None

                case.interaction.response.defer.side_effect = change_during_defer
                set_final_response(case, record_response)
                await invoke(case)
                self.assertEqual(case.operations, ["defer", "response"])
                self.assertFalse(case.state.skip_requested)
                case.voice.stop.assert_not_called()
                if replacement_voice is not None:
                    replacement_voice.stop.assert_not_called()
                case.interaction.response.defer.assert_awaited_once_with()
                assert_feedback(case, expected_message)
                bot.music_states.pop(case.interaction.guild_id, None)

        case = make_case()
        response_error = bot.discord.DiscordServerError(
            MagicMock(status=500, reason="Internal Server Error"),
            "<html>skip final response failure</html>",
        )

        async def acknowledge_final_failure() -> None:
            case.operations.append("defer")
            case.acknowledged["done"] = True

        async def fail_final_response(*_args: object, **_kwargs: object) -> None:
            case.operations.append("response")
            raise response_error

        case.interaction.response.defer.side_effect = acknowledge_final_failure
        set_final_response(case, fail_final_response)
        with self.assertRaises(bot.discord.DiscordServerError) as raised:
            await invoke(case)
        self.assertIs(raised.exception, response_error)
        self.assertEqual(case.operations, ["defer", "stop:True", "response"])
        self.assertTrue(case.state.skip_requested)
        case.voice.stop.assert_called_once_with()
        assert_feedback(case, "다음 곡으로 넘어갈게요.")
        bot.music_states.pop(case.interaction.guild_id, None)

        case = make_case()
        response_started = asyncio.Event()
        release_response = asyncio.Event()

        async def acknowledge_final_cancel() -> None:
            case.operations.append("defer")
            case.acknowledged["done"] = True

        async def block_final_response(*_args: object, **_kwargs: object) -> None:
            case.operations.append("response")
            response_started.set()
            await release_response.wait()

        case.interaction.response.defer.side_effect = acknowledge_final_cancel
        set_final_response(case, block_final_response)
        callback_task = asyncio.create_task(invoke(case))
        try:
            await asyncio.wait_for(response_started.wait(), timeout=1)
            self.assertEqual(case.operations, ["defer", "stop:True", "response"])
            self.assertTrue(case.state.skip_requested)
            case.voice.stop.assert_called_once_with()
            callback_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(callback_task, timeout=1)
            self.assertTrue(callback_task.cancelled())
            assert_feedback(case, "다음 곡으로 넘어갈게요.")
        finally:
            release_response.set()
            callback_task.cancel()
            await asyncio.gather(callback_task, return_exceptions=True)
            bot.music_states.pop(case.interaction.guild_id, None)

    async def test_component_skip_acknowledges_and_revalidates_before_stop(
        self,
    ) -> None:
        await self._assert_component_skip_contract(first_guild_id=362)

    async def test_pause_resume_acknowledges_and_revalidates_before_toggle(
        self,
    ) -> None:
        def make_case(guild_id: int, *, paused: bool):
            action = "resume" if paused else "pause"
            state, voice, flags, operations, acknowledged, interaction = (
                self._make_pause_case(guild_id, action)
            )
            lock_states: list[bool] = []
            view = bot.MusicControlView(guild_id)
            return state, voice, flags, operations, lock_states, acknowledged, interaction, view

        with patch.object(
            bot,
            "create_housekeeping_task",
            side_effect=lambda coroutine: coroutine.close(),
        ):
            for guild_id, initial_state, expected_message in (
                (341, "missing", "봇이 음성 채널에 없어요."),
                (342, "idle", "지금 재생 중인 곡이 없어요."),
            ):
                with self.subTest(initial_state=initial_state):
                    state, voice, flags, _ops, _locks, _ack, interaction, view = (
                        make_case(guild_id, paused=False)
                    )
                    if initial_state == "missing":
                        state.voice = None
                    else:
                        flags.update(playing=False, paused=False)
                    await view.pause_resume.callback(interaction)
                    interaction.response.send_message.assert_awaited_once_with(
                        expected_message, ephemeral=True
                    )
                    interaction.response.defer.assert_not_awaited()
                    interaction.followup.send.assert_not_awaited()
                    interaction.edit_original_response.assert_not_awaited()
                    self.assertEqual(_ops, [])
                    bot.music_states.pop(guild_id, None)

        for guild_id, initially_paused, expected_action in (
            (343, False, "pause"),
            (344, True, "resume"),
        ):
            with self.subTest(expected_action=expected_action):
                state, voice, flags, operations, lock_states, acknowledged, interaction, view = (
                    make_case(guild_id, paused=initially_paused)
                )

                async def defer_response() -> None:
                    operations.append("defer")
                    lock_states.append(state.control_panel_lock.locked())
                    voice.pause.assert_not_called()
                    voice.resume.assert_not_called()
                    acknowledged["done"] = True

                async def edit_response(**_kwargs: object) -> None:
                    operations.append("edit")
                    lock_states.append(state.control_panel_lock.locked())

                interaction.response.defer.side_effect = defer_response
                interaction.edit_original_response.side_effect = edit_response
                await view.pause_resume.callback(interaction)
                self.assertEqual(operations, ["defer", expected_action, "edit"])
                self.assertEqual(lock_states, [False, True])
                interaction.response.defer.assert_awaited_once_with()
                interaction.edit_original_response.assert_awaited_once()
                interaction.response.send_message.assert_not_awaited()
                interaction.followup.send.assert_not_awaited()
                self.assertEqual(
                    flags,
                    {"playing": initially_paused, "paused": not initially_paused},
                )
                bot.music_states.pop(guild_id, None)

        state, voice, flags, operations, _locks, _ack, interaction, view = (
            make_case(345, paused=False)
        )
        response_error = bot.discord.DiscordServerError(
            MagicMock(status=500, reason="Internal Server Error"),
            "<html>temporary failure</html>",
        )
        interaction.response.defer.side_effect = response_error
        with self.assertRaises(bot.discord.DiscordServerError) as raised:
            await view.pause_resume.callback(interaction)
        self.assertIs(raised.exception, response_error)
        self.assertEqual(flags, {"playing": True, "paused": False})
        self.assertIs(state.voice, voice)
        self.assertEqual(operations, [])
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_not_awaited()
        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()
        bot.music_states.pop(345, None)

        state, voice, flags, operations, lock_states, _ack, interaction, view = (
            make_case(346, paused=False)
        )
        defer_started = asyncio.Event()
        release_defer = asyncio.Event()

        async def block_defer() -> None:
            operations.append("defer")
            lock_states.append(state.control_panel_lock.locked())
            defer_started.set()
            await release_defer.wait()

        interaction.response.defer.side_effect = block_defer
        callback_task = asyncio.create_task(view.pause_resume.callback(interaction))
        try:
            await asyncio.wait_for(defer_started.wait(), timeout=1)
            self.assertEqual(flags, {"playing": True, "paused": False})
            self.assertEqual(lock_states, [False])
            callback_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(callback_task, timeout=1)

            self.assertTrue(callback_task.cancelled())
            self.assertIs(state.voice, voice)
            voice.pause.assert_not_called()
            voice.resume.assert_not_called()
            interaction.edit_original_response.assert_not_awaited()
            interaction.response.send_message.assert_not_awaited()
            interaction.followup.send.assert_not_awaited()
        finally:
            release_defer.set()
            callback_task.cancel()
            await asyncio.gather(callback_task, return_exceptions=True)
            bot.music_states.pop(346, None)

        for guild_id, changed_state, expected_message in (
            (347, "moved", "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."),
            (348, "idle", "지금 재생 중인 곡이 없어요."),
            (
                349,
                "replacement",
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            ),
        ):
            with self.subTest(changed_state=changed_state):
                state, voice, flags, operations, lock_states, acknowledged, interaction, view = (
                    make_case(guild_id, paused=False)
                )
                replacement_voice = None

                async def defer_response() -> None:
                    nonlocal replacement_voice
                    operations.append("defer")
                    lock_states.append(state.control_panel_lock.locked())
                    if changed_state == "moved":
                        interaction.user.voice.channel = MagicMock(id=9000 + guild_id)
                    elif changed_state == "idle":
                        flags.update(playing=False, paused=False)
                    else:
                        replacement_voice = MagicMock(
                            channel=MagicMock(id=9000 + guild_id)
                        )
                        replacement_voice.is_connected.return_value = False
                        state.voice = replacement_voice
                    acknowledged["done"] = True

                async def send_followup(*_args: object, **_kwargs: object) -> None:
                    operations.append("followup")
                    return None

                interaction.response.defer.side_effect = defer_response
                interaction.followup.send.side_effect = send_followup
                await view.pause_resume.callback(interaction)
                self.assertEqual(operations, ["defer", "followup"])
                self.assertEqual(lock_states, [False])
                if changed_state == "replacement":
                    self.assertIs(state.voice, replacement_voice)
                    replacement_voice.pause.assert_not_called()
                    replacement_voice.resume.assert_not_called()
                else:
                    self.assertIs(state.voice, voice)
                interaction.response.defer.assert_awaited_once_with()
                interaction.response.send_message.assert_not_awaited()
                interaction.edit_original_response.assert_not_awaited()
                interaction.followup.send.assert_awaited_once_with(
                    expected_message, ephemeral=True, wait=True
                )
                bot.music_states.pop(guild_id, None)


    async def test_component_edit_cannot_overwrite_newer_idle_panel(self) -> None:
        guild_id = 320
        playing_edit_started = asyncio.Event()
        release_playing_edit = asyncio.Event()
        remote_titles: list[str | None] = []
        remote_views: list[bot.discord.ui.View] = []
        playing_edit_sources: list[str] = []
        playing_edit_lock_states: list[bool] = []
        defer_lock_states: list[bool] = []

        class Guild:
            id = guild_id

        class Channel:
            id = 653
            guild = Guild()

            def __init__(self) -> None:
                self.send = AsyncMock()

        channel = Channel()
        state = bot.get_state(guild_id)

        async def record_remote_edit(
            source: str,
            *,
            embed: bot.discord.Embed,
            view: bot.discord.ui.View,
            **_kwargs: object,
        ) -> None:
            if (
                embed.title == bot.PLAYING_PANEL_TITLE
                and not playing_edit_started.is_set()
            ):
                playing_edit_sources.append(source)
                playing_edit_lock_states.append(state.control_panel_lock.locked())
                playing_edit_started.set()
                await release_playing_edit.wait()
            remote_titles.append(embed.title)
            remote_views.append(view)

        class Message:
            id = 986

            def __init__(self) -> None:
                self.channel = channel
                self.edit = AsyncMock(side_effect=self._edit)

            async def _edit(self, **kwargs: object) -> None:
                await record_remote_edit("control_message", **kwargs)

        message = Message()
        state.current = make_track("playing")
        state.control_message = message
        state.announcement_channel = channel
        view = bot.MusicControlView(guild_id)
        interaction = MagicMock()
        interaction.message = message

        async def defer_response() -> None:
            defer_lock_states.append(state.control_panel_lock.locked())

        async def edit_interaction_response(**kwargs: object) -> None:
            await record_remote_edit("interaction_response", **kwargs)

        interaction.response.defer = AsyncMock(side_effect=defer_response)
        interaction.response.is_done.return_value = False
        interaction.response.edit_message = AsyncMock()
        interaction.edit_original_response = AsyncMock(
            side_effect=edit_interaction_response
        )
        component_task = None
        idle_task = None
        idle_pending_before_release = False

        with patch.object(bot, "get_music_channel_id", return_value=None):
            try:
                component_task = asyncio.create_task(view.edit_panel(interaction))
                await asyncio.wait_for(playing_edit_started.wait(), timeout=1)
                interaction.response.defer.assert_awaited_once_with()
                self.assertEqual(defer_lock_states, [False])

                state.current = None
                idle_task = asyncio.create_task(
                    bot.show_idle_panel(guild_id, state)
                )
                await asyncio.sleep(0)
                idle_pending_before_release = not idle_task.done()

                release_playing_edit.set()
                await asyncio.wait_for(
                    asyncio.gather(component_task, idle_task),
                    timeout=1,
                )
            finally:
                release_playing_edit.set()
                tasks = [
                    task
                    for task in (component_task, idle_task)
                    if task is not None
                ]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )

        interaction.response.edit_message.assert_not_awaited()
        interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(playing_edit_sources, ["interaction_response"])
        self.assertEqual(playing_edit_lock_states, [True])
        self.assertTrue(idle_pending_before_release)
        self.assertEqual(
            remote_titles,
            [bot.PLAYING_PANEL_TITLE, bot.IDLE_PANEL_TITLE],
        )
        self.assertEqual(message.edit.await_count, 1)
        channel.send.assert_not_awaited()
        final_view = remote_views[-1]
        self.assertTrue(
            all(
                item.disabled
                for item in final_view.children
                if item.custom_id != bot.AUTOPLAY_BUTTON_CUSTOM_ID
            )
        )


    async def test_state_buttons_revalidate_voice_after_defer(self) -> None:
        changed_message = (
            "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요."
        )
        same_channel_message = (
            "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
        )
        enter_channel_message = "먼저 음성 채널에 들어가 주세요."
        cases = [
            (action, outcome)
            for action in ("repeat", "shuffle", "autoplay")
            for outcome in (
                "defer-voice",
                "member",
                "disconnect",
                "finished",
            )
        ]
        cases.extend(
            (
                ("repeat", "current"),
                ("repeat", "generation"),
                ("shuffle", "current-success"),
                ("shuffle", "generation"),
                ("autoplay", "current-generation-success"),
                ("autoplay", "no-voice-member"),
                ("autoplay", "offline-success"),
                ("autoplay", "disconnected-connected"),
                ("autoplay", "disconnected-connected-success"),
            )
        )

        async def run_case(guild_id: int, action: str, outcome: str) -> None:
            state = bot.get_state(guild_id)
            current = make_track(f"{action}-{outcome}-current")
            queued = [
                make_track(f"{action}-{outcome}-{index}")
                for index in range(3)
            ]
            state.current = current
            state.queue.extend(queued)
            original_queue = state.queue
            generation = state.playback_generation
            member_channel = MagicMock(id=10_000 + guild_id)
            member_voice = MagicMock(channel=member_channel)
            member = MagicMock(voice=member_voice)
            accepted_voice = None
            if outcome != "no-voice-member":
                accepted_voice = MagicMock(channel=member_channel)
                accepted_voice.is_connected.return_value = (
                    outcome
                    not in {
                        "offline-success",
                        "disconnected-connected",
                        "disconnected-connected-success",
                    }
                )
                state.voice = accepted_voice
                if outcome == "offline-success":
                    accepted_voice.channel = MagicMock(id=10_500 + guild_id)

            panel_channel = MagicMock(id=11_000 + guild_id)
            panel_channel.send = AsyncMock()
            canonical = MagicMock(
                id=12_000 + guild_id,
                channel=panel_channel,
            )
            canonical.edit = AsyncMock()
            state.control_message = canonical
            state.announcement_channel = panel_channel
            state.control_view = bot.MusicControlView(guild_id)
            view = bot.MusicControlView(guild_id)
            custom_id = (
                bot.AUTOPLAY_BUTTON_CUSTOM_ID
                if action == "autoplay"
                else f"music:{action}"
            )
            button = next(
                item for item in view.children if item.custom_id == custom_id
            )
            clicked = MagicMock(
                id=canonical.id + 1,
                channel=panel_channel,
            )
            interaction = MagicMock(
                message=clicked,
                user=member,
                data={"custom_id": custom_id},
            )
            acknowledged = False
            defer_completed = asyncio.Event()
            release_defer = asyncio.Event()

            async def defer_response() -> None:
                nonlocal acknowledged
                acknowledged = True
                defer_completed.set()
                await release_defer.wait()

            interaction.response.is_done.side_effect = lambda: acknowledged
            interaction.response.send_message = AsyncMock()
            interaction.response.defer = AsyncMock(side_effect=defer_response)
            interaction.edit_original_response = AsyncMock()
            interaction.followup.send = AsyncMock(return_value=None)
            callback_task = None
            replacement_voice = None
            replacement_current = None
            with (
                patch.object(bot, "get_music_channel_id", return_value=None),
                patch.object(
                    bot.random,
                    "shuffle",
                    side_effect=lambda tracks: tracks.reverse(),
                ) as shuffle_mock,
                patch.object(bot, "set_autoplay_enabled") as persist_mock,
                patch.object(bot, "schedule_autoplay_refill") as refill_mock,
                patch.object(bot, "cancel_autoplay_refill") as cancel_mock,
            ):
                try:
                    self.assertTrue(await view.interaction_check(interaction))
                    interaction.response.send_message.assert_not_awaited()
                    callback_task = asyncio.create_task(
                        button.callback(interaction)
                    )
                    await asyncio.wait_for(defer_completed.wait(), timeout=1)
                    self.assertFalse(callback_task.done())

                    if outcome == "defer-voice":
                        replacement_channel = MagicMock(id=13_000 + guild_id)
                        replacement_voice = MagicMock(
                            channel=replacement_channel
                        )
                        replacement_voice.is_connected.return_value = True
                        self.assertIsNotNone(accepted_voice)
                        accepted_voice.is_connected.return_value = False
                        state.voice = replacement_voice
                        member_voice.channel = replacement_channel
                    elif outcome == "member":
                        member_voice.channel = None
                    elif outcome == "disconnect":
                        self.assertIsNotNone(accepted_voice)
                        accepted_voice.is_connected.return_value = False
                    elif outcome == "finished":
                        bot.discord.ui.View.stop(view)
                    elif outcome in {
                        "current",
                        "current-success",
                        "current-generation-success",
                    }:
                        replacement_current = make_track(
                            f"{action}-replacement-current"
                        )
                        state.current = replacement_current
                        if outcome == "current-generation-success":
                            state.playback_generation += 1
                    elif outcome == "generation":
                        state.playback_generation += 1
                    elif outcome == "no-voice-member":
                        member_voice.channel = None
                    elif outcome == "disconnected-connected":
                        self.assertIsNotNone(accepted_voice)
                        accepted_voice.channel = MagicMock(id=14_000 + guild_id)
                        accepted_voice.is_connected.return_value = True
                    elif outcome == "disconnected-connected-success":
                        self.assertIsNotNone(accepted_voice)
                        accepted_voice.is_connected.return_value = True
                    else:
                        self.assertEqual(outcome, "offline-success")

                    release_defer.set()
                    await asyncio.wait_for(callback_task, timeout=1)

                    interaction.response.defer.assert_awaited_once_with()
                    if outcome in {
                        "current-success",
                        "current-generation-success",
                        "offline-success",
                        "disconnected-connected-success",
                    }:
                        if outcome in {
                            "current-success",
                            "current-generation-success",
                        }:
                            self.assertIs(state.current, replacement_current)
                            self.assertEqual(
                                state.playback_generation,
                                generation
                                + (outcome == "current-generation-success"),
                            )
                        else:
                            self.assertIs(state.current, current)
                            self.assertEqual(
                                state.playback_generation,
                                generation,
                            )
                        interaction.followup.send.assert_not_awaited()
                        interaction.edit_original_response.assert_awaited_once()
                        canonical.edit.assert_awaited_once()
                        if action == "repeat":
                            self.assertTrue(state.repeat_one)
                            self.assertIs(state.queue, original_queue)
                            self.assertEqual(list(state.queue), queued)
                        elif action == "shuffle":
                            self.assertFalse(state.repeat_one)
                            self.assertEqual(
                                list(state.queue),
                                list(reversed(queued)),
                            )
                            shuffle_mock.assert_called_once()
                        else:
                            self.assertTrue(state.autoplay_enabled)
                            persist_mock.assert_called_once_with(guild_id, True)
                            refill_mock.assert_called_once_with(guild_id)
                            cancel_mock.assert_not_called()
                    else:
                        expected_message = (
                            changed_message
                            if outcome
                            in {
                                "defer-voice",
                                "finished",
                                "current",
                                "generation",
                            }
                            else (
                                enter_channel_message
                                if outcome == "no-voice-member"
                                else same_channel_message
                            )
                        )
                        self.assertIs(
                            state.current,
                            replacement_current
                            if outcome == "current"
                            else current,
                        )
                        self.assertEqual(
                            state.playback_generation,
                            generation + (outcome == "generation"),
                        )
                        self.assertIs(state.queue, original_queue)
                        self.assertEqual(list(state.queue), queued)
                        self.assertFalse(state.repeat_one)
                        self.assertFalse(state.autoplay_enabled)
                        interaction.followup.send.assert_awaited_once_with(
                            expected_message,
                            ephemeral=True,
                            wait=True,
                        )
                        interaction.edit_original_response.assert_not_awaited()
                        canonical.edit.assert_not_awaited()
                        shuffle_mock.assert_not_called()
                        persist_mock.assert_not_called()
                        refill_mock.assert_not_called()
                        cancel_mock.assert_not_called()
                        if accepted_voice is not None:
                            accepted_voice.stop.assert_not_called()
                        if replacement_voice is not None:
                            replacement_voice.stop.assert_not_called()
                    panel_channel.send.assert_not_awaited()
                finally:
                    release_defer.set()
                    if callback_task is not None and not callback_task.done():
                        callback_task.cancel()
                    if callback_task is not None:
                        await asyncio.wait_for(
                            asyncio.gather(
                                callback_task,
                                return_exceptions=True,
                            ),
                            timeout=1,
                        )
                    bot.cancel_autoplay_refill(state)
                    bot.cancel_empty_channel_disconnect(state)
                    if state.control_view is not None:
                        bot.discord.ui.View.stop(state.control_view)
                    bot.discord.ui.View.stop(view)
                    bot.music_states.pop(guild_id, None)

        for offset, (action, outcome) in enumerate(cases):
            with self.subTest(action=action, outcome=outcome):
                await run_case(350 + offset, action, outcome)

    async def test_component_edit_canonical_refresh_contract(self) -> None:
        def make_case(
            guild_id: int,
            *,
            same_id: bool,
        ) -> tuple[
            bot.GuildMusicState,
            MagicMock,
            MagicMock,
            MagicMock,
            bot.MusicControlView,
        ]:
            state = bot.get_state(guild_id)
            state.current = make_track(f"current-{guild_id}")
            channel = MagicMock(id=6000 + guild_id)
            channel.send = AsyncMock()
            canonical = MagicMock(id=7000 + guild_id, channel=channel)
            canonical.edit = AsyncMock()
            state.control_message = canonical
            state.announcement_channel = channel
            clicked = MagicMock(
                id=canonical.id if same_id else canonical.id + 1,
                channel=channel,
            )
            interaction = MagicMock(message=clicked)
            interaction.response.is_done.return_value = False
            interaction.response.defer = AsyncMock()
            interaction.edit_original_response = AsyncMock()
            view = bot.MusicControlView(guild_id)
            if same_id:
                state.control_view = view
            return state, channel, canonical, interaction, view

        async def run_failure_case(guild_id: int, *, cancel: bool) -> None:
            state, channel, canonical, interaction, view = make_case(
                guild_id,
                same_id=True,
            )
            self.assertIsNot(interaction.message, canonical)
            replacement = make_track(f"replacement-{guild_id}")
            order: list[str] = []
            lock_states: list[bool] = []
            clicked_started = asyncio.Event()
            release_clicked = asyncio.Event()
            response = MagicMock(status=500, reason="Internal Server Error")
            clicked_error = bot.discord.DiscordServerError(
                response,
                f"<html>clicked failure {guild_id}</html>",
            )

            async def defer_response() -> None:
                order.append("defer")
                lock_states.append(state.control_panel_lock.locked())

            async def fail_clicked(**_kwargs: object) -> None:
                order.append("clicked")
                lock_states.append(state.control_panel_lock.locked())
                state.current = replacement
                clicked_started.set()
                if cancel:
                    await release_clicked.wait()
                raise clicked_error

            async def edit_canonical(**_kwargs: object) -> None:
                order.append("canonical")
                lock_states.append(state.control_panel_lock.locked())

            interaction.response.defer = AsyncMock(side_effect=defer_response)
            interaction.edit_original_response = AsyncMock(side_effect=fail_clicked)
            canonical.edit = AsyncMock(side_effect=edit_canonical)
            task = None
            try:
                with patch.object(bot, "get_music_channel_id", return_value=None):
                    task = asyncio.create_task(
                        view.edit_panel(interaction, refresh_canonical=True)
                    )
                    await asyncio.wait_for(clicked_started.wait(), timeout=1)
                    if cancel:
                        self.assertFalse(task.done())
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(task, timeout=1)
                        self.assertTrue(task.cancelled())
                    else:
                        with self.assertRaises(
                            bot.discord.DiscordServerError
                        ) as raised:
                            await asyncio.wait_for(task, timeout=1)
                        self.assertIs(raised.exception, clicked_error)

                self.assertEqual(order, ["defer", "clicked", "canonical"])
                self.assertEqual(lock_states, [False, True, True])
                interaction.response.defer.assert_awaited_once_with()
                interaction.edit_original_response.assert_awaited_once()
                canonical.edit.assert_awaited_once()
                self.assertEqual(
                    canonical.edit.await_args.kwargs["embed"].to_dict(),
                    bot.make_player_embed(replacement, state).to_dict(),
                )
                channel.send.assert_not_awaited()
            finally:
                release_clicked.set()
                if task is not None and not task.done():
                    task.cancel()
                if task is not None:
                    await asyncio.gather(task, return_exceptions=True)
                bot.cancel_empty_channel_disconnect(state)
                if state.control_view is not None:
                    bot.discord.ui.View.stop(state.control_view)
                bot.music_states.pop(guild_id, None)

        state, channel, canonical, interaction, view = make_case(
            339,
            same_id=False,
        )
        replacement = make_track("default-live")
        defer_seen = asyncio.Event()
        interaction.response.defer = AsyncMock(side_effect=defer_seen.set)
        edit_task = None
        test_holds_lock = False
        try:
            await asyncio.wait_for(state.control_panel_lock.acquire(), timeout=1)
            test_holds_lock = True
            edit_task = asyncio.create_task(view.edit_panel(interaction))
            await asyncio.wait_for(defer_seen.wait(), timeout=1)
            self.assertFalse(edit_task.done())
            state.current = replacement
            state.control_panel_lock.release()
            test_holds_lock = False
            await asyncio.wait_for(edit_task, timeout=1)
            canonical.edit.assert_not_awaited()
            self.assertEqual(
                interaction.edit_original_response.await_args.kwargs[
                    "embed"
                ].to_dict(),
                bot.make_player_embed(replacement, state).to_dict(),
            )
            channel.send.assert_not_awaited()
        finally:
            if test_holds_lock:
                state.control_panel_lock.release()
            if edit_task is not None and not edit_task.done():
                edit_task.cancel()
            if edit_task is not None:
                await asyncio.gather(edit_task, return_exceptions=True)
            bot.cancel_empty_channel_disconnect(state)
            if state.control_view is not None:
                bot.discord.ui.View.stop(state.control_view)
            bot.music_states.pop(339, None)

        state, channel, canonical, interaction, view = make_case(
            340,
            same_id=True,
        )
        self.assertIsNot(interaction.message, canonical)
        try:
            await view.edit_panel(interaction, refresh_canonical=True)
            interaction.edit_original_response.assert_awaited_once()
            canonical.edit.assert_not_awaited()
            channel.send.assert_not_awaited()
        finally:
            bot.cancel_empty_channel_disconnect(state)
            if state.control_view is not None:
                bot.discord.ui.View.stop(state.control_view)
            bot.music_states.pop(340, None)

        await run_failure_case(341, cancel=False)
        await run_failure_case(342, cancel=True)

    async def test_stop_button_converges_clicked_and_canonical_panels(
        self,
    ) -> None:
        def assert_idle_panel(kwargs: dict[str, object]) -> None:
            self.assertEqual(kwargs["embed"].title, bot.IDLE_PANEL_TITLE)
            idle_view = kwargs["view"]
            self.assertIsInstance(idle_view, bot.MusicControlView)
            self.assertTrue(
                all(
                    item.disabled
                    for item in idle_view.children
                    if item.custom_id != bot.AUTOPLAY_BUTTON_CUSTOM_ID
                )
            )

        guild_ids = (325, 326)
        try:
            for guild_id, clicked_is_canonical in zip(
                guild_ids,
                (False, True),
            ):
                with self.subTest(clicked_is_canonical=clicked_is_canonical):
                    state = bot.get_state(guild_id)
                    state.current = make_track("current")
                    state.queue.append(make_track("queued"))
                    generation = state.playback_generation
                    voice = MagicMock()
                    voice.playing = True
                    voice.is_connected.return_value = True
                    voice.is_playing.side_effect = lambda: voice.playing
                    voice.is_paused.return_value = False
                    voice.stop.side_effect = lambda: setattr(
                        voice,
                        "playing",
                        False,
                    )

                    channel = MagicMock(id=660 + guild_id)
                    channel.send = AsyncMock()
                    voice.channel = channel
                    state.voice = voice
                    canonical_message = MagicMock(id=760 + guild_id)
                    canonical_message.channel = channel
                    operation_order: list[str] = []
                    canonical_message.edit = AsyncMock(
                        side_effect=lambda **_kwargs: operation_order.append(
                            "canonical"
                        )
                    )
                    state.control_message = canonical_message
                    state.announcement_channel = channel
                    clicked_message = MagicMock(
                        id=(
                            canonical_message.id
                            if clicked_is_canonical
                            else canonical_message.id + 1
                        )
                    )
                    clicked_message.channel = channel

                    member = MagicMock()
                    member.voice = type(
                        "MemberVoice",
                        (),
                        {"channel": channel},
                    )()
                    interaction = MagicMock(
                        message=clicked_message,
                        user=member,
                    )
                    interaction.response.is_done.return_value = False

                    async def defer_response() -> None:
                        operation_order.append("defer")
                        self.assertIsNotNone(state.current)
                        self.assertTrue(state.queue)
                        self.assertEqual(state.playback_generation, generation)
                        voice.stop.assert_not_called()
                        interaction.response.is_done.return_value = True

                    interaction.response.defer = AsyncMock(
                        side_effect=defer_response
                    )
                    interaction.edit_original_response = AsyncMock(
                        side_effect=lambda **_kwargs: operation_order.append(
                            "clicked"
                        )
                    )
                    view = bot.MusicControlView(guild_id)
                    if clicked_is_canonical:
                        state.control_view = view
                    else:
                        state.control_view = bot.MusicControlView(guild_id)
                    button = next(
                        item
                        for item in view.children
                        if isinstance(item, bot.discord.ui.Button)
                        and item.style == bot.discord.ButtonStyle.danger
                    )

                    with patch.object(
                        bot,
                        "get_music_channel_id",
                        return_value=None,
                    ):
                        await button.callback(interaction)

                    self.assertIsNone(state.current)
                    self.assertFalse(state.queue)
                    self.assertEqual(state.playback_generation, generation + 1)
                    self.assertFalse(voice.is_playing())
                    voice.stop.assert_called_once_with()
                    interaction.response.defer.assert_awaited_once_with()
                    interaction.edit_original_response.assert_awaited_once()
                    assert_idle_panel(
                        interaction.edit_original_response.await_args.kwargs
                    )
                    self.assertIsNot(clicked_message, canonical_message)

                    if clicked_is_canonical:
                        self.assertEqual(clicked_message.id, canonical_message.id)
                        self.assertEqual(operation_order, ["defer", "clicked"])
                        canonical_message.edit.assert_not_awaited()
                    else:
                        self.assertNotEqual(clicked_message.id, canonical_message.id)
                        self.assertEqual(
                            operation_order,
                            ["defer", "clicked", "canonical"],
                        )
                        canonical_message.edit.assert_awaited_once()
                        canonical_kwargs = canonical_message.edit.await_args.kwargs
                        self.assertIsNone(canonical_kwargs["content"])
                        assert_idle_panel(canonical_kwargs)
                    channel.send.assert_not_awaited()
        finally:
            for guild_id in guild_ids:
                state = bot.music_states.get(guild_id)
                if state is None:
                    continue
                bot.cancel_autoplay_refill(state)
                bot.cancel_empty_channel_disconnect(state)
                if state.control_view is not None:
                    bot.discord.ui.View.stop(state.control_view)
                bot.music_states.pop(guild_id, None)

    async def test_stop_button_acknowledges_revalidates_and_converges(
        self,
    ) -> None:
        def assert_stopped(
            state: bot.GuildMusicState,
            voice: MagicMock,
            generation: int,
        ) -> None:
            self.assertIsNone(state.current)
            self.assertFalse(state.queue)
            self.assertEqual(state.playback_generation, generation + 1)
            self.assertFalse(voice.is_playing())
            voice.stop.assert_called_once_with()

        def assert_idle_panel(kwargs: dict[str, object]) -> None:
            self.assertIsNone(kwargs["content"])
            self.assertEqual(kwargs["embed"].title, bot.IDLE_PANEL_TITLE)
            idle_view = kwargs["view"]
            self.assertIsInstance(idle_view, bot.MusicControlView)
            self.assertTrue(
                all(
                    item.disabled
                    for item in idle_view.children
                    if item.custom_id != bot.AUTOPLAY_BUTTON_CUSTOM_ID
                )
            )

        async def run_case(guild_id: int, outcome: str) -> None:
            state = bot.get_state(guild_id)
            current = make_track("current")
            queued = make_track("queued")
            state.current = current
            state.queue.append(queued)
            generation = state.playback_generation
            voice = MagicMock()
            voice.playing = True
            voice.is_connected.return_value = True
            voice.is_playing.side_effect = lambda: voice.playing
            voice.is_paused.return_value = False
            voice.stop.side_effect = lambda: setattr(voice, "playing", False)

            channel = MagicMock(id=860 + guild_id)
            channel.send = AsyncMock()
            voice.channel = channel
            state.voice = voice
            canonical_message = MagicMock(id=960 + guild_id)
            canonical_message.channel = channel
            operation_order: list[str] = []
            canonical_message.edit = AsyncMock(
                side_effect=lambda **_kwargs: operation_order.append("canonical")
            )
            state.control_message = canonical_message
            state.announcement_channel = channel
            clicked_message = MagicMock(id=canonical_message.id)
            clicked_message.channel = channel

            response = MagicMock(status=500, reason="Internal Server Error")
            response_error = bot.discord.DiscordServerError(
                response,
                "<html>temporary failure</html>",
            )
            defer_started = asyncio.Event()
            release_defer = asyncio.Event()
            edit_started = asyncio.Event()
            release_edit = asyncio.Event()
            member = MagicMock()
            member.voice = type(
                "MemberVoice",
                (),
                {"channel": channel},
            )()
            interaction = MagicMock(message=clicked_message, user=member)
            interaction.response.is_done.return_value = False
            interaction.followup.send = AsyncMock(return_value=None)
            replacement_voice = None

            def assert_not_stopped() -> None:
                self.assertIs(state.current, current)
                self.assertEqual(list(state.queue), [queued])
                self.assertFalse(state.stop_requested)
                voice.stop.assert_not_called()

            async def defer_response() -> None:
                nonlocal replacement_voice
                operation_order.append("defer")
                assert_not_stopped()
                self.assertEqual(state.playback_generation, generation)
                if outcome == "voice":
                    replacement_voice = MagicMock()
                    state.voice = replacement_voice
                    voice.is_connected.return_value = False
                elif outcome == "generation":
                    state.playback_generation += 1
                elif outcome == "member":
                    interaction.user.voice.channel = None
                elif outcome == "disconnected":
                    voice.is_connected.return_value = False
                elif outcome == "current":
                    state.current = make_track("replacement-current")
                elif outcome == "defer-error":
                    raise response_error
                elif outcome == "defer-cancel":
                    defer_started.set()
                    await release_defer.wait()
                interaction.response.is_done.return_value = True

            async def edit_clicked_panel(**_kwargs: object) -> None:
                operation_order.append("clicked")
                self.assertTrue(state.control_panel_lock.locked())
                assert_stopped(state, voice, generation)
                edit_started.set()
                if outcome in {"current", "final-error", "final-cancel"}:
                    await release_edit.wait()
                if outcome == "final-error":
                    raise response_error

            interaction.response.defer = AsyncMock(side_effect=defer_response)
            interaction.edit_original_response = AsyncMock(
                side_effect=edit_clicked_panel
            )
            view = bot.MusicControlView(guild_id)
            state.control_view = view
            button = next(
                item
                for item in view.children
                if isinstance(item, bot.discord.ui.Button)
                and item.style == bot.discord.ButtonStyle.danger
            )
            callback_task = None
            try:
                with patch.object(
                    bot,
                    "get_music_channel_id",
                    return_value=None,
                ):
                    callback_task = asyncio.create_task(
                        button.callback(interaction)
                    )
                    if outcome == "defer-cancel":
                        await asyncio.wait_for(defer_started.wait(), timeout=1)
                        callback_task.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(callback_task, timeout=1)
                        self.assertTrue(callback_task.cancelled())
                    elif outcome == "defer-error":
                        with self.assertRaises(
                            bot.discord.DiscordServerError
                        ) as raised:
                            await asyncio.wait_for(callback_task, timeout=1)
                        self.assertIs(raised.exception, response_error)
                    elif outcome in {"voice", "generation", "member", "disconnected"}:
                        await asyncio.wait_for(callback_task, timeout=1)
                    else:
                        await asyncio.wait_for(edit_started.wait(), timeout=1)
                        self.assertEqual(operation_order, ["defer", "clicked"])
                        self.assertFalse(callback_task.done())
                        canonical_message.edit.assert_not_awaited()
                        assert_stopped(state, voice, generation)
                        if outcome == "final-cancel":
                            callback_task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await asyncio.wait_for(callback_task, timeout=1)
                            self.assertTrue(callback_task.cancelled())
                        else:
                            release_edit.set()
                            if outcome == "final-error":
                                with self.assertRaises(
                                    bot.discord.DiscordServerError
                                ) as raised:
                                    await asyncio.wait_for(callback_task, timeout=1)
                                self.assertIs(raised.exception, response_error)
                            else:
                                await asyncio.wait_for(callback_task, timeout=1)

                interaction.response.defer.assert_awaited_once_with()
                if outcome in {"defer-error", "defer-cancel"}:
                    self.assertEqual(operation_order, ["defer"])
                    self.assertEqual(state.playback_generation, generation)
                    assert_not_stopped()
                    interaction.edit_original_response.assert_not_awaited()
                    interaction.followup.send.assert_not_awaited()
                    canonical_message.edit.assert_not_awaited()
                elif outcome in {"voice", "generation", "member", "disconnected"}:
                    expected_message = (
                        "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요."
                        if outcome in {"voice", "generation"}
                        else "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
                    )
                    self.assertIs(state.current, current)
                    self.assertEqual(list(state.queue), [queued])
                    self.assertFalse(state.stop_requested)
                    self.assertEqual(
                        state.playback_generation,
                        generation + (outcome == "generation"),
                    )
                    voice.stop.assert_not_called()
                    if replacement_voice is not None:
                        replacement_voice.stop.assert_not_called()
                    interaction.edit_original_response.assert_not_awaited()
                    interaction.followup.send.assert_awaited_once_with(
                        expected_message,
                        ephemeral=True,
                        wait=True,
                    )
                    canonical_message.edit.assert_not_awaited()
                elif outcome == "current":
                    self.assertEqual(operation_order, ["defer", "clicked"])
                    assert_stopped(state, voice, generation)
                    interaction.edit_original_response.assert_awaited_once()
                    canonical_message.edit.assert_not_awaited()
                else:
                    self.assertEqual(
                        operation_order,
                        ["defer", "clicked", "canonical"],
                    )
                    interaction.edit_original_response.assert_awaited_once()
                    canonical_message.edit.assert_awaited_once()
                    assert_idle_panel(canonical_message.edit.await_args.kwargs)
                channel.send.assert_not_awaited()
            finally:
                release_defer.set()
                release_edit.set()
                if callback_task is not None and not callback_task.done():
                    callback_task.cancel()
                if callback_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(callback_task, return_exceptions=True),
                        timeout=1,
                    )
                bot.cancel_autoplay_refill(state)
                bot.cancel_empty_channel_disconnect(state)
                if state.control_view is not None:
                    bot.discord.ui.View.stop(state.control_view)
                bot.music_states.pop(guild_id, None)

        for guild_id, outcome in enumerate(
            (
                "defer-error",
                "defer-cancel",
                "voice",
                "generation",
                "member",
                "disconnected",
                "current",
                "final-error",
                "final-cancel",
            ),
            start=327,
        ):
            with self.subTest(outcome=outcome):
                await run_case(guild_id, outcome)

    async def test_remove_responds_before_blocked_panel_and_converges_after_response_failure(
        self,
    ) -> None:
        guild_id = 324
        response_attempted = asyncio.Event()

        class Guild:
            id = guild_id

        class VoiceChannel:
            id = 657

        voice_channel = VoiceChannel()

        class TextChannel:
            id = 658
            guild = Guild()

            def __init__(self) -> None:
                self.send = AsyncMock()

        text_channel = TextChannel()

        class Message:
            id = 991

            def __init__(self) -> None:
                self.channel = text_channel
                self.edit = AsyncMock()

        message = Message()

        class Voice:
            channel = voice_channel

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return True

            def is_paused(self) -> bool:
                return False

        class User:
            voice = type("MemberVoice", (), {"channel": voice_channel})()

        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )

        async def fail_followup(*_args: object, **_kwargs: object) -> None:
            response_attempted.set()
            raise response_error

        async def defer_response(**_kwargs: object) -> None:
            interaction.response.is_done.return_value = True

        interaction = MagicMock()
        interaction.guild_id = guild_id
        interaction.user = User()
        interaction.response.defer = AsyncMock(side_effect=defer_response)
        interaction.response.send_message = AsyncMock()
        interaction.response.is_done.return_value = False
        interaction.followup.send = AsyncMock(side_effect=fail_followup)

        current = make_track("now-playing")
        first = make_track("remove-first")
        second = make_track("keep-second")
        state = bot.get_state(guild_id)
        state.voice = Voice()
        state.current = current
        state.queue.extend([first, second])
        state.autoplay_enabled = False
        state.control_message = message
        state.announcement_channel = text_channel
        remove_task = None
        test_holds_lock = False

        expected_content = f"대기열에서 `{first.title}`을 삭제했어요."
        with (
            patch.object(bot, "get_music_channel_id", return_value=None),
            patch.object(
                bot,
                "send_ephemeral_followup",
                wraps=bot.send_ephemeral_followup,
            ) as send_ephemeral_followup,
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
        ):
            try:
                await asyncio.wait_for(state.control_panel_lock.acquire(), timeout=1)
                test_holds_lock = True
                remove_task = asyncio.create_task(
                    bot.remove_from_queue.callback(interaction, 1)
                )
                await asyncio.wait_for(response_attempted.wait(), timeout=1)

                interaction.response.defer.assert_awaited_once_with(ephemeral=True)
                send_ephemeral_followup.assert_awaited_once_with(
                    interaction,
                    expected_content,
                    delete_after=bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
                )
                interaction.followup.send.assert_awaited_once_with(
                    expected_content,
                    ephemeral=True,
                    wait=True,
                )
                interaction.response.send_message.assert_not_awaited()
                schedule_refill.assert_called_once_with(guild_id)
                self.assertEqual(list(state.queue), [second])
                self.assertIs(state.current, current)
                self.assertFalse(remove_task.done())
                message.edit.assert_not_awaited()

                state.control_panel_lock.release()
                test_holds_lock = False
                with self.assertRaises(bot.discord.DiscordServerError) as raised:
                    await asyncio.wait_for(remove_task, timeout=1)
                self.assertIs(raised.exception, response_error)
            finally:
                if test_holds_lock:
                    state.control_panel_lock.release()
                if remove_task is not None and not remove_task.done():
                    remove_task.cancel()
                if remove_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(remove_task, return_exceptions=True),
                        timeout=1,
                    )
                autoplay_task = state.autoplay_task
                bot.cancel_autoplay_refill(state)
                if autoplay_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(autoplay_task, return_exceptions=True),
                        timeout=1,
                    )
                empty_timer = state.empty_channel_task
                bot.cancel_empty_channel_disconnect(state)
                if empty_timer is not None:
                    await asyncio.wait_for(
                        asyncio.gather(empty_timer, return_exceptions=True),
                        timeout=1,
                    )
                if state.control_view is not None:
                    bot.discord.ui.View.stop(state.control_view)
                bot.music_states.pop(guild_id, None)

        message.edit.assert_awaited_once()
        edit_kwargs = message.edit.await_args.kwargs
        self.assertIsNone(edit_kwargs["content"])
        self.assertEqual(
            edit_kwargs["embed"].to_dict(),
            bot.make_player_embed(current, state).to_dict(),
        )
        panel_text = str(edit_kwargs["embed"].to_dict())
        self.assertIn(second.title, panel_text)
        self.assertNotIn(first.title, panel_text)
        active_view = edit_kwargs["view"]
        self.assertIsInstance(active_view, bot.MusicControlView)
        self.assertTrue(all(not item.disabled for item in active_view.children))
        text_channel.send.assert_not_awaited()

    async def test_remove_acknowledges_before_stable_deletion_and_revalidates(
        self,
    ) -> None:
        cases: list[SimpleNamespace] = []
        callback_tasks: list[asyncio.Task] = []
        release_events: list[asyncio.Event] = []

        def make_case(guild_id: int, *, playing: bool = False) -> SimpleNamespace:
            channel = SimpleNamespace(id=20_000 + guild_id)
            voice = MagicMock(channel=channel)
            voice.is_connected.return_value = True
            member = SimpleNamespace(voice=SimpleNamespace(channel=channel))
            tracks = tuple(make_track(f"remove-{guild_id}-{index}") for index in range(3))
            state = bot.get_state(guild_id)
            state.voice = voice
            state.current = make_track(f"current-{guild_id}") if playing else None
            state.queue.extend(tracks)
            acknowledged = {"done": False}
            interaction = MagicMock(guild_id=guild_id, user=member)
            interaction.response.send_message = AsyncMock()
            interaction.response.is_done.side_effect = lambda: acknowledged["done"]
            interaction.followup.send = AsyncMock(return_value=None)

            async def defer_response(**_kwargs: object) -> None:
                acknowledged["done"] = True

            interaction.response.defer = AsyncMock(side_effect=defer_response)
            case = SimpleNamespace(
                guild_id=guild_id,
                state=state,
                voice=voice,
                member=member,
                tracks=tracks,
                interaction=interaction,
                acknowledged=acknowledged,
            )
            cases.append(case)
            return case

        def make_server_error(label: str) -> bot.discord.DiscordServerError:
            response = MagicMock(status=500, reason="Internal Server Error")
            return bot.discord.DiscordServerError(response, f"<html>{label}</html>")

        def discard_housekeeping(coroutine: object) -> None:
            coroutine.close()

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "update_control_panel", new_callable=AsyncMock) as update_panel,
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ) as create_housekeeping_task,
        ):
            try:
                invalid = make_case(336)
                not_found_message = "그 번호의 대기열 곡을 찾지 못했어요."
                with patch.object(
                    bot,
                    "send_ephemeral_response",
                    wraps=bot.send_ephemeral_response,
                ) as send_response:
                    await bot.remove_from_queue.callback(invalid.interaction, 0)

                    send_response.assert_awaited_once_with(
                        invalid.interaction,
                        not_found_message,
                    )
                    invalid.interaction.response.send_message.assert_awaited_once_with(
                        not_found_message,
                        ephemeral=True,
                    )
                    invalid.interaction.response.defer.assert_not_awaited()
                    invalid.interaction.followup.send.assert_not_awaited()
                    self.assertEqual(list(invalid.state.queue), list(invalid.tracks))
                    schedule_refill.assert_not_called()
                    update_panel.assert_not_awaited()

                create_housekeeping_task.reset_mock()

                stable = make_case(329)
                target = stable.tracks[1]
                ack_started = asyncio.Event()
                release_ack = asyncio.Event()
                release_events.append(release_ack)

                async def block_stable_defer(**_kwargs: object) -> None:
                    stable.acknowledged["done"] = True
                    ack_started.set()
                    await release_ack.wait()

                stable.interaction.response.defer.side_effect = block_stable_defer
                feedback_message = MagicMock()
                stable.interaction.followup.send.return_value = feedback_message
                expected_content = f"대기열에서 `{target.title}`을 삭제했어요."
                with patch.object(
                    bot,
                    "send_ephemeral_followup",
                    wraps=bot.send_ephemeral_followup,
                ) as send_followup:
                    stable_task = asyncio.create_task(
                        bot.remove_from_queue.callback(stable.interaction, 2)
                    )
                    callback_tasks.append(stable_task)
                    await asyncio.wait_for(ack_started.wait(), timeout=1)
                    self.assertEqual(list(stable.state.queue), list(stable.tracks))
                    schedule_refill.assert_not_called()
                    stable.interaction.followup.send.assert_not_awaited()

                    stable.state.queue.clear()
                    stable.state.queue.extend(
                        [stable.tracks[2], stable.tracks[0], target]
                    )
                    release_ack.set()
                    await asyncio.wait_for(stable_task, timeout=1)

                    stable.interaction.response.defer.assert_awaited_once_with(
                        ephemeral=True
                    )
                    send_followup.assert_awaited_once_with(
                        stable.interaction,
                        expected_content,
                        delete_after=bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
                    )
                    stable.interaction.followup.send.assert_awaited_once_with(
                        expected_content,
                        ephemeral=True,
                        wait=True,
                    )
                    self.assertEqual(
                        list(stable.state.queue),
                        [stable.tracks[2], stable.tracks[0]],
                    )
                    schedule_refill.assert_called_once_with(stable.guild_id)
                    update_panel.assert_not_awaited()
                    create_housekeeping_task.assert_called_once()
                    stable.interaction.response.send_message.assert_not_awaited()

                schedule_refill.reset_mock()
                update_panel.reset_mock()
                create_housekeeping_task.reset_mock()

                defer_failure = make_case(330)
                defer_error = make_server_error("remove defer failure")
                defer_failure.interaction.response.defer.side_effect = defer_error
                with self.assertRaises(bot.discord.DiscordServerError) as raised:
                    await bot.remove_from_queue.callback(defer_failure.interaction, 1)
                self.assertIs(raised.exception, defer_error)
                self.assertEqual(
                    list(defer_failure.state.queue), list(defer_failure.tracks)
                )
                schedule_refill.assert_not_called()
                update_panel.assert_not_awaited()
                defer_failure.interaction.followup.send.assert_not_awaited()

                defer_cancel = make_case(331)
                defer_started = asyncio.Event()
                release_defer = asyncio.Event()
                release_events.append(release_defer)

                async def block_cancelled_defer(**_kwargs: object) -> None:
                    defer_started.set()
                    await release_defer.wait()

                defer_cancel.interaction.response.defer.side_effect = block_cancelled_defer
                cancel_defer_task = asyncio.create_task(
                    bot.remove_from_queue.callback(defer_cancel.interaction, 1)
                )
                callback_tasks.append(cancel_defer_task)
                await asyncio.wait_for(defer_started.wait(), timeout=1)
                cancel_defer_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(cancel_defer_task, timeout=1)
                self.assertEqual(list(defer_cancel.state.queue), list(defer_cancel.tracks))
                schedule_refill.assert_not_called()
                update_panel.assert_not_awaited()
                defer_cancel.interaction.followup.send.assert_not_awaited()

                guard_specs = (
                    (
                        "voice replacement",
                        "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
                    ),
                    (
                        "member move",
                        "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
                    ),
                    ("target missing", "그 번호의 대기열 곡을 찾지 못했어요."),
                )
                for offset, (scenario, expected_message) in enumerate(guard_specs):
                    with self.subTest(scenario=scenario):
                        schedule_refill.reset_mock()
                        update_panel.reset_mock()
                        guarded = make_case(332 + offset)
                        target = guarded.tracks[0]

                        async def mutate_during_defer(
                            _scenario: str = scenario,
                            **_kwargs: object,
                        ) -> None:
                            guarded.acknowledged["done"] = True
                            if _scenario == "voice replacement":
                                replacement_voice = MagicMock(
                                    channel=guarded.voice.channel
                                )
                                replacement_voice.is_connected.return_value = True
                                guarded.state.voice = replacement_voice
                            elif _scenario == "member move":
                                guarded.member.voice.channel = object()
                            else:
                                bot.remove_queued_track_by_id(
                                    guarded.state,
                                    target.track_id,
                                )

                        guarded.interaction.response.defer.side_effect = mutate_during_defer
                        await bot.remove_from_queue.callback(guarded.interaction, 1)

                        guarded.interaction.response.defer.assert_awaited_once_with(
                            ephemeral=True
                        )
                        guarded.interaction.followup.send.assert_awaited_once_with(
                            expected_message,
                            ephemeral=True,
                            wait=True,
                        )
                        if scenario == "target missing":
                            self.assertEqual(
                                list(guarded.state.queue), list(guarded.tracks[1:])
                            )
                        else:
                            self.assertEqual(
                                list(guarded.state.queue), list(guarded.tracks)
                            )
                        schedule_refill.assert_not_called()
                        update_panel.assert_not_awaited()
                        guarded.interaction.response.send_message.assert_not_awaited()

                schedule_refill.reset_mock()
                update_panel.reset_mock()
                final_cancel = make_case(335, playing=True)
                followup_started = asyncio.Event()
                release_followup = asyncio.Event()
                release_events.append(release_followup)

                async def block_followup(*_args: object, **_kwargs: object) -> None:
                    followup_started.set()
                    await release_followup.wait()

                final_cancel.interaction.followup.send.side_effect = block_followup
                final_task = asyncio.create_task(
                    bot.remove_from_queue.callback(final_cancel.interaction, 1)
                )
                callback_tasks.append(final_task)
                await asyncio.wait_for(followup_started.wait(), timeout=1)
                self.assertEqual(
                    list(final_cancel.state.queue), list(final_cancel.tracks[1:])
                )
                schedule_refill.assert_called_once_with(final_cancel.guild_id)
                update_panel.assert_not_awaited()

                final_task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(final_task, timeout=1)
                update_panel.assert_awaited_once_with(
                    final_cancel.guild_id,
                    final_cancel.state,
                )
                self.assertEqual(
                    list(final_cancel.state.queue), list(final_cancel.tracks[1:])
                )
                final_cancel.interaction.response.defer.assert_awaited_once_with(
                    ephemeral=True
                )
            finally:
                for event in release_events:
                    event.set()
                for task in callback_tasks:
                    if not task.done():
                        task.cancel()
                if callback_tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*callback_tasks, return_exceptions=True),
                        timeout=1,
                    )
                for case in cases:
                    bot.cancel_autoplay_refill(case.state)
                    bot.cancel_empty_channel_disconnect(case.state)
                    bot.music_states.pop(case.guild_id, None)

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
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
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
                self.history = MagicMock()

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
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "get_control_message_id", return_value=message.id),
        ):
            result = await bot.update_control_panel(111, state, channel=channel)

        self.assertIs(result, message)
        channel.fetch_message.assert_awaited_once_with(message.id)
        channel.history.assert_not_called()
        channel.send.assert_not_awaited()
        message.edit.assert_awaited_once()

    def test_panel_history_match_requires_bot_author_title_and_controls(self) -> None:
        class Value:
            def __init__(self, **values: object) -> None:
                self.__dict__.update(values)

        panel = Value(
            author=Value(id=77),
            embeds=[Value(title="🎵 재생 대기 중")],
            components=[
                Value(children=[Value(custom_id=bot.AUTOPLAY_BUTTON_CUSTOM_ID)])
            ],
        )

        self.assertTrue(bot.is_music_control_panel_message(panel, 77))
        self.assertFalse(bot.is_music_control_panel_message(panel, 88))
        panel.interaction_metadata = Value()
        self.assertFalse(bot.is_music_control_panel_message(panel, 77))
        panel.interaction_metadata = None
        panel.embeds[0].title = "Added to queue"
        self.assertFalse(bot.is_music_control_panel_message(panel, 77))

    async def test_recovery_only_deletes_duplicate_bot_panels(self) -> None:
        class Guild:
            id = 777

        class Channel:
            id = 888
            guild = Guild()

            def __init__(self) -> None:
                self.fetch_message = AsyncMock()
                self.send = AsyncMock()
                self.messages = []
                self.history_limit = None
                self.history_called = False

            def history(self, *, limit: int | None):
                self.history_called = True
                self.history_limit = limit

                async def messages():
                    for message in self.messages:
                        yield message

                return messages()

        class Message:
            def __init__(
                self,
                message_id: int,
                channel: Channel,
                *,
                is_panel: bool,
            ) -> None:
                self.id = message_id
                self.channel = channel
                self.is_panel = is_panel
                self.edit = AsyncMock()
                self.delete = AsyncMock()

        channel = Channel()
        older = Message(100, channel, is_panel=True)
        newest = Message(200, channel, is_panel=True)
        user_request = Message(300, channel, is_panel=False)
        temporary_feedback = Message(150, channel, is_panel=False)
        channel.messages = [user_request, newest, temporary_feedback, older]
        channel.fetch_message.return_value = older
        state = bot.GuildMusicState()

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "get_control_message_id", return_value=None),
            patch.object(bot, "set_control_message_id") as save_message_id,
            patch.object(
                bot,
                "is_music_control_panel_message",
                side_effect=lambda message, _: message.is_panel,
            ),
        ):
            result = await bot.update_control_panel(
                777,
                state,
                channel=channel,
            )

        self.assertIs(result, newest)
        self.assertIs(state.control_message, newest)
        self.assertTrue(channel.history_called)
        self.assertEqual(channel.history_limit, bot.CONTROL_PANEL_HISTORY_LIMIT)
        channel.fetch_message.assert_not_awaited()
        channel.send.assert_not_awaited()
        older.delete.assert_awaited_once()
        user_request.delete.assert_not_awaited()
        temporary_feedback.delete.assert_not_awaited()
        newest.delete.assert_not_awaited()
        newest.edit.assert_awaited_once()
        save_message_id.assert_called_once_with(777, newest.id)

    async def test_startup_cleanup_keeps_latest_panel_and_deletes_everything_else(
        self,
    ) -> None:
        class Channel:
            id = 888

            def __init__(self) -> None:
                self.send = AsyncMock()
                self.messages = []
                self.history_limit = object()

            def history(self, *, limit: int | None):
                self.history_limit = limit

                async def messages():
                    for message in self.messages:
                        yield message

                return messages()

        class Message:
            def __init__(
                self,
                message_id: int,
                channel: Channel,
                *,
                is_panel: bool,
            ) -> None:
                self.id = message_id
                self.channel = channel
                self.is_panel = is_panel
                self.edit = AsyncMock()
                self.delete = AsyncMock()

        channel = Channel()
        older_panel = Message(100, channel, is_panel=True)
        newest_panel = Message(200, channel, is_panel=True)
        user_request = Message(300, channel, is_panel=False)
        temporary_feedback = Message(150, channel, is_panel=False)
        lyrics = Message(125, channel, is_panel=False)
        channel.messages = [
            user_request,
            newest_panel,
            temporary_feedback,
            lyrics,
            older_panel,
        ]
        state = bot.GuildMusicState(control_message=older_panel)
        bot.music_states[777] = state

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(
                bot,
                "is_music_control_panel_message",
                side_effect=lambda message, _: message.is_panel,
            ),
            patch.object(
                bot,
                "get_control_message_id",
                return_value=older_panel.id,
            ),
            patch.object(bot, "set_control_message_id") as save_message_id,
        ):
            result = await bot.update_control_panel(
                777,
                state,
                channel=channel,
                clean_channel=True,
            )

        self.assertIs(result, newest_panel)
        self.assertIsNone(channel.history_limit)
        self.assertIs(state.control_message, newest_panel)
        channel.send.assert_not_awaited()
        older_panel.delete.assert_awaited_once_with()
        user_request.delete.assert_awaited_once_with()
        temporary_feedback.delete.assert_awaited_once_with()
        lyrics.delete.assert_awaited_once_with()
        newest_panel.delete.assert_not_awaited()
        newest_panel.edit.assert_awaited_once()
        save_message_id.assert_called_once_with(777, newest_panel.id)

    async def test_startup_cleanup_without_panel_deletes_every_message(self) -> None:
        class Channel:
            id = 889

            def __init__(self) -> None:
                self.send = AsyncMock()
                self.messages = []
                self.history_limit = object()

            def history(self, *, limit: int | None):
                self.history_limit = limit

                async def messages():
                    for message in self.messages:
                        yield message

                return messages()

        first = MagicMock(id=1)
        first.delete = AsyncMock()
        second = MagicMock(id=2)
        second.delete = AsyncMock()
        channel = Channel()
        channel.messages = [first, second]
        state = bot.GuildMusicState()
        panel = MagicMock(id=333, channel=channel)
        channel.send.return_value = panel
        bot.music_states[778] = state

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(
                bot,
                "is_music_control_panel_message",
                return_value=False,
            ),
            patch.object(bot, "get_control_message_id", return_value=999),
            patch.object(bot, "set_control_message_id") as save_message_id,
        ):
            result = await bot.update_control_panel(
                778,
                state,
                channel=channel,
                clean_channel=True,
            )

        self.assertIs(result, panel)
        self.assertIs(state.control_message, panel)
        self.assertIsNone(channel.history_limit)
        first.delete.assert_awaited_once_with()
        second.delete.assert_awaited_once_with()
        channel.send.assert_awaited_once()
        save_message_id.assert_called_once_with(778, panel.id)

    async def test_startup_cleanup_runs_after_control_panel_restore(self) -> None:
        channel = MagicMock(id=889)
        guild = MagicMock(id=779)
        guild.get_channel.return_value = channel
        state = bot.GuildMusicState()

        with (
            patch.object(bot.bot._connection, "_guilds", {guild.id: guild}),
            patch.object(bot, "get_music_channel_id", return_value=channel.id),
            patch.object(bot, "get_state", return_value=state),
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ) as update_panel,
        ):
            await bot.restore_control_panels()

        update_panel.assert_awaited_once_with(
            guild.id,
            state,
            channel=channel,
            clean_channel=True,
        )

    async def test_restart_recovers_panel_when_saved_id_is_missing(self) -> None:
        class Guild:
            id = 778

        class Channel:
            id = 889
            guild = Guild()

            def __init__(self) -> None:
                self.fetch_message = AsyncMock()
                self.send = AsyncMock()
                self.messages = []
                self.history_limit = None

            def history(self, *, limit: int):
                self.history_limit = limit

                async def messages():
                    for message in self.messages:
                        yield message

                return messages()

        class Message:
            def __init__(
                self,
                message_id: int,
                channel: Channel,
                *,
                is_panel: bool,
            ) -> None:
                self.id = message_id
                self.channel = channel
                self.is_panel = is_panel
                self.edit = AsyncMock()
                self.delete = AsyncMock()

        channel = Channel()
        message = Message(300, channel, is_panel=True)
        unrelated = Message(301, channel, is_panel=False)
        channel.messages = [unrelated, message]
        state = bot.GuildMusicState()

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "get_control_message_id", return_value=None),
            patch.object(bot, "set_control_message_id") as save_message_id,
            patch.object(
                bot,
                "is_music_control_panel_message",
                side_effect=lambda candidate, _: candidate.is_panel,
            ),
        ):
            result = await bot.update_control_panel(778, state, channel=channel)

        self.assertIs(result, message)
        self.assertEqual(channel.history_limit, bot.CONTROL_PANEL_HISTORY_LIMIT)
        channel.fetch_message.assert_not_awaited()
        channel.send.assert_not_awaited()
        unrelated.delete.assert_not_awaited()
        message.edit.assert_awaited_once()
        save_message_id.assert_called_once_with(778, message.id)

    async def test_on_ready_restores_control_panels_only_once(self) -> None:
        with (
            patch.object(bot, "startup_initialized", False),
            patch.object(bot, "commands_synced", False),
            patch.object(bot, "startup_initialization_lock", asyncio.Lock()),
            patch.object(bot, "DEV_GUILD_ID", None),
            patch.object(bot, "load_music_channel_config") as load_config,
            patch.object(
                bot,
                "restore_control_panels",
                new=AsyncMock(),
            ) as restore_panels,
            patch.object(bot, "ffmpeg_is_available", return_value=True) as ffmpeg_check,
            patch.object(
                bot.bot.tree,
                "sync",
                new=AsyncMock(return_value=[]),
            ) as sync_commands,
        ):
            await bot.on_ready()
            await bot.on_ready()

        load_config.assert_called_once_with()
        restore_panels.assert_awaited_once_with()
        ffmpeg_check.assert_called_once_with()
        sync_commands.assert_awaited_once_with()

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
        member = MagicMock()
        member.voice = MagicMock(channel=MagicMock())
        enable_interaction = MagicMock(user=member)
        enable_interaction.response.defer = AsyncMock()

        with (
            patch.object(bot, "set_autoplay_enabled") as save_setting,
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(view, "edit_panel", new=AsyncMock()) as edit_panel,
        ):
            await button.callback(enable_interaction)

        self.assertTrue(state.autoplay_enabled)
        enable_interaction.response.defer.assert_awaited_once_with()
        save_setting.assert_called_once_with(guild_id, True)
        schedule_refill.assert_called_once_with(guild_id)
        edit_panel.assert_awaited_once_with(
            enable_interaction,
            refresh_canonical=True,
        )

        disable_interaction = MagicMock(user=member)
        disable_interaction.response.defer = AsyncMock()

        with (
            patch.object(bot, "set_autoplay_enabled") as save_setting,
            patch.object(bot, "cancel_autoplay_refill") as cancel_refill,
            patch.object(view, "edit_panel", new=AsyncMock()) as edit_panel,
        ):
            await button.callback(disable_interaction)

        self.assertFalse(state.autoplay_enabled)
        disable_interaction.response.defer.assert_awaited_once_with()
        save_setting.assert_called_once_with(guild_id, False)
        cancel_refill.assert_called_once_with(state)
        edit_panel.assert_awaited_once_with(
            disable_interaction,
            refresh_canonical=True,
        )

    async def test_autoplay_acknowledges_before_persistence_and_mutation(
        self,
    ) -> None:
        guild_id = 445
        state = bot.get_state(guild_id)
        state.current = make_track("seed")
        view = bot.MusicControlView(guild_id)
        button = next(
            item
            for item in view.children
            if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
        )
        acknowledged = False
        operation_order: list[str] = []
        edit_lock_states: list[bool] = []
        member = MagicMock()
        member.voice = MagicMock(channel=MagicMock())
        interaction = MagicMock(user=member)

        async def defer_response() -> None:
            nonlocal acknowledged
            self.assertFalse(state.autoplay_enabled)
            acknowledged = True
            operation_order.append("defer")

        def persist_setting(requested_guild_id: int, enabled: bool) -> None:
            self.assertTrue(acknowledged)
            self.assertEqual((requested_guild_id, enabled), (guild_id, True))
            operation_order.append("persist")

        def schedule_refill(requested_guild_id: int) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            operation_order.append("refill")

        async def edit_response(**_kwargs: object) -> None:
            edit_lock_states.append(state.control_panel_lock.locked())
            operation_order.append("edit")

        interaction.response.defer = AsyncMock(side_effect=defer_response)
        interaction.response.is_done.side_effect = lambda: acknowledged
        interaction.edit_original_response = AsyncMock(side_effect=edit_response)

        try:
            with (
                patch.object(
                    bot,
                    "set_autoplay_enabled",
                    side_effect=persist_setting,
                ) as save_setting,
                patch.object(
                    bot,
                    "schedule_autoplay_refill",
                    side_effect=schedule_refill,
                ) as schedule_autoplay_refill,
                patch.object(bot, "cancel_autoplay_refill") as cancel_refill,
            ):
                await button.callback(interaction)

            self.assertEqual(
                operation_order,
                ["defer", "persist", "refill", "edit"],
            )
            self.assertTrue(state.autoplay_enabled)
            interaction.response.defer.assert_awaited_once_with()
            save_setting.assert_called_once_with(guild_id, True)
            schedule_autoplay_refill.assert_called_once_with(guild_id)
            cancel_refill.assert_not_called()
            interaction.edit_original_response.assert_awaited_once()
            self.assertEqual(edit_lock_states, [True])
            edit_kwargs = interaction.edit_original_response.await_args.kwargs
            self.assertEqual(
                edit_kwargs["embed"].to_dict(),
                bot.make_player_embed(state.current, state).to_dict(),
            )
            edited_view = edit_kwargs["view"]
            self.assertIsInstance(edited_view, bot.MusicControlView)
            self.assertTrue(all(not item.disabled for item in edited_view.children))
            autoplay_button = next(
                item
                for item in edited_view.children
                if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
            )
            self.assertEqual(
                autoplay_button.style,
                bot.discord.ButtonStyle.success,
            )

            failure_guild_id = 446
            failure_state = bot.get_state(failure_guild_id)
            failure_state.current = make_track("failure-seed")
            failure_view = bot.MusicControlView(failure_guild_id)
            failure_button = next(
                item
                for item in failure_view.children
                if item.custom_id == bot.AUTOPLAY_BUTTON_CUSTOM_ID
            )
            failure_response = MagicMock(
                status=500,
                reason="Internal Server Error",
            )
            response_error = bot.discord.DiscordServerError(
                failure_response,
                "<html>temporary failure</html>",
            )
            failure_interaction = MagicMock()
            failure_interaction.response.defer = AsyncMock(
                side_effect=response_error
            )
            failure_interaction.edit_original_response = AsyncMock()

            with (
                patch.object(bot, "set_autoplay_enabled") as save_setting,
                patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
                patch.object(bot, "cancel_autoplay_refill") as cancel_refill,
                self.assertRaises(bot.discord.DiscordServerError) as raised,
            ):
                await failure_button.callback(failure_interaction)

            self.assertIs(raised.exception, response_error)
            self.assertFalse(failure_state.autoplay_enabled)
            failure_interaction.response.defer.assert_awaited_once_with()
            save_setting.assert_not_called()
            schedule_refill.assert_not_called()
            cancel_refill.assert_not_called()
            failure_interaction.edit_original_response.assert_not_awaited()
        finally:
            for cleanup_guild_id in (guild_id, 446):
                cleanup_state = bot.music_states.get(cleanup_guild_id)
                if cleanup_state is None:
                    continue
                autoplay_task = cleanup_state.autoplay_task
                bot.cancel_autoplay_refill(cleanup_state)
                if autoplay_task is not None:
                    await asyncio.wait_for(
                        asyncio.gather(autoplay_task, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(cleanup_guild_id, None)


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
                "extract_auto_tracks_from_seed",
                new=AsyncMock(return_value=[queued, seed, recent, fresh]),
            ) as extract,
            patch.object(bot, "extract_auto_tracks", new=AsyncMock()) as query_extract,
            patch.object(bot, "update_control_panel", new=AsyncMock()) as update_panel,
        ):
            await bot.refill_autoplay_queue(
                guild_id,
                state.playback_generation,
                seed,
            )

        self.assertEqual(list(state.queue), [queued, fresh])
        extract.assert_awaited_once()
        self.assertIs(extract.await_args.args[0], queued)
        self.assertEqual(
            extract.await_args.args[2],
            bot.AUTOPLAY_REFILL_CANDIDATES,
        )
        self.assertEqual(
            extract.await_args.kwargs["job_kind"],
            bot.YtdlJobKind.AUTOPLAY,
        )
        query_extract.assert_not_awaited()
        update_panel.assert_awaited_once_with(guild_id, state)

    async def test_refill_fills_empty_queue_to_two_tracks(self) -> None:
        guild_id = 559
        seed = make_track("seed")
        first = make_track("first")
        second = make_track("second")
        state = bot.get_state(guild_id)
        state.voice = self.Voice()
        state.current = seed
        state.autoplay_enabled = True

        with (
            patch.object(
                bot,
                "extract_auto_tracks_from_seed",
                new=AsyncMock(
                    side_effect=[
                        [seed, first],
                        [first, second],
                    ]
                ),
            ) as extract,
            patch.object(bot, "update_control_panel", new=AsyncMock()) as update_panel,
        ):
            await bot.refill_autoplay_queue(
                guild_id,
                state.playback_generation,
                seed,
            )

        self.assertEqual(list(state.queue), [first, second])
        self.assertEqual(extract.await_count, 2)
        self.assertIs(extract.await_args_list[0].args[0], seed)
        self.assertIs(extract.await_args_list[1].args[0], first)
        self.assertEqual(update_panel.await_count, 2)

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

        async def finish_current_during_search(
            *args: object,
            **kwargs: object,
        ) -> list[bot.Track]:
            state.current = None
            return [seed, fresh]

        with (
            patch.object(
                bot,
                "extract_auto_tracks_from_seed",
                side_effect=finish_current_during_search,
            ),
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
        queued = make_track("queued")
        fresh = make_track("fresh")
        state = bot.get_state(guild_id)
        state.voice = self.Voice()
        state.current = seed
        state.queue.append(queued)
        state.autoplay_enabled = True

        with (
            patch.object(
                bot,
                "extract_auto_tracks_from_seed",
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

        self.assertEqual(list(state.queue), [queued, fresh])
        self.assertEqual(extract.await_count, 2)
        sleep.assert_awaited_once_with(bot.AUTOPLAY_RETRY_DELAYS_SECONDS[0])

    def test_autoplay_retry_delay_increases_and_caps(self) -> None:
        self.assertEqual(
            [bot.get_autoplay_retry_delay(index) for index in range(7)],
            [60, 120, 300, 900, 1800, 1800, 1800],
        )

    async def test_only_one_refill_task_runs_and_target_is_two_tracks(self) -> None:
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

        bot.stop_playback(state, 0)
        await asyncio.sleep(0)

        self.assertTrue(state.autoplay_enabled)
        self.assertIsNone(state.autoplay_task)


class HousekeepingTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.housekeeping_tasks.clear()
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        bot.bot._discord_close_task = None

    async def asyncTearDown(self) -> None:
        tasks = list(bot.housekeeping_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bot.housekeeping_tasks.clear()
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        discord_close_task = bot.bot._discord_close_task
        if discord_close_task is not None and not discord_close_task.done():
            discord_close_task.cancel()
            await asyncio.gather(discord_close_task, return_exceptions=True)
        bot.bot._discord_close_task = None

    async def test_housekeeping_task_is_removed_after_completion(self) -> None:
        completed = asyncio.Event()

        async def work() -> None:
            completed.set()

        task = bot.create_housekeeping_task(work())

        self.assertIsNotNone(task)
        self.assertIn(task, bot.housekeeping_tasks)
        await completed.wait()
        await task
        await asyncio.sleep(0)

        self.assertNotIn(task, bot.housekeeping_tasks)

    async def test_shutdown_removes_done_task_before_done_callback_runs(
        self,
    ) -> None:
        async def work() -> None:
            return None

        task = asyncio.create_task(work())
        await task
        bot.housekeeping_tasks.add(task)
        task.add_done_callback(bot.finish_housekeeping_task)

        await bot.shutdown_housekeeping_tasks()

        self.assertFalse(bot.housekeeping_tasks)

    async def test_shutdown_rejects_new_housekeeping_task(self) -> None:
        coroutine = MagicMock()
        bot.begin_bot_shutdown()

        task = bot.create_housekeeping_task(coroutine)

        self.assertIsNone(task)
        coroutine.close.assert_called_once_with()
        self.assertFalse(bot.housekeeping_tasks)

    async def test_close_cancels_delayed_housekeeping_task(self) -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()
        order: list[str] = []

        async def work() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                order.append("housekeeping")
                cancelled.set()
                raise

        async def base_close(_self: object) -> None:
            order.append("discord")

        task = bot.create_housekeeping_task(work())
        await started.wait()

        with (
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot, "shutdown_voice_operations", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_operations", new=AsyncMock()),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot, "shutdown_lyrics_executor", new=AsyncMock()),
            patch.object(
                bot,
                "restore_control_panels",
                new=AsyncMock(),
            ) as restore_control_panels,
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            await bot.MusicBot.close(bot.bot)

        self.assertTrue(cancelled.is_set())
        self.assertTrue(task.cancelled())
        self.assertFalse(bot.housekeeping_tasks)
        self.assertEqual(order, ["housekeeping", "discord"])
        restore_control_panels.assert_not_awaited()

    async def test_housekeeping_exception_is_retrieved(self) -> None:
        async def fail() -> None:
            raise RuntimeError("delete failed")

        with patch.object(bot.logger, "warning") as warning:
            task = bot.create_housekeeping_task(fail())
            results = await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)

        self.assertIsInstance(results[0], RuntimeError)
        self.assertFalse(bot.housekeeping_tasks)
        warning.assert_called_once()
        self.assertIn("Housekeeping task failed", warning.call_args.args[0])

    async def test_concurrent_close_does_not_double_cancel_housekeeping(
        self,
    ) -> None:
        started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release = asyncio.Event()
        cancellation_count = 0
        base_close_calls = 0

        async def work() -> None:
            nonlocal cancellation_count
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_count += 1
                cancellation_seen.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    cancellation_count += 1
                    raise
                raise

        async def base_close(_self: object) -> None:
            nonlocal base_close_calls
            base_close_calls += 1

        task = bot.create_housekeeping_task(work())
        await started.wait()

        with (
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot, "shutdown_voice_operations", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_operations", new=AsyncMock()),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot, "shutdown_lyrics_executor", new=AsyncMock()),
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            first = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await cancellation_seen.wait()
            second = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await asyncio.sleep(0)

            self.assertFalse(first.done())
            self.assertFalse(second.done())
            release.set()
            await asyncio.gather(first, second)

        self.assertTrue(task.cancelled())
        self.assertEqual(cancellation_count, 1)
        self.assertEqual(base_close_calls, 1)
        self.assertFalse(bot.housekeeping_tasks)


class AuxiliaryWorkerLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.housekeeping_tasks.clear()
        bot.auxiliary_operation_tasks.clear()
        bot.auxiliary_worker_tasks.clear()
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        bot.lyrics_executor_shutdown_task = None
        bot.bot_shutdown_started = False
        bot.voice_operation_tasks.clear()
        bot.bot._discord_close_task = None
        bot.music_states.pop(991, None)
        bot.music_states.pop(992, None)
        bot.music_states.pop(993, None)
        bot.music_states.pop(994, None)

    async def asyncTearDown(self) -> None:
        tasks = list(
            bot.housekeeping_tasks
            | bot.auxiliary_operation_tasks
            | bot.auxiliary_worker_tasks
            | bot.voice_operation_tasks
        )
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bot.housekeeping_tasks.clear()
        bot.auxiliary_operation_tasks.clear()
        bot.auxiliary_worker_tasks.clear()
        bot.voice_operation_tasks.clear()
        bot.auxiliary_workers_closing = False
        shutdown_task = bot.lyrics_executor_shutdown_task
        if shutdown_task is not None and not shutdown_task.done():
            shutdown_task.cancel()
            await asyncio.gather(shutdown_task, return_exceptions=True)
        bot.lyrics_executor_closing = False
        bot.lyrics_executor_shutdown_task = None
        bot.bot_shutdown_started = False
        discord_close_task = bot.bot._discord_close_task
        if discord_close_task is not None and not discord_close_task.done():
            discord_close_task.cancel()
            await asyncio.gather(discord_close_task, return_exceptions=True)
        bot.bot._discord_close_task = None
        bot.music_states.pop(991, None)
        bot.music_states.pop(992, None)
        bot.music_states.pop(993, None)
        bot.music_states.pop(994, None)

    async def test_shutdown_waits_for_running_auxiliary_worker(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def work() -> str:
            started.set()
            await release.wait()
            return "done"

        worker = bot.track_auxiliary_worker(asyncio.create_task(work()))
        await started.wait()
        shutdown = asyncio.create_task(bot.shutdown_auxiliary_workers())
        await asyncio.sleep(0)

        self.assertFalse(shutdown.done())
        self.assertIn(worker, bot.auxiliary_worker_tasks)
        release.set()
        await shutdown

        self.assertTrue(worker.done())
        self.assertFalse(bot.auxiliary_worker_tasks)

    async def test_shutdown_removes_done_worker_before_done_callback_runs(
        self,
    ) -> None:
        completed = asyncio.Event()

        async def work() -> None:
            completed.set()

        worker = bot.track_auxiliary_worker(asyncio.create_task(work()))
        await completed.wait()

        self.assertTrue(worker.done())
        self.assertIn(worker, bot.auxiliary_worker_tasks)

        original_wait = bot.wait_for_task_completion_despite_cancellation
        wait_count = 0

        async def wait_once(task: asyncio.Task) -> tuple[bool, BaseException | None]:
            nonlocal wait_count
            wait_count += 1
            if wait_count > 1:
                raise AssertionError("completed auxiliary worker was revisited")
            return await original_wait(task)

        with patch.object(
            bot,
            "wait_for_task_completion_despite_cancellation",
            new=wait_once,
        ):
            await bot.shutdown_auxiliary_workers()

        self.assertEqual(wait_count, 1)
        self.assertFalse(bot.auxiliary_worker_tasks)

    async def test_cancelled_auxiliary_shutdown_still_waits_for_worker(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        worker_cancelled = asyncio.Event()

        async def work() -> str:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                worker_cancelled.set()
                raise
            return "done"

        worker = bot.track_auxiliary_worker(asyncio.create_task(work()))
        await started.wait()
        shutdown = asyncio.create_task(bot.shutdown_auxiliary_workers())
        await asyncio.sleep(0)
        shutdown.cancel()
        for _ in range(3):
            await asyncio.sleep(0)

        self.assertFalse(shutdown.done())
        self.assertFalse(worker_cancelled.is_set())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await shutdown

        self.assertTrue(worker.done())
        self.assertFalse(bot.auxiliary_worker_tasks)

    async def test_lyrics_executor_shutdown_is_idempotent(self) -> None:
        calls: list[tuple[bool, bool]] = []

        class FakeExecutor:
            def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
                calls.append((wait, cancel_futures))

        async def run_inline(
            function: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            return function(*args, **kwargs)

        with (
            patch.object(bot, "lyrics_executor", FakeExecutor()),
            patch.object(bot.asyncio, "to_thread", side_effect=run_inline),
        ):
            await bot.shutdown_lyrics_executor()
            await bot.shutdown_lyrics_executor()

        self.assertEqual(calls, [(True, True)])

    async def test_concurrent_executor_shutdown_callers_share_completion(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[bool, bool]] = []

        class FakeExecutor:
            def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
                calls.append((wait, cancel_futures))

        async def delayed_to_thread(
            function: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            started.set()
            await release.wait()
            return function(*args, **kwargs)

        with (
            patch.object(bot, "lyrics_executor", FakeExecutor()),
            patch.object(bot.asyncio, "to_thread", side_effect=delayed_to_thread),
        ):
            first = asyncio.create_task(bot.shutdown_lyrics_executor())
            await started.wait()
            second = asyncio.create_task(bot.shutdown_lyrics_executor())
            await asyncio.sleep(0)

            self.assertFalse(first.done())
            self.assertFalse(second.done())
            release.set()
            await asyncio.gather(first, second)

        self.assertEqual(calls, [(True, True)])

    async def test_cancelled_shutdown_waits_before_later_caller_returns(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls: list[tuple[bool, bool]] = []

        class FakeExecutor:
            def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
                calls.append((wait, cancel_futures))

        async def delayed_to_thread(
            function: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            started.set()
            await release.wait()
            return function(*args, **kwargs)

        with (
            patch.object(bot, "lyrics_executor", FakeExecutor()),
            patch.object(bot.asyncio, "to_thread", side_effect=delayed_to_thread),
        ):
            first = asyncio.create_task(bot.shutdown_lyrics_executor())
            await started.wait()
            first.cancel()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(first.done())

            second = asyncio.create_task(bot.shutdown_lyrics_executor())
            await asyncio.sleep(0)
            self.assertFalse(second.done())
            release.set()
            results = await asyncio.gather(
                first,
                second,
                return_exceptions=True,
            )

        self.assertEqual(calls, [(True, True)])
        self.assertIsInstance(results[0], asyncio.CancelledError)
        self.assertIsNone(results[1])

    async def test_run_lyrics_job_rejects_work_after_shutdown_begins(self) -> None:
        function = MagicMock(return_value="lyrics")
        bot.begin_lyrics_executor_shutdown()

        with self.assertRaises(asyncio.CancelledError):
            await bot.run_lyrics_job(function)

        function.assert_not_called()

    async def test_lyrics_executor_shutdown_propagates_worker_error(self) -> None:
        async def failing_to_thread(
            function: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            raise RuntimeError("executor shutdown failed")

        with patch.object(
            bot.asyncio,
            "to_thread",
            side_effect=failing_to_thread,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "executor shutdown failed",
            ):
                await bot.shutdown_lyrics_executor()

    async def test_shutdown_cancels_delayed_noncritical_lyrics_work(self) -> None:
        guild_id = 991
        state = bot.get_state(guild_id)
        started = asyncio.Event()
        lyrics_job = AsyncMock()

        async def delayed_work() -> None:
            started.set()
            await asyncio.Event().wait()
            await bot.run_lyrics_job(lambda: "lyrics")

        state.noncritical_task = asyncio.create_task(delayed_work())
        await started.wait()
        with patch.object(bot, "run_lyrics_job", new=lyrics_job):
            await bot.cancel_music_background_tasks_for_shutdown()

        self.assertIsNone(state.noncritical_task)
        lyrics_job.assert_not_awaited()
        bot.music_states.pop(guild_id, None)

    async def test_shutdown_collects_background_task_rescheduled_in_finally(self) -> None:
        guild_id = 992
        state = bot.get_state(guild_id)
        started = asyncio.Event()
        replacements: list[asyncio.Task[None]] = []

        async def replacement() -> None:
            await asyncio.Event().wait()

        async def initial() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                task = asyncio.create_task(replacement())
                replacements.append(task)
                state.autoplay_task = task

        state.autoplay_task = asyncio.create_task(initial())
        await started.wait()
        await bot.cancel_music_background_tasks_for_shutdown()

        self.assertEqual(len(replacements), 1)
        self.assertTrue(replacements[0].cancelled())
        self.assertIsNone(state.autoplay_task)
        bot.music_states.pop(guild_id, None)

    async def test_cancelled_close_waits_for_lyrics_executor_shutdown(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []
        calls: list[tuple[bool, bool]] = []

        class FakeExecutor:
            def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
                calls.append((wait, cancel_futures))
                order.append("executor")

        async def delayed_to_thread(
            function: object,
            *args: object,
            **kwargs: object,
        ) -> object:
            started.set()
            await release.wait()
            return function(*args, **kwargs)

        async def base_close(_self: object) -> None:
            order.append("super")

        with (
            patch.object(bot, "lyrics_executor", FakeExecutor()),
            patch.object(bot.asyncio, "to_thread", side_effect=delayed_to_thread),
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            close_task = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await started.wait()
            close_task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(close_task.done())
            self.assertEqual(order, [])
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await close_task

        self.assertEqual(order, ["executor", "super"])
        self.assertEqual(calls, [(True, True)])

    async def test_repeated_cancellation_waits_for_discord_close(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        base_cancelled = asyncio.Event()
        calls = 0

        async def base_close(_self: object) -> None:
            nonlocal calls
            calls += 1
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                base_cancelled.set()
                raise

        with (
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot, "shutdown_voice_operations", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_operations", new=AsyncMock()),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot, "shutdown_lyrics_executor", new=AsyncMock()),
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            close_task = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await started.wait()
            close_task.cancel()
            await asyncio.sleep(0)
            close_task.cancel()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(close_task.done())
            self.assertFalse(base_cancelled.is_set())
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await close_task

        self.assertEqual(calls, 1)

    async def test_concurrent_close_callers_share_discord_close(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def base_close(_self: object) -> None:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()

        with (
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot, "shutdown_voice_operations", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_operations", new=AsyncMock()),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot, "shutdown_lyrics_executor", new=AsyncMock()),
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            first = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await started.wait()
            second = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await asyncio.sleep(0)

            self.assertFalse(first.done())
            self.assertFalse(second.done())
            release.set()
            await asyncio.gather(first, second)

        self.assertEqual(calls, 1)

    async def test_autoplay_finalizer_cannot_reschedule_during_shutdown(self) -> None:
        guild_id = 993
        state = bot.get_state(guild_id)
        started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release = asyncio.Event()
        results: list[tuple[asyncio.Task[None] | None, bool]] = []

        async def autoplay_task() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()
            finally:
                if state.autoplay_task is asyncio.current_task():
                    state.autoplay_task = None
                    results.append(bot.schedule_autoplay_refill(guild_id))

        state.autoplay_task = asyncio.create_task(autoplay_task())
        await started.wait()
        bot.begin_bot_shutdown()
        cleanup = asyncio.create_task(
            bot.cancel_music_background_tasks_for_shutdown()
        )
        await cancellation_seen.wait()
        release.set()
        await cleanup

        self.assertEqual(results, [(None, False)])
        self.assertIsNone(state.autoplay_task)

    async def test_shutdown_gate_rejects_new_managed_tasks(self) -> None:
        guild_id = 993
        state = bot.get_state(guild_id)
        track = make_track("shutdown-gate")
        state.current = track
        state.autoplay_enabled = True
        message = MagicMock(id=1234)

        bot.begin_bot_shutdown()

        self.assertEqual(bot.schedule_play_next(guild_id), (None, False))
        self.assertEqual(
            bot.schedule_play_next_after_current(
                guild_id,
                state.playback_generation,
            ),
            (None, False),
        )
        self.assertEqual(
            bot.schedule_noncritical_tasks(guild_id, track),
            (None, False),
        )
        self.assertEqual(
            bot.schedule_autoplay_refill(guild_id),
            (None, False),
        )
        self.assertEqual(
            bot.schedule_lyrics_publish(guild_id, track),
            (None, False),
        )
        self.assertIsNone(
            bot.schedule_queue_message_cleanup(state, message, 30)
        )

        self.assertIsNone(state.advance_task)
        self.assertIsNone(state.noncritical_task)
        self.assertIsNone(state.autoplay_task)
        self.assertIsNone(state.lyrics_task)
        self.assertFalse(state.queue_cleanup_tasks)

        with patch.object(
            bot.ytdl_scheduler,
            "submit",
            new=AsyncMock(),
        ) as submit:
            with self.assertRaises(asyncio.CancelledError):
                await bot.extract_ytdl_info(
                    bot.YTDL_SEARCH_OPTIONS,
                    "ytsearch1:closing",
                    "closing",
                    job_kind=bot.YtdlJobKind.AUTOPLAY,
                    use_cache=False,
                )

        submit.assert_not_awaited()

    async def test_inflight_advance_cannot_schedule_work_during_shutdown(self) -> None:
        guild_id = 994
        state = bot.get_state(guild_id)
        track = make_track("late-advance")
        state.current = track
        started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release = asyncio.Event()
        scheduling_result: list[tuple[asyncio.Task[None] | None, bool]] = []

        async def inflight_advance() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release.wait()
            scheduling_result.append(
                bot.schedule_noncritical_tasks(guild_id, track)
            )

        state.advance_task = asyncio.create_task(inflight_advance())
        await started.wait()
        bot.begin_bot_shutdown()
        cleanup = asyncio.create_task(
            bot.cancel_music_background_tasks_for_shutdown()
        )
        await cancellation_seen.wait()

        self.assertFalse(cleanup.done())
        release.set()
        await cleanup

        self.assertEqual(scheduling_result, [(None, False)])
        self.assertIsNone(state.advance_task)
        self.assertIsNone(state.noncritical_task)

    async def test_shutdown_finishes_with_no_pending_guild_tasks(self) -> None:
        guild_id = 993
        state = bot.get_state(guild_id)

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        state.advance_task = asyncio.create_task(wait_forever())
        state.pending_advance_task = state.advance_task
        state.pending_advance_generation = state.playback_generation
        state.noncritical_task = asyncio.create_task(wait_forever())
        state.autoplay_task = asyncio.create_task(wait_forever())
        state.lyrics_task = asyncio.create_task(wait_forever())
        state.empty_channel_task = asyncio.create_task(wait_forever())
        state.queue_cleanup_tasks[99] = asyncio.create_task(wait_forever())
        await asyncio.sleep(0)

        bot.begin_bot_shutdown()
        await bot.cancel_music_background_tasks_for_shutdown()

        self.assertIsNone(state.advance_task)
        self.assertIsNone(state.pending_advance_task)
        self.assertIsNone(state.noncritical_task)
        self.assertIsNone(state.autoplay_task)
        self.assertIsNone(state.lyrics_task)
        self.assertIsNone(state.empty_channel_task)
        self.assertFalse(state.queue_cleanup_tasks)

    async def test_shutdown_invalidates_generation_before_voice_stop(self) -> None:
        guild_id = 994
        state = bot.get_state(guild_id)
        old_generation = state.playback_generation
        observed_generations: list[int] = []
        scheduling_results: list[
            tuple[asyncio.Task[None] | None, bool]
        ] = []

        class Voice:
            @staticmethod
            def is_playing() -> bool:
                return True

            @staticmethod
            def is_paused() -> bool:
                return False

            @staticmethod
            def stop() -> None:
                observed_generations.append(state.playback_generation)
                scheduling_results.append(
                    bot.schedule_play_next_after_current(
                        guild_id,
                        old_generation,
                    )
                )

        state.voice = Voice()
        bot.begin_bot_shutdown()
        await bot.cancel_music_background_tasks_for_shutdown()

        self.assertEqual(observed_generations, [old_generation + 1])
        self.assertEqual(scheduling_results, [(None, False)])
        self.assertTrue(state.stop_requested)

    async def test_closing_during_auxiliary_rate_wait_starts_no_worker(self) -> None:
        wait_started = asyncio.Event()
        release_wait = asyncio.Event()
        semaphore = asyncio.Semaphore(1)
        to_thread = AsyncMock(return_value=[])

        async def interval_wait() -> None:
            wait_started.set()
            await release_wait.wait()

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                bot,
                "wait_for_youtube_music_interval",
                side_effect=interval_wait,
            ),
        ):
            search = asyncio.create_task(bot.search_youtube_music("closing"))
            await wait_started.wait()
            bot.begin_auxiliary_worker_shutdown()
            release_wait.set()
            with self.assertRaises(RuntimeError):
                await search

        to_thread.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)

    async def test_shutdown_waits_for_youtube_music_pre_worker_operation(self) -> None:
        wait_started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release_wait = asyncio.Event()
        semaphore = asyncio.Semaphore(1)
        to_thread = AsyncMock(return_value=[])

        async def interval_wait() -> None:
            wait_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release_wait.wait()

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                bot,
                "wait_for_youtube_music_interval",
                side_effect=interval_wait,
            ),
        ):
            search = asyncio.create_task(
                bot.search_youtube_music("shutdown waiter")
            )
            await wait_started.wait()
            bot.begin_bot_shutdown()
            shutdown = asyncio.create_task(
                bot.shutdown_auxiliary_operations()
            )
            await cancellation_seen.wait()

            self.assertFalse(shutdown.done())
            self.assertEqual(semaphore._value, 0)
            release_wait.set()
            results = await asyncio.gather(search, return_exceptions=True)
            await shutdown

        self.assertIsInstance(results[0], RuntimeError)
        to_thread.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)
        self.assertFalse(bot.auxiliary_operation_tasks)

    async def test_shutdown_waits_for_subtitle_pre_worker_operation(self) -> None:
        wait_started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release_wait = asyncio.Event()
        semaphore = asyncio.Semaphore(1)
        lyrics_job = AsyncMock(return_value="lyrics")
        track = make_track("subtitle-shutdown")

        async def interval_wait() -> None:
            wait_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_seen.set()
                await release_wait.wait()

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(bot, "run_lyrics_job", new=lyrics_job),
            patch.object(
                bot,
                "wait_for_youtube_subtitle_interval",
                side_effect=interval_wait,
            ),
        ):
            subtitle = asyncio.create_task(
                bot.get_selected_youtube_subtitle(
                    track,
                    ("ko", "json3", "https://example.test/subtitle"),
                    purpose="shutdown",
                )
            )
            await wait_started.wait()
            bot.begin_bot_shutdown()
            shutdown = asyncio.create_task(
                bot.shutdown_auxiliary_operations()
            )
            await cancellation_seen.wait()

            self.assertFalse(shutdown.done())
            self.assertEqual(semaphore._value, 0)
            release_wait.set()
            results = await asyncio.gather(subtitle, return_exceptions=True)
            await shutdown

        self.assertIsInstance(results[0], RuntimeError)
        lyrics_job.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)
        self.assertFalse(bot.auxiliary_operation_tasks)


class YouTubeMusicProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.youtube_music_cache.clear()
        bot.youtube_music_client = None
        bot.youtube_music_last_request_started_at = 0.0
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def asyncTearDown(self) -> None:
        bot.youtube_music_cache.clear()
        bot.youtube_music_client = None
        bot.youtube_music_last_request_started_at = 0.0
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def test_repeated_music_query_uses_cache(self) -> None:
        payload = [
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
            }
        ]
        to_thread = AsyncMock(return_value=payload)

        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(bot, "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(bot, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await bot.search_youtube_music("でいねいめいめい")
            first[0]["title"] = "caller mutation"
            second = await bot.search_youtube_music("でいねいめいめい")

        to_thread.assert_awaited_once()
        self.assertEqual(second[0]["title"], "泥濘鳴鳴")

    async def test_empty_music_results_are_cached(self) -> None:
        to_thread = AsyncMock(return_value=[])

        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(bot, "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(bot, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await bot.search_youtube_music("missing song")
            second = await bot.search_youtube_music("missing song")

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        to_thread.assert_awaited_once()

    async def test_disabled_music_search_does_not_start_worker(self) -> None:
        to_thread = AsyncMock()

        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", False),
        ):
            results = await bot.search_youtube_music("sample")

        self.assertEqual(results, [])
        to_thread.assert_not_awaited()

    async def test_music_search_uses_its_own_rate_limiter(self) -> None:
        to_thread = AsyncMock(return_value=[])

        with (
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                bot,
                "wait_for_youtube_music_interval",
                new=AsyncMock(),
            ) as music_wait,
            patch.object(
                music_ytdl,
                "wait_for_ytdl_interval",
                new=AsyncMock(),
            ) as ytdl_wait,
        ):
            await bot.search_youtube_music("independent limiter")

        music_wait.assert_awaited_once_with()
        ytdl_wait.assert_not_awaited()

    async def test_music_search_rechecks_circuit_after_rate_limit_wait(self) -> None:
        semaphore = asyncio.Semaphore(1)
        to_thread = AsyncMock(return_value=[])

        async def open_circuit_during_wait() -> None:
            music_ytdl.youtube_circuit_open_until = music_ytdl.time.monotonic() + 60
            music_ytdl.youtube_circuit_reason = "test circuit"

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                bot,
                "wait_for_youtube_music_interval",
                side_effect=open_circuit_during_wait,
            ),
            self.assertRaises(music_ytdl.YouTubeCircuitOpenError),
        ):
            await bot.search_youtube_music("circuit opens while waiting")

        to_thread.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)


class LocalMusicTestModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_audio_mode_never_calls_ytdl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "test-tone.ogg"
            audio_path.write_bytes(b"test audio fixture")
            mode = LocalMusicMode(audio_path, bulk_tracks=2)

            with patch.object(
                bot,
                "extract_ytdl_info",
                new=AsyncMock(),
            ) as extract:
                single = await mode.extract_track("test song", "tester")
                bulk = await mode.extract_tracks("test album", "tester", "album")
                auto = await mode.extract_auto_tracks("test auto", "tester", 3)

        extract.assert_not_awaited()
        self.assertEqual(single.source_url, str(audio_path.resolve()))
        self.assertEqual(single.stream_url, str(audio_path))
        self.assertEqual(len(bulk), 2)
        self.assertEqual(len(auto), 3)
        self.assertEqual(len({bot.normalize_track_key(track) for track in auto}), 3)


class QueueRangeDeleteViewTests(unittest.IsolatedAsyncioTestCase):
    def set_same_voice(
        self,
        state: bot.GuildMusicState,
        *interactions: MagicMock,
    ) -> MagicMock:
        channel = MagicMock()
        voice = MagicMock(channel=channel)
        voice.is_connected.return_value = True
        state.voice = voice
        member = MagicMock()
        member.voice = MagicMock(channel=channel)
        for interaction in interactions:
            interaction.user = member
        return voice

    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_queue_message_cleanups(state)
        await asyncio.sleep(0)
        bot.music_states.clear()

    async def test_view_has_two_selects_and_disabled_confirm_button(self) -> None:
        guild_id = 987
        state = bot.get_state(guild_id)
        state.queue.extend([make_track("first"), make_track("second")])

        view = bot.QueueRangeDeleteView(guild_id)
        selects = [
            item for item in view.children if isinstance(item, bot.discord.ui.Select)
        ]

        self.assertEqual(len(selects), 2)
        self.assertIn("시작", selects[0].placeholder)
        self.assertIn("끝", selects[1].placeholder)
        self.assertTrue(view.confirm_button.disabled)

    async def test_boundary_selection_resets_expiry_only_after_response(self) -> None:
        guild_id = 996
        tracks = [make_track("first"), make_track("second"), make_track("third")]
        state = bot.get_state(guild_id)
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        start = next(
            item
            for item in view.children
            if isinstance(item, bot.QueueRangeBoundarySelect)
            and item.boundary == "start"
        )
        interaction = MagicMock(message=MagicMock(id=997))
        operation_order: list[str] = []
        interaction.response.defer = AsyncMock(
            side_effect=lambda: operation_order.append("defer")
        )
        interaction.edit_original_response = AsyncMock(
            side_effect=lambda **_kwargs: operation_order.append("edit")
        )

        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
            side_effect=lambda *_args: operation_order.append("cleanup"),
        ) as schedule_cleanup:
            start._values = [tracks[0].track_id]
            await start.callback(interaction)

            self.assertEqual(operation_order, ["defer", "edit", "cleanup"])
            expected_cleanup = (
                state,
                interaction.message,
                bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
            )
            self.assertEqual(schedule_cleanup.call_args.args, expected_cleanup)

            schedule_cleanup.reset_mock()
            failed_view = bot.QueueRangeDeleteView(guild_id)
            failed_start = next(
                item
                for item in failed_view.children
                if getattr(item, "boundary", None) == "start"
            )
            failed_start._values = [tracks[1].track_id]
            failed_interaction = MagicMock(message=MagicMock(id=998))
            failed_interaction.response.defer = AsyncMock()
            response = MagicMock(status=500, reason="Internal Server Error")
            response_error = bot.discord.DiscordServerError(
                response,
                "<html>temporary failure</html>",
            )
            failed_interaction.edit_original_response = AsyncMock(
                side_effect=response_error
            )

            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await failed_start.callback(failed_interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(view.start_track_id, tracks[0].track_id)
        self.assertEqual(
            [option.value for option in start.options if option.default],
            [tracks[0].track_id],
        )
        self.assertTrue(view.confirm_button.disabled)
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        failed_interaction.response.defer.assert_awaited_once_with()
        failed_interaction.edit_original_response.assert_awaited_once()
        schedule_cleanup.assert_not_called()

    async def test_range_boundary_responses_are_serialized_from_live_state(
        self,
    ) -> None:
        def make_case(guild_id: int):
            tracks = [make_track("first"), make_track("second"), make_track("third")]
            state = bot.get_state(guild_id)
            state.queue.extend(tracks)
            view = bot.QueueRangeDeleteView(guild_id)
            start = next(
                item
                for item in view.children
                if isinstance(item, bot.QueueRangeBoundarySelect)
                and item.boundary == "start"
            )
            end = next(
                item
                for item in view.children
                if isinstance(item, bot.QueueRangeBoundarySelect)
                and item.boundary == "end"
            )
            start._values = [tracks[0].track_id]
            end._values = [tracks[2].track_id]
            return state, tracks, view, start, end

        def render_snapshot(
            state: bot.GuildMusicState,
            view: bot.QueueRangeDeleteView,
            start: bot.QueueRangeBoundarySelect,
            end: bot.QueueRangeBoundarySelect,
            kwargs: dict[str, object],
        ) -> tuple[object, ...]:
            return (
                kwargs["content"],
                kwargs["embed"].to_dict(),
                view.start_track_id,
                view.end_track_id,
                tuple(option.value for option in start.options if option.default),
                tuple(option.value for option in end.options if option.default),
                view.confirm_button.disabled,
            )

        def expected_snapshot(
            state: bot.GuildMusicState,
            tracks: list[bot.Track],
            view: bot.QueueRangeDeleteView,
        ) -> tuple[object, ...]:
            return (
                view.make_selection_content(state),
                bot.make_queue_embed(state).to_dict(),
                tracks[0].track_id,
                tracks[2].track_id,
                (tracks[0].track_id,),
                (tracks[2].track_id,),
                False,
            )

        state, tracks, view, start, end = make_case(997)
        first_edit_started = asyncio.Event()
        second_deferred = asyncio.Event()
        release_first_edit = asyncio.Event()
        operations: list[str] = []
        remote_snapshots: list[tuple[object, ...]] = []
        edit_lock_states: list[bool] = []
        start_interaction = MagicMock(message=MagicMock(id=1001))
        end_interaction = MagicMock(message=MagicMock(id=1002))

        async def defer_start() -> None:
            operations.append("start-defer")

        async def defer_end() -> None:
            operations.append("end-defer")
            second_deferred.set()

        async def edit_start(**kwargs: object) -> None:
            operations.append("start-edit")
            edit_lock_states.append(view.interaction_lock.locked())
            snapshot = render_snapshot(state, view, start, end, kwargs)
            first_edit_started.set()
            await release_first_edit.wait()
            remote_snapshots.append(snapshot)

        async def edit_end(**kwargs: object) -> None:
            operations.append("end-edit")
            edit_lock_states.append(view.interaction_lock.locked())
            remote_snapshots.append(
                render_snapshot(state, view, start, end, kwargs)
            )

        start_interaction.response.defer = AsyncMock(side_effect=defer_start)
        start_interaction.edit_original_response = AsyncMock(side_effect=edit_start)
        end_interaction.response.defer = AsyncMock(side_effect=defer_end)
        end_interaction.edit_original_response = AsyncMock(side_effect=edit_end)
        tasks: list[asyncio.Task] = []

        def record_cleanup(
            _state: bot.GuildMusicState,
            message: object,
            _delay: float,
        ) -> None:
            operations.append(f"cleanup-{message.id}")

        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
            side_effect=record_cleanup,
        ) as schedule_cleanup:
            try:
                tasks.append(asyncio.create_task(start.callback(start_interaction)))
                await asyncio.wait_for(first_edit_started.wait(), timeout=1)
                tasks.append(asyncio.create_task(end.callback(end_interaction)))
                await asyncio.wait_for(second_deferred.wait(), timeout=1)
                await asyncio.sleep(0)

                self.assertFalse(tasks[1].done())
                end_interaction.edit_original_response.assert_not_awaited()
                release_first_edit.set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
            finally:
                release_first_edit.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(997, None)

        self.assertEqual(edit_lock_states, [True, True])
        self.assertEqual(remote_snapshots[-1], expected_snapshot(state, tracks, view))
        self.assertEqual(
            operations,
            [
                "start-defer",
                "start-edit",
                "end-defer",
                "cleanup-1001",
                "end-edit",
                "cleanup-1002",
            ],
        )
        self.assertEqual(
            [call.args for call in schedule_cleanup.call_args_list],
            [
                (
                    state,
                    start_interaction.message,
                    bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
                ),
                (
                    state,
                    end_interaction.message,
                    bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
                ),
            ],
        )

        state, tracks, view, start, end = make_case(998)
        first_defer_started = asyncio.Event()
        second_deferred = asyncio.Event()
        release_first_defer = asyncio.Event()
        operations = []
        remote_snapshots = []
        defer_lock_states: list[bool] = []
        edit_lock_states = []
        start_interaction = MagicMock(message=MagicMock(id=1003))
        end_interaction = MagicMock(message=MagicMock(id=1004))

        async def slow_defer_start() -> None:
            operations.append("start-defer")
            defer_lock_states.append(view.interaction_lock.locked())
            first_defer_started.set()
            await release_first_defer.wait()

        async def record_defer_end() -> None:
            operations.append("end-defer")
            defer_lock_states.append(view.interaction_lock.locked())
            second_deferred.set()

        async def record_edit_start(**kwargs: object) -> None:
            operations.append("start-edit")
            edit_lock_states.append(view.interaction_lock.locked())
            remote_snapshots.append(
                render_snapshot(state, view, start, end, kwargs)
            )

        async def record_edit_end(**kwargs: object) -> None:
            operations.append("end-edit")
            edit_lock_states.append(view.interaction_lock.locked())
            remote_snapshots.append(
                render_snapshot(state, view, start, end, kwargs)
            )

        start_interaction.response.defer = AsyncMock(side_effect=slow_defer_start)
        start_interaction.edit_original_response = AsyncMock(
            side_effect=record_edit_start
        )
        end_interaction.response.defer = AsyncMock(side_effect=record_defer_end)
        end_interaction.edit_original_response = AsyncMock(side_effect=record_edit_end)
        tasks = []

        def record_second_cleanup(
            _state: bot.GuildMusicState,
            message: object,
            _delay: float,
        ) -> None:
            operations.append(f"cleanup-{message.id}")

        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
            side_effect=record_second_cleanup,
        ) as schedule_cleanup:
            try:
                tasks.append(asyncio.create_task(start.callback(start_interaction)))
                await asyncio.wait_for(first_defer_started.wait(), timeout=1)
                tasks.append(asyncio.create_task(end.callback(end_interaction)))
                await asyncio.wait_for(second_deferred.wait(), timeout=1)
                await asyncio.wait_for(tasks[1], timeout=1)

                self.assertFalse(tasks[0].done())
                release_first_defer.set()
                await asyncio.wait_for(tasks[0], timeout=1)
            finally:
                release_first_defer.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(998, None)

        self.assertEqual(defer_lock_states, [False, False])
        self.assertEqual(edit_lock_states, [True, True])
        self.assertEqual(remote_snapshots[-1], expected_snapshot(state, tracks, view))
        self.assertEqual(
            operations,
            [
                "start-defer",
                "end-defer",
                "end-edit",
                "cleanup-1004",
                "start-edit",
                "cleanup-1003",
            ],
        )
        self.assertEqual(
            [call.args for call in schedule_cleanup.call_args_list],
            [
                (
                    state,
                    end_interaction.message,
                    bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
                ),
                (
                    state,
                    start_interaction.message,
                    bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
                ),
            ],
        )

    async def test_single_delete_rechecks_voice_after_waiting_for_interaction_lock(
        self,
    ) -> None:
        messages = {
            "member": "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            "disconnect": "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            "voice": "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요.",
            "defer-voice": "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요.",
        }
        for offset, outcome in enumerate(
            ("member", "disconnect", "voice", "defer-voice")
        ):
            with self.subTest(outcome=outcome):
                guild_id = 1200 + offset
                state = bot.get_state(guild_id)
                current = make_track(f"current-{outcome}")
                tracks = [
                    make_track(f"first-{outcome}"),
                    make_track(f"second-{outcome}"),
                ]
                state.current = current
                state.queue.extend(tracks)
                original_queue = state.queue
                generation = state.playback_generation
                channel = MagicMock(id=1300 + offset)
                voice = MagicMock(channel=channel)
                voice.is_connected.return_value = True
                state.voice = voice
                member_voice = MagicMock(channel=channel)
                member = MagicMock(voice=member_voice)
                view = bot.QueueManageView(guild_id)
                select = next(
                    item
                    for item in view.children
                    if isinstance(item, bot.QueueRemoveSelect)
                )
                select._values = [tracks[0].track_id]
                interaction = MagicMock(
                    message=MagicMock(id=1400 + offset),
                    user=member,
                )
                deferred = asyncio.Event()
                replacement_voice = None

                async def defer_response() -> None:
                    nonlocal replacement_voice
                    self.assertIs(state.voice, voice)
                    self.assertEqual(list(state.queue), tracks)
                    if outcome == "defer-voice":
                        replacement_channel = MagicMock(id=1500 + offset)
                        replacement_voice = MagicMock(
                            channel=replacement_channel
                        )
                        replacement_voice.is_connected.return_value = True
                        voice.is_connected.return_value = False
                        state.voice = replacement_voice
                        member_voice.channel = replacement_channel
                    deferred.set()

                async def send_followup(
                    _content: str,
                    **_kwargs: object,
                ) -> None:
                    self.assertFalse(select.interaction_lock.locked())
                    self.assertFalse(state.lock.locked())
                    return None

                interaction.response.is_done.return_value = False
                interaction.response.send_message = AsyncMock()
                interaction.response.defer = AsyncMock(side_effect=defer_response)
                interaction.edit_original_response = AsyncMock()
                interaction.followup.send = AsyncMock(side_effect=send_followup)
                callback_task = None
                test_holds_lock = False
                with (
                    patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
                    patch.object(
                        bot,
                        "schedule_queue_message_cleanup",
                    ) as schedule_cleanup,
                    patch.object(
                        bot,
                        "update_control_panel",
                        new=AsyncMock(),
                    ) as update_panel,
                ):
                    try:
                        self.assertTrue(await view.interaction_check(interaction))
                        interaction.response.send_message.assert_not_awaited()
                        await asyncio.wait_for(
                            select.interaction_lock.acquire(),
                            timeout=1,
                        )
                        test_holds_lock = True
                        callback_task = asyncio.create_task(
                            select.callback(interaction)
                        )
                        await asyncio.wait_for(deferred.wait(), timeout=1)
                        await asyncio.sleep(0)
                        self.assertFalse(callback_task.done())
                        if outcome == "member":
                            member_voice.channel = None
                        elif outcome == "disconnect":
                            voice.is_connected.return_value = False
                        elif outcome == "voice":
                            replacement_channel = MagicMock(id=1500 + offset)
                            replacement_voice = MagicMock(
                                channel=replacement_channel
                            )
                            replacement_voice.is_connected.return_value = True
                            voice.is_connected.return_value = False
                            state.voice = replacement_voice
                            member_voice.channel = replacement_channel

                        select.interaction_lock.release()
                        test_holds_lock = False
                        await asyncio.wait_for(callback_task, timeout=1)

                        self.assertIs(state.queue, original_queue)
                        self.assertEqual(list(state.queue), tracks)
                        self.assertIs(state.current, current)
                        self.assertEqual(state.playback_generation, generation)
                        self.assertFalse(state.stop_requested)
                        self.assertFalse(view.is_finished())
                        voice.stop.assert_not_called()
                        if replacement_voice is not None:
                            replacement_voice.stop.assert_not_called()
                        interaction.response.defer.assert_awaited_once_with()
                        interaction.edit_original_response.assert_not_awaited()
                        interaction.followup.send.assert_awaited_once_with(
                            messages[outcome],
                            ephemeral=True,
                            wait=True,
                        )
                        schedule_refill.assert_not_called()
                        schedule_cleanup.assert_not_called()
                        update_panel.assert_not_awaited()
                    finally:
                        if test_holds_lock:
                            select.interaction_lock.release()
                        if callback_task is not None and not callback_task.done():
                            callback_task.cancel()
                        if callback_task is not None:
                            await asyncio.wait_for(
                                asyncio.gather(
                                    callback_task,
                                    return_exceptions=True,
                                ),
                                timeout=1,
                            )
                        bot.discord.ui.View.stop(view)
                        bot.music_states.pop(guild_id, None)

    async def test_range_delete_rechecks_voice_after_waiting_for_state_lock(
        self,
    ) -> None:
        messages = {
            "member": "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            "disconnect": "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            "voice": "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요.",
            "defer-voice": "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요.",
        }
        for offset, outcome in enumerate(
            ("member", "disconnect", "voice", "defer-voice")
        ):
            with self.subTest(outcome=outcome):
                guild_id = 1210 + offset
                state = bot.get_state(guild_id)
                current = make_track(f"range-current-{outcome}")
                tracks = [
                    make_track(f"range-{outcome}-{index}")
                    for index in range(4)
                ]
                state.current = current
                state.queue.extend(tracks)
                original_queue = state.queue
                generation = state.playback_generation
                channel = MagicMock(id=1310 + offset)
                voice = MagicMock(channel=channel)
                voice.is_connected.return_value = True
                state.voice = voice
                member_voice = MagicMock(channel=channel)
                member = MagicMock(voice=member_voice)
                view = bot.QueueRangeDeleteView(guild_id)
                view.start_track_id = tracks[0].track_id
                view.end_track_id = tracks[2].track_id
                view.confirm_button.disabled = False
                interaction = MagicMock(
                    message=MagicMock(id=1410 + offset),
                    user=member,
                )
                deferred = asyncio.Event()
                replacement_voice = None

                async def defer_response() -> None:
                    nonlocal replacement_voice
                    self.assertIs(state.voice, voice)
                    self.assertEqual(list(state.queue), tracks)
                    if outcome == "defer-voice":
                        replacement_channel = MagicMock(id=1510 + offset)
                        replacement_voice = MagicMock(
                            channel=replacement_channel
                        )
                        replacement_voice.is_connected.return_value = True
                        voice.is_connected.return_value = False
                        state.voice = replacement_voice
                        member_voice.channel = replacement_channel
                    deferred.set()

                async def send_followup(
                    _content: str,
                    **_kwargs: object,
                ) -> None:
                    self.assertFalse(view.interaction_lock.locked())
                    self.assertFalse(state.lock.locked())
                    return None

                interaction.response.is_done.return_value = False
                interaction.response.send_message = AsyncMock()
                interaction.response.defer = AsyncMock(side_effect=defer_response)
                interaction.edit_original_response = AsyncMock()
                interaction.followup.send = AsyncMock(side_effect=send_followup)
                callback_task = None
                test_holds_state_lock = False
                with (
                    patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
                    patch.object(
                        bot,
                        "schedule_queue_message_cleanup",
                    ) as schedule_cleanup,
                    patch.object(
                        bot,
                        "update_control_panel",
                        new=AsyncMock(),
                    ) as update_panel,
                ):
                    try:
                        self.assertTrue(await view.interaction_check(interaction))
                        interaction.response.send_message.assert_not_awaited()
                        await asyncio.wait_for(state.lock.acquire(), timeout=1)
                        test_holds_state_lock = True
                        callback_task = asyncio.create_task(
                            view.confirm_button.callback(interaction)
                        )
                        await asyncio.wait_for(deferred.wait(), timeout=1)
                        for _ in range(10):
                            if view.interaction_lock.locked():
                                break
                            await asyncio.sleep(0)
                        self.assertTrue(view.interaction_lock.locked())
                        self.assertFalse(callback_task.done())
                        if outcome == "member":
                            member_voice.channel = None
                        elif outcome == "disconnect":
                            voice.is_connected.return_value = False
                        elif outcome == "voice":
                            replacement_channel = MagicMock(id=1510 + offset)
                            replacement_voice = MagicMock(
                                channel=replacement_channel
                            )
                            replacement_voice.is_connected.return_value = True
                            voice.is_connected.return_value = False
                            state.voice = replacement_voice
                            member_voice.channel = replacement_channel

                        state.lock.release()
                        test_holds_state_lock = False
                        await asyncio.wait_for(callback_task, timeout=1)

                        self.assertIs(state.queue, original_queue)
                        self.assertEqual(list(state.queue), tracks)
                        self.assertIs(state.current, current)
                        self.assertEqual(state.playback_generation, generation)
                        self.assertFalse(state.stop_requested)
                        self.assertFalse(view.is_finished())
                        voice.stop.assert_not_called()
                        if replacement_voice is not None:
                            replacement_voice.stop.assert_not_called()
                        interaction.response.defer.assert_awaited_once_with()
                        interaction.edit_original_response.assert_not_awaited()
                        interaction.followup.send.assert_awaited_once_with(
                            messages[outcome],
                            ephemeral=True,
                            wait=True,
                        )
                        schedule_refill.assert_not_called()
                        schedule_cleanup.assert_not_called()
                        update_panel.assert_not_awaited()
                    finally:
                        if test_holds_state_lock:
                            state.lock.release()
                        if callback_task is not None and not callback_task.done():
                            callback_task.cancel()
                        if callback_task is not None:
                            await asyncio.wait_for(
                                asyncio.gather(
                                    callback_task,
                                    return_exceptions=True,
                                ),
                                timeout=1,
                            )
                        bot.discord.ui.View.stop(view)
                        bot.music_states.pop(guild_id, None)

    async def test_range_confirm_cannot_be_revived_by_waiting_boundary(
        self,
    ) -> None:
        guild_id = 999
        tracks = [make_track(f"track-{index}") for index in range(1, 7)]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = tracks[1].track_id
        view.end_track_id = tracks[3].track_id
        view.confirm_button.disabled = False
        start = next(
            item
            for item in view.children
            if isinstance(item, bot.QueueRangeBoundarySelect)
            and item.boundary == "start"
        )
        start._values = [tracks[0].track_id]

        confirm_deferred = asyncio.Event()
        boundary_deferred = asyncio.Event()
        confirm_interaction = MagicMock(message=MagicMock(id=1101))
        boundary_interaction = MagicMock(message=MagicMock(id=1102))
        panel_lock_states: list[bool] = []

        async def defer_confirm() -> None:
            confirm_deferred.set()

        async def defer_boundary() -> None:
            boundary_deferred.set()

        confirm_interaction.response.defer = AsyncMock(side_effect=defer_confirm)
        confirm_interaction.edit_original_response = AsyncMock()
        boundary_interaction.response.defer = AsyncMock(side_effect=defer_boundary)
        boundary_interaction.edit_original_response = AsyncMock()
        self.set_same_voice(state, confirm_interaction, boundary_interaction)

        def record_panel(*_args: object, **_kwargs: object) -> None:
            panel_lock_states.append(view.interaction_lock.locked())

        confirm_task = None
        boundary_task = None
        test_holds_lock = False
        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as update_control_panel,
        ):
            try:
                await asyncio.wait_for(view.interaction_lock.acquire(), timeout=1)
                test_holds_lock = True
                confirm_task = asyncio.create_task(
                    view.confirm_button.callback(confirm_interaction)
                )
                await asyncio.wait_for(confirm_deferred.wait(), timeout=1)
                await asyncio.sleep(0)
                self.assertFalse(confirm_task.done())

                boundary_task = asyncio.create_task(start.callback(boundary_interaction))
                await asyncio.wait_for(boundary_deferred.wait(), timeout=1)
                self.assertEqual(view.start_track_id, tracks[0].track_id)
                self.assertFalse(boundary_task.done())
                confirm_interaction.response.defer.assert_awaited_once_with()
                boundary_interaction.response.defer.assert_awaited_once_with()
                confirm_interaction.edit_original_response.assert_not_awaited()
                boundary_interaction.edit_original_response.assert_not_awaited()

                view.interaction_lock.release()
                test_holds_lock = False
                await asyncio.wait_for(
                    asyncio.gather(confirm_task, boundary_task),
                    timeout=1,
                )
            finally:
                if test_holds_lock:
                    view.interaction_lock.release()
                for task in (confirm_task, boundary_task):
                    if task is not None and not task.done():
                        task.cancel()
                tasks = [
                    task
                    for task in (confirm_task, boundary_task)
                    if task is not None
                ]
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(guild_id, None)

        self.assertEqual(list(state.queue), [tracks[0], tracks[4], tracks[5]])
        self.assertTrue(view.is_finished())
        confirm_interaction.edit_original_response.assert_awaited_once()
        confirm_kwargs = confirm_interaction.edit_original_response.await_args.kwargs
        self.assertIn("2~4번", confirm_kwargs["content"])
        self.assertIn("3곡", confirm_kwargs["content"])
        self.assertEqual(
            confirm_kwargs["embed"].to_dict(),
            bot.make_queue_embed(state).to_dict(),
        )
        self.assertIsNone(confirm_kwargs["view"])
        boundary_interaction.edit_original_response.assert_not_awaited()
        schedule_refill.assert_called_once_with(guild_id)
        schedule_cleanup.assert_called_once_with(
            state,
            confirm_interaction.message,
            bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )
        update_control_panel.assert_awaited_once_with(guild_id, state)
        self.assertEqual(panel_lock_states, [False])

    async def test_confirm_deletes_inclusive_range(self) -> None:
        guild_id = 988
        tracks = [make_track(f"track-{index}") for index in range(1, 21)]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = tracks[4].track_id
        view.end_track_id = tracks[12].track_id
        view.confirm_button.disabled = False
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 989
        self.set_same_voice(state, interaction)
        operation_order: list[str] = []
        cleanup_error = RuntimeError("queue cleanup scheduling failed")

        def fail_cleanup(*_args: object, **_kwargs: object) -> None:
            operation_order.append("cleanup")
            raise cleanup_error

        interaction.response.defer.side_effect = (
            lambda: operation_order.append("defer")
        )
        interaction.edit_original_response.side_effect = (
            lambda **_kwargs: operation_order.append("edit")
        )

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
                side_effect=fail_cleanup,
            ) as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(
                    side_effect=lambda *_args, **_kwargs: operation_order.append("panel")
                ),
            ) as update_control_panel,
        ):
            with self.assertRaises(RuntimeError) as raised:
                await view.confirm_button.callback(interaction)

        self.assertIs(raised.exception, cleanup_error)
        self.assertEqual(
            operation_order,
            ["defer", "edit", "cleanup", "panel"],
        )

        self.assertEqual(len(state.queue), 11)
        self.assertEqual(list(state.queue), tracks[:4] + tracks[13:])
        schedule_refill.assert_called_once_with(guild_id)
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn("5~13번", kwargs["content"])
        self.assertIn("9곡", kwargs["content"])
        self.assertIsNone(kwargs["view"])
        schedule_cleanup.assert_called_once_with(
            state,
            interaction.message,
            bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )
        update_control_panel.assert_awaited_once_with(guild_id, state)
        self.assertTrue(view.is_finished())

    async def test_range_delete_response_failure_still_refreshes_panel(self) -> None:
        guild_id = 995
        tracks = [make_track("first"), make_track("second"), make_track("third")]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = tracks[0].track_id
        view.end_track_id = tracks[1].track_id
        view.confirm_button.disabled = False
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        self.set_same_voice(state, interaction)
        operation_order: list[str] = []
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )

        interaction.response.defer.side_effect = (
            lambda: operation_order.append("defer")
        )

        def fail_response(**_kwargs: object) -> None:
            operation_order.append("edit")
            raise response_error

        interaction.edit_original_response.side_effect = fail_response
        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(
                    side_effect=lambda *_args, **_kwargs: operation_order.append("panel")
                ),
            ) as update_control_panel,
        ):
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await view.confirm_button.callback(interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(operation_order, ["defer", "edit", "panel"])
        self.assertEqual(list(state.queue), [tracks[2]])
        schedule_refill.assert_called_once_with(guild_id)
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        schedule_cleanup.assert_not_called()
        update_control_panel.assert_awaited_once_with(guild_id, state)
        self.assertFalse(view.is_finished())

    async def test_range_confirm_defer_failure_keeps_selection_and_queue(
        self,
    ) -> None:
        guild_id = 993
        tracks = [make_track("first"), make_track("second"), make_track("third")]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = tracks[0].track_id
        view.end_track_id = tracks[1].track_id
        view.confirm_button.disabled = False
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )
        interaction = MagicMock(message=MagicMock(id=994))
        interaction.response.defer = AsyncMock(side_effect=response_error)
        interaction.edit_original_response = AsyncMock()
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ) as update_control_panel,
        ):
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await view.confirm_button.callback(interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(list(state.queue), tracks)
        self.assertEqual(view.start_track_id, tracks[0].track_id)
        self.assertEqual(view.end_track_id, tracks[1].track_id)
        self.assertFalse(view.confirm_button.disabled)
        self.assertFalse(view.is_finished())
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_not_awaited()
        schedule_refill.assert_not_called()
        schedule_cleanup.assert_not_called()
        update_control_panel.assert_not_awaited()

    async def test_missing_range_replaces_and_finishes_old_view(self) -> None:
        guild_id = 994
        first = make_track("first")
        second = make_track("second")
        missing = make_track("missing")
        state = bot.get_state(guild_id)
        state.queue.extend([first, second])
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = missing.track_id
        view.end_track_id = second.track_id
        view.confirm_button.disabled = False
        interaction = MagicMock(message=MagicMock(id=995))
        interaction.response.defer = AsyncMock()

        async def edit_replacement(**_kwargs: object) -> None:
            self.assertFalse(view.is_finished())

        interaction.edit_original_response = AsyncMock(
            side_effect=edit_replacement
        )
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
            ) as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ) as update_control_panel,
        ):
            await view.confirm_button.callback(interaction)

        self.assertEqual(list(state.queue), [first, second])
        self.assertTrue(view.is_finished())
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        edit_kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn("다시 선택", edit_kwargs["content"])
        self.assertEqual(
            edit_kwargs["embed"].to_dict(),
            bot.make_queue_embed(state).to_dict(),
        )
        replacement_view = edit_kwargs["view"]
        self.assertIsInstance(replacement_view, bot.QueueRangeDeleteView)
        self.assertIsNot(replacement_view, view)
        self.assertFalse(replacement_view.is_finished())
        schedule_cleanup.assert_called_once_with(
            state,
            interaction.message,
            bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
        )
        schedule_refill.assert_not_called()
        update_control_panel.assert_not_awaited()

        empty_state = bot.get_state(992)
        empty_view = bot.QueueRangeDeleteView(992)
        empty_view.start_track_id = first.track_id
        empty_view.end_track_id = second.track_id
        empty_view.confirm_button.disabled = False
        empty_interaction = MagicMock(message=MagicMock(id=996))
        empty_interaction.response.defer = AsyncMock()
        empty_interaction.edit_original_response = AsyncMock()
        self.set_same_voice(empty_state, empty_interaction)
        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
        ) as empty_cleanup:
            await empty_view.confirm_button.callback(empty_interaction)

        self.assertTrue(empty_view.is_finished())
        empty_interaction.edit_original_response.assert_awaited_once()
        self.assertIsNone(
            empty_interaction.edit_original_response.await_args.kwargs["view"]
        )
        empty_cleanup.assert_not_called()

    async def test_missing_range_edit_failure_keeps_old_view_active(self) -> None:
        guild_id = 991
        first = make_track("first")
        second = make_track("second")
        missing = make_track("missing")
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend([first, second])
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = missing.track_id
        view.end_track_id = second.track_id
        view.confirm_button.disabled = False
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )
        interaction = MagicMock(message=MagicMock(id=997))
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock(
            side_effect=response_error
        )
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ) as update_control_panel,
        ):
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await view.confirm_button.callback(interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(list(state.queue), [first, second])
        self.assertFalse(view.is_finished())
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        schedule_refill.assert_not_called()
        schedule_cleanup.assert_not_called()
        update_control_panel.assert_not_awaited()

    async def test_single_delete_resets_queue_message_expiry(self) -> None:
        guild_id = 990
        first = make_track("first")
        second = make_track("second")
        state = bot.get_state(guild_id)
        state.queue.extend([first, second])
        select = bot.QueueRemoveSelect(guild_id)
        select._values = [first.track_id]
        interaction = MagicMock()
        interaction.response.defer = AsyncMock()
        interaction.edit_original_response = AsyncMock()
        interaction.message = MagicMock(id=991)
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill"),
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
            ) as schedule_cleanup,
        ):
            await select.callback(interaction)

        self.assertEqual(list(state.queue), [second])
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        schedule_cleanup.assert_called_once_with(
            state,
            interaction.message,
            bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )

    async def test_stale_single_delete_refreshes_latest_queue_message(self) -> None:
        stale = make_track("stale")
        latest = make_track("latest")

        success_state = bot.get_state(991)
        success_state.queue.extend([stale, latest])
        success_select = bot.QueueRemoveSelect(991)
        success_select._values = [stale.track_id]
        self.assertEqual(success_select.options[0].value, stale.track_id)
        self.assertIs(
            bot.remove_queued_track_by_id(success_state, stale.track_id),
            stale,
        )
        success_interaction = MagicMock(message=MagicMock(id=992))
        operation_order: list[str] = []
        success_interaction.response.defer = AsyncMock(
            side_effect=lambda: operation_order.append("defer")
        )
        success_interaction.edit_original_response = AsyncMock(
            side_effect=lambda **_kwargs: operation_order.append("edit")
        )
        self.set_same_voice(success_state, success_interaction)
        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
            side_effect=lambda *_args: operation_order.append("cleanup"),
        ) as schedule_cleanup:
            await success_select.callback(success_interaction)

        self.assertEqual(operation_order, ["defer", "edit", "cleanup"])
        self.assertEqual(list(success_state.queue), [latest])
        success_interaction.response.defer.assert_awaited_once_with()
        response_kwargs = success_interaction.edit_original_response.await_args.kwargs
        self.assertEqual(
            response_kwargs["content"],
            "이미 삭제되었거나 찾을 수 없는 곡이에요.",
        )
        self.assertEqual(
            response_kwargs["embed"].to_dict(),
            bot.make_queue_embed(success_state).to_dict(),
        )
        replacement_view = response_kwargs["view"]
        self.assertIsInstance(replacement_view, bot.QueueManageView)
        replacement_select = next(
            item
            for item in replacement_view.children
            if isinstance(item, bot.QueueRemoveSelect)
        )
        self.assertEqual(
            [option.value for option in replacement_select.options],
            [latest.track_id],
        )
        self.assertIs(
            replacement_select.interaction_lock,
            success_select.interaction_lock,
        )
        schedule_cleanup.assert_called_once_with(
            success_state,
            success_interaction.message,
            bot.EPHEMERAL_RESPONSE_DELETE_SECONDS,
        )

        failure_state = bot.get_state(993)
        failure_state.queue.extend([stale, latest])
        failure_select = bot.QueueRemoveSelect(993)
        failure_select._values = [stale.track_id]
        self.assertEqual(failure_select.options[0].value, stale.track_id)
        self.assertIs(
            bot.remove_queued_track_by_id(failure_state, stale.track_id),
            stale,
        )
        failure_interaction = MagicMock(message=MagicMock(id=994))
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )
        failure_interaction.response.defer = AsyncMock()
        failure_interaction.edit_original_response = AsyncMock(
            side_effect=response_error
        )
        self.set_same_voice(failure_state, failure_interaction)
        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
        ) as schedule_cleanup:
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await failure_select.callback(failure_interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(list(failure_state.queue), [latest])
        failure_interaction.response.defer.assert_awaited_once_with()
        failure_interaction.edit_original_response.assert_awaited_once()
        schedule_cleanup.assert_not_called()

        empty_state = bot.get_state(995)
        empty_state.queue.append(stale)
        empty_select = bot.QueueRemoveSelect(995)
        empty_select._values = [stale.track_id]
        empty_state.queue.clear()
        empty_interaction = MagicMock(message=MagicMock(id=996))
        empty_interaction.response.defer = AsyncMock()
        empty_interaction.edit_original_response = AsyncMock()
        self.set_same_voice(empty_state, empty_interaction)
        with patch.object(
            bot,
            "schedule_queue_message_cleanup",
        ) as schedule_cleanup:
            await empty_select.callback(empty_interaction)

        self.assertEqual(list(empty_state.queue), [])
        empty_interaction.response.defer.assert_awaited_once_with()
        empty_kwargs = empty_interaction.edit_original_response.await_args.kwargs
        self.assertEqual(
            empty_kwargs["content"],
            "이미 삭제되었거나 찾을 수 없는 곡이에요.",
        )
        self.assertEqual(
            empty_kwargs["embed"].to_dict(),
            bot.make_queue_embed(empty_state).to_dict(),
        )
        self.assertIsNone(empty_kwargs["view"])
        schedule_cleanup.assert_not_called()

    async def test_single_delete_response_failure_still_refreshes_panel(self) -> None:
        guild_id = 990
        first = make_track("first")
        second = make_track("second")
        third = make_track("third")
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend([third, first, second])
        select = bot.QueueRemoveSelect(guild_id)
        select._values = [second.track_id]
        operation_order: list[str] = []
        interaction = MagicMock()
        interaction.response.defer = AsyncMock(
            side_effect=lambda: operation_order.append("defer")
        )
        interaction.edit_original_response = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 991
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )

        def edit_response(**_kwargs: object) -> None:
            operation_order.append("response")
            raise response_error

        interaction.edit_original_response.side_effect = edit_response
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
            ) as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(
                    side_effect=lambda *_args, **_kwargs: operation_order.append("panel")
                ),
            ) as update_control_panel,
        ):
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await select.callback(interaction)

        self.assertIs(raised.exception, response_error)
        self.assertEqual(operation_order, ["defer", "response", "panel"])
        self.assertEqual(list(state.queue), [third, first])
        schedule_refill.assert_called_once_with(guild_id)
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_awaited_once()
        response_kwargs = interaction.edit_original_response.await_args.kwargs
        self.assertIn(second.title, response_kwargs["content"])
        self.assertEqual(
            response_kwargs["embed"].to_dict(),
            bot.make_queue_embed(state).to_dict(),
        )
        self.assertIsInstance(response_kwargs["view"], bot.QueueManageView)
        schedule_cleanup.assert_not_called()
        update_control_panel.assert_awaited_once_with(guild_id, state)

    async def test_single_delete_defer_failure_keeps_queue_unchanged(self) -> None:
        guild_id = 997
        tracks = [make_track("first"), make_track("second")]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        original_queue = state.queue
        select = bot.QueueRemoveSelect(guild_id)
        select._values = [tracks[0].track_id]
        interaction = MagicMock(message=MagicMock(id=998))
        response = MagicMock(status=500, reason="Internal Server Error")
        response_error = bot.discord.DiscordServerError(
            response,
            "<html>defer failure</html>",
        )
        interaction.response.defer = AsyncMock(side_effect=response_error)
        interaction.edit_original_response = AsyncMock()
        self.set_same_voice(state, interaction)

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_queue_message_cleanup") as schedule_cleanup,
            patch.object(bot, "update_control_panel", new=AsyncMock()) as update_panel,
        ):
            with self.assertRaises(bot.discord.DiscordServerError) as raised:
                await select.callback(interaction)

        self.assertIs(raised.exception, response_error)
        self.assertIs(state.queue, original_queue)
        self.assertEqual(list(state.queue), tracks)
        interaction.response.defer.assert_awaited_once_with()
        interaction.edit_original_response.assert_not_awaited()
        schedule_refill.assert_not_called()
        schedule_cleanup.assert_not_called()
        update_panel.assert_not_awaited()

    async def test_single_delete_replacement_views_share_serialization_lock(
        self,
    ) -> None:
        guild_id = 999
        tracks = [make_track(title) for title in ("A", "B", "C", "D")]
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.queue.extend(tracks)
        old_select = bot.QueueRemoveSelect(guild_id)
        old_select._values = [tracks[0].track_id]
        shared_message = MagicMock(id=1000)
        deferred = {name: asyncio.Event() for name in ("A", "B", "C")}
        edit_started = {name: asyncio.Event() for name in ("A", "B", "C")}
        release_edit = {name: asyncio.Event() for name in ("A", "B", "C")}
        defer_order: list[str] = []
        edit_order: list[str] = []
        edit_lock_states: list[bool] = []
        cleanup_lock_states: list[bool] = []
        panel_lock_states: list[bool] = []
        snapshots: dict[str, tuple[list[bot.Track], dict[str, object]]] = {}

        def make_interaction(name: str) -> MagicMock:
            interaction = MagicMock(message=shared_message)

            async def defer_response() -> None:
                defer_order.append(name)
                deferred[name].set()
                if name == "B":
                    old_select._values = [tracks[3].track_id]

            async def edit_response(**kwargs: object) -> None:
                edit_order.append(name)
                edit_lock_states.append(old_select.interaction_lock.locked())
                response_view = kwargs["view"]
                self.assertIsInstance(response_view, bot.QueueManageView)
                response_select = next(
                    item
                    for item in response_view.children
                    if isinstance(item, bot.QueueRemoveSelect)
                )
                self.assertEqual(
                    [option.value for option in response_select.options],
                    [track.track_id for track in state.queue],
                )
                self.assertEqual(
                    kwargs["embed"].to_dict(),
                    bot.make_queue_embed(state).to_dict(),
                )
                self.assertIn(f"`{name}`", kwargs["content"])
                snapshots[name] = (list(state.queue), kwargs)
                edit_started[name].set()
                await release_edit[name].wait()

            interaction.response.defer = AsyncMock(side_effect=defer_response)
            interaction.edit_original_response = AsyncMock(side_effect=edit_response)
            return interaction

        async def record_panel(*_args: object, **_kwargs: object) -> None:
            panel_lock_states.append(old_select.interaction_lock.locked())

        def record_cleanup(*_args: object) -> None:
            cleanup_lock_states.append(old_select.interaction_lock.locked())

        interactions = {name: make_interaction(name) for name in ("A", "B", "C")}
        self.set_same_voice(state, *interactions.values())
        tasks: list[asyncio.Task[None]] = []
        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
                side_effect=record_cleanup,
            ) as schedule_cleanup,
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as update_panel,
        ):
            try:
                task_a = asyncio.create_task(old_select.callback(interactions["A"]))
                tasks.append(task_a)
                await asyncio.wait_for(edit_started["A"].wait(), timeout=1)

                old_select._values = [tracks[1].track_id]
                task_b = asyncio.create_task(old_select.callback(interactions["B"]))
                tasks.append(task_b)
                await asyncio.wait_for(deferred["B"].wait(), timeout=1)
                await asyncio.sleep(0)
                self.assertFalse(edit_started["B"].is_set())
                self.assertFalse(task_b.done())

                release_edit["A"].set()
                await asyncio.wait_for(edit_started["B"].wait(), timeout=1)
                replacement_view = snapshots["A"][1]["view"]
                self.assertIsInstance(replacement_view, bot.QueueManageView)
                replacement_select = next(
                    item
                    for item in replacement_view.children
                    if isinstance(item, bot.QueueRemoveSelect)
                )
                self.assertIs(
                    replacement_select.interaction_lock,
                    old_select.interaction_lock,
                )

                replacement_select._values = [tracks[2].track_id]
                task_c = asyncio.create_task(
                    replacement_select.callback(interactions["C"])
                )
                tasks.append(task_c)
                await asyncio.wait_for(deferred["C"].wait(), timeout=1)
                await asyncio.sleep(0)
                self.assertFalse(edit_started["C"].is_set())
                self.assertFalse(task_c.done())

                release_edit["B"].set()
                await asyncio.wait_for(edit_started["C"].wait(), timeout=1)
                release_edit["C"].set()
                await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
            finally:
                for release in release_edit.values():
                    release.set()
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )

        self.assertEqual(defer_order, ["A", "B", "C"])
        self.assertEqual(edit_order, ["A", "B", "C"])
        self.assertEqual(edit_lock_states, [True, True, True])
        self.assertEqual(cleanup_lock_states, [True, True, True])
        self.assertEqual(panel_lock_states, [False, False, False])
        self.assertEqual(
            [snapshot for snapshot, _kwargs in snapshots.values()],
            [tracks[1:], tracks[2:], tracks[3:]],
        )
        self.assertEqual(list(state.queue), tracks[3:])
        final_view = snapshots["C"][1]["view"]
        self.assertIsInstance(final_view, bot.QueueManageView)
        final_select = next(
            item
            for item in final_view.children
            if isinstance(item, bot.QueueRemoveSelect)
        )
        self.assertEqual(
            [option.value for option in final_select.options],
            [tracks[3].track_id],
        )
        for interaction in interactions.values():
            interaction.response.defer.assert_awaited_once_with()
            interaction.edit_original_response.assert_awaited_once()
        self.assertEqual(schedule_refill.call_count, 3)
        self.assertEqual(schedule_cleanup.call_count, 3)
        for cleanup_call in schedule_cleanup.call_args_list:
            self.assertEqual(
                cleanup_call.args,
                (state, shared_message, bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS),
            )
        self.assertEqual(update_panel.await_count, 3)
        for panel_call in update_panel.await_args_list:
            self.assertEqual(panel_call.args, (guild_id, state))


class VoiceConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        bot.voice_operation_tasks.clear()
        bot.bot._discord_close_task = None

    async def asyncTearDown(self) -> None:
        tasks = list(bot.voice_operation_tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bot.voice_operation_tasks.clear()
        bot.bot_shutdown_started = False
        bot.auxiliary_workers_closing = False
        bot.lyrics_executor_closing = False
        discord_close_task = bot.bot._discord_close_task
        if discord_close_task is not None and not discord_close_task.done():
            discord_close_task.cancel()
            await asyncio.gather(discord_close_task, return_exceptions=True)
        bot.bot._discord_close_task = None
        bot.music_states.clear()

    async def test_concurrent_requests_share_one_voice_connection(self) -> None:
        class Guild:
            id = 810
            voice_client = None

        guild = Guild()
        connect_started = asyncio.Event()
        release_connect = asyncio.Event()

        class Channel:
            mention = "#voice"

            def __init__(self) -> None:
                self.connect_calls = 0

            async def connect(self) -> object:
                self.connect_calls += 1
                connect_started.set()
                await release_connect.wait()
                guild.voice_client = voice
                return voice

        class Voice:
            def __init__(self, channel: Channel) -> None:
                self.channel = channel

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        channel = Channel()
        voice = Voice(channel)

        class Member:
            bot = False

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
        channel.members = [member]
        state = bot.GuildMusicState()

        first = asyncio.create_task(bot.ensure_voice_for_member(member, state))
        await connect_started.wait()
        second = asyncio.create_task(bot.ensure_voice_for_member(member, state))
        await asyncio.sleep(0)

        self.assertFalse(second.done())
        release_connect.set()
        results = await asyncio.gather(first, second)

        self.assertEqual(results, [(True, None), (True, None)])
        self.assertEqual(channel.connect_calls, 1)
        self.assertIs(state.voice, voice)

    async def test_swallowed_move_timeout_does_not_accept_request(self) -> None:
        guild_id = 819
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        fresh_connect_started = asyncio.Event()
        release_fresh_connect = asyncio.Event()
        panel_started = asyncio.Event()

        class Channel:
            def __init__(self, channel_id: int) -> None:
                self.id = channel_id
                self.members = []
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1419)
        target_channel = Channel(1519)

        class Voice:
            def __init__(self, channel: Channel) -> None:
                self.channel = channel
                self.connected = True
                self.move_to = AsyncMock()
                self.disconnect = AsyncMock(side_effect=self._disconnect)
                self.cleanup = MagicMock(side_effect=self._cleanup)

            async def _disconnect(self, *, force: bool = False) -> None:
                self.assert_force = force
                cleanup_started.set()
                await release_cleanup.wait()
                self.connected = False

            def _cleanup(self) -> None:
                guild.voice_client = None

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        voice = Voice(old_channel)
        fresh_voice = Voice(old_channel)
        fresh_voice.disconnect = AsyncMock()
        fresh_voice.cleanup = MagicMock()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()

        async def connect_fresh_voice() -> Voice:
            fresh_connect_started.set()
            await release_fresh_connect.wait()
            guild.voice_client = fresh_voice
            return fresh_voice

        old_channel.connect = AsyncMock(side_effect=connect_fresh_voice)

        class Requester:
            bot = False

            def __init__(self, channel: Channel) -> None:
                self.voice = type("MemberVoice", (), {"channel": channel})()
                self.guild = guild

        moving_member = Requester(target_channel)
        fresh_member = Requester(old_channel)
        target_channel.members.append(moving_member)
        old_channel.members.append(fresh_member)
        state = bot.get_state(guild_id)
        state.voice = voice
        original_generation = state.playback_generation
        panel_lock_states: list[bool] = []

        async def record_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_lock_states.append(state.voice_connect_lock.locked())
            panel_started.set()

        movement = None
        fresh_request = None
        try:
            with patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as show_idle_panel:
                movement = asyncio.create_task(
                    bot.ensure_voice_for_member(moving_member, state)
                )
                await asyncio.wait_for(cleanup_started.wait(), timeout=1)

                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertIs(state.voice, voice)
                self.assertTrue(state.voice_connect_lock.locked())
                self.assertFalse(movement.done())

                fresh_request = asyncio.create_task(
                    bot.ensure_voice_for_member(fresh_member, state)
                )
                await asyncio.sleep(0)
                self.assertFalse(fresh_request.done())
                old_channel.connect.assert_not_awaited()

                release_cleanup.set()
                await asyncio.wait_for(fresh_connect_started.wait(), timeout=1)
                result = await asyncio.wait_for(movement, timeout=1)
                self.assertEqual(
                    result,
                    (
                        False,
                        "음성 채널 이동에 실패했어요. "
                        "잠시 후 다시 시도해 주세요.",
                    ),
                )
                self.assertIsNone(state.voice)
                self.assertIsNone(guild.voice_client)

                await asyncio.wait_for(panel_started.wait(), timeout=1)
                self.assertEqual(panel_lock_states, [False])
                show_idle_panel.assert_awaited_once_with(guild_id, state)

                release_fresh_connect.set()
                self.assertEqual(
                    await asyncio.wait_for(fresh_request, timeout=1),
                    (True, None),
                )

            voice.move_to.assert_awaited_once_with(target_channel)
            voice.disconnect.assert_awaited_once_with(force=True)
            self.assertTrue(voice.assert_force)
            voice.cleanup.assert_called_once_with()
            self.assertIs(state.voice, fresh_voice)
            self.assertEqual(
                state.playback_generation,
                original_generation + 1,
            )
            self.assertFalse(bot.voice_operation_tasks)
        finally:
            release_cleanup.set()
            release_fresh_connect.set()
            for task in (movement, fresh_request):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(
                *(task for task in (movement, fresh_request) if task is not None),
                return_exceptions=True,
            )
            bot.cancel_empty_channel_disconnect(state)
            bot.music_states.pop(guild_id, None)

    async def test_disconnected_target_after_move_is_not_accepted(self) -> None:
        guild_id = 827
        old_channel = MagicMock(id=1427, mention="<#1427>", members=[])
        target_channel = MagicMock(id=1527, mention="<#1527>", members=[])

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.connected = True
                self.move_to = AsyncMock(side_effect=self._move_to)
                self.disconnect = AsyncMock()
                self.cleanup = MagicMock(side_effect=self._cleanup)

            async def _move_to(self, channel: object) -> None:
                self.channel = channel
                self.connected = False

            def _cleanup(self) -> None:
                guild.voice_client = None

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()
        requester = MagicMock(
            bot=False,
            guild=guild,
            voice=MagicMock(channel=target_channel),
        )
        state = bot.get_state(guild_id)
        state.voice = voice
        original_generation = state.playback_generation
        panel_started = asyncio.Event()

        async def record_panel(*_args: object) -> None:
            self.assertFalse(state.voice_connect_lock.locked())
            panel_started.set()

        try:
            with patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as show_idle_panel:
                result = await bot.ensure_voice_for_member(requester, state)
                await asyncio.wait_for(panel_started.wait(), timeout=1)

            self.assertEqual(
                result,
                (
                    False,
                    "음성 채널 이동에 실패했어요. "
                    "잠시 후 다시 시도해 주세요.",
                ),
            )
            self.assertEqual(
                state.playback_generation,
                original_generation + 1,
            )
            self.assertIsNone(state.voice)
            self.assertIsNone(guild.voice_client)
            voice.move_to.assert_awaited_once_with(target_channel)
            voice.disconnect.assert_awaited_once_with(force=True)
            voice.cleanup.assert_called_once_with()
            show_idle_panel.assert_awaited_once_with(guild_id, state)
            self.assertFalse(bot.voice_operation_tasks)
        finally:
            bot.cancel_empty_channel_disconnect(state)
            bot.music_states.pop(guild_id, None)

    async def test_cancelled_voice_move_finishes_cleanup_before_propagating(
        self,
    ) -> None:
        guild_id = 820
        move_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        release_cleanup = asyncio.Event()
        panel_started = asyncio.Event()

        class Channel:
            def __init__(self, channel_id: int) -> None:
                self.id = channel_id
                self.members = []
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1420)
        target_channel = Channel(1520)

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.connected = True
                self.move_to = AsyncMock(side_effect=self._move_to)
                self.disconnect = AsyncMock(side_effect=self._disconnect)
                self.cleanup = MagicMock(side_effect=self._cleanup)

            async def _move_to(self, _channel: Channel) -> None:
                move_started.set()
                await asyncio.Event().wait()

            async def _disconnect(self, *, force: bool = False) -> None:
                self.force = force
                cleanup_started.set()
                await release_cleanup.wait()
                self.connected = False

            def _cleanup(self) -> None:
                guild.voice_client = None

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()

        class Requester:
            bot = False
            voice = type("MemberVoice", (), {"channel": target_channel})()

        requester = Requester()
        requester.guild = guild
        target_channel.members.append(requester)
        state = bot.get_state(guild_id)
        state.voice = voice
        original_generation = state.playback_generation
        panel_lock_states: list[bool] = []

        async def record_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_lock_states.append(state.voice_connect_lock.locked())
            panel_started.set()

        movement = None
        try:
            with patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as show_idle_panel:
                movement = asyncio.create_task(
                    bot.ensure_voice_for_member(requester, state)
                )
                await asyncio.wait_for(move_started.wait(), timeout=1)
                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )

                movement.cancel("move-cancel")
                await asyncio.wait_for(cleanup_started.wait(), timeout=1)
                self.assertFalse(movement.done())
                self.assertTrue(state.voice_connect_lock.locked())
                self.assertIs(state.voice, voice)

                movement.cancel("cleanup-cancel")
                await asyncio.sleep(0)
                self.assertFalse(movement.done())
                release_cleanup.set()

                with self.assertRaises(asyncio.CancelledError) as raised:
                    await asyncio.wait_for(movement, timeout=1)
                self.assertEqual(raised.exception.args, ("move-cancel",))
                await asyncio.wait_for(panel_started.wait(), timeout=1)

                show_idle_panel.assert_awaited_once_with(guild_id, state)
                self.assertEqual(panel_lock_states, [False])

            voice.move_to.assert_awaited_once_with(target_channel)
            voice.disconnect.assert_awaited_once_with(force=True)
            self.assertTrue(voice.force)
            voice.cleanup.assert_called_once_with()
            self.assertIsNone(state.voice)
            self.assertIsNone(guild.voice_client)
            self.assertEqual(
                state.playback_generation,
                original_generation + 1,
            )
            self.assertFalse(state.voice_connect_lock.locked())
            self.assertFalse(bot.voice_operation_tasks)
        finally:
            release_cleanup.set()
            if movement is not None and not movement.done():
                movement.cancel()
            if movement is not None:
                await asyncio.gather(movement, return_exceptions=True)
            bot.cancel_empty_channel_disconnect(state)
            bot.music_states.pop(guild_id, None)

    async def test_non_move_voice_paths_do_not_reset_or_disconnect(
        self,
    ) -> None:
        cases = (
            ("current", True, False, False, False, False),
            ("queue", False, True, False, False, False),
            ("playing", False, False, True, False, False),
            ("paused", False, False, False, True, False),
            ("same-channel", False, False, False, False, True),
        )
        for offset, (
            case_name,
            has_current,
            has_queue,
            playing,
            paused,
            same_channel,
        ) in enumerate(cases):
            with self.subTest(case=case_name):
                guild_id = 821 + offset
                old_channel = MagicMock(
                    id=1421 + offset,
                    mention=f"<#{1421 + offset}>",
                )
                target_channel = (
                    old_channel
                    if same_channel
                    else MagicMock(
                        id=1521 + offset,
                        mention=f"<#{1521 + offset}>",
                    )
                )
                voice = MagicMock(channel=old_channel)
                voice.is_connected.return_value = True
                voice.is_playing.return_value = playing
                voice.is_paused.return_value = paused
                voice.move_to = AsyncMock()
                voice.disconnect = AsyncMock()
                voice.cleanup = MagicMock()
                guild = MagicMock(id=guild_id, voice_client=voice)
                requester = MagicMock(
                    bot=False,
                    guild=guild,
                    voice=MagicMock(channel=target_channel),
                )
                old_channel.members = [requester]
                state = bot.get_state(guild_id)
                state.voice = voice
                current = make_track(f"current-{case_name}") if has_current else None
                queued = make_track(f"queued-{case_name}") if has_queue else None
                state.current = current
                if queued is not None:
                    state.queue.append(queued)
                original_generation = state.playback_generation

                try:
                    with patch.object(
                        bot,
                        "show_idle_panel",
                        new=AsyncMock(),
                    ) as show_idle_panel:
                        result = await bot.ensure_voice_for_member(requester, state)

                    expected = (
                        (True, None)
                        if same_channel
                        else (
                            False,
                            f"봇이 이미 {old_channel.mention}에서 재생 중이에요. "
                            "같은 음성 채널에 들어와 주세요.",
                        )
                    )
                    self.assertEqual(result, expected)
                    self.assertEqual(
                        state.playback_generation,
                        original_generation,
                    )
                    self.assertIs(state.current, current)
                    self.assertEqual(list(state.queue), [queued] if queued else [])
                    self.assertIs(state.voice, voice)
                    voice.stop.assert_not_called()
                    voice.move_to.assert_not_awaited()
                    voice.disconnect.assert_not_awaited()
                    voice.cleanup.assert_not_called()
                    show_idle_panel.assert_not_awaited()
                    self.assertFalse(bot.voice_operation_tasks)
                finally:
                    bot.cancel_empty_channel_disconnect(state)
                    bot.music_states.pop(guild_id, None)

    async def test_unexpected_voice_move_error_cleans_up_before_rethrowing(
        self,
    ) -> None:
        guild_id = 826
        old_channel = MagicMock(id=1426, mention="<#1426>", members=[])
        target_channel = MagicMock(id=1526, mention="<#1526>", members=[])
        move_error = RuntimeError("unexpected move failure")
        voice = MagicMock(channel=old_channel)
        voice.is_connected.return_value = True
        voice.is_playing.return_value = False
        voice.is_paused.return_value = False
        voice.move_to = AsyncMock(side_effect=move_error)
        voice.disconnect = AsyncMock()
        guild = MagicMock(id=guild_id, voice_client=voice)
        voice.cleanup = MagicMock(
            side_effect=lambda: setattr(guild, "voice_client", None)
        )
        requester = MagicMock(
            bot=False,
            guild=guild,
            voice=MagicMock(channel=target_channel),
        )
        state = bot.get_state(guild_id)
        state.voice = voice
        original_generation = state.playback_generation
        panel_started = asyncio.Event()
        panel_lock_states: list[bool] = []

        async def record_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_lock_states.append(state.voice_connect_lock.locked())
            panel_started.set()

        try:
            with patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=record_panel),
            ) as show_idle_panel:
                with self.assertRaises(RuntimeError) as raised:
                    await bot.ensure_voice_for_member(requester, state)
                self.assertIs(raised.exception, move_error)
                await asyncio.wait_for(panel_started.wait(), timeout=1)
                show_idle_panel.assert_awaited_once_with(guild_id, state)

            self.assertEqual(panel_lock_states, [False])
            self.assertEqual(
                state.playback_generation,
                original_generation + 1,
            )
            self.assertIsNone(state.voice)
            self.assertIsNone(guild.voice_client)
            voice.move_to.assert_awaited_once_with(target_channel)
            voice.disconnect.assert_awaited_once_with(force=True)
            voice.cleanup.assert_called_once_with()
            self.assertFalse(bot.voice_operation_tasks)
        finally:
            bot.cancel_empty_channel_disconnect(state)
            bot.music_states.pop(guild_id, None)

    async def test_voice_move_replaces_empty_timer_after_member_leaves(
        self,
    ) -> None:
        guild_id = 817
        move_started = asyncio.Event()
        release_move = asyncio.Event()

        class Member:
            def __init__(self, *, bot_member: bool) -> None:
                self.bot = bot_member

        class Channel:
            def __init__(
                self,
                channel_id: int,
                members: list[Member],
            ) -> None:
                self.id = channel_id
                self.members = members
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1201, [Member(bot_member=True)])
        new_channel = Channel(1202, [])

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.move_to = AsyncMock(side_effect=self._move_to)

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

            async def _move_to(self, channel: Channel) -> None:
                move_started.set()
                await release_move.wait()
                self.channel = channel

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()

        class Requester(Member):
            pass

        requester = Requester(bot_member=False)
        requester.guild = guild
        requester.voice = type("MemberVoice", (), {"channel": new_channel})()
        new_channel.members.append(requester)
        state = bot.get_state(guild_id)
        state.voice = voice
        movement = None
        old_timer = None
        new_timer = None

        with patch.object(bot, "EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS", 60):
            try:
                bot.update_empty_channel_disconnect(state, guild_id)
                old_timer = state.empty_channel_task
                self.assertIsNotNone(old_timer)

                movement = asyncio.create_task(
                    bot.ensure_voice_for_member(requester, state)
                )
                await asyncio.wait_for(move_started.wait(), timeout=1)

                new_channel.members.clear()
                requester.voice = type("MemberVoice", (), {"channel": None})()
                before = type("VoiceState", (), {"channel": new_channel})()
                after = type("VoiceState", (), {"channel": None})()
                await bot.on_voice_state_update(requester, before, after)
                self.assertIs(state.empty_channel_task, old_timer)

                release_move.set()
                result = await asyncio.wait_for(movement, timeout=1)

                self.assertEqual(result, (True, None))
                voice.move_to.assert_awaited_once_with(new_channel)
                self.assertIs(voice.channel, new_channel)
                self.assertFalse(new_channel.members)
                new_timer = state.empty_channel_task
                self.assertIsNotNone(new_timer)
                self.assertIsNot(new_timer, old_timer)
                self.assertFalse(new_timer.done())
            finally:
                release_move.set()
                if movement is not None and not movement.done():
                    movement.cancel()
                if movement is not None:
                    await asyncio.gather(movement, return_exceptions=True)
                timers = {
                    task
                    for task in (
                        old_timer,
                        new_timer,
                        state.empty_channel_task,
                    )
                    if task is not None
                }
                bot.cancel_empty_channel_disconnect(state)
                for task in timers:
                    if not task.done():
                        task.cancel()
                if timers:
                    await asyncio.gather(*timers, return_exceptions=True)
                bot.music_states.pop(guild_id, None)

    async def test_external_bot_move_replaces_empty_channel_timer(self) -> None:
        guild_id = 819
        old_timer_started = asyncio.Event()
        new_timer_started = asyncio.Event()
        release_timers = asyncio.Event()
        captured_channel_ids: list[int] = []

        class Guild:
            id = guild_id
            voice_client = None

        guild = Guild()

        class Member:
            bot = True
            id = 9101

        member = Member()
        member.guild = guild

        class Channel:
            def __init__(self, channel_id: int) -> None:
                self.id = channel_id
                self.members: list[Member] = []

        old_channel = Channel(1301)
        new_channel = Channel(1302)
        old_channel.members.append(member)

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        voice = Voice()
        guild.voice_client = voice
        state = bot.get_state(guild_id)
        state.voice = voice
        initial_generation = state.playback_generation
        old_timer = None
        new_timer = None

        async def block_empty_disconnect(
            requested_guild_id: int,
            channel_id: int,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            captured_channel_ids.append(channel_id)
            if len(captured_channel_ids) == 1:
                old_timer_started.set()
            elif len(captured_channel_ids) == 2:
                new_timer_started.set()
            await release_timers.wait()

        with (
            patch.object(
                bot,
                "disconnect_from_empty_channel",
                new=AsyncMock(side_effect=block_empty_disconnect),
            ) as disconnect_from_empty_channel,
            patch.object(bot.bot._connection, "user", member),
        ):
            try:
                bot.update_empty_channel_disconnect(state, guild_id)
                old_timer = state.empty_channel_task
                self.assertIsNotNone(old_timer)
                await asyncio.wait_for(old_timer_started.wait(), timeout=1)

                old_channel.members.clear()
                new_channel.members.append(member)
                voice.channel = new_channel
                before = type("VoiceState", (), {"channel": old_channel})()
                after = type("VoiceState", (), {"channel": new_channel})()

                await asyncio.wait_for(
                    bot.on_voice_state_update(member, before, after),
                    timeout=1,
                )
                new_timer = state.empty_channel_task

                self.assertIsNotNone(new_timer)
                self.assertIsNot(new_timer, old_timer)
                self.assertFalse(new_timer.done())
                await asyncio.wait_for(new_timer_started.wait(), timeout=1)
                await asyncio.wait_for(
                    asyncio.gather(old_timer, return_exceptions=True),
                    timeout=1,
                )

                self.assertTrue(old_timer.cancelled())
                self.assertIs(state.empty_channel_task, new_timer)
                self.assertFalse(new_timer.done())
                self.assertEqual(captured_channel_ids, [1301, 1302])
                self.assertEqual(disconnect_from_empty_channel.await_count, 2)
                self.assertIs(bot.music_states[guild_id], state)
                self.assertIs(state.voice, voice)
                self.assertIs(voice.channel, new_channel)
                self.assertEqual(state.playback_generation, initial_generation)
            finally:
                release_timers.set()
                timers = {
                    task
                    for task in (
                        old_timer,
                        new_timer,
                        state.empty_channel_task,
                    )
                    if task is not None
                }
                bot.cancel_empty_channel_disconnect(state)
                for task in timers:
                    if not task.done():
                        task.cancel()
                if timers:
                    await asyncio.wait_for(
                        asyncio.gather(*timers, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(guild_id, None)

    async def test_stale_bot_disconnect_keeps_replacement_voice_state(self) -> None:
        guild_id = 820
        guild = MagicMock(id=guild_id, voice_client=None)
        member = MagicMock(bot=True, id=9201, guild=guild)
        member.voice = type("MemberVoice", (), {"channel": None})()
        old_channel = MagicMock(id=1401, members=[member])
        replacement_channel = MagicMock(id=1402, members=[member])
        old_voice = MagicMock(channel=old_channel)
        replacement_voice = MagicMock(channel=replacement_channel)
        for voice in (old_voice, replacement_voice):
            voice.is_connected.return_value = True
            voice.is_playing.return_value = True
            voice.is_paused.return_value = False
        guild.voice_client = old_voice
        state = bot.get_state(guild_id)
        state.voice = old_voice
        timer_started = asyncio.Event()
        release_timer = asyncio.Event()

        async def hold_active_timer() -> None:
            timer_started.set()
            await release_timer.wait()

        timer = asyncio.create_task(hold_active_timer())
        state.empty_channel_task = timer
        handler_task = None
        test_holds_lock = False

        with (
            patch.object(bot, "show_idle_panel", new=AsyncMock()) as show_idle_panel,
            patch.object(bot.bot._connection, "user", member),
        ):
            try:
                await asyncio.wait_for(timer_started.wait(), timeout=1)
                await state.voice_connect_lock.acquire()
                test_holds_lock = True
                before = type("VoiceState", (), {"channel": old_channel})()
                after = type("VoiceState", (), {"channel": None})()
                handler_task = asyncio.create_task(
                    bot.on_voice_state_update(member, before, after)
                )
                await asyncio.sleep(0)
                self.assertFalse(handler_task.done())

                replacement_current = make_track("replacement current")
                replacement_queued = make_track("replacement queued")
                replacement_generation = state.playback_generation + 7
                state.voice = replacement_voice
                state.current = replacement_current
                state.queue.clear()
                state.queue.append(replacement_queued)
                state.playback_generation = replacement_generation

                state.voice_connect_lock.release()
                test_holds_lock = False
                await asyncio.wait_for(handler_task, timeout=1)

                self.assertIs(state.voice, replacement_voice)
                self.assertIs(state.current, replacement_current)
                self.assertEqual(list(state.queue), [replacement_queued])
                self.assertEqual(
                    state.playback_generation,
                    replacement_generation,
                )
                self.assertIs(state.empty_channel_task, timer)
                self.assertFalse(timer.done())
                self.assertFalse(timer.cancelled())
                old_voice.stop.assert_not_called()
                replacement_voice.stop.assert_not_called()
                show_idle_panel.assert_not_awaited()
            finally:
                if test_holds_lock:
                    state.voice_connect_lock.release()
                release_timer.set()
                bot.cancel_empty_channel_disconnect(state)
                for task in (handler_task, timer):
                    if task is not None and not task.done():
                        task.cancel()
                tasks = [
                    task
                    for task in (handler_task, timer)
                    if task is not None
                ]
                if tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=1,
                    )
                bot.music_states.pop(guild_id, None)

    async def test_stale_bot_disconnect_keeps_reconnected_same_voice(self) -> None:
        guild_id = 822
        guild = MagicMock(id=guild_id, voice_client=None)
        member = MagicMock(bot=True, id=9401, guild=guild)
        member.voice = type("MemberVoice", (), {"channel": None})()
        disconnected_channel = MagicMock(id=1601)
        reconnected_channel = MagicMock(id=1602)
        voice = MagicMock(channel=disconnected_channel)
        voice.is_playing.return_value = True
        voice.is_paused.return_value = False
        guild.voice_client = voice

        state = bot.get_state(guild_id)
        state.voice = voice
        current = make_track("reconnected current")
        queued = make_track("reconnected queued")
        state.current = current
        state.queue.append(queued)
        generation = state.playback_generation
        handler_task = None
        test_holds_lock = False

        with (
            patch.object(bot, "show_idle_panel", new=AsyncMock()) as show_idle_panel,
            patch.object(bot.bot._connection, "user", member),
        ):
            try:
                await state.voice_connect_lock.acquire()
                test_holds_lock = True
                before = type(
                    "VoiceState",
                    (),
                    {"channel": disconnected_channel},
                )()
                after = type("VoiceState", (), {"channel": None})()
                handler_task = asyncio.create_task(
                    bot.on_voice_state_update(member, before, after)
                )
                await asyncio.sleep(0)
                self.assertFalse(handler_task.done())

                member.voice = type(
                    "MemberVoice",
                    (),
                    {"channel": reconnected_channel},
                )()
                voice.channel = reconnected_channel
                state.voice_connect_lock.release()
                test_holds_lock = False
                await asyncio.wait_for(handler_task, timeout=1)

                self.assertIs(state.voice, voice)
                self.assertIs(state.current, current)
                self.assertEqual(list(state.queue), [queued])
                self.assertEqual(state.playback_generation, generation)
                voice.stop.assert_not_called()
                show_idle_panel.assert_not_awaited()
            finally:
                if test_holds_lock:
                    state.voice_connect_lock.release()
                if handler_task is not None and not handler_task.done():
                    handler_task.cancel()
                if handler_task is not None:
                    await asyncio.gather(handler_task, return_exceptions=True)
                bot.music_states.pop(guild_id, None)

    async def test_external_bot_disconnect_cancels_pending_message_request(
        self,
    ) -> None:
        guild_id = 821
        extract_started = asyncio.Event()
        release_extract = asyncio.Event()
        channel = MagicMock(id=1501, mention="<#1501>", members=[])
        guild = MagicMock(id=guild_id, voice_client=None)
        channel.guild = guild
        bot_member = MagicMock(bot=True, id=9301, guild=guild)
        bot_member.voice = type("MemberVoice", (), {"channel": channel})()

        class Requester:
            bot = False
            id = 9302
            display_name = "requester"

        requester = Requester()
        requester.guild = guild
        requester.voice = type("MemberVoice", (), {"channel": channel})()
        channel.members = [bot_member, requester]
        voice = MagicMock(channel=channel)
        voice.is_connected.return_value = True
        voice.is_playing.return_value = True
        voice.is_paused.return_value = False

        def stop_voice() -> None:
            voice.is_playing.return_value = False

        voice.stop.side_effect = stop_voice
        guild.voice_client = voice
        state = bot.get_state(guild_id)
        state.voice = voice
        state.current = make_track("current")
        state.queue.append(make_track("queued"))
        initial_generation = state.playback_generation

        loading_message = MagicMock()
        loading_message.edit = AsyncMock()
        message = MagicMock()
        message.author = requester
        message.guild = guild
        message.channel = channel
        message.content = "late song"
        message.reply = AsyncMock(return_value=loading_message)

        late_track = make_track("late")
        enqueue_results: list[bool] = []
        original_enqueue_tracks = bot.enqueue_tracks
        panel_lock_states: list[bool] = []

        async def delayed_extract(*_args: object, **_kwargs: object) -> bot.Track:
            extract_started.set()
            await release_extract.wait()
            return late_track

        async def capture_enqueue_result(*args: object, **kwargs: object) -> bool:
            self.assertEqual(
                kwargs.get("request_generation"),
                initial_generation,
            )
            result = await original_enqueue_tracks(*args, **kwargs)
            enqueue_results.append(result)
            return result

        async def record_idle_panel(*_args: object) -> None:
            panel_lock_states.append(state.voice_connect_lock.locked())

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        request_task = None
        empty_timer = None
        with (
            patch.object(bot.discord, "Member", Requester),
            patch.object(bot, "get_music_channel_id", return_value=channel.id),
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            patch.object(
                music_discord_display,
                "MUSIC_CHANNEL_DELETE_REQUESTS",
                False,
            ),
            patch.object(bot, "EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS", 60),
            patch.object(bot, "extract_track", side_effect=delayed_extract),
            patch.object(bot, "enqueue_tracks", side_effect=capture_enqueue_result),
            patch.object(
                bot, "schedule_play_next", return_value=(None, False)
            ) as schedule_play_next,
            patch.object(bot, "schedule_autoplay_refill") as schedule_autoplay_refill,
            patch.object(bot, "show_idle_panel", side_effect=record_idle_panel) as show_idle_panel,
            patch.object(bot.bot, "process_commands", new=AsyncMock()) as process_commands,
            patch.object(bot, "create_housekeeping_task", side_effect=discard_housekeeping),
            patch.object(bot.bot._connection, "user", bot_member),
        ):
            try:
                request_task = asyncio.create_task(bot.on_message(message))
                await asyncio.wait_for(extract_started.wait(), timeout=1)

                channel.members = [bot_member]
                requester.voice = type("MemberVoice", (), {"channel": None})()
                bot.update_empty_channel_disconnect(state, guild_id)
                empty_timer = state.empty_channel_task
                self.assertIsNotNone(empty_timer)

                bot_member.voice = type("MemberVoice", (), {"channel": None})()
                before = type("VoiceState", (), {"channel": channel})()
                after = type("VoiceState", (), {"channel": None})()
                await asyncio.wait_for(
                    bot.on_voice_state_update(bot_member, before, after),
                    timeout=1,
                )

                self.assertIs(state.empty_channel_task, empty_timer)
                self.assertFalse(empty_timer.done())
                self.assertFalse(empty_timer.cancelled())
                self.assertEqual(
                    state.playback_generation,
                    initial_generation + 1,
                )
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                self.assertIs(state.voice, voice)
                voice.stop.assert_called_once_with()
                show_idle_panel.assert_awaited_once_with(guild_id, state)
                self.assertEqual(panel_lock_states, [False])

                release_extract.set()
                await asyncio.wait_for(request_task, timeout=1)

                self.assertEqual(enqueue_results, [False])
                self.assertFalse(state.queue)
                schedule_play_next.assert_not_called()
                schedule_autoplay_refill.assert_not_called()
                loading_message.edit.assert_awaited_once_with(
                    content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요.",
                    embed=None,
                    view=None,
                )
                process_commands.assert_awaited_once_with(message)
            finally:
                release_extract.set()
                if request_task is not None and not request_task.done():
                    request_task.cancel()
                if request_task is not None:
                    await asyncio.gather(request_task, return_exceptions=True)
                timers = {
                    task
                    for task in (empty_timer, state.empty_channel_task)
                    if task is not None
                }
                bot.cancel_empty_channel_disconnect(state)
                for task in timers:
                    if not task.done():
                        task.cancel()
                if timers:
                    await asyncio.gather(*timers, return_exceptions=True)
                bot.music_states.pop(guild_id, None)

    async def test_cross_channel_move_cancels_pending_request_and_updates_panel_in_background(
        self,
    ) -> None:
        guild_id = 818
        extract_started = asyncio.Event()
        release_extract = asyncio.Event()
        move_started = asyncio.Event()
        release_move = asyncio.Event()
        convergence_started = asyncio.Event()
        release_convergence = asyncio.Event()

        class Channel:
            def __init__(self, channel_id: int) -> None:
                self.id = channel_id
                self.members = []
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1301)
        new_channel = Channel(1302)

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.playing = False
                self.move_to = AsyncMock(side_effect=self._move_to)
                self.disconnect = AsyncMock()
                self.cleanup = MagicMock()
                self.stop = MagicMock(side_effect=self._stop)

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            async def _move_to(self, channel: Channel) -> None:
                move_started.set()
                await release_move.wait()
                self.channel = channel

            def _stop(self) -> None:
                self.playing = False

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()

        class OldRequester:
            display_name = "old-channel-requester"
            id = 1818

        class MovingMember:
            bot = False
            display_name = "new-channel-requester"
            id = 2818
            voice = type("MemberVoice", (), {"channel": new_channel})()

        moving_member = MovingMember()
        moving_member.guild = guild
        new_channel.members.append(moving_member)

        state = bot.get_state(guild_id)
        state.voice = voice
        original_generation = state.playback_generation
        track = make_track("old-channel-result")
        loading_message = MagicMock()
        loading_message.edit = AsyncMock()
        panel_currents: list[bot.Track | None] = []
        panel_lock_states: list[bool] = []
        created_housekeeping_tasks: list[asyncio.Task] = []

        async def delayed_extract(*_args: object) -> bot.Track:
            extract_started.set()
            await release_extract.wait()
            return track

        async def record_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
            *,
            channel: object = None,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            self.assertIsNone(channel)
            panel_currents.append(requested_state.current)
            panel_lock_states.append(requested_state.voice_connect_lock.locked())
            convergence_started.set()
            await release_convergence.wait()

        original_create_housekeeping_task = bot.create_housekeeping_task

        def track_housekeeping(coroutine):
            task = original_create_housekeeping_task(coroutine)
            if task is not None:
                created_housekeeping_tasks.append(task)
            return task

        async def move_and_capture() -> tuple[tuple[bool, str | None], int]:
            result = await bot.ensure_voice_for_member(moving_member, state)
            return result, state.playback_generation

        request_task = None
        movement = None
        with (
            patch.object(bot, "extract_track", side_effect=delayed_extract),
            patch.object(
                bot,
                "schedule_play_next",
                return_value=(None, False),
            ) as schedule_play_next,
            patch.object(bot, "_update_control_panel", side_effect=record_panel),
            patch.object(bot, "delete_message_later", new=AsyncMock()),
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=track_housekeeping,
            ),
        ):
            try:
                request_task = asyncio.create_task(
                    bot.enqueue_tracks(
                        guild_id,
                        MagicMock(),
                        OldRequester(),
                        "old channel song",
                        initial_response=loading_message,
                        request_generation=original_generation,
                    )
                )
                await asyncio.wait_for(extract_started.wait(), timeout=1)

                movement = asyncio.create_task(move_and_capture())
                await asyncio.wait_for(move_started.wait(), timeout=1)

                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertFalse(movement.done())

                release_extract.set()
                self.assertFalse(await asyncio.wait_for(request_task, timeout=1))
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                schedule_play_next.assert_not_called()
                loading_message.edit.assert_awaited_once_with(
                    content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요.",
                    embed=None,
                    view=None,
                )
                self.assertFalse(movement.done())

                release_move.set()
                await asyncio.wait_for(convergence_started.wait(), timeout=1)

                self.assertTrue(movement.done())
                move_result, move_generation = await movement
                self.assertEqual(move_result, (True, None))
                self.assertEqual(move_generation, original_generation + 1)
                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                self.assertFalse(voice.is_playing())
                voice.stop.assert_not_called()
                voice.disconnect.assert_not_awaited()
                voice.cleanup.assert_not_called()
                self.assertIs(voice.channel, new_channel)
                self.assertFalse(state.voice_connect_lock.locked())
                self.assertEqual(panel_currents, [None])
                self.assertEqual(panel_lock_states, [False])

                active_housekeeping = {
                    task
                    for task in created_housekeeping_tasks
                    if task in bot.housekeeping_tasks and not task.done()
                }
                self.assertEqual(len(active_housekeeping), 1)
                convergence_task = next(iter(active_housekeeping))
                self.assertFalse(convergence_task.done())

                release_convergence.set()
                await asyncio.wait_for(convergence_task, timeout=1)
                await asyncio.sleep(0)
                self.assertNotIn(convergence_task, bot.housekeeping_tasks)
            finally:
                release_extract.set()
                release_move.set()
                release_convergence.set()
                for task in (request_task, movement, *created_housekeeping_tasks):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(
                    *(
                        task
                        for task in (
                            request_task,
                            movement,
                            *created_housekeeping_tasks,
                        )
                        if task is not None
                    ),
                    return_exceptions=True,
                )
                await asyncio.sleep(0)
                bot.clear_pending_playback_advance(state)
                bot.cancel_empty_channel_disconnect(state)
                bot.music_states.pop(guild_id, None)

        self.assertFalse(
            set(created_housekeeping_tasks) & bot.housekeeping_tasks
        )

    async def test_connect_race_adopts_discord_registered_voice_client(self) -> None:
        class Guild:
            id = 811
            voice_client = None

        guild = Guild()

        class Channel:
            mention = "#voice"

            def __init__(self) -> None:
                self.connect_calls = 0

            async def connect(self) -> object:
                self.connect_calls += 1
                guild.voice_client = voice
                raise bot.discord.ClientException(
                    "Already connected to a voice channel."
                )

        class Voice:
            def __init__(self, channel: Channel) -> None:
                self.channel = channel

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

        channel = Channel()
        voice = Voice(channel)

        class Member:
            bot = False

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
        channel.members = [member]
        state = bot.GuildMusicState()

        result = await bot.ensure_voice_for_member(member, state)

        self.assertEqual(result, (True, None))
        self.assertEqual(channel.connect_calls, 1)
        self.assertIs(state.voice, voice)

    async def test_empty_channel_timer_does_not_disconnect_voice_moved_during_panel_update(
        self,
    ) -> None:
        guild_id = 815
        panel_started = asyncio.Event()
        release_panel = asyncio.Event()

        class Member:
            def __init__(self, *, bot_member: bool) -> None:
                self.bot = bot_member

        class Channel:
            def __init__(
                self,
                channel_id: int,
                members: list[Member],
            ) -> None:
                self.id = channel_id
                self.members = members
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1001, [Member(bot_member=True)])
        new_channel = Channel(1002, [Member(bot_member=False)])

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.connected = True
                self.move_to = AsyncMock(side_effect=self._move_to)
                self.disconnect = AsyncMock(side_effect=self._disconnect)

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

            async def _move_to(self, channel: Channel) -> None:
                self.channel = channel

            async def _disconnect(self) -> None:
                self.connected = False

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()
        state = bot.get_state(guild_id)
        state.voice = voice

        async def block_idle_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_started.set()
            await release_panel.wait()

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        timer = None
        with (
            patch.object(bot, "EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS", 0),
            patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=block_idle_panel),
            ) as show_idle_panel,
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ),
        ):
            try:
                bot.update_empty_channel_disconnect(state, guild_id)
                timer = state.empty_channel_task
                self.assertIsNotNone(timer)
                await asyncio.wait_for(panel_started.wait(), timeout=1)

                result = await asyncio.wait_for(
                    bot.ensure_voice_channel(guild, new_channel, state),
                    timeout=1,
                )

                self.assertEqual(result, (True, None))
                voice.move_to.assert_awaited_once_with(new_channel)
                voice.disconnect.assert_not_awaited()
                self.assertIs(voice.channel, new_channel)

                release_panel.set()
                await asyncio.wait_for(
                    asyncio.gather(timer, return_exceptions=True),
                    timeout=1,
                )
            finally:
                release_panel.set()
                bot.cancel_empty_channel_disconnect(state)
                if timer is not None:
                    await asyncio.gather(timer, return_exceptions=True)
                bot.music_states.pop(guild_id, None)

        show_idle_panel.assert_awaited_once_with(guild_id, state)
        voice.disconnect.assert_not_awaited()
        self.assertTrue(voice.is_connected())
        self.assertIs(state.voice, voice)
        self.assertIs(voice.channel, new_channel)
        self.assertIsNone(state.empty_channel_task)



    async def test_leave_disconnects_before_accepting_request_during_panel_update(
        self,
    ) -> None:
        guild_id = 816
        disconnect_started = asyncio.Event()
        release_disconnect = asyncio.Event()
        panel_started = asyncio.Event()
        release_panel = asyncio.Event()

        class Channel:
            id = 1101
            mention = "<#1101>"

        channel = Channel()

        class Voice:
            def __init__(self, *, playing: bool = False) -> None:
                self.channel = channel
                self.connected = True
                self.playing = playing
                self.disconnect = AsyncMock()

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def stop(self) -> None:
                self.playing = False

        old_voice = Voice(playing=True)
        new_voice = Voice()

        class Guild:
            id = guild_id
            voice_client = old_voice

        guild = Guild()

        async def disconnect_old_voice() -> None:
            disconnect_started.set()
            self.assertTrue(state.voice_connect_lock.locked())
            await release_disconnect.wait()
            old_voice.connected = False
            guild.voice_client = None

        async def connect_new_voice() -> Voice:
            guild.voice_client = new_voice
            return new_voice

        old_voice.disconnect.side_effect = disconnect_old_voice
        channel.connect = AsyncMock(side_effect=connect_new_voice)

        class Requester:
            bot = False
            display_name = "requester"
            id = 8160
            voice = type("MemberVoice", (), {"channel": channel})()

        requester = Requester()
        requester.guild = guild
        channel.members = [requester]

        defer_lock_states: list[bool] = []

        async def record_defer() -> None:
            defer_lock_states.append(state.voice_connect_lock.locked())

        edit_response = MagicMock(status=500, reason="Internal Server Error")
        edit_error = bot.discord.DiscordServerError(
            edit_response,
            "<html>temporary failure</html>",
        )
        interaction = MagicMock()
        interaction.guild_id = guild_id
        interaction.user = requester
        interaction.response.defer = AsyncMock(side_effect=record_defer)
        interaction.response.send_message = AsyncMock()
        interaction.response.is_done.return_value = False
        interaction.edit_original_response = AsyncMock(side_effect=edit_error)

        state = bot.get_state(guild_id)
        state.voice = old_voice
        state.current = make_track("current")
        state.queue.append(make_track("queued"))
        original_generation = state.playback_generation

        async def accept_request() -> tuple[tuple[bool, str | None], int]:
            result = await bot.ensure_voice_for_member(requester, state)
            return result, state.playback_generation

        async def block_idle_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_started.set()
            await release_panel.wait()

        leave_task = None
        request_task = None
        with patch.object(
            bot,
            "show_idle_panel",
            new=AsyncMock(side_effect=block_idle_panel),
        ) as show_idle_panel:
            try:
                leave_task = asyncio.create_task(bot.leave.callback(interaction))
                await asyncio.wait_for(disconnect_started.wait(), timeout=1)

                interaction.response.defer.assert_awaited_once_with()
                self.assertEqual(defer_lock_states, [False])
                interaction.response.send_message.assert_not_awaited()
                interaction.edit_original_response.assert_not_awaited()
                self.assertEqual(
                    state.playback_generation,
                    original_generation + 1,
                )
                self.assertIs(state.voice, old_voice)
                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                self.assertFalse(old_voice.is_playing())
                self.assertFalse(leave_task.done())

                request_task = asyncio.create_task(accept_request())
                await asyncio.sleep(0)
                self.assertFalse(request_task.done())
                channel.connect.assert_not_awaited()

                release_disconnect.set()
                await asyncio.wait_for(panel_started.wait(), timeout=1)
                interaction.edit_original_response.assert_awaited_once_with(
                    content="음성 채널에서 나왔어요."
                )
                interaction.response.send_message.assert_not_awaited()
                self.assertFalse(leave_task.done())
                result, request_generation = await asyncio.wait_for(
                    request_task,
                    timeout=1,
                )

                self.assertEqual(result, (True, None))
                self.assertEqual(
                    request_generation,
                    original_generation + 1,
                )
                channel.connect.assert_awaited_once_with()
                self.assertIs(state.voice, new_voice)

                release_panel.set()
                with self.assertRaises(bot.discord.DiscordServerError) as raised:
                    await asyncio.wait_for(leave_task, timeout=1)
                self.assertIs(raised.exception, edit_error)
            finally:
                release_disconnect.set()
                release_panel.set()
                for task in (leave_task, request_task):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(
                    *(
                        task
                        for task in (leave_task, request_task)
                        if task is not None
                    ),
                    return_exceptions=True,
                )
                bot.cancel_empty_channel_disconnect(state)
                bot.music_states.pop(guild_id, None)

        show_idle_panel.assert_awaited_once_with(guild_id, state)
        old_voice.disconnect.assert_awaited_once_with()
        new_voice.disconnect.assert_not_awaited()
        self.assertTrue(new_voice.is_connected())
        self.assertIs(state.voice, new_voice)
        self.assertIsNone(state.empty_channel_task)
        interaction.response.send_message.assert_not_awaited()
        interaction.edit_original_response.assert_awaited_once_with(
            content="음성 채널에서 나왔어요."
        )

    async def test_stale_registered_voice_is_cleaned_before_reconnecting(self) -> None:
        class Guild:
            id = 812
            voice_client = None

        guild = Guild()

        class Channel:
            mention = "#voice"

            def __init__(self) -> None:
                self.connect_calls = 0

            async def connect(self) -> object:
                self.connect_calls += 1
                guild.voice_client = fresh_voice
                return fresh_voice

        class Voice:
            def __init__(self, channel: Channel, *, connected: bool) -> None:
                self.channel = channel
                self.connected = connected
                self.disconnect_calls = 0
                self.cleanup_calls = 0

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return False

            def is_paused(self) -> bool:
                return False

            async def disconnect(self, *, force: bool = False) -> None:
                self.disconnect_calls += 1
                self.assert_force = force

            def cleanup(self) -> None:
                self.cleanup_calls += 1
                guild.voice_client = None

        channel = Channel()
        stale_voice = Voice(channel, connected=False)
        fresh_voice = Voice(channel, connected=True)
        guild.voice_client = stale_voice

        class Member:
            bot = False

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
        channel.members = [member]
        state = bot.GuildMusicState(voice=stale_voice)

        with patch.object(
            bot,
            "wait_for_voice_connection",
            new=AsyncMock(return_value=False),
        ) as wait_for_connection:
            result = await bot.ensure_voice_for_member(member, state)

        self.assertEqual(result, (True, None))
        wait_for_connection.assert_awaited_once_with(stale_voice)
        self.assertEqual(stale_voice.disconnect_calls, 1)
        self.assertTrue(stale_voice.assert_force)
        self.assertEqual(stale_voice.cleanup_calls, 1)
        self.assertEqual(channel.connect_calls, 1)
        self.assertIs(state.voice, fresh_voice)

    async def test_inflight_voice_connect_cannot_escape_shutdown(self) -> None:
        class Guild:
            id = 813
            voice_client = None

        guild = Guild()
        connect_started = asyncio.Event()
        cancellation_seen = asyncio.Event()
        release_connect = asyncio.Event()

        class Voice:
            def __init__(self) -> None:
                self.disconnect_calls = 0
                self.cleanup_calls = 0

            async def disconnect(self, *, force: bool = False) -> None:
                self.disconnect_calls += 1
                self.force = force

            def cleanup(self) -> None:
                self.cleanup_calls += 1
                guild.voice_client = None

        voice = Voice()

        class Channel:
            mention = "#voice"

            async def connect(self) -> object:
                connect_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancellation_seen.set()
                    await release_connect.wait()
                guild.voice_client = voice
                return voice

        channel = Channel()

        class Member:
            pass

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
        state = bot.GuildMusicState()
        connection = asyncio.create_task(
            bot.ensure_voice_for_member(member, state)
        )
        await connect_started.wait()

        async def base_close(_self: object) -> None:
            return None

        with (
            patch.object(
                bot,
                "cancel_music_background_tasks_for_shutdown",
                new=AsyncMock(),
            ),
            patch.object(bot, "shutdown_auxiliary_operations", new=AsyncMock()),
            patch.object(bot.ytdl_scheduler, "shutdown", new=AsyncMock()),
            patch.object(bot, "shutdown_auxiliary_workers", new=AsyncMock()),
            patch.object(bot, "shutdown_lyrics_executor", new=AsyncMock()),
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            close_task = asyncio.create_task(bot.MusicBot.close(bot.bot))
            await cancellation_seen.wait()

            self.assertFalse(close_task.done())
            release_connect.set()
            result = await connection
            await close_task

        self.assertFalse(result[0])
        self.assertIsNone(state.voice)
        self.assertIsNone(guild.voice_client)
        self.assertEqual(voice.disconnect_calls, 1)
        self.assertTrue(voice.force)
        self.assertEqual(voice.cleanup_calls, 1)
        self.assertFalse(bot.voice_operation_tasks)

    async def test_shutdown_gate_prevents_voice_move(self) -> None:
        class Guild:
            id = 814
            voice_client = None

        guild = Guild()
        target_channel = MagicMock()
        existing_channel = MagicMock()

        class Voice:
            channel = existing_channel

            @staticmethod
            def is_connected() -> bool:
                return True

            @staticmethod
            def is_playing() -> bool:
                return False

            @staticmethod
            def is_paused() -> bool:
                return False

            move_to = AsyncMock()

        voice = Voice()
        guild.voice_client = voice
        state = bot.GuildMusicState(voice=voice)
        bot.begin_bot_shutdown()

        result = await bot.ensure_voice_channel(guild, target_channel, state)

        self.assertFalse(result[0])
        voice.move_to.assert_not_awaited()
        self.assertFalse(bot.voice_operation_tasks)


class PlaybackSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_noncritical_tasks(state)
            bot.cancel_autoplay_refill(state)
            bot.cancel_lyrics_publish(state)
            bot.schedule_private_lyrics_cleanup(state)
            bot.cancel_queue_message_cleanups(state)
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

    async def test_duplicate_pending_advances_create_one_followup_task(self) -> None:
        first_release = asyncio.Event()
        second_started = asyncio.Event()
        play_next_calls = 0

        async def fake_play_next(guild_id: int, announce: bool = True) -> None:
            nonlocal play_next_calls
            play_next_calls += 1
            if play_next_calls == 1:
                await first_release.wait()
            else:
                second_started.set()

        guild_id = 124
        state = bot.get_state(guild_id)
        generation = state.playback_generation

        with patch.object(bot, "play_next", side_effect=fake_play_next):
            first_task, first_created = bot.schedule_play_next(guild_id)
            for _ in range(3):
                pending_task, pending_created = bot.schedule_play_next_after_current(
                    guild_id,
                    generation,
                )
                self.assertIs(pending_task, first_task)
                self.assertFalse(pending_created)

            self.assertTrue(first_created)
            self.assertIs(state.pending_advance_task, first_task)
            first_release.set()
            await first_task
            await asyncio.wait_for(second_started.wait(), timeout=1)
            followup_task = state.advance_task
            self.assertIsNotNone(followup_task)
            await followup_task

        self.assertEqual(play_next_calls, 2)
        self.assertIsNone(state.pending_advance_task)

    async def test_stop_discards_pending_advance_from_old_generation(self) -> None:
        first_started = asyncio.Event()
        first_release = asyncio.Event()
        play_next_calls = 0

        async def fake_play_next(guild_id: int, announce: bool = True) -> None:
            nonlocal play_next_calls
            play_next_calls += 1
            first_started.set()
            await first_release.wait()

        guild_id = 125
        state = bot.get_state(guild_id)

        with (
            patch.object(bot, "play_next", side_effect=fake_play_next),
            patch.object(bot, "schedule_lyrics_message_cleanup"),
        ):
            first_task, _ = bot.schedule_play_next(guild_id)
            await first_started.wait()
            bot.schedule_play_next_after_current(
                guild_id,
                state.playback_generation,
            )
            self.assertIs(state.pending_advance_task, first_task)

            bot.stop_playback(state, guild_id)
            await asyncio.gather(first_task, return_exceptions=True)
            await asyncio.sleep(0)

        self.assertEqual(play_next_calls, 1)
        self.assertIsNone(state.advance_task)
        self.assertIsNone(state.pending_advance_task)

    async def test_enqueue_during_idle_cleanup_starts_followup_playback(
        self,
    ) -> None:
        guild_id = 126
        idle_panel_started = asyncio.Event()
        release_idle_panel = asyncio.Event()
        playback_started = asyncio.Event()

        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.play = MagicMock(side_effect=self._play)

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def _play(self, source: object, *, after: object) -> None:
                self.playing = True
                playback_started.set()

        class Requester:
            display_name = "tester"
            id = 1260

        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        track = make_track("followup")
        track.stream_url = "https://example.test/followup.opus"
        track.audio_codec = "opus"
        loading_message = MagicMock()
        loading_message.edit = AsyncMock()

        async def block_idle_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            idle_panel_started.set()
            await release_idle_panel.wait()

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        first_task = None
        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=block_idle_panel),
            ) as show_idle_panel,
            patch.object(
                bot,
                "extract_track",
                new=AsyncMock(return_value=track),
            ),
            patch.object(bot, "resolve_track_stream", new=AsyncMock()),
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                return_value=MagicMock(),
            ),
            patch.object(
                bot,
                "update_control_panel",
                new=AsyncMock(),
            ) as update_control_panel,
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "schedule_autoplay_refill") as schedule_autoplay_refill,
            patch.object(
                bot,
                "create_housekeeping_task",
                side_effect=discard_housekeeping,
            ),
        ):
            try:
                first_task, first_created = bot.schedule_play_next(
                    guild_id,
                    announce=False,
                )
                self.assertTrue(first_created)
                self.assertIsNotNone(first_task)
                await asyncio.wait_for(idle_panel_started.wait(), timeout=1)

                enqueue_result = await bot.enqueue_tracks(
                    guild_id,
                    MagicMock(),
                    Requester(),
                    "followup song",
                    initial_response=loading_message,
                )

                self.assertTrue(enqueue_result)
                self.assertEqual(list(state.queue), [track])
                self.assertIs(state.pending_advance_task, first_task)
                self.assertTrue(state.pending_advance_announce)
                self.assertFalse(playback_started.is_set())

                release_idle_panel.set()
                await asyncio.wait_for(first_task, timeout=1)
                await asyncio.wait_for(playback_started.wait(), timeout=1)
                await asyncio.sleep(0)
            finally:
                release_idle_panel.set()
                bot.clear_pending_playback_advance(state)
                tasks = {
                    task
                    for task in (first_task, state.advance_task)
                    if task is not None
                }
                for task in tasks:
                    if not task.done():
                        task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.sleep(0)
                late_advance = state.advance_task
                if late_advance is not None and late_advance not in tasks:
                    if not late_advance.done():
                        late_advance.cancel()
                    await asyncio.gather(late_advance, return_exceptions=True)
                bot.clear_pending_playback_advance(state)
                bot.cancel_empty_channel_disconnect(state)
                bot.music_states.pop(guild_id, None)

        self.assertIs(state.current, track)
        self.assertFalse(state.queue)
        self.assertTrue(voice.is_playing())
        voice.play.assert_called_once()
        show_idle_panel.assert_awaited_once_with(guild_id, state)
        update_control_panel.assert_awaited_once_with(guild_id, state)
        schedule_autoplay_refill.assert_not_called()

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
        first.stream_url = "https://example.test/first.opus"
        first.audio_codec = "opus"
        second = make_track("second")
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.autoplay_enabled = True
        state.queue.extend([first, second])

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "resolve_track_stream", new=AsyncMock()),
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                return_value=MagicMock(),
            ) as ffmpeg_opus,
            patch.object(bot, "schedule_noncritical_tasks") as schedule_background,
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
        ffmpeg_opus.assert_called_once()
        self.assertEqual(ffmpeg_opus.call_args.kwargs["codec"], "copy")
        self.assertEqual(ffmpeg_opus.call_args.kwargs["bitrate"], 128)
        schedule_background.assert_called_once_with(guild_id, first)

    async def test_repeat_one_preserves_a_fresh_stream_url(self) -> None:
        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.after = None

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.playing = True
                self.after = after

        guild_id = 460
        stream_url = "https://example.test/fresh.opus"
        resolved_at = bot.time.monotonic()
        track = make_track("repeat")
        track.stream_url = stream_url
        track.stream_resolved_at = resolved_at
        track.audio_codec = "opus"
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.repeat_one = True
        state.queue.append(track)
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "extract_ytdl_info", new=AsyncMock()) as extract,
            patch.object(bot.discord, "FFmpegOpusAudio", return_value=MagicMock()),
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "schedule_play_next") as schedule_next,
            patch.object(bot, "bot", fake_bot),
        ):
            await bot.play_next(guild_id, announce=False)
            voice.playing = False
            self.assertIsNotNone(voice.after)
            voice.after(None)
            await asyncio.sleep(0)

        extract.assert_not_awaited()
        self.assertEqual(list(state.queue), [track])
        self.assertEqual(track.stream_url, stream_url)
        self.assertEqual(track.stream_resolved_at, resolved_at)
        self.assertEqual(track.playback_attempts, 0)
        self.assertFalse(track.force_transcode)
        schedule_next.assert_called_once_with(guild_id)

    async def test_playback_error_retries_once_then_stops_with_transcode_fallback(
        self,
    ) -> None:
        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.after = None

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.playing = True
                self.after = after

        guild_id = 461
        track = make_track("retry")
        track.stream_url = "https://example.test/first.opus"
        track.stream_resolved_at = bot.time.monotonic()
        track.audio_codec = "opus"
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.queue.append(track)
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        async def resolve_stream(target: bot.Track) -> None:
            if target.stream_url is None:
                target.stream_url = "https://example.test/refreshed.opus"
                target.stream_resolved_at = bot.time.monotonic()
                target.audio_codec = "opus"

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(
                bot,
                "resolve_track_stream",
                new=AsyncMock(side_effect=resolve_stream),
            ) as resolve,
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                side_effect=[MagicMock(), MagicMock()],
            ) as ffmpeg_opus,
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "schedule_play_next") as schedule_next,
            patch.object(bot, "bot", fake_bot),
        ):
            await bot.play_next(guild_id, announce=False)
            self.assertEqual(ffmpeg_opus.call_args_list[0].kwargs["codec"], "copy")

            voice.playing = False
            voice.after(RuntimeError("copy failed"))
            await asyncio.sleep(0)

            self.assertEqual(list(state.queue), [track])
            self.assertIsNone(track.stream_url)
            self.assertIsNone(track.stream_resolved_at)
            self.assertEqual(track.playback_attempts, 1)
            self.assertTrue(track.force_transcode)

            await bot.play_next(guild_id, announce=False)
            self.assertEqual(ffmpeg_opus.call_args_list[1].kwargs["codec"], None)

            voice.playing = False
            voice.after(RuntimeError("transcode failed"))
            await asyncio.sleep(0)

        self.assertEqual(resolve.await_count, 2)
        self.assertEqual(ffmpeg_opus.call_count, 2)
        self.assertEqual(list(state.queue), [])
        self.assertIsNone(state.current)
        self.assertEqual(track.playback_attempts, 0)
        self.assertFalse(track.force_transcode)
        self.assertEqual(schedule_next.call_count, 2)

    async def test_immediate_error_defers_retry_until_active_advance_finishes(
        self,
    ) -> None:
        panel_entered = asyncio.Event()
        panel_release = asyncio.Event()
        retry_started = asyncio.Event()

        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.play_calls = 0

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.play_calls += 1
                if self.play_calls == 1:
                    self.playing = False
                    after(RuntimeError("immediate copy failure"))
                else:
                    self.playing = True
                    retry_started.set()

        async def resolve_stream(target: bot.Track) -> None:
            if target.stream_url is None:
                target.stream_url = "https://example.test/refreshed.opus"
                target.stream_resolved_at = bot.time.monotonic()
                target.audio_codec = "opus"

        panel_calls = 0

        async def update_panel(*args: object, **kwargs: object) -> None:
            nonlocal panel_calls
            panel_calls += 1
            if panel_calls == 1:
                panel_entered.set()
                await panel_release.wait()

        guild_id = 462
        track = make_track("fast-error")
        track.stream_url = "https://example.test/first.opus"
        track.stream_resolved_at = bot.time.monotonic()
        track.audio_codec = "opus"
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.queue.append(track)
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(
                bot,
                "resolve_track_stream",
                new=AsyncMock(side_effect=resolve_stream),
            ),
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                side_effect=[MagicMock(), MagicMock()],
            ) as ffmpeg_opus,
            patch.object(bot, "update_control_panel", new=AsyncMock(side_effect=update_panel)),
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "bot", fake_bot),
        ):
            first_task, created = bot.schedule_play_next(guild_id)
            await asyncio.wait_for(panel_entered.wait(), timeout=1)

            self.assertTrue(created)
            self.assertIs(state.advance_task, first_task)
            self.assertIs(state.pending_advance_task, first_task)
            self.assertEqual(list(state.queue), [track])

            panel_release.set()
            await first_task
            await asyncio.wait_for(retry_started.wait(), timeout=1)
            followup_task = state.advance_task
            if followup_task is not None:
                await followup_task

        self.assertEqual(voice.play_calls, 2)
        self.assertIs(state.current, track)
        self.assertEqual(list(state.queue), [])
        self.assertEqual(
            [call.kwargs["codec"] for call in ffmpeg_opus.call_args_list],
            ["copy", None],
        )

    async def test_final_playback_error_advances_to_the_next_track(self) -> None:
        panel_entered = [asyncio.Event(), asyncio.Event()]
        panel_release = [asyncio.Event(), asyncio.Event()]
        next_track_started = asyncio.Event()
        play_titles: list[str] = []

        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                assert state.current is not None
                play_titles.append(state.current.title)
                if len(play_titles) <= 2:
                    self.playing = False
                    after(RuntimeError(f"failure {len(play_titles)}"))
                else:
                    self.playing = True
                    next_track_started.set()

        async def resolve_stream(target: bot.Track) -> None:
            if target.stream_url is None:
                target.stream_url = f"https://example.test/{target.title}.opus"
                target.stream_resolved_at = bot.time.monotonic()
                target.audio_codec = "opus"

        panel_calls = 0

        async def update_panel(*args: object, **kwargs: object) -> None:
            nonlocal panel_calls
            index = panel_calls
            panel_calls += 1
            if index < len(panel_entered):
                panel_entered[index].set()
                await panel_release[index].wait()

        guild_id = 463
        failed_track = make_track("fails-twice")
        failed_track.stream_url = "https://example.test/first.opus"
        failed_track.stream_resolved_at = bot.time.monotonic()
        failed_track.audio_codec = "opus"
        next_track = make_track("next-track")
        next_track.stream_url = "https://example.test/next.opus"
        next_track.stream_resolved_at = bot.time.monotonic()
        next_track.audio_codec = "opus"
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.queue.extend([failed_track, next_track])
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(
                bot,
                "resolve_track_stream",
                new=AsyncMock(side_effect=resolve_stream),
            ),
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                side_effect=[MagicMock(), MagicMock(), MagicMock()],
            ) as ffmpeg_opus,
            patch.object(bot, "update_control_panel", new=AsyncMock(side_effect=update_panel)),
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "bot", fake_bot),
        ):
            active_task, _ = bot.schedule_play_next(guild_id)
            for index in range(2):
                await asyncio.wait_for(panel_entered[index].wait(), timeout=1)
                self.assertIs(state.pending_advance_task, active_task)
                panel_release[index].set()
                await active_task
                if index == 0:
                    while state.advance_task is None:
                        await asyncio.sleep(0)
                    active_task = state.advance_task

            await asyncio.wait_for(next_track_started.wait(), timeout=1)

        self.assertEqual(play_titles, ["fails-twice", "fails-twice", "next-track"])
        self.assertIs(state.current, next_track)
        self.assertEqual(failed_track.playback_attempts, 0)
        self.assertFalse(failed_track.force_transcode)
        self.assertEqual(
            [call.kwargs["codec"] for call in ffmpeg_opus.call_args_list],
            ["copy", None, "copy"],
        )

    async def test_repeat_one_keeps_transcode_after_copy_failure(self) -> None:
        third_play_started = asyncio.Event()
        attempts_at_play: list[int] = []

        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.play_calls = 0

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.play_calls += 1
                assert state.current is track
                attempts_at_play.append(track.playback_attempts)
                if self.play_calls == 1:
                    self.playing = False
                    after(RuntimeError("copy failed"))
                elif self.play_calls == 2:
                    self.playing = False
                    after(None)
                else:
                    self.playing = True
                    third_play_started.set()

        async def resolve_stream(target: bot.Track) -> None:
            if target.stream_url is None:
                target.stream_url = "https://example.test/refreshed.opus"
                target.stream_resolved_at = bot.time.monotonic()
                target.audio_codec = "opus"

        guild_id = 464
        track = make_track("repeat-transcode")
        track.stream_url = "https://example.test/first.opus"
        track.stream_resolved_at = bot.time.monotonic()
        track.audio_codec = "opus"
        voice = FakeVoice()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.repeat_one = True
        state.queue.append(track)
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(
                bot,
                "resolve_track_stream",
                new=AsyncMock(side_effect=resolve_stream),
            ),
            patch.object(
                bot.discord,
                "FFmpegOpusAudio",
                side_effect=[MagicMock(), MagicMock(), MagicMock()],
            ) as ffmpeg_opus,
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "bot", fake_bot),
        ):
            first_task, _ = bot.schedule_play_next(guild_id, announce=False)
            await first_task
            await asyncio.wait_for(third_play_started.wait(), timeout=1)

        self.assertEqual(voice.play_calls, 3)
        self.assertEqual(attempts_at_play, [1, 2, 1])
        self.assertTrue(track.force_transcode)
        self.assertEqual(
            [call.kwargs["codec"] for call in ffmpeg_opus.call_args_list],
            ["copy", None, None],
        )

    async def test_noncritical_work_is_scheduled_after_playback_starts(self) -> None:
        guild_id = 458
        track = make_track("background")
        state = bot.get_state(guild_id)
        state.current = track

        with (
            patch.object(bot, "AUTOPLAY_START_DELAY_SECONDS", 0.0),
            patch.object(bot, "LYRICS_START_DELAY_SECONDS", 0.0),
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_lyrics_publish") as schedule_lyrics,
        ):
            await bot.start_noncritical_tasks(
                guild_id,
                state.playback_generation,
                track,
            )

        schedule_refill.assert_called_once_with(guild_id)
        schedule_lyrics.assert_called_once_with(guild_id, track)

    async def test_noncritical_work_stops_when_the_track_changes(self) -> None:
        guild_id = 459
        track = make_track("old")
        state = bot.get_state(guild_id)
        state.current = make_track("new")

        with (
            patch.object(bot, "AUTOPLAY_START_DELAY_SECONDS", 0.0),
            patch.object(bot, "LYRICS_START_DELAY_SECONDS", 0.0),
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(bot, "schedule_lyrics_publish") as schedule_lyrics,
        ):
            await bot.start_noncritical_tasks(
                guild_id,
                state.playback_generation,
                track,
            )

        schedule_refill.assert_not_called()
        schedule_lyrics.assert_not_called()

    async def test_track_end_deletes_its_private_lyrics_messages(self) -> None:
        class FakeVoice:
            def __init__(self) -> None:
                self.playing = False
                self.after = None

            def is_connected(self) -> bool:
                return True

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def play(self, source: object, *, after: object) -> None:
                self.playing = True
                self.after = after

        guild_id = 457
        track = make_track("finished")
        voice = FakeVoice()
        private_message = MagicMock()
        private_message.delete = AsyncMock()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.queue.append(track)
        state.private_lyrics_messages[track.track_id] = [private_message]
        fake_bot = MagicMock()
        fake_bot.loop = asyncio.get_running_loop()

        with (
            patch.object(bot, "ffmpeg_is_available", return_value=True),
            patch.object(bot, "resolve_track_stream", new=AsyncMock()),
            patch.object(bot.discord, "FFmpegOpusAudio", return_value=MagicMock()),
            patch.object(bot, "schedule_noncritical_tasks"),
            patch.object(bot, "schedule_play_next") as schedule_next,
            patch.object(bot, "bot", fake_bot),
        ):
            await bot.play_next(guild_id, announce=False)
            self.assertIsNotNone(voice.after)
            voice.after(None)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        private_message.delete.assert_awaited_once_with()
        self.assertFalse(state.private_lyrics_messages)
        self.assertIsNone(state.current)
        schedule_next.assert_called_once_with(guild_id)

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
            "acodec": "opus",
            "formats": [{}],
        }

        with patch.object(
            bot,
            "extract_ytdl_info",
            new=AsyncMock(return_value=resolved),
        ) as extract:
            await bot.resolve_track_stream(track)

        extract.assert_awaited_once_with(
            bot.YTDL_OPTIONS,
            track.source_url,
            "audio stream resolve",
            job_kind=bot.YtdlJobKind.PLAYBACK_STREAM,
            use_cache=False,
            minimum_interval_seconds=0.0,
        )
        self.assertEqual(track.stream_url, "https://example.test/new-audio")
        self.assertEqual(track.title, "refreshed")
        self.assertEqual(track.audio_codec, "opus")

    async def test_extraction_slot_wait_also_times_out(self) -> None:
        scheduler = music_ytdl.YtdlPriorityScheduler(1)
        worker_started = asyncio.Event()
        release_worker = asyncio.Event()

        async def worker(*args: object, **kwargs: object) -> dict:
            worker_started.set()
            await release_worker.wait()
            return {"id": "blocker"}

        with (
            patch.object(bot, "ytdl_scheduler", scheduler),
            patch.object(music_ytdl, "run_ytdl_worker", side_effect=worker),
            patch.object(bot, "YTDL_EXTRACT_TIMEOUT_SECONDS", 0.01),
        ):
            blocker = asyncio.create_task(
                scheduler.submit(
                    {},
                    "blocker",
                    "blocker",
                    job_kind=bot.YtdlJobKind.USER_REQUEST,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=0.0,
                )
            )
            await worker_started.wait()
            with self.assertRaises(asyncio.TimeoutError):
                await bot.extract_ytdl_info(
                    {},
                    "test",
                    "blocked extraction",
                    job_kind=bot.YtdlJobKind.PLAYBACK_STREAM,
                    use_cache=False,
                )
            release_worker.set()
            await blocker

        await scheduler.shutdown()

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
