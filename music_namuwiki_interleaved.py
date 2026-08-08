from __future__ import annotations

import html
import re

from music_namuwiki_validation import is_valid_korean_translation
from music_script_detection import HANGUL_RE, JAPANESE_HAN_RE, JAPANESE_KANA_RE


def normalize_namuwiki_table_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    normalized_lines: list[str] = []
    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if line:
            normalized_lines.append(line)
        elif normalized_lines and normalized_lines[-1]:
            normalized_lines.append("")
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    return "\n".join(normalized_lines).strip()


def extract_interleaved_namuwiki_groups(
    value: str,
) -> tuple[list[str], list[str], int]:
    groups: list[str] = []
    translated_lines: list[str] = []
    source_line_count = 0
    current_source: str | None = None
    current_hangul_lines: list[str] | None = None

    def finish_group() -> None:
        if (
            current_source
            and current_hangul_lines
            and len(current_hangul_lines) >= 2
        ):
            groups.append(
                "\n".join((current_source, *current_hangul_lines))
            )
            translated_lines.append(current_hangul_lines[-1])

    for line in normalize_namuwiki_table_text(value).splitlines():
        has_hangul = bool(HANGUL_RE.search(line))
        has_japanese = bool(
            JAPANESE_KANA_RE.search(line) or JAPANESE_HAN_RE.search(line)
        )
        latin_letter_count = sum(
            character.isascii() and character.isalpha()
            for character in line
        )
        if not has_hangul and (has_japanese or latin_letter_count >= 2):
            finish_group()
            source_line_count += 1
            current_source = line
            current_hangul_lines = []
        elif current_hangul_lines is not None and has_hangul:
            current_hangul_lines.append(line)

    finish_group()
    return groups, translated_lines, source_line_count


def extract_interleaved_namuwiki_lyrics(
    rows: list[list[str]],
) -> str | None:
    table_text = "\n".join(
        cell
        for row in rows
        for cell in row
    )
    (
        groups,
        translated_lines,
        source_line_count,
    ) = extract_interleaved_namuwiki_groups(table_text)

    translation = "\n".join(translated_lines).strip()
    if (
        source_line_count < 3
        or len(groups) < 3
        or not is_valid_korean_translation(translation)
    ):
        return None
    return "\n\n".join(groups)
