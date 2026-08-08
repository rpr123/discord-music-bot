from __future__ import annotations

import re
import urllib.parse
from collections.abc import Mapping

from music_lyrics_matching import QUOTED_TRACK_TITLE_RE, get_lyrics_search_terms
from music_models import Track
from music_namuwiki_artists import get_namuwiki_track_artists
from music_namuwiki_parsing import NamuWikiLyricsError
from music_search_scoring import (
    clean_track_title,
    clean_track_title_preserving_case,
    strip_edge_title_tags,
)
from music_track_identity import get_track_video_id, normalize_track_key


def find_namuwiki_override(
    track: Track,
    document_overrides: Mapping[str, str],
) -> str | None:
    if not document_overrides:
        return None

    keys: list[str] = []
    video_id = get_track_video_id(track)
    if video_id:
        keys.extend((f"video:{video_id}", video_id))
    keys.extend(
        value
        for value in (
            normalize_track_key(track),
            track.song_name,
            track.title,
        )
        if value
    )
    normalized_overrides = {
        key.casefold(): value
        for key, value in document_overrides.items()
    }
    for key in keys:
        override = normalized_overrides.get(key.casefold())
        if override:
            return override
    return None


def build_namuwiki_document_candidates(
    track: Track,
    override: str | None,
    max_candidates: int,
) -> list[str]:
    candidates: list[str] = []
    artists = get_namuwiki_track_artists(track)

    def add(value: str | None) -> None:
        if not value:
            return
        candidate = value.strip().strip("\"'")
        if (
            not candidate
            or "\n" in candidate
            or len(candidate) > 1000
            or candidate in candidates
        ):
            return
        candidates.append(candidate)

    def add_title(value: str | None) -> None:
        if not value:
            return
        title = value.strip().strip("\"'")
        add(title)
        for artist in artists:
            add(f"{title}({artist})")

    add(override)
    add_title(track.song_name)

    quoted_match = QUOTED_TRACK_TITLE_RE.match(track.title)
    if quoted_match:
        add_title(quoted_match.group("title"))

    raw_parts = re.split(
        r"\s+(?:-|–|—|\|)\s+",
        track.title,
        maxsplit=1,
    )
    if len(raw_parts) == 2:
        cleaned_part = clean_track_title_preserving_case(raw_parts[1])
        add_title(cleaned_part)
        add_title(strip_edge_title_tags(cleaned_part))
        add_title(raw_parts[1])
    else:
        cleaned_title = clean_track_title_preserving_case(track.title)
        add_title(cleaned_title)
        add_title(strip_edge_title_tags(cleaned_title))

    track_name, _ = get_lyrics_search_terms(track)
    add_title(track_name)
    add_title(clean_track_title(track.title))
    return candidates[:max_candidates]


def parse_namuwiki_candidate(
    candidate: str,
    page_base_url: str,
) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"}:
            raise NamuWikiLyricsError("NamuWiki override URL must use HTTP or HTTPS.")
        marker = "/w/"
        if marker not in parsed.path:
            raise NamuWikiLyricsError("NamuWiki override URL must point to a /w/ page.")
        path_prefix, encoded_document = parsed.path.split(marker, 1)
        document = urllib.parse.unquote(encoded_document).strip()
        encoded_path = (
            f"{path_prefix}{marker}"
            f"{urllib.parse.quote(document, safe='')}"
        )
        page_url = urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, encoded_path, "", "", "")
        )
    else:
        document = candidate.strip()
        page_url = (
            f"{page_base_url}/"
            f"{urllib.parse.quote(document, safe='')}"
        )

    if not document or "\n" in document or len(document) > 255:
        raise NamuWikiLyricsError("NamuWiki document title is invalid.")
    return document, page_url
