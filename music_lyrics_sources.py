from __future__ import annotations

import json
import re
import time
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
from music_track_metadata import get_track_song_candidates


LYRICS_NATIVE_SCRIPT_MIN_RATIO = 0.3
LYRICS_NATIVE_SCRIPT_SCORE_WINDOW = 20
LYRICS_DURATION_MATCH_TOLERANCE_SECONDS = 8
# LRCLIB sheds load with 503; retry a few times inside one lookup deadline.
LYRICS_RETRY_STATUS_CODES = frozenset({429, 503})
LYRICS_RETRY_DELAYS_SECONDS = (2.0, 5.0, 10.0, 15.0)
LYRICS_LOOKUP_TIMEOUT_SECONDS = LYRICS_REQUEST_TIMEOUT_SECONDS * 6
LRC_TIMESTAMP_RE = re.compile(
    r"\[(?:(?:\d{1,2}):)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]"
)
# "ファイトソング (Fight Song)": a native title with its romanized or
# translated name in parentheses. LRCLIB lists the song under one of them.
TITLE_WITH_ALIAS_RE = re.compile(r"(.+?)\s*[(（]([^()（）]+)[)）]")
# Last resort for titles the song/artist parser cannot read, e.g.
# "米津玄師 - ピースサイン , Kenshi Yonezu - Peace Sign": search each piece
# and keep a record only if its song and artist both appear in the title.
TITLE_SEGMENT_SPLIT_RE = re.compile(
    r"\s+[-–—|,]\s+|\s*/\s*|[「」『』【】\[\]()（）［］]"
)
TITLE_SEGMENT_EDGE_CHARACTERS = " -–—~|:"
# The Japanese iTunes store turns a romanized query into the native title,
# without sending YouTube any extra request. The search API returns nothing
# for the Korean store, so Korean songs have no such lookup.
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_STORES = {"ja": ("JP", "ja_jp")}
ITUNES_DURATION_TOLERANCE_SECONDS = 3
ITUNES_NON_VOCAL_RE = re.compile(
    r"off\s*vocal|instrumental|karaoke|\binst\b|オフボーカル|カラオケ|\bmr\b",
    flags=re.IGNORECASE,
)
LYRICS_SEGMENT_SEARCH_LIMIT = 3
LRC_METADATA_RE = re.compile(
    r"^\[(?:ar|ti|al|by|offset|length|re|ve):.*\]\s*$",
    flags=re.IGNORECASE,
)
class LyricsLookupError(RuntimeError):
    pass


def get_lyrics_search_candidates(track: Track) -> list[tuple[str, str | None]]:
    return get_track_song_candidates(track)


def get_lyrics_search_terms(track: Track) -> tuple[str, str | None]:
    return get_lyrics_search_candidates(track)[0]


def extract_original_lyrics(record: dict) -> str | None:
    if record.get("instrumental"):
        return None

    plain_lyrics = record.get("plainLyrics")
    if isinstance(plain_lyrics, str) and plain_lyrics.strip():
        # Some uploads leave LRC timestamps inside the plain lyrics.
        plain_lines = [
            LRC_TIMESTAMP_RE.sub("", line).strip()
            if LRC_TIMESTAMP_RE.search(line)
            else line
            for line in plain_lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ]
        return "\n".join(plain_lines).strip()

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


def non_latin_letter_ratio(value: str) -> float:
    letters = [character for character in value if character.isalpha()]
    if not letters:
        return 0.0

    non_latin_letters = sum(
        "LATIN" not in unicodedata.name(character, "")
        for character in letters
    )
    return non_latin_letters / len(letters)


def get_native_metadata_language(track: Track) -> str | None:
    """Guess the YouTube Music language that shows a romanized song natively."""
    if non_latin_letter_ratio(track.song_name or track.title) >= LYRICS_NATIVE_SCRIPT_MIN_RATIO:
        return None
    # English metadata romanizes the song but keeps the channel name native,
    # e.g. "Ano Hana no you ni" by "noctchill" on the "ノクチル" channel.
    names = " ".join(value for value in (track.uploader, track.artist) if value)
    character_names = [unicodedata.name(character, "") for character in names]
    if any(
        name.startswith(("HIRAGANA", "KATAKANA")) for name in character_names
    ):
        return "ja"
    if any(name.startswith("HANGUL") for name in character_names):
        return "ko"
    return None


