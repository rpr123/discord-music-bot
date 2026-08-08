from __future__ import annotations

import re
import unicodedata

from music_models import Track
from music_search_scoring import (
    clean_track_title,
    normalize_artist_name,
    normalize_identity_component,
)


LYRICS_NATIVE_SCRIPT_MIN_RATIO = 0.3
LYRICS_NATIVE_SCRIPT_SCORE_WINDOW = 20
LYRICS_DURATION_MATCH_TOLERANCE_SECONDS = 8
LRC_TIMESTAMP_RE = re.compile(
    r"\[(?:(?:\d{1,2}):)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]"
)
LRC_METADATA_RE = re.compile(
    r"^\[(?:ar|ti|al|by|offset|length|re|ve):.*\]\s*$",
    flags=re.IGNORECASE,
)
QUOTED_TRACK_TITLE_RE = re.compile(
    r"^\s*(?P<artist>.+?)\s*[「『](?P<title>[^」』]+)[」』]"
)


def get_lyrics_search_terms(track: Track) -> tuple[str, str | None]:
    parsed_artist: str | None = None
    raw_title = track.song_name or track.title
    quoted_match = (
        QUOTED_TRACK_TITLE_RE.match(raw_title)
        if track.song_name is None
        else None
    )
    if quoted_match:
        parsed_artist = quoted_match.group("artist")
        song_name = clean_track_title(quoted_match.group("title"))
    else:
        cleaned_title = clean_track_title(raw_title)
        song_name = cleaned_title

    if track.song_name is None and quoted_match is None:
        title_parts = re.split(
            r"\s+(?:-|–|—|\|)\s+",
            song_name,
            maxsplit=1,
        )
        if len(title_parts) == 2:
            parsed_artist, song_name = title_parts

    artist = track.artist or parsed_artist or track.uploader
    artist_name = normalize_artist_name(artist) if artist else None
    return song_name.strip(), artist_name or None


def extract_original_lyrics(record: dict) -> str | None:
    if record.get("instrumental"):
        return None

    plain_lyrics = record.get("plainLyrics")
    if isinstance(plain_lyrics, str) and plain_lyrics.strip():
        return plain_lyrics.replace("\r\n", "\n").replace("\r", "\n").strip()

    synced_lyrics = record.get("syncedLyrics")
    if not isinstance(synced_lyrics, str) or not synced_lyrics.strip():
        return None

    lines = []
    for line in synced_lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if LRC_METADATA_RE.fullmatch(line.strip()):
            continue
        lines.append(LRC_TIMESTAMP_RE.sub("", line))
    lyrics = "\n".join(lines).strip()
    return lyrics or None


def normalize_lyrics_match_text(value: str) -> str:
    return normalize_identity_component(clean_track_title(value))


def get_lyrics_title_aliases(value: str) -> set[str]:
    cleaned_value = clean_track_title(value)
    aliases = {normalize_identity_component(cleaned_value)}
    aliases.update(
        normalize_identity_component(part)
        for part in re.split(
            r"\s+(?:-|–|—|\||/)\s+",
            cleaned_value,
        )
    )
    return {alias for alias in aliases if alias}


def lyrics_native_script_ratio(record: dict) -> float:
    lyrics = extract_original_lyrics(record) or ""
    letters = [character for character in lyrics if character.isalpha()]
    if not letters:
        return 0.0

    non_latin_letters = sum(
        "LATIN" not in unicodedata.name(character, "")
        for character in letters
    )
    return non_latin_letters / len(letters)


def lyrics_record_score(
    record: dict,
    track_name: str,
    artist_name: str | None,
    duration: int | None,
) -> int | None:
    if extract_original_lyrics(record) is None:
        return None

    expected_title = normalize_lyrics_match_text(track_name)
    candidate_title = normalize_lyrics_match_text(str(record.get("trackName") or ""))
    if not expected_title or not candidate_title:
        return None

    expected_aliases = get_lyrics_title_aliases(track_name)
    candidate_aliases = get_lyrics_title_aliases(
        str(record.get("trackName") or "")
    )
    title_is_exact = bool(expected_aliases & candidate_aliases)
    if title_is_exact:
        score = 100
    elif (
        len(expected_title) >= 4
        and (expected_title in candidate_title or candidate_title in expected_title)
    ):
        score = 40
    else:
        return None

    candidate_duration = record.get("duration")
    duration_difference = (
        abs(float(candidate_duration) - duration)
        if duration is not None and isinstance(candidate_duration, (int, float))
        else None
    )
    title_and_duration_match = (
        title_is_exact
        and duration_difference is not None
        and duration_difference <= LYRICS_DURATION_MATCH_TOLERANCE_SECONDS
    )

    if artist_name:
        expected_artist = normalize_artist_name(artist_name)
        candidate_artist = normalize_artist_name(str(record.get("artistName") or ""))
        if candidate_artist == expected_artist:
            score += 80
        elif (
            candidate_artist
            and len(expected_artist) >= 3
            and (expected_artist in candidate_artist or candidate_artist in expected_artist)
        ):
            score += 25
        elif not title_and_duration_match:
            return None

    if duration_difference is not None:
        if duration_difference <= 2:
            score += 40
        elif duration_difference <= 8:
            score += 20
        elif duration_difference <= 20:
            score += 5

    return score


def select_lyrics_record(
    records: list[dict],
    track_name: str,
    artist_name: str | None,
    duration: int | None,
) -> dict | None:
    scored_records: list[tuple[dict, int]] = []
    for record in records:
        score = lyrics_record_score(record, track_name, artist_name, duration)
        if score is not None:
            scored_records.append((record, score))

    if not scored_records:
        return None

    best_score = max(score for _, score in scored_records)
    close_matches = [
        (record, score)
        for record, score in scored_records
        if score >= best_score - LYRICS_NATIVE_SCRIPT_SCORE_WINDOW
    ]
    native_script_matches: list[tuple[dict, int, float]] = []
    for record, score in close_matches:
        native_script_ratio = lyrics_native_script_ratio(record)
        if native_script_ratio >= LYRICS_NATIVE_SCRIPT_MIN_RATIO:
            native_script_matches.append((record, score, native_script_ratio))
    if native_script_matches:
        return max(
            native_script_matches,
            key=lambda candidate: (candidate[1], candidate[2]),
        )[0]

    return max(scored_records, key=lambda candidate: candidate[1])[0]
