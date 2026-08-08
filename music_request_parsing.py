from __future__ import annotations

import re
import urllib.parse


YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
YOUTUBE_PLAYLIST_SEARCH_FILTER = "EgIQAw%253D%253D"


def is_youtube_search_query(query: str) -> bool:
    return bool(re.match(r"^ytsearch(?:\d+)?:", query, flags=re.IGNORECASE))


def build_youtube_playlist_search_url(query: str, search_kind: str) -> str:
    search_text = f"{query} full album" if search_kind == "album" else query
    encoded_query = urllib.parse.quote_plus(search_text)
    return (
        "https://www.youtube.com/results?"
        f"search_query={encoded_query}&sp={YOUTUBE_PLAYLIST_SEARCH_FILTER}"
    )


def is_playlist_search_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host == "youtube.com" and parsed.path == "/results"


def get_playlist_result_url(info: dict) -> str:
    raw_url = info.get("webpage_url") or info.get("url") or ""
    if raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme in {"http", "https"}:
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/playlist" or "list" in params:
                return raw_url

    playlist_id = info.get("playlist_id") or info.get("id")
    if playlist_id and not re.fullmatch(r"[\w-]{11}", str(playlist_id)):
        return f"https://www.youtube.com/playlist?list={playlist_id}"

    raise ValueError("No YouTube playlist was found in the search results.")


def is_bulk_youtube_url(query: str) -> bool:
    parsed = urllib.parse.urlparse(query.strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower().removeprefix("www.")
    if host not in YOUTUBE_HOSTS:
        return False

    return parsed.path == "/playlist"


def parse_music_request(query: str) -> tuple[str, str | None, bool]:
    query = query.strip()
    lowered = query.lower()
    prefixes: dict[str, tuple[str, bool]] = {
        "album:": ("album", True),
        "album ": ("album", True),
        "playlist:": ("playlist", True),
        "playlist ": ("playlist", True),
        "list:": ("playlist", True),
        "list ": ("playlist", True),
    }

    for prefix, (search_kind, bulk) in prefixes.items():
        if lowered.startswith(prefix):
            return query[len(prefix):].strip(), search_kind, bulk

    return query, None, is_bulk_youtube_url(query)
