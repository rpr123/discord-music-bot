import unittest

import bot
import music_namuwiki_parsing as music_namuwiki_table_lyrics


class MusicNamuWikiTableLyricsTests(unittest.TestCase):
    def test_bot_reexports_table_lyrics_selector(self) -> None:
        self.assertIs(
            bot.extract_namuwiki_lyrics_from_tables,
            music_namuwiki_table_lyrics.extract_namuwiki_lyrics_from_tables,
        )

    def test_header_table_preserves_source_reading_and_translation(self) -> None:
        tables = [[
            ["일본어 원문", "일본어 독음", "한국어 번역"],
            ["泥濘 鳴鳴", "でいねい めいめい", "진창에서 울리는 노랫소리"],
            ["礼を持って", "れいをもって", "예를 갖추어 다시 걸어가"],
        ]]
        self.assertEqual(
            music_namuwiki_table_lyrics.extract_namuwiki_lyrics_from_tables(
                tables
            ),
            (
                "泥濘 鳴鳴\nでいねい めいめい\n진창에서 울리는 노랫소리\n\n"
                "礼を持って\nれいをもって\n예를 갖추어 다시 걸어가"
            ),
        )

    def test_best_candidate_prefers_more_korean_lyrics(self) -> None:
        short_table = [
            ["원문", "한국어 번역"],
            ["First line", "짧지만 충분한 첫 번째 가사 문장입니다"],
            ["Second line", "두 번째 가사 문장입니다"],
        ]
        long_table = [
            ["원문", "한국어 번역"],
            ["First line", "더 많은 한글을 포함하는 긴 가사 문장입니다"],
            ["Second line", "이 후보가 최종 결과로 선택되어야 합니다"],
        ]
        result = music_namuwiki_table_lyrics.extract_namuwiki_lyrics_from_tables(
            [short_table, long_table]
        )
        self.assertIn("최종 결과로 선택", result or "")

    def test_short_metadata_table_is_rejected(self) -> None:
        tables = [[["원문", "한국어 번역"], ["Title", "설명"]]]
        self.assertIsNone(
            music_namuwiki_table_lyrics.extract_namuwiki_lyrics_from_tables(
                tables
            )
        )
