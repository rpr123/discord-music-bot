from __future__ import annotations

import copy
import re
import time
import urllib.parse

from music_models import Track
from music_search_scoring import (
    clean_track_title,
    normalize_artist_name,
    normalize_identity_component,
)


def get_video_id(info: dict, url: str | None = None) -> str | None:
    video_id = info.get("id")
    if video_id and re.fullmatch(r"[\w-]{11}", video_id):
        return video_id

    if not url:
        return None

    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    values = params.get("v")
    if values:
        return values[0]

    return None


def normalize_track_key(track: Track) -> str:
    cleaned_title = clean_track_title(track.title)
    title_parts = re.split(r"\s+(?:-|–|—|\|)\s+", cleaned_title, maxsplit=1)
    parsed_artist = title_parts[0] if len(title_parts) == 2 else None
    parsed_song_name = title_parts[1] if len(title_parts) == 2 else cleaned_title

    artist = track.artist or parsed_artist or track.uploader
    song_name = track.song_name or parsed_song_name
    artist_key = normalize_artist_name(artist) if artist else ""
    song_key = normalize_identity_component(clean_track_title(song_name))

    if artist_key and song_key.startswith(f"{artist_key} "):
        song_key = song_key[len(artist_key) + 1 :]
    if artist_key and song_key:
        return f"song:{artist_key}|{song_key}"
    if song_key:
        return f"song:{song_key}"

    parsed = urllib.parse.urlparse(track.webpage_url)
    params = urllib.parse.parse_qs(parsed.query)
    video_id = params.get("v", [None])[0]
    return f"video:{video_id}" if video_id else track.webpage_url.casefold()


def get_track_video_id(track: Track) -> str | None:
    for url in (track.webpage_url, track.source_url):
        video_id = get_video_id({}, url)
        if video_id:
            return video_id
    return None


def get_track_identity_keys(track: Track) -> set[str]:
    keys = {normalize_track_key(track)}
    video_id = get_track_video_id(track)
    if video_id:
        keys.add(f"video:{video_id}")
    return keys


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
