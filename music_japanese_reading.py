from __future__ import annotations

import functools
import re
import threading
import unicodedata

from music_models import Track

try:
    from sudachipy import dictionary as sudachi_dictionary
except ImportError:
    sudachi_dictionary = None


JAPANESE_KANA_RE = re.compile(r"[\u3041-\u309f\u30a0-\u30ff]")
JAPANESE_HAN_RE = re.compile(
    r"[\u3005\u3007\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
JAPANESE_READING_RE = re.compile(
    r"^[\u3041-\u309f\u30a0-\u30ff\u30fc\u3005\u30fb\uff65\s]+$"
)
EXPLICIT_READING_BRACKETS = (
    ("(", ")"),
    ("（", "）"),
    ("[", "]"),
    ("［", "］"),
    ("{", "}"),
    ("｛", "｝"),
    ("〈", "〉"),
    ("《", "》"),
    ("【", "】"),
    ("〔", "〕"),
)


class LyricsReadingError(RuntimeError):
    pass


SUDACHI_TOKENIZER = None
SUDACHI_TOKENIZER_LOCK = threading.Lock()


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


def find_explicit_reading_base_start(prefix: str, tokenizer) -> int | None:
    marker_index = max(prefix.rfind("|"), prefix.rfind("｜"))
    if marker_index >= 0:
        marked_base = prefix[marker_index + 1 :]
        if marked_base and JAPANESE_HAN_RE.search(marked_base):
            return marker_index

    if not prefix or not JAPANESE_HAN_RE.fullmatch(prefix[-1]):
        return None

    tokens = list(tokenizer.tokenize(prefix))
    token_positions: list[tuple[int, int, str]] = []
    position = 0
    for token in tokens:
        surface = token.surface()
        start = position
        position += len(surface)
        token_positions.append((start, position, surface))

    suffix_start = len(prefix)
    for start, end, surface in reversed(token_positions[-4:]):
        if end != suffix_start or not surface:
            break
        if surface.isspace() or all(
            unicodedata.category(character).startswith("P") for character in surface
        ):
            break
        suffix_start = start
        if JAPANESE_HAN_RE.search(surface):
            return suffix_start

    fallback = re.search(
        (
            r"[\u3005\u3007\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+"
            r"[\u3041-\u309f\u30a0-\u30ff\u30fc]{0,12}$"
        ),
        prefix,
    )
    return fallback.start() if fallback else None


def find_explicit_reading_replacements(
    line: str,
    tokenizer,
) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    for opening, closing in EXPLICIT_READING_BRACKETS:
        pattern = re.compile(
            re.escape(opening)
            + r"(?P<reading>[^"
            + re.escape(closing)
            + r"]+)"
            + re.escape(closing)
        )
        for match in pattern.finditer(line):
            reading = match.group("reading").strip()
            if reading and JAPANESE_READING_RE.fullmatch(reading):
                matches.append((match.start(), match.end(), reading))

    replacements: list[tuple[int, int, str]] = []
    cursor = 0
    for opening_start, annotation_end, reading in sorted(matches):
        if opening_start < cursor:
            continue
        prefix = line[cursor:opening_start]
        base_start = find_explicit_reading_base_start(prefix, tokenizer)
        if base_start is None:
            continue

        absolute_base_start = cursor + base_start
        base = line[absolute_base_start:opening_start]
        if base.startswith(("|", "｜")):
            base = base[1:]
        replacements.append(
            (
                absolute_base_start,
                annotation_end,
                f"{base}({normalize_japanese_reading(reading).strip()})",
            )
        )
        cursor = annotation_end
    return replacements


def replace_explicit_readings(line: str, tokenizer) -> str:
    replacements = find_explicit_reading_replacements(line, tokenizer)
    if not replacements:
        return line

    output: list[str] = []
    cursor = 0
    for start, end, replacement in replacements:
        output.append(line[cursor:start])
        output.append(replacement)
        cursor = end
    output.append(line[cursor:])
    return "".join(output)


def protect_explicit_readings(
    line: str,
    tokenizer,
) -> tuple[str, dict[str, str]]:
    replacements = find_explicit_reading_replacements(line, tokenizer)
    if not replacements:
        return line, {}

    output: list[str] = []
    protected: dict[str, str] = {}
    cursor = 0
    placeholder_codepoint = 0xE000
    for start, end, replacement in replacements:
        while chr(placeholder_codepoint) in line:
            placeholder_codepoint += 1
        placeholder = chr(placeholder_codepoint)
        placeholder_codepoint += 1
        output.append(line[cursor:start])
        output.append(placeholder)
        protected[placeholder] = replacement
        cursor = end
    output.append(line[cursor:])
    return "".join(output), protected


def get_sudachi_tokenizer():
    global SUDACHI_TOKENIZER
    if sudachi_dictionary is None:
        raise LyricsReadingError(
            "SudachiPy and SudachiDict-core are not installed."
        )
    if SUDACHI_TOKENIZER is None:
        SUDACHI_TOKENIZER = sudachi_dictionary.Dictionary().create()
    return SUDACHI_TOKENIZER


def annotate_token_reading(surface: str, reading: str) -> str:
    if (
        not reading
        or re.search(r"[A-Za-z]", surface)
        or not JAPANESE_HAN_RE.search(surface)
        or surface.isspace()
        or all(
            unicodedata.category(character).startswith(("P", "S"))
            for character in surface
        )
    ):
        return surface
    return annotate_japanese_reading(surface, reading)


def generate_hiragana_lyrics(lyrics: str) -> str:
    with SUDACHI_TOKENIZER_LOCK:
        tokenizer = get_sudachi_tokenizer()
        converted_lines: list[str] = []
        for line in lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line, protected_readings = protect_explicit_readings(line, tokenizer)
            converted_tokens: list[str] = []
            for token in tokenizer.tokenize(line):
                surface = token.surface()
                reading = token.reading_form()
                converted_tokens.append(annotate_token_reading(surface, reading))
            converted_line = "".join(converted_tokens)
            for placeholder, replacement in protected_readings.items():
                converted_line = converted_line.replace(placeholder, replacement)
            converted_lines.append(converted_line)
    reading_text = "\n".join(converted_lines).strip()
    if not reading_text:
        raise LyricsReadingError("Sudachi returned empty reading text.")
    return reading_text
