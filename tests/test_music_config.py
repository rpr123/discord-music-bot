import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_config


class MusicConfigTests(unittest.TestCase):
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

        self.assertIs(bot.logger, music_config.logger)
        with patch.dict(
            music_config.os.environ,
            {
                positive_name: "invalid",
                float_name: "-0.5",
            },
            clear=False,
        ):
            with patch.object(bot.logger, "warning") as warning:
                self.assertEqual(music_config.parse_positive_int_env(positive_name, 7), 7)
                warning.assert_called_once_with(
                    "%s must be a positive integer. Falling back to %s.",
                    positive_name,
                    7,
                )

                warning.reset_mock()
                self.assertEqual(
                    music_config.parse_nonnegative_float_env(float_name, 1.25),
                    1.25,
                )
                warning.assert_called_once_with(
                    "%s must be zero or greater. Falling back to %s.",
                    float_name,
                    1.25,
                )


    def test_environment_parsers_preserve_valid_values(self) -> None:
        positive_name = "MUSIC_CONFIG_TEST_POSITIVE_VALUE"
        minimum_name = "MUSIC_CONFIG_TEST_POSITIVE_MINIMUM"
        float_name = "MUSIC_CONFIG_TEST_FLOAT_VALUE"
        with patch.dict(
            music_config.os.environ,
            {
                positive_name: "17",
                minimum_name: "0",
                float_name: "0.25",
            },
            clear=False,
        ):
            self.assertEqual(music_config.parse_positive_int_env(positive_name, 5), 17)
            self.assertEqual(music_config.parse_positive_int_env(minimum_name, 5), 1)
            self.assertEqual(
                music_config.parse_nonnegative_float_env(float_name, 5.0),
                0.25,
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

                music_config.load_env_file(env_path)

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
