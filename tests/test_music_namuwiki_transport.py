import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot
import music_namuwiki


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
