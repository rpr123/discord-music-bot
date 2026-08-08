import ast
import unittest
from pathlib import Path

import bot
import music_player_embeds
from music_models import GuildMusicState, Track


MOVED_NAMES = (
    "CONTROL_PANEL_TITLES",
    "IDLE_PANEL_TITLE",
    "PLAYING_PANEL_TITLE",
    "describe_queue_selection",
    "make_idle_player_embed",
    "make_player_embed",
    "make_queue_embed",
    "make_track_embed",
)


def make_track(title: str, *, requester_id: int | None = None) -> Track:
    return Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        requester_id=requester_id,
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        duration=65,
    )


class MusicPlayerEmbedsTests(unittest.TestCase):
    def test_bot_reexports_moved_player_embed_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_player_embeds, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_player_embeds.__file__).read_text(encoding="utf-8")
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
            {"__future__", "discord", "music_models", "music_text"},
        )

    def test_player_and_queue_embeds_preserve_visible_state(self) -> None:
        current = make_track("current", requester_id=123)
        queued = make_track("queued")
        state = GuildMusicState(
            current=current,
            repeat_one=True,
            autoplay_enabled=True,
        )
        state.queue.append(queued)

        player = music_player_embeds.make_player_embed(current, state)
        player_fields = {field.name: field.value for field in player.fields}
        queue = music_player_embeds.make_queue_embed(state)
        queue_fields = {field.name: field.value for field in queue.fields}

        self.assertEqual(player.title, music_player_embeds.PLAYING_PANEL_TITLE)
        self.assertIn("<@123>", player.description)
        self.assertEqual(player_fields["대기열"], "1곡")
        self.assertEqual(player_fields["반복"], "켜짐")
        self.assertEqual(player_fields["자동재생"], "켜짐")
        self.assertIn("queued", player_fields["다음 곡"])
        self.assertIn("current", queue_fields["지금 재생 중"])
        self.assertIn("queued", queue_fields["다음 곡"])

    def test_idle_and_queue_selection_contract(self) -> None:
        first = make_track("first")
        state = GuildMusicState()
        state.queue.append(first)

        idle = music_player_embeds.make_idle_player_embed()

        self.assertEqual(idle.title, music_player_embeds.IDLE_PANEL_TITLE)
        self.assertEqual(
            music_player_embeds.CONTROL_PANEL_TITLES,
            frozenset(
                {
                    music_player_embeds.PLAYING_PANEL_TITLE,
                    music_player_embeds.IDLE_PANEL_TITLE,
                }
            ),
        )
        self.assertEqual(
            music_player_embeds.describe_queue_selection(state, first.track_id),
            "1. first",
        )
        self.assertEqual(
            music_player_embeds.describe_queue_selection(state, None),
            "선택 안 함",
        )
