import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_config


MOVED_NAMES = (
    "AUTOPLAY_BUTTON_CUSTOM_ID",
    "AUTOPLAY_REFILL_CANDIDATES",
    "AUTOPLAY_START_DELAY_SECONDS",
    "CONTROL_PANEL_HISTORY_LIMIT",
    "DEV_GUILD_ID",
    "DISCORD_TOKEN",
    "EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS",
    "EPHEMERAL_RESPONSE_DELETE_SECONDS",
    "FFMPEG_EXECUTABLE",
    "FFMPEG_OPTIONS",
    "LOG_LEVEL",
    "LYRICS_API_URL",
    "LYRICS_READING_ENABLED",
    "LYRICS_REQUEST_TIMEOUT_SECONDS",
    "LYRICS_START_DELAY_SECONDS",
    "MAX_AUTO_TRACKS",
    "MAX_BULK_TRACKS",
    "MUSIC_CHANNEL_DELETE_REQUESTS",
    "MUSIC_CHANNEL_ID",
    "MUSIC_CHANNEL_NAME",
    "MUSIC_CHANNEL_SILENT",
    "MUSIC_CHANNELS_FILE",
    "MUSIC_FEEDBACK_DELETE_SECONDS",
    "NAMUWIKI_API_BASE_URL",
    "NAMUWIKI_API_TOKEN",
    "NAMUWIKI_DOCUMENT_OVERRIDES",
    "NAMUWIKI_LYRICS_ENABLED",
    "NAMUWIKI_PAGE_BASE_URL",
    "NAMUWIKI_PREVIEW_FALLBACK_ENABLED",
    "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
    "NAMUWIKI_REQUEST_TIMEOUT_SECONDS",
    "PROJECT_DIR",
    "QUEUE_DELETE_RESPONSE_DELETE_SECONDS",
    "QUEUE_SELECT_LIMIT",
    "STREAM_URL_MAX_AGE_SECONDS",
    "VOICE_DISCONNECT_TIMEOUT_SECONDS",
    "VOICE_RECONNECT_GRACE_SECONDS",
    "YOUTUBE_CIRCUIT_BREAKER_SECONDS",
    "YOUTUBE_COOKIES_FILE",
    "YOUTUBE_LYRICS_FALLBACK",
    "YOUTUBE_MUSIC_AUTH_FILE",
    "YOUTUBE_MUSIC_LANGUAGE",
    "YOUTUBE_MUSIC_LOCATION",
    "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS",
    "YOUTUBE_MUSIC_OAUTH_CLIENT_ID",
    "YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET",
    "YOUTUBE_MUSIC_SEARCH_ENABLED",
    "YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS",
    "YOUTUBE_SEARCH_CANDIDATES",
    "YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS",
    "YTDL_BASE_OPTIONS",
    "YTDL_CACHE_MAX_ENTRIES",
    "YTDL_CACHE_TTL_SECONDS",
    "YTDL_EXTRACT_TIMEOUT_SECONDS",
    "YTDL_MAX_CONCURRENT_EXTRACTIONS",
    "YTDL_MIN_INTERVAL_SECONDS",
    "YTDL_OPTIONS",
    "YTDL_PLAYLIST_OPTIONS",
    "YTDL_SEARCH_OPTIONS",
    "YTDL_WORKER_PATH",
    "clear_control_message_id",
    "configured_autoplay_enabled",
    "configured_control_messages",
    "configured_music_channels",
    "get_autoplay_enabled",
    "get_control_message_id",
    "get_music_channel_id",
    "load_env_file",
    "load_music_channel_config",
    "logger",
    "parse_nonnegative_float_env",
    "parse_positive_int_env",
    "parse_string_map_env",
    "resolve_project_path",
    "save_music_channel_config",
    "set_autoplay_enabled",
    "set_control_message_id",
    "set_music_channel",
)


