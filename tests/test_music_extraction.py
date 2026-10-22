import ast
import asyncio
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import bot
import music_extraction
import music_ytdl
from music_models import Track
from music_ytdl import YtdlJobKind


def make_track(title: str) -> Track:
    return Track(
        title=title,
        webpage_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
        requester="tester",
        source_url=f"https://www.youtube.com/watch?v={title:0<11}"[:43],
    )


class MusicExtractionModuleTests(unittest.TestCase):
    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        tree = ast.parse(Path(music_extraction.__file__).read_text(encoding="utf-8"))
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
                "asyncio",
                "collections",
                "copy",
                "functools",
                "music_autoplay_logging",
                "music_config",
                "music_models",
                "music_request_parsing",
                "music_search_scoring",
                "music_track_metadata",
                "music_ytdl",
                "requests",
                "threading",
                "time",
                "unicodedata",
                "uuid",
                "ytmusicapi",
                "ytmusicapi.auth.oauth",
            },
        )


class AutoRequestParsingTests(unittest.TestCase):
    def test_auto_parser_uses_runtime_default_setting(self) -> None:
        with patch.object(music_extraction, "DEFAULT_AUTO_TRACKS", 7):
            self.assertEqual(
                music_extraction.parse_auto_request("auto: back number"),
                ("back number", 7),
            )

    def test_auto_parser_uses_runtime_max_setting(self) -> None:
        with patch.object(music_extraction, "MAX_AUTO_TRACKS", 9):
            self.assertEqual(music_extraction.clamp_auto_count(999), 9)
            self.assertEqual(
                music_extraction.parse_auto_request("auto999: lofi chill"),
                ("lofi chill", 9),
            )

    def test_auto_parser_uses_clamp_monkeypatch(self) -> None:
        with patch.object(music_extraction, "clamp_auto_count", return_value=8) as clamp:
            self.assertEqual(
                music_extraction.parse_auto_request("auto999: lofi chill"),
                ("lofi chill", 8),
            )

        clamp.assert_called_once_with(999)


class SearchExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_text_search_uses_flat_candidates_and_selector(self) -> None:
        entries = [
            {"id": "first-track", "title": "Game Version", "duration": 120},
            {"id": "second-track", "title": "Full Version", "duration": 240},
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(
                music_extraction,
                "search_youtube_music",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(music_extraction, "extract_ytdl_info", extract),
            patch.object(
                music_extraction,
                "select_youtube_search_result",
                return_value=entries[1],
            ) as select,
        ):
            result = await music_extraction.extract_first_info(
                "sample song",
                f"ytsearch{music_extraction.YOUTUBE_SEARCH_CANDIDATES}:sample song",
            )

        self.assertIs(result, entries[1])
        extract.assert_awaited_once_with(
            music_extraction.YTDL_SEARCH_OPTIONS,
            f"ytsearch{music_extraction.YOUTUBE_SEARCH_CANDIDATES}:sample song",
            "YouTube search",
            job_kind=YtdlJobKind.USER_REQUEST,
        )
        select.assert_called_once_with("sample song", entries)

    async def test_catalog_song_is_resolved_directly(self) -> None:
        music_results = [
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
                "artists": [{"name": "CoMETIK"}],
                "duration_seconds": 235,
            }
        ]
        resolved = {
            "id": "CuRIuFRD1zI",
            "title": "泥濘鳴鳴",
            "webpage_url": "https://www.youtube.com/watch?v=CuRIuFRD1zI",
            "artist": "CoMETIK",
        }
        extract = AsyncMock(return_value=resolved)

        with (
            patch.object(
                music_extraction,
                "search_youtube_music",
                new=AsyncMock(return_value=music_results),
            ),
            patch.object(music_extraction, "extract_ytdl_info", extract),
        ):
            result = await music_extraction.extract_first_info(
                "でいねいめいめい",
                f"ytsearch{music_extraction.YOUTUBE_SEARCH_CANDIDATES}:"
                "でいねいめいめい",
            )

        self.assertIs(result, resolved)
        extract.assert_awaited_once_with(
            music_extraction.YTDL_OPTIONS,
            "https://www.youtube.com/watch?v=CuRIuFRD1zI",
            "YouTube Music catalog song resolve",
            job_kind=YtdlJobKind.USER_REQUEST,
        )

    async def test_top_album_artist_enriches_youtube_fallback(self) -> None:
        music_results = [
            {
                "category": "Top result",
                "resultType": "album",
                "title": "THE IDOLM@STER SHINY COLORS ECHOES 08",
                "artists": [{"name": "CoMETIK"}],
            }
        ]
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
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(
                music_extraction,
                "search_youtube_music",
                new=AsyncMock(return_value=music_results),
            ),
            patch.object(music_extraction, "extract_ytdl_info", extract),
        ):
            result = await music_extraction.extract_first_info(
                "でいねいめいめい",
                f"ytsearch{music_extraction.YOUTUBE_SEARCH_CANDIDATES}:"
                "でいねいめいめい",
            )

        self.assertEqual(result["id"], "CuRIuFRD1zI")
        extract.assert_awaited_once_with(
            music_extraction.YTDL_SEARCH_OPTIONS,
            f"ytsearch{music_extraction.YOUTUBE_SEARCH_CANDIDATES}:"
            "でいねいめいめい CoMETIK",
            "YouTube search",
            job_kind=YtdlJobKind.USER_REQUEST,
        )

    async def test_direct_url_keeps_full_extraction_options(self) -> None:
        url = "https://www.youtube.com/watch?v=abcdefghijk"
        info = {"id": "abcdefghijk", "title": "Direct song"}
        extract = AsyncMock(return_value=info)
        music_search = AsyncMock()

        with (
            patch.object(music_extraction, "extract_ytdl_info", extract),
            patch.object(music_extraction, "search_youtube_music", new=music_search),
        ):
            result = await music_extraction.extract_first_info(url, url)

        self.assertIs(result, info)
        music_search.assert_not_awaited()
        extract.assert_awaited_once_with(
            music_extraction.YTDL_OPTIONS,
            url,
            "YouTube search",
            job_kind=YtdlJobKind.USER_REQUEST,
        )

    async def test_text_track_defers_stream_resolution_until_playback(self) -> None:
        info = {
            "id": "abcdefghijk",
            "title": "Selected song",
            "duration": 180,
            "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
        }

        with (
            patch.object(
                music_extraction,
                "extract_first_info",
                new=AsyncMock(return_value=info),
            ),
            patch.object(
                music_extraction,
                "resolve_track_stream",
                new=AsyncMock(),
            ) as resolve_stream,
        ):
            track = await music_extraction.extract_track("selected song", "tester")

        resolve_stream.assert_not_awaited()
        self.assertIsNone(track.stream_url)
        self.assertEqual(
            track.source_url,
            "https://www.youtube.com/watch?v=abcdefghijk",
        )

    async def test_auto_fallback_search_uses_flat_options(self) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        candidate = {
            "id": "candidate01",
            "title": "Candidate Song",
            "duration": 180,
        }
        extract = AsyncMock(return_value={"entries": [candidate]})

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 2)

        self.assertEqual([track.title for track in tracks], ["Seed Song", "Candidate Song"])
        extract.assert_awaited_once_with(
            music_extraction.YTDL_SEARCH_OPTIONS,
            "ytsearch6:Seed Song radio mix",
            "auto fallback search",
            job_kind=YtdlJobKind.USER_REQUEST,
        )

    async def test_auto_style_intent_comes_from_seed_title_without_query_scoring(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song Cover",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": "aaaaaaaaaaa",
                "title": "Artist A - Candidate Cover",
                "duration": 240,
            },
            {
                "id": "bbbbbbbbbbb",
                "title": "Artist B - Plain Candidate",
                "duration": 240,
            },
        ]

        with patch.object(
            music_extraction,
            "extract_ytdl_info",
            new=AsyncMock(return_value={"entries": entries}),
        ):
            tracks = await music_extraction.extract_auto_tracks_from_seed(
                seed,
                "자동재생",
                3,
                job_kind=YtdlJobKind.AUTOPLAY,
            )

        self.assertEqual(
            [track.title for track in tracks],
            [
                "Seed Song Cover",
                "Artist A - Candidate Cover",
                "Artist B - Plain Candidate",
            ],
        )
        self.assertEqual(getattr(tracks[1], "_autoplay_score"), 60)

    async def test_background_autoplay_excludes_covers_without_cover_intent(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": "aaaaaaaaaaa",
                "title": "Artist A - Candidate (Self Cover)",
                "duration": 240,
            },
            {
                "id": "bbbbbbbbbbb",
                "title": "Artist B - Plain Candidate",
                "duration": 240,
            },
            {
                "id": "ccccccccccc",
                "title": "Artist C - Cover Me",
                "duration": 240,
            },
        ]

        for job_kind, expected in (
            (
                YtdlJobKind.AUTOPLAY,
                ["Seed Song", "Artist B - Plain Candidate", "Artist C - Cover Me"],
            ),
            (
                YtdlJobKind.USER_REQUEST,
                [
                    "Seed Song",
                    "Artist B - Plain Candidate",
                    "Artist C - Cover Me",
                    "Artist A - Candidate (Self Cover)",
                ],
            ),
        ):
            with (
                self.subTest(job_kind=job_kind),
                patch.object(
                    music_extraction,
                    "extract_ytdl_info",
                    new=AsyncMock(return_value={"entries": entries}),
                ),
                patch.object(music_extraction, "log_autoplay_event") as log_event,
            ):
                tracks = await music_extraction.extract_auto_tracks_from_seed(
                    seed,
                    "자동재생",
                    4,
                    job_kind=job_kind,
                )

                self.assertEqual([track.title for track in tracks], expected)
                statuses = {
                    record["title"]: record["status"]
                    for record in log_event.call_args.kwargs["candidates"]
                }
                self.assertEqual(
                    statuses["Artist A - Candidate (Self Cover)"],
                    "cover_excluded"
                    if job_kind == YtdlJobKind.AUTOPLAY
                    else "candidate",
                )

    async def test_manual_auto_passes_original_query_as_style_context(self) -> None:
        seed_info = {
            "id": "abcdefghijk",
            "title": "Seed Song",
            "webpage_url": "https://www.youtube.com/watch?v=abcdefghijk",
        }
        related_tracks = [make_track("related")]

        with (
            patch.object(
                music_extraction,
                "extract_first_info",
                new=AsyncMock(return_value=seed_info),
            ),
            patch.object(
                music_extraction,
                "extract_auto_tracks_from_seed",
                new=AsyncMock(return_value=related_tracks),
            ) as related,
        ):
            tracks = await music_extraction.extract_auto_tracks(
                "Seed Song cover",
                "tester",
                3,
            )

        self.assertIs(tracks, related_tracks)
        self.assertEqual(related.await_args.kwargs["style_query"], "Seed Song cover")

    async def test_auto_supplemental_search_uses_flat_options(self) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        supplemental = {
            "id": "candidate01",
            "title": "Candidate Song",
            "duration": 180,
        }
        extract = AsyncMock(
            side_effect=[
                {"entries": [{"id": "abcdefghijk", "title": "Seed Song"}]},
                {"entries": [supplemental]},
            ]
        )

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 2)

        self.assertEqual([track.title for track in tracks], ["Seed Song", "Candidate Song"])
        self.assertEqual(extract.await_count, 2)
        self.assertEqual(
            extract.await_args_list[0].args[0]["playlistend"],
            2,
        )
        self.assertEqual(
            extract.await_args_list[0].kwargs["job_kind"],
            YtdlJobKind.USER_REQUEST,
        )
        self.assertEqual(extract.await_args_list[1].args[0], music_extraction.YTDL_SEARCH_OPTIONS)
        self.assertEqual(
            extract.await_args_list[1].args[2],
            "auto supplemental search",
        )
        self.assertEqual(
            extract.await_args_list[1].kwargs["job_kind"],
            YtdlJobKind.USER_REQUEST,
        )

    async def test_auto_supplemental_reranks_before_cross_batch_dedup(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        radio_short = {
            "id": "aaaaaaaaaaa",
            "title": "Artist - Song Short Version",
            "duration": 80,
            "artist": "Artist",
            "track": "Song",
        }
        supplemental_official = {
            "id": "bbbbbbbbbbb",
            "title": "Artist - Song Full Version Official MV",
            "duration": 240,
            "artist": "Artist",
            "track": "Song",
            "channel": "Artist Official",
        }
        supplemental_other = {
            "id": "ccccccccccc",
            "title": "Other Artist - Other Song",
            "duration": 240,
        }
        extract = AsyncMock(
            side_effect=[
                {"entries": [radio_short]},
                {"entries": [supplemental_official, supplemental_other]},
            ]
        )

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 3)

        self.assertEqual(
            [track.title for track in tracks],
            [
                "Seed Song",
                "Artist - Song Full Version Official MV",
                "Other Artist - Other Song",
            ],
        )
        self.assertEqual(extract.await_count, 2)

    async def test_background_autoplay_does_not_run_supplemental_search(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        extract = AsyncMock(
            return_value={
                "entries": [{"id": "abcdefghijk", "title": "Seed Song"}],
            }
        )

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_auto_tracks_from_seed(
                seed,
                "자동재생",
                10,
                job_kind=YtdlJobKind.AUTOPLAY,
            )

        self.assertEqual(tracks, [seed])
        extract.assert_awaited_once()
        self.assertEqual(extract.await_args.args[0]["playlistend"], 10)
        self.assertEqual(
            extract.await_args.kwargs["job_kind"],
            YtdlJobKind.AUTOPLAY,
        )
        self.assertEqual(
            extract.await_args.kwargs["minimum_interval_seconds"],
            music_extraction.AUTOPLAY_MIN_INTERVAL_SECONDS,
        )

    async def test_background_autoplay_does_not_fallback_after_empty_radio(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        extract = AsyncMock(return_value={"entries": []})

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_auto_tracks_from_seed(
                seed,
                "자동재생",
                10,
                job_kind=YtdlJobKind.AUTOPLAY,
            )

        self.assertEqual(tracks, [seed])
        extract.assert_awaited_once()
        self.assertEqual(extract.await_args.args[2], "YouTube radio mix")

    async def test_background_autoplay_does_not_fallback_after_radio_error(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        extract = AsyncMock(side_effect=RuntimeError("radio failed"))

        with (
            patch.object(music_extraction, "extract_ytdl_info", extract),
            self.assertRaisesRegex(RuntimeError, "radio failed"),
        ):
            await music_extraction.extract_auto_tracks_from_seed(
                seed,
                "자동재생",
                10,
                job_kind=YtdlJobKind.AUTOPLAY,
            )

        extract.assert_awaited_once()
        self.assertEqual(extract.await_args.args[2], "YouTube radio mix")

    async def test_user_auto_count_is_not_limited_by_background_refill(self) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://www.youtube.com/watch?v=seedtrack01",
            requester="tester",
            source_url="https://www.youtube.com/watch?v=seedtrack01",
        )
        entries = [
            {
                "id": f"track{index:06d}",
                "title": f"Candidate {index}",
                "duration": 180,
            }
            for index in range(24)
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(music_extraction, "MAX_AUTO_TRACKS", 25),
            patch.object(music_extraction, "MAX_BULK_TRACKS", 10),
            patch.object(bot, "AUTOPLAY_REFILL_CANDIDATES", 5),
            patch.object(music_extraction, "extract_ytdl_info", extract),
        ):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 25)

        self.assertEqual(len(tracks), 25)
        self.assertEqual(extract.await_args.args[0]["playlistend"], 25)
        self.assertEqual(
            extract.await_args.kwargs["job_kind"],
            YtdlJobKind.USER_REQUEST,
        )

    async def test_background_auto_fallback_uses_refill_candidate_count(self) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": f"track{index:06d}",
                "title": f"Candidate {index}",
                "duration": 180,
            }
            for index in range(4)
        ]
        extract = AsyncMock(return_value={"entries": entries})

        with (
            patch.object(bot, "AUTOPLAY_REFILL_CANDIDATES", 5),
            patch.object(music_extraction, "extract_ytdl_info", extract),
        ):
            tracks = await music_extraction.extract_auto_tracks_from_seed(
                seed,
                "tester",
                5,
                job_kind=YtdlJobKind.AUTOPLAY,
            )

        self.assertEqual(len(tracks), 5)
        extract.assert_awaited_once_with(
            music_extraction.YTDL_SEARCH_OPTIONS,
            "ytsearch5:Seed Song radio mix",
            "auto fallback search",
            job_kind=YtdlJobKind.AUTOPLAY,
            minimum_interval_seconds=music_extraction.AUTOPLAY_MIN_INTERVAL_SECONDS,
        )

    async def test_manual_auto_ranks_candidates_before_returning_tracks(self) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": "aaaaaaaaaaa",
                "title": "Artist - Song Short Version",
                "duration": 80,
            },
            {
                "id": "bbbbbbbbbbb",
                "title": "Artist - Song Full Version Official MV",
                "duration": 240,
                "channel": "Artist Official",
            },
            {
                "id": "ccccccccccc",
                "title": "Other Artist - Other Song Cover",
                "duration": 240,
            },
        ]

        with patch.object(
            music_extraction,
            "extract_ytdl_info",
            new=AsyncMock(return_value={"entries": entries}),
        ):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 4)

        self.assertEqual(
            [track.title for track in tracks],
            [
                "Seed Song",
                "Artist - Song Full Version Official MV",
                "Other Artist - Other Song Cover",
                "Artist - Song Short Version",
            ],
        )
        self.assertEqual(getattr(tracks[1], "_autoplay_score"), 158)
        self.assertEqual(getattr(tracks[1], "_autoplay_source_index"), 1)

    async def test_auto_ranking_keeps_best_duplicate_before_deduplication(
        self,
    ) -> None:
        seed = Track(
            title="Seed Song",
            webpage_url="https://example.test/seed",
            requester="tester",
            source_url="https://example.test/seed",
        )
        entries = [
            {
                "id": "aaaaaaaaaaa",
                "title": "Artist - Song Official Audio",
                "duration": 240,
                "channel": "Artist Official",
            },
            {
                "id": "bbbbbbbbbbb",
                "title": "Artist - Song Official MV",
                "duration": 240,
                "channel": "Artist Official",
            },
        ]

        with patch.object(
            music_extraction,
            "extract_ytdl_info",
            new=AsyncMock(return_value={"entries": entries}),
        ):
            tracks = await music_extraction.extract_auto_tracks_from_seed(seed, "tester", 3)

        self.assertEqual(
            [track.title for track in tracks],
            ["Seed Song", "Artist - Song Official MV"],
        )

    async def test_playlist_request_uses_bulk_priority(self) -> None:
        url = "https://www.youtube.com/playlist?list=PL1234567890"
        extract = AsyncMock(
            return_value={
                "entries": [
                    {"id": "abcdefghijk", "title": "Playlist Track"},
                ]
            }
        )

        with patch.object(music_extraction, "extract_ytdl_info", extract):
            tracks = await music_extraction.extract_tracks(url, "tester", "playlist")

        self.assertEqual([track.title for track in tracks], ["Playlist Track"])
        extract.assert_awaited_once_with(
            music_extraction.YTDL_PLAYLIST_OPTIONS,
            url,
            "playlist or album search",
            job_kind=YtdlJobKind.PLAYLIST_ALBUM,
        )


class YouTubeMusicProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        music_extraction.youtube_music_cache.clear()
        music_extraction.youtube_music_client = None
        music_extraction.youtube_music_last_request_started_at = 0.0
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def asyncTearDown(self) -> None:
        music_extraction.youtube_music_cache.clear()
        music_extraction.youtube_music_client = None
        music_extraction.youtube_music_last_request_started_at = 0.0
        music_ytdl.ytdl_last_request_started_at = 0.0
        music_ytdl.youtube_circuit_open_until = 0.0
        music_ytdl.youtube_circuit_reason = None

    async def test_repeated_music_query_uses_cache(self) -> None:
        payload = [
            {
                "resultType": "song",
                "videoId": "CuRIuFRD1zI",
                "title": "泥濘鳴鳴",
            }
        ]
        to_thread = AsyncMock(return_value=payload)

        with (
            patch.object(asyncio, "to_thread", new=to_thread),
            patch.object(music_extraction, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(music_extraction, "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(music_extraction, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await music_extraction.search_youtube_music("でいねいめいめい")
            first[0]["title"] = "caller mutation"
            second = await music_extraction.search_youtube_music("でいねいめいめい")

        to_thread.assert_awaited_once()
        self.assertEqual(second[0]["title"], "泥濘鳴鳴")

    async def test_empty_music_results_are_cached(self) -> None:
        to_thread = AsyncMock(return_value=[])

        with (
            patch.object(asyncio, "to_thread", new=to_thread),
            patch.object(music_extraction, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(music_extraction, "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 0.0),
            patch.object(music_extraction, "YTDL_CACHE_TTL_SECONDS", 600),
        ):
            first = await music_extraction.search_youtube_music("missing song")
            second = await music_extraction.search_youtube_music("missing song")

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        to_thread.assert_awaited_once()

    async def test_disabled_music_search_does_not_start_worker(self) -> None:
        to_thread = AsyncMock()

        with (
            patch.object(asyncio, "to_thread", new=to_thread),
            patch.object(music_extraction, "YOUTUBE_MUSIC_SEARCH_ENABLED", False),
        ):
            results = await music_extraction.search_youtube_music("sample")

        self.assertEqual(results, [])
        to_thread.assert_not_awaited()

    async def test_music_search_uses_its_own_rate_limiter(self) -> None:
        to_thread = AsyncMock(return_value=[])

        with (
            patch.object(asyncio, "to_thread", new=to_thread),
            patch.object(music_extraction, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                music_extraction,
                "wait_for_youtube_music_interval",
                new=AsyncMock(),
            ) as music_wait,
            patch.object(
                music_ytdl,
                "wait_for_ytdl_interval",
                new=AsyncMock(),
            ) as ytdl_wait,
        ):
            await music_extraction.search_youtube_music("independent limiter")

        music_wait.assert_awaited_once_with()
        ytdl_wait.assert_not_awaited()

    async def test_music_search_rechecks_circuit_after_rate_limit_wait(self) -> None:
        semaphore = asyncio.Semaphore(1)
        to_thread = AsyncMock(return_value=[])

        async def open_circuit_during_wait() -> None:
            music_ytdl.youtube_circuit_open_until = music_ytdl.time.monotonic() + 60
            music_ytdl.youtube_circuit_reason = "test circuit"

        with (
            patch.object(music_extraction, "auxiliary_network_semaphore", semaphore),
            patch.object(asyncio, "to_thread", new=to_thread),
            patch.object(music_extraction, "YOUTUBE_MUSIC_SEARCH_ENABLED", True),
            patch.object(
                music_extraction,
                "wait_for_youtube_music_interval",
                side_effect=open_circuit_during_wait,
            ),
            self.assertRaises(music_ytdl.YouTubeCircuitOpenError),
        ):
            await music_extraction.search_youtube_music("circuit opens while waiting")

        to_thread.assert_not_awaited()
        self.assertEqual(semaphore._value, 1)


if __name__ == "__main__":
    unittest.main()
