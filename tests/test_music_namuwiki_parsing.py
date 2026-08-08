import ast
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import bot
import music_namuwiki_parsing


MOVED_NAMES = (
    "NamuWikiLyricsError",
    "NamuWikiPageBlockedError",
    "extract_namuwiki_lyrics_from_html",
    "extract_namuwiki_lyrics_from_namumark",
    "parse_namuwiki_html_tables",
)


class MusicNamuWikiParsingTests(unittest.TestCase):
    def test_bot_reexports_moved_parsing_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_parsing, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_parsing.__file__).read_text(
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
                "dataclasses",
                "html",
                "html.parser",
                "music_japanese_reading",
                "music_models",
                "re",
                "typing",
            },
        )

    def test_page_blocked_error_preserves_inheritance(self) -> None:
        self.assertTrue(
            issubclass(
                music_namuwiki_parsing.NamuWikiPageBlockedError,
                music_namuwiki_parsing.NamuWikiLyricsError,
            )
        )

    def test_html_parser_errors_are_wrapped(self) -> None:
        parser = MagicMock()
        parser.feed.side_effect = ValueError("broken table")
        with (
            patch.object(
                music_namuwiki_parsing,
                "NamuWikiHTMLTableParser",
                return_value=parser,
            ),
            self.assertRaisesRegex(
                music_namuwiki_parsing.NamuWikiLyricsError,
                "Could not parse NamuWiki HTML: broken table",
            ),
        ):
            music_namuwiki_parsing.parse_namuwiki_html_tables("<table>")

    def test_html_and_namumark_wrappers_feed_tables_to_selector(self) -> None:
        html_tables = [[[]]]
        namumark_tables = [[["cell"]]]
        with (
            patch.object(
                music_namuwiki_parsing,
                "parse_namuwiki_html_tables",
                return_value=html_tables,
            ),
            patch.object(
                music_namuwiki_parsing,
                "parse_namumark_tables",
                return_value=namumark_tables,
            ),
            patch.object(
                music_namuwiki_parsing,
                "extract_namuwiki_lyrics_from_tables",
                side_effect=["html lyrics", "namumark lyrics"],
            ) as select,
        ):
            self.assertEqual(
                music_namuwiki_parsing.extract_namuwiki_lyrics_from_html(
                    "<table>"
                ),
                "html lyrics",
            )
            self.assertEqual(
                music_namuwiki_parsing.extract_namuwiki_lyrics_from_namumark(
                    "|| cell ||"
                ),
                "namumark lyrics",
            )

        self.assertEqual(
            [call.args[0] for call in select.call_args_list],
            [html_tables, namumark_tables],
        )
