from __future__ import annotations

from music_models import GuildMusicState, Track


MAX_PLAYBACK_ATTEMPTS = 2


def reset_track_playback_attempts(track: Track) -> None:
    track.playback_attempts = 0


def reset_track_playback_state(track: Track) -> None:
    reset_track_playback_attempts(track)
    track.force_transcode = False


def invalidate_track_stream(track: Track) -> None:
    track.stream_url = None
    track.stream_resolved_at = None


def requeue_track_after_playback_error(
    state: GuildMusicState,
    track: Track,
    *,
    used_opus_copy: bool,
) -> bool:
    can_retry = (
        state.current is track
        and not state.skip_requested
        and not state.stop_requested
        and track.playback_attempts < MAX_PLAYBACK_ATTEMPTS
    )
    if not can_retry:
        reset_track_playback_state(track)
        if state.current is track:
            state.current = None
        return False

    invalidate_track_stream(track)
    if used_opus_copy:
        track.force_transcode = True
    state.queue.appendleft(track)
    state.current = None
    return True
