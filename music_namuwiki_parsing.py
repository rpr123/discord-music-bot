from __future__ import annotations

from music_namumark_tables import parse_namumark_tables
from music_namuwiki_html_tables import NamuWikiHTMLTableParser
from music_namuwiki_table_lyrics import extract_namuwiki_lyrics_from_tables


class NamuWikiLyricsError(RuntimeError):
    pass


class NamuWikiPageBlockedError(NamuWikiLyricsError):
    pass


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
