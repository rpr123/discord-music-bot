import ast
import unittest
from pathlib import Path

import bot
import music_request_parsing


MOVED_NAMES = (
    "YOUTUBE_HOSTS",
    "YOUTUBE_PLAYLIST_SEARCH_FILTER",
    "build_youtube_playlist_search_url",
    "get_playlist_result_url",
    "is_bulk_youtube_url",
    "is_legacy_auto_request",
    "is_playlist_search_url",
    "is_youtube_search_query",
    "parse_music_request",
)


class MusicRequestParsingTests(unittest.TestCase):
    def test_bot_reexports_moved_request_parsing_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_request_parsing, name),
                )

    def test_module_depends_only_on_the_standard_library(self) -> None:
        source = Path(music_request_parsing.__file__).read_text(encoding="utf-8")
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
            {"__future__", "re", "urllib.parse"},
        )

    def test_legacy_auto_request_detector_accepts_retired_message_syntax(self) -> None:
        requests = (
            "auto: back number",
            "auto back number",
            "auto5: back number",
            "auto 5: back number",
            "AUTO12 : lofi chill",
            "auto:5 back number",
            "  auto   city pop  ",
        )

        for request in requests:
            with self.subTest(request=request):
                self.assertTrue(
                    music_request_parsing.is_legacy_auto_request(request)
                )

    def test_legacy_auto_request_detector_ignores_regular_music_requests(self) -> None:
        requests = (
            "auto",
            "automatic playlist",
            "autoplay: mix",
            "autograph song",
            "song auto: remix",
            "/auto n:5 곡명:back number",
            "https://www.youtube.com/watch?v=abcdefghijk",
        )

        for request in requests:
            with self.subTest(request=request):
                self.assertFalse(
                    music_request_parsing.is_legacy_auto_request(request)
                )

    def test_auto_count_clamp_keeps_counts_within_the_command_range(self) -> None:
        self.assertEqual(music_request_parsing.clamp_auto_count(0, 25), 1)
        self.assertEqual(music_request_parsing.clamp_auto_count(999, 25), 25)
        self.assertEqual(music_request_parsing.clamp_auto_count(12, 25), 12)

    def test_album_and_playlist_prefixes_preserve_the_request(self) -> None:
        cases = {
            "album: NewJeans Get Up": ("NewJeans Get Up", "album", True),
            "ALBUM NewJeans Get Up": ("NewJeans Get Up", "album", True),
            "playlist: lofi beats": ("lofi beats", "playlist", True),
            "list city pop": ("city pop", "playlist", True),
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(
                    music_request_parsing.parse_music_request(request),
                    expected,
                )

    def test_direct_playlist_url_is_bulk_but_video_url_is_not(self) -> None:
        playlist = "https://www.youtube.com/playlist?list=PL123"
        video = "https://www.youtube.com/watch?v=abcdefghijk&list=PL123"

        self.assertEqual(
            music_request_parsing.parse_music_request(playlist),
            (playlist, None, True),
        )
        self.assertEqual(
            music_request_parsing.parse_music_request(video),
            (video, None, False),
        )
