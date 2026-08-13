from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import discord


AUTOPLAY_HISTORY_SIZE = 50
MAX_PLAYBACK_ATTEMPTS = 2


@dataclass
class Track:
    title: str
    webpage_url: str
    requester: str
    source_url: str
    requester_id: int | None = None
    duration: int | None = None
    stream_url: str | None = None
    thumbnail_url: str | None = None
    artist: str | None = None
    song_name: str | None = None
    uploader: str | None = None
    audio_codec: str | None = None
    stream_resolved_at: float | None = None
    playback_attempts: int = 0
    force_transcode: bool = False
    lyrics: str | None = None
    lyrics_loaded: bool = False
    lyrics_source: str | None = None
    korean_lyrics: str | None = None
    korean_lyrics_loaded: bool = False
    korean_lyrics_source: str | None = None
    korean_lyrics_url: str | None = None
    namuwiki_lyrics_checked: bool = False
    korean_lyrics_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )
    manual_subtitles: dict[str, list[dict]] = field(default_factory=dict)
    subtitle_language: str | None = None
    track_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class GuildMusicState:
    queue: Deque[Track] = field(default_factory=deque)
    current: Track | None = None
    voice: discord.VoiceClient | None = None
    announcement_channel: discord.abc.Messageable | None = None
    control_message: discord.Message | None = None
    control_view: discord.ui.View | None = None
    repeat_one: bool = False
    autoplay_enabled: bool = False
    recent_track_keys: Deque[str] = field(
        default_factory=lambda: deque(maxlen=AUTOPLAY_HISTORY_SIZE)
    )
    recent_video_ids: Deque[str] = field(
        default_factory=lambda: deque(maxlen=AUTOPLAY_HISTORY_SIZE)
    )
    skip_requested: bool = False
    stop_requested: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    voice_connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    control_panel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    advance_task: asyncio.Task[None] | None = None
    pending_advance_task: asyncio.Task[None] | None = field(default=None, repr=False)
    pending_advance_generation: int | None = None
    pending_advance_announce: bool = False
    noncritical_task: asyncio.Task[None] | None = None
    autoplay_task: asyncio.Task[None] | None = None
    lyrics_task: asyncio.Task[None] | None = None
    lyrics_message: discord.Message | None = None
    lyrics_view: discord.ui.View | None = None
    private_lyrics_messages: dict[
        str,
        list[discord.WebhookMessage | discord.InteractionMessage],
    ] = field(default_factory=dict)
    queue_cleanup_tasks: dict[int, asyncio.Task[None]] = field(default_factory=dict)
    empty_channel_task: asyncio.Task[None] | None = None
    playback_generation: int = 0


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
