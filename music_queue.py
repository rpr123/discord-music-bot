from __future__ import annotations

from collections import deque

from music_models import GuildMusicState, Track


def remove_queued_track(state: GuildMusicState, index: int) -> Track | None:
    if index < 0 or index >= len(state.queue):
        return None

    tracks = list(state.queue)
    removed = tracks.pop(index)
    state.queue = deque(tracks)
    return removed


def remove_queued_track_by_id(
    state: GuildMusicState,
    track_id: str,
) -> Track | None:
    for index, track in enumerate(state.queue):
        if track.track_id == track_id:
            return remove_queued_track(state, index)
    return None


def remove_queued_track_range_by_ids(
    state: GuildMusicState,
    first_track_id: str,
    second_track_id: str,
) -> tuple[list[Track], int, int] | None:
    tracks = list(state.queue)
    positions = {track.track_id: index for index, track in enumerate(tracks)}
    if first_track_id not in positions or second_track_id not in positions:
        return None

    start_index, end_index = sorted(
        (positions[first_track_id], positions[second_track_id])
    )
    removed = tracks[start_index : end_index + 1]
    state.queue = deque(tracks[:start_index] + tracks[end_index + 1 :])
    return removed, start_index, end_index