class MusicConfigTests(unittest.TestCase):
    def test_bot_reexports_moved_config_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertTrue(
                    getattr(bot, name) is getattr(music_config, name),
                    f"{name} is not re-exported from music_config",
                )

    def test_retired_default_auto_track_setting_is_not_exported(self) -> None:
        self.assertFalse(hasattr(music_config, "DEFAULT_AUTO_TRACKS"))
        self.assertFalse(hasattr(bot, "DEFAULT_AUTO_TRACKS"))

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_config.__file__).read_text(encoding="utf-8")
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
            {"__future__", "json", "logging", "os", "pathlib", "shutil"},
        )

    def test_bot_and_config_share_logger_and_parser_warnings(self) -> None:
        positive_name = "MUSIC_CONFIG_TEST_POSITIVE_WARNING"
        float_name = "MUSIC_CONFIG_TEST_FLOAT_WARNING"
        map_name = "MUSIC_CONFIG_TEST_MAP_WARNING"

        self.assertIs(bot.logger, music_config.logger)
        with patch.dict(
            music_config.os.environ,
            {
                positive_name: "invalid",
                float_name: "-0.5",
                map_name: "not-json",
            },
            clear=False,
        ):
            with patch.object(bot.logger, "warning") as warning:
                self.assertEqual(bot.parse_positive_int_env(positive_name, 7), 7)
                warning.assert_called_once_with(
                    "%s must be a positive integer. Falling back to %s.",
                    positive_name,
                    7,
                )

                warning.reset_mock()
                self.assertEqual(
                    bot.parse_nonnegative_float_env(float_name, 1.25),
                    1.25,
                )
                warning.assert_called_once_with(
                    "%s must be zero or greater. Falling back to %s.",
                    float_name,
                    1.25,
                )

                warning.reset_mock()
                self.assertEqual(bot.parse_string_map_env(map_name), {})
                warning.assert_called_once_with(
                    "%s must be a JSON object. Ignoring its value.",
                    map_name,
                )

    def test_environment_parsers_preserve_valid_values(self) -> None:
        positive_name = "MUSIC_CONFIG_TEST_POSITIVE_VALUE"
        minimum_name = "MUSIC_CONFIG_TEST_POSITIVE_MINIMUM"
        float_name = "MUSIC_CONFIG_TEST_FLOAT_VALUE"
        map_name = "MUSIC_CONFIG_TEST_MAP_VALUE"
        with patch.dict(
            music_config.os.environ,
            {
                positive_name: "17",
                minimum_name: "0",
                float_name: "0.25",
                map_name: '{" artist ": " document ", "": "ignored", "count": 3}',
            },
            clear=False,
        ):
            self.assertEqual(bot.parse_positive_int_env(positive_name, 5), 17)
            self.assertEqual(bot.parse_positive_int_env(minimum_name, 5), 1)
            self.assertEqual(
                bot.parse_nonnegative_float_env(float_name, 5.0),
                0.25,
            )
            self.assertEqual(
                bot.parse_string_map_env(map_name),
                {"artist": "document", "count": "3"},
            )

    def test_load_env_file_preserves_existing_and_parses_supported_lines(self) -> None:
        existing_name = "MUSIC_CONFIG_TEST_EXISTING"
        double_name = "MUSIC_CONFIG_TEST_DOUBLE_QUOTED"
        single_name = "MUSIC_CONFIG_TEST_SINGLE_QUOTED"
        equals_name = "MUSIC_CONFIG_TEST_WITH_EQUALS"
        ignored_name = "MUSIC_CONFIG_TEST_IGNORED_LINE"
        managed_names = {
            existing_name,
            double_name,
            single_name,
            equals_name,
            ignored_name,
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "\n".join(
                    (
                        "# ignored comment",
                        "",
                        ignored_name,
                        f'{existing_name}="replacement"',
                        f'{double_name}="two words"',
                        f"{single_name}='한글 값'",
                        f"{equals_name}=left=right",
                    )
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.dict(
                music_config.os.environ,
                {existing_name: "original"},
                clear=False,
            ):
                for name in managed_names - {existing_name}:
                    music_config.os.environ.pop(name, None)

                bot.load_env_file(env_path)

                self.assertEqual(music_config.os.environ[existing_name], "original")
                self.assertEqual(music_config.os.environ[double_name], "two words")
                self.assertEqual(music_config.os.environ[single_name], "한글 값")
                self.assertEqual(music_config.os.environ[equals_name], "left=right")
                self.assertNotIn(ignored_name, music_config.os.environ)

    def test_ytdl_and_ffmpeg_option_relationships(self) -> None:
        option_sets = (
            ("single", music_config.YTDL_OPTIONS),
            ("search", music_config.YTDL_SEARCH_OPTIONS),
            ("playlist", music_config.YTDL_PLAYLIST_OPTIONS),
        )
        for name, options in option_sets:
            with self.subTest(name=name):
                for key, value in music_config.YTDL_BASE_OPTIONS.items():
                    self.assertEqual(options[key], value)

        self.assertIsNot(music_config.YTDL_OPTIONS, music_config.YTDL_BASE_OPTIONS)
        self.assertIsNot(
            music_config.YTDL_SEARCH_OPTIONS,
            music_config.YTDL_BASE_OPTIONS,
        )
        self.assertIsNot(
            music_config.YTDL_PLAYLIST_OPTIONS,
            music_config.YTDL_BASE_OPTIONS,
        )
        self.assertEqual(
            music_config.YTDL_BASE_OPTIONS["format"],
            "bestaudio[acodec=opus]/bestaudio/best",
        )
        self.assertTrue(music_config.YTDL_OPTIONS["noplaylist"])
        self.assertFalse(music_config.YTDL_OPTIONS["extract_flat"])
        self.assertTrue(music_config.YTDL_SEARCH_OPTIONS["noplaylist"])
        self.assertEqual(
            music_config.YTDL_SEARCH_OPTIONS["extract_flat"],
            "in_playlist",
        )
        self.assertFalse(music_config.YTDL_PLAYLIST_OPTIONS["noplaylist"])
        self.assertEqual(
            music_config.YTDL_PLAYLIST_OPTIONS["extract_flat"],
            "in_playlist",
        )
        self.assertEqual(
            music_config.YTDL_PLAYLIST_OPTIONS["playlistend"],
            music_config.MAX_BULK_TRACKS,
        )
        self.assertEqual(
            music_config.FFMPEG_OPTIONS,
            {
                "before_options": (
                    "-reconnect 1 -reconnect_streamed 1 "
                    "-reconnect_delay_max 5"
                ),
                "options": "-vn",
            },
        )


class MusicChannelConfigTests(unittest.TestCase):
    def test_legacy_channel_config_is_migrated_with_control_message_id(self) -> None:
        original_channels = dict(music_config.configured_music_channels)
        original_messages = dict(music_config.configured_control_messages)
        original_autoplay = dict(music_config.configured_autoplay_enabled)

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "music_channels.json"
                config_path.write_text('{"123": 456}\n', encoding="utf-8")

                with (
                    patch.object(music_config, "MUSIC_CHANNELS_FILE", config_path),
                    patch.object(music_config, "MUSIC_CHANNEL_ID", None),
                ):
                    music_config.load_music_channel_config()
                    self.assertEqual(music_config.get_music_channel_id(123), 456)
                    self.assertIsNone(music_config.get_control_message_id(123))
                    self.assertFalse(music_config.get_autoplay_enabled(123))

                    music_config.set_control_message_id(123, 789)
                    saved = json.loads(config_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        saved["123"],
                        {"channel_id": 456, "control_message_id": 789},
                    )

                    music_config.set_autoplay_enabled(123, True)
                    saved = json.loads(config_path.read_text(encoding="utf-8"))
                    self.assertTrue(saved["123"]["autoplay_enabled"])

                    music_config.configured_music_channels.clear()
                    music_config.configured_control_messages.clear()
                    music_config.configured_autoplay_enabled.clear()
                    music_config.load_music_channel_config()
                    self.assertEqual(music_config.get_music_channel_id(123), 456)
                    self.assertEqual(music_config.get_control_message_id(123), 789)
                    self.assertTrue(music_config.get_autoplay_enabled(123))
        finally:
            music_config.configured_music_channels.clear()
            music_config.configured_music_channels.update(original_channels)
            music_config.configured_control_messages.clear()
            music_config.configured_control_messages.update(original_messages)
            music_config.configured_autoplay_enabled.clear()
            music_config.configured_autoplay_enabled.update(original_autoplay)
