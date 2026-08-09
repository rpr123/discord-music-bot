import ast
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot
import music_namuwiki
from music_models import Track


ARTIST_MOVED_NAMES = (
    "extract_namuwiki_primary_artist_from_tables",
    "get_namuwiki_track_artists",
    "namuwiki_artist_matches_track",
)


NAMUWIKI_HTML_FIXTURE = """
<html>
  <body>
    <table class="wiki-table">
      <tbody>
        <tr>
          <th>일본어 원문</th>
          <th>일본어 독음</th>
          <th>한국어 번역<sup>[1]</sup></th>
        </tr>
        <tr>
          <td>泥濘 鳴鳴</td>
          <td>でいねい めいめい</td>
          <td><div>진창에서 울리는 노랫소리</div></td>
        </tr>
        <tr>
          <td>礼を持って</td>
          <td>れいをもって</td>
          <td>예를 갖추어 다시 걸어가</td>
        </tr>
      </tbody>
    </table>
  </body>
</html>
"""
NAMUWIKI_NAMUMARK_FIXTURE = """
||<tablewidth=100%><rowbgcolor=#222> '''일본어 원문''' || '''일본어 독음''' || '''한국어 번역''' ||
|| 泥濘 鳴鳴 || でいねい めいめい || 진창에서 울리는 노랫소리 ||
|| 礼を持って || れいをもって || 예를 갖추어 다시 걸어가 ||
"""
NAMUWIKI_EXPECTED_LYRICS = (
    "泥濘 鳴鳴\n"
    "でいねい めいめい\n"
    "진창에서 울리는 노랫소리\n\n"
    "礼を持って\n"
    "れいをもって\n"
    "예를 갖추어 다시 걸어가"
)
NAMUWIKI_DOCUMENT = "泥濘鳴鳴"
NAMUWIKI_PAGE_URL = (
    "https://namu.wiki/w/"
    "%E6%B3%A5%E6%BF%98%E9%B3%B4%E9%B3%B4"
)

def make_track(
    title: str = "Song",
    *,
    source_url: str = "https://example.com/watch?v=test",
) -> Track:
    return Track(
        title=title,
        webpage_url=source_url,
        requester="tester",
        source_url=source_url,
    )


def make_namuwiki_track(title: str) -> Track:
    source_url = f"https://www.youtube.com/watch?v={title:0<11}"[:43]
    return make_track(title, source_url=source_url)


class MusicNamuWikiArtistsTests(unittest.TestCase):
    def test_bot_reexports_moved_artist_names(self) -> None:
        for name in ARTIST_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki, name),
                )

    def test_primary_artist_uses_first_value_after_a_known_label(self) -> None:
        tables = [[["발매일", "2026"], ["ＡＲＴＩＳＴ", "", "SUPER BEAVER\n공식"]]]
        self.assertEqual(
            music_namuwiki.extract_namuwiki_primary_artist_from_tables(
                tables
            ),
            "SUPER BEAVER",
        )

    def test_track_artist_prefers_metadata_then_falls_back_to_title(self) -> None:
        track = make_track("Ignored Artist「Song」")
        track.artist = "Ａｒｔｉｓｔ - Topic"
        self.assertEqual(
            music_namuwiki.get_namuwiki_track_artists(track),
            ["Artist"],
        )

        track.artist = None
        self.assertEqual(
            music_namuwiki.get_namuwiki_track_artists(track),
            ["Ignored Artist"],
        )

    def test_track_artist_can_be_inferred_around_song_name(self) -> None:
        track = make_track("SUPER BEAVER - らしさ")
        track.song_name = "らしさ"
        self.assertEqual(
            music_namuwiki.get_namuwiki_track_artists(track),
            ["SUPER BEAVER"],
        )

    def test_artist_match_preserves_exact_partial_and_unknown_rules(self) -> None:
        track = make_track()
        track.artist = "Official髭男dism"

        self.assertTrue(
            music_namuwiki.namuwiki_artist_matches_track(
                track, "Official髭男dism"
            )
        )
        self.assertTrue(
            music_namuwiki.namuwiki_artist_matches_track(
                track, "Official髭男dism Music"
            )
        )
        self.assertFalse(
            music_namuwiki.namuwiki_artist_matches_track(
                track, "SUPER BEAVER"
            )
        )
        self.assertTrue(
            music_namuwiki.namuwiki_artist_matches_track(track, None)
        )


