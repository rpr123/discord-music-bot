from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

from music_japanese_reading import (
    HANGUL_RE,
    JAPANESE_HAN_RE,
    JAPANESE_KANA_RE,
    annotate_japanese_reading,
    lyrics_are_japanese,
)
from music_models import Track


NAMUMARK_STYLE_PREFIX_RE = re.compile(r"^(?:\s*<[^>\n]*>)+")
NAMUMARK_RUBY_RE = re.compile(
    r"\[ruby\((?P<base>.*?),\s*ruby=.*?\)\]",
    flags=re.IGNORECASE,
)
NAMUMARK_LINK_RE = re.compile(r"\[\[(?P<value>[^\]]+)\]\]")
NAMUMARK_FOOTNOTE_RE = re.compile(r"\[\*(?:[^\]]*)\]")
NAMUWIKI_IGNORED_HTML_TAGS = frozenset(
    {"button", "noscript", "script", "style", "sup", "svg"}
)
NAMUWIKI_VOID_HTML_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
)


class NamuWikiLyricsError(RuntimeError):
    pass


class NamuWikiPageBlockedError(NamuWikiLyricsError):
    pass


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


def namuwiki_translation_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "한국어번역" in key:
        return 100
    if "한국어해석" in key:
        return 95
    if "한국어가사" in key:
        return 90
    if key in {"번역", "해석", "한국어"}:
        return 70
    return 0


def namuwiki_source_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "일본어원문" in key or "원어원문" in key:
        return 100
    if key == "원문":
        return 90
    if key in {"일본어", "일어", "원어"}:
        return 70
    return 0


def namuwiki_reading_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if any(
        marker in key
        for marker in ("일본어독음", "한글독음", "한국어독음")
    ):
        return 100
    if "독음" in key:
        return 90
    if key in {"발음", "요미가나", "읽는법"}:
        return 70
    return 0


def best_namuwiki_header_column(
    row: list[str],
    scorer: Callable[[str], int],
    excluded: set[int],
) -> int | None:
    candidates = [
        (scorer(header), column_index)
        for column_index, header in enumerate(row)
        if column_index not in excluded and scorer(header) > 0
    ]
    return max(candidates)[1] if candidates else None


