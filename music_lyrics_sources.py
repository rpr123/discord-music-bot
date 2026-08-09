from __future__ import annotations

import html
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from music_config import (
    LYRICS_API_URL,
    LYRICS_REQUEST_TIMEOUT_SECONDS,
    logger,
)
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


class LyricsLookupError(RuntimeError):
    pass


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


def request_lyrics_records(track_name: str, artist_name: str | None) -> list[dict]:
    params = {"track_name": track_name}
    if artist_name:
        params["artist_name"] = artist_name
    separator = "&" if "?" in LYRICS_API_URL else "?"
    url = f"{LYRICS_API_URL}{separator}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "discord-music-bot/1.0 "
                "(https://github.com/rpr123/discord-music-bot)"
            ),
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise LyricsLookupError(str(error)) from error

    if not isinstance(payload, list):
        raise LyricsLookupError("Lyrics API returned an invalid response.")
    return [record for record in payload if isinstance(record, dict)]


def lookup_track_lyrics(track: Track) -> str | None:
    track_name, artist_name = get_lyrics_search_terms(track)
    if not track_name:
        return None
    records = request_lyrics_records(track_name, artist_name)
    record = select_lyrics_record(
        records,
        track_name,
        artist_name,
        track.duration,
    )
    if record is None and artist_name:
        records = request_lyrics_records(track_name, None)
        record = select_lyrics_record(
            records,
            track_name,
            artist_name,
            track.duration,
        )
        if record is not None:
            logger.info(
                "LRCLIB title-only retry matched lyrics for %s",
                track.title,
            )
    return extract_original_lyrics(record) if record else None


class YouTubeSubtitleError(RuntimeError):
    pass


def normalize_subtitle_text(value: str) -> str:
    return html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_json3_lyrics(payload: str) -> str | None:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.") from error
    if not isinstance(document, dict):
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.")

    lines: list[str] = []
    for event in document.get("events") or []:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs") or []
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in segments
            if isinstance(segment, dict)
        )
        for line in normalize_subtitle_text(text).splitlines():
            line = line.strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


VTT_TIMESTAMP_LINE_RE = re.compile(
    r"^(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


def extract_vtt_lyrics(payload: str) -> str | None:
    lines: list[str] = []
    skip_block = False
    for raw_line in normalize_subtitle_text(payload).splitlines():
        line = raw_line.strip()
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if not line:
            skip_block = False
            continue
        if skip_block or line == "WEBVTT" or VTT_TIMESTAMP_LINE_RE.match(line):
            continue
        if line.isdigit():
            continue
        line = normalize_subtitle_text(VTT_TAG_RE.sub("", line))
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


def request_youtube_subtitle(url: str, extension: str) -> str | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 discord-music-bot/1.0"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise YouTubeSubtitleError(str(error)) from error

    if extension == "json3":
        return extract_json3_lyrics(payload)
    if extension == "vtt":
        return extract_vtt_lyrics(payload)
    return None


def get_subtitle_candidates(
    subtitles: dict[str, list[dict]],
) -> list[tuple[str, str, str, int]]:
    candidates: list[tuple[str, str, str, int]] = []
    format_scores = {"json3": 30, "vtt": 20}
    for language, formats in subtitles.items():
        if not isinstance(formats, list):
            continue
        for subtitle_format in formats:
            if not isinstance(subtitle_format, dict):
                continue
            extension = str(subtitle_format.get("ext") or "").casefold()
            url = subtitle_format.get("url")
            if extension not in format_scores or not isinstance(url, str) or not url:
                continue
            candidates.append(
                (str(language), extension, url, format_scores[extension])
            )
    return candidates


def get_manual_subtitle_candidates(track: Track) -> list[tuple[str, str, str, int]]:
    return get_subtitle_candidates(track.manual_subtitles)


def select_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    preferred_language = (track.subtitle_language or "").casefold()
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold()
        language_score = 0
        if preferred_language and (
            language_key == preferred_language
            or language_key.split("-", 1)[0] == preferred_language.split("-", 1)[0]
        ):
            language_score += 100
        if language_key.endswith("-orig"):
            language_score += 50
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url


def select_korean_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold().replace("_", "-")
        language_parts = language_key.split("-")
        if not language_parts or language_parts[0] != "ko":
            continue
        language_score = 20 if language_key in {"ko", "ko-kr"} else 0
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url
