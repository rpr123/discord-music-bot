from __future__ import annotations

import re

from music_models import Track


JAPANESE_KANA_RE = re.compile(r"[\u3041-\u309f\u30a0-\u30ff]")
JAPANESE_HAN_RE = re.compile(
    r"[\u3005\u3007\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")


def lyrics_are_japanese(track: Track, lyrics: str) -> bool:
    language = (track.subtitle_language or "").lower()
    if language == "ja" or language.startswith("ja-"):
        return True
    return bool(JAPANESE_KANA_RE.search(lyrics) or JAPANESE_KANA_RE.search(track.title))


def lyrics_are_primarily_korean(lyrics: str) -> bool:
    letters = [character for character in lyrics if character.isalpha()]
    if not letters:
        return False
    hangul_characters = sum(bool(HANGUL_RE.fullmatch(character)) for character in letters)
    return hangul_characters / len(letters) >= 0.5
