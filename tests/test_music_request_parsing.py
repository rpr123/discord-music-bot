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
