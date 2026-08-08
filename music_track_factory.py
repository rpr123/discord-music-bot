from __future__ import annotations

import copy
import time
import urllib.parse

from music_models import Track
from music_track_identity import get_video_id


def get_resolved_stream_url(info: dict) -> str | None:
    if info.get("_type") in {"url", "url_transparent"}:
        return None

    if not (info.get("formats") or info.get("requested_formats")):
        return None

    return info.get("url")


def get_audio_codec(info: dict) -> str | None:
    candidates = [info]
    for key in ("requested_downloads", "requested_formats"):
        values = info.get(key)
        if isinstance(values, list):
            candidates.extend(value for value in values if isinstance(value, dict))

    for candidate in candidates:
        codec = candidate.get("acodec")
        if isinstance(codec, str) and codec.casefold() not in {"", "none"}:
            return codec
    return None


def get_thumbnail_url(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]

    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url")

    return None


def get_entry_url(info: dict, fallback_url: str) -> str:
    raw_url = info.get("webpage_url") or info.get("url") or fallback_url
    video_id = get_video_id(info, raw_url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme and raw_url:
        return f"https://www.youtube.com/watch?v={raw_url}"

    return raw_url


def get_manual_subtitles(info: dict) -> dict[str, list[dict]]:
    subtitles = info.get("subtitles")
    if not isinstance(subtitles, dict):
        return {}

    return {
        str(language): [copy.deepcopy(item) for item in formats if isinstance(item, dict)]
        for language, formats in subtitles.items()
        if isinstance(formats, list)
    }


def make_track_from_info(
    info: dict,
    requester: str,
    fallback_url: str,
    requester_id: int | None = None,
) -> Track:
    source_url = get_entry_url(info, fallback_url)
    stream_url = get_resolved_stream_url(info)
    return Track(
        title=info.get("title") or "Untitled track",
        webpage_url=info.get("webpage_url") or source_url,
        requester=requester,
        source_url=source_url,
        requester_id=requester_id,
        duration=info.get("duration"),
        stream_url=stream_url,
        thumbnail_url=get_thumbnail_url(info),
        artist=info.get("artist") or info.get("creator"),
        song_name=info.get("track") or info.get("alt_title"),
        uploader=info.get("uploader") or info.get("channel"),
        audio_codec=get_audio_codec(info),
        manual_subtitles=get_manual_subtitles(info),
        subtitle_language=info.get("language") or info.get("original_language"),
        stream_resolved_at=(
            info.get("_music_bot_extracted_at", time.monotonic())
            if stream_url
            else None
        ),
    )
