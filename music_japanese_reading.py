from __future__ import annotations

import functools
import re
import unicodedata

from music_script_detection import JAPANESE_HAN_RE, JAPANESE_KANA_RE


JAPANESE_READING_RE = re.compile(
    r"^[\u3041-\u309f\u30a0-\u30ff\u30fc\u3005\u30fb\uff65\s]+$"
)


def katakana_to_hiragana(value: str) -> str:
    converted: list[str] = []
    for character in value:
        codepoint = ord(character)
        if 0x30A1 <= codepoint <= 0x30F6:
            converted.append(chr(codepoint - 0x60))
        else:
            converted.append(character)
    return "".join(converted)


def normalize_japanese_reading(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = katakana_to_hiragana(normalized)
    return re.sub(r"\s+", " ", normalized)


def get_reading_surface_segment_kind(character: str) -> str:
    if JAPANESE_HAN_RE.fullmatch(character):
        return "han"
    if JAPANESE_KANA_RE.fullmatch(character) or character == "ー":
        return "anchor"
    if character.isspace():
        return "space"

    normalized = unicodedata.normalize("NFKC", character)
    if normalized and all(
        item.isascii() and item.isalnum() for item in normalized
    ):
        return "anchor"
    return "optional"


def split_reading_surface(surface: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    for character in surface:
        kind = get_reading_surface_segment_kind(character)
        if segments and segments[-1][0] == kind:
            previous_kind, previous_text = segments[-1]
            segments[-1] = (previous_kind, previous_text + character)
        else:
            segments.append((kind, character))
    return segments


def annotate_japanese_reading(surface: str, reading: str) -> str:
    if not surface or not JAPANESE_HAN_RE.search(surface):
        return surface

    normalized_reading = normalize_japanese_reading(reading).strip()
    if (
        not normalized_reading
        or not JAPANESE_KANA_RE.search(normalized_reading)
    ):
        return surface

    segments = split_reading_surface(surface)

    @functools.lru_cache(maxsize=None)
    def align(segment_index: int, reading_index: int) -> tuple[str, ...] | None:
        if segment_index == len(segments):
            return () if reading_index == len(normalized_reading) else None

        kind, text = segments[segment_index]
        if kind == "han":
            remaining_han_segments = sum(
                future_kind == "han"
                for future_kind, _ in segments[segment_index + 1 :]
            )
            last_reading_index = len(normalized_reading) - remaining_han_segments
            for end in range(reading_index + 1, last_reading_index + 1):
                candidate = normalized_reading[reading_index:end]
                if (
                    any(character.isspace() for character in candidate)
                    or not JAPANESE_READING_RE.fullmatch(candidate)
                    or not JAPANESE_KANA_RE.search(candidate)
                ):
                    continue
                remainder = align(segment_index + 1, end)
                if remainder is not None:
                    return (f"{text}({candidate})", *remainder)
            return None

        normalized_text = normalize_japanese_reading(text)
        matching_end = reading_index + len(normalized_text)
        if normalized_reading.startswith(normalized_text, reading_index):
            remainder = align(segment_index + 1, matching_end)
            if remainder is not None:
                return (text, *remainder)

        if kind in {"optional", "space"}:
            remainder = align(segment_index + 1, reading_index)
            if remainder is not None:
                return (text, *remainder)
        return None

    aligned = align(0, 0)
    if aligned is not None:
        return "".join(aligned)
    if JAPANESE_READING_RE.fullmatch(normalized_reading):
        return f"{surface}({normalized_reading})"
    return surface
