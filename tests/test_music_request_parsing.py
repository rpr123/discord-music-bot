import ast
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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
            {"__future__", "collections.abc", "re", "urllib.parse"},
        )

    def test_auto_request_parser_accepts_supported_count_syntax(self) -> None:
        cases = {
            "auto5: back number": ("back number", 5),
            "auto 5: back number": ("back number", 5),
            "AUTO12 : lofi chill": ("lofi chill", 12),
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                self.assertEqual(
                    music_request_parsing.parse_auto_request(
                        request,
                        default_count=3,
                        clamp_count=lambda count: count,
                    ),
                    expected,
                )

    def test_auto_request_parser_uses_default_count(self) -> None:
        self.assertEqual(
            music_request_parsing.parse_auto_request(
                "auto: back number",
                default_count=7,
                clamp_count=lambda count: count,
            ),
            ("back number", 7),
        )

    def test_auto_request_parser_uses_supplied_clamp_callback(self) -> None:
        clamp_count = Mock(return_value=9)

        self.assertEqual(
            music_request_parsing.parse_auto_request(
                "auto999: lofi chill",
                default_count=3,
                clamp_count=clamp_count,
            ),
            ("lofi chill", 9),
        )
        clamp_count.assert_called_once_with(999)
        self.assertEqual(music_request_parsing.clamp_auto_count(0, 25), 1)
        self.assertEqual(music_request_parsing.clamp_auto_count(999, 25), 25)

    def test_auto_request_parser_preserves_existing_validation_errors(self) -> None:
        cases = {
            "auto:": "auto: 뒤에 곡명이나 아티스트를 입력해 주세요.",
            "auto5:": (
                "auto5: 또는 auto 5: 뒤에 곡명이나 아티스트를 입력해 주세요."
            ),
            "auto:5 back number": (
                "곡 개수는 `auto5: 곡명` 또는 `auto 5: 곡명`처럼 "
                "콜론 앞에 입력해 주세요."
            ),
        }

        for request, expected in cases.items():
            with self.subTest(request=request):
                with self.assertRaises(ValueError) as raised:
                    music_request_parsing.parse_auto_request(
                        request,
                        default_count=3,
                        clamp_count=lambda count: count,
                    )
                self.assertEqual(str(raised.exception), expected)

    def test_auto_request_parser_ignores_unrelated_requests(self) -> None:
        self.assertIsNone(
            music_request_parsing.parse_auto_request(
                "automatic playlist",
                default_count=3,
                clamp_count=lambda count: count,
            )
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


class BotAutoRequestParsingCompatibilityTests(unittest.TestCase):
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
