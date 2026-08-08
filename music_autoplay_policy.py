from __future__ import annotations

from typing import Deque

from music_models import GuildMusicState, Track
from music_track_identity import (
    get_track_identity_keys,
    get_track_video_id,
    normalize_track_key,
)


AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)
AUTOPLAY_QUEUE_TARGET = 2


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


def get_autoplay_seed(state: GuildMusicState) -> Track | None:
    if state.queue:
        return state.queue[-1]
    return state.current


def autoplay_can_refill(state: GuildMusicState, generation: int) -> bool:
    voice = state.voice
    return (
        state.autoplay_enabled
        and generation == state.playback_generation
        and voice is not None
        and voice.is_connected()
        and len(state.queue) < AUTOPLAY_QUEUE_TARGET
    )


def get_autoplay_retry_delay(failure_count: int) -> int:
    index = min(max(0, failure_count), len(AUTOPLAY_RETRY_DELAYS_SECONDS) - 1)
    return AUTOPLAY_RETRY_DELAYS_SECONDS[index]
