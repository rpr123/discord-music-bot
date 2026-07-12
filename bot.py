from __future__ import annotations

import asyncio
import copy
import json
import itertools
import logging
import math
import os
import random
import re
import shutil
import time
import unicodedata
import urllib.parse
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands


PROJECT_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path | str = PROJECT_DIR / ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


load_env_file()


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("music-bot")


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_DIR / path


DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
FFMPEG_EXECUTABLE = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg") or "ffmpeg"
MUSIC_CHANNEL_ID = os.getenv("MUSIC_CHANNEL_ID")
MUSIC_CHANNEL_NAME = os.getenv("MUSIC_CHANNEL_NAME", "music")
MUSIC_CHANNELS_FILE = resolve_project_path(
    os.getenv("MUSIC_CHANNELS_FILE", "music_channels.json")
)
MUSIC_CHANNEL_SILENT = os.getenv("MUSIC_CHANNEL_SILENT", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
MUSIC_CHANNEL_DELETE_REQUESTS = os.getenv("MUSIC_CHANNEL_DELETE_REQUESTS", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE")
MUSIC_TEST_AUDIO_FILE = os.getenv("MUSIC_TEST_AUDIO_FILE")
YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
YOUTUBE_PLAYLIST_SEARCH_FILTER = "EgIQAw%253D%253D"


def parse_positive_int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        logger.warning("%s must be a positive integer. Falling back to %s.", name, default)
        return default


def parse_nonnegative_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be zero or greater. Falling back to %s.", name, default)
        return default

    if value < 0:
        logger.warning("%s must be zero or greater. Falling back to %s.", name, default)
        return default
    return value


def parse_volume_env(name: str, default: float) -> float:
    try:
        volume = float(os.getenv(name, str(default)))
    except ValueError:
        logger.warning("%s must be a number between 0.0 and 1.0. Falling back to %.2f.", name, default)
        return default

    if volume < 0.0 or volume > 1.0:
        logger.warning("%s must be between 0.0 and 1.0. Falling back to %.2f.", name, default)
        return default

    return volume


MAX_BULK_TRACKS = parse_positive_int_env("MAX_BULK_TRACKS", 50)
MUSIC_FEEDBACK_DELETE_SECONDS = parse_positive_int_env("MUSIC_FEEDBACK_DELETE_SECONDS", 10)
DEFAULT_AUTO_TRACKS = parse_positive_int_env("DEFAULT_AUTO_TRACKS", 8)
MAX_AUTO_TRACKS = parse_positive_int_env("MAX_AUTO_TRACKS", 25)
BOT_VOLUME = parse_volume_env("BOT_VOLUME", 0.2)
DISCORD_EMBED_FIELD_LIMIT = 1024
YTDL_EXTRACT_TIMEOUT_SECONDS = parse_positive_int_env("YTDL_EXTRACT_TIMEOUT_SECONDS", 45)
YTDL_MAX_CONCURRENT_EXTRACTIONS = parse_positive_int_env(
    "YTDL_MAX_CONCURRENT_EXTRACTIONS", 1
)
STREAM_URL_MAX_AGE_SECONDS = parse_positive_int_env("STREAM_URL_MAX_AGE_SECONDS", 900)
YTDL_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env("YTDL_MIN_INTERVAL_SECONDS", 6.0)
YTDL_CACHE_TTL_SECONDS = parse_positive_int_env("YTDL_CACHE_TTL_SECONDS", 600)
YTDL_CACHE_MAX_ENTRIES = parse_positive_int_env("YTDL_CACHE_MAX_ENTRIES", 128)
YOUTUBE_CIRCUIT_BREAKER_SECONDS = parse_positive_int_env(
    "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800
)
MUSIC_TEST_BULK_TRACKS = parse_positive_int_env("MUSIC_TEST_BULK_TRACKS", 3)
EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS = 3
AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)
AUTOPLAY_HISTORY_SIZE = 50
AUTOPLAY_BUTTON_CUSTOM_ID = "music:autoplay"

YTDL_BASE_OPTIONS = {
    "format": "bestaudio/best",
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
}

if YOUTUBE_COOKIES_FILE:
    YTDL_BASE_OPTIONS["cookiefile"] = str(resolve_project_path(YOUTUBE_COOKIES_FILE))

YTDL_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": True,
    "extract_flat": False,
}

YTDL_PLAYLIST_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": False,
    "extract_flat": "in_playlist",
    "playlistend": MAX_BULK_TRACKS,
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
FFMPEG_LOCAL_OPTIONS = {"options": "-vn"}

ytdl_semaphore = asyncio.Semaphore(YTDL_MAX_CONCURRENT_EXTRACTIONS)
ytdl_rate_lock = asyncio.Lock()
ytdl_cache_lock = asyncio.Lock()
ytdl_cache: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
ytdl_last_request_started_at = 0.0
youtube_circuit_open_until = 0.0
youtube_circuit_reason: str | None = None
music_test_track_counter = itertools.count(1)

YOUTUBE_BLOCK_ERROR_MARKERS = (
    "http error 429",
    "too many requests",
    "http error 402",
    "sign in to confirm",
    "confirm you're not a bot",
    "confirm you’re not a bot",
    "request rate limit",
    "ip address has been blocked",
)


class YouTubeCircuitOpenError(RuntimeError):
    def __init__(self, retry_after_seconds: int, reason: str | None = None):
        self.retry_after_seconds = retry_after_seconds
        self.reason = reason
        minutes = max(1, math.ceil(retry_after_seconds / 60))
        super().__init__(f"YouTube 요청이 제한되어 있어 약 {minutes}분 뒤 다시 시도해 주세요.")


def is_youtube_block_error(error: BaseException) -> bool:
    message = str(error).casefold()
    return any(marker in message for marker in YOUTUBE_BLOCK_ERROR_MARKERS)


def get_youtube_circuit_retry_after() -> int:
    global youtube_circuit_open_until, youtube_circuit_reason
    remaining = youtube_circuit_open_until - time.monotonic()
    if remaining <= 0:
        youtube_circuit_open_until = 0.0
        youtube_circuit_reason = None
        return 0
    return math.ceil(remaining)


def trip_youtube_circuit(error: BaseException) -> bool:
    global youtube_circuit_open_until, youtube_circuit_reason
    if not is_youtube_block_error(error):
        return False
    if get_youtube_circuit_retry_after() > 0:
        return True

    youtube_circuit_open_until = time.monotonic() + YOUTUBE_CIRCUIT_BREAKER_SECONDS
    youtube_circuit_reason = str(error)
    logger.error(
        "YouTube circuit opened for %s seconds: %s",
        YOUTUBE_CIRCUIT_BREAKER_SECONDS,
        error,
    )
    return True


def ensure_youtube_circuit_closed() -> None:
    retry_after = get_youtube_circuit_retry_after()
    if retry_after > 0:
        raise YouTubeCircuitOpenError(retry_after, youtube_circuit_reason)


def get_ytdl_cache_key(options: dict, query: str) -> tuple[str, str]:
    mode = "|".join(
        (
            str(options.get("extract_flat")),
            str(options.get("noplaylist")),
            str(options.get("playlistend")),
        )
    )
    return mode, query


def stamp_ytdl_info(info: dict, extracted_at: float) -> None:
    info["_music_bot_extracted_at"] = extracted_at
    for entry in info.get("entries") or []:
        if isinstance(entry, dict):
            stamp_ytdl_info(entry, extracted_at)


async def get_cached_ytdl_info(cache_key: tuple[str, str]) -> dict | None:
    if YTDL_CACHE_TTL_SECONDS <= 0:
        return None

    async with ytdl_cache_lock:
        cached = ytdl_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, info = cached
        if time.monotonic() - cached_at >= YTDL_CACHE_TTL_SECONDS:
            ytdl_cache.pop(cache_key, None)
            return None
        ytdl_cache.move_to_end(cache_key)
        return copy.deepcopy(info)


async def cache_ytdl_info(cache_key: tuple[str, str], info: dict) -> None:
    if YTDL_CACHE_TTL_SECONDS <= 0:
        return

    async with ytdl_cache_lock:
        ytdl_cache[cache_key] = (time.monotonic(), copy.deepcopy(info))
        ytdl_cache.move_to_end(cache_key)
        while len(ytdl_cache) > YTDL_CACHE_MAX_ENTRIES:
            ytdl_cache.popitem(last=False)


