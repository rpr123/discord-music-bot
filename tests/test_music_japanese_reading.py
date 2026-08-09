import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import bot
import music_japanese_reading
from music_models import Track


SCRIPT_DETECTION_MOVED_NAMES = (
    "HANGUL_RE",
    "JAPANESE_HAN_RE",
    "JAPANESE_KANA_RE",
    "lyrics_are_japanese",
    "lyrics_are_primarily_korean",
)
JAPANESE_READING_MOVED_NAMES = (
    "JAPANESE_READING_RE",
    "annotate_japanese_reading",
    "get_reading_surface_segment_kind",
    "katakana_to_hiragana",
    "normalize_japanese_reading",
    "split_reading_surface",
)
EXPLICIT_READING_MOVED_NAMES = (
    "EXPLICIT_READING_BRACKETS",
    "find_explicit_reading_base_start",
    "find_explicit_reading_replacements",
    "protect_explicit_readings",
    "replace_explicit_readings",
)
SUDACHI_READING_MOVED_NAMES = (
    "LyricsReadingError",
    "SUDACHI_TOKENIZER_LOCK",
    "annotate_token_reading",
    "generate_hiragana_lyrics",
    "get_sudachi_tokenizer",
    "sudachi_dictionary",
)
EXPECTED_IMPORTS = {
    "__future__",
    "functools",
    "music_models",
    "re",
    "sudachipy",
    "threading",
    "unicodedata",
}


def get_imported_modules() -> set[str]:
    source = Path(music_japanese_reading.__file__).read_text(encoding="utf-8")
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
    return imported_modules


def make_track(title: str = "Song") -> Track:
    return Track(
        title=title,
        webpage_url="https://www.youtube.com/watch?v=abcdefghijk",
        requester="tester",
        source_url="https://www.youtube.com/watch?v=abcdefghijk",
    )


class MusicScriptDetectionTests(unittest.TestCase):
    def test_bot_reexports_moved_script_detection_names(self) -> None:
        for name in SCRIPT_DETECTION_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_japanese_reading, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        self.assertEqual(get_imported_modules(), EXPECTED_IMPORTS)

    def test_japanese_detection_uses_subtitle_language_lyrics_and_title(self) -> None:
        language_track = make_track()
        language_track.subtitle_language = "ja-JP"
        self.assertTrue(
            music_japanese_reading.lyrics_are_japanese(language_track, "English")
        )

        self.assertTrue(
            music_japanese_reading.lyrics_are_japanese(
                make_track(),
                "きみの声が聞こえる",
            )
        )
        self.assertTrue(
            music_japanese_reading.lyrics_are_japanese(
                make_track("カタカナ Song"),
                "English",
            )
        )
        self.assertFalse(
            music_japanese_reading.lyrics_are_japanese(make_track(), "English")
        )

    def test_korean_detection_uses_letter_ratio_and_handles_empty_text(self) -> None:
        self.assertTrue(music_japanese_reading.lyrics_are_primarily_korean("가a"))
        self.assertFalse(music_japanese_reading.lyrics_are_primarily_korean("가ab"))
        self.assertFalse(music_japanese_reading.lyrics_are_primarily_korean("123 !"))


class MusicJapaneseReadingTests(unittest.TestCase):
    def test_bot_reexports_moved_japanese_reading_names(self) -> None:
        for name in JAPANESE_READING_MOVED_NAMES + SUDACHI_READING_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_japanese_reading, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        self.assertEqual(get_imported_modules(), EXPECTED_IMPORTS)

    def test_reading_normalization_converts_katakana_and_whitespace(self) -> None:
        self.assertEqual(
            music_japanese_reading.katakana_to_hiragana("カタカナ"),
            "かたかな",
        )
        self.assertEqual(
            music_japanese_reading.normalize_japanese_reading(
                "カタカナ  \tテスト"
            ),
            "かたかな てすと",
        )

    def test_surface_segmentation_groups_adjacent_character_kinds(self) -> None:
        self.assertEqual(
            music_japanese_reading.split_reading_surface("漢かな ABC!"),
            [
                ("han", "漢"),
                ("anchor", "かな"),
                ("space", " "),
                ("anchor", "ABC"),
                ("optional", "!"),
            ],
        )
        self.assertEqual(
            music_japanese_reading.get_reading_surface_segment_kind("ー"),
            "anchor",
        )

    def test_annotation_aligns_kanji_with_normalized_reading(self) -> None:
        self.assertEqual(
            music_japanese_reading.annotate_japanese_reading("食べる", "タベル"),
            "食(た)べる",
        )
        self.assertEqual(
            music_japanese_reading.annotate_japanese_reading("かな", "カナ"),
            "かな",
        )


class FakeToken:
    def __init__(self, surface: str, reading: str | None = None) -> None:
        self._surface = surface
        self._reading = reading if reading is not None else surface

    def surface(self) -> str:
        return self._surface

    def reading_form(self) -> str:
        return self._reading


class FakeTokenizer:
    def tokenize(self, text: str) -> list[FakeToken]:
        return [FakeToken(text)] if text else []


