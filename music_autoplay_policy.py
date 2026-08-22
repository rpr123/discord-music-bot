from __future__ import annotations

import time
from typing import Deque

from music_config import AUTOPLAY_HISTORY_TTL_SECONDS
from music_models import (
    AUTOPLAY_CANDIDATE_POOL_CAP,
    AutoplayHistoryEntry,
    GuildMusicState,
    RecentPlaybackEntry,
    Track,
)
from music_track_metadata import (
    get_track_identity_keys,
    get_track_video_id,
    normalize_track_key,
)


AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)
AUTOPLAY_QUEUE_TARGET = 2
AUTOPLAY_RECENT_OVERLAP_MEDIUM = 0.30
AUTOPLAY_RECENT_OVERLAP_HIGH = 0.60
AUTOPLAY_MEDIUM_FETCH_LIMIT = 12
AUTOPLAY_HIGH_FETCH_LIMIT = 15


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


def _prune_expired_recent_playbacks(
    state: GuildMusicState,
    now: float,
) -> None:
    while state.recent_playbacks and state.recent_playbacks[0].expires_at <= now:
        state.recent_playbacks.popleft()


def remember_recent_playback(
    state: GuildMusicState,
    track: Track,
    *,
    now: float | None = None,
    played_at: float | None = None,
) -> None:
    current_time = time.monotonic() if now is None else now
    playback_time = time.time() if played_at is None else played_at
    identity_keys = frozenset(get_track_identity_keys(track))
    _prune_expired_recent_playbacks(state, current_time)
    state.recent_playbacks.append(
        RecentPlaybackEntry(
            identity_keys=identity_keys,
            title=track.title,
            webpage_url=track.webpage_url or track.source_url,
            played_at=playback_time,
            expires_at=current_time + AUTOPLAY_HISTORY_TTL_SECONDS,
        )
    )


def get_recent_playbacks(
    state: GuildMusicState,
    *,
    now: float | None = None,
) -> tuple[RecentPlaybackEntry, ...]:
    current_time = time.monotonic() if now is None else now
    _prune_expired_recent_playbacks(state, current_time)
    return tuple(reversed(state.recent_playbacks))


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


def get_autoplay_recent_overlap_counts(
    state: GuildMusicState,
    candidates: list[Track],
    extra_excluded_keys: set[str] | None = None,
    *,
    now: float | None = None,
) -> tuple[int, int]:
    current_time = time.monotonic() if now is None else now
    recent_keys = set(_get_recent_expiry_by_key(state, current_time))
    seen_keys = _get_active_track_keys(state)
    if extra_excluded_keys:
        seen_keys.update(extra_excluded_keys)

    recent_count = 0
    considered_count = 0
    for candidate in candidates:
        identity_keys = get_track_identity_keys(candidate)
        if not identity_keys.isdisjoint(seen_keys):
            continue
        seen_keys.update(identity_keys)
        considered_count += 1
        if not identity_keys.isdisjoint(recent_keys):
            recent_count += 1
    return recent_count, considered_count


def get_autoplay_recent_penalty(
    recent_count: int,
    considered_count: int,
) -> int:
    overlap_ratio = recent_count / considered_count if considered_count else 0.0
    if overlap_ratio >= AUTOPLAY_RECENT_OVERLAP_HIGH:
        return 10
    if overlap_ratio >= AUTOPLAY_RECENT_OVERLAP_MEDIUM:
        return 40
    return 80


def get_autoplay_refill_candidate_count(
    base_count: int,
    recent_count: int,
    considered_count: int,
) -> int:
    base_count = max(1, base_count)
    overlap_ratio = recent_count / considered_count if considered_count else 0.0
    if overlap_ratio >= AUTOPLAY_RECENT_OVERLAP_HIGH:
        return max(base_count, AUTOPLAY_HIGH_FETCH_LIMIT)
    if overlap_ratio >= AUTOPLAY_RECENT_OVERLAP_MEDIUM:
        return max(base_count, AUTOPLAY_MEDIUM_FETCH_LIMIT)
    return base_count


