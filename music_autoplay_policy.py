from __future__ import annotations

import time
from typing import Deque

from music_config import AUTOPLAY_HISTORY_TTL_SECONDS
from music_models import AutoplayHistoryEntry, GuildMusicState, Track
from music_track_metadata import (
    get_track_identity_keys,
    get_track_video_id,
    normalize_track_key,
)


AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)
AUTOPLAY_QUEUE_TARGET = 2


def _prune_expired_recent_values(
    values: Deque[AutoplayHistoryEntry],
    now: float,
) -> None:
    while values and values[0].expires_at <= now:
        values.popleft()


def remember_recent_value(
    values: Deque[AutoplayHistoryEntry],
    value: str,
    *,
    now: float | None = None,
) -> None:
    current_time = time.monotonic() if now is None else now
    _prune_expired_recent_values(values, current_time)
    for entry in values:
        if entry.value == value:
            values.remove(entry)
            break
    values.append(
        AutoplayHistoryEntry(
            value=value,
            expires_at=current_time + AUTOPLAY_HISTORY_TTL_SECONDS,
        )
    )


def remember_autoplay_track(
    state: GuildMusicState,
    track: Track,
    *,
    now: float | None = None,
) -> None:
    current_time = time.monotonic() if now is None else now
    remember_recent_value(
        state.recent_track_keys,
        normalize_track_key(track),
        now=current_time,
    )
    video_id = get_track_video_id(track)
    if video_id:
        remember_recent_value(
            state.recent_video_ids,
            video_id,
            now=current_time,
        )


def _get_recent_expiry_by_key(
    state: GuildMusicState,
    now: float,
) -> dict[str, float]:
    _prune_expired_recent_values(state.recent_track_keys, now)
    _prune_expired_recent_values(state.recent_video_ids, now)
    expiry_by_key: dict[str, float] = {}
    for entry in state.recent_track_keys:
        expiry_by_key[entry.value] = max(
            expiry_by_key.get(entry.value, entry.expires_at),
            entry.expires_at,
        )
    for entry in state.recent_video_ids:
        key = f"video:{entry.value}"
        expiry_by_key[key] = max(
            expiry_by_key.get(key, entry.expires_at),
            entry.expires_at,
        )
    return expiry_by_key


def _get_active_track_keys(state: GuildMusicState) -> set[str]:
    keys: set[str] = set()
    if state.current is not None:
        keys.update(get_track_identity_keys(state.current))
    for track in state.queue:
        keys.update(get_track_identity_keys(track))
    return keys


def get_autoplay_excluded_keys(
    state: GuildMusicState,
    *,
    now: float | None = None,
) -> set[str]:
    current_time = time.monotonic() if now is None else now
    keys = set(_get_recent_expiry_by_key(state, current_time))
    keys.update(_get_active_track_keys(state))
    return keys


def select_autoplay_candidate(
    state: GuildMusicState,
    candidates: list[Track],
    extra_excluded_keys: set[str] | None = None,
    *,
    allow_recent_fallback: bool = False,
    now: float | None = None,
) -> Track | None:
    current_time = time.monotonic() if now is None else now
    recent_expiry_by_key = _get_recent_expiry_by_key(state, current_time)
    hard_excluded_keys = _get_active_track_keys(state)
    if extra_excluded_keys:
        hard_excluded_keys.update(extra_excluded_keys)

    oldest_recent_candidate: Track | None = None
    oldest_recent_expiry: float | None = None
    for candidate in candidates:
        identity_keys = get_track_identity_keys(candidate)
        if not identity_keys.isdisjoint(hard_excluded_keys):
            continue

        recent_expiries = [
            recent_expiry_by_key[key]
            for key in identity_keys
            if key in recent_expiry_by_key
        ]
        if not recent_expiries:
            return candidate

        candidate_expiry = max(recent_expiries)
        if (
            allow_recent_fallback
            and (
                oldest_recent_expiry is None
                or candidate_expiry < oldest_recent_expiry
            )
        ):
            oldest_recent_candidate = candidate
            oldest_recent_expiry = candidate_expiry

    return oldest_recent_candidate


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
