import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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

    def test_local_test_track_skips_the_lyrics_service(self) -> None:
        track = make_track("local")
        track.is_local = True

        with patch.object(bot, "request_lyrics_records") as request:
            lyrics = bot.lookup_track_lyrics(track)

        self.assertIsNone(lyrics)
        request.assert_not_called()


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

    def test_track_keeps_manual_but_not_automatic_caption_metadata(self) -> None:
        track = bot.make_track_from_info(
            {
                "id": "captions001",
                "title": "Captioned song",
                "webpage_url": "https://www.youtube.com/watch?v=captions001",
                "subtitles": {
                    "ja": [{"ext": "json3", "url": "https://example.com/manual"}]
                },
                "automatic_captions": {
                    "en": [{"ext": "json3", "url": "https://example.com/auto"}]
                },
                "language": "ja",
            },
            "tester",
            "https://www.youtube.com/watch?v=captions001",
        )

        self.assertEqual(set(track.manual_subtitles), {"ja"})
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


class LyricsMessageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_lyrics_publish(state)
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

        with patch.object(bot, "get_track_lyrics", new=AsyncMock(return_value=None)):
            await bot.publish_current_lyrics(guild_id, track)

        channel.send.assert_awaited_once()
        message.edit.assert_awaited_once()
        final_embed = message.edit.await_args.kwargs["embed"]
        self.assertEqual(final_embed.description, "미제공")
        self.assertIs(state.lyrics_message, message)

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
        _, message = self.make_channel_and_message()
        state = bot.get_state(guild_id)
        state.current = make_track("current")
        state.lyrics_message = message

        bot.stop_playback(state, guild_id)
        await asyncio.sleep(0)

        message.delete.assert_awaited_once()
        self.assertIsNone(state.lyrics_message)

    async def test_empty_queue_deletes_the_lyrics_message(self) -> None:
        guild_id = 604
        _, message = self.make_channel_and_message()
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

    async def test_startup_keeps_latest_panel_and_cleans_channel(self) -> None:
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
            patch.object(bot, "get_control_message_id", return_value=older.id),
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
                clean_channel=True,
            )

        self.assertIs(result, newest)
        self.assertIs(state.control_message, newest)
        self.assertTrue(channel.history_called)
        self.assertIsNone(channel.history_limit)
        channel.fetch_message.assert_awaited_once_with(older.id)
        channel.send.assert_not_awaited()
        older.delete.assert_awaited_once()
        user_request.delete.assert_awaited_once()
        temporary_feedback.delete.assert_awaited_once()
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

        with patch.object(bot, "schedule_autoplay_refill") as schedule_refill:
            await view.confirm_button.callback(interaction)

        self.assertEqual(len(state.queue), 11)
        self.assertEqual(list(state.queue), tracks[:4] + tracks[13:])
        schedule_refill.assert_called_once_with(guild_id)
        interaction.response.edit_message.assert_awaited_once()
        kwargs = interaction.response.edit_message.await_args.kwargs
        self.assertIn("5~13번", kwargs["content"])
        self.assertIn("9곡", kwargs["content"])
        self.assertIsNone(kwargs["view"])


class PlaybackSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        for state in bot.music_states.values():
            bot.cancel_autoplay_refill(state)
            bot.cancel_lyrics_publish(state)
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
            patch.object(bot, "schedule_lyrics_publish") as schedule_lyrics,
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
        schedule_lyrics.assert_called_once_with(guild_id, first)

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
