from __future__ import annotations

import re

from music_script_detection import HANGUL_RE


def is_valid_korean_translation(value: str) -> bool:
    hangul_count = sum(
        bool(HANGUL_RE.fullmatch(character))
        for character in value
    )
    nonempty_lines = [line for line in value.splitlines() if line.strip()]
    return hangul_count >= 8 and (
        len(nonempty_lines) >= 2 or len(value) >= 30
    )


def is_usable_namuwiki_lyrics(value: str) -> bool:
    groups = [
        group.strip()
        for group in re.split(r"\n\s*\n", value)
        if group.strip()
    ]
    nonempty_lines = [
        line.strip()
        for group in groups
        for line in group.splitlines()
        if line.strip()
    ]
    if len(groups) < 2 and len(nonempty_lines) < 6:
        return False

    foreign_letter_count = sum(
        character.isalpha() and not HANGUL_RE.fullmatch(character)
        for character in value
    )
    return foreign_letter_count >= 2 and is_valid_korean_translation(value)
