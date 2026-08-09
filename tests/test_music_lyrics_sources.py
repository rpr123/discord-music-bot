import ast
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_lyrics_sources


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


MOVED_NAMES = (
    "LRC_METADATA_RE",
    "LRC_TIMESTAMP_RE",
    "LYRICS_DURATION_MATCH_TOLERANCE_SECONDS",
    "LYRICS_NATIVE_SCRIPT_MIN_RATIO",
    "LYRICS_NATIVE_SCRIPT_SCORE_WINDOW",
    "QUOTED_TRACK_TITLE_RE",
    "LyricsLookupError",
    "extract_original_lyrics",
    "get_lyrics_search_terms",
    "get_lyrics_title_aliases",
    "lyrics_native_script_ratio",
    "lyrics_record_score",
    "normalize_lyrics_match_text",
    "lookup_track_lyrics",
    "request_lyrics_records",
    "request_youtube_subtitle",
    "select_lyrics_record",
    "VTT_TAG_RE",
    "VTT_TIMESTAMP_LINE_RE",
    "YouTubeSubtitleError",
    "extract_json3_lyrics",
    "extract_vtt_lyrics",
    "get_manual_subtitle_candidates",
    "get_subtitle_candidates",
    "normalize_subtitle_text",
    "select_korean_manual_subtitle",
    "select_manual_subtitle",
)


class MusicLyricsSourcesTests(unittest.TestCase):
    def test_bot_reexports_moved_lyrics_source_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_lyrics_sources, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_lyrics_sources.__file__).read_text(encoding="utf-8")
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
                "html",
                "json",
                "music_config",
                "music_models",
                "music_search_scoring",
                "re",
                "unicodedata",
                "urllib.error",
                "urllib.parse",
                "urllib.request",
            },
        )

    def test_candidates_ignore_malformed_and_unsupported_formats(self) -> None:
        candidates = music_lyrics_sources.get_subtitle_candidates(
            {
                "ja": [
                    {"ext": "srt", "url": "https://example.test/unsupported"},
                    None,
                    {"ext": "JSON3", "url": "https://example.test/json3"},
                    {"ext": "vtt", "url": ""},
                ],
                "en": "not-a-list",
            }
        )

        self.assertEqual(
            candidates,
            [("ja", "json3", "https://example.test/json3", 30)],
        )

    def test_title_aliases_include_full_and_split_script_variants(self) -> None:
        self.assertEqual(
            music_lyrics_sources.get_lyrics_title_aliases(
                "らしさ - Rashisa"
            ),
            {"らしさ rashisa", "らしさ", "rashisa"},
        )


