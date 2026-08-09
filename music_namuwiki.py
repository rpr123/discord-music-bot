from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence

from music_config import (
    NAMUWIKI_API_BASE_URL,
    NAMUWIKI_API_TOKEN,
    NAMUWIKI_DOCUMENT_OVERRIDES,
    NAMUWIKI_LYRICS_ENABLED,
    NAMUWIKI_PAGE_BASE_URL,
    NAMUWIKI_PREVIEW_FALLBACK_ENABLED,
    NAMUWIKI_REQUEST_INTERVAL_SECONDS,
    NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
    logger,
)
from music_lyrics_sources import QUOTED_TRACK_TITLE_RE, get_lyrics_search_terms
from music_models import Track
from music_namuwiki_parsing import (
    NamuWikiLyricsError,
    NamuWikiPageBlockedError,
    extract_namuwiki_lyrics_from_tables,
    parse_namumark_tables,
    parse_namuwiki_html_tables,
)
from music_search_scoring import (
    ARTIST_CHANNEL_SUFFIX_RE,
    clean_track_title,
    clean_track_title_preserving_case,
    normalize_artist_name,
    normalize_identity_component,
    strip_edge_title_tags,
)
from music_track_metadata import get_track_video_id, normalize_track_key


NAMUWIKI_BLOCKED_MARKERS = (
    "captcha 인증이 필요",
    "로봇이 아닙니다",
    "idc 대역 ip",
    "ip 우회 수단",
    "rate limit",
    "too many requests",
    "비정상적인 접근",
    "차단되었습니다",
)
NAMUWIKI_REQUEST_LOCK = threading.Lock()
namuwiki_last_request_started_at = 0.0
namuwiki_prefer_preview_renderer = False
NAMUWIKI_MAX_DOCUMENT_CANDIDATES = 4
NAMUWIKI_MAX_RESPONSE_BYTES = 3_000_000
NAMUWIKI_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
NAMUWIKI_PREVIEW_USER_AGENT = "Discordbot/2.0"


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


def read_namuwiki_http_response(
    response,
    max_response_bytes: int,
) -> bytes:
    payload = response.read(max_response_bytes + 1)
    if len(payload) > max_response_bytes:
        raise NamuWikiLyricsError("NamuWiki response was too large.")
    return payload


