import unittest

import bot
import music_namuwiki_parsing as music_namuwiki_readings
from music_models import Track


MOVED_NAMES = (
    "extract_namuwiki_annotated_reading",
    "extract_namuwiki_original_lyrics",
    "get_hiragana_reading_source_lyrics",
    "split_namuwiki_lyrics_groups",
)


def make_track() -> Track:
    return Track(
        title="Song",
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
    )


class MusicNamuWikiReadingTests(unittest.TestCase):
    def test_bot_reexports_moved_namuwiki_reading_names(self) -> None:
        for name in MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_namuwiki_readings, name),
                )

    def test_groups_original_lyrics_and_annotated_reading_are_extracted(self) -> None:
        lyrics = (
            "君の声\n"
            "きみのこえ\n"
            "너의 목소리\n\n"
            "空へ\n"
            "そらへ\n"
            "하늘로"
        )

        self.assertEqual(
            music_namuwiki_readings.split_namuwiki_lyrics_groups(lyrics),
            [
                ["君の声", "きみのこえ", "너의 목소리"],
                ["空へ", "そらへ", "하늘로"],
            ],
        )
        self.assertEqual(
            music_namuwiki_readings.extract_namuwiki_original_lyrics(lyrics),
            "君の声\n空へ",
        )
        self.assertEqual(
            music_namuwiki_readings.extract_namuwiki_annotated_reading(lyrics),
            "君(きみ)の声(こえ)\n空(そら)へ",
        )

    def test_incomplete_groups_do_not_produce_annotated_reading(self) -> None:
        self.assertIsNone(
            music_namuwiki_readings.extract_namuwiki_annotated_reading(
                "君の声\n너의 목소리"
            )
        )

    def test_source_prefers_japanese_lyrics_then_namuwiki_original(self) -> None:
        track = make_track()
        track.subtitle_language = "ja"
        self.assertEqual(
            music_namuwiki_readings.get_hiragana_reading_source_lyrics(
                track,
                "直接の歌詞",
            ),
            "直接の歌詞",
        )

        track.subtitle_language = None
        track.korean_lyrics = "君の声\nきみのこえ\n너의 목소리"
        track.korean_lyrics_url = "https://namu.wiki/w/example"
        self.assertEqual(
            music_namuwiki_readings.get_hiragana_reading_source_lyrics(
                track,
                "English lyrics",
            ),
            "君の声",
        )

        track.korean_lyrics_url = None
        self.assertIsNone(
            music_namuwiki_readings.get_hiragana_reading_source_lyrics(
                track,
                "English lyrics",
            )
        )
