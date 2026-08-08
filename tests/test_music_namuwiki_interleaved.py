import unittest

import bot
import music_namuwiki_parsing as music_namuwiki_interleaved


MOVED_NAMES = (
    "extract_interleaved_namuwiki_groups",
    "extract_interleaved_namuwiki_lyrics",
    "normalize_namuwiki_table_text",
)


class MusicNamuWikiInterleavedTests(unittest.TestCase):
    def test_bot_reexports_moved_interleaved_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_interleaved, name),
                )

    def test_table_text_normalization_preserves_single_blank_separators(self) -> None:
        value = " A&nbsp; B\r\n\r\n\u200b\r\n C\tD \n\n"
        self.assertEqual(
            music_namuwiki_interleaved.normalize_namuwiki_table_text(value),
            "A B\n\nC D",
        )

    def test_interleaved_groups_and_lyrics_preserve_complete_triplets(self) -> None:
        rows = [
            ["君の声\n키미노 코에\n너의 목소리"],
            ["空へ\n소라에\n하늘로 간다"],
            ["夢を見る\n유메오 미루\n꿈을 꾸고 있어"],
        ]
        table_text = "\n".join(row[0] for row in rows)

        groups, translations, source_count = (
            music_namuwiki_interleaved.extract_interleaved_namuwiki_groups(
                table_text
            )
        )

        self.assertEqual(source_count, 3)
        self.assertEqual(
            groups,
            [
                "君の声\n키미노 코에\n너의 목소리",
                "空へ\n소라에\n하늘로 간다",
                "夢を見る\n유메오 미루\n꿈을 꾸고 있어",
            ],
        )
        self.assertEqual(translations, ["너의 목소리", "하늘로 간다", "꿈을 꾸고 있어"])
        self.assertEqual(
            music_namuwiki_interleaved.extract_interleaved_namuwiki_lyrics(rows),
            "\n\n".join(groups),
        )

    def test_incomplete_interleaved_groups_are_rejected(self) -> None:
        rows = [
            ["君の声\n너의 목소리"],
            ["空へ\n하늘로"],
            ["夢を見る\n꿈을 꿔"],
        ]
        self.assertIsNone(
            music_namuwiki_interleaved.extract_interleaved_namuwiki_lyrics(rows)
        )
