from __future__ import annotations

import re

from music_japanese_reading import annotate_japanese_reading
from music_models import Track
from music_script_detection import (
    HANGUL_RE,
    JAPANESE_HAN_RE,
    JAPANESE_KANA_RE,
    lyrics_are_japanese,
)


def split_namuwiki_lyrics_groups(value: str) -> list[list[str]]:
    return [
        [line.strip() for line in group.splitlines() if line.strip()]
        for group in re.split(r"\n\s*\n", value)
        if group.strip()
    ]


def extract_namuwiki_original_lyrics(value: str) -> str | None:
    source_lines = [
        lines[0]
        for lines in split_namuwiki_lyrics_groups(value)
        if len(lines) >= 2
        and (
            JAPANESE_KANA_RE.search(lines[0])
            or JAPANESE_HAN_RE.search(lines[0])
        )
    ]
    return "\n".join(source_lines) if source_lines else None


def extract_namuwiki_annotated_reading(value: str) -> str | None:
    groups = split_namuwiki_lyrics_groups(value)
    japanese_groups = [
        lines
        for lines in groups
        if len(lines) >= 3
        and (
            JAPANESE_KANA_RE.search(lines[0])
            or JAPANESE_HAN_RE.search(lines[0])
        )
    ]
    if not japanese_groups:
        return None

    readings: list[str] = []
    for lines in japanese_groups:
        reading = next(
            (
                line
                for line in lines[1:-1]
                if JAPANESE_KANA_RE.search(line) and not HANGUL_RE.search(line)
            ),
            None,
        )
        if reading is None:
            return None
        readings.append(annotate_japanese_reading(lines[0], reading))
    return "\n".join(readings)


def get_hiragana_reading_source_lyrics(track: Track, lyrics: str) -> str | None:
    if lyrics.strip() and lyrics_are_japanese(track, lyrics):
        return lyrics
    if track.korean_lyrics and track.korean_lyrics_url:
        return extract_namuwiki_original_lyrics(track.korean_lyrics)
    return None
