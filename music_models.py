from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import discord


AUTOPLAY_HISTORY_SIZE = 50


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
    lyrics_reading: str | None = None
    lyrics_reading_loaded: bool = False
    lyrics_reading_source: str | None = None
    lyrics_reading_url: str | None = None
    korean_lyrics_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        repr=False,
    )
    lyrics_reading_lock: asyncio.Lock = field(
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
