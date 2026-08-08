import ast
import unittest
from pathlib import Path

import bot
import music_lyrics_display
from music_models import Track


MOVED_NAMES = (
    "LYRICS_INLINE_LIMIT",
    "make_lyrics_embed",
    "make_lyrics_file",
    "make_lyrics_variant_embed",
)


def make_track() -> Track:
    return Track(
        title="Video title",
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
        artist="Artist",
        song_name="Song title",
        lyrics_source="LRCLIB",
    )


class MusicLyricsDisplayTests(unittest.TestCase):
    def test_bot_reexports_moved_lyrics_display_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_lyrics_display, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        source = Path(music_lyrics_display.__file__).read_text(encoding="utf-8")
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
            {"__future__", "discord", "io", "music_models", "music_text"},
        )

    def test_original_and_variant_embeds_preserve_metadata(self) -> None:
        track = make_track()

        original = music_lyrics_display.make_lyrics_embed(track, "original lyrics")
        variant = music_lyrics_display.make_lyrics_variant_embed(
            track,
            "나무위키 가사",
            "variant lyrics",
            "NamuWiki",
            "https://namu.wiki/w/example",
        )

        self.assertEqual(original.title, "가사 · Song title")
        self.assertEqual(original.description, "original lyrics")
        self.assertEqual(original.author.name, "Artist")
        self.assertEqual(original.footer.text, "LRCLIB · 원문 가사")
        self.assertEqual(variant.title, "나무위키 가사 · Song title")
        self.assertEqual(variant.description, "variant lyrics")
        self.assertEqual(variant.url, "https://namu.wiki/w/example")
        self.assertEqual(variant.footer.text, "NamuWiki")

    def test_lyrics_file_contains_full_utf8_text(self) -> None:
        lyrics = "첫 줄\n第二行"
        attachment = music_lyrics_display.make_lyrics_file(
            lyrics,
            "translated-lyrics.txt",
        )
        try:
            self.assertEqual(attachment.filename, "translated-lyrics.txt")
            self.assertEqual(attachment.fp.read(), lyrics.encode("utf-8"))
        finally:
            attachment.close()