class MusicNamuWikiCandidatesTests(unittest.TestCase):
    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki.__file__).read_text(
            encoding="utf-8"
        )
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
                "collections.abc",
                "json",
                "music_config",
                "music_lyrics_sources",
                "music_models",
                "music_namuwiki_parsing",
                "music_search_scoring",
                "music_track_metadata",
                "re",
                "threading",
                "time",
                "unicodedata",
                "urllib.error",
                "urllib.parse",
                "urllib.request",
            },
        )

    def test_bot_override_wrapper_reads_current_setting(self) -> None:
        track = make_track(
            source_url="https://www.youtube.com/watch?v=abcdefghijk"
        )
        with patch.object(
            music_namuwiki,
            "NAMUWIKI_DOCUMENT_OVERRIDES",
            {"video:abcdefghijk": "Configured document"},
        ):
            self.assertEqual(
                bot.get_namuwiki_override(track),
                "Configured document",
            )

    def test_document_wrapper_preserves_override_patch_and_limit(self) -> None:
        track = make_track(
            "Artist - Song (Official Video)",
            source_url="https://www.youtube.com/watch?v=abcdefghijk",
        )
        with (
            patch.object(
                music_namuwiki,
                "get_namuwiki_override",
                return_value="Patched document",
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_MAX_DOCUMENT_CANDIDATES",
                1,
            ),
        ):
            self.assertEqual(
                bot.get_namuwiki_document_candidates(track),
                ["Patched document"],
            )

    def test_split_wrapper_reads_current_base_url(self) -> None:
        with patch.object(
            music_namuwiki,
            "NAMUWIKI_PAGE_BASE_URL",
            "https://example.test/w",
        ):
            self.assertEqual(
                bot.split_namuwiki_candidate("문서"),
                (
                    "문서",
                    "https://example.test/w/%EB%AC%B8%EC%84%9C",
                ),
            )

    def test_candidate_parser_canonicalizes_url_and_rejects_bad_scheme(self) -> None:
        document, page_url = music_namuwiki.parse_namuwiki_candidate(
            "https://namu.wiki/w/문서?from=old#section",
            "https://unused.test/w",
        )
        self.assertEqual(document, "문서")
        self.assertEqual(
            page_url,
            "https://namu.wiki/w/%EB%AC%B8%EC%84%9C",
        )
        with self.assertRaises(bot.NamuWikiLyricsError):
            music_namuwiki.parse_namuwiki_candidate(
                "ftp://namu.wiki/w/document",
                "https://namu.wiki/w",
            )


    def test_exact_song_title_is_the_first_document_candidate(self) -> None:
        track = make_namuwiki_track(NAMUWIKI_DOCUMENT)

        candidates = music_namuwiki.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], NAMUWIKI_DOCUMENT)

    def test_artist_qualified_document_follows_ambiguous_song_title(
        self,
    ) -> None:
        track = make_namuwiki_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"

        candidates = music_namuwiki.get_namuwiki_document_candidates(track)

        self.assertEqual(
            candidates[:2],
            ["らしさ", "らしさ(Official髭男dism)"],
        )

    def test_document_candidate_keeps_case_while_removing_video_label(
        self,
    ) -> None:
        track = make_namuwiki_track("SUNFADED (Official Audio)")

        candidates = music_namuwiki.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], "SUNFADED")

    def test_artist_prefix_and_video_label_are_removed_from_candidate(
        self,
    ) -> None:
        track = make_namuwiki_track("CoMETIK - 泥濘鳴鳴 (Official MV)")

        candidates = music_namuwiki.get_namuwiki_document_candidates(track)

        self.assertEqual(candidates[0], NAMUWIKI_DOCUMENT)

    def test_unknown_leading_video_tag_has_clean_title_fallback(self) -> None:
        track = make_namuwiki_track(f"【シャニソン】{NAMUWIKI_DOCUMENT}")

        candidates = music_namuwiki.get_namuwiki_document_candidates(track)

        self.assertEqual(
            candidates[:2],
            [f"【シャニソン】{NAMUWIKI_DOCUMENT}", NAMUWIKI_DOCUMENT],
        )

    def test_unicode_override_url_is_canonicalized(self) -> None:
        document, page_url = music_namuwiki.split_namuwiki_candidate(
            f"https://namu.wiki/w/{NAMUWIKI_DOCUMENT}?from=test#lyrics"
        )

        self.assertEqual(document, NAMUWIKI_DOCUMENT)
        self.assertEqual(page_url, NAMUWIKI_PAGE_URL)

