import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from discord.ui.view import ViewStore

import bot
from devtools.local_music_bot import LocalMusicMode


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class SearchRoutingTests(unittest.TestCase):
    def test_song_and_auto_seed_use_the_same_youtube_search(self) -> None:
        expected = f"ytsearch{bot.YOUTUBE_SEARCH_CANDIDATES}:sunfaded"

        self.assertEqual(bot.resolve_query("sunfaded"), expected)
        self.assertEqual(bot.resolve_query("sunfaded", None), expected)

    def test_full_song_is_preferred_over_game_and_short_versions(self) -> None:
        entries = [
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV（4K対応）",
                "duration": 148,
                "channel": "アイドルマスターチャンネル",
            },
            {
                "id": "x5dIe0FKY_U",
                "title": (
                    "泥濘鳴鳴(Muddy Cries) / コメティック (CoMETIK) / "
                    "歌詞 Color coded lyrics"
                ),
                "duration": 233,
                "channel": "iluvsmurfs",
            },
            {
                "id": "3fwoSr7hxZM",
                "title": "泥濘鳴鳴(斑鳩ルカver)",
                "duration": 235,
                "channel": "CoMETIK SOLO COLLECTION",
            },
            {
                "id": "LkbTHyLUO4k",
                "title": "【シャニソン】Short Ver. コメティック「泥濘鳴鳴」3DMV",
                "duration": 95,
                "channel": "アイドルマスターチャンネル",
            },
        ]

        selected = bot.select_youtube_search_result("でいねいめいめい", entries)

        self.assertEqual(selected["id"], "x5dIe0FKY_U")

    def test_title_relevance_beats_an_unrelated_longer_result(self) -> None:
        entries = [
            {
                "id": "quick-song1",
                "title": "Artist - Quick Song (Official Audio)",
                "duration": 155,
            },
            {
                "id": "other-song1",
                "title": "Artist - Different Song (Full Version)",
                "duration": 240,
            },
        ]

        selected = bot.select_youtube_search_result("Artist Quick Song", entries)

        self.assertEqual(selected["id"], "quick-song1")

    def test_explicit_game_mv_request_is_respected(self) -> None:
        entries = [
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV（4K対応）",
                "duration": 148,
            },
            {
                "id": "x5dIe0FKY_U",
                "title": "泥濘鳴鳴 / コメティック / 歌詞 Color coded lyrics",
                "duration": 233,
            },
        ]

        selected = bot.select_youtube_search_result("泥濘鳴鳴 game mv", entries)

        self.assertEqual(selected["id"], "I-CZXVMPiPg")

    def test_youtube_music_song_result_preserves_catalog_metadata(self) -> None:
        entry = bot.youtube_music_result_to_entry(
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "artists": [{"name": "CoMETIK"}],
                "album": {"name": "THE IDOLM@STER SHINY COLORS ECHOES 08"},
                "duration_seconds": 235,
                "thumbnails": [{"url": "https://example.com/cover.jpg"}],
            }
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], "CuRIuFRD1zI")
        self.assertEqual(entry["track"], "泥濘鳴鳴")
        self.assertEqual(entry["artist"], "CoMETIK")
        self.assertEqual(entry["duration"], 235)
        self.assertEqual(
            entry["webpage_url"],
            "https://www.youtube.com/watch?v=CuRIuFRD1zI",
        )

    def test_youtube_music_ignores_non_song_results(self) -> None:
        result = bot.youtube_music_result_to_entry(
            {
                "resultType": "episode",
                "videoId": "abcdefghijk",
                "title": "Unrelated podcast",
            }
        )

        self.assertIsNone(result)

    def test_top_album_supplies_artist_hint(self) -> None:
        results = [
            {
                "category": "Top result",
                "resultType": "album",
                "title": "THE IDOLM@STER SHINY COLORS ECHOES 08",
                "artists": [{"name": "CoMETIK"}],
            },
            {
                "resultType": "album",
                "title": "Unrelated karaoke",
                "artists": [{"name": "Karaoke Artist"}],
            },
        ]

        self.assertEqual(
            bot.get_youtube_music_artist_hint("でいねいめいめい", results),
            "CoMETIK",
        )

    def test_same_title_from_multiple_artists_skips_catalog_shortcut(self) -> None:
        results = [
            {
                "resultType": "song",
                "videoId": "keOnleW2eak",
                "title": "らしさ",
                "artists": [{"name": "Official髭男dism"}],
                "duration_seconds": 313,
            },
            {
                "resultType": "song",
                "videoId": "abcdefghijk",
                "title": "らしさ",
                "artists": [{"name": "SUPER BEAVER"}],
                "duration_seconds": 269,
            },
        ]

        self.assertIsNone(
            bot.select_youtube_music_song_result("らしさ", results)
        )
        self.assertIsNone(bot.get_youtube_music_artist_hint("らしさ", results))

    def test_romanized_query_prefers_official_mv_over_full_fan_upload(self) -> None:
        entries = [
            {
                "id": "BCMKhsXcdJI",
                "title": "OFFICIAL HIGE DANDISM - Rashisa [Official Audio]",
                "duration": 303,
                "channel": "OFFICIAL HIGE DANDISM",
            },
            {
                "id": "keOnleW2eak",
                "title": "OFFICIAL HIGE DANDISM - Rashisa [Official Video]",
                "duration": 313,
                "channel": "OFFICIAL HIGE DANDISM",
            },
            {
                "id": "MizuH2nfwaI",
                "title": (
                    "100 Meters - Theme Song FULL \"Rashisa\" by "
                    "Official HIGE DANdism (Lyrics)"
                ),
                "duration": 313,
                "channel": "Jamong",
            },
        ]

        selected = bot.select_youtube_search_result("rashisa", entries)

        self.assertEqual(selected["id"], "keOnleW2eak")

    def test_enriched_search_prefers_bare_catalog_title(self) -> None:
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
            {
                "id": "x5dIe0FKY_U",
                "title": (
                    "泥濘鳴鳴(Muddy Cries) / コメティック (CoMETIK) / "
                    "歌詞 Color coded lyrics"
                ),
                "duration": 233,
                "channel": "iluvsmurfs",
            },
        ]
        preferred_title = bot.infer_youtube_search_song_title(
            entries[0],
            "CoMETIK",
        )

        selected = bot.select_youtube_search_result(
            "でいねいめいめい CoMETIK",
            entries,
            preferred_artist="CoMETIK",
            preferred_title=preferred_title,
        )

        self.assertEqual(preferred_title, "泥濘鳴鳴")
        self.assertEqual(selected["id"], "CuRIuFRD1zI")

    def test_explicit_versions_skip_youtube_music_catalog(self) -> None:
        self.assertFalse(bot.should_use_youtube_music_search("泥濘鳴鳴 game mv"))
        self.assertFalse(bot.should_use_youtube_music_search("泥濘鳴鳴 cover"))
        self.assertFalse(bot.should_use_youtube_music_search("泥濘鳴鳴 off vocal"))
        self.assertTrue(bot.should_use_youtube_music_search("泥濘鳴鳴"))

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

    async def test_music_reply_ignores_transient_discord_500(self) -> None:
        message = MagicMock()
        message.reply = AsyncMock(side_effect=self.make_server_error())

        with (
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
            self.assertLogs("music-bot", level="WARNING") as logs,
        ):
            result = await bot.send_music_request_reply(message, "곡을 찾고 있어요...")

        self.assertIsNone(result)
        self.assertIn("HTTP 500", "\n".join(logs.output))
        self.assertNotIn("<html>", "\n".join(logs.output))

    async def test_feedback_500_does_not_undo_queued_track(self) -> None:
        class Requester:
            display_name = "tester"
            id = 123

        channel = MagicMock()
        channel.send = AsyncMock(side_effect=self.make_server_error())
        track = make_track("queued")

        with (
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
            patch.object(bot, "extract_track", new=AsyncMock(return_value=track)),
            self.assertLogs("music-bot", level="WARNING"),
        ):
            result = await bot.enqueue_tracks(987, channel, Requester(), "queued")

        self.assertTrue(result)
        self.assertEqual(list(bot.get_state(987).queue), [track])

    async def test_request_delete_ignores_transient_discord_500(self) -> None:
        message = MagicMock()
        message.delete = AsyncMock(side_effect=self.make_server_error())

        with (
            patch.object(bot, "MUSIC_CHANNEL_DELETE_REQUESTS", True),
            self.assertLogs("music-bot", level="WARNING") as logs,
        ):
            await bot.delete_music_request_message(message)

        self.assertIn("HTTP 500", "\n".join(logs.output))


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

    def test_bot_auto_parser_uses_runtime_default_setting(self) -> None:
        with patch.object(bot, "DEFAULT_AUTO_TRACKS", 7):
            self.assertEqual(
                bot.parse_auto_request("auto: back number"),
                ("back number", 7),
            )

    def test_bot_auto_parser_uses_runtime_max_setting(self) -> None:
        with patch.object(bot, "MAX_AUTO_TRACKS", 9):
            self.assertEqual(bot.clamp_auto_count(999), 9)
            self.assertEqual(
                bot.parse_auto_request("auto999: lofi chill"),
                ("lofi chill", 9),
            )

    def test_bot_auto_parser_uses_bot_clamp_monkeypatch(self) -> None:
        with patch.object(bot, "clamp_auto_count", return_value=8) as clamp:
            self.assertEqual(
                bot.parse_auto_request("auto999: lofi chill"),
                ("lofi chill", 8),
            )

        clamp.assert_called_once_with(999)

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


class AutoRequestEnqueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_count_request_routes_to_auto_extractor_and_enqueues_all_tracks(
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
                "auto5: back number",
                initial_response=initial_response,
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

    def test_autoplay_skips_recent_videos_when_metadata_changes(self) -> None:
        played_first = self.make_identity_track(
            "First Artist - First Song",
            "aaaaaaaaaaa",
            artist="First Artist",
            song_name="First Song",
        )
        played_second = self.make_identity_track(
            "Second Artist - Second Song",
            "bbbbbbbbbbb",
            artist="Second Artist",
            song_name="Second Song",
        )
        rediscovered_first = self.make_identity_track(
            "First Song (Official Audio)",
            "aaaaaaaaaaa",
            uploader="Archive Channel",
        )
        rediscovered_second = self.make_identity_track(
            "Second Song (Official Audio)",
            "bbbbbbbbbbb",
            uploader="Another Channel",
        )
        fresh = self.make_identity_track(
            "Third Artist - Third Song",
            "ccccccccccc",
        )
        state = bot.GuildMusicState()
        bot.remember_autoplay_track(state, played_first)
        bot.remember_autoplay_track(state, played_second)

        self.assertNotEqual(
            bot.normalize_track_key(played_first),
            bot.normalize_track_key(rediscovered_first),
        )
        self.assertNotEqual(
            bot.normalize_track_key(played_second),
            bot.normalize_track_key(rediscovered_second),
        )
        self.assertIs(
            bot.select_autoplay_candidate(
                state,
                [rediscovered_first, rediscovered_second, fresh],
            ),
            fresh,
        )


class LyricsLookupTests(unittest.TestCase):
    def test_japanese_quoted_title_ignores_official_label_and_english_alias(self) -> None:
        track = bot.Track(
            title=(
                "初星学園 「白線」Official Music Video "
                "(HATSUBOSHI GAKUEN - Hakusen)"
            ),
            webpage_url="https://www.youtube.com/watch?v=m4VahiqP9vA",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=m4VahiqP9vA",
            uploader="HATSUBOSHI GAKUEN",
            duration=218,
        )

        self.assertEqual(
            bot.get_lyrics_search_terms(track),
            ("白線", "初星学園"),
        )

    def test_search_terms_use_song_title_and_artist_in_original_script(self) -> None:
        track = bot.Track(
            title="back number - ブルーアンバー 【Official Music Video】",
            webpage_url="https://www.youtube.com/watch?v=lyrics00001",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=lyrics00001",
            uploader="back number - Topic",
        )

        self.assertEqual(
            bot.get_lyrics_search_terms(track),
            ("ブルーアンバー", "back number"),
        )

    def test_plain_lyrics_are_returned_without_translation_or_romanization(self) -> None:
        original = "君の声が聞こえる\n夜を越えて"
        record = {
            "instrumental": False,
            "plainLyrics": original,
            "syncedLyrics": "[00:01.00]Kimi no koe ga kikoeru",
        }

        self.assertEqual(bot.extract_original_lyrics(record), original)

    def test_synced_lyrics_fallback_removes_only_lrc_metadata(self) -> None:
        record = {
            "instrumental": False,
            "plainLyrics": None,
            "syncedLyrics": (
                "[ar:back number]\n"
                "[00:01.00]君の声が聞こえる\n"
                "[00:04.20]夜を越えて"
            ),
        }

        self.assertEqual(
            bot.extract_original_lyrics(record),
            "君の声が聞こえる\n夜を越えて",
        )

    def test_exact_artist_match_is_selected_over_another_song(self) -> None:
        wrong_artist = {
            "trackName": "Blue Amber",
            "artistName": "Different Artist",
            "duration": 220,
            "instrumental": False,
            "plainLyrics": "wrong",
        }
        matching_record = {
            "trackName": "Blue Amber",
            "artistName": "back number",
            "duration": 221,
            "instrumental": False,
            "plainLyrics": "correct",
        }

        selected = bot.select_lyrics_record(
            [wrong_artist, matching_record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIs(selected, matching_record)

    def test_exact_title_and_duration_allow_a_different_artist_label(self) -> None:
        record = {
            "trackName": "Blue Amber",
            "artistName": "バックナンバー",
            "duration": 224,
            "instrumental": False,
            "plainLyrics": "correct",
        }

        selected = bot.select_lyrics_record(
            [record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIs(selected, record)

    def test_artist_mismatch_is_rejected_when_duration_is_not_close(self) -> None:
        record = {
            "trackName": "Blue Amber",
            "artistName": "Different Artist",
            "duration": 240,
            "instrumental": False,
            "plainLyrics": "wrong",
        }

        selected = bot.select_lyrics_record(
            [record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIsNone(selected)

    def test_lookup_retries_without_artist_when_strict_search_misses(self) -> None:
        track = bot.Track(
            title="Artist - Exact Song",
            webpage_url="https://www.youtube.com/watch?v=retrylyrics",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=retrylyrics",
            duration=180,
        )
        record = {
            "trackName": "Exact Song",
            "artistName": "Artist feat. Guest",
            "duration": 181,
            "instrumental": False,
            "plainLyrics": "found on retry",
        }

        with patch.object(
            bot,
            "request_lyrics_records",
            side_effect=[[], [record]],
        ) as request:
            lyrics = bot.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "found on retry")
        self.assertEqual(
            [call.args for call in request.call_args_list],
            [("exact song", "artist"), ("exact song", None)],
        )

    def test_romanized_official_title_matches_native_lrclib_record(self) -> None:
        track = bot.Track(
            title="OFFICIAL HIGE DANDISM - Rashisa [Official Video]",
            webpage_url="https://www.youtube.com/watch?v=keOnleW2eak",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=keOnleW2eak",
            uploader="OFFICIAL HIGE DANDISM",
            duration=313,
        )
        record = {
            "trackName": "らしさ - Rashisa",
            "artistName": "Official髭男dism",
            "duration": 313,
            "instrumental": False,
            "plainLyrics": "Japanese lyrics fixture",
        }

        with patch.object(
            bot,
            "request_lyrics_records",
            return_value=[record],
        ) as request:
            lyrics = bot.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "Japanese lyrics fixture")
        request.assert_called_once_with("rashisa", "official hige dandism")

    def test_native_script_beats_nearby_romanized_duplicate(self) -> None:
        romanized_record = {
            "trackName": "Sparkle - movie ver.",
            "artistName": "RADWIMPS",
            "duration": 538,
            "instrumental": False,
            "plainLyrics": "Mada kono sekai wa boku o kainarashi tetai mitai da",
        }
        japanese_record = {
            "trackName": "Sparkle (movie ver.)",
            "artistName": "RADWIMPS",
            "duration": 535,
            "instrumental": False,
            "plainLyrics": "まだこの世界は僕を飼いならしてたいみたいだ",
        }

        selected = bot.select_lyrics_record(
            [romanized_record, japanese_record],
            "Sparkle - movie ver.",
            "RADWIMPS",
            538,
        )

        self.assertIs(selected, japanese_record)

    def test_native_script_preference_does_not_override_distant_match(self) -> None:
        exact_english_record = {
            "trackName": "Original English Song",
            "artistName": "Artist",
            "duration": 200,
            "instrumental": False,
            "plainLyrics": "This is the original English lyric",
        }
        unrelated_native_record = {
            "trackName": "Original English Song translated version",
            "artistName": "Artist",
            "duration": 200,
            "instrumental": False,
            "plainLyrics": "これは別の候補です",
        }

        selected = bot.select_lyrics_record(
            [exact_english_record, unrelated_native_record],
            "Original English Song",
            "Artist",
            200,
        )

        self.assertIs(selected, exact_english_record)

    def test_instrumental_record_is_treated_as_unavailable(self) -> None:
        self.assertIsNone(
            bot.extract_original_lyrics(
                {
                    "instrumental": True,
                    "plainLyrics": "should not be shown",
                }
            )
        )

class LyricsFallbackTests(unittest.IsolatedAsyncioTestCase):
    def test_json3_manual_subtitles_are_converted_to_plain_lyrics(self) -> None:
        payload = json.dumps(
            {
                "events": [
                    {"segs": [{"utf8": "君の声が"}, {"utf8": "聞こえる"}]},
                    {"segs": [{"utf8": "夜を越えて"}]},
                    {"segs": [{"utf8": "夜を越えて"}]},
                ]
            }
        )

        self.assertEqual(
            bot.extract_json3_lyrics(payload),
            "君の声が聞こえる\n夜を越えて",
        )

    def test_invalid_json3_document_is_rejected(self) -> None:
        with self.assertRaises(bot.YouTubeSubtitleError):
            bot.extract_json3_lyrics("[]")

    def test_vtt_manual_subtitles_drop_timestamps_and_markup(self) -> None:
        payload = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<c>First &amp; second</c>\n\n"
            "00:00:03.000 --> 00:00:05.000\n"
            "Next line\n"
        )

        self.assertEqual(
            bot.extract_vtt_lyrics(payload),
            "First & second\nNext line",
        )

    def test_original_language_manual_subtitle_is_preferred(self) -> None:
        track = make_track("captioned")
        track.subtitle_language = "ja"
        track.manual_subtitles = {
            "en": [{"ext": "json3", "url": "https://example.com/en"}],
            "ja": [{"ext": "vtt", "url": "https://example.com/ja"}],
        }

        self.assertEqual(
            bot.select_manual_subtitle(track),
            ("ja", "vtt", "https://example.com/ja"),
        )

    def test_korean_manual_subtitle_is_selected_independently(self) -> None:
        track = make_track("captioned")
        track.subtitle_language = "ja"
        track.manual_subtitles = {
            "ja": [{"ext": "json3", "url": "https://example.com/ja"}],
            "en": [{"ext": "json3", "url": "https://example.com/en"}],
            "ko-KR": [{"ext": "vtt", "url": "https://example.com/ko"}],
        }

        self.assertEqual(
            bot.select_korean_manual_subtitle(track),
            ("ko-KR", "vtt", "https://example.com/ko"),
        )

    def test_korean_manual_subtitle_does_not_use_other_languages(self) -> None:
        track = make_track("captioned")
        track.manual_subtitles = {
            "ja": [{"ext": "json3", "url": "https://example.com/ja"}],
            "en": [{"ext": "vtt", "url": "https://example.com/en"}],
        }

        self.assertIsNone(bot.select_korean_manual_subtitle(track))

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
    class FakeToken:
        def __init__(self, surface: str, reading: str | None = None):
            self._surface = surface
            self._reading = reading if reading is not None else surface

        def surface(self) -> str:
            return self._surface

        def reading_form(self) -> str:
            return self._reading

    class FakeTokenizer:
        def tokenize(self, text: str):
            return [LyricsVariantTests.FakeToken(text)] if text else []

    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.schedule_private_lyrics_cleanup(state)
            bot.cancel_queue_message_cleanups(state)
        await asyncio.sleep(0)
        bot.music_states.clear()

    def test_japanese_and_korean_lyrics_are_detected_locally(self) -> None:
        track = make_track("Japanese song")

        self.assertTrue(bot.lyrics_are_japanese(track, "君の声が聞こえる"))
        self.assertFalse(bot.lyrics_are_japanese(track, "I can hear your voice"))
        self.assertTrue(bot.lyrics_are_primarily_korean("너의 목소리가 들려"))
        self.assertFalse(bot.lyrics_are_primarily_korean("君の声が聞こえる"))

    def test_explicit_readings_accept_common_bracket_styles(self) -> None:
        tokenizer = self.FakeTokenizer()
        examples = {
            "運命(さだめ)": "運命(さだめ)",
            "運命（さだめ）": "運命(さだめ)",
            "運命[さだめ]": "運命(さだめ)",
            "運命【さだめ】": "運命(さだめ)",
            "運命《サダメ》": "運命(さだめ)",
            "｜超電磁砲《レールガン》": "超電磁砲(れーるがん)",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(
                    bot.replace_explicit_readings(source, tokenizer),
                    expected,
                )

    def test_non_kana_parentheses_are_not_treated_as_a_reading(self) -> None:
        source = "運命(Oh yeah)"

        self.assertEqual(
            bot.replace_explicit_readings(source, self.FakeTokenizer()),
            source,
        )
        self.assertEqual(
            bot.replace_explicit_readings("愛してる(ああ)", self.FakeTokenizer()),
            "愛してる(ああ)",
        )
        self.assertEqual(bot.annotate_token_reading("(", "キゴウ"), "(")
        self.assertEqual(bot.annotate_token_reading("Oh", "オー"), "Oh")

    def test_dictionary_readings_are_added_after_kanji(self) -> None:
        examples = {
            ("運命", "ウンメイ"): "運命(うんめい)",
            ("礼を持って", "レイヲモッテ"): "礼(れい)を持(も)って",
            ("取り戻す", "トリモドス"): "取(と)り戻(もど)す",
            ("かなだけ", "カナダケ"): "かなだけ",
        }

        for (surface, reading), expected in examples.items():
            with self.subTest(surface=surface):
                self.assertEqual(
                    bot.annotate_token_reading(surface, reading),
                    expected,
                )

    def test_explicit_reading_overrides_dictionary_reading(self) -> None:
        tokenizer = self.FakeTokenizer()

        with patch.object(bot, "get_sudachi_tokenizer", return_value=tokenizer):
            reading = bot.generate_hiragana_lyrics("未来(あした)")

        self.assertEqual(reading, "未来(あした)")

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
    HTML_FIXTURE = """
    <html>
      <body>
        <table class="wiki-table">
          <tbody>
            <tr>
              <th>일본어 원문</th>
              <th>일본어 독음</th>
              <th>한국어 번역<sup>[1]</sup></th>
            </tr>
            <tr>
              <td>泥濘 鳴鳴</td>
              <td>でいねい めいめい</td>
              <td><div>진창에서 울리는 노랫소리</div></td>
            </tr>
            <tr>
              <td>礼を持って</td>
              <td>れいをもって</td>
              <td>예를 갖추어 다시 걸어가</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """
    NAMUMARK_FIXTURE = """
    ||<tablewidth=100%><rowbgcolor=#222> '''일본어 원문''' || '''일본어 독음''' || '''한국어 번역''' ||
    || 泥濘 鳴鳴 || でいねい めいめい || 진창에서 울리는 노랫소리 ||
    || 礼を持って || れいをもって || 예를 갖추어 다시 걸어가 ||
    """
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

    def test_rendered_html_preserves_source_reading_and_translation(self) -> None:
        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_html(self.HTML_FIXTURE),
            self.EXPECTED_LYRICS,
        )

    def test_namumark_preserves_source_reading_and_translation(self) -> None:
        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_namumark(
                self.NAMUMARK_FIXTURE
            ),
            self.EXPECTED_LYRICS,
        )

    def test_headerless_interleaved_html_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        <table>
          <tr><th>합창</th></tr>
          <tr><td>
            持ち合った<br>
            모치앗타<br>
            서로가 가진 건<br>
            それぞれ<br>
            소레조레<br>
            제각각 달랐지만<br>
            視線は違えど<br>
            시센와 치가에도<br>
            바라보는 곳은 달라도<br>
            掛け合わせるわ 今<br>
            카케아와세루와 이마<br>
            지금 서로의 마음을 포개
          </td></tr>
        </table>
        """

        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_html(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_interleaved_html_across_rows_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        <table>
          <tr><th>勇者</th></tr>
          <tr><td>[ 가사 보기 ]</td></tr>
          <tr><td>持ち合った</td></tr>
          <tr><td>모치앗타</td></tr>
          <tr><td>서로가 가진 건</td></tr>
          <tr><td>それぞれ</td></tr>
          <tr><td>소레조레</td></tr>
          <tr><td>제각각 달랐지만</td></tr>
          <tr><td>視線は違えど</td></tr>
          <tr><td>시센와 치가에도</td></tr>
          <tr><td>바라보는 곳은 달라도</td></tr>
          <tr><td>掛け合わせるわ 今</td></tr>
          <tr><td>카케아와세루와 이마</td></tr>
          <tr><td>지금 서로의 마음을 포개</td></tr>
        </table>
        """

        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_html(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_multiline_namumark_cell_preserves_complete_groups(
        self,
    ) -> None:
        source = """
        ||<tablewidth=100%> {{{#!wiki style="text-align: center"
        持ち合った
        모치앗타
        서로가 가진 건
        それぞれ
        소레조레
        제각각 달랐지만
        視線は違えど
        시센와 치가에도
        바라보는 곳은 달라도
        掛け合わせるわ 今
        카케아와세루와 이마
        지금 서로의 마음을 포개
        }}} ||
        """

        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_namumark(source),
            (
                "持ち合った\n"
                "모치앗타\n"
                "서로가 가진 건\n"
                "\n"
                "それぞれ\n"
                "소레조레\n"
                "제각각 달랐지만\n"
                "\n"
                "視線は違えど\n"
                "시센와 치가에도\n"
                "바라보는 곳은 달라도\n"
                "\n"
                "掛け合わせるわ 今\n"
                "카케아와세루와 이마\n"
                "지금 서로의 마음을 포개"
            ),
        )

    def test_headerless_readings_without_translation_are_rejected(
        self,
    ) -> None:
        source = """
        <table><tr><td>
          持ち合った<br>모치앗타<br>
          それぞれ<br>소레조레<br>
          視線は違えど<br>시센와 치가에도<br>
          掛け合わせるわ 今<br>카케아와세루와 이마
        </td></tr></table>
        """

        self.assertIsNone(
            bot.extract_namuwiki_lyrics_from_html(source)
        )

    def test_short_metadata_translation_is_not_mistaken_for_lyrics(self) -> None:
        source = """
        <table>
          <tr><th>항목</th><th>번역</th></tr>
          <tr><td>제목</td><td>진창 울음</td></tr>
        </table>
        """

        self.assertIsNone(
            bot.extract_namuwiki_lyrics_from_html(source)
        )

    def test_long_bilingual_metadata_is_not_mistaken_for_lyrics(self) -> None:
        source = """
        <table>
          <tr><th>원문</th><th>한국어 번역</th></tr>
          <tr>
            <td>Official description for the song and its release.</td>
            <td>
              이 문서는 곡의 발매 정보와 제작 배경을 설명하는 문서이며
              실제 가사 내용은 수록되어 있지 않습니다.
            </td>
          </tr>
        </table>
        """

        self.assertIsNone(
            bot.extract_namuwiki_lyrics_from_html(source)
        )

    def test_repeated_lyrics_lines_are_preserved(self) -> None:
        source = """
        <table>
          <tr><th>원문</th><th>한국어 번역</th></tr>
          <tr><td>repeat</td><td>같은 후렴을 다시 불러</td></tr>
          <tr><td>repeat</td><td>같은 후렴을 다시 불러</td></tr>
        </table>
        """

        self.assertEqual(
            bot.extract_namuwiki_lyrics_from_html(source),
            (
                "repeat\n"
                "같은 후렴을 다시 불러\n\n"
                "repeat\n"
                "같은 후렴을 다시 불러"
            ),
        )

    def test_exact_song_title_is_the_first_document_candidate(self) -> None:
        track = make_track(self.DOCUMENT)

        candidates = bot.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], self.DOCUMENT)

    def test_artist_qualified_document_follows_ambiguous_song_title(
        self,
    ) -> None:
        track = make_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"

        candidates = bot.get_namuwiki_document_candidates(track)

        self.assertEqual(
            candidates[:2],
            ["らしさ", "らしさ(Official髭男dism)"],
        )

    def test_document_candidate_keeps_case_while_removing_video_label(
        self,
    ) -> None:
        track = make_track("SUNFADED (Official Audio)")

        candidates = bot.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], "SUNFADED")

    def test_artist_prefix_and_video_label_are_removed_from_candidate(
        self,
    ) -> None:
        track = make_track("CoMETIK - 泥濘鳴鳴 (Official MV)")

        candidates = bot.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], self.DOCUMENT)

    def test_unknown_leading_video_tag_has_clean_title_fallback(self) -> None:
        track = make_track(f"【シャニソン】{self.DOCUMENT}")

        candidates = bot.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[:2], [f"【シャニソン】{self.DOCUMENT}", self.DOCUMENT])

    def test_unicode_override_url_is_canonicalized(self) -> None:
        document, page_url = bot.split_namuwiki_candidate(
            f"https://namu.wiki/w/{self.DOCUMENT}?from=test#lyrics"
        )

        self.assertEqual(document, self.DOCUMENT)
        self.assertEqual(page_url, self.PAGE_URL)

    def test_public_html_request_returns_page_source_and_final_url(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = self.HTML_FIXTURE.encode("utf-8")
        response.geturl.return_value = self.PAGE_URL

        with (
            patch.object(bot, "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(
                bot.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            result = bot.request_namuwiki_html(self.PAGE_URL)

        self.assertEqual(result, (self.HTML_FIXTURE, self.PAGE_URL))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, self.PAGE_URL)
        self.assertIn("text/html", request.get_header("Accept"))

    def test_public_html_403_switches_to_discord_preview_renderer(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = self.HTML_FIXTURE.encode("utf-8")
        response.geturl.return_value = self.PAGE_URL
        blocked = bot.urllib.error.HTTPError(
            self.PAGE_URL,
            403,
            "Forbidden",
            {},
            None,
        )

        with (
            patch.object(bot, "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(bot, "NAMUWIKI_PREVIEW_FALLBACK_ENABLED", True),
            patch.object(bot, "namuwiki_prefer_preview_renderer", False),
            patch.object(
                bot.urllib.request,
                "urlopen",
                side_effect=[blocked, response, response],
            ) as urlopen,
        ):
            first_result = bot.request_namuwiki_html(self.PAGE_URL)
            second_result = bot.request_namuwiki_html(self.PAGE_URL)

            self.assertTrue(bot.namuwiki_prefer_preview_renderer)

        self.assertEqual(first_result, (self.HTML_FIXTURE, self.PAGE_URL))
        self.assertEqual(second_result, (self.HTML_FIXTURE, self.PAGE_URL))
        user_agents = [
            call.args[0].get_header("User-agent")
            for call in urlopen.call_args_list
        ]
        self.assertEqual(
            user_agents,
            [
                bot.NAMUWIKI_BROWSER_USER_AGENT,
                bot.NAMUWIKI_PREVIEW_USER_AGENT,
                bot.NAMUWIKI_PREVIEW_USER_AGENT,
            ],
        )

    def test_public_html_preview_fallback_can_be_disabled(self) -> None:
        blocked = bot.urllib.error.HTTPError(
            self.PAGE_URL,
            403,
            "Forbidden",
            {},
            None,
        )
        with (
            patch.object(bot, "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(bot, "NAMUWIKI_PREVIEW_FALLBACK_ENABLED", False),
            patch.object(bot, "namuwiki_prefer_preview_renderer", False),
            patch.object(
                bot.urllib.request,
                "urlopen",
                side_effect=blocked,
            ) as urlopen,
            self.assertRaises(bot.NamuWikiPageBlockedError),
        ):
            bot.request_namuwiki_html(self.PAGE_URL)

        urlopen.assert_called_once()

    def test_public_html_challenge_switches_to_discord_preview(self) -> None:
        challenge_response = MagicMock()
        challenge_response.__enter__.return_value = challenge_response
        challenge_response.read.return_value = (
            "<html><body>CAPTCHA 인증이 필요합니다.</body></html>"
        ).encode("utf-8")
        challenge_response.geturl.return_value = self.PAGE_URL
        preview_response = MagicMock()
        preview_response.__enter__.return_value = preview_response
        preview_response.read.return_value = self.HTML_FIXTURE.encode("utf-8")
        preview_response.geturl.return_value = self.PAGE_URL

        with (
            patch.object(bot, "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(bot, "NAMUWIKI_PREVIEW_FALLBACK_ENABLED", True),
            patch.object(bot, "namuwiki_prefer_preview_renderer", False),
            patch.object(
                bot.urllib.request,
                "urlopen",
                side_effect=[challenge_response, preview_response],
            ) as urlopen,
        ):
            result = bot.request_namuwiki_html(self.PAGE_URL)

        self.assertEqual(result, (self.HTML_FIXTURE, self.PAGE_URL))
        self.assertEqual(urlopen.call_count, 2)

    def test_api_request_reads_namumark_text_with_bearer_token(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"exists": True, "text": self.NAMUMARK_FIXTURE}
        ).encode("utf-8")

        with (
            patch.object(bot, "NAMUWIKI_API_TOKEN", "test-token"),
            patch.object(bot, "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 0),
            patch.object(
                bot.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            source = bot.request_namuwiki_api_source(self.DOCUMENT)

        self.assertEqual(source, self.NAMUMARK_FIXTURE)
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/edit/" + self.PAGE_URL.rsplit("/", 1)[1]))
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-token",
        )

    def test_exact_namuwiki_page_uses_rendered_html_without_api_token(
        self,
    ) -> None:
        track = make_track(self.DOCUMENT)
        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                bot,
                "request_namuwiki_html",
                return_value=(self.HTML_FIXTURE, self.PAGE_URL),
            ) as html_lookup,
        ):
            result = bot.lookup_namuwiki_lyrics(track)

        self.assertEqual(
            result,
            (
                self.EXPECTED_LYRICS,
                "나무위키 · 원문·독음·번역",
                self.PAGE_URL,
            ),
        )
        html_lookup.assert_called_once_with(self.PAGE_URL)

    def test_artist_mismatch_uses_qualified_namuwiki_document(self) -> None:
        track = make_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"
        wrong_document = "らしさ"
        right_document = "らしさ(Official髭男dism)"
        wrong_url = bot.split_namuwiki_candidate(wrong_document)[1]
        right_url = bot.split_namuwiki_candidate(right_document)[1]

        def page_with_artist(artist: str) -> str:
            return self.HTML_FIXTURE.replace(
                "<body>",
                (
                    "<body><table><tr><td>가수</td>"
                    f"<td>{artist}</td></tr></table>"
                ),
            )

        def request_page(page_url: str):
            if page_url == wrong_url:
                return page_with_artist("SUPER BEAVER"), wrong_url
            if page_url == right_url:
                return page_with_artist("Official髭男dism"), right_url
            return None

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                bot,
                "request_namuwiki_html",
                side_effect=request_page,
            ) as html_lookup,
        ):
            result = bot.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], self.EXPECTED_LYRICS)
        self.assertEqual(result[2], right_url)
        self.assertEqual(
            [call.args[0] for call in html_lookup.call_args_list],
            [wrong_url, right_url],
        )

    def test_existing_namuwiki_page_without_lyrics_returns_none(self) -> None:
        track = make_track(self.DOCUMENT)
        page_without_lyrics = """
        <html>
          <body>
            <table>
              <tr><th>원문</th><th>한국어 번역</th></tr>
              <tr>
                <td>Official description for the song and its release.</td>
                <td>
                  이 문서는 곡의 발매 정보와 제작 배경을 설명하는 문서이며
                  실제 가사 내용은 수록되어 있지 않습니다.
                </td>
              </tr>
            </table>
          </body>
        </html>
        """
        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                bot,
                "request_namuwiki_html",
                return_value=(page_without_lyrics, self.PAGE_URL),
            ) as html_lookup,
        ):
            result = bot.lookup_namuwiki_lyrics(track)

        self.assertIsNone(result)
        html_lookup.assert_called_once_with(self.PAGE_URL)

    def test_transient_page_failure_is_reported_for_retry(self) -> None:
        track = make_track(self.DOCUMENT)

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                bot,
                "get_namuwiki_document_candidates",
                return_value=[self.DOCUMENT],
            ),
            patch.object(
                bot,
                "request_namuwiki_html",
                side_effect=bot.NamuWikiLyricsError("request blocked"),
            ),
            self.assertRaisesRegex(
                bot.NamuWikiLyricsError,
                "configure NAMUWIKI_API_TOKEN",
            ),
        ):
            bot.lookup_namuwiki_lyrics(track)

    def test_api_namumark_is_preferred_when_token_is_configured(self) -> None:
        track = make_track(self.DOCUMENT)
        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", "test-token"),
            patch.object(
                bot,
                "request_namuwiki_api_source",
                return_value=self.NAMUMARK_FIXTURE,
            ) as api_lookup,
            patch.object(bot, "request_namuwiki_html") as html_lookup,
        ):
            result = bot.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], self.EXPECTED_LYRICS)
        self.assertEqual(result[2], self.PAGE_URL)
        api_lookup.assert_called_once_with(self.DOCUMENT)
        html_lookup.assert_not_called()

    def test_api_artist_mismatch_uses_qualified_document(self) -> None:
        track = make_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"
        right_document = "らしさ(Official髭男dism)"
        wrong_source = (
            "|| 가수 || SUPER BEAVER ||\n" + self.NAMUMARK_FIXTURE
        )
        right_source = (
            "|| 가수 || Official髭男dism ||\n" + self.NAMUMARK_FIXTURE
        )

        def request_source(document: str):
            if document == "らしさ":
                return wrong_source
            if document == right_document:
                return right_source
            return None

        with (
            patch.object(bot, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(bot, "NAMUWIKI_API_TOKEN", "test-token"),
            patch.object(
                bot,
                "request_namuwiki_api_source",
                side_effect=request_source,
            ) as api_lookup,
            patch.object(bot, "request_namuwiki_html") as html_lookup,
        ):
            result = bot.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], self.EXPECTED_LYRICS)
        self.assertEqual(
            result[2],
            bot.split_namuwiki_candidate(right_document)[1],
        )
        self.assertEqual(
            [call.args[0] for call in api_lookup.call_args_list],
            ["らしさ", right_document],
        )
        html_lookup.assert_not_called()

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
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
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
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
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
            patch.object(bot, "MUSIC_CHANNEL_SILENT", False),
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

    def test_default_options_leave_youtube_client_selection_to_ytdl(self) -> None:
        extractor_args = bot.YTDL_BASE_OPTIONS.get("extractor_args", {})
        youtube_args = extractor_args.get("youtube", {})

        self.assertNotIn("player_client", youtube_args)
        self.assertNotEqual(youtube_args.get("fetch_pot"), ["always"])

    async def test_repeated_query_uses_cache_without_a_second_worker(self) -> None:
        payload = {"id": "cachetest01", "title": "cached result"}
        worker = AsyncMock(return_value=payload)

        with (
            patch.object(bot, "run_ytdl_worker", new=worker),
            patch.object(bot, "YTDL_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(bot, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
                job_kind=bot.YtdlJobKind.USER_REQUEST,
            )
            first["title"] = "caller mutation"
            second = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:cache-protection-test",
                "cache test",
                job_kind=bot.YtdlJobKind.USER_REQUEST,
            )

        worker.assert_awaited_once()
        self.assertEqual(second["title"], "cached result")

    async def test_timed_out_worker_process_is_stopped(self) -> None:
        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                await asyncio.Event().wait()
                return b"", b""

        process = FakeProcess()
        stop_worker = AsyncMock()
        with (
            patch.object(
                bot.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch.object(bot, "stop_ytdl_worker", new=stop_worker),
            self.assertRaises(asyncio.TimeoutError),
        ):
            await bot.run_ytdl_worker({}, "timeout-test", 0.01)

        stop_worker.assert_awaited_once_with(process)

    async def test_repeated_cancellation_waits_for_process_cleanup(self) -> None:
        communicate_started = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()
        cleanup_cancelled = asyncio.Event()

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                await asyncio.Event().wait()
                return b"", b""

        async def stop_worker(process: object) -> None:
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise
            cleanup_finished.set()

        with (
            patch.object(
                bot.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(bot, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            worker = asyncio.create_task(
                bot.run_ytdl_worker({}, "repeated-cancel", 5.0)
            )
            await communicate_started.wait()
            worker.cancel()
            await cleanup_started.wait()
            worker.cancel()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(worker.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            with self.assertRaises(asyncio.CancelledError):
                await worker

        self.assertTrue(cleanup_finished.is_set())

    async def test_worker_log_includes_queue_wait_and_execution_time(self) -> None:
        class FakeProcess:
            returncode = 0
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                response = json.dumps({"info": {"id": "logged"}}).encode("utf-8")
                return response, b""

        with (
            patch.object(
                bot.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            self.assertLogs("music-bot", level="INFO") as logs,
        ):
            result = await bot.run_ytdl_worker(
                {},
                "log-test",
                1.0,
                label="stream log test",
                job_kind=bot.YtdlJobKind.PLAYBACK_STREAM.log_name,
                priority=str(int(bot.YtdlJobKind.PLAYBACK_STREAM)),
                queue_wait_seconds=0.25,
            )

        output = "\n".join(logs.output)
        self.assertEqual(result["id"], "logged")
        self.assertIn("queue_wait=0.250s", output)
        self.assertIn("worker=", output)
        self.assertIn("response_bytes=", output)

    async def test_worker_entrypoint_returns_a_structured_error(self) -> None:
        with self.assertRaises(RuntimeError):
            await bot.run_ytdl_worker({}, "", 5.0)

    async def test_extraction_slot_is_released_after_worker_timeout(self) -> None:
        scheduler = bot.YtdlPriorityScheduler(1)
        worker = AsyncMock(
            side_effect=[asyncio.TimeoutError, {"id": "next-request"}],
        )
        with (
            patch.object(bot, "ytdl_scheduler", scheduler),
            patch.object(bot, "YTDL_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(bot, "run_ytdl_worker", new=worker),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await bot.extract_ytdl_info(
                    bot.YTDL_OPTIONS,
                    "ytsearch1:worker-timeout-test",
                    "worker timeout test",
                    job_kind=bot.YtdlJobKind.USER_REQUEST,
                    use_cache=False,
                )

            result = await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:worker-after-timeout",
                "worker after timeout",
                job_kind=bot.YtdlJobKind.USER_REQUEST,
                use_cache=False,
            )

        await scheduler.shutdown()
        self.assertEqual(result["id"], "next-request")
        self.assertEqual(worker.await_count, 2)

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

    async def test_request_can_skip_the_general_interval(self) -> None:
        bot.ytdl_last_request_started_at = bot.time.monotonic()
        with patch.object(bot.asyncio, "sleep", new=AsyncMock()) as sleep:
            await bot.wait_for_ytdl_interval(0.0)

        sleep.assert_not_awaited()

    async def test_429_opens_circuit_and_blocks_new_worker(self) -> None:
        with patch.object(bot, "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800):
            opened = bot.trip_youtube_circuit(
                RuntimeError("HTTP Error 429: Too Many Requests")
            )

        self.assertTrue(opened)
        self.assertGreater(bot.get_youtube_circuit_retry_after(), 1700)

        worker = AsyncMock(return_value={"id": "should-not-run"})
        with (
            patch.object(bot, "run_ytdl_worker", new=worker),
            self.assertRaises(bot.YouTubeCircuitOpenError),
        ):
            await bot.extract_ytdl_info(
                bot.YTDL_OPTIONS,
                "ytsearch1:circuit-open-test",
                "circuit test",
                job_kind=bot.YtdlJobKind.USER_REQUEST,
                use_cache=False,
            )

        worker.assert_not_awaited()

    def test_only_rate_limit_errors_trip_the_circuit(self) -> None:
        self.assertTrue(
            bot.is_youtube_block_error(RuntimeError("Sign in to confirm you're not a bot"))
        )
        self.assertFalse(bot.is_youtube_block_error(RuntimeError("Video unavailable")))


class YtdlPrioritySchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None
        self.scheduler = bot.YtdlPriorityScheduler(1)

    async def asyncTearDown(self) -> None:
        await self.scheduler.shutdown()
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None

    async def submit(
        self,
        query: str,
        job_kind: bot.YtdlJobKind,
        *,
        timeout_seconds: float = 1.0,
    ) -> dict:
        return await self.scheduler.submit(
            {},
            query,
            query,
            job_kind=job_kind,
            timeout_seconds=timeout_seconds,
            minimum_interval_seconds=0.0,
        )

    async def assert_priority_order(
        self,
        lower_kind: bot.YtdlJobKind,
        higher_kind: bot.YtdlJobKind,
    ) -> list[str]:
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            order.append(query)
            if query == "blocker":
                started.set()
                await release.wait()
            return {"id": query}

        with patch.object(bot, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("blocker", bot.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()

            lower = asyncio.create_task(self.submit("lower", lower_kind))
            await asyncio.sleep(0)
            higher = asyncio.create_task(self.submit("higher", higher_kind))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(blocker, lower, higher)

        return order

    async def test_playback_stream_runs_before_queued_autoplay(self) -> None:
        order = await self.assert_priority_order(
            bot.YtdlJobKind.AUTOPLAY,
            bot.YtdlJobKind.PLAYBACK_STREAM,
        )

        self.assertEqual(order, ["blocker", "higher", "lower"])

    async def test_submit_replaces_done_worker_before_callback_cleanup(self) -> None:
        finished_worker = asyncio.create_task(asyncio.sleep(0))
        await finished_worker
        self.scheduler.worker_tasks.add(finished_worker)

        with patch.object(
            bot,
            "run_ytdl_worker",
            new=AsyncMock(return_value={"id": "replacement"}),
        ):
            result = await self.submit(
                "replacement",
                bot.YtdlJobKind.USER_REQUEST,
            )

        self.assertEqual(result["id"], "replacement")
        self.assertNotIn(finished_worker, self.scheduler.worker_tasks)

    async def test_playback_preempts_autoplay_rate_limit_wait(self) -> None:
        autoplay_waiting = asyncio.Event()
        autoplay_release = asyncio.Event()
        executed: list[str] = []

        async def interval_wait(
            minimum_interval: float | None = None,
            *,
            on_interval_reserved: object = None,
        ) -> None:
            if minimum_interval is None:
                autoplay_waiting.set()
                await autoplay_release.wait()
            if callable(on_interval_reserved):
                on_interval_reserved()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            executed.append(query)
            return {"id": query}

        with (
            patch.object(bot, "wait_for_ytdl_interval", side_effect=interval_wait),
            patch.object(bot, "run_ytdl_worker", side_effect=worker),
        ):
            autoplay = asyncio.create_task(
                self.scheduler.submit(
                    {},
                    "autoplay",
                    "autoplay",
                    job_kind=bot.YtdlJobKind.AUTOPLAY,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=None,
                )
            )
            await autoplay_waiting.wait()
            playback = await asyncio.wait_for(
                self.scheduler.submit(
                    {},
                    "playback",
                    "playback",
                    job_kind=bot.YtdlJobKind.PLAYBACK_STREAM,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=0.0,
                ),
                timeout=0.2,
            )
            autoplay.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await autoplay
            autoplay_release.set()

        self.assertEqual(playback["id"], "playback")
        self.assertEqual(executed, ["playback"])

    async def test_reserved_rate_slot_is_not_cancelled_before_worker_start(self) -> None:
        slot_reserved = asyncio.Event()
        release_interval = asyncio.Event()
        order: list[str] = []
        interval_calls = 0

        async def interval_wait(
            minimum_interval: float | None = None,
            *,
            on_interval_reserved: object = None,
        ) -> None:
            nonlocal interval_calls
            interval_calls += 1
            if callable(on_interval_reserved):
                on_interval_reserved()
            if interval_calls == 1:
                slot_reserved.set()
                await release_interval.wait()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            order.append(query)
            return {"id": query}

        with (
            patch.object(bot, "wait_for_ytdl_interval", side_effect=interval_wait),
            patch.object(bot, "run_ytdl_worker", side_effect=worker),
        ):
            autoplay = asyncio.create_task(
                self.scheduler.submit(
                    {},
                    "autoplay",
                    "autoplay",
                    job_kind=bot.YtdlJobKind.AUTOPLAY,
                    timeout_seconds=1.0,
                    minimum_interval_seconds=None,
                )
            )
            await slot_reserved.wait()
            user = asyncio.create_task(
                self.submit("user", bot.YtdlJobKind.USER_REQUEST)
            )
            await asyncio.sleep(0)

            self.assertFalse(autoplay.done())
            self.assertFalse(user.done())
            release_interval.set()
            await asyncio.gather(autoplay, user)

        self.assertEqual(order, ["autoplay", "user"])

    async def test_user_search_runs_before_queued_autoplay(self) -> None:
        order = await self.assert_priority_order(
            bot.YtdlJobKind.AUTOPLAY,
            bot.YtdlJobKind.USER_REQUEST,
        )

        self.assertEqual(order, ["blocker", "higher", "lower"])

    async def test_cancelled_queued_autoplay_is_not_executed(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        executed: list[str] = []

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            executed.append(query)
            if query == "blocker":
                started.set()
                await release.wait()
            return {"id": query}

        with patch.object(bot, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("blocker", bot.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            autoplay = asyncio.create_task(
                self.submit("cancelled-autoplay", bot.YtdlJobKind.AUTOPLAY)
            )
            await asyncio.sleep(0)
            autoplay.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await autoplay
            release.set()
            await blocker
            await self.scheduler.queue.join()

        self.assertEqual(executed, ["blocker"])

    async def test_worker_concurrency_never_exceeds_one(self) -> None:
        active = 0
        maximum_active = 0

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"id": query}

        with patch.object(bot, "run_ytdl_worker", side_effect=worker):
            await asyncio.gather(
                *(
                    self.submit(f"job-{index}", bot.YtdlJobKind.USER_REQUEST)
                    for index in range(6)
                )
            )

        self.assertEqual(maximum_active, 1)

    async def test_subtitle_request_does_not_block_stream_resolution(self) -> None:
        subtitle_started = asyncio.Event()
        release_subtitle = asyncio.Event()
        track = make_track("subtitle")

        async def lyrics_job(*args: object) -> str:
            subtitle_started.set()
            await release_subtitle.wait()
            return "lyrics"

        worker = AsyncMock(return_value={"id": "stream"})
        with (
            patch.object(bot, "auxiliary_network_semaphore", asyncio.Semaphore(1)),
            patch.object(
                bot,
                "wait_for_youtube_subtitle_interval",
                new=AsyncMock(),
            ),
            patch.object(bot, "run_lyrics_job", side_effect=lyrics_job),
            patch.object(bot, "run_ytdl_worker", new=worker),
        ):
            subtitle = asyncio.create_task(
                bot.get_selected_youtube_subtitle(
                    track,
                    ("ko", "vtt", "https://example.test/subtitle"),
                    purpose="test",
                )
            )
            await subtitle_started.wait()
            stream = await asyncio.wait_for(
                self.submit("stream", bot.YtdlJobKind.PLAYBACK_STREAM),
                timeout=0.2,
            )
            release_subtitle.set()
            lyrics = await subtitle

        self.assertEqual(stream["id"], "stream")
        self.assertEqual(lyrics, "lyrics")
        worker.assert_awaited_once()

    async def test_subtitle_rechecks_circuit_after_rate_limit_wait(self) -> None:
        semaphore = asyncio.Semaphore(1)
        lyrics_job = AsyncMock(return_value="lyrics")

        async def open_circuit_during_wait() -> None:
            bot.youtube_circuit_open_until = bot.time.monotonic() + 60
            bot.youtube_circuit_reason = "test circuit"

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(
                bot,
                "wait_for_youtube_subtitle_interval",
                side_effect=open_circuit_during_wait,
            ),
            patch.object(bot, "run_lyrics_job", new=lyrics_job),
            self.assertRaises(bot.YouTubeCircuitOpenError),
        ):
            await bot.get_selected_youtube_subtitle(
                make_track("subtitle"),
                ("ko", "vtt", "https://example.test/subtitle"),
                purpose="test",
            )

        lyrics_job.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)

    async def test_multiple_guild_jobs_share_priority_and_single_worker(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        order: list[str] = []
        active = 0
        maximum_active = 0

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            order.append(query)
            if query == "guild-a-blocker":
                started.set()
                await release.wait()
            await asyncio.sleep(0)
            active -= 1
            return {"id": query}

        with patch.object(bot, "run_ytdl_worker", side_effect=worker):
            blocker = asyncio.create_task(
                self.submit("guild-a-blocker", bot.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            jobs = [
                asyncio.create_task(
                    self.submit("guild-a-autoplay", bot.YtdlJobKind.AUTOPLAY)
                ),
                asyncio.create_task(
                    self.submit("guild-b-autoplay", bot.YtdlJobKind.AUTOPLAY)
                ),
                asyncio.create_task(
                    self.submit("guild-a-user", bot.YtdlJobKind.USER_REQUEST)
                ),
                asyncio.create_task(
                    self.submit(
                        "guild-b-playback",
                        bot.YtdlJobKind.PLAYBACK_STREAM,
                    )
                ),
            ]
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(blocker, *jobs)

        self.assertEqual(
            order,
            [
                "guild-a-blocker",
                "guild-b-playback",
                "guild-a-user",
                "guild-a-autoplay",
                "guild-b-autoplay",
            ],
        )
        self.assertEqual(maximum_active, 1)

    async def test_scheduler_shutdown_does_not_recancel_worker_cleanup(self) -> None:
        communicate_started = asyncio.Event()
        communication_cancelled = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_finished = asyncio.Event()
        cleanup_cancelled = asyncio.Event()
        stop_calls = 0

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    communication_cancelled.set()
                    raise
                return b"", b""

        async def stop_worker(process: object) -> None:
            nonlocal stop_calls
            stop_calls += 1
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise
            cleanup_finished.set()

        with (
            patch.object(
                bot.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(bot, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            submission = asyncio.create_task(
                self.submit(
                    "shutdown-cleanup",
                    bot.YtdlJobKind.USER_REQUEST,
                    timeout_seconds=5.0,
                )
            )
            await communicate_started.wait()
            shutdown = asyncio.create_task(self.scheduler.shutdown())
            await cleanup_started.wait()
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertFalse(shutdown.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            await shutdown
            result = await asyncio.gather(submission, return_exceptions=True)

        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertEqual(stop_calls, 1)
        self.assertTrue(cleanup_finished.is_set())
        self.assertTrue(communication_cancelled.is_set())
        self.assertFalse(self.scheduler.active_jobs)
        self.assertFalse(self.scheduler.worker_tasks)

    async def test_caller_cancellation_overlapping_shutdown_cleans_once(self) -> None:
        communicate_started = asyncio.Event()
        communication_cancelled = asyncio.Event()
        cleanup_started = asyncio.Event()
        cleanup_release = asyncio.Event()
        cleanup_cancelled = asyncio.Event()
        stop_calls = 0

        class FakeProcess:
            returncode = None
            pid = 12345

            async def communicate(self, request: bytes) -> tuple[bytes, bytes]:
                communicate_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    communication_cancelled.set()
                    raise
                return b"", b""

        async def stop_worker(process: object) -> None:
            nonlocal stop_calls
            stop_calls += 1
            cleanup_started.set()
            try:
                await cleanup_release.wait()
            except asyncio.CancelledError:
                cleanup_cancelled.set()
                raise

        with (
            patch.object(
                bot.asyncio,
                "create_subprocess_exec",
                new=AsyncMock(return_value=FakeProcess()),
            ),
            patch.object(bot, "stop_ytdl_worker", side_effect=stop_worker),
        ):
            submission = asyncio.create_task(
                self.submit(
                    "caller-cancel-cleanup",
                    bot.YtdlJobKind.USER_REQUEST,
                    timeout_seconds=5.0,
                )
            )
            await communicate_started.wait()
            submission.cancel()
            await cleanup_started.wait()
            execution_task = next(iter(self.scheduler.active_jobs.values())).execution_task
            self.assertIsNotNone(execution_task)
            cancelling_count = execution_task.cancelling()

            shutdown = asyncio.create_task(self.scheduler.shutdown())
            for _ in range(3):
                await asyncio.sleep(0)

            self.assertEqual(execution_task.cancelling(), cancelling_count)
            self.assertFalse(shutdown.done())
            self.assertFalse(cleanup_cancelled.is_set())
            cleanup_release.set()
            await shutdown
            result = await asyncio.gather(submission, return_exceptions=True)

        self.assertIsInstance(result[0], asyncio.CancelledError)
        self.assertEqual(stop_calls, 1)
        self.assertTrue(communication_cancelled.is_set())
        self.assertFalse(self.scheduler.active_jobs)
        self.assertFalse(self.scheduler.worker_tasks)

    async def test_shutdown_cancels_running_and_pending_jobs(self) -> None:
        started = asyncio.Event()

        async def worker(
            options: dict,
            query: str,
            timeout_seconds: float,
            **kwargs: object,
        ) -> dict:
            started.set()
            await asyncio.Event().wait()
            return {"id": query}

        with patch.object(bot, "run_ytdl_worker", side_effect=worker):
            running = asyncio.create_task(
                self.submit("running", bot.YtdlJobKind.USER_REQUEST)
            )
            await started.wait()
            pending = asyncio.create_task(
                self.submit("pending", bot.YtdlJobKind.AUTOPLAY)
            )
            await asyncio.sleep(0)
            await self.scheduler.shutdown()
            results = await asyncio.gather(
                running,
                pending,
                return_exceptions=True,
            )

        self.assertTrue(
            all(isinstance(result, asyncio.CancelledError) for result in results)
        )


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
            patch.object(bot.commands.Bot, "close", new=base_close),
        ):
            await bot.MusicBot.close(bot.bot)

        self.assertTrue(cancelled.is_set())
        self.assertTrue(task.cancelled())
        self.assertFalse(bot.housekeeping_tasks)
        self.assertEqual(order, ["housekeeping", "discord"])

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
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None

    async def asyncTearDown(self) -> None:
        bot.youtube_music_cache.clear()
        bot.youtube_music_client = None
        bot.youtube_music_last_request_started_at = 0.0
        bot.ytdl_last_request_started_at = 0.0
        bot.youtube_circuit_open_until = 0.0
        bot.youtube_circuit_reason = None

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
                bot,
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
            bot.youtube_circuit_open_until = bot.time.monotonic() + 60
            bot.youtube_circuit_reason = "test circuit"

        with (
            patch.object(bot, "auxiliary_network_semaphore", semaphore),
            patch.object(bot.asyncio, "to_thread", new=to_thread),
            patch.object(bot, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                bot,
                "wait_for_youtube_music_interval",
                side_effect=open_circuit_during_wait,
            ),
            self.assertRaises(bot.YouTubeCircuitOpenError),
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


class QueueTests(unittest.TestCase):
    def test_remove_by_id_uses_stable_track_identity(self) -> None:
        first = make_track("first")
        second = make_track("second")
        third = make_track("third")
        state = bot.GuildMusicState(queue=deque([third, first, second]))

        removed = bot.remove_queued_track_by_id(state, second.track_id)

        self.assertIs(removed, second)
        self.assertEqual(list(state.queue), [third, first])

    def test_remove_range_is_inclusive(self) -> None:
        tracks = [make_track(f"track-{index}") for index in range(1, 21)]
        state = bot.GuildMusicState(queue=deque(tracks))

        result = bot.remove_queued_track_range_by_ids(
            state,
            tracks[4].track_id,
            tracks[12].track_id,
        )

        self.assertIsNotNone(result)
        removed, start_index, end_index = result
        self.assertEqual((start_index, end_index), (4, 12))
        self.assertEqual(removed, tracks[4:13])
        self.assertEqual(len(state.queue), 11)
        self.assertEqual(list(state.queue), tracks[:4] + tracks[13:])

    def test_remove_range_accepts_reversed_boundaries(self) -> None:
        tracks = [make_track(f"track-{index}") for index in range(1, 21)]
        state = bot.GuildMusicState(queue=deque(tracks))

        result = bot.remove_queued_track_range_by_ids(
            state,
            tracks[12].track_id,
            tracks[4].track_id,
        )

        self.assertIsNotNone(result)
        removed, start_index, end_index = result
        self.assertEqual((start_index, end_index), (4, 12))
        self.assertEqual(removed, tracks[4:13])
        self.assertEqual(len(state.queue), 11)

    def test_remove_range_keeps_queue_when_endpoint_is_missing(self) -> None:
        tracks = [make_track("first"), make_track("second")]
        state = bot.GuildMusicState(queue=deque(tracks))

        result = bot.remove_queued_track_range_by_ids(
            state,
            tracks[0].track_id,
            "missing-track-id",
        )

        self.assertIsNone(result)
        self.assertEqual(list(state.queue), tracks)


class QueueRangeDeleteViewTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_confirm_deletes_inclusive_range(self) -> None:
        guild_id = 988
        tracks = [make_track(f"track-{index}") for index in range(1, 21)]
        state = bot.get_state(guild_id)
        state.queue.extend(tracks)
        view = bot.QueueRangeDeleteView(guild_id)
        view.start_track_id = tracks[4].track_id
        view.end_track_id = tracks[12].track_id
        view.confirm_button.disabled = False
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 989

        with (
            patch.object(bot, "schedule_autoplay_refill") as schedule_refill,
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
            ) as schedule_cleanup,
        ):
            await view.confirm_button.callback(interaction)

        self.assertEqual(len(state.queue), 11)
        self.assertEqual(list(state.queue), tracks[:4] + tracks[13:])
        schedule_refill.assert_called_once_with(guild_id)
        interaction.response.edit_message.assert_awaited_once()
        kwargs = interaction.response.edit_message.await_args.kwargs
        self.assertIn("5~13번", kwargs["content"])
        self.assertIn("9곡", kwargs["content"])
        self.assertIsNone(kwargs["view"])
        schedule_cleanup.assert_called_once_with(
            state,
            interaction.message,
            bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )

    async def test_single_delete_resets_queue_message_expiry(self) -> None:
        guild_id = 990
        first = make_track("first")
        second = make_track("second")
        state = bot.get_state(guild_id)
        state.queue.extend([first, second])
        select = bot.QueueRemoveSelect(guild_id)
        select._values = [first.track_id]
        interaction = MagicMock()
        interaction.response.edit_message = AsyncMock()
        interaction.message = MagicMock()
        interaction.message.id = 991

        with (
            patch.object(bot, "schedule_autoplay_refill"),
            patch.object(
                bot,
                "schedule_queue_message_cleanup",
            ) as schedule_cleanup,
        ):
            await select.callback(interaction)

        self.assertEqual(list(state.queue), [second])
        schedule_cleanup.assert_called_once_with(
            state,
            interaction.message,
            bot.QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )


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
            pass

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
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
            pass

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
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

        timer = None
        with (
            patch.object(bot, "EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS", 0),
            patch.object(
                bot,
                "show_idle_panel",
                new=AsyncMock(side_effect=block_idle_panel),
            ) as show_idle_panel,
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
                await asyncio.wait_for(timer, timeout=1)
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

    async def test_leave_does_not_disconnect_voice_moved_during_panel_update(
        self,
    ) -> None:
        guild_id = 816
        panel_started = asyncio.Event()
        release_panel = asyncio.Event()

        class Channel:
            def __init__(self, channel_id: int) -> None:
                self.id = channel_id
                self.mention = f"<#{channel_id}>"

        old_channel = Channel(1101)
        new_channel = Channel(1102)

        class Voice:
            def __init__(self) -> None:
                self.channel = old_channel
                self.connected = True
                self.playing = True
                self.move_to = AsyncMock(side_effect=self._move_to)
                self.disconnect = AsyncMock(side_effect=self._disconnect)

            def is_connected(self) -> bool:
                return self.connected

            def is_playing(self) -> bool:
                return self.playing

            def is_paused(self) -> bool:
                return False

            def stop(self) -> None:
                self.playing = False

            async def _move_to(self, channel: Channel) -> None:
                self.channel = channel

            async def _disconnect(self) -> None:
                self.connected = False

        voice = Voice()

        class Guild:
            id = guild_id
            voice_client = voice

        guild = Guild()

        class Response:
            def __init__(self) -> None:
                self.send_message = AsyncMock()

            def is_done(self) -> bool:
                return False

        class User:
            voice = type("MemberVoice", (), {"channel": old_channel})()

        class Interaction:
            pass

        interaction = Interaction()
        interaction.guild_id = guild_id
        interaction.guild = guild
        interaction.user = User()
        interaction.response = Response()
        state = bot.get_state(guild_id)
        state.voice = voice
        state.current = make_track("current")
        state.queue.append(make_track("queued"))

        def discard_housekeeping(coroutine) -> None:
            coroutine.close()

        async def block_idle_panel(
            requested_guild_id: int,
            requested_state: bot.GuildMusicState,
        ) -> None:
            self.assertEqual(requested_guild_id, guild_id)
            self.assertIs(requested_state, state)
            panel_started.set()
            await release_panel.wait()

        leave_task = None
        with (
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
                leave_task = asyncio.create_task(bot.leave.callback(interaction))
                await asyncio.wait_for(panel_started.wait(), timeout=1)

                self.assertIsNone(state.current)
                self.assertFalse(state.queue)
                self.assertFalse(voice.is_playing())
                self.assertFalse(leave_task.done())

                result = await asyncio.wait_for(
                    bot.ensure_voice_channel(guild, new_channel, state),
                    timeout=1,
                )

                self.assertEqual(result, (True, None))
                voice.move_to.assert_awaited_once_with(new_channel)
                voice.disconnect.assert_not_awaited()
                self.assertIs(state.voice, voice)
                self.assertIs(voice.channel, new_channel)

                release_panel.set()
                await asyncio.wait_for(leave_task, timeout=1)
            finally:
                release_panel.set()
                if leave_task is not None and not leave_task.done():
                    leave_task.cancel()
                if leave_task is not None:
                    await asyncio.gather(leave_task, return_exceptions=True)
                bot.cancel_empty_channel_disconnect(state)
                bot.music_states.pop(guild_id, None)

        show_idle_panel.assert_awaited_once_with(guild_id, state)
        voice.disconnect.assert_not_awaited()
        self.assertTrue(voice.is_connected())
        self.assertIs(state.voice, voice)
        self.assertIs(voice.channel, new_channel)
        interaction.response.send_message.assert_awaited_once_with(
            "재생은 중지했지만 봇의 음성 채널이 변경되어 연결 해제를 취소했어요.",
            ephemeral=True,
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
            pass

        member = Member()
        member.guild = guild
        member.voice = type("MemberVoice", (), {"channel": channel})()
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
        scheduler = bot.YtdlPriorityScheduler(1)
        worker_started = asyncio.Event()
        release_worker = asyncio.Event()

        async def worker(*args: object, **kwargs: object) -> dict:
            worker_started.set()
            await release_worker.wait()
            return {"id": "blocker"}

        with (
            patch.object(bot, "ytdl_scheduler", scheduler),
            patch.object(bot, "run_ytdl_worker", side_effect=worker),
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
