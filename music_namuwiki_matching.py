from __future__ import annotations

import re
import unicodedata
import urllib.parse
from collections.abc import Mapping

from music_lyrics_matching import QUOTED_TRACK_TITLE_RE, get_lyrics_search_terms
from music_models import Track
from music_namuwiki_parsing import NamuWikiLyricsError
from music_search_scoring import (
    ARTIST_CHANNEL_SUFFIX_RE,
    clean_track_title,
    clean_track_title_preserving_case,
    normalize_artist_name,
    normalize_identity_component,
    strip_edge_title_tags,
)
from music_track_metadata import get_track_video_id, normalize_track_key


def extract_namuwiki_primary_artist_from_tables(
    tables: list[list[list[str]]],
) -> str | None:
    artist_labels = {"가수", "아티스트", "artist", "歌手"}
    for table in tables:
        for row in table:
            for index, cell in enumerate(row):
                label = normalize_identity_component(cell)
                if label not in artist_labels:
                    continue
                for value in row[index + 1 :]:
                    artist = value.strip()
                    if artist:
                        return artist.splitlines()[0].strip()
    return None


def get_namuwiki_track_artists(track: Track) -> list[str]:
    artists: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        artist = unicodedata.normalize("NFKC", value).strip().strip("\"'")
        artist = ARTIST_CHANNEL_SUFFIX_RE.sub("", artist).strip()
        normalized = normalize_artist_name(artist)
        if (
            not artist
            or not normalized
            or "\n" in artist
            or len(artist) > 120
            or any(normalize_artist_name(item) == normalized for item in artists)
        ):
            return
        artists.append(artist)

    add(track.artist)
    if artists:
        return artists

    quoted_match = QUOTED_TRACK_TITLE_RE.match(track.title)
    if quoted_match:
        add(quoted_match.group("artist"))
    elif track.song_name:
        title_parts = re.split(
            r"\s+(?:-|–|—|\|)\s+",
            track.title,
            maxsplit=1,
        )
        if len(title_parts) == 2:
            normalized_song_name = normalize_identity_component(
                track.song_name
            )
            normalized_left = normalize_identity_component(title_parts[0])
            normalized_right = normalize_identity_component(title_parts[1])
            if normalized_song_name and normalized_song_name in normalized_right:
                add(title_parts[0])
            elif normalized_song_name and normalized_song_name in normalized_left:
                add(title_parts[1])
    return artists


def namuwiki_artist_matches_track(track: Track, page_artist: str | None) -> bool:
    expected_artists = get_namuwiki_track_artists(track)
    if not expected_artists or not page_artist:
        return True

    normalized_page_artist = normalize_artist_name(page_artist)
    if not normalized_page_artist:
        return True
    for expected_artist in expected_artists:
        normalized_expected_artist = normalize_artist_name(expected_artist)
        if normalized_expected_artist == normalized_page_artist:
            return True
        if (
            min(len(normalized_expected_artist), len(normalized_page_artist)) >= 4
            and (
                normalized_expected_artist in normalized_page_artist
                or normalized_page_artist in normalized_expected_artist
            )
        ):
            return True
    return False


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