class LyricsLookupTests(unittest.TestCase):
    def test_japanese_quoted_title_ignores_official_label_and_english_alias(self) -> None:
        track = bot.Track(
            title=(
                "初星学園 「白線」Official Music Video "
                "(HATSUBOSHI GAKUEN - Hakusen)"
            ),
            webpage_url="https://www.youtube.com/watch?v=m4VahiqP9vA",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=m4VahiqP9vA",
            uploader="HATSUBOSHI GAKUEN",
            duration=218,
        )

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_terms(track),
            ("白線", "初星学園"),
        )

    def test_search_terms_use_song_title_and_artist_in_original_script(self) -> None:
        track = bot.Track(
            title="back number - ブルーアンバー 【Official Music Video】",
            webpage_url="https://www.youtube.com/watch?v=lyrics00001",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=lyrics00001",
            uploader="back number - Topic",
        )

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_terms(track),
            ("ブルーアンバー", "back number"),
        )

    def test_plain_lyrics_are_returned_without_translation_or_romanization(self) -> None:
        original = "君の声が聞こえる\n夜を越えて"
        record = {
            "instrumental": False,
            "plainLyrics": original,
            "syncedLyrics": "[00:01.00]Kimi no koe ga kikoeru",
        }

        self.assertEqual(
            music_lyrics_sources.extract_original_lyrics(record),
            original,
        )

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
            music_lyrics_sources.extract_original_lyrics(record),
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

        selected = music_lyrics_sources.select_lyrics_record(
            [wrong_artist, matching_record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIs(selected, matching_record)

    def test_exact_title_and_duration_allow_a_different_artist_label(self) -> None:
        record = {
            "trackName": "Blue Amber",
            "artistName": "バックナンバー",
            "duration": 224,
            "instrumental": False,
            "plainLyrics": "correct",
        }

        selected = music_lyrics_sources.select_lyrics_record(
            [record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIs(selected, record)

    def test_artist_mismatch_is_rejected_when_duration_is_not_close(self) -> None:
        record = {
            "trackName": "Blue Amber",
            "artistName": "Different Artist",
            "duration": 240,
            "instrumental": False,
            "plainLyrics": "wrong",
        }

        selected = music_lyrics_sources.select_lyrics_record(
            [record],
            "Blue Amber",
            "back number",
            220,
        )

        self.assertIsNone(selected)

    def test_lookup_retries_without_artist_when_strict_search_misses(self) -> None:
        track = bot.Track(
            title="Artist - Exact Song",
            webpage_url="https://www.youtube.com/watch?v=retrylyrics",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=retrylyrics",
            duration=180,
        )
        record = {
            "trackName": "Exact Song",
            "artistName": "Artist feat. Guest",
            "duration": 181,
            "instrumental": False,
            "plainLyrics": "found on retry",
        }

        with patch.object(
            music_lyrics_sources,
            "request_lyrics_records",
            side_effect=[[], [record]],
        ) as request:
            lyrics = music_lyrics_sources.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "found on retry")
        self.assertEqual(
            [call.args for call in request.call_args_list],
            [("exact song", "artist"), ("exact song", None)],
        )

    def test_romanized_official_title_matches_native_lrclib_record(self) -> None:
        track = bot.Track(
            title="OFFICIAL HIGE DANDISM - Rashisa [Official Video]",
            webpage_url="https://www.youtube.com/watch?v=keOnleW2eak",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=keOnleW2eak",
            uploader="OFFICIAL HIGE DANDISM",
            duration=313,
        )
        record = {
            "trackName": "らしさ - Rashisa",
            "artistName": "Official髭男dism",
            "duration": 313,
            "instrumental": False,
            "plainLyrics": "Japanese lyrics fixture",
        }

        with patch.object(
            music_lyrics_sources,
            "request_lyrics_records",
            return_value=[record],
        ) as request:
            lyrics = music_lyrics_sources.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "Japanese lyrics fixture")
        request.assert_called_once_with("rashisa", "official hige dandism")

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

        selected = music_lyrics_sources.select_lyrics_record(
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

        selected = music_lyrics_sources.select_lyrics_record(
            [exact_english_record, unrelated_native_record],
            "Original English Song",
            "Artist",
            200,
        )

        self.assertIs(selected, exact_english_record)

    def test_instrumental_record_is_treated_as_unavailable(self) -> None:
        self.assertIsNone(
            music_lyrics_sources.extract_original_lyrics(
                {
                    "instrumental": True,
                    "plainLyrics": "should not be shown",
                }
            )
        )


class LyricsSourceParsingTests(unittest.TestCase):
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
            music_lyrics_sources.extract_json3_lyrics(payload),
            "君の声が聞こえる\n夜を越えて",
        )

    def test_invalid_json3_document_is_rejected(self) -> None:
        with self.assertRaises(music_lyrics_sources.YouTubeSubtitleError):
            music_lyrics_sources.extract_json3_lyrics("[]")

    def test_vtt_manual_subtitles_drop_timestamps_and_markup(self) -> None:
        payload = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<c>First &amp; second</c>\n\n"
            "00:00:03.000 --> 00:00:05.000\n"
            "Next line\n"
        )

        self.assertEqual(
            music_lyrics_sources.extract_vtt_lyrics(payload),
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
            music_lyrics_sources.select_manual_subtitle(track),
            ("ja", "vtt", "https://example.com/ja"),
        )

    def test_korean_manual_subtitle_is_selected_independently(self) -> None:
        track = make_track("captioned")
        track.subtitle_language = "ja"
        track.manual_subtitles = {
            "ja": [{"ext": "json3", "url": "https://example.com/ja"}],
            "en": [{"ext": "json3", "url": "https://example.com/en"}],
            "ko-KR": [{"ext": "vtt", "url": "https://example.com/ko"}],
        }

        self.assertEqual(
            music_lyrics_sources.select_korean_manual_subtitle(track),
            ("ko-KR", "vtt", "https://example.com/ko"),
        )

    def test_korean_manual_subtitle_does_not_use_other_languages(self) -> None:
        track = make_track("captioned")
        track.manual_subtitles = {
            "ja": [{"ext": "json3", "url": "https://example.com/ja"}],
            "en": [{"ext": "vtt", "url": "https://example.com/en"}],
        }

        self.assertIsNone(
            music_lyrics_sources.select_korean_manual_subtitle(track)
        )
