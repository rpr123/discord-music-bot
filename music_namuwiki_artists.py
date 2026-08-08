from __future__ import annotations

import re
import unicodedata

from music_lyrics_matching import QUOTED_TRACK_TITLE_RE
from music_models import Track
from music_search_scoring import (
    ARTIST_CHANNEL_SUFFIX_RE,
    normalize_artist_name,
    normalize_identity_component,
)


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
