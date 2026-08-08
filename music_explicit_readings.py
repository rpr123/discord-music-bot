from __future__ import annotations

import re
import unicodedata

from music_japanese_reading import JAPANESE_READING_RE, normalize_japanese_reading
from music_script_detection import JAPANESE_HAN_RE


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
