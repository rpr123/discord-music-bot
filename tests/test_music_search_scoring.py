import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_search_scoring


MOVED_FUNCTION_NAMES = (
    "build_youtube_search_query",
    "clean_track_title",
    "clean_track_title_preserving_case",
    "get_search_result_duration",
    "get_version_style_intents",
    "get_youtube_music_artist_hint",
    "get_youtube_music_artist_names",
    "get_youtube_search_tokens",
    "infer_youtube_search_song_title",
    "is_likely_official_youtube_upload",
    "normalize_artist_name",
    "normalize_identity_component",
    "rank_autoplay_candidates",
    "resolve_query",
    "score_autoplay_candidate",
    "score_youtube_search_result",
    "select_youtube_music_song_result",
    "select_youtube_search_result",
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

    def test_module_has_expected_dependencies(self) -> None:
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
            {
                "__future__",
                "music_config",
                "music_discord_display",
                "music_request_parsing",
                "re",
                "unicodedata",
                "urllib.parse",
            },
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

    def test_autoplay_duration_score_boundaries(self) -> None:
        expected_scores = {
            None: 25,
            44: -110,
            45: -60,
            89: -60,
            90: -20,
            149: -20,
            150: 10,
            179: 10,
            180: 60,
            420: 60,
            421: 40,
            600: 40,
            601: 10,
            900: 10,
            901: -60,
        }

        for duration, expected in expected_scores.items():
            with self.subTest(duration=duration):
                entry = {"title": "Candidate"}
                if duration is not None:
                    entry["duration"] = duration
                self.assertEqual(
                    music_search_scoring.score_autoplay_candidate(entry, 0),
                    expected,
                )

    def test_autoplay_score_adds_quality_markers_without_query_relevance(
        self,
    ) -> None:
        entries_and_scores = (
            ({"title": "Song Full Version", "duration": 240}, 95),
            ({"title": "Song #Shorts", "duration": 240}, -60),
            ({"title": "Song Game MV", "duration": 200}, -2),
            ({"title": "Song Game MV", "duration": 210}, 48),
            ({"title": "Song Cover", "duration": 240}, -20),
            ({"title": "Song Live", "duration": 240}, -20),
            ({"title": "Song Remix", "duration": 240}, 15),
            ({"title": "Song Extended Loop", "duration": 240}, -20),
            ({"title": "Song Official Audio", "duration": 700}, 24),
            ({"title": "Song", "duration": 240, "is_live": True}, -140),
        )

        for entry, expected in entries_and_scores:
            with self.subTest(entry=entry):
                self.assertEqual(
                    music_search_scoring.score_autoplay_candidate(entry, 0),
                    expected,
                )

        official_full = {
            "title": "Artist - Song Full Version Official MV",
            "duration": 240,
            "channel": "Artist Official",
        }
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(official_full, 0),
            161,
        )

        for live_entry in (
            {"title": "Song", "duration": 240, "is_upcoming": True},
            {"title": "Song", "duration": 240, "live_status": "is_live"},
            {"title": "Song", "duration": 240, "live_status": "post_live"},
        ):
            with self.subTest(live_entry=live_entry):
                self.assertEqual(
                    music_search_scoring.score_autoplay_candidate(live_entry, 0),
                    -140,
                )

        popularity = {
            "title": "Candidate",
            "duration": 240,
            "view_count": 100_000_000,
            "like_count": 1_000_000,
        }
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(popularity, 0),
            music_search_scoring.score_autoplay_candidate(
                {"title": "Candidate", "duration": 240},
                0,
            ),
        )

    def test_cover_and_recorded_live_intents_only_neutralize_same_style(
        self,
    ) -> None:
        cover = {"title": "Song Cover", "duration": 240}
        recorded_live = {"title": "Song Live", "duration": 240}
        cover_live = {"title": "Song Cover Live", "duration": 240}

        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(cover, 0),
            -20,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                cover,
                0,
                style_intents=frozenset({"cover"}),
            ),
            60,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                cover,
                0,
                style_intents=frozenset({"live"}),
            ),
            -20,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                recorded_live,
                0,
                style_intents=frozenset({"live"}),
            ),
            60,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                recorded_live,
                0,
                style_intents=frozenset({"cover"}),
            ),
            -20,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(cover_live, 0),
            -100,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                cover_live,
                0,
                style_intents=frozenset({"cover", "live"}),
            ),
            60,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                {"title": "Song Cover Remix", "duration": 240},
                0,
                style_intents=frozenset({"cover"}),
            ),
            15,
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                {"title": "Song Cover Live Remix", "duration": 240},
                0,
                style_intents=frozenset({"cover", "live"}),
            ),
            15,
        )

    def test_recorded_live_intent_does_not_remove_actual_broadcast_penalty(
        self,
    ) -> None:
        entry = {
            "title": "Song Live",
            "duration": 240,
            "live_status": "post_live",
        }

        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                entry,
                0,
                style_intents=frozenset({"live"}),
            ),
            -140,
        )

    def test_style_intents_ignore_urls_and_keep_cover_live_separate(self) -> None:
        self.assertEqual(
            music_search_scoring.get_version_style_intents(
                "https://www.youtube.com/live/abcdefghijk"
            ),
            frozenset(),
        )
        self.assertEqual(
            music_search_scoring.get_version_style_intents(
                "Song Cover Live"
            ),
            frozenset({"cover", "live"}),
        )
        self.assertEqual(
            music_search_scoring.get_version_style_intents("How to Live"),
            frozenset(),
        )
        self.assertEqual(
            music_search_scoring.get_version_style_intents("Cover Me"),
            frozenset(),
        )
        self.assertEqual(
            music_search_scoring.get_version_style_intents(
                "Song [Cover] (Live)"
            ),
            frozenset({"cover", "live"}),
        )
        for value in (
            "Song (Live @ Wembley)",
            "Song Live Recording",
            "Song (Live in Tokyo)",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    music_search_scoring.get_version_style_intents(value),
                    frozenset({"live"}),
                )
        for value in ("Song Cover feat. Artist", "Song Cover Lyrics"):
            with self.subTest(value=value):
                self.assertEqual(
                    music_search_scoring.get_version_style_intents(value),
                    frozenset({"cover"}),
                )

    def test_generic_version_marker_does_not_match_inside_english_words(
        self,
    ) -> None:
        for value in ("Cover", "Discover", "Forever", "Never", "Over"):
            with self.subTest(value=value):
                self.assertIsNone(
                    music_search_scoring.GENERIC_VERSION_SEARCH_RE.search(value)
                )

        self.assertIsNotNone(
            music_search_scoring.GENERIC_VERSION_SEARCH_RE.search("斑鳩ルカver")
        )
        self.assertTrue(
            music_search_scoring.should_use_youtube_music_search(
                "Never Gonna Give You Up"
            )
        )
        self.assertEqual(
            music_search_scoring.score_autoplay_candidate(
                {
                    "title": "Song",
                    "channel": "Cover Nation",
                    "duration": 240,
                },
                0,
            ),
            60,
        )

    def test_general_search_only_neutralizes_the_requested_style(self) -> None:
        cover = {"title": "Song Cover", "duration": 240}
        recorded_live = {"title": "Song Live", "duration": 240}

        with patch.object(
            music_search_scoring,
            "get_youtube_search_tokens",
            return_value=set(),
        ):
            self.assertEqual(
                music_search_scoring.score_youtube_search_result(
                    cover,
                    "request cover",
                    0,
                ),
                60,
            )
            self.assertEqual(
                music_search_scoring.score_youtube_search_result(
                    cover,
                    "request live",
                    0,
                ),
                -20,
            )
            self.assertEqual(
                music_search_scoring.score_youtube_search_result(
                    recorded_live,
                    "request live",
                    0,
                ),
                60,
            )
            self.assertEqual(
                music_search_scoring.score_youtube_search_result(
                    recorded_live,
                    "request cover",
                    0,
                ),
                -20,
            )
            self.assertEqual(
                music_search_scoring.score_youtube_search_result(
                    {"title": "Song Remix", "duration": 240},
                    "request cover version",
                    0,
                ),
                15,
            )

    def test_autoplay_ranking_prefers_quality_and_preserves_source_ties(
        self,
    ) -> None:
        entries = [
            {"id": "short", "title": "Song Short Version", "duration": 80},
            {"id": "cover", "title": "Song Cover", "duration": 240},
            {
                "id": "official",
                "title": "Artist - Song Full Version Official MV",
                "duration": 240,
                "channel": "Artist Official",
            },
        ]

        ranked = music_search_scoring.rank_autoplay_candidates(entries)

        self.assertEqual([entry["id"] for entry, _, _ in ranked], ["official", "cover", "short"])
        with patch.object(
            music_search_scoring,
            "score_autoplay_candidate",
            return_value=10,
        ):
            tied = music_search_scoring.rank_autoplay_candidates(entries)
        self.assertEqual([entry["id"] for entry, _, _ in tied], ["short", "cover", "official"])
        self.assertEqual([source_index for _, _, source_index in tied], [0, 1, 2])


