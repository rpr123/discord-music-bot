import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_namuwiki_matching as music_namuwiki_candidates
from music_models import Track


def make_track(title: str = "Song") -> Track:
    return Track(
        title=title,
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
    )


class MusicNamuWikiCandidatesTests(unittest.TestCase):
    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_namuwiki_candidates.__file__).read_text(
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
                "music_lyrics_matching",
                "music_models",
                "music_namuwiki_parsing",
                "music_search_scoring",
                "music_track_identity",
                "re",
                "unicodedata",
                "urllib.parse",
            },
        )

    def test_bot_override_wrapper_reads_current_setting(self) -> None:
        track = make_track()
        with patch.object(
            bot,
            "NAMUWIKI_DOCUMENT_OVERRIDES",
            {"video:abcdefghijk": "Configured document"},
        ):
            self.assertEqual(
                bot.get_namuwiki_override(track),
                "Configured document",
            )

    def test_document_wrapper_preserves_override_patch_and_limit(self) -> None:
        track = make_track("Artist - Song (Official Video)")
        with (
            patch.object(
                bot,
                "get_namuwiki_override",
                return_value="Patched document",
            ),
            patch.object(bot, "NAMUWIKI_MAX_DOCUMENT_CANDIDATES", 1),
        ):
            self.assertEqual(
                bot.get_namuwiki_document_candidates(track),
                ["Patched document"],
            )

    def test_split_wrapper_reads_current_base_url(self) -> None:
        with patch.object(
            bot,
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
        document, page_url = music_namuwiki_candidates.parse_namuwiki_candidate(
            "https://namu.wiki/w/문서?from=old#section",
            "https://unused.test/w",
        )
        self.assertEqual(document, "문서")
        self.assertEqual(
            page_url,
            "https://namu.wiki/w/%EB%AC%B8%EC%84%9C",
        )
        with self.assertRaises(bot.NamuWikiLyricsError):
            music_namuwiki_candidates.parse_namuwiki_candidate(
                "ftp://namu.wiki/w/document",
                "https://namu.wiki/w",
            )