async def wait_for_ytdl_interval() -> None:
    global ytdl_last_request_started_at
    async with ytdl_rate_lock:
        elapsed = time.monotonic() - ytdl_last_request_started_at
        delay = max(0.0, YTDL_MIN_INTERVAL_SECONDS - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
        ytdl_last_request_started_at = time.monotonic()


async def extract_ytdl_info(
    options: dict,
    query: str,
    label: str,
    *,
    use_cache: bool = True,
) -> dict:
    cache_key = get_ytdl_cache_key(options, query)
    if use_cache:
        cached = await get_cached_ytdl_info(cache_key)
        if cached is not None:
            logger.info("yt-dlp cache hit: %s", label)
            return cached

    ensure_youtube_circuit_closed()
    logger.info("yt-dlp start: %s", label)
    logger.debug("yt-dlp query for %s: %s", label, query)

    def extract() -> dict:
        with yt_dlp.YoutubeDL(dict(options)) as downloader:
            return downloader.extract_info(query, download=False)

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    try:
        await asyncio.wait_for(
            ytdl_semaphore.acquire(),
            timeout=YTDL_EXTRACT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("yt-dlp queue timed out: %s", label)
        raise

    try:
        ensure_youtube_circuit_closed()
        await wait_for_ytdl_interval()
    except BaseException:
        ytdl_semaphore.release()
        raise

    worker = asyncio.create_task(asyncio.to_thread(extract))

    def extraction_finished(task: asyncio.Task[dict]) -> None:
        ytdl_semaphore.release()
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            trip_youtube_circuit(error)

    worker.add_done_callback(extraction_finished)
    remaining_timeout = max(
        0.1,
        YTDL_EXTRACT_TIMEOUT_SECONDS - (loop.time() - started_at),
    )
    try:
        info = await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=remaining_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "yt-dlp timed out after %s seconds: %s",
            YTDL_EXTRACT_TIMEOUT_SECONDS,
            label,
        )
        raise
    except Exception as error:
        trip_youtube_circuit(error)
        raise

    stamp_ytdl_info(info, loop.time())
    if use_cache:
        await cache_ytdl_info(cache_key, info)
    logger.info("yt-dlp done: %s", label)
    return info


def ffmpeg_is_available() -> bool:
    if Path(FFMPEG_EXECUTABLE).exists():
        return True
    return shutil.which(FFMPEG_EXECUTABLE) is not None


def is_silent_music_channel(channel: discord.abc.Messageable | None) -> bool:
    if not MUSIC_CHANNEL_SILENT or channel is None:
        return False

    guild = getattr(channel, "guild", None)
    channel_id = getattr(channel, "id", None)
    if guild is None or channel_id is None:
        return False

    return get_music_channel_id(guild.id) == channel_id


async def delete_music_request_message(message: discord.Message) -> None:
    if not MUSIC_CHANNEL_DELETE_REQUESTS:
        return

    try:
        await message.delete()
    except discord.NotFound:
        pass


async def delete_message_later(message: discord.Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException:
        logger.exception("Failed to delete temporary music feedback message")


async def notify_playback_error(state: GuildMusicState, content: str) -> None:
    if not state.announcement_channel:
        return

    try:
        await state.announcement_channel.send(
            content,
            silent=is_silent_music_channel(state.announcement_channel),
        )
    except discord.Forbidden:
        logger.warning("Missing permission to send playback error message")


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
    is_local: bool = False
    stream_resolved_at: float | None = None
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
    skip_requested: bool = False
    stop_requested: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control_panel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    advance_task: asyncio.Task[None] | None = None
    autoplay_task: asyncio.Task[None] | None = None
    empty_channel_task: asyncio.Task[None] | None = None
    playback_generation: int = 0


intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
music_states: dict[int, GuildMusicState] = {}
configured_music_channels: dict[int, int] = {}
configured_control_messages: dict[int, int] = {}
configured_autoplay_enabled: dict[int, bool] = {}
commands_synced = False


def get_state(guild_id: int) -> GuildMusicState:
    if guild_id not in music_states:
        music_states[guild_id] = GuildMusicState(
            autoplay_enabled=configured_autoplay_enabled.get(guild_id, False)
        )
    return music_states[guild_id]


def load_music_channel_config() -> None:
    if not MUSIC_CHANNELS_FILE.exists():
        configured_music_channels.clear()
        configured_control_messages.clear()
        configured_autoplay_enabled.clear()
        return

    try:
        raw_config = json.loads(MUSIC_CHANNELS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read %s", MUSIC_CHANNELS_FILE)
        return

    if not isinstance(raw_config, dict):
        logger.warning("Ignoring invalid music channel config in %s", MUSIC_CHANNELS_FILE)
        return

    configured_music_channels.clear()
    configured_control_messages.clear()
    configured_autoplay_enabled.clear()
    for guild_id, value in raw_config.items():
        if isinstance(value, dict):
            channel_id = value.get("channel_id")
            control_message_id = value.get("control_message_id")
            autoplay_enabled = value.get("autoplay_enabled", False)
        else:
            channel_id = value
            control_message_id = None
            autoplay_enabled = False

        try:
            parsed_guild_id = int(guild_id)
            configured_music_channels[parsed_guild_id] = int(channel_id)
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid music channel config for guild %s", guild_id)
            continue

        if control_message_id is not None:
            try:
                configured_control_messages[parsed_guild_id] = int(control_message_id)
            except (TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid control message config for guild %s",
                    guild_id,
                )

        if isinstance(autoplay_enabled, bool):
            if autoplay_enabled:
                configured_autoplay_enabled[parsed_guild_id] = True
        else:
            logger.warning(
                "Ignoring invalid autoplay config for guild %s",
                guild_id,
            )


def save_music_channel_config() -> None:
    raw_config: dict[str, dict[str, int | bool]] = {}
    for guild_id, channel_id in sorted(configured_music_channels.items()):
        entry = {"channel_id": channel_id}
        control_message_id = configured_control_messages.get(guild_id)
        if control_message_id is not None:
            entry["control_message_id"] = control_message_id
        if configured_autoplay_enabled.get(guild_id, False):
            entry["autoplay_enabled"] = True
        raw_config[str(guild_id)] = entry

    MUSIC_CHANNELS_FILE.write_text(
        json.dumps(raw_config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def get_music_channel_id(guild_id: int) -> int | None:
    if MUSIC_CHANNEL_ID:
        try:
            return int(MUSIC_CHANNEL_ID)
        except ValueError:
            logger.warning("MUSIC_CHANNEL_ID must be a numeric Discord channel ID")
            return None
    return configured_music_channels.get(guild_id)


def set_music_channel(guild_id: int, channel_id: int) -> None:
    if configured_music_channels.get(guild_id) != channel_id:
        configured_control_messages.pop(guild_id, None)
    configured_music_channels[guild_id] = channel_id
    save_music_channel_config()


def get_control_message_id(guild_id: int) -> int | None:
    return configured_control_messages.get(guild_id)


def set_control_message_id(guild_id: int, message_id: int) -> None:
    channel_id = get_music_channel_id(guild_id)
    if channel_id is None:
        return

    configured_music_channels.setdefault(guild_id, channel_id)
    if configured_control_messages.get(guild_id) == message_id:
        return

    configured_control_messages[guild_id] = message_id
    save_music_channel_config()


def clear_control_message_id(guild_id: int) -> None:
    if configured_control_messages.pop(guild_id, None) is not None:
        save_music_channel_config()


def get_autoplay_enabled(guild_id: int) -> bool:
    return configured_autoplay_enabled.get(guild_id, False)


def set_autoplay_enabled(guild_id: int, enabled: bool) -> None:
    channel_id = get_music_channel_id(guild_id)
    if channel_id is not None:
        configured_music_channels.setdefault(guild_id, channel_id)

    if enabled:
        configured_autoplay_enabled[guild_id] = True
    else:
        configured_autoplay_enabled.pop(guild_id, None)
    save_music_channel_config()


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "live"

    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def requester_label(track: Track) -> str:
    if track.requester_id is None:
        return track.requester
    return f"<@{track.requester_id}>"


def make_track_embed(track: Track, title: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=make_track_link(track, 4096))
    embed.add_field(name="Length", value=format_duration(track.duration), inline=True)
    embed.add_field(name="Requested by", value=track.requester, inline=True)
    if track.thumbnail_url:
        embed.set_thumbnail(url=track.thumbnail_url)
    return embed


def make_player_embed(track: Track, state: GuildMusicState) -> discord.Embed:
    queue_count = len(state.queue)
    repeat_text = "켜짐" if state.repeat_one else "꺼짐"
    autoplay_text = "켜짐" if state.autoplay_enabled else "꺼짐"
    embed = discord.Embed(
        title="💿 지금 재생 중",
        description=f"🎧 {requester_label(track)}님이 신청한 곡이에요!",
        color=discord.Color.gold(),
    )
    embed.add_field(
        name="YouTube",
        value=make_track_link(track, DISCORD_EMBED_FIELD_LIMIT),
        inline=False,
    )
    embed.add_field(name="길이", value=format_duration(track.duration), inline=True)
    embed.add_field(name="대기열", value=f"{queue_count}곡", inline=True)
    embed.add_field(name="반복", value=repeat_text, inline=True)
    embed.add_field(name="자동재생", value=autoplay_text, inline=True)
    if state.queue:
        preview = []
        for index, queued in enumerate(list(state.queue)[:5], start=1):
            preview.append(make_queue_line(index, queued))
        if len(state.queue) > 5:
            preview.append(f"...and {len(state.queue) - 5} more")
        embed.add_field(name="다음 곡", value="\n".join(preview), inline=False)
    #embed.set_footer(text=f"기본 볼륨 {int(BOT_VOLUME * 100)} · 버튼으로 바로 제어") 필요 없을듯?
    if track.thumbnail_url:
        embed.set_image(url=track.thumbnail_url)
    return embed


def make_idle_player_embed() -> discord.Embed:
    return discord.Embed(
        title="🎵 재생 대기 중",
        description=(
            "음성 채널에 들어간 뒤 아래 형식으로 메시지를 보내 주세요.\n\n"
            "`곡명` 또는 `YouTube URL`\n"
            "`album: 앨범명`\n"
            "`playlist: 플레이리스트명`\n"
            "`auto: 곡명` 또는 `auto: 12 곡명`\n\n"
            "자동재생은 아래 버튼으로 켜고 끌 수 있어요."
        ),
        color=discord.Color.blurple(),
    )


def make_bulk_embed(tracks: list[Track], title: str) -> discord.Embed:
    embed = discord.Embed(title=title)
    preview = [
        f"{index}. {make_track_link(track, DISCORD_EMBED_FIELD_LIMIT - 8)}"
        for index, track in enumerate(tracks[:10], start=1)
    ]
    if len(tracks) > 10:
        preview.append(f"...and {len(tracks) - 10} more")

    embed.description = "\n".join(preview)
    embed.add_field(name="Added", value=str(len(tracks)), inline=True)
    embed.add_field(name="Limit", value=str(MAX_BULK_TRACKS), inline=True)
    return embed


def single_line(value: str) -> str:
    return " ".join(value.split())


def truncate_text(value: str, limit: int) -> str:
    value = single_line(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def make_track_link(track: Track, limit: int = DISCORD_EMBED_FIELD_LIMIT) -> str:
    title = truncate_text(track.title, 120)
    if not track.webpage_url:
        return title
    value = f"[{title}]({track.webpage_url})"
    if len(value) <= limit:
        return value
    return truncate_text(track.title, limit)


def make_queue_line(index: int, track: Track) -> str:
    return f"{index}. {truncate_text(track.title, 72)} - {format_duration(track.duration)}"


def make_queue_embed(state: GuildMusicState) -> discord.Embed:
    embed = discord.Embed(title="📋 대기열", color=discord.Color.blurple())

    if state.current:
        embed.add_field(
            name="지금 재생 중",
            value=make_track_link(state.current, DISCORD_EMBED_FIELD_LIMIT),
            inline=False,
        )

    if state.queue:
        lines = [
            make_queue_line(index, track)
            for index, track in enumerate(list(state.queue)[:10], start=1)
        ]
        if len(state.queue) > 10:
            lines.append(f"...and {len(state.queue) - 10} more")
        embed.add_field(name="다음 곡", value="\n".join(lines), inline=False)
    elif not state.current:
        embed.description = "대기열이 비어 있어요."

    return embed


def truncate_option_text(value: str, limit: int = 100) -> str:
    return truncate_text(value, limit)


def remove_queued_track(state: GuildMusicState, index: int) -> Track | None:
    if index < 0 or index >= len(state.queue):
        return None

    tracks = list(state.queue)
    removed = tracks.pop(index)
    state.queue = deque(tracks)
    return removed


def remove_queued_track_by_id(state: GuildMusicState, track_id: str) -> Track | None:
    for index, track in enumerate(state.queue):
        if track.track_id == track_id:
            return remove_queued_track(state, index)
    return None


class QueueRemoveSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        state = get_state(guild_id)
        options = [
            discord.SelectOption(
                label=truncate_option_text(f"{index}. {track.title}"),
                description=truncate_option_text(f"신청자: {track.requester}", 100),
                value=track.track_id,
            )
            for index, track in enumerate(list(state.queue)[:25], start=1)
        ]
        super().__init__(
            placeholder="삭제할 대기열 곡을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        state = get_state(self.guild_id)
        removed = remove_queued_track_by_id(state, self.values[0])
        if removed is None:
            await interaction.response.edit_message(
                content="이미 삭제되었거나 찾을 수 없는 곡이에요.",
                embed=make_queue_embed(state),
                view=QueueManageView(self.guild_id) if state.queue else None,
            )
            return

        schedule_autoplay_refill(self.guild_id)
        if state.current:
            await update_control_panel(self.guild_id, state)

        await interaction.response.edit_message(
            content=f"대기열에서 `{removed.title}`을 삭제했어요.",
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
        )


class QueueManageView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        if get_state(guild_id).queue:
            self.add_item(QueueRemoveSelect(guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_same_voice_channel(interaction, get_state(self.guild_id))


class MusicControlView(discord.ui.View):
    def __init__(self, guild_id: int, *, disabled: bool = False):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        state = get_state(guild_id)
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            if child.custom_id == AUTOPLAY_BUTTON_CUSTOM_ID:
                child.label = f"자동재생: {'켜짐' if state.autoplay_enabled else '꺼짐'}"
                child.style = (
                    discord.ButtonStyle.success
                    if state.autoplay_enabled
                    else discord.ButtonStyle.secondary
                )
            elif disabled:
                child.disabled = True

    def get_state(self) -> GuildMusicState:
        return get_state(self.guild_id)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = (interaction.data or {}).get("custom_id")
        if custom_id == AUTOPLAY_BUTTON_CUSTOM_ID:
            state = self.get_state()
            if state.voice and state.voice.is_connected():
                return await ensure_same_voice_channel(interaction, state)

            member_channel = getattr(
                getattr(interaction.user, "voice", None),
                "channel",
                None,
            )
            if member_channel is not None:
                return True

            await interaction.response.send_message(
                "먼저 음성 채널에 들어가 주세요.",
                ephemeral=True,
            )
            return False

        return await ensure_same_voice_channel(interaction, self.get_state())

    async def edit_panel(self, interaction: discord.Interaction) -> None:
        state = self.get_state()
        if state.current is None:
            await interaction.response.edit_message(
                embed=make_idle_player_embed(),
                view=MusicControlView(self.guild_id, disabled=True),
            )
            return

        await interaction.response.edit_message(
            embed=make_player_embed(state.current, state),
            view=MusicControlView(self.guild_id),
        )

    @discord.ui.button(label="재생/일시정지", emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        if state.voice is None:
            await interaction.response.send_message("봇이 음성 채널에 없어요.", ephemeral=True)
            return

        if state.voice.is_paused():
            state.voice.resume()
        elif state.voice.is_playing():
            state.voice.pause()
        else:
            await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)
            return

        await self.edit_panel(interaction)

    @discord.ui.button(label="스킵", emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
            state.skip_requested = True
            state.voice.stop()
            await interaction.response.send_message("다음 곡으로 넘어갈게요.", ephemeral=True)
            return

        await interaction.response.send_message("스킵할 곡이 없어요.", ephemeral=True)

    @discord.ui.button(label="정지", emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        stop_playback(state)
        await interaction.response.defer()
        await show_idle_panel(self.guild_id, state)

    @discord.ui.button(label="반복", emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def repeat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        state.repeat_one = not state.repeat_one
        await self.edit_panel(interaction)

    @discord.ui.button(label="셔플", emoji="🔀", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        tracks = list(state.queue)
        random.shuffle(tracks)
        state.queue = deque(tracks)
        await self.edit_panel(interaction)

    @discord.ui.button(label="대기열 삭제", emoji="📋", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        await interaction.response.send_message(
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
            ephemeral=True,
        )

    @discord.ui.button(
        label="자동재생: 꺼짐",
        emoji="♾️",
        style=discord.ButtonStyle.secondary,
        custom_id=AUTOPLAY_BUTTON_CUSTOM_ID,
        row=2,
    )
    async def autoplay(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        state = self.get_state()
        state.autoplay_enabled = not state.autoplay_enabled
        set_autoplay_enabled(self.guild_id, state.autoplay_enabled)
        if state.autoplay_enabled:
            schedule_autoplay_refill(self.guild_id)
        else:
            cancel_autoplay_refill(state)
        await self.edit_panel(interaction)


def build_youtube_search_query(query: str) -> str:
    return f"ytsearch1:{query} music"


def build_youtube_playlist_search_url(query: str, search_kind: str) -> str:
    search_text = f"{query} full album" if search_kind == "album" else query
    encoded_query = urllib.parse.quote_plus(search_text)
    return (
        "https://www.youtube.com/results?"
        f"search_query={encoded_query}&sp={YOUTUBE_PLAYLIST_SEARCH_FILTER}"
    )


def resolve_query(query: str, search_kind: str | None = None) -> str:
    query = query.strip()
    parsed = urllib.parse.urlparse(query)

    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.lower().removeprefix("www.")
        if host not in YOUTUBE_HOSTS:
            raise ValueError("YouTube 링크나 검색어만 사용할 수 있어요.")
        return query

    if search_kind in {"album", "playlist"}:
        return build_youtube_playlist_search_url(query, search_kind)

    return build_youtube_search_query(query)


async def extract_first_info(
    query: str,
    resolved_query: str,
) -> dict:
    try:
        info = await extract_ytdl_info(YTDL_OPTIONS, resolved_query, "YouTube search")
    except asyncio.TimeoutError:
        raise ValueError(f"Timed out while searching for '{query}'.") from None

    if "entries" not in info:
        return info

    entries = [entry for entry in info["entries"] if entry]
    if entries:
        return entries[0]

    raise ValueError(f"No playable search results were found for '{query}'.")


def get_resolved_stream_url(info: dict) -> str | None:
    if info.get("_type") in {"url", "url_transparent"}:
        return None

    if not (info.get("formats") or info.get("requested_formats")):
        return None

    return info.get("url")


def get_thumbnail_url(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]

    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        return thumbnails[-1].get("url")

    return None


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


def get_entry_url(info: dict, fallback_url: str) -> str:
    raw_url = info.get("webpage_url") or info.get("url") or fallback_url
    video_id = get_video_id(info, raw_url)
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"

    parsed = urllib.parse.urlparse(raw_url)
    if not parsed.scheme and raw_url:
        return f"https://www.youtube.com/watch?v={raw_url}"

    return raw_url


BRACKETED_TITLE_PART_RE = re.compile(
    r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］|「[^」]*」|『[^』]*』"
)
VERSION_MARKER_RE = re.compile(
    r"\b(?:live|remix|cover|acoustic|instrumental|demo|version|edit|sped\s*up|slowed(?:\s*down)?|nightcore)\b"
    r"|라이브|리믹스|커버|어쿠스틱|인스트루멘털|데모"
    r"|ライブ|リミックス|カバー|アコースティック|インスト",
    flags=re.IGNORECASE,
)
NON_SONG_LABEL_RE = re.compile(
    r"\b(?:official|music\s*video|m\s*/?\s*v|audio|lyric(?:s|\s*video)?|visuali[sz]er|4k|hd|ost|original\s*soundtrack|theme\s*song)\b"
    r"|공식|뮤직비디오|가사|음원|오디오|주제가"
    r"|公式|ミュージックビデオ|オーディオ|歌詞|音源|主題歌",
    flags=re.IGNORECASE,
)
NON_SONG_SUFFIX_RE = re.compile(
    r"(?:\s*[-|:]\s*|\s+)"
    r"(?:official\s*(?:music\s*)?(?:video|mv|audio)|music\s*video|m\s*/?\s*v|official\s*audio|lyric(?:s|\s*video)?|visuali[sz]er|4k|hd|ost|original\s*soundtrack|theme\s*song|공식\s*(?:뮤직비디오|음원|오디오)?|뮤직비디오|가사|음원|오디오|公式\s*(?:mv|ミュージックビデオ|オーディオ|音源)?|ミュージックビデオ|オーディオ|歌詞|音源|主題歌)\s*$",
    flags=re.IGNORECASE,
)
ARTIST_CHANNEL_SUFFIX_RE = re.compile(
    r"(?:\s*-\s*topic|\s*official(?:\s+channel)?|vevo|\s*공식(?:\s*채널)?|\s*公式(?:チャンネル)?)$",
    flags=re.IGNORECASE,
)


def clean_track_title(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()

    def replace_bracketed_part(match: re.Match[str]) -> str:
        part = match.group(0)
        if VERSION_MARKER_RE.search(part):
            return part
        if NON_SONG_LABEL_RE.search(part):
            return " "
        return part

    value = BRACKETED_TITLE_PART_RE.sub(replace_bracketed_part, value)
    previous = None
    while previous != value:
        previous = value
        value = NON_SONG_SUFFIX_RE.sub("", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_identity_component(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).strip()


def normalize_artist_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = ARTIST_CHANNEL_SUFFIX_RE.sub("", value)
    return normalize_identity_component(value)


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
        stream_resolved_at=(
            info.get("_music_bot_extracted_at", time.monotonic())
            if stream_url
            else None
        ),
    )


def is_playlist_search_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host == "youtube.com" and parsed.path == "/results"


def get_playlist_result_url(info: dict) -> str:
    raw_url = info.get("webpage_url") or info.get("url") or ""
    if raw_url:
        parsed = urllib.parse.urlparse(raw_url)
        if parsed.scheme in {"http", "https"}:
            params = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/playlist" or "list" in params:
                return raw_url

    playlist_id = info.get("playlist_id") or info.get("id")
    if playlist_id and not re.fullmatch(r"[\w-]{11}", str(playlist_id)):
        return f"https://www.youtube.com/playlist?list={playlist_id}"

    raise ValueError("No YouTube playlist was found in the search results.")


def is_bulk_youtube_url(query: str) -> bool:
    parsed = urllib.parse.urlparse(query.strip())
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower().removeprefix("www.")
    if host not in YOUTUBE_HOSTS:
        return False

    return parsed.path == "/playlist"


def parse_music_request(query: str) -> tuple[str, str | None, bool]:
    query = query.strip()
    lowered = query.lower()
    prefixes: dict[str, tuple[str, bool]] = {
        "album:": ("album", True),
        "album ": ("album", True),
        "playlist:": ("playlist", True),
        "playlist ": ("playlist", True),
        "list:": ("playlist", True),
        "list ": ("playlist", True),
    }

    for prefix, (search_kind, bulk) in prefixes.items():
        if lowered.startswith(prefix):
            return query[len(prefix):].strip(), search_kind, bulk

    return query, None, is_bulk_youtube_url(query)


def clamp_auto_count(count: int) -> int:
    return max(1, min(count, MAX_AUTO_TRACKS))


def parse_auto_request(query: str) -> tuple[str, int] | None:
    query = query.strip()
    match = re.match(r"^auto(?::|\s+)(.*)$", query, flags=re.IGNORECASE)
    if not match:
        return None

    rest = match.group(1).strip()
    count = DEFAULT_AUTO_TRACKS
    count_match = re.match(r"^(\d+)\s+(.+)$", rest)
    if count_match:
        count = clamp_auto_count(int(count_match.group(1)))
        rest = count_match.group(2).strip()

    if not rest:
        raise ValueError("auto: 뒤에 곡명이나 아티스트를 입력해 주세요.")

    return rest, count


async def resolve_track_stream(track: Track) -> None:
    if track.is_local:
        source_path = Path(track.source_url)
        if not source_path.is_file():
            raise ValueError(f"로컬 테스트 음원 파일을 찾지 못했어요: {source_path}")
        track.stream_url = str(source_path)
        track.stream_resolved_at = time.monotonic()
        return

    stream_age = (
        time.monotonic() - track.stream_resolved_at
        if track.stream_resolved_at is not None
        else STREAM_URL_MAX_AGE_SECONDS
    )
    if track.stream_url and stream_age < STREAM_URL_MAX_AGE_SECONDS:
        return

    track.stream_url = None
    track.stream_resolved_at = None
    info = await extract_ytdl_info(
        YTDL_OPTIONS,
        track.source_url,
        "audio stream resolve",
        use_cache=False,
    )

    if "entries" in info:
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise ValueError("No playable search results were found.")
        info = entries[0]

    stream_url = get_resolved_stream_url(info)
    if not stream_url:
        raise ValueError("Could not resolve an audio stream for that query.")

    track.title = info.get("title") or track.title
    track.webpage_url = info.get("webpage_url") or track.webpage_url
    track.duration = info.get("duration") or track.duration
    track.stream_url = stream_url
    track.stream_resolved_at = time.monotonic()
    track.thumbnail_url = get_thumbnail_url(info) or track.thumbnail_url
    track.artist = info.get("artist") or info.get("creator") or track.artist
    track.song_name = info.get("track") or info.get("alt_title") or track.song_name
    track.uploader = info.get("uploader") or info.get("channel") or track.uploader


def get_music_test_audio_path() -> Path | None:
    if not MUSIC_TEST_AUDIO_FILE:
        return None
    path = resolve_project_path(MUSIC_TEST_AUDIO_FILE)
    if not path.is_file():
        raise ValueError(f"MUSIC_TEST_AUDIO_FILE을 찾지 못했어요: {path}")
    return path


def make_music_test_track(
    query: str,
    requester: str,
    requester_id: int | None = None,
) -> Track:
    source_path = get_music_test_audio_path()
    if source_path is None:
        raise RuntimeError("MUSIC_TEST_AUDIO_FILE is not configured")

    sequence = next(music_test_track_counter)
    return Track(
        title=f"[TEST {sequence}] {query}",
        webpage_url="",
        requester=requester,
        source_url=str(source_path),
        requester_id=requester_id,
        stream_url=str(source_path),
        stream_resolved_at=time.monotonic(),
        is_local=True,
    )


def make_music_test_tracks(
    query: str,
    requester: str,
    count: int,
    requester_id: int | None = None,
) -> list[Track]:
    return [
        make_music_test_track(query, requester, requester_id)
        for _ in range(count)
    ]


async def extract_track(
    query: str,
    requester: str,
    search_kind: str | None = None,
    requester_id: int | None = None,
) -> Track:
    if MUSIC_TEST_AUDIO_FILE:
        return make_music_test_track(query, requester, requester_id)

    resolved_query = resolve_query(query, search_kind)
    info = await extract_first_info(query, resolved_query)

    track = make_track_from_info(info, requester, resolved_query, requester_id)
    await resolve_track_stream(track)
    return track


async def extract_tracks(
    query: str,
    requester: str,
    search_kind: str | None = None,
    requester_id: int | None = None,
) -> list[Track]:
    if MUSIC_TEST_AUDIO_FILE:
        return make_music_test_tracks(
            query,
            requester,
            min(MUSIC_TEST_BULK_TRACKS, MAX_BULK_TRACKS),
            requester_id,
        )

    resolved_query = resolve_query(query, search_kind)
    info = await extract_ytdl_info(
        YTDL_PLAYLIST_OPTIONS, resolved_query, "playlist or album search"
    )

    if is_playlist_search_url(resolved_query):
        search_entries = [entry for entry in info.get("entries", []) if entry]
        if not search_entries:
            raise ValueError("No matching album or playlist was found.")

        first_result_url = get_playlist_result_url(search_entries[0])
        info = await extract_ytdl_info(
            YTDL_PLAYLIST_OPTIONS, first_result_url, "playlist or album resolve"
        )

    entries = [entry for entry in info.get("entries", []) if entry]
    if not entries:
        return [await extract_track(query, requester, search_kind, requester_id)]

    return [
        make_track_from_info(entry, requester, resolved_query, requester_id)
        for entry in entries[:MAX_BULK_TRACKS]
    ]


async def extract_auto_tracks(
    query: str,
    requester: str,
    count: int,
    requester_id: int | None = None,
) -> list[Track]:
    auto_count = clamp_auto_count(count)
    if MUSIC_TEST_AUDIO_FILE:
        return make_music_test_tracks(query, requester, auto_count, requester_id)

    seed_query = resolve_query(query)
    seed_info = await extract_first_info(query, seed_query)
    seed_track = make_track_from_info(seed_info, requester, seed_query, requester_id)
    seed_id = get_video_id(seed_info, seed_track.webpage_url)

    entries: list[dict] = []
    fallback_url = seed_query
    if seed_id:
        radio_url = f"https://www.youtube.com/watch?v={seed_id}&list=RD{seed_id}"
        fallback_url = radio_url
        try:
            radio_info = await extract_ytdl_info(
                YTDL_PLAYLIST_OPTIONS, radio_url, "YouTube radio mix"
            )
            entries = [entry for entry in radio_info.get("entries", []) if entry]
        except Exception:
            logger.exception("Failed to extract YouTube radio mix for %s", seed_id)

    if not entries:
        search_query = f"ytsearch{auto_count * 3}:{seed_track.title} radio mix"
        fallback_url = search_query
        info = await extract_ytdl_info(YTDL_OPTIONS, search_query, "auto fallback search")
        entries = [entry for entry in info.get("entries", []) if entry]

    tracks: list[Track] = []
    seen_keys: set[str] = set()

    for track in [seed_track]:
        key = normalize_track_key(track)
        seen_keys.add(key)
        tracks.append(track)
        if len(tracks) >= auto_count:
            return tracks

    for entry in entries:
        track = make_track_from_info(entry, requester, fallback_url, requester_id)
        if not get_video_id(entry, track.webpage_url):
            continue
        key = normalize_track_key(track)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        tracks.append(track)
        if len(tracks) >= auto_count:
            break

    if len(tracks) < auto_count and fallback_url.startswith("https://www.youtube.com/watch"):
        search_query = f"ytsearch{auto_count * 3}:{seed_track.title} radio mix"
        info = await extract_ytdl_info(
            YTDL_OPTIONS, search_query, "auto supplemental search"
        )
        for entry in [entry for entry in info.get("entries", []) if entry]:
            track = make_track_from_info(entry, requester, search_query, requester_id)
            key = normalize_track_key(track)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            tracks.append(track)
            if len(tracks) >= auto_count:
                break

    if not tracks:
        raise ValueError(f"관련 곡을 찾지 못했어요: {query}")

    return tracks


def remember_autoplay_track(state: GuildMusicState, track: Track) -> None:
    key = normalize_track_key(track)
    try:
        state.recent_track_keys.remove(key)
    except ValueError:
        pass
    state.recent_track_keys.append(key)


def get_autoplay_seed(state: GuildMusicState) -> Track | None:
    if state.queue:
        return state.queue[-1]
    return state.current


def get_autoplay_excluded_keys(state: GuildMusicState) -> set[str]:
    keys = set(state.recent_track_keys)
    if state.current is not None:
        keys.add(normalize_track_key(state.current))
    keys.update(normalize_track_key(track) for track in state.queue)
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
        if normalize_track_key(candidate) not in excluded_keys:
            return candidate
    return None


def cancel_autoplay_refill(state: GuildMusicState) -> None:
    task = state.autoplay_task
    if task and not task.done():
        task.cancel()
    state.autoplay_task = None


def autoplay_can_refill(state: GuildMusicState, generation: int) -> bool:
    voice = state.voice
    return (
        state.autoplay_enabled
        and generation == state.playback_generation
        and voice is not None
        and voice.is_connected()
        and len(state.queue) <= 1
    )


def get_autoplay_retry_delay(failure_count: int) -> int:
    index = min(max(0, failure_count), len(AUTOPLAY_RETRY_DELAYS_SECONDS) - 1)
    return AUTOPLAY_RETRY_DELAYS_SECONDS[index]


def schedule_autoplay_refill(
    guild_id: int,
) -> tuple[asyncio.Task[None] | None, bool]:
    state = get_state(guild_id)
    if not autoplay_can_refill(state, state.playback_generation):
        return None, False

    seed = get_autoplay_seed(state)
    if seed is None:
        return None, False

    if state.autoplay_task and not state.autoplay_task.done():
        return state.autoplay_task, False

    task = asyncio.create_task(
        refill_autoplay_queue(
            guild_id,
            state.playback_generation,
            seed,
        )
    )
    state.autoplay_task = task
    return task, True


async def refill_autoplay_queue(
    guild_id: int,
    generation: int,
    fallback_seed: Track,
) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    starting_track_id = state.current.track_id if state.current else None
    initial_seed_key = normalize_track_key(fallback_seed)
    added_track = False
    failure_count = 0
    candidate_count = clamp_auto_count(max(DEFAULT_AUTO_TRACKS, 5))

    try:
        while autoplay_can_refill(state, generation):
            seed = get_autoplay_seed(state) or fallback_seed
            fallback_seed = seed
            try:
                candidates = await extract_auto_tracks(
                    seed.webpage_url,
                    "자동재생",
                    candidate_count,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                retry_delay = get_autoplay_retry_delay(failure_count)
                failure_count += 1
                if isinstance(exc, YouTubeCircuitOpenError):
                    retry_delay = max(retry_delay, exc.retry_after_seconds)
                logger.warning(
                    "Autoplay search failed in guild %s; retrying in %s seconds: %s",
                    guild_id,
                    retry_delay,
                    exc,
                )
                await asyncio.sleep(retry_delay)
                continue

            if not autoplay_can_refill(state, generation):
                return

            candidate = select_autoplay_candidate(
                state,
                candidates,
                {
                    initial_seed_key,
                    normalize_track_key(seed),
                },
            )
            if candidate is None:
                retry_delay = get_autoplay_retry_delay(failure_count)
                failure_count += 1
                logger.warning(
                    "Autoplay found no new candidate in guild %s; retrying in %s seconds",
                    guild_id,
                    retry_delay,
                )
                await asyncio.sleep(retry_delay)
                continue

            should_start = False
            async with state.lock:
                if not autoplay_can_refill(state, generation):
                    return
                if normalize_track_key(candidate) in get_autoplay_excluded_keys(state):
                    continue

                state.queue.append(candidate)
                added_track = True
                voice = state.voice
                should_start = (
                    state.current is None
                    and voice is not None
                    and voice.is_connected()
                    and not voice.is_playing()
                    and not voice.is_paused()
                )

            logger.info(
                "Autoplay queued %s in guild %s",
                candidate.title,
                guild_id,
            )
            if state.current is not None:
                await update_control_panel(guild_id, state)

            if should_start:
                advance_task = state.advance_task
                if advance_task and advance_task is not current_task:
                    try:
                        await asyncio.shield(advance_task)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Playback advance failed before autoplay restart in guild %s",
                            guild_id,
                        )

                voice = state.voice
                if (
                    generation == state.playback_generation
                    and state.current is None
                    and state.queue
                    and voice is not None
                    and voice.is_connected()
                    and not voice.is_playing()
                    and not voice.is_paused()
                ):
                    schedule_play_next(guild_id)
            return
    finally:
        if state.autoplay_task is current_task:
            state.autoplay_task = None
            current_track_id = state.current.track_id if state.current else None
            if added_track and current_track_id != starting_track_id:
                schedule_autoplay_refill(guild_id)


async def ensure_voice(interaction: discord.Interaction, state: GuildMusicState) -> bool:
    user = interaction.user
    voice_state = getattr(user, "voice", None)
    channel = getattr(voice_state, "channel", None)

    if channel is None:
        await interaction.followup.send("먼저 음성 채널에 들어가 주세요.", ephemeral=True)
        return False

    if state.voice and not state.voice.is_connected():
        stop_playback(state)
        state.voice = None

    if state.voice and state.voice.is_connected():
        if state.voice.channel != channel:
            if state.current or state.queue or state.voice.is_playing() or state.voice.is_paused():
                await interaction.followup.send(
                    f"봇이 이미 {state.voice.channel.mention}에서 재생 중이에요. "
                    "같은 음성 채널에 들어와 주세요.",
                    ephemeral=True,
                )
                return False
            await state.voice.move_to(channel)
        return True

    state.voice = await channel.connect()
    return True


async def ensure_voice_for_member(
    member: discord.Member,
    state: GuildMusicState,
) -> tuple[bool, str | None]:
    voice_state = getattr(member, "voice", None)
    channel = getattr(voice_state, "channel", None)

    if channel is None:
        return False, "먼저 음성 채널에 들어가 주세요."

    if state.voice and not state.voice.is_connected():
        stop_playback(state)
        state.voice = None

    if state.voice and state.voice.is_connected():
        if state.voice.channel != channel:
            if state.current or state.queue or state.voice.is_playing() or state.voice.is_paused():
                return (
                    False,
                    f"봇이 이미 {state.voice.channel.mention}에서 재생 중이에요. "
                    "같은 음성 채널에 들어와 주세요.",
                )
            await state.voice.move_to(channel)
        return True, None

    state.voice = await channel.connect()
    return True, None


async def ensure_same_voice_channel(
    interaction: discord.Interaction,
    state: GuildMusicState,
) -> bool:
    voice = state.voice
    member_channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
    if voice and voice.is_connected() and member_channel == voice.channel:
        return True

    message = "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)
    return False


def stop_playback(state: GuildMusicState) -> None:
    state.playback_generation += 1
    state.stop_requested = True
    state.queue.clear()
    state.current = None
    cancel_autoplay_refill(state)

    if state.advance_task and not state.advance_task.done():
        state.advance_task.cancel()
    state.advance_task = None

    if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
        state.voice.stop()


def channel_has_human_listener(channel: discord.abc.Connectable) -> bool:
    return any(not member.bot for member in getattr(channel, "members", []))


def cancel_empty_channel_disconnect(state: GuildMusicState) -> None:
    task = state.empty_channel_task
    if task and not task.done():
        task.cancel()
    state.empty_channel_task = None


async def disconnect_from_empty_channel(guild_id: int, channel_id: int) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS)
        voice = state.voice
        if (
            voice is None
            or not voice.is_connected()
            or voice.channel.id != channel_id
            or channel_has_human_listener(voice.channel)
        ):
            return

        stop_playback(state)
        await show_idle_panel(guild_id, state)
        await voice.disconnect()
        if state.voice is voice:
            state.voice = None
        logger.info(
            "Left empty voice channel %s in guild %s",
            channel_id,
            guild_id,
        )
    finally:
        if state.empty_channel_task is current_task:
            state.empty_channel_task = None


def update_empty_channel_disconnect(state: GuildMusicState, guild_id: int) -> None:
    voice = state.voice
    if voice is None or not voice.is_connected():
        cancel_empty_channel_disconnect(state)
        return

    if channel_has_human_listener(voice.channel):
        cancel_empty_channel_disconnect(state)
        return

    if state.empty_channel_task and not state.empty_channel_task.done():
        return

    state.empty_channel_task = asyncio.create_task(
        disconnect_from_empty_channel(guild_id, voice.channel.id)
    )


def schedule_play_next(
    guild_id: int,
    *,
    announce: bool = True,
) -> tuple[asyncio.Task[None], bool]:
    state = get_state(guild_id)
    if state.advance_task and not state.advance_task.done():
        return state.advance_task, False

    task = asyncio.create_task(play_next(guild_id, announce=announce))
    state.advance_task = task
    return task, True


async def enqueue_tracks(
    guild_id: int,
    text_channel: discord.abc.Messageable,
    requester: discord.abc.User,
    query: str,
    *,
    initial_response: discord.Message | None = None,
    bulk: bool | None = None,
    search_kind: str | None = None,
    auto_count: int | None = None,
) -> bool:
    state = get_state(guild_id)
    state.announcement_channel = text_channel

    async def send_feedback(
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
        private: bool = False,
    ) -> discord.Message | None:
        if initial_response:
            await initial_response.edit(content=content, embed=embed, view=view)
            if view is None or private:
                asyncio.create_task(
                    delete_message_later(initial_response, MUSIC_FEEDBACK_DELETE_SECONDS)
                )
            return initial_response

        message = await text_channel.send(
            content=content,
            embed=embed,
            view=view,
            silent=is_silent_music_channel(text_channel),
        )
        if private:
            asyncio.create_task(delete_message_later(message, MUSIC_FEEDBACK_DELETE_SECONDS))
        return message

    try:
        auto_request = parse_auto_request(query)
        if auto_request:
            query, parsed_auto_count = auto_request
            auto_count = auto_count or parsed_auto_count
            bulk = True
        else:
            query, parsed_search_kind, parsed_bulk = parse_music_request(query)
            search_kind = search_kind or parsed_search_kind
            bulk = parsed_bulk if bulk is None else bulk

        tracks = (
            await extract_auto_tracks(query, requester.display_name, auto_count, requester.id)
            if auto_count is not None
            else (
                await extract_tracks(query, requester.display_name, search_kind, requester.id)
                if bulk
                else [await extract_track(query, requester.display_name, search_kind, requester.id)]
            )
        )
    except Exception as exc:
        logger.exception("Failed to extract track(s)")
        await send_feedback(content=f"곡을 찾지 못했어요: {exc}")
        return False

    if not tracks:
        await send_feedback(content="추가할 곡을 찾지 못했어요.")
        return False

    state.queue.extend(tracks)
    schedule_autoplay_refill(guild_id)
    should_start = (
        bool(state.voice)
        and state.current is None
        and not state.voice.is_playing()
        and not state.voice.is_paused()
    )
    playback_task: asyncio.Task[None] | None = None
    started_playback = False
    if should_start:
        playback_task, started_playback = schedule_play_next(guild_id, announce=False)

    if started_playback and playback_task:
        await playback_task
        if state.current:
            await update_control_panel(guild_id, state)
            await send_feedback(content="재생을 시작했어요.", private=True)
        else:
            await send_feedback(content="재생을 시작하지 못했어요. 로그를 확인해 주세요.")
        return state.current is not None

    if len(tracks) == 1:
        embed = make_track_embed(tracks[0], "Added to queue")
        embed.add_field(name="Position", value=str(len(state.queue)), inline=True)
    else:
        embed = make_bulk_embed(tracks, "Added playlist to queue")
        embed.add_field(name="Queue size", value=str(len(state.queue)), inline=True)

    await send_feedback(embed=embed, private=True)
    if state.current:
        await update_control_panel(guild_id, state)
    return True


def resolve_control_panel_channel(
    guild_id: int,
    state: GuildMusicState,
) -> discord.abc.Messageable | None:
    channel_id = get_music_channel_id(guild_id)
    if channel_id is not None:
        channel = bot.get_channel(channel_id)
        if channel is not None and hasattr(channel, "send"):
            return channel
    return state.announcement_channel


async def update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
) -> discord.Message | None:
    async with state.control_panel_lock:
        return await _update_control_panel(guild_id, state, channel=channel)


async def _update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
) -> discord.Message | None:
    control_channel = channel or resolve_control_panel_channel(guild_id, state)
    if control_channel is None:
        return None

    state.announcement_channel = control_channel
    control_channel_id = getattr(control_channel, "id", None)
    if state.control_message is not None:
        message_channel_id = getattr(
            getattr(state.control_message, "channel", None),
            "id",
            None,
        )
        if (
            control_channel_id is not None
            and message_channel_id is not None
            and message_channel_id != control_channel_id
        ):
            state.control_message = None

    if state.control_message is None:
        message_id = get_control_message_id(guild_id)
        fetch_message = getattr(control_channel, "fetch_message", None)
        if message_id is not None and fetch_message is not None:
            try:
                state.control_message = await fetch_message(message_id)
            except discord.NotFound:
                clear_control_message_id(guild_id)
            except discord.Forbidden:
                logger.warning(
                    "Missing permission to fetch music control panel in guild %s",
                    guild_id,
                )
                return None
            except discord.HTTPException:
                logger.exception(
                    "Failed to fetch music control panel in guild %s",
                    guild_id,
                )
                return None

    if state.current is None:
        embed = make_idle_player_embed()
        view = MusicControlView(guild_id, disabled=True)
    else:
        embed = make_player_embed(state.current, state)
        view = MusicControlView(guild_id)

    if state.control_message is not None:
        try:
            await state.control_message.edit(content=None, embed=embed, view=view)
            return state.control_message
        except discord.NotFound:
            state.control_message = None
            clear_control_message_id(guild_id)
        except discord.Forbidden:
            logger.warning(
                "Missing permission to edit music control panel in guild %s",
                guild_id,
            )
            return None
        except discord.HTTPException:
            logger.exception("Failed to edit music control panel in guild %s", guild_id)
            return None

    try:
        state.control_message = await control_channel.send(
            embed=embed,
            view=view,
            silent=is_silent_music_channel(control_channel),
        )
    except discord.Forbidden:
        logger.warning("Missing permission to send music control panel in guild %s", guild_id)
        return None
    except discord.HTTPException:
        logger.exception("Failed to send music control panel in guild %s", guild_id)
        return None

    set_control_message_id(guild_id, state.control_message.id)
    return state.control_message


async def show_idle_panel(guild_id: int, state: GuildMusicState) -> None:
    await update_control_panel(guild_id, state)


async def delete_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
) -> None:
    async with state.control_panel_lock:
        await _delete_control_panel(guild_id, state, channel=channel)


async def _delete_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
) -> None:
    control_channel = channel or resolve_control_panel_channel(guild_id, state)
    message = state.control_message
    if message is None and control_channel is not None:
        message_id = get_control_message_id(guild_id)
        fetch_message = getattr(control_channel, "fetch_message", None)
        if message_id is not None and fetch_message is not None:
            try:
                message = await fetch_message(message_id)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                message = None

    if message is not None:
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("Failed to delete music control panel in guild %s", guild_id)

    state.control_message = None
    clear_control_message_id(guild_id)


async def restore_control_panels() -> None:
    for guild in bot.guilds:
        channel_id = get_music_channel_id(guild.id)
        if channel_id is None:
            continue

        channel = guild.get_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            logger.warning(
                "Configured music channel %s was not found in guild %s",
                channel_id,
                guild.id,
            )
            continue

        state = get_state(guild.id)
        try:
            await update_control_panel(guild.id, state, channel=channel)
        except Exception:
            logger.exception("Failed to restore music control panel in guild %s", guild.id)


async def play_next(guild_id: int, announce: bool = True) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    generation = state.playback_generation

    try:
        if not ffmpeg_is_available():
            state.current = None
            state.queue.clear()
            cancel_autoplay_refill(state)
            await show_idle_panel(guild_id, state)
            await notify_playback_error(
                state,
                "FFmpeg를 찾지 못해서 재생할 수 없어요. "
                "FFmpeg를 설치하거나 `.env`에 `FFMPEG_PATH`를 설정해 주세요.",
            )
            logger.error("FFmpeg executable was not found: %s", FFMPEG_EXECUTABLE)
            return

        while generation == state.playback_generation:
            async with state.lock:
                if generation != state.playback_generation:
                    return
                voice = state.voice
                if voice is None or not voice.is_connected():
                    state.current = None
                    should_delete_panel = True
                    track = None
                elif voice.is_playing() or voice.is_paused():
                    return
                elif not state.queue:
                    state.current = None
                    should_delete_panel = True
                    track = None
                else:
                    track = state.queue.popleft()
                    state.current = track
                    state.skip_requested = False
                    state.stop_requested = False
                    should_delete_panel = False

            if should_delete_panel:
                await show_idle_panel(guild_id, state)
                return
            assert track is not None

            try:
                await resolve_track_stream(track)
                ffmpeg_options = FFMPEG_LOCAL_OPTIONS if track.is_local else FFMPEG_OPTIONS
                ffmpeg_source = discord.FFmpegPCMAudio(
                    track.stream_url,
                    executable=FFMPEG_EXECUTABLE,
                    **ffmpeg_options,
                )
                source = discord.PCMVolumeTransformer(ffmpeg_source, volume=BOT_VOLUME)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to create FFmpeg source for %s", track.title)
                if state.current is track and generation == state.playback_generation:
                    state.current = None
                continue

            try:
                async with state.lock:
                    voice = state.voice
                    can_start = (
                        generation == state.playback_generation
                        and state.current is track
                        and voice is not None
                        and voice.is_connected()
                        and not voice.is_playing()
                        and not voice.is_paused()
                    )
                    if not can_start:
                        source.cleanup()
                        return

                    def after_playback(error: Exception | None) -> None:
                        if error:
                            logger.warning("Playback error: %s", error)

                        def advance() -> None:
                            if (
                                generation != state.playback_generation
                                or state.current is not track
                            ):
                                return

                            if state.repeat_one and not state.skip_requested and not state.stop_requested:
                                track.stream_url = None
                                track.stream_resolved_at = None
                                state.queue.appendleft(track)
                            state.current = None
                            schedule_play_next(guild_id)

                        bot.loop.call_soon_threadsafe(advance)

                    try:
                        voice.play(source, after=after_playback)
                    except Exception:
                        source.cleanup()
                        logger.exception("Failed to start playback for %s", track.title)
                        if state.current is track:
                            state.current = None
                        continue
            except asyncio.CancelledError:
                if not voice.is_playing():
                    source.cleanup()
                raise

            remember_autoplay_track(state, track)
            schedule_autoplay_refill(guild_id)
            if announce and state.current is track:
                await update_control_panel(guild_id, state)
            return
    finally:
        if state.advance_task is current_task:
            state.advance_task = None


def guild_only_error() -> str:
    return "이 명령어는 디스코드 서버 안에서만 사용할 수 있어요."


@bot.event
async def on_ready() -> None:
    global commands_synced
    load_music_channel_config()
    logger.info("Logged in as %s", bot.user)
    if ffmpeg_is_available():
        logger.info("Using FFmpeg executable: %s", FFMPEG_EXECUTABLE)
    else:
        logger.error(
            "FFmpeg executable was not found. Set FFMPEG_PATH in .env or add ffmpeg to PATH."
        )
    if MUSIC_TEST_AUDIO_FILE:
        logger.warning(
            "Local music test mode is enabled with MUSIC_TEST_AUDIO_FILE=%s; "
            "YouTube will not be queried.",
            MUSIC_TEST_AUDIO_FILE,
        )

    await restore_control_panels()

    if commands_synced:
        return

    if DEV_GUILD_ID:
        guild = discord.Object(id=int(DEV_GUILD_ID))
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.info("Synced %s command(s) to dev guild %s", len(synced), DEV_GUILD_ID)
    else:
        synced = await bot.tree.sync()
        logger.info("Synced %s global command(s)", len(synced))
    commands_synced = True


@bot.event
async def on_message(message: discord.Message) -> None:
    if message.author.bot or message.guild is None:
        return

    music_channel_id = get_music_channel_id(message.guild.id)
    if music_channel_id is None or message.channel.id != music_channel_id:
        return

    query = message.content.strip()
    if not query or query.startswith(("/", "!")):
        return

    if not isinstance(message.author, discord.Member):
        return

    state = get_state(message.guild.id)
    ok, error = await ensure_voice_for_member(message.author, state)
    if not ok:
        error_message = await message.reply(
            error,
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
        asyncio.create_task(delete_message_later(error_message, MUSIC_FEEDBACK_DELETE_SECONDS))
        await delete_music_request_message(message)
        return

    async with message.channel.typing():
        loading_message = await message.reply(
            "곡을 찾고 있어요...",
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
        await enqueue_tracks(
            message.guild.id,
            message.channel,
            message.author,
            query,
            initial_response=loading_message,
        )
        await delete_music_request_message(message)

    await bot.process_commands(message)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member.bot:
        return

    state = music_states.get(member.guild.id)
    if state is None or state.voice is None or not state.voice.is_connected():
        return

    bot_channel = state.voice.channel
    if before.channel != bot_channel and after.channel != bot_channel:
        return

    update_empty_channel_disconnect(state, member.guild.id)


@bot.tree.command(
    name="setupmusic",
    description="Create or select a text channel for quick music requests.",
)
@app_commands.describe(channel="Existing channel to use. Leave empty to create one.")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_channels=True)
async def setup_music_channel(
    interaction: discord.Interaction,
    channel: discord.TextChannel | None = None,
) -> None:
    await interaction.response.defer(ephemeral=True)
    if interaction.guild is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    selected_channel = channel
    if selected_channel is None:
        selected_channel = discord.utils.get(
            interaction.guild.text_channels,
            name=MUSIC_CHANNEL_NAME,
        )

    if selected_channel is None:
        selected_channel = await interaction.guild.create_text_channel(
            MUSIC_CHANNEL_NAME,
            reason="Music request channel setup",
        )

    guild_id = interaction.guild.id
    state = get_state(guild_id)
    previous_channel_id = get_music_channel_id(guild_id)
    if previous_channel_id is not None and previous_channel_id != selected_channel.id:
        previous_channel = interaction.guild.get_channel(previous_channel_id)
        await delete_control_panel(guild_id, state, channel=previous_channel)

    set_music_channel(guild_id, selected_channel.id)
    state.announcement_channel = selected_channel
    await update_control_panel(guild_id, state, channel=selected_channel)
    await interaction.followup.send(
        f"{selected_channel.mention} 채널을 음악 신청 전용 채널로 설정했어요. "
        "이제 그 채널에 곡명이나 YouTube URL만 보내면 재생되고, 컨트롤 패널은 항상 유지됩니다.",
        ephemeral=True,
    )


@setup_music_channel.error
async def setup_music_channel_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    async def send_error(content: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    if isinstance(error, app_commands.MissingPermissions):
        await send_error("이 설정은 채널 관리 권한이 있는 사람만 사용할 수 있어요.")
        return

    logger.exception("setupmusic failed", exc_info=error)
    await send_error("전용 채널을 설정하는 중 문제가 생겼어요.")


@bot.tree.command(name="join", description="Join your current voice channel.")
@app_commands.guild_only()
async def join(interaction: discord.Interaction) -> None:
    await interaction.response.defer(ephemeral=True)
    if interaction.guild_id is None:
        await interaction.followup.send(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if await ensure_voice(interaction, state):
        state.announcement_channel = interaction.channel
        await interaction.followup.send("음성 채널에 들어왔어요.", ephemeral=True)


@bot.tree.command(name="pause", description="Pause the current track.")
@app_commands.guild_only()
async def pause(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_playing():
        state.voice.pause()
        await interaction.response.send_message("일시정지했어요.", ephemeral=True)
        return

    await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="resume", description="Resume the paused track.")
@app_commands.guild_only()
async def resume(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_paused():
        state.voice.resume()
        await interaction.response.send_message("다시 재생할게요.", ephemeral=True)
        return

    await interaction.response.send_message("일시정지된 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="skip", description="Skip the current track.")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
        state.skip_requested = True
        state.voice.stop()
        await interaction.response.send_message("다음 곡으로 넘어갈게요.")
        return

    await interaction.response.send_message("스킵할 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
@app_commands.guild_only()
async def stop(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    stop_playback(state)

    await show_idle_panel(interaction.guild_id, state)
    await interaction.response.send_message("재생을 멈추고 대기열을 비웠어요.")


@bot.tree.command(name="queue", description="Show the current music queue.")
@app_commands.guild_only()
async def show_queue(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    await interaction.response.send_message(
        embed=make_queue_embed(state),
        view=QueueManageView(interaction.guild_id) if state.queue else None,
        ephemeral=True,
    )


@bot.tree.command(name="remove", description="Remove a track from the queue by position.")
@app_commands.describe(position="Queue position to remove, starting from 1")
@app_commands.guild_only()
async def remove_from_queue(interaction: discord.Interaction, position: int) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    removed = remove_queued_track(state, position - 1)
    if removed is None:
        await interaction.response.send_message("그 번호의 대기열 곡을 찾지 못했어요.", ephemeral=True)
        return

    schedule_autoplay_refill(interaction.guild_id)
    if state.current:
        await update_control_panel(interaction.guild_id, state)

    await interaction.response.send_message(
        f"대기열에서 `{removed.title}`을 삭제했어요.",
        ephemeral=True,
    )


@bot.tree.command(name="nowplaying", description="Show the current track.")
@app_commands.guild_only()
async def now_playing(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if state.current:
        await interaction.response.send_message(
            embed=make_player_embed(state.current, state),
            view=MusicControlView(interaction.guild_id),
        )
        return

    await interaction.response.send_message("지금 재생 중인 곡이 없어요.", ephemeral=True)


@bot.tree.command(name="leave", description="Disconnect from voice and clear the queue.")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await interaction.response.send_message(guild_only_error(), ephemeral=True)
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    cancel_empty_channel_disconnect(state)
    stop_playback(state)

    if state.voice and state.voice.is_connected():
        await show_idle_panel(interaction.guild_id, state)
        await state.voice.disconnect()
        state.voice = None
        await interaction.response.send_message("음성 채널에서 나왔어요.")
        return

    await interaction.response.send_message("이미 음성 채널에 없어요.", ephemeral=True)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Put it in .env or your environment.")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