class SearchRoutingTests(unittest.TestCase):
    def test_song_and_auto_seed_use_the_same_youtube_search(self) -> None:
        expected = f"ytsearch{music_search_scoring.YOUTUBE_SEARCH_CANDIDATES}:sunfaded"

        self.assertEqual(music_search_scoring.resolve_query("sunfaded"), expected)
        self.assertEqual(music_search_scoring.resolve_query("sunfaded", None), expected)

    def test_full_song_is_preferred_over_game_and_short_versions(self) -> None:
        entries = [
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV（4K対応）",
                "duration": 148,
                "channel": "アイドルマスターチャンネル",
            },
            {
                "id": "x5dIe0FKY_U",
                "title": (
                    "泥濘鳴鳴(Muddy Cries) / コメティック (CoMETIK) / "
                    "歌詞 Color coded lyrics"
                ),
                "duration": 233,
                "channel": "iluvsmurfs",
            },
            {
                "id": "3fwoSr7hxZM",
                "title": "泥濘鳴鳴(斑鳩ルカver)",
                "duration": 235,
                "channel": "CoMETIK SOLO COLLECTION",
            },
            {
                "id": "LkbTHyLUO4k",
                "title": "【シャニソン】Short Ver. コメティック「泥濘鳴鳴」3DMV",
                "duration": 95,
                "channel": "アイドルマスターチャンネル",
            },
        ]

        selected = music_search_scoring.select_youtube_search_result(
            "でいねいめいめい",
            entries,
        )

        self.assertEqual(selected["id"], "x5dIe0FKY_U")

    def test_title_relevance_beats_an_unrelated_longer_result(self) -> None:
        entries = [
            {
                "id": "quick-song1",
                "title": "Artist - Quick Song (Official Audio)",
                "duration": 155,
            },
            {
                "id": "other-song1",
                "title": "Artist - Different Song (Full Version)",
                "duration": 240,
            },
        ]

        selected = music_search_scoring.select_youtube_search_result(
            "Artist Quick Song",
            entries,
        )

        self.assertEqual(selected["id"], "quick-song1")

    def test_explicit_game_mv_request_is_respected(self) -> None:
        entries = [
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV（4K対応）",
                "duration": 148,
            },
            {
                "id": "x5dIe0FKY_U",
                "title": "泥濘鳴鳴 / コメティック / 歌詞 Color coded lyrics",
                "duration": 233,
            },
        ]

        selected = music_search_scoring.select_youtube_search_result(
            "泥濘鳴鳴 game mv",
            entries,
        )

        self.assertEqual(selected["id"], "I-CZXVMPiPg")

    def test_youtube_music_song_result_preserves_catalog_metadata(self) -> None:
        entry = music_search_scoring.youtube_music_result_to_entry(
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "artists": [{"name": "CoMETIK"}],
                "album": {"name": "THE IDOLM@STER SHINY COLORS ECHOES 08"},
                "duration_seconds": 235,
                "thumbnails": [{"url": "https://example.com/cover.jpg"}],
            }
        )

        self.assertIsNotNone(entry)
        self.assertEqual(entry["id"], "CuRIuFRD1zI")
        self.assertEqual(entry["track"], "泥濘鳴鳴")
        self.assertEqual(entry["artist"], "CoMETIK")
        self.assertEqual(entry["duration"], 235)
        self.assertEqual(
            entry["webpage_url"],
            "https://www.youtube.com/watch?v=CuRIuFRD1zI",
        )

    def test_youtube_music_ignores_non_song_results(self) -> None:
        result = music_search_scoring.youtube_music_result_to_entry(
            {
                "resultType": "episode",
                "videoId": "abcdefghijk",
                "title": "Unrelated podcast",
            }
        )

        self.assertIsNone(result)

    def test_top_album_supplies_artist_hint(self) -> None:
        results = [
            {
                "category": "Top result",
                "resultType": "album",
                "title": "THE IDOLM@STER SHINY COLORS ECHOES 08",
                "artists": [{"name": "CoMETIK"}],
            },
            {
                "resultType": "album",
                "title": "Unrelated karaoke",
                "artists": [{"name": "Karaoke Artist"}],
            },
        ]

        self.assertEqual(
            music_search_scoring.get_youtube_music_artist_hint("でいねいめいめい", results),
            "CoMETIK",
        )

    def test_same_title_from_multiple_artists_skips_catalog_shortcut(self) -> None:
        results = [
            {
                "resultType": "song",
                "videoId": "keOnleW2eak",
                "title": "らしさ",
                "artists": [{"name": "Official髭男dism"}],
                "duration_seconds": 313,
            },
            {
                "resultType": "song",
                "videoId": "abcdefghijk",
                "title": "らしさ",
                "artists": [{"name": "SUPER BEAVER"}],
                "duration_seconds": 269,
            },
        ]

        self.assertIsNone(
            music_search_scoring.select_youtube_music_song_result("らしさ", results)
        )
        self.assertIsNone(
            music_search_scoring.get_youtube_music_artist_hint("らしさ", results)
        )

    def test_romanized_query_prefers_official_mv_over_full_fan_upload(self) -> None:
        entries = [
            {
                "id": "BCMKhsXcdJI",
                "title": "OFFICIAL HIGE DANDISM - Rashisa [Official Audio]",
                "duration": 303,
                "channel": "OFFICIAL HIGE DANDISM",
            },
            {
                "id": "keOnleW2eak",
                "title": "OFFICIAL HIGE DANDISM - Rashisa [Official Video]",
                "duration": 313,
                "channel": "OFFICIAL HIGE DANDISM",
            },
            {
                "id": "MizuH2nfwaI",
                "title": (
                    "100 Meters - Theme Song FULL \"Rashisa\" by "
                    "Official HIGE DANdism (Lyrics)"
                ),
                "duration": 313,
                "channel": "Jamong",
            },
        ]

        selected = music_search_scoring.select_youtube_search_result("rashisa", entries)

        self.assertEqual(selected["id"], "keOnleW2eak")

    def test_enriched_search_prefers_bare_catalog_title(self) -> None:
        entries = [
            {
                "id": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "duration": 235,
                "channel": "コメティック",
            },
            {
                "id": "I-CZXVMPiPg",
                "title": "【シャニソン】コメティック「泥濘鳴鳴」3DMV",
                "duration": 148,
                "channel": "アイドルマスターチャンネル",
            },
            {
                "id": "x5dIe0FKY_U",
                "title": (
                    "泥濘鳴鳴(Muddy Cries) / コメティック (CoMETIK) / "
                    "歌詞 Color coded lyrics"
                ),
                "duration": 233,
                "channel": "iluvsmurfs",
            },
        ]
        preferred_title = music_search_scoring.infer_youtube_search_song_title(
            entries[0],
            "CoMETIK",
        )

        selected = music_search_scoring.select_youtube_search_result(
            "でいねいめいめい CoMETIK",
            entries,
            preferred_artist="CoMETIK",
            preferred_title=preferred_title,
        )

        self.assertEqual(preferred_title, "泥濘鳴鳴")
        self.assertEqual(selected["id"], "CuRIuFRD1zI")

    def test_explicit_versions_skip_youtube_music_catalog(self) -> None:
        self.assertFalse(
            music_search_scoring.should_use_youtube_music_search("泥濘鳴鳴 game mv")
        )
        self.assertFalse(
            music_search_scoring.should_use_youtube_music_search("泥濘鳴鳴 cover")
        )
        self.assertFalse(
            music_search_scoring.should_use_youtube_music_search("泥濘鳴鳴 off vocal")
        )
        self.assertTrue(
            music_search_scoring.should_use_youtube_music_search("泥濘鳴鳴")
        )

    def test_album_and_playlist_use_youtube_playlist_search(self) -> None:
        album_url = music_search_scoring.resolve_query("NewJeans Get Up", "album")
        playlist_url = music_search_scoring.resolve_query("lofi beats", "playlist")

        self.assertIn("youtube.com/results?", album_url)
        self.assertIn("NewJeans+Get+Up+full+album", album_url)
        self.assertIn("sp=EgIQAw%253D%253D", album_url)
        self.assertIn("lofi+beats", playlist_url)
        self.assertNotIn("full+album", playlist_url)

    def test_youtube_links_are_accepted_without_rewriting(self) -> None:
        regular = "https://www.youtube.com/watch?v=abcdefghijk"
        music = "https://music.youtube.com/watch?v=abcdefghijk"

        self.assertEqual(music_search_scoring.resolve_query(regular), regular)
        self.assertEqual(music_search_scoring.resolve_query(music), music)

    def test_non_youtube_links_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            music_search_scoring.resolve_query("https://example.com/audio")

    def test_playlist_links_are_detected_as_bulk_requests(self) -> None:
        self.assertTrue(
            bot.is_bulk_youtube_url("https://www.youtube.com/playlist?list=PL123")
        )
        self.assertFalse(
            bot.is_bulk_youtube_url(
                "https://www.youtube.com/watch?v=abcdefghijk&list=PL123"
            )
        )
        self.assertFalse(
            bot.is_bulk_youtube_url("https://www.youtube.com/watch?v=abcdefghijk")
        )

    def test_playlist_result_uses_playlist_id(self) -> None:
        result = {"id": "PL1234567890ABCDEFG"}

        self.assertEqual(
            bot.get_playlist_result_url(result),
            "https://www.youtube.com/playlist?list=PL1234567890ABCDEFG",
        )
