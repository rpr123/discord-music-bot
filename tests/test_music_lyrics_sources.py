import ast
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot
import music_lyrics_sources


def make_track(title: str) -> bot.Track:
    return bot.Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class MusicLyricsSourcesTests(unittest.TestCase):
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
                "json",
                "music_config",
                "music_models",
                "music_search_scoring",
                "music_track_metadata",
                "re",
                "time",
                "unicodedata",
                "urllib.error",
                "urllib.parse",
                "urllib.request",
            },
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
        request.assert_called_once()
        self.assertEqual(request.call_args.args, ("rashisa", "official hige dandism"))

    def test_title_side_matching_the_channel_is_used_as_artist(self) -> None:
        cases = (
            ("廻廻奇譚 - Eve MV", "Eve", ("廻廻奇譚", "eve")),
            (
                "W/X/Y - Tani Yuuki (Official Lyric Video)",
                "Tani Yuuki",
                ("w/x/y", "tani yuuki"),
            ),
            ("レミオロメン - 粉雪", "レミオロメン", ("粉雪", "レミオロメン")),
        )
        for title, uploader, expected in cases:
            with self.subTest(title=title):
                track = make_track(title)
                track.uploader = uploader
                self.assertEqual(
                    music_lyrics_sources.get_lyrics_search_candidates(track),
                    [expected],
                )

    def test_unknown_title_order_tries_artist_first_then_swapped(self) -> None:
        track = make_track("スピッツ / 渚")
        track.uploader = "spitzclips"

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_candidates(track),
            [("渚", "スピッツ"), ("スピッツ", "渚")],
        )

    def test_youtube_music_metadata_uses_the_first_listed_artist(self) -> None:
        track = make_track("Star-mine")
        track.song_name = "Star-mine"
        track.artist = "Hatsuboshi Gakuen, JIN, Begrazia, Ume Hanami"
        track.uploader = "HATSUBOSHI GAKUEN"

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_terms(track),
            ("star-mine", "hatsuboshi gakuen"),
        )

    def test_title_artist_beats_channel_credit_and_leading_tags(self) -> None:
        track = make_track("【リゼロ】鈴木このみ「Recollect」-lyric video-")
        track.artist = "「Re:ゼロから始める異世界生活」チャンネル【公式】, Konomi Suzuki"
        track.uploader = "「Re:ゼロから始める異世界生活」チャンネル【公式】"

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_terms(track),
            ("recollect", "鈴木このみ"),
        )

    def test_title_that_starts_with_quotes_keeps_the_quoted_song(self) -> None:
        track = make_track("「ねえ、言っちゃうよ。」 - 初星学園 [Lyrics]")
        track.uploader = "fan channel"

        self.assertEqual(
            music_lyrics_sources.get_lyrics_search_terms(track),
            ("ねえ、言っちゃうよ。", "初星学園"),
        )

    def test_lookup_tries_swapped_order_after_title_only_miss(self) -> None:
        track = make_track("廻廻奇譚 - Eve MV")
        track.uploader = "fan uploads"
        track.duration = 223
        english_song = {
            "trackName": "Eve",
            "artistName": "Chantal Kreviazuk",
            "duration": 225,
            "instrumental": False,
            "plainLyrics": "Eve is gone again",
        }
        japanese_song = {
            "trackName": "廻廻奇譚",
            "artistName": "Eve",
            "duration": 223,
            "instrumental": False,
            "plainLyrics": "言いたいことも言えずに",
        }

        with patch.object(
            music_lyrics_sources,
            "request_lyrics_records",
            side_effect=[[], [english_song], [japanese_song]],
        ) as request:
            lyrics = music_lyrics_sources.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "言いたいことも言えずに")
        self.assertEqual(
            [call.args for call in request.call_args_list],
            [("eve", "廻廻奇譚"), ("eve", None), ("廻廻奇譚", "eve")],
        )

    def test_title_alias_in_parentheses_is_searched_separately(self) -> None:
        cases = [
            # LRCLIB lists the first under its native title, the second
            # under its romanized one.
            ("ファイトソング (Fight Song) - Eve Music Video", "ファイトソング", 0),
            ("ぼくらの (Bokurano) - Eve Music Video", "Bokurano", 1),
        ]
        for title, record_name, alias_index in cases:
            with self.subTest(title=title):
                track = make_track(title)
                track.uploader = "Eve"
                track.duration = 260
                record = {
                    "trackName": record_name,
                    "artistName": "Eve",
                    "duration": 258,
                    "instrumental": False,
                    "plainLyrics": "歌詞",
                }
                name, artist = music_lyrics_sources.get_lyrics_search_terms(track)
                aliases = music_lyrics_sources.split_title_alias(name)
                responses = [[], []] + [[]] * alias_index + [[record]]

                with patch.object(
                    music_lyrics_sources,
                    "request_lyrics_records",
                    side_effect=responses,
                ) as request:
                    lyrics = music_lyrics_sources.lookup_track_lyrics(track)

                self.assertEqual(lyrics, "歌詞")
                self.assertEqual(
                    [call.args for call in request.call_args_list],
                    [(name, artist), (name, None)]
                    + [(alias, artist) for alias in aliases[: alias_index + 1]],
                )

    def test_title_segments_drop_channel_names_and_labels(self) -> None:
        cases = [
            ("サカナクション / 怪獣　-Music Video-", "sakanaction", ["サカナクション", "怪獣"]),
            ("暴徒 - Eve MV", "Eve", ["暴徒"]),
            (
                "神山羊 - YELLOW【Music Video】/ Yoh Kamiyama - YELLOW",
                "Yoh Kamiyama",
                ["神山羊", "yellow"],
            ),
            (
                "ティーンエイジブルー (Teenage Blue) – Eve 「アオのハコ」SPECIAL MV",
                "Eve",
                ["ティーンエイジブルー", "teenage blue", "アオのハコ"],
            ),
        ]
        for title, uploader, expected in cases:
            with self.subTest(title=title):
                track = make_track(title)
                track.uploader = uploader
                self.assertEqual(
                    music_lyrics_sources.get_title_search_segments(track),
                    expected,
                )

    def test_title_segment_search_keeps_records_named_in_the_title(self) -> None:
        track = make_track("米津玄師 - ピースサイン , Kenshi Yonezu - Peace Sign")
        track.uploader = "米津玄師"
        track.duration = 240
        other_artist = {
            "trackName": "ピースサイン",
            "artistName": "Cover Singer",
            "duration": 240,
            "instrumental": False,
            "plainLyrics": "cover",
        }
        original = {
            "trackName": "ピースサイン",
            "artistName": "Kenshi Yonezu",
            "duration": 239,
            "instrumental": False,
            "plainLyrics": "original",
        }

        with (
            patch.object(
                music_lyrics_sources, "request_lyrics_records", return_value=[]
            ),
            patch.object(
                music_lyrics_sources,
                "search_lyrics_records",
                return_value=[other_artist, original],
            ) as search,
        ):
            lyrics = music_lyrics_sources.lookup_track_lyrics(track)

        self.assertEqual(lyrics, "original")
        search.assert_called_once()

    def test_title_segment_search_gives_up_after_the_limit(self) -> None:
        track = make_track("A one / B two / C three / D four / E five")
        track.uploader = "Nobody"
        unrelated = {
            "trackName": "Elsewhere",
            "artistName": "Someone",
            "duration": 200,
            "instrumental": False,
            "plainLyrics": "words",
        }

        with (
            patch.object(
                music_lyrics_sources, "request_lyrics_records", return_value=[]
            ),
            patch.object(
                music_lyrics_sources,
                "search_lyrics_records",
                return_value=[unrelated],
            ) as search,
        ):
            lyrics = music_lyrics_sources.lookup_track_lyrics(track)

        self.assertIsNone(lyrics)
        self.assertEqual(
            search.call_count, music_lyrics_sources.LYRICS_SEGMENT_SEARCH_LIMIT
        )

    def native_song_for(self, results: list[dict], duration: int | None = 248):
        track = make_track("Ano Hana no you ni")
        track.song_name = "Ano Hana no you ni"
        track.artist = "noctchill"
        track.uploader = "ノクチル"
        track.duration = duration
        with patch.object(
            music_lyrics_sources, "request_itunes_songs", return_value=results
        ) as request:
            song = music_lyrics_sources.lookup_native_song(track, "ja")
        return song, request

    def test_itunes_japan_store_gives_the_native_title(self) -> None:
        song, request = self.native_song_for(
            [
                {"trackName": "あの花のように (Off Vocal)", "artistName": "ノクチル", "trackTimeMillis": 247100},
                {"trackName": "別の曲", "artistName": "ノクチル", "trackTimeMillis": 200000},
                {"trackName": "あの花のように", "artistName": "ノクチル", "trackTimeMillis": 247600},
            ]
        )

        self.assertEqual(song, ("あの花のように", "ノクチル"))
        params = request.call_args.args[0]
        self.assertEqual(params["term"], "ano hana no you ni noctchill")
        self.assertEqual((params["country"], params["lang"]), ("JP", "ja_jp"))

    def test_itunes_result_must_match_the_track_length(self) -> None:
        song, _ = self.native_song_for(
            [{"trackName": "あの花のように", "artistName": "ノクチル", "trackTimeMillis": 300000}]
        )
        self.assertIsNone(song)

        song, request = self.native_song_for([], duration=None)
        self.assertIsNone(song)
        request.assert_not_called()

    def test_korean_songs_skip_itunes(self) -> None:
        track = make_track("Bam Pyeonji")
        track.duration = 253
        with patch.object(music_lyrics_sources, "request_itunes_songs") as request:
            self.assertIsNone(music_lyrics_sources.lookup_native_song(track, "ko"))
        request.assert_not_called()

    def test_title_alias_needs_two_scripts(self) -> None:
        self.assertEqual(
            music_lyrics_sources.split_title_alias("ファイトソング (fight song)"),
            ["ファイトソング", "fight song"],
        )
        self.assertEqual(
            music_lyrics_sources.split_title_alias("あびすいんざわーるど(abyss in the world)"),
            ["あびすいんざわーるど", "abyss in the world"],
        )
        for value in ("song (live)", "夜に駆ける (アコースティック)", "plain title"):
            with self.subTest(value=value):
                self.assertEqual(music_lyrics_sources.split_title_alias(value), [])

    def test_native_title_rejects_foreign_lyrics_without_artist_match(self) -> None:
        record = {
            "trackName": "Eve",
            "artistName": "Chantal Kreviazuk",
            "duration": 225,
            "instrumental": False,
            "plainLyrics": "Eve is gone again",
        }

        self.assertIs(
            music_lyrics_sources.select_lyrics_record([record], "eve", "廻廻奇譚", 223),
            record,
        )
        self.assertIsNone(
            music_lyrics_sources.select_lyrics_record(
                [record], "eve", "廻廻奇譚", 223, require_native_script=True,
            )
        )

    def test_romanized_song_on_native_channel_requests_native_metadata(self) -> None:
        def track(title: str, uploader: str | None, artist: str | None = None) -> bot.Track:
            return bot.Track(
                title=title,
                webpage_url="https://www.youtube.com/watch?v=S38phza2dn8",
                requester="tester",
                source_url="https://www.youtube.com/watch?v=S38phza2dn8",
                song_name=title,
                uploader=uploader,
                artist=artist,
            )

        get_language = music_lyrics_sources.get_native_metadata_language
        self.assertEqual(get_language(track("Ano Hana no you ni", "ノクチル", "noctchill")), "ja")
        self.assertEqual(get_language(track("Blue Moon", "이세계아이돌")), "ko")
        self.assertIsNone(get_language(track("あの花のように", "ノクチル")))
        self.assertIsNone(get_language(track("Karma", "Fumage - Topic", "Fumage")))
        self.assertIsNone(get_language(track("Song", None)))

    def test_plain_lyrics_drop_stray_lrc_timestamps(self) -> None:
        record = {
            "instrumental": False,
            "plainLyrics": "淡い暗い夜に浮かんで\n[00:05.10] 崩れた",
        }

        self.assertEqual(
            music_lyrics_sources.extract_original_lyrics(record),
            "淡い暗い夜に浮かんで\n崩れた",
        )

    def test_request_retries_when_lrclib_is_overloaded(self) -> None:
        overloaded = urllib.error.HTTPError(
            "https://lrclib.net/api/search", 503, "Service Unavailable", {}, None,
        )
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            [{"trackName": "Song"}]
        ).encode("utf-8")

        with (
            patch.object(
                music_lyrics_sources.urllib.request,
                "urlopen",
                side_effect=[overloaded, overloaded, response],
            ) as urlopen,
            patch.object(music_lyrics_sources.time, "sleep") as sleep,
        ):
            records = music_lyrics_sources.request_lyrics_records("song", None)

        self.assertEqual(records, [{"trackName": "Song"}])
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(
            [call.args[0] for call in sleep.call_args_list],
            list(music_lyrics_sources.LYRICS_RETRY_DELAYS_SECONDS[:2]),
        )

    def test_request_gives_up_on_overload_and_other_http_errors(self) -> None:
        overload_attempts = len(music_lyrics_sources.LYRICS_RETRY_DELAYS_SECONDS) + 1
        self.assertEqual(overload_attempts, 5)
        for code, expected_attempts in ((503, overload_attempts), (404, 1)):
            error = urllib.error.HTTPError(
                "https://lrclib.net/api/search", code, "error", {}, None,
            )
            with (
                self.subTest(code=code),
                patch.object(
                    music_lyrics_sources.urllib.request,
                    "urlopen",
                    side_effect=error,
                ) as urlopen,
                patch.object(music_lyrics_sources.time, "sleep"),
                self.assertRaises(music_lyrics_sources.LyricsLookupError),
            ):
                music_lyrics_sources.request_lyrics_records("song", None)
            self.assertEqual(urlopen.call_count, expected_attempts)

    def test_request_does_not_retry_past_the_lookup_deadline(self) -> None:
        overloaded = urllib.error.HTTPError(
            "https://lrclib.net/api/search", 503, "Service Unavailable", {}, None,
        )

        with (
            patch.object(
                music_lyrics_sources.urllib.request,
                "urlopen",
                side_effect=overloaded,
            ) as urlopen,
            patch.object(music_lyrics_sources.time, "sleep") as sleep,
            patch.object(music_lyrics_sources.time, "monotonic", return_value=100.0),
            self.assertRaises(music_lyrics_sources.LyricsLookupError),
        ):
            music_lyrics_sources.request_lyrics_records(
                "song", None, deadline=101.0,
            )

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()

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
