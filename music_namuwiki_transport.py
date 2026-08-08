from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence

from music_namuwiki_parsing import (
    NamuWikiLyricsError,
    NamuWikiPageBlockedError,
)


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


def read_limited_http_response(
    response,
    max_response_bytes: int,
) -> bytes:
    payload = response.read(max_response_bytes + 1)
    if len(payload) > max_response_bytes:
        raise NamuWikiLyricsError("NamuWiki response was too large.")
    return payload


def request_namuwiki_api_source(
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


def request_namuwiki_html_once(
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