def select_autoplay_candidate(
    state: GuildMusicState,
    candidates: list[Track],
    extra_excluded_keys: set[str] | None = None,
    *,
    allow_recent_fallback: bool = False,
    recent_penalty: int | None = None,
    now: float | None = None,
) -> Track | None:
    current_time = time.monotonic() if now is None else now
    recent_expiry_by_key = _get_recent_expiry_by_key(state, current_time)
    hard_excluded_keys = _get_active_track_keys(state)
    if extra_excluded_keys:
        hard_excluded_keys.update(extra_excluded_keys)

    oldest_recent_candidate: Track | None = None
    oldest_recent_expiry: float | None = None
    best_scored_candidate: Track | None = None
    best_selection_score: int | None = None
    best_is_fresh = False
    best_recent_expiry: float | None = None
    for candidate in candidates:
        identity_keys = get_track_identity_keys(candidate)
        if not identity_keys.isdisjoint(hard_excluded_keys):
            continue

        recent_expiries = [
            recent_expiry_by_key[key]
            for key in identity_keys
            if key in recent_expiry_by_key
        ]
        is_fresh = not recent_expiries
        candidate_expiry = max(recent_expiries) if recent_expiries else None
        if recent_penalty is not None:
            if not is_fresh and not allow_recent_fallback:
                continue
            quality_score = int(getattr(candidate, "_autoplay_score", 0))
            selection_score = quality_score - (0 if is_fresh else recent_penalty)
            replace_best = (
                best_selection_score is None
                or selection_score > best_selection_score
            )
            if selection_score == best_selection_score:
                if is_fresh and not best_is_fresh:
                    replace_best = True
                elif (
                    not is_fresh
                    and not best_is_fresh
                    and candidate_expiry is not None
                    and (
                        best_recent_expiry is None
                        or candidate_expiry < best_recent_expiry
                    )
                ):
                    replace_best = True
            if replace_best:
                best_scored_candidate = candidate
                best_selection_score = selection_score
                best_is_fresh = is_fresh
                best_recent_expiry = candidate_expiry
            continue

        if is_fresh:
            return candidate

        if (
            allow_recent_fallback
            and candidate_expiry is not None
            and (
                oldest_recent_expiry is None
                or candidate_expiry < oldest_recent_expiry
            )
        ):
            oldest_recent_candidate = candidate
            oldest_recent_expiry = candidate_expiry

    if best_scored_candidate is not None:
        setattr(
            best_scored_candidate,
            "_autoplay_selection_score",
            best_selection_score,
        )
        setattr(
            best_scored_candidate,
            "_autoplay_recent_penalty",
            recent_penalty,
        )
        return best_scored_candidate
    return oldest_recent_candidate


def select_autoplay_candidates(
    state: GuildMusicState,
    candidates: list[Track],
    extra_excluded_keys: set[str] | None = None,
    *,
    limit: int,
    recent_penalty: int | None = None,
    now: float | None = None,
) -> list[Track]:
    if limit <= 0:
        return []

    current_time = time.monotonic() if now is None else now
    selected: list[Track] = []
    selected_keys = set(extra_excluded_keys or ())
    while len(selected) < limit:
        candidate = select_autoplay_candidate(
            state,
            candidates,
            selected_keys,
            allow_recent_fallback=True,
            recent_penalty=recent_penalty,
            now=current_time,
        )
        if candidate is None:
            break
        selected.append(candidate)
        selected_keys.update(get_track_identity_keys(candidate))
    return selected


def replace_autoplay_candidate_pool(
    state: GuildMusicState,
    candidates: list[Track],
) -> None:
    pooled_candidates = candidates[:AUTOPLAY_CANDIDATE_POOL_CAP]
    state.autoplay_candidate_pool.clear()
    state.autoplay_candidate_pool.extend(pooled_candidates)


def clear_autoplay_candidate_pool(state: GuildMusicState) -> None:
    state.autoplay_candidate_pool.clear()
    state.autoplay_next_fetch_limit = None


def consume_autoplay_candidate(
    state: GuildMusicState,
    extra_excluded_keys: set[str] | None = None,
    *,
    now: float | None = None,
) -> Track | None:
    current_time = time.monotonic() if now is None else now
    hard_excluded_keys = _get_active_track_keys(state)
    if extra_excluded_keys:
        hard_excluded_keys.update(extra_excluded_keys)
    usable_candidates = [
        candidate
        for candidate in state.autoplay_candidate_pool
        if get_track_identity_keys(candidate).isdisjoint(hard_excluded_keys)
    ]
    replace_autoplay_candidate_pool(state, usable_candidates)
    recent_penalty = (
        getattr(usable_candidates[0], "_autoplay_recent_penalty", None)
        if usable_candidates
        else None
    )
    selected = select_autoplay_candidate(
        state,
        usable_candidates,
        extra_excluded_keys,
        allow_recent_fallback=True,
        recent_penalty=recent_penalty,
        now=current_time,
    )
    if selected is None:
        return None

    replace_autoplay_candidate_pool(
        state,
        [
            candidate
            for candidate in usable_candidates
            if candidate.track_id != selected.track_id
        ],
    )
    return selected


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