def make_http_error(url: str, status: int):
    return music_namuwiki.urllib.error.HTTPError(
        url,
        status,
        "error",
        {},
        None,
    )


class MusicNamuWikiTransportTests(unittest.TestCase):
    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki.__file__).read_text(
            encoding="utf-8"
        )
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
                "collections.abc",
                "json",
                "music_config",
                "music_lyrics_sources",
                "music_models",
                "music_namuwiki_parsing",
                "music_search_scoring",
                "music_track_metadata",
                "re",
                "threading",
                "time",
                "unicodedata",
                "urllib.error",
                "urllib.parse",
                "urllib.request",
            },
        )

    def test_response_wrapper_reads_current_size_limit(self) -> None:
        response = MagicMock()
        response.read.return_value = b"12345"

        with patch.object(music_namuwiki, "NAMUWIKI_MAX_RESPONSE_BYTES", 4):
            with self.assertRaises(bot.NamuWikiLyricsError):
                bot.read_limited_http_response(response)

        response.read.assert_called_once_with(5)

    def test_api_wrapper_passes_current_settings_and_helpers(self) -> None:
        wait_for_interval = MagicMock()
        read_response = MagicMock()
        urlopen = MagicMock()
        with (
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", "token"),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_API_BASE_URL",
                "https://api.test",
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_TIMEOUT_SECONDS",
                7,
            ),
            patch.object(
                music_namuwiki,
                "wait_for_namuwiki_interval",
                wait_for_interval,
            ),
            patch.object(
                music_namuwiki,
                "read_limited_http_response",
                read_response,
            ),
            patch.object(music_namuwiki.urllib.request, "urlopen", urlopen),
            patch.object(
                music_namuwiki,
                "fetch_namuwiki_api_source",
                return_value="source",
            ) as fetch_source,
        ):
            result = bot.request_namuwiki_api_source("Document")

        self.assertEqual(result, "source")
        fetch_source.assert_called_once_with(
            "Document",
            api_token="token",
            api_base_url="https://api.test",
            timeout_seconds=7,
            wait_for_interval=wait_for_interval,
            read_response=read_response,
            urlopen=urlopen,
        )

    def test_html_wrapper_passes_current_settings_and_helpers(self) -> None:
        wait_for_interval = MagicMock()
        read_response = MagicMock()
        urlopen = MagicMock()
        blocked_markers = ("blocked",)
        with (
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_TIMEOUT_SECONDS",
                9,
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_BLOCKED_MARKERS",
                blocked_markers,
            ),
            patch.object(
                music_namuwiki,
                "wait_for_namuwiki_interval",
                wait_for_interval,
            ),
            patch.object(
                music_namuwiki,
                "read_limited_http_response",
                read_response,
            ),
            patch.object(music_namuwiki.urllib.request, "urlopen", urlopen),
            patch.object(
                music_namuwiki,
                "fetch_namuwiki_html_once",
                return_value=("html", "https://final.test"),
            ) as fetch_html,
        ):
            result = bot.request_namuwiki_html_once(
                "https://page.test",
                "agent",
            )

        self.assertEqual(result, ("html", "https://final.test"))
        fetch_html.assert_called_once_with(
            "https://page.test",
            "agent",
            timeout_seconds=9,
            wait_for_interval=wait_for_interval,
            read_response=read_response,
            urlopen=urlopen,
            blocked_markers=blocked_markers,
        )

    def test_html_transport_detects_challenge_marker(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://final.test"

        with self.assertRaises(bot.NamuWikiPageBlockedError):
            music_namuwiki.fetch_namuwiki_html_once(
                "https://page.test",
                "agent",
                timeout_seconds=3,
                wait_for_interval=MagicMock(),
                read_response=MagicMock(return_value=b"RATE LIMIT"),
                urlopen=MagicMock(return_value=response),
            )

    def test_transport_api_404_and_410_return_none(self) -> None:
        common = {
            "api_token": "token",
            "api_base_url": "https://api.test",
            "timeout_seconds": 3,
            "wait_for_interval": MagicMock(),
            "read_response": MagicMock(),
        }
        for status in (404, 410):
            with self.subTest(status=status):
                self.assertIsNone(
                    music_namuwiki.fetch_namuwiki_api_source(
                        "Document",
                        urlopen=MagicMock(
                            side_effect=make_http_error(
                                "https://api.test/edit/Document",
                                status,
                            )
                        ),
                        **common,
                    )
                )

    def test_transport_api_other_http_error_is_wrapped(self) -> None:
        with self.assertRaisesRegex(
            bot.NamuWikiLyricsError,
            "NamuWiki API returned HTTP 500",
        ):
            music_namuwiki.fetch_namuwiki_api_source(
                "Document",
                api_token="token",
                api_base_url="https://api.test",
                timeout_seconds=3,
                wait_for_interval=MagicMock(),
                read_response=MagicMock(),
                urlopen=MagicMock(
                    side_effect=make_http_error(
                        "https://api.test/edit/Document",
                        500,
                    )
                ),
            )

    def test_transport_html_404_and_410_return_none(self) -> None:
        common = {
            "timeout_seconds": 3,
            "wait_for_interval": MagicMock(),
            "read_response": MagicMock(),
        }
        for status in (404, 410):
            with self.subTest(status=status):
                self.assertIsNone(
                    music_namuwiki.fetch_namuwiki_html_once(
                        "https://page.test",
                        "agent",
                        urlopen=MagicMock(
                            side_effect=make_http_error(
                                "https://page.test",
                                status,
                            )
                        ),
                        **common,
                    )
                )

    def test_transport_html_403_is_blocked(self) -> None:
        with self.assertRaises(bot.NamuWikiPageBlockedError):
            music_namuwiki.fetch_namuwiki_html_once(
                "https://page.test",
                "agent",
                timeout_seconds=3,
                wait_for_interval=MagicMock(),
                read_response=MagicMock(),
                urlopen=MagicMock(
                    side_effect=make_http_error(
                        "https://page.test",
                        403,
                    )
                ),
            )
    def test_public_html_request_returns_page_source_and_final_url(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = NAMUWIKI_HTML_FIXTURE.encode("utf-8")
        response.geturl.return_value = NAMUWIKI_PAGE_URL

        with (
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
                0,
            ),
            patch.object(
                music_namuwiki.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            result = music_namuwiki.request_namuwiki_html(NAMUWIKI_PAGE_URL)

        self.assertEqual(result, (NAMUWIKI_HTML_FIXTURE, NAMUWIKI_PAGE_URL))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, NAMUWIKI_PAGE_URL)
        self.assertIn("text/html", request.get_header("Accept"))

    def test_public_html_403_switches_to_discord_preview_renderer(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = NAMUWIKI_HTML_FIXTURE.encode("utf-8")
        response.geturl.return_value = NAMUWIKI_PAGE_URL
        blocked = music_namuwiki.urllib.error.HTTPError(
            NAMUWIKI_PAGE_URL,
            403,
            "Forbidden",
            {},
            None,
        )

        with (
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
                0,
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_PREVIEW_FALLBACK_ENABLED",
                True,
            ),
            patch.object(
                music_namuwiki,
                "namuwiki_prefer_preview_renderer",
                False,
            ),
            patch.object(
                music_namuwiki.urllib.request,
                "urlopen",
                side_effect=[blocked, response, response],
            ) as urlopen,
        ):
            first_result = music_namuwiki.request_namuwiki_html(NAMUWIKI_PAGE_URL)
            second_result = music_namuwiki.request_namuwiki_html(NAMUWIKI_PAGE_URL)

            self.assertTrue(music_namuwiki.namuwiki_prefer_preview_renderer)

        self.assertEqual(first_result, (NAMUWIKI_HTML_FIXTURE, NAMUWIKI_PAGE_URL))
        self.assertEqual(second_result, (NAMUWIKI_HTML_FIXTURE, NAMUWIKI_PAGE_URL))
        user_agents = [
            call.args[0].get_header("User-agent")
            for call in urlopen.call_args_list
        ]
        self.assertEqual(
            user_agents,
            [
                music_namuwiki.NAMUWIKI_BROWSER_USER_AGENT,
                music_namuwiki.NAMUWIKI_PREVIEW_USER_AGENT,
                music_namuwiki.NAMUWIKI_PREVIEW_USER_AGENT,
            ],
        )

    def test_public_html_preview_fallback_can_be_disabled(self) -> None:
        blocked = music_namuwiki.urllib.error.HTTPError(
            NAMUWIKI_PAGE_URL,
            403,
            "Forbidden",
            {},
            None,
        )
        with (
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
                0,
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_PREVIEW_FALLBACK_ENABLED",
                False,
            ),
            patch.object(
                music_namuwiki,
                "namuwiki_prefer_preview_renderer",
                False,
            ),
            patch.object(
                music_namuwiki.urllib.request,
                "urlopen",
                side_effect=blocked,
            ) as urlopen,
            self.assertRaises(music_namuwiki.NamuWikiPageBlockedError),
        ):
            music_namuwiki.request_namuwiki_html(NAMUWIKI_PAGE_URL)

        urlopen.assert_called_once()

    def test_public_html_challenge_switches_to_discord_preview(self) -> None:
        challenge_response = MagicMock()
        challenge_response.__enter__.return_value = challenge_response
        challenge_response.read.return_value = (
            "<html><body>CAPTCHA 인증이 필요합니다.</body></html>"
        ).encode("utf-8")
        challenge_response.geturl.return_value = NAMUWIKI_PAGE_URL
        preview_response = MagicMock()
        preview_response.__enter__.return_value = preview_response
        preview_response.read.return_value = NAMUWIKI_HTML_FIXTURE.encode("utf-8")
        preview_response.geturl.return_value = NAMUWIKI_PAGE_URL

        with (
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
                0,
            ),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_PREVIEW_FALLBACK_ENABLED",
                True,
            ),
            patch.object(
                music_namuwiki,
                "namuwiki_prefer_preview_renderer",
                False,
            ),
            patch.object(
                music_namuwiki.urllib.request,
                "urlopen",
                side_effect=[challenge_response, preview_response],
            ) as urlopen,
        ):
            result = music_namuwiki.request_namuwiki_html(NAMUWIKI_PAGE_URL)

        self.assertEqual(result, (NAMUWIKI_HTML_FIXTURE, NAMUWIKI_PAGE_URL))
        self.assertEqual(urlopen.call_count, 2)

    def test_api_request_reads_namumark_text_with_bearer_token(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            {"exists": True, "text": NAMUWIKI_NAMUMARK_FIXTURE}
        ).encode("utf-8")

        with (
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", "test-token"),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_REQUEST_INTERVAL_SECONDS",
                0,
            ),
            patch.object(
                music_namuwiki.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
        ):
            source = music_namuwiki.request_namuwiki_api_source(NAMUWIKI_DOCUMENT)

        self.assertEqual(source, NAMUWIKI_NAMUMARK_FIXTURE)
        request = urlopen.call_args.args[0]
        self.assertTrue(
            request.full_url.endswith(
                "/edit/" + NAMUWIKI_PAGE_URL.rsplit("/", 1)[1]
            )
        )
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-token",
        )

