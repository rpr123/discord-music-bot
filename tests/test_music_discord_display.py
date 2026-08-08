import ast
import unittest
from pathlib import Path

import bot
import music_discord_display
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "CONTROL_PANEL_TITLES",
    "DISCORD_EMBED_FIELD_LIMIT",
    "IDLE_PANEL_TITLE",
    "LYRICS_INLINE_LIMIT",
    "PLAYING_PANEL_TITLE",
    "describe_queue_selection",
    "format_duration",
    "make_idle_player_embed",
    "make_lyrics_embed",
    "make_lyrics_file",
    "make_lyrics_variant_embed",
    "make_player_embed",
    "make_queue_embed",
    "make_queue_line",
    "make_track_embed",
    "make_track_link",
    "requester_label",
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
            {"__future__", "discord", "io", "music_models"},
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

        self.assertEqual(player.title, music_discord_display.PLAYING_PANEL_TITLE)
        self.assertIn("<@123>", player.description)
        self.assertEqual(player_fields["대기열"], "1곡")
        self.assertEqual(player_fields["반복"], "켜짐")
        self.assertEqual(player_fields["자동재생"], "켜짐")
        self.assertIn("queued", player_fields["다음 곡"])
        self.assertIn("current", queue_fields["지금 재생 중"])
        self.assertIn("queued", queue_fields["다음 곡"])

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
