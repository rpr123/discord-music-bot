from __future__ import annotations

import re

from music_namuwiki_interleaved import normalize_namuwiki_table_text


NAMUMARK_STYLE_PREFIX_RE = re.compile(r"^(?:\s*<[^>\n]*>)+")
NAMUMARK_RUBY_RE = re.compile(
    r"\[ruby\((?P<base>.*?),\s*ruby=.*?\)\]",
    flags=re.IGNORECASE,
)
NAMUMARK_LINK_RE = re.compile(r"\[\[(?P<value>[^\]]+)\]\]")
NAMUMARK_FOOTNOTE_RE = re.compile(r"\[\*(?:[^\]]*)\]")


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