def fetch_namuwiki_api_source(
    document: str,
    *,
    api_token: str | None,
    api_base_url: str,
    timeout_seconds: float,
    wait_for_interval: Callable[[], None],
    read_response: Callable[[object], bytes],
    urlopen: Callable[..., object],
) -> str | None:
    if not api_token:
        return None

    url = (
        f"{api_base_url}/edit/"
        f"{urllib.parse.quote(document, safe='')}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_token}",
            "User-Agent": (
                "discord-music-bot/1.0 "
                "(https://github.com/rpr123/discord-music-bot)"
            ),
        },
    )
    wait_for_interval()
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            payload = json.loads(read_response(response).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return None
        raise NamuWikiLyricsError(
            f"NamuWiki API returned HTTP {error.code}."
        ) from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise NamuWikiLyricsError(str(error)) from error

    if not isinstance(payload, dict) or payload.get("exists") is False:
        return None
    source = payload.get("text")
    return source if isinstance(source, str) and source.strip() else None


def fetch_namuwiki_html_once(
    page_url: str,
    user_agent: str,
    *,
    timeout_seconds: float,
    wait_for_interval: Callable[[], None],
    read_response: Callable[[object], bytes],
    urlopen: Callable[..., object],
    blocked_markers: Sequence[str] = NAMUWIKI_BLOCKED_MARKERS,
) -> tuple[str, str] | None:
    request = urllib.request.Request(
        page_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "User-Agent": user_agent,
        },
    )
    wait_for_interval()
    try:
        with urlopen(
            request,
            timeout=timeout_seconds,
        ) as response:
            payload = read_response(response)
            final_url = response.geturl()
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return None
        if error.code == 403:
            raise NamuWikiPageBlockedError(
                "NamuWiki page returned HTTP 403."
            ) from error
        raise NamuWikiLyricsError(
            f"NamuWiki page returned HTTP {error.code}."
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise NamuWikiLyricsError(str(error)) from error

    source = payload.decode("utf-8", errors="replace")
    lowered_source = source.casefold()
    if any(marker in lowered_source for marker in blocked_markers):
        raise NamuWikiPageBlockedError(
            "NamuWiki blocked or challenged the request."
        )
    return source, final_url


def get_namuwiki_override(track: Track) -> str | None:
    return find_namuwiki_override(track, NAMUWIKI_DOCUMENT_OVERRIDES)


def get_namuwiki_document_candidates(track: Track) -> list[str]:
    return build_namuwiki_document_candidates(
        track,
        get_namuwiki_override(track),
        NAMUWIKI_MAX_DOCUMENT_CANDIDATES,
    )


def split_namuwiki_candidate(candidate: str) -> tuple[str, str]:
    return parse_namuwiki_candidate(candidate, NAMUWIKI_PAGE_BASE_URL)


def wait_for_namuwiki_interval() -> None:
    global namuwiki_last_request_started_at
    with NAMUWIKI_REQUEST_LOCK:
        elapsed = time.monotonic() - namuwiki_last_request_started_at
        delay = max(0.0, NAMUWIKI_REQUEST_INTERVAL_SECONDS - elapsed)
        if delay:
            time.sleep(delay)
        namuwiki_last_request_started_at = time.monotonic()


def read_limited_http_response(response) -> bytes:
    return read_namuwiki_http_response(
        response,
        NAMUWIKI_MAX_RESPONSE_BYTES,
    )


def request_namuwiki_api_source(document: str) -> str | None:
    return fetch_namuwiki_api_source(
        document,
        api_token=NAMUWIKI_API_TOKEN,
        api_base_url=NAMUWIKI_API_BASE_URL,
        timeout_seconds=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        wait_for_interval=wait_for_namuwiki_interval,
        read_response=read_limited_http_response,
        urlopen=urllib.request.urlopen,
    )


def request_namuwiki_html_once(
    page_url: str,
    user_agent: str,
) -> tuple[str, str] | None:
    return fetch_namuwiki_html_once(
        page_url,
        user_agent,
        timeout_seconds=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        wait_for_interval=wait_for_namuwiki_interval,
        read_response=read_limited_http_response,
        urlopen=urllib.request.urlopen,
        blocked_markers=NAMUWIKI_BLOCKED_MARKERS,
    )


def request_namuwiki_html(page_url: str) -> tuple[str, str] | None:
    global namuwiki_prefer_preview_renderer

    if (
        not NAMUWIKI_PREVIEW_FALLBACK_ENABLED
        or namuwiki_prefer_preview_renderer
    ):
        user_agent = (
            NAMUWIKI_PREVIEW_USER_AGENT
            if namuwiki_prefer_preview_renderer
            else NAMUWIKI_BROWSER_USER_AGENT
        )
        return request_namuwiki_html_once(page_url, user_agent)

    try:
        return request_namuwiki_html_once(
            page_url,
            NAMUWIKI_BROWSER_USER_AGENT,
        )
    except NamuWikiPageBlockedError as browser_error:
        logger.info(
            "NamuWiki browser page was blocked; retrying through the "
            "Discord link-preview renderer"
        )
        try:
            result = request_namuwiki_html_once(
                page_url,
                NAMUWIKI_PREVIEW_USER_AGENT,
            )
        except NamuWikiLyricsError as preview_error:
            raise NamuWikiLyricsError(
                f"{browser_error} Discord preview fallback failed: "
                f"{preview_error}"
            ) from preview_error

        namuwiki_prefer_preview_renderer = True
        logger.info(
            "NamuWiki Discord link-preview renderer is now preferred "
            "for this process"
        )
        return result


def lookup_namuwiki_lyrics(
    track: Track,
) -> tuple[str, str, str] | None:
    if not NAMUWIKI_LYRICS_ENABLED:
        return None

    candidates = get_namuwiki_document_candidates(track)
    override = get_namuwiki_override(track)
    transient_failures: list[str] = []
    for candidate in candidates:
        try:
            document, page_url = split_namuwiki_candidate(candidate)
        except NamuWikiLyricsError as error:
            logger.warning(
                "Invalid NamuWiki document candidate for %s: %s",
                track.title,
                error,
            )
            continue

        if NAMUWIKI_API_TOKEN:
            try:
                namumark = request_namuwiki_api_source(document)
            except NamuWikiLyricsError as error:
                logger.warning(
                    "NamuWiki API lookup failed for %s (%s): %s",
                    track.title,
                    document,
                    error,
                )
            else:
                if namumark:
                    try:
                        namumark_tables = parse_namumark_tables(namumark)
                        lyrics = extract_namuwiki_lyrics_from_tables(
                            namumark_tables
                        )
                        page_artist = extract_namuwiki_primary_artist_from_tables(
                            namumark_tables
                        )
                    except Exception as error:
                        logger.warning(
                            "NamuWiki source parsing failed for %s (%s): %s",
                            track.title,
                            document,
                            error,
                        )
                        lyrics = None
                    if lyrics:
                        if (
                            candidate != override
                            and not namuwiki_artist_matches_track(
                                track,
                                page_artist,
                            )
                        ):
                            logger.info(
                                "NamuWiki artist mismatch for %s (%s): "
                                "expected %s, page has %s",
                                track.title,
                                document,
                                ", ".join(get_namuwiki_track_artists(track)),
                                page_artist,
                            )
                            continue
                        return lyrics, "나무위키 · 원문·독음·번역", page_url

        try:
            html_result = request_namuwiki_html(page_url)
        except NamuWikiLyricsError as error:
            logger.warning(
                "NamuWiki page lookup failed for %s (%s): %s",
                track.title,
                document,
                error,
            )
            transient_failures.append(f"{document}: {error}")
            continue
        if html_result is None:
            continue

        page_source, final_url = html_result
        try:
            html_tables = parse_namuwiki_html_tables(page_source)
            lyrics = extract_namuwiki_lyrics_from_tables(html_tables)
            page_artist = extract_namuwiki_primary_artist_from_tables(
                html_tables
            )
        except NamuWikiLyricsError as error:
            logger.warning(
                "NamuWiki HTML parsing failed for %s (%s): %s",
                track.title,
                document,
                error,
            )
            transient_failures.append(f"{document}: {error}")
            continue
        if lyrics:
            if (
                candidate != override
                and not namuwiki_artist_matches_track(track, page_artist)
            ):
                logger.info(
                    "NamuWiki artist mismatch for %s (%s): expected %s, "
                    "page has %s",
                    track.title,
                    document,
                    ", ".join(get_namuwiki_track_artists(track)),
                    page_artist,
                )
                continue
            logger.info(
                "NamuWiki lyrics selected for %s (%s)",
                track.title,
                document,
            )
            return lyrics, "나무위키 · 원문·독음·번역", final_url

    if transient_failures:
        raise NamuWikiLyricsError(
            "NamuWiki candidate pages could not be verified. "
            "On hosted servers, configure NAMUWIKI_API_TOKEN. "
            f"Last failure: {transient_failures[-1]}"
        )

    if candidates:
        logger.info(
            "No NamuWiki lyrics found for %s (candidates: %s)",
            track.title,
            ", ".join(candidates),
        )
    return None
