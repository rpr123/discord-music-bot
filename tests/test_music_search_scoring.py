import ast
import unittest
from pathlib import Path

import bot
import music_search_scoring


MOVED_FUNCTION_NAMES = (
    "clean_track_title",
    "clean_track_title_preserving_case",
    "get_search_result_duration",
    "get_youtube_music_artist_hint",
    "get_youtube_music_artist_names",
    "get_youtube_search_tokens",
    "infer_youtube_search_song_title",
    "is_likely_official_youtube_upload",
    "normalize_artist_name",
    "normalize_identity_component",
    "score_youtube_search_result",
    "should_use_youtube_music_search",
    "strip_edge_title_tags",
    "youtube_music_entries_are_ambiguous",
    "youtube_music_result_to_entry",
)

MOVED_CONSTANT_NAMES = (
    "ALTERNATE_VERSION_SEARCH_RE",
    "ARTIST_CHANNEL_SUFFIX_RE",
    "BRACKETED_TITLE_PART_RE",
    "FULL_VERSION_SEARCH_RE",
    "GAME_VIDEO_SEARCH_RE",
    "LEADING_BRACKETED_TITLE_PART_RE",
    "LONG_FORM_SEARCH_RE",
    "NON_SONG_LABEL_RE",
    "NON_SONG_SUFFIX_RE",
    "OFFICIAL_AUDIO_SEARCH_RE",
    "OFFICIAL_CHANNEL_RE",
    "OFFICIAL_MEDIA_SEARCH_RE",
    "OFFICIAL_VIDEO_SEARCH_RE",
    "SHORT_VERSION_SEARCH_RE",
    "TRAILING_BRACKETED_TITLE_PART_RE",
    "VERSION_MARKER_RE",
    "YOUTUBE_SEARCH_NOISE_TOKENS",
)


class MusicSearchScoringTests(unittest.TestCase):
    def test_bot_reexports_moved_search_names(self) -> None:
        for name in MOVED_FUNCTION_NAMES + MOVED_CONSTANT_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_search_scoring, name),
                )

    def test_module_depends_only_on_the_standard_library(self) -> None:
        source = Path(music_search_scoring.__file__).read_text(encoding="utf-8")
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
            {"__future__", "re", "unicodedata"},
        )

    def test_version_scoring_preserves_query_intent(self) -> None:
        full_song = {
            "id": "x5dIe0FKY_U",
            "title": "泥濘鳴鳴 / コメティック / 歌詞 Color coded lyrics",
            "duration": 233,
            "channel": "iluvsmurfs",
        }
        game_mv = {
            "id": "I-CZXVMPiPg",
            "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV（4K対応）",
            "duration": 148,
            "channel": "アイドルマスターチャンネル",
        }

        plain_full_score = music_search_scoring.score_youtube_search_result(
            full_song,
            "でいねいめいめい",
            1,
        )
        plain_game_score = music_search_scoring.score_youtube_search_result(
            game_mv,
            "でいねいめいめい",
            0,
        )
        explicit_full_score = music_search_scoring.score_youtube_search_result(
            full_song,
            "泥濘鳴鳴 game mv",
            1,
        )
        explicit_game_score = music_search_scoring.score_youtube_search_result(
            game_mv,
            "泥濘鳴鳴 game mv",
            0,
        )

        self.assertGreater(plain_full_score, plain_game_score)
        self.assertGreater(explicit_game_score, explicit_full_score)