def split_title_alias(value: str) -> list[str]:
    match = TITLE_WITH_ALIAS_RE.fullmatch(value.strip())
    if not match:
        return []
    names = [part.strip() for part in match.groups()]
    native = [
        non_latin_letter_ratio(name) >= LYRICS_NATIVE_SCRIPT_MIN_RATIO
        for name in names
    ]
    # Same-script parentheses are usually versions, e.g. "(Live)".
    if not all(names) or native[0] == native[1]:
        return []
    return names


def get_title_search_segments(track: Track) -> list[str]:
    """Title pieces worth a free-text search, minus the channel's names.

    Titles already tried by name are searched again: a free-text search for
    "神山羊" lists the artist's songs, which the title search could not find.
    """
    names = {
        normalize_artist_name(name)
        for value in (track.uploader, track.artist)
        if value
        for name in value.split(",")
    }
    seen = set(names)
    segments: list[str] = []
    for part in TITLE_SEGMENT_SPLIT_RE.split(clean_track_title(track.title)):
        # "怪獣 -Music Video-": drop the dashes so the label suffix comes off.
        part = part.strip(TITLE_SEGMENT_EDGE_CHARACTERS)
        part = clean_track_title(part).strip(TITLE_SEGMENT_EDGE_CHARACTERS)
        key = normalize_identity_component(part)
        if not key or key in seen:
            continue
        seen.add(key)
        segments.append(part)
    return segments[:LYRICS_SEGMENT_SEARCH_LIMIT]


def contains_words(text: str, words: str) -> bool:
    return bool(words) and f" {words} " in f" {text} "


def record_is_named_in_title(record: dict, track: Track) -> bool:
    title_text = normalize_identity_component(
        " ".join(
            value for value in (track.title, track.uploader, track.artist) if value
        )
    )
    song = normalize_identity_component(str(record.get("trackName") or ""))
    artist = normalize_artist_name(str(record.get("artistName") or ""))
    return contains_words(title_text, song) and contains_words(title_text, artist)


def select_title_segment_record(records: list[dict], track: Track) -> dict | None:
    matches = [
        record
        for record in records
        if extract_original_lyrics(record) is not None
        and record_is_named_in_title(record, track)
    ]
    if not matches:
        return None

    def duration_difference(record: dict) -> float:
        duration = record.get("duration")
        if track.duration is None or not isinstance(duration, (int, float)):
            return float("inf")
        return abs(float(duration) - track.duration)

    return min(matches, key=duration_difference)


def request_itunes_songs(params: dict[str, str]) -> list[dict]:
    url = f"{ITUNES_SEARCH_URL}?{urllib.parse.urlencode(params)}"
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
            request, timeout=float(LYRICS_REQUEST_TIMEOUT_SECONDS)
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as error:
        raise LyricsLookupError(str(error)) from error
    results = payload.get("results") if isinstance(payload, dict) else None
    return [result for result in results or [] if isinstance(result, dict)]


def lookup_native_song(track: Track, language: str) -> tuple[str, str | None] | None:
    """Return the native (song, artist) the iTunes store lists for a track."""
    store = ITUNES_STORES.get(language)
    if store is None or track.duration is None:
        return None
    song_name, artist_name = get_lyrics_search_terms(track)
    term = " ".join(value for value in (song_name, artist_name) if value)
    if not term:
        return None
    country, store_language = store
    results = request_itunes_songs(
        {
            "term": term,
            "country": country,
            "lang": store_language,
            "media": "music",
            "entity": "song",
            "limit": "10",
        }
    )
    for result in results:
        name = result.get("trackName")
        milliseconds = result.get("trackTimeMillis")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(milliseconds, (int, float)):
            continue
        # Same-length karaoke and off-vocal tracks have no lyrics to find.
        if ITUNES_NON_VOCAL_RE.search(name):
            continue
        if abs(milliseconds / 1000 - track.duration) > ITUNES_DURATION_TOLERANCE_SECONDS:
            continue
        artist = result.get("artistName")
        return name.strip(), artist.strip() if isinstance(artist, str) else None
    return None


def lyrics_native_script_ratio(record: dict) -> float:
    return non_latin_letter_ratio(extract_original_lyrics(record) or "")