class MusicJapaneseReadingBotCompatibilityTests(unittest.TestCase):
    def test_generate_hiragana_lyrics_uses_bot_reexported_protect_helper(
        self,
    ) -> None:
        tokenizer = FakeTokenizer()
        with (
            patch.object(
                music_japanese_reading,
                "get_sudachi_tokenizer",
                return_value=tokenizer,
            ),
            patch.object(
                music_japanese_reading,
                "protect_explicit_readings",
                return_value=("protected", {}),
            ) as protect,
        ):
            self.assertEqual(
                music_japanese_reading.generate_hiragana_lyrics("source"),
                "protected",
            )

        protect.assert_called_once_with("source", tokenizer)

    def test_annotate_token_reading_uses_bot_reexported_annotation_helper(
        self,
    ) -> None:
        with patch.object(
            music_japanese_reading,
            "annotate_japanese_reading",
            return_value="patched",
        ) as annotate:
            self.assertEqual(
                music_japanese_reading.annotate_token_reading("漢", "カン"),
                "patched",
            )

        annotate.assert_called_once_with("漢", "カン")


class MusicJapaneseReadingGenerationTests(unittest.TestCase):
    def test_japanese_and_korean_lyrics_are_detected_locally(self) -> None:
        track = make_track("Japanese song")

        self.assertTrue(
            music_japanese_reading.lyrics_are_japanese(track, "君の声が聞こえる")
        )
        self.assertFalse(
            music_japanese_reading.lyrics_are_japanese(
                track,
                "I can hear your voice",
            )
        )
        self.assertTrue(
            music_japanese_reading.lyrics_are_primarily_korean(
                "너의 목소리가 들려"
            )
        )
        self.assertFalse(
            music_japanese_reading.lyrics_are_primarily_korean("君の声が聞こえる")
        )

    def test_explicit_readings_accept_common_bracket_styles(self) -> None:
        tokenizer = FakeTokenizer()
        examples = {
            "運命(さだめ)": "運命(さだめ)",
            "運命（さだめ）": "運命(さだめ)",
            "運命[さだめ]": "運命(さだめ)",
            "運命【さだめ】": "運命(さだめ)",
            "運命《サダメ》": "運命(さだめ)",
            "｜超電磁砲《レールガン》": "超電磁砲(れーるがん)",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(
                    music_japanese_reading.replace_explicit_readings(
                        source,
                        tokenizer,
                    ),
                    expected,
                )

    def test_non_kana_parentheses_are_not_treated_as_a_reading(self) -> None:
        source = "運命(Oh yeah)"

        self.assertEqual(
            music_japanese_reading.replace_explicit_readings(
                source,
                FakeTokenizer(),
            ),
            source,
        )
        self.assertEqual(
            music_japanese_reading.replace_explicit_readings(
                "愛してる(ああ)",
                FakeTokenizer(),
            ),
            "愛してる(ああ)",
        )
        self.assertEqual(
            music_japanese_reading.annotate_token_reading("(", "キゴウ"),
            "(",
        )
        self.assertEqual(
            music_japanese_reading.annotate_token_reading("Oh", "オー"),
            "Oh",
        )

    def test_dictionary_readings_are_added_after_kanji(self) -> None:
        examples = {
            ("運命", "ウンメイ"): "運命(うんめい)",
            ("礼を持って", "レイヲモッテ"): "礼(れい)を持(も)って",
            ("取り戻す", "トリモドス"): "取(と)り戻(もど)す",
            ("かなだけ", "カナダケ"): "かなだけ",
        }

        for (surface, reading), expected in examples.items():
            with self.subTest(surface=surface):
                self.assertEqual(
                    music_japanese_reading.annotate_token_reading(
                        surface,
                        reading,
                    ),
                    expected,
                )

    def test_explicit_reading_overrides_dictionary_reading(self) -> None:
        tokenizer = FakeTokenizer()

        with patch.object(
            music_japanese_reading,
            "get_sudachi_tokenizer",
            return_value=tokenizer,
        ):
            reading = music_japanese_reading.generate_hiragana_lyrics(
                "未来(あした)"
            )

        self.assertEqual(reading, "未来(あした)")


class MusicExplicitReadingsTests(unittest.TestCase):
    def test_bot_reexports_moved_explicit_reading_names(self) -> None:
        for name in EXPLICIT_READING_MOVED_NAMES:
            with self.subTest(name=name):
                self.assertIs(
                    getattr(bot, name),
                    getattr(music_japanese_reading, name),
                )

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        self.assertEqual(get_imported_modules(), EXPECTED_IMPORTS)

    def test_explicit_reading_brackets_are_normalized(self) -> None:
        tokenizer = FakeTokenizer()
        examples = {
            "運命(サダメ)": "運命(さだめ)",
            "運命《さだめ》": "運命(さだめ)",
            "｜運命【さだめ】": "運命(さだめ)",
        }

        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(
                    music_japanese_reading.replace_explicit_readings(
                        source,
                        tokenizer,
                    ),
                    expected,
                )

        self.assertEqual(
            music_japanese_reading.replace_explicit_readings(
                "運命(love)",
                tokenizer,
            ),
            "運命(love)",
        )

    def test_protection_uses_an_unused_private_placeholder(self) -> None:
        tokenizer = FakeTokenizer()
        protected_line, replacements = (
            music_japanese_reading.protect_explicit_readings(
                "運命(さだめ)\ue000",
                tokenizer,
            )
        )

        self.assertEqual(protected_line, "\ue001\ue000")
        self.assertEqual(replacements, {"\ue001": "運命(さだめ)"})
