import ast
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import bot
import music_discord_display
from music_models import GuildMusicState, RecentPlaybackEntry, Track


MOVED_NAMES = (
    "CONTROL_PANEL_TITLES",
    "DISCORD_EMBED_FIELD_LIMIT",
    "IDLE_PANEL_TITLE",
    "LYRICS_INLINE_LIMIT",
    "MUSIC_CHANNEL_DELETE_REQUESTS",
    "MUSIC_CHANNEL_SILENT",
    "PLAYING_PANEL_TITLE",
    "delete_interaction_response_later",
    "delete_message_later",
    "delete_music_request_message",
    "delete_private_interaction_message",
    "describe_queue_selection",
    "format_duration",
    "is_silent_music_channel",
    "log_discord_http_error",
    "make_bulk_embed",
    "make_idle_player_embed",
    "make_lyrics_embed",
    "make_lyrics_file",
    "make_lyrics_variant_embed",
    "make_player_embed",
    "make_queue_embed",
    "make_queue_line",
    "make_recent_playback_embed",
    "make_track_embed",
    "make_track_link",
    "notify_playback_error",
    "requester_label",
    "send_music_request_reply",
    "single_line",
    "truncate_option_text",
    "truncate_text",
)


def make_player_track(title: str, *, requester_id: int | None = None) -> Track:
    return Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        requester_id=requester_id,
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        duration=65,
    )


def make_text_track(
    title: str = "Example Song",
    *,
    duration: int | None = 65,
    requester_id: int | None = None,
) -> Track:
    return Track(
        title=title,
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        requester_id=requester_id,
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        duration=duration,
    )


def make_lyrics_track() -> Track:
    return Track(
        title="Video title",
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        artist="Artist",
        song_name="Song title",
        lyrics_source="LRCLIB",
    )