def lyrics_record_score(
    record: dict,
    track_name: str,
    artist_name: str | None,
    duration: int | None,
    *,
    require_native_script: bool = False,
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

    artist_matched = False
    if artist_name:
        expected_artist = normalize_artist_name(artist_name)
        candidate_artist = normalize_artist_name(str(record.get("artistName") or ""))
        if candidate_artist == expected_artist:
            score += 80
            artist_matched = True
        elif (
            candidate_artist
            and len(expected_artist) >= 3
            and (expected_artist in candidate_artist or candidate_artist in expected_artist)
        ):
            score += 25
            artist_matched = True
        elif not title_and_duration_match:
            return None

    # Without an artist match, a same-named song in another language can
    # slip through on title and duration alone (e.g. "Eve" for an Eve MV).
    if (
        require_native_script
        and not artist_matched
        and lyrics_native_script_ratio(record) < LYRICS_NATIVE_SCRIPT_MIN_RATIO
    ):
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
    *,
    require_native_script: bool = False,
) -> dict | None:
    scored_records: list[tuple[dict, int]] = []
    for record in records:
        score = lyrics_record_score(
            record,
            track_name,
            artist_name,
            duration,
            require_native_script=require_native_script,
        )
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


def request_lyrics_records(
    track_name: str,
    artist_name: str | None,
    *,
    deadline: float | None = None,
) -> list[dict]:
    params = {"track_name": track_name}
    if artist_name:
        params["artist_name"] = artist_name
    return request_lyrics_search(params, deadline=deadline)


def search_lyrics_records(query: str, *, deadline: float | None = None) -> list[dict]:
    return request_lyrics_search({"q": query}, deadline=deadline)


def request_lyrics_search(
    params: dict[str, str],
    *,
    deadline: float | None = None,
) -> list[dict]:
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
    for retry_delay in (*LYRICS_RETRY_DELAYS_SECONDS, None):
        timeout = float(LYRICS_REQUEST_TIMEOUT_SECONDS)
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                raise LyricsLookupError("Lyrics lookup ran out of time.")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as error:
            if (
                error.code not in LYRICS_RETRY_STATUS_CODES
                or retry_delay is None
                or (
                    deadline is not None
                    and time.monotonic() + retry_delay >= deadline
                )
            ):
                raise LyricsLookupError(str(error)) from error
            logger.info(
                "LRCLIB returned HTTP %s; retrying in %.0f seconds",
                error.code,
                retry_delay,
            )
            time.sleep(retry_delay)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
            raise LyricsLookupError(str(error)) from error

    if not isinstance(payload, list):
        raise LyricsLookupError("Lyrics API returned an invalid response.")
    return [record for record in payload if isinstance(record, dict)]


def lookup_track_lyrics(track: Track) -> str | None:
    search_candidates = get_lyrics_search_candidates(track)
    track_name, artist_name = search_candidates[0]
    if not track_name:
        return None
    deadline = time.monotonic() + LYRICS_LOOKUP_TIMEOUT_SECONDS
    require_native_script = (
        non_latin_letter_ratio(track.title) >= LYRICS_NATIVE_SCRIPT_MIN_RATIO
    )

    def find_record(
        name: str,
        artist: str | None,
        query_artist: str | None,
    ) -> dict | None:
        records = request_lyrics_records(name, query_artist, deadline=deadline)
        return select_lyrics_record(
            records,
            name,
            artist,
            track.duration,
            require_native_script=require_native_script,
        )

    record = find_record(track_name, artist_name, artist_name)
    if record is None and artist_name:
        record = find_record(track_name, artist_name, None)
        if record is not None:
            logger.info(
                "LRCLIB title-only retry matched lyrics for %s",
                track.title,
            )
    for alternate_name, alternate_artist in search_candidates[1:]:
        if record is not None:
            break
        record = find_record(alternate_name, alternate_artist, alternate_artist)
        if record is not None:
            logger.info(
                "LRCLIB swapped title and artist matched lyrics for %s",
                track.title,
            )
    for name, artist in search_candidates:
        for alias in split_title_alias(name):
            if record is not None:
                break
            record = find_record(alias, artist, artist)
            if record is not None:
                logger.info(
                    "LRCLIB title alias %s matched lyrics for %s",
                    alias,
                    track.title,
                )
    if record is None:
        for segment in get_title_search_segments(track):
            record = select_title_segment_record(
                search_lyrics_records(segment, deadline=deadline),
                track,
            )
            if record is not None:
                logger.info(
                    "LRCLIB title segment %s matched lyrics for %s",
                    segment,
                    track.title,
                )
                break
    return extract_original_lyrics(record) if record else None