class MusicNamuWikiLookupTests(unittest.TestCase):
    def test_exact_namuwiki_page_uses_rendered_html_without_api_token(
        self,
    ) -> None:
        track = make_namuwiki_track(NAMUWIKI_DOCUMENT)
        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
                return_value=(NAMUWIKI_HTML_FIXTURE, NAMUWIKI_PAGE_URL),
            ) as html_lookup,
        ):
            result = music_namuwiki.lookup_namuwiki_lyrics(track)

        self.assertEqual(
            result,
            (
                NAMUWIKI_EXPECTED_LYRICS,
                "나무위키 · 원문·독음·번역",
                NAMUWIKI_PAGE_URL,
            ),
        )
        html_lookup.assert_called_once_with(NAMUWIKI_PAGE_URL)

    def test_artist_mismatch_uses_qualified_namuwiki_document(self) -> None:
        track = make_namuwiki_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"
        wrong_document = "らしさ"
        right_document = "らしさ(Official髭男dism)"
        wrong_url = music_namuwiki.split_namuwiki_candidate(wrong_document)[1]
        right_url = music_namuwiki.split_namuwiki_candidate(right_document)[1]

        def page_with_artist(artist: str) -> str:
            return NAMUWIKI_HTML_FIXTURE.replace(
                "<body>",
                (
                    "<body><table><tr><td>가수</td>"
                    f"<td>{artist}</td></tr></table>"
                ),
            )

        def request_page(page_url: str):
            if page_url == wrong_url:
                return page_with_artist("SUPER BEAVER"), wrong_url
            if page_url == right_url:
                return page_with_artist("Official髭男dism"), right_url
            return None

        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
                side_effect=request_page,
            ) as html_lookup,
        ):
            result = music_namuwiki.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], NAMUWIKI_EXPECTED_LYRICS)
        self.assertEqual(result[2], right_url)
        self.assertEqual(
            [call.args[0] for call in html_lookup.call_args_list],
            [wrong_url, right_url],
        )

    def test_existing_namuwiki_page_without_lyrics_returns_none(self) -> None:
        track = make_namuwiki_track(NAMUWIKI_DOCUMENT)
        page_without_lyrics = """
        <html>
          <body>
            <table>
              <tr><th>원문</th><th>한국어 번역</th></tr>
              <tr>
                <td>Official description for the song and its release.</td>
                <td>
                  이 문서는 곡의 발매 정보와 제작 배경을 설명하는 문서이며
                  실제 가사 내용은 수록되어 있지 않습니다.
                </td>
              </tr>
            </table>
          </body>
        </html>
        """
        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
                return_value=(page_without_lyrics, NAMUWIKI_PAGE_URL),
            ) as html_lookup,
        ):
            result = music_namuwiki.lookup_namuwiki_lyrics(track)

        self.assertIsNone(result)
        html_lookup.assert_called_once_with(NAMUWIKI_PAGE_URL)

    def test_transient_page_failure_is_reported_for_retry(self) -> None:
        track = make_namuwiki_track(NAMUWIKI_DOCUMENT)

        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(music_namuwiki, "NAMUWIKI_API_TOKEN", None),
            patch.object(
                music_namuwiki,
                "get_namuwiki_document_candidates",
                return_value=[NAMUWIKI_DOCUMENT],
            ),
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
                side_effect=music_namuwiki.NamuWikiLyricsError("request blocked"),
            ),
            self.assertRaisesRegex(
                music_namuwiki.NamuWikiLyricsError,
                "configure NAMUWIKI_API_TOKEN",
            ),
        ):
            music_namuwiki.lookup_namuwiki_lyrics(track)

    def test_api_namumark_is_preferred_when_token_is_configured(self) -> None:
        track = make_namuwiki_track(NAMUWIKI_DOCUMENT)
        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_API_TOKEN",
                "test-token",
            ),
            patch.object(
                music_namuwiki,
                "request_namuwiki_api_source",
                return_value=NAMUWIKI_NAMUMARK_FIXTURE,
            ) as api_lookup,
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
            ) as html_lookup,
        ):
            result = music_namuwiki.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], NAMUWIKI_EXPECTED_LYRICS)
        self.assertEqual(result[2], NAMUWIKI_PAGE_URL)
        api_lookup.assert_called_once_with(NAMUWIKI_DOCUMENT)
        html_lookup.assert_not_called()

    def test_api_artist_mismatch_uses_qualified_document(self) -> None:
        track = make_namuwiki_track("Official髭男dism - らしさ [Official Video]")
        track.song_name = "らしさ"
        track.artist = "Official髭男dism"
        right_document = "らしさ(Official髭男dism)"
        wrong_source = (
            "|| 가수 || SUPER BEAVER ||\n" + NAMUWIKI_NAMUMARK_FIXTURE
        )
        right_source = (
            "|| 가수 || Official髭男dism ||\n" + NAMUWIKI_NAMUMARK_FIXTURE
        )

        def request_source(document: str):
            if document == "らしさ":
                return wrong_source
            if document == right_document:
                return right_source
            return None

        with (
            patch.object(music_namuwiki, "NAMUWIKI_LYRICS_ENABLED", True),
            patch.object(
                music_namuwiki,
                "NAMUWIKI_API_TOKEN",
                "test-token",
            ),
            patch.object(
                music_namuwiki,
                "request_namuwiki_api_source",
                side_effect=request_source,
            ) as api_lookup,
            patch.object(
                music_namuwiki,
                "request_namuwiki_html",
            ) as html_lookup,
        ):
            result = music_namuwiki.lookup_namuwiki_lyrics(track)

        self.assertEqual(result[0], NAMUWIKI_EXPECTED_LYRICS)
        self.assertEqual(
            result[2],
            music_namuwiki.split_namuwiki_candidate(right_document)[1],
        )
        self.assertEqual(
            [call.args[0] for call in api_lookup.call_args_list],
            ["らしさ", right_document],
        )
        html_lookup.assert_not_called()
