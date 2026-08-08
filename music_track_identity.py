from __future__ import annotations

import re
import urllib.parse
from typing import Deque

from music_models import GuildMusicState, Track
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


def remember_recent_value(values: Deque[str], value: str) -> None:
    try:
        values.remove(value)
    except ValueError:
        pass
    values.append(value)


def remember_autoplay_track(state: GuildMusicState, track: Track) -> None:
    remember_recent_value(state.recent_track_keys, normalize_track_key(track))
    video_id = get_track_video_id(track)
    if video_id:
        remember_recent_value(state.recent_video_ids, video_id)


def get_autoplay_excluded_keys(state: GuildMusicState) -> set[str]:
    keys = set(state.recent_track_keys)
    keys.update(f"video:{video_id}" for video_id in state.recent_video_ids)
    if state.current is not None:
        keys.update(get_track_identity_keys(state.current))
    for track in state.queue:
        keys.update(get_track_identity_keys(track))
    return keys


def select_autoplay_candidate(
    state: GuildMusicState,
    candidates: list[Track],
    extra_excluded_keys: set[str] | None = None,
) -> Track | None:
    excluded_keys = get_autoplay_excluded_keys(state)
    if extra_excluded_keys:
        excluded_keys.update(extra_excluded_keys)
    for candidate in candidates:
        if get_track_identity_keys(candidate).isdisjoint(excluded_keys):
            return candidate
    return None
