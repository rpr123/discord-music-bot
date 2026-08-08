from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

from music_namuwiki_interleaved import normalize_namuwiki_table_text


NAMUWIKI_IGNORED_HTML_TAGS = frozenset(
    {"button", "noscript", "script", "style", "sup", "svg"}
)
NAMUWIKI_VOID_HTML_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
)


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