class MusicDiscordDisplayTests(unittest.TestCase):
    def test_bot_reexports_discord_display_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_discord_display, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_discord_display.__file__).read_text(encoding="utf-8")
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
                "discord",
                "io",
                "music_config",
                "music_models",
            },
        )

    def test_player_and_queue_embeds_preserve_visible_state(self) -> None:
        current = make_player_track("current", requester_id=123)
        queued = make_player_track("queued")
        state = GuildMusicState(
            current=current,
            repeat_one=True,
            autoplay_enabled=True,
        )
        state.queue.append(queued)

        player = music_discord_display.make_player_embed(current, state)
        player_fields = {field.name: field.value for field in player.fields}
        queue = music_discord_display.make_queue_embed(state)
        queue_fields = {field.name: field.value for field in queue.fields}
        bulk = music_discord_display.make_bulk_embed(
            [current, queued],
            "Added playlist to queue",
        )
        bulk_fields = {field.name: field.value for field in bulk.fields}

        self.assertEqual(player.title, music_discord_display.PLAYING_PANEL_TITLE)
        self.assertIn("<@123>", player.description)
        self.assertEqual(player_fields["대기열"], "1곡")
        self.assertEqual(player_fields["반복"], "켜짐")
        self.assertEqual(player_fields["자동재생"], "켜짐")
        self.assertIn("queued", player_fields["다음 곡"])
        self.assertIn("current", queue_fields["지금 재생 중"])
        self.assertIn("queued", queue_fields["다음 곡"])
        self.assertIn("current", bulk.description)
        self.assertIn("queued", bulk.description)
        self.assertEqual(bulk_fields["Added"], "2")
        self.assertEqual(
            bulk_fields["Limit"],
            str(music_discord_display.MAX_BULK_TRACKS),
        )

    def test_idle_and_queue_selection_contract(self) -> None:
        first = make_player_track("first")
        state = GuildMusicState()
        state.queue.append(first)

        idle = music_discord_display.make_idle_player_embed()

        self.assertEqual(idle.title, music_discord_display.IDLE_PANEL_TITLE)
        self.assertEqual(
            music_discord_display.CONTROL_PANEL_TITLES,
            frozenset(
                {
                    music_discord_display.PLAYING_PANEL_TITLE,
                    music_discord_display.IDLE_PANEL_TITLE,
                }
            ),
        )
        self.assertEqual(
            music_discord_display.describe_queue_selection(state, first.track_id),
            "1. first",
        )
        self.assertEqual(
            music_discord_display.describe_queue_selection(state, None),
            "선택 안 함",
        )

    def test_duration_and_requester_formatting_contract(self) -> None:
        self.assertEqual(music_discord_display.format_duration(None), "live")
        self.assertEqual(music_discord_display.format_duration(65), "1:05")
        self.assertEqual(music_discord_display.format_duration(3661), "1:01:01")
        self.assertEqual(
            music_discord_display.requester_label(make_text_track()),
            "tester",
        )
        self.assertEqual(
            music_discord_display.requester_label(
                make_text_track(requester_id=123)
            ),
            "<@123>",
        )

    def test_link_queue_and_truncation_contract(self) -> None:
        track = make_text_track("  Example\n Song  ")

        self.assertEqual(
            music_discord_display.single_line(track.title),
            "Example Song",
        )
        self.assertEqual(music_discord_display.truncate_text("abcd", 3), "ab…")
        self.assertEqual(
            music_discord_display.make_track_link(track),
            "[Example Song](https://www.youtube.com/watch?v=abcdefghijk)",
        )
        self.assertEqual(
            music_discord_display.make_queue_line(2, track),
            "2. Example Song - 1:05",
        )
        self.assertEqual(
            music_discord_display.truncate_option_text("abcd", 3),
            "ab…",
        )

    def test_recent_playback_embed_is_newest_first_and_private_ready(self) -> None:
        entries = (
            RecentPlaybackEntry(
                identity_keys=frozenset({"song:newest"}),
                title="Newest Song",
                webpage_url="https://www.youtube.com/watch?v=aaaaaaaaaaa",
                played_at=1_700_000_100.0,
                expires_at=200.0,
            ),
            RecentPlaybackEntry(
                identity_keys=frozenset({"song:older"}),
                title="Older Song",
                webpage_url="https://www.youtube.com/watch?v=bbbbbbbbbbb",
                played_at=1_700_000_000.0,
                expires_at=100.0,
            ),
        )

        embed = music_discord_display.make_recent_playback_embed(entries)

        self.assertEqual(embed.title, "🕘 최근 재생곡")
        self.assertEqual(len(embed.fields), 1)
        self.assertLess(
            embed.fields[0].value.index("Newest Song"),
            embed.fields[0].value.index("Older Song"),
        )
        self.assertIn(
            "[Newest Song](https://www.youtube.com/watch?v=aaaaaaaaaaa)",
            embed.fields[0].value,
        )
        self.assertIn("<t:1700000100:R>", embed.fields[0].value)

    def test_recent_playback_embed_handles_empty_and_fifty_entry_limits(
        self,
    ) -> None:
        empty = music_discord_display.make_recent_playback_embed(())
        entries = tuple(
            RecentPlaybackEntry(
                identity_keys=frozenset({f"song:{index}"}),
                title=f"{index} " + "긴 제목 " * 20,
                webpage_url=(
                    "https://www.youtube.com/watch?v=" + f"{index:011d}"
                ),
                played_at=1_700_000_000.0 + index,
                expires_at=100.0 + index,
            )
            for index in range(50)
        )
        full = music_discord_display.make_recent_playback_embed(entries)

        self.assertIn("없어요", empty.description)
        self.assertEqual(len(full.fields), 5)
        self.assertTrue(all(len(field.value) <= 1024 for field in full.fields))
        self.assertLessEqual(len(full), 6000)

    def test_original_and_variant_embeds_preserve_metadata(self) -> None:
        track = make_lyrics_track()

        original = music_discord_display.make_lyrics_embed(
            track,
            "original lyrics",
        )
        variant = music_discord_display.make_lyrics_variant_embed(
            track,
            "나무위키 가사",
            "variant lyrics",
            "NamuWiki",
            "https://namu.wiki/w/example",
        )

        self.assertEqual(original.title, "가사 · Song title")
        self.assertEqual(original.description, "original lyrics")
        self.assertEqual(original.author.name, "Artist")
        self.assertEqual(original.footer.text, "LRCLIB · 원문 가사")
        self.assertEqual(variant.title, "나무위키 가사 · Song title")
        self.assertEqual(variant.description, "variant lyrics")
        self.assertEqual(variant.url, "https://namu.wiki/w/example")
        self.assertEqual(variant.footer.text, "NamuWiki")

    def test_lyrics_file_contains_full_utf8_text(self) -> None:
        lyrics = "첫 줄\n第二行"
        attachment = music_discord_display.make_lyrics_file(
            lyrics,
            "translated-lyrics.txt",
        )
        try:
            self.assertEqual(attachment.filename, "translated-lyrics.txt")
            self.assertEqual(attachment.fp.read(), lyrics.encode("utf-8"))
        finally:
            attachment.close()


class MusicDiscordMessageTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_server_error() -> bot.discord.DiscordServerError:
        response = MagicMock(status=500, reason="Internal Server Error")
        return bot.discord.DiscordServerError(
            response,
            "<html>temporary failure</html>",
        )

    async def test_music_reply_ignores_transient_discord_500(self) -> None:
        message = MagicMock()
        message.reply = AsyncMock(side_effect=self.make_server_error())

        with (
            patch.object(music_discord_display, "MUSIC_CHANNEL_SILENT", False),
            self.assertLogs("music-bot", level="WARNING") as logs,
        ):
            result = await music_discord_display.send_music_request_reply(
                message,
                "곡을 찾고 있어요...",
            )

        self.assertIsNone(result)
        self.assertIn("HTTP 500", "\n".join(logs.output))
        self.assertNotIn("<html>", "\n".join(logs.output))

    async def test_request_delete_ignores_transient_discord_500(self) -> None:
        message = MagicMock()
        message.delete = AsyncMock(side_effect=self.make_server_error())

        with (
            patch.object(
                music_discord_display,
                "MUSIC_CHANNEL_DELETE_REQUESTS",
                True,
            ),
            self.assertLogs("music-bot", level="WARNING") as logs,
        ):
            await music_discord_display.delete_music_request_message(message)

        self.assertIn("HTTP 500", "\n".join(logs.output))