def clean_namumark_cell(value: str) -> str:
    value = NAMUMARK_STYLE_PREFIX_RE.sub("", value.strip())
    value = re.sub(r"\[br\]", "\n", value, flags=re.IGNORECASE)
    value = NAMUMARK_RUBY_RE.sub(lambda match: match.group("base"), value)
    value = NAMUMARK_FOOTNOTE_RE.sub("", value)
    value = NAMUMARK_LINK_RE.sub(
        lambda match: match.group("value").split("|", 1)[-1],
        value,
    )
    value = re.sub(r"\[(?:clearfix|목차)\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\{\{\{(?:#!wiki[^\n]*|#[^\s}]+\s*)?", "", value)
    value = value.replace("{{{", "").replace("}}}", "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("'''", "").replace("''", "")
    return normalize_namuwiki_table_text(value)


def parse_namumark_tables(source: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []
    pending_row_lines: list[str] = []

    def finish_table() -> None:
        nonlocal current_table
        if current_table:
            tables.append(current_table)
            current_table = []

    def finish_row() -> None:
        nonlocal pending_row_lines
        row_source = "\n".join(pending_row_lines).strip()
        pending_row_lines = []
        if not row_source.startswith("||"):
            return
        row_source = row_source[2:]
        if row_source.endswith("||"):
            row_source = row_source[:-2]
        cells = [
            clean_namumark_cell(cell)
            for cell in re.split(r"\s*\|\|\s*", row_source)
        ]
        if any(cells):
            current_table.append(cells)

    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized_source.split("\n"):
        line = raw_line.strip()
        if pending_row_lines:
            pending_row_lines.append(raw_line)
            if line.endswith("||"):
                finish_row()
            continue

        if line.startswith("||"):
            pending_row_lines = [line]
            if line.endswith("||") and len(line) > 2:
                finish_row()
            continue

        finish_table()

    if pending_row_lines:
        finish_row()
    finish_table()
    return tables


@dataclass
class _NamuWikiHTMLTableContext:
    rows: list[list[str]] = field(default_factory=list)
    row: list[str] | None = None
    cell_fragments: list[str] | None = None
    cell_colspan: int = 1


class NamuWikiHTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[_NamuWikiHTMLTableContext] = []
        self._ignored_tags: list[str] = []

    def _current_context(self) -> _NamuWikiHTMLTableContext | None:
        return self._table_stack[-1] if self._table_stack else None

    def _append_cell_fragment(self, value: str) -> None:
        context = self._current_context()
        if context is not None and context.cell_fragments is not None:
            context.cell_fragments.append(value)

    def _append_cell_break(self) -> None:
        context = self._current_context()
        if context is None or context.cell_fragments is None:
            return
        if context.cell_fragments and context.cell_fragments[-1].endswith("\n"):
            return
        context.cell_fragments.append("\n")

    def _finish_cell(self, context: _NamuWikiHTMLTableContext) -> None:
        if context.cell_fragments is None:
            return
        if context.row is None:
            context.row = []
        text = normalize_namuwiki_table_text("".join(context.cell_fragments))
        context.row.append(text)
        context.row.extend("" for _ in range(max(1, context.cell_colspan) - 1))
        context.cell_fragments = None
        context.cell_colspan = 1

    def _finish_row(self, context: _NamuWikiHTMLTableContext) -> None:
        self._finish_cell(context)
        if context.row is not None and any(cell for cell in context.row):
            context.rows.append(context.row)
        context.row = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        if self._ignored_tags:
            if tag not in NAMUWIKI_VOID_HTML_TAGS:
                self._ignored_tags.append(tag)
            return
        if tag in NAMUWIKI_IGNORED_HTML_TAGS:
            self._ignored_tags.append(tag)
            return

        if tag == "table":
            self._table_stack.append(_NamuWikiHTMLTableContext())
            return

        context = self._current_context()
        if context is None:
            return
        if tag == "tr":
            self._finish_row(context)
            context.row = []
        elif tag in {"td", "th"}:
            self._finish_cell(context)
            context.cell_fragments = []
            attributes = dict(attrs)
            try:
                context.cell_colspan = max(1, int(attributes.get("colspan") or "1"))
            except ValueError:
                context.cell_colspan = 1
        elif tag == "br":
            self._append_cell_break()
        elif tag == "img":
            alt_text = dict(attrs).get("alt")
            if alt_text and not alt_text.startswith("파일:"):
                self._append_cell_fragment(alt_text)
        elif tag in {"div", "li", "p"}:
            self._append_cell_break()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in NAMUWIKI_IGNORED_HTML_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in NAMUWIKI_VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._ignored_tags:
            if tag == self._ignored_tags[-1]:
                self._ignored_tags.pop()
            return

        context = self._current_context()
        if context is None:
            return
        if tag in {"td", "th"}:
            self._finish_cell(context)
        elif tag == "tr":
            self._finish_row(context)
        elif tag == "table":
            self._finish_row(context)
            completed = self._table_stack.pop()
            if completed.rows:
                self.tables.append(completed.rows)
        elif tag in {"div", "li", "p"}:
            self._append_cell_break()

    def handle_data(self, data: str) -> None:
        if not self._ignored_tags:
            self._append_cell_fragment(data)


def extract_namuwiki_lyrics_from_tables(
    tables: list[list[list[str]]],
) -> str | None:
    candidates: list[tuple[int, int, int, int, str]] = []
    for rows in tables:
        for header_row_index, row in enumerate(rows):
            for translation_index, header in enumerate(row):
                header_score = namuwiki_translation_header_score(header)
                if header_score == 0:
                    continue

                source_index = best_namuwiki_header_column(
                    row,
                    namuwiki_source_header_score,
                    {translation_index},
                )
                excluded = {translation_index}
                if source_index is not None:
                    excluded.add(source_index)
                reading_index = best_namuwiki_header_column(
                    row,
                    namuwiki_reading_header_score,
                    excluded,
                )

                groups: list[str] = []
                translated_cells: list[str] = []
                complete_group_count = 0
                for candidate_row in rows[header_row_index + 1 :]:
                    if any(
                        namuwiki_translation_header_score(cell) >= header_score
                        for cell in candidate_row
                    ):
                        break
                    if translation_index >= len(candidate_row):
                        continue
                    translation = normalize_namuwiki_table_text(
                        candidate_row[translation_index]
                    )
                    if (
                        not translation
                        or namuwiki_translation_header_score(translation)
                    ):
                        continue

                    group_lines: list[str] = []
                    source = ""
                    reading = ""
                    if (
                        source_index is not None
                        and source_index < len(candidate_row)
                    ):
                        source = normalize_namuwiki_table_text(
                            candidate_row[source_index]
                        )
                        if source:
                            group_lines.append(source)
                    if (
                        reading_index is not None
                        and reading_index < len(candidate_row)
                    ):
                        reading = normalize_namuwiki_table_text(
                            candidate_row[reading_index]
                        )
                        if reading:
                            group_lines.append(reading)
                    group_lines.append(translation)
                    groups.append("\n".join(group_lines))
                    translated_cells.append(translation)
                    if source and reading:
                        complete_group_count += 1

                translation = "\n".join(translated_cells).strip()
                if not translation or not is_valid_korean_translation(translation):
                    continue
                lyrics = "\n\n".join(groups)
                hangul_count = sum(
                    bool(HANGUL_RE.fullmatch(character))
                    for character in translation
                )
                candidates.append(
                    (
                        hangul_count,
                        complete_group_count,
                        header_score,
                        len(lyrics),
                        lyrics,
                    )
                )

        interleaved_lyrics = extract_interleaved_namuwiki_lyrics(rows)
        if interleaved_lyrics:
            groups, translated_lines, _ = extract_interleaved_namuwiki_groups(
                interleaved_lyrics
            )
            translation = "\n".join(translated_lines)
            hangul_count = sum(
                bool(HANGUL_RE.fullmatch(character))
                for character in translation
            )
            candidates.append(
                (
                    hangul_count,
                    len(groups),
                    50,
                    len(interleaved_lyrics),
                    interleaved_lyrics,
                )
            )

    if not candidates:
        return None
    lyrics = max(candidates, key=lambda candidate: candidate[:4])[4]
    return lyrics if is_usable_namuwiki_lyrics(lyrics) else None


def parse_namuwiki_html_tables(source: str) -> list[list[list[str]]]:
    parser = NamuWikiHTMLTableParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as error:
        raise NamuWikiLyricsError(f"Could not parse NamuWiki HTML: {error}") from error
    return parser.tables


def extract_namuwiki_lyrics_from_namumark(source: str) -> str | None:
    return extract_namuwiki_lyrics_from_tables(parse_namumark_tables(source))


def extract_namuwiki_lyrics_from_html(source: str) -> str | None:
    return extract_namuwiki_lyrics_from_tables(
        parse_namuwiki_html_tables(source)
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
