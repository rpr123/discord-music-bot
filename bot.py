from __future__ import annotations

import asyncio
import copy
import functools
import html
import io
import json
import itertools
import logging
import math
import os
import random
import re
import shutil
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Deque

import discord
import requests
import yt_dlp
from discord import app_commands
from discord.ext import commands
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials

try:
    from sudachipy import dictionary as sudachi_dictionary
except ImportError:
    sudachi_dictionary = None


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


def parse_string_map_env(name: str) -> dict[str, str]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return {}
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("%s must be a JSON object. Ignoring its value.", name)
        return {}
    if not isinstance(payload, dict):
        logger.warning("%s must be a JSON object. Ignoring its value.", name)
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in payload.items()
        if str(key).strip() and str(value).strip()
    }


MAX_BULK_TRACKS = parse_positive_int_env("MAX_BULK_TRACKS", 50)
MUSIC_FEEDBACK_DELETE_SECONDS = parse_positive_int_env("MUSIC_FEEDBACK_DELETE_SECONDS", 10)
EPHEMERAL_RESPONSE_DELETE_SECONDS = parse_positive_int_env(
    "EPHEMERAL_RESPONSE_DELETE_SECONDS", 15
)
QUEUE_DELETE_RESPONSE_DELETE_SECONDS = parse_positive_int_env(
    "QUEUE_DELETE_RESPONSE_DELETE_SECONDS", 30
)
DEFAULT_AUTO_TRACKS = parse_positive_int_env("DEFAULT_AUTO_TRACKS", 8)
MAX_AUTO_TRACKS = parse_positive_int_env("MAX_AUTO_TRACKS", 25)
BOT_VOLUME = parse_volume_env("BOT_VOLUME", 0.2)
DISCORD_EMBED_FIELD_LIMIT = 1024
QUEUE_SELECT_LIMIT = 25
LYRICS_API_URL = os.getenv("LYRICS_API_URL", "https://lrclib.net/api/search")
LYRICS_REQUEST_TIMEOUT_SECONDS = parse_positive_int_env(
    "LYRICS_REQUEST_TIMEOUT_SECONDS", 10
)
YOUTUBE_LYRICS_FALLBACK = os.getenv("YOUTUBE_LYRICS_FALLBACK", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
LYRICS_INLINE_LIMIT = 3900
LYRICS_NATIVE_SCRIPT_MIN_RATIO = 0.3
LYRICS_NATIVE_SCRIPT_SCORE_WINDOW = 20
LYRICS_DURATION_MATCH_TOLERANCE_SECONDS = 8
LYRICS_TRANSLATION_ENABLED = os.getenv(
    "LYRICS_TRANSLATION_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
NAMUWIKI_LYRICS_ENABLED = os.getenv(
    "NAMUWIKI_LYRICS_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
NAMUWIKI_PAGE_BASE_URL = os.getenv(
    "NAMUWIKI_PAGE_BASE_URL", "https://namu.wiki/w"
).rstrip("/")
NAMUWIKI_API_BASE_URL = os.getenv(
    "NAMUWIKI_API_BASE_URL", "https://wiki-api.namu.la/api"
).rstrip("/")
NAMUWIKI_API_TOKEN = os.getenv("NAMUWIKI_API_TOKEN", "").strip() or None
NAMUWIKI_REQUEST_TIMEOUT_SECONDS = parse_positive_int_env(
    "NAMUWIKI_REQUEST_TIMEOUT_SECONDS", 10
)
NAMUWIKI_REQUEST_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "NAMUWIKI_REQUEST_INTERVAL_SECONDS", 1.1
)
NAMUWIKI_DOCUMENT_OVERRIDES = parse_string_map_env("NAMUWIKI_DOCUMENT_OVERRIDES")
LYRICS_READING_ENABLED = os.getenv("LYRICS_READING_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YTDL_EXTRACT_TIMEOUT_SECONDS = parse_positive_int_env("YTDL_EXTRACT_TIMEOUT_SECONDS", 45)
YTDL_MAX_CONCURRENT_EXTRACTIONS = parse_positive_int_env(
    "YTDL_MAX_CONCURRENT_EXTRACTIONS", 1
)
STREAM_URL_MAX_AGE_SECONDS = parse_positive_int_env("STREAM_URL_MAX_AGE_SECONDS", 900)
YTDL_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env("YTDL_MIN_INTERVAL_SECONDS", 6.0)
YTDL_CACHE_TTL_SECONDS = parse_positive_int_env("YTDL_CACHE_TTL_SECONDS", 600)
YTDL_CACHE_MAX_ENTRIES = parse_positive_int_env("YTDL_CACHE_MAX_ENTRIES", 128)
YOUTUBE_SEARCH_CANDIDATES = min(
    parse_positive_int_env("YOUTUBE_SEARCH_CANDIDATES", 10),
    20,
)
YOUTUBE_MUSIC_SEARCH_ENABLED = os.getenv(
    "YOUTUBE_MUSIC_SEARCH_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS", 1.0
)
YOUTUBE_MUSIC_AUTH_FILE = os.getenv("YOUTUBE_MUSIC_AUTH_FILE", "").strip() or None
YOUTUBE_MUSIC_OAUTH_CLIENT_ID = (
    os.getenv("YOUTUBE_MUSIC_OAUTH_CLIENT_ID", "").strip() or None
)
YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET = (
    os.getenv("YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET", "").strip() or None
)
YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS = parse_positive_int_env(
    "YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS", 5
)
YOUTUBE_MUSIC_LANGUAGE = os.getenv("YOUTUBE_MUSIC_LANGUAGE", "en").strip() or "en"
YOUTUBE_MUSIC_LOCATION = os.getenv("YOUTUBE_MUSIC_LOCATION", "").strip()
YOUTUBE_CIRCUIT_BREAKER_SECONDS = parse_positive_int_env(
    "YOUTUBE_CIRCUIT_BREAKER_SECONDS", 1800
)
MUSIC_TEST_BULK_TRACKS = parse_positive_int_env("MUSIC_TEST_BULK_TRACKS", 3)
EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS = 3
AUTOPLAY_RETRY_DELAYS_SECONDS = (60, 120, 300, 900, 1800)
AUTOPLAY_HISTORY_SIZE = 50
AUTOPLAY_BUTTON_CUSTOM_ID = "music:autoplay"
CONTROL_PANEL_HISTORY_LIMIT = 100
PLAYING_PANEL_TITLE = "💿 지금 재생 중"
IDLE_PANEL_TITLE = "🎵 재생 대기 중"
CONTROL_PANEL_TITLES = frozenset({PLAYING_PANEL_TITLE, IDLE_PANEL_TITLE})

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

YTDL_SEARCH_OPTIONS = {
    **YTDL_BASE_OPTIONS,
    "noplaylist": True,
    "extract_flat": "in_playlist",
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
youtube_music_client: YTMusic | None = None
youtube_music_client_lock = threading.Lock()
youtube_music_rate_lock = asyncio.Lock()
youtube_music_last_request_started_at = 0.0
youtube_music_cache_lock = asyncio.Lock()
youtube_music_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
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


async def wait_for_youtube_music_interval() -> None:
    global youtube_music_last_request_started_at
    async with youtube_music_rate_lock:
        elapsed = time.monotonic() - youtube_music_last_request_started_at
        delay = max(0.0, YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
        youtube_music_last_request_started_at = time.monotonic()


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


def get_youtube_music_client() -> YTMusic:
    global youtube_music_client
    with youtube_music_client_lock:
        if youtube_music_client is not None:
            return youtube_music_client

        auth_path: str | None = None
        if YOUTUBE_MUSIC_AUTH_FILE:
            resolved_auth_path = resolve_project_path(YOUTUBE_MUSIC_AUTH_FILE)
            if not resolved_auth_path.is_file():
                raise FileNotFoundError(
                    f"YouTube Music auth file was not found: {resolved_auth_path}"
                )
            auth_path = str(resolved_auth_path)

        session = requests.Session()
        session.request = functools.partial(
            session.request,
            timeout=YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
        )
        oauth_credentials: OAuthCredentials | None = None
        if YOUTUBE_MUSIC_OAUTH_CLIENT_ID or YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET:
            if not (
                YOUTUBE_MUSIC_OAUTH_CLIENT_ID
                and YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET
            ):
                raise ValueError(
                    "YOUTUBE_MUSIC_OAUTH_CLIENT_ID and "
                    "YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET must be set together."
                )
            oauth_credentials = OAuthCredentials(
                client_id=YOUTUBE_MUSIC_OAUTH_CLIENT_ID,
                client_secret=YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET,
                session=session,
            )
        youtube_music_client = YTMusic(
            auth=auth_path,
            requests_session=session,
            language=YOUTUBE_MUSIC_LANGUAGE,
            location=YOUTUBE_MUSIC_LOCATION,
            oauth_credentials=oauth_credentials,
        )
        return youtube_music_client


def get_youtube_music_cache_key(query: str) -> str:
    return unicodedata.normalize("NFKC", query).casefold().strip()


async def get_cached_youtube_music_results(query: str) -> list[dict] | None:
    if YTDL_CACHE_TTL_SECONDS <= 0:
        return None

    cache_key = get_youtube_music_cache_key(query)
    async with youtube_music_cache_lock:
        cached = youtube_music_cache.get(cache_key)
        if cached is None:
            return None
        cached_at, results = cached
        if time.monotonic() - cached_at >= YTDL_CACHE_TTL_SECONDS:
            youtube_music_cache.pop(cache_key, None)
            return None
        youtube_music_cache.move_to_end(cache_key)
        return copy.deepcopy(results)


async def cache_youtube_music_results(query: str, results: list[dict]) -> None:
    if YTDL_CACHE_TTL_SECONDS <= 0:
        return

    cache_key = get_youtube_music_cache_key(query)
    async with youtube_music_cache_lock:
        youtube_music_cache[cache_key] = (
            time.monotonic(),
            copy.deepcopy(results),
        )
        youtube_music_cache.move_to_end(cache_key)
        while len(youtube_music_cache) > YTDL_CACHE_MAX_ENTRIES:
            youtube_music_cache.popitem(last=False)


async def search_youtube_music(query: str) -> list[dict]:
    if not YOUTUBE_MUSIC_SEARCH_ENABLED:
        return []

    cached = await get_cached_youtube_music_results(query)
    if cached is not None:
        logger.info("YouTube Music cache hit: %s", query)
        return cached

    ensure_youtube_circuit_closed()
    logger.info("YouTube Music search start: %s", query)

    def search() -> list[dict]:
        results = get_youtube_music_client().search(
            query,
            limit=YOUTUBE_SEARCH_CANDIDATES,
        )
        return [result for result in results if isinstance(result, dict)]

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    try:
        await asyncio.wait_for(
            ytdl_semaphore.acquire(),
            timeout=YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("YouTube Music search queue timed out: %s", query)
        raise

    try:
        ensure_youtube_circuit_closed()
        await wait_for_youtube_music_interval()
    except BaseException:
        ytdl_semaphore.release()
        raise

    worker = asyncio.create_task(asyncio.to_thread(search))

    def search_finished(task: asyncio.Task[list[dict]]) -> None:
        ytdl_semaphore.release()
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            trip_youtube_circuit(error)

    worker.add_done_callback(search_finished)
    remaining_timeout = max(
        0.1,
        YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS - (loop.time() - started_at),
    )
    try:
        results = await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=remaining_timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "YouTube Music search timed out after %s seconds: %s",
            YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
            query,
        )
        raise
    except Exception as error:
        trip_youtube_circuit(error)
        raise

    await cache_youtube_music_results(query, results)
    logger.info("YouTube Music search done: %s result(s)", len(results))
    return results


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


def log_discord_http_error(action: str, error: discord.HTTPException) -> None:
    logger.warning(
        "Discord API failed while %s: HTTP %s (code %s)",
        action,
        getattr(error, "status", "unknown"),
        getattr(error, "code", "unknown"),
    )


async def send_music_request_reply(
    message: discord.Message,
    content: str,
) -> discord.Message | None:
    try:
        return await message.reply(
            content,
            mention_author=False,
            silent=is_silent_music_channel(message.channel),
        )
    except discord.HTTPException as error:
        log_discord_http_error("sending a music request reply", error)
        return None


async def delete_music_request_message(message: discord.Message) -> None:
    if not MUSIC_CHANNEL_DELETE_REQUESTS:
        return

    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting a music request", error)


async def delete_message_later(message: discord.Message, delay_seconds: int) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting temporary music feedback", error)


async def notify_playback_error(state: GuildMusicState, content: str) -> None:
    if not state.announcement_channel:
        return

    try:
        await state.announcement_channel.send(
            content,
            silent=is_silent_music_channel(state.announcement_channel),
        )
    except discord.HTTPException as error:
        log_discord_http_error("sending a playback error message", error)


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
    control_panel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    advance_task: asyncio.Task[None] | None = None
    autoplay_task: asyncio.Task[None] | None = None
    lyrics_task: asyncio.Task[None] | None = None
    lyrics_message: discord.Message | None = None
    namuwiki_notice_message: discord.Message | None = None
    lyrics_view: discord.ui.View | None = None
    private_lyrics_messages: dict[str, list[discord.WebhookMessage]] = field(
        default_factory=dict
    )
    queue_cleanup_tasks: dict[int, asyncio.Task[None]] = field(default_factory=dict)
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


async def send_ephemeral_response(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    delete_after: float = EPHEMERAL_RESPONSE_DELETE_SECONDS,
) -> None:
    options: dict[str, object] = {
        "ephemeral": True,
        "delete_after": delete_after,
    }
    if embed is not None:
        options["embed"] = embed
    if view is not None:
        options["view"] = view
    await interaction.response.send_message(content, **options)


async def send_ephemeral_followup(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    file: discord.File | None = None,
    view: discord.ui.View | None = None,
    delete_after: float | None = EPHEMERAL_RESPONSE_DELETE_SECONDS,
) -> discord.WebhookMessage | None:
    options: dict[str, object] = {
        "ephemeral": True,
        "wait": True,
    }
    if embed is not None:
        options["embed"] = embed
    if file is not None:
        options["file"] = file
    if view is not None:
        options["view"] = view
    message = await interaction.followup.send(content, **options)
    if message is not None and delete_after is not None:
        await message.delete(delay=delete_after)
    return message


async def delete_private_interaction_message(
    message: discord.WebhookMessage,
) -> None:
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting a private interaction message", error)


async def register_private_lyrics_message(
    guild_id: int,
    track: Track,
    message: discord.WebhookMessage,
) -> None:
    state = get_state(guild_id)
    if state.current is not track:
        await delete_private_interaction_message(message)
        return
    state.private_lyrics_messages.setdefault(track.track_id, []).append(message)


def schedule_private_lyrics_cleanup(
    state: GuildMusicState,
    track_id: str | None = None,
) -> None:
    if track_id is None:
        messages = [
            message
            for tracked_messages in state.private_lyrics_messages.values()
            for message in tracked_messages
        ]
        state.private_lyrics_messages.clear()
    else:
        messages = state.private_lyrics_messages.pop(track_id, [])

    for message in messages:
        asyncio.create_task(delete_private_interaction_message(message))


async def delete_queue_message_after(
    state: GuildMusicState,
    message_id: int,
    message: discord.InteractionMessage,
    delay_seconds: float,
) -> None:
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(delay_seconds)
        try:
            await message.delete()
        except discord.NotFound:
            pass
        except discord.HTTPException as error:
            log_discord_http_error("deleting a private queue message", error)
    finally:
        if state.queue_cleanup_tasks.get(message_id) is current_task:
            state.queue_cleanup_tasks.pop(message_id, None)


def schedule_queue_message_cleanup(
    state: GuildMusicState,
    message: discord.InteractionMessage | None,
    delay_seconds: float,
) -> asyncio.Task[None] | None:
    if message is None:
        return None
    message_id = getattr(message, "id", None)
    if not isinstance(message_id, int):
        return None

    previous_task = state.queue_cleanup_tasks.pop(message_id, None)
    if previous_task is not None and not previous_task.done():
        previous_task.cancel()

    task = asyncio.create_task(
        delete_queue_message_after(
            state,
            message_id,
            message,
            delay_seconds,
        )
    )
    state.queue_cleanup_tasks[message_id] = task
    return task


def cancel_queue_message_cleanups(state: GuildMusicState) -> None:
    for task in state.queue_cleanup_tasks.values():
        if not task.done():
            task.cancel()
    state.queue_cleanup_tasks.clear()


async def send_queue_management_response(
    interaction: discord.Interaction,
    guild_id: int,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
) -> None:
    options: dict[str, object] = {"ephemeral": True}
    if embed is not None:
        options["embed"] = embed
    if view is not None:
        options["view"] = view
    await interaction.response.send_message(content, **options)
    try:
        message = await interaction.original_response()
    except discord.HTTPException as error:
        log_discord_http_error("fetching a private queue message", error)
        return
    schedule_queue_message_cleanup(
        get_state(guild_id),
        message,
        EPHEMERAL_RESPONSE_DELETE_SECONDS,
    )


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
        title=PLAYING_PANEL_TITLE,
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
        title=IDLE_PANEL_TITLE,
        description=(
            "음성 채널에 들어간 뒤 아래 형식으로 메시지를 보내 주세요.\n\n"
            "`곡명` 또는 `YouTube URL`\n"
            "`album: 앨범명`\n"
            "`playlist: 플레이리스트명`\n"
            "`auto: 곡명`, `auto12: 곡명` 또는 `auto 12: 곡명`\n\n"
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


def describe_queue_selection(state: GuildMusicState, track_id: str | None) -> str:
    if track_id is None:
        return "선택 안 함"

    for index, track in enumerate(state.queue, start=1):
        if track.track_id == track_id:
            return f"{index}. {truncate_text(track.title, 72)}"
    return "대기열에서 찾을 수 없음"


def make_lyrics_embed(track: Track, description: str) -> discord.Embed:
    song_title = track.song_name or track.title
    embed = discord.Embed(
        title=f"가사 · {truncate_text(song_title, 220)}",
        description=description,
        color=discord.Color.blurple(),
    )
    artist = track.artist or track.uploader
    if artist:
        embed.set_author(name=truncate_text(artist, 200))

    source = track.lyrics_source or "LRCLIB → YouTube 수동 자막"
    embed.set_footer(text=f"{source} · 원문 가사")
    return embed


def make_lyrics_variant_embed(
    track: Track,
    label: str,
    description: str,
    source: str,
    source_url: str | None = None,
) -> discord.Embed:
    song_title = track.song_name or track.title
    embed = discord.Embed(
        title=f"{label} · {truncate_text(song_title, 220)}",
        description=description,
        color=discord.Color.blurple(),
    )
    artist = track.artist or track.uploader
    if artist:
        embed.set_author(name=truncate_text(artist, 200))
    if source_url:
        embed.url = source_url
    embed.set_footer(text=source)
    return embed


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
            for index, track in enumerate(
                list(state.queue)[:QUEUE_SELECT_LIMIT],
                start=1,
            )
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
        schedule_queue_message_cleanup(
            state,
            interaction.message,
            QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )


class QueueManageView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        if get_state(guild_id).queue:
            self.add_item(QueueRemoveSelect(guild_id))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_same_voice_channel(interaction, get_state(self.guild_id))


class QueueRangeBoundarySelect(discord.ui.Select):
    def __init__(
        self,
        range_view: QueueRangeDeleteView,
        boundary: str,
        *,
        row: int,
    ):
        self.range_view = range_view
        self.boundary = boundary
        state = get_state(range_view.guild_id)
        options = [
            discord.SelectOption(
                label=truncate_option_text(f"{index}. {track.title}"),
                description=truncate_option_text(f"신청자: {track.requester}", 100),
                value=track.track_id,
            )
            for index, track in enumerate(
                list(state.queue)[:QUEUE_SELECT_LIMIT],
                start=1,
            )
        ]
        boundary_label = "시작" if boundary == "start" else "끝"
        super().__init__(
            placeholder=f"삭제 구간의 {boundary_label} 곡을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
            row=row,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_track_id = self.values[0]
        if self.boundary == "start":
            self.range_view.start_track_id = selected_track_id
        else:
            self.range_view.end_track_id = selected_track_id

        for option in self.options:
            option.default = option.value == selected_track_id
        self.range_view.confirm_button.disabled = not (
            self.range_view.start_track_id and self.range_view.end_track_id
        )
        state = get_state(self.range_view.guild_id)
        await interaction.response.edit_message(
            content=self.range_view.make_selection_content(state),
            embed=make_queue_embed(state),
            view=self.range_view,
        )


class QueueRangeDeleteButton(discord.ui.Button):
    def __init__(self, range_view: QueueRangeDeleteView):
        self.range_view = range_view
        super().__init__(
            label="선택 구간 삭제",
            emoji="✂️",
            style=discord.ButtonStyle.danger,
            disabled=True,
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.range_view.delete_selected_range(interaction)


class QueueRangeDeleteView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.start_track_id: str | None = None
        self.end_track_id: str | None = None
        self.add_item(QueueRangeBoundarySelect(self, "start", row=0))
        self.add_item(QueueRangeBoundarySelect(self, "end", row=1))
        self.confirm_button = QueueRangeDeleteButton(self)
        self.add_item(self.confirm_button)

    def make_selection_content(self, state: GuildMusicState) -> str:
        return (
            "삭제할 구간의 시작 곡과 끝 곡을 선택한 뒤 확인 버튼을 누르세요.\n"
            f"시작: {describe_queue_selection(state, self.start_track_id)}\n"
            f"끝: {describe_queue_selection(state, self.end_track_id)}"
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await ensure_same_voice_channel(interaction, get_state(self.guild_id))

    async def delete_selected_range(self, interaction: discord.Interaction) -> None:
        if self.start_track_id is None or self.end_track_id is None:
            await interaction.response.edit_message(
                content=self.make_selection_content(get_state(self.guild_id)),
                view=self,
            )
            return

        state = get_state(self.guild_id)
        async with state.lock:
            result = remove_queued_track_range_by_ids(
                state,
                self.start_track_id,
                self.end_track_id,
            )

        if result is None:
            await interaction.response.edit_message(
                content=(
                    "대기열이 변경되어 선택한 곡을 찾을 수 없어요. "
                    "삭제할 구간을 다시 선택해 주세요."
                ),
                embed=make_queue_embed(state),
                view=QueueRangeDeleteView(self.guild_id) if state.queue else None,
            )
            return

        removed, start_index, end_index = result
        schedule_autoplay_refill(self.guild_id)
        if state.current:
            await update_control_panel(self.guild_id, state)

        await interaction.response.edit_message(
            content=(
                f"대기열 {start_index + 1}~{end_index + 1}번, "
                f"{len(removed)}곡을 삭제했어요."
            ),
            embed=make_queue_embed(state),
            view=None,
        )
        schedule_queue_message_cleanup(
            state,
            interaction.message,
            QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )


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

            await send_ephemeral_response(
                interaction,
                "먼저 음성 채널에 들어가 주세요.",
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
            await send_ephemeral_response(interaction, "봇이 음성 채널에 없어요.")
            return

        if state.voice.is_paused():
            state.voice.resume()
        elif state.voice.is_playing():
            state.voice.pause()
        else:
            await send_ephemeral_response(interaction, "지금 재생 중인 곡이 없어요.")
            return

        await self.edit_panel(interaction)

    @discord.ui.button(label="스킵", emoji="⏭️", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
            state.skip_requested = True
            state.voice.stop()
            await send_ephemeral_response(interaction, "다음 곡으로 넘어갈게요.")
            return

        await send_ephemeral_response(interaction, "스킵할 곡이 없어요.")

    @discord.ui.button(label="정지", emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        stop_playback(state, self.guild_id)
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
        await send_queue_management_response(
            interaction,
            self.guild_id,
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
        )

    @discord.ui.button(label="구간 삭제", emoji="✂️", style=discord.ButtonStyle.secondary, row=1)
    async def queue_range(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        state = self.get_state()
        view = QueueRangeDeleteView(self.guild_id) if state.queue else None
        await send_queue_management_response(
            interaction,
            self.guild_id,
            content=(
                view.make_selection_content(state)
                if view
                else "대기열이 비어 있어요."
            ),
            embed=make_queue_embed(state),
            view=view,
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


FULL_VERSION_SEARCH_RE = re.compile(
    r"\b(?:full(?:\s*(?:ver(?:sion)?|size|song))?|complete\s*version|long\s*version)\b"
    r"|フル(?:サイズ|バージョン|ver\.?)?|完全版|完整版"
    r"|풀\s*버전|풀버전|완곡",
    flags=re.IGNORECASE,
)
SHORT_VERSION_SEARCH_RE = re.compile(
    r"\b(?:short(?:\s*ver(?:sion)?)?|tv\s*(?:size|ver(?:sion)?)"
    r"|anime\s*(?:size|ver(?:sion)?)|game\s*(?:size|ver(?:sion)?)"
    r"|preview|teaser|sample|one\s*chorus|1\s*chorus)\b"
    r"|ショート(?:ver\.?)?|TVサイズ|テレビサイズ|アニメサイズ"
    r"|ゲームサイズ|ワンコーラス|試聴(?:版)?"
    r"|숏\s*버전|숏버전|TV\s*판|애니\s*버전|게임\s*버전"
    r"|미리듣기|1절\s*버전",
    flags=re.IGNORECASE,
)
GAME_VIDEO_SEARCH_RE = re.compile(
    r"\b(?:2d|3d)\s*m\s*/?\s*v\b|\bgame\s*(?:mv|movie|play)\b"
    r"|\b(?:op|ed)\s*(?:movie|animation)\b|\bcreditless\b"
    r"|ノンクレジット|ゲーム(?:MV|映像)|プレイ動画|譜面"
    r"|오프닝\s*영상|엔딩\s*영상|게임\s*(?:MV|영상)|플레이\s*영상",
    flags=re.IGNORECASE,
)
ALTERNATE_VERSION_SEARCH_RE = re.compile(
    r"\b(?:cover|remix|live|instrumental|karaoke|acoustic|sped\s*up"
    r"|off\s*vocal|slowed(?:\s*down)?|nightcore|solo)\b"
    r"|ver(?:sion)?\.?(?=\s|[)\]}>】」』）]|$)"
    r"|カバー|歌ってみた|リミックス|ライブ|インスト|カラオケ"
    r"|オフボーカル|アコースティック|ソロ"
    r"|커버|리믹스|라이브|연주|노래방|오프\s*보컬|솔로",
    flags=re.IGNORECASE,
)
LONG_FORM_SEARCH_RE = re.compile(
    r"\b(?:extended|loop|hour|medley|compilation|playlist)\b"
    r"|耐久|作業用|メドレー|모음|메들리|반복",
    flags=re.IGNORECASE,
)
OFFICIAL_MEDIA_SEARCH_RE = re.compile(
    r"\b(?:official|music\s*video|m\s*/?\s*v|official\s*audio"
    r"|lyric(?:s|\s*video)?)\b"
    r"|公式|ミュージックビデオ|オーディオ|歌詞"
    r"|공식|뮤직비디오|오디오|가사",
    flags=re.IGNORECASE,
)
OFFICIAL_VIDEO_SEARCH_RE = re.compile(
    r"\bofficial\s*(?:music\s*)?(?:video|m\s*/?\s*v)\b"
    r"|公式\s*(?:ミュージックビデオ|m\s*/?\s*v)"
    r"|공식\s*(?:뮤직비디오|m\s*/?\s*v)",
    flags=re.IGNORECASE,
)
OFFICIAL_AUDIO_SEARCH_RE = re.compile(
    r"\bofficial\s*audio\b|公式\s*(?:オーディオ|音源)|공식\s*(?:오디오|음원)",
    flags=re.IGNORECASE,
)
OFFICIAL_CHANNEL_RE = re.compile(
    r"\bofficial\b|\bvevo\b|(?:^|\s)-\s*topic$|公式|공식",
    flags=re.IGNORECASE,
)
YOUTUBE_SEARCH_NOISE_TOKENS = frozenset(
    {
        "music",
        "song",
        "official",
        "audio",
        "video",
        "lyrics",
        "lyric",
        "mv",
        "노래",
        "음악",
        "가사",
        "공식",
    }
)


def should_use_youtube_music_search(query: str) -> bool:
    return not any(
        pattern.search(query)
        for pattern in (
            SHORT_VERSION_SEARCH_RE,
            GAME_VIDEO_SEARCH_RE,
            ALTERNATE_VERSION_SEARCH_RE,
            LONG_FORM_SEARCH_RE,
        )
    )


def get_youtube_music_artist_names(result: dict) -> list[str]:
    artists = result.get("artists")
    if isinstance(artists, list):
        names = [
            str(artist.get("name")).strip()
            for artist in artists
            if isinstance(artist, dict) and artist.get("name")
        ]
        if names:
            return names

    artist = result.get("artist")
    if isinstance(artist, str) and artist.strip():
        return [artist.strip()]
    return []


def youtube_music_result_to_entry(result: dict) -> dict | None:
    video_id = result.get("videoId")
    title = result.get("title")
    if (
        result.get("resultType") != "song"
        or not isinstance(video_id, str)
        or not re.fullmatch(r"[\w-]{11}", video_id)
        or not isinstance(title, str)
        or not title.strip()
    ):
        return None

    artists = get_youtube_music_artist_names(result)
    artist = ", ".join(artists) or None
    album = result.get("album")
    album_name = album.get("name") if isinstance(album, dict) else None
    thumbnails = result.get("thumbnails")
    thumbnail = None
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and item.get("url"):
                thumbnail = item["url"]
                break

    webpage_url = f"https://www.youtube.com/watch?v={video_id}"
    return {
        "id": video_id,
        "url": webpage_url,
        "webpage_url": webpage_url,
        "title": title.strip(),
        "track": title.strip(),
        "artist": artist,
        "creator": artist,
        "channel": artist,
        "album": album_name,
        "duration": result.get("duration_seconds"),
        "thumbnail": thumbnail,
        "_music_bot_youtube_music": True,
    }


def youtube_music_entries_are_ambiguous(
    query: str,
    entries: list[dict],
) -> bool:
    normalized_query = normalize_identity_component(clean_track_title(query))
    if not normalized_query:
        return False

    exact_title_artists = {
        normalize_artist_name(str(entry.get("artist") or entry.get("creator") or ""))
        for entry in entries
        if normalize_identity_component(
            clean_track_title(str(entry.get("track") or entry.get("title") or ""))
        )
        == normalized_query
        and (entry.get("artist") or entry.get("creator"))
    }
    return len(exact_title_artists) > 1


def select_youtube_music_song_result(query: str, results: list[dict]) -> dict | None:
    entries = [
        entry
        for result in results
        if (entry := youtube_music_result_to_entry(result)) is not None
    ]
    if not entries:
        return None
    if youtube_music_entries_are_ambiguous(query, entries):
        logger.info(
            "YouTube Music returned multiple artists for title-only query %s; "
            "using YouTube ranking instead",
            query,
        )
        return None

    selected = select_youtube_search_result(query, entries)
    logger.info(
        "YouTube Music selected catalog song for %s: %s (%s)",
        query,
        selected.get("title"),
        selected.get("id"),
    )
    return selected


def get_youtube_music_artist_hint(query: str, results: list[dict]) -> str | None:
    song_entries = [
        entry
        for result in results
        if (entry := youtube_music_result_to_entry(result)) is not None
    ]
    if youtube_music_entries_are_ambiguous(query, song_entries):
        return None

    normalized_query = normalize_identity_component(query)
    for index, result in enumerate(results[:3]):
        if result.get("resultType") not in {"album", "song"}:
            continue
        if index > 0 and str(result.get("category") or "").casefold() != "top result":
            continue

        artists = get_youtube_music_artist_names(result)
        if not artists:
            continue
        artist = artists[0]
        normalized_artist = normalize_artist_name(artist)
        if (
            not normalized_artist
            or normalized_artist in normalized_query
            or len(artist) > 120
        ):
            return None
        return artist
    return None


def build_youtube_search_query(
    query: str,
    artist_hint: str | None = None,
) -> str:
    search_text = query
    if artist_hint:
        search_text = f"{query} {artist_hint}"
    return f"ytsearch{YOUTUBE_SEARCH_CANDIDATES}:{search_text}"


def is_youtube_search_query(query: str) -> bool:
    return bool(re.match(r"^ytsearch(?:\d+)?:", query, flags=re.IGNORECASE))


def get_youtube_search_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return {
        token
        for token in re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
        if len(token) >= 2 and token not in YOUTUBE_SEARCH_NOISE_TOKENS
    }


def get_search_result_duration(entry: dict) -> float | None:
    duration = entry.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    return None


def infer_youtube_search_song_title(
    entry: dict,
    preferred_artist: str | None = None,
) -> str | None:
    track = entry.get("track")
    if isinstance(track, str) and track.strip():
        return clean_track_title_preserving_case(track)

    raw_title = entry.get("title")
    if not isinstance(raw_title, str) or not raw_title.strip():
        return None

    quoted_match = re.search(r"[「『](?P<title>[^」』]+)[」』]", raw_title)
    if quoted_match:
        candidate = quoted_match.group("title")
    else:
        slash_parts = re.split(r"\s*/\s*", raw_title, maxsplit=1)
        if len(slash_parts) == 2:
            candidate = slash_parts[0]
        else:
            candidate = raw_title
            dash_parts = re.split(
                r"\s+(?:-|–|—|\|)\s+",
                raw_title,
                maxsplit=1,
            )
            if len(dash_parts) == 2 and preferred_artist:
                normalized_artist = normalize_artist_name(preferred_artist)
                if normalize_artist_name(dash_parts[0]) == normalized_artist:
                    candidate = dash_parts[1]
                elif normalize_artist_name(dash_parts[1]) == normalized_artist:
                    candidate = dash_parts[0]

    candidate = strip_edge_title_tags(candidate)
    return clean_track_title_preserving_case(candidate) or None


def is_likely_official_youtube_upload(entry: dict) -> bool:
    raw_title = str(entry.get("title") or "")
    channel = str(entry.get("channel") or entry.get("uploader") or "")
    if not channel:
        return False
    if OFFICIAL_CHANNEL_RE.search(channel):
        return True

    title_parts = re.split(
        r"\s+(?:-|–|—|\|)\s+",
        raw_title,
        maxsplit=1,
    )
    if len(title_parts) != 2:
        quoted_match = re.match(r"^\s*(?P<artist>.+?)[「『]", raw_title)
        if quoted_match is None:
            return False
        title_artist = quoted_match.group("artist")
    else:
        title_artist = title_parts[0]

    normalized_title_artist = normalize_artist_name(title_artist)
    normalized_channel = normalize_artist_name(channel)
    if not normalized_title_artist or not normalized_channel:
        return False
    if normalized_title_artist == normalized_channel:
        return True
    return (
        min(len(normalized_title_artist), len(normalized_channel)) >= 4
        and (
            normalized_title_artist in normalized_channel
            or normalized_channel in normalized_title_artist
        )
    )


def score_youtube_search_result(
    entry: dict,
    query: str,
    result_index: int,
    preferred_artist: str | None = None,
    preferred_title: str | None = None,
) -> int:
    title = str(entry.get("title") or "")
    artist = str(entry.get("artist") or entry.get("creator") or "")
    uploader = str(entry.get("channel") or entry.get("uploader") or "")
    searchable = " ".join((title, artist, uploader)).strip()
    normalized_query = normalize_identity_component(query)
    normalized_searchable = normalize_identity_component(searchable)
    query_tokens = get_youtube_search_tokens(query)
    candidate_tokens = get_youtube_search_tokens(searchable)

    score = max(0, 30 - result_index * 3)
    if normalized_query and normalized_query in normalized_searchable:
        score += 100
    if query_tokens:
        overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
        score += round(overlap * 80)

    query_requests_short = bool(SHORT_VERSION_SEARCH_RE.search(query))
    query_requests_game_video = bool(GAME_VIDEO_SEARCH_RE.search(query))
    query_requests_alternate = bool(ALTERNATE_VERSION_SEARCH_RE.search(query))
    query_requests_long_form = bool(LONG_FORM_SEARCH_RE.search(query))
    query_requests_official_video = bool(OFFICIAL_VIDEO_SEARCH_RE.search(query))
    query_requests_official_audio = bool(OFFICIAL_AUDIO_SEARCH_RE.search(query))
    query_requests_short_form = query_requests_short or query_requests_game_video

    duration = get_search_result_duration(entry)
    if duration is None:
        score -= 5
    elif duration < 45:
        score -= 140
    elif duration < 90:
        score += -20 if query_requests_short_form else -90
    elif duration < 150:
        score += 15 if query_requests_short_form else -50
    elif duration < 180:
        score += 10 if query_requests_short_form else -20
    elif duration <= 420:
        score += 30
    elif duration <= 600:
        score += 10
    elif duration > 900:
        score -= 90
    else:
        score -= 20

    if FULL_VERSION_SEARCH_RE.search(searchable):
        score += 35
    if SHORT_VERSION_SEARCH_RE.search(searchable):
        score += 70 if query_requests_short else -120
    if GAME_VIDEO_SEARCH_RE.search(searchable):
        if query_requests_game_video:
            score += 50
        elif duration is None or duration < 210:
            score -= 70
        else:
            score -= 20
    if (
        ALTERNATE_VERSION_SEARCH_RE.search(searchable)
        and not FULL_VERSION_SEARCH_RE.search(searchable)
    ):
        score += 40 if query_requests_alternate else -45
    if LONG_FORM_SEARCH_RE.search(searchable):
        score += 40 if query_requests_long_form else -80
    if OFFICIAL_MEDIA_SEARCH_RE.search(searchable) and (
        duration is None or 150 <= duration <= 600
    ):
        score += 8
    if OFFICIAL_VIDEO_SEARCH_RE.search(searchable):
        score += 55 if query_requests_official_video else 18
    if OFFICIAL_AUDIO_SEARCH_RE.search(searchable):
        score += 55 if query_requests_official_audio else 6
    if is_likely_official_youtube_upload(entry):
        score += 40
    if preferred_artist:
        candidate_artist = artist or uploader
        if candidate_artist:
            normalized_preferred_artist = normalize_artist_name(preferred_artist)
            normalized_candidate_artist = normalize_artist_name(candidate_artist)
            if normalized_candidate_artist == normalized_preferred_artist:
                score += 60
    if preferred_title:
        normalized_preferred_title = normalize_identity_component(preferred_title)
        normalized_raw_title = normalize_identity_component(title)
        inferred_title = infer_youtube_search_song_title(
            entry,
            preferred_artist,
        )
        normalized_inferred_title = (
            normalize_identity_component(inferred_title)
            if inferred_title
            else ""
        )
        if normalized_raw_title == normalized_preferred_title:
            score += 120
        elif normalized_inferred_title == normalized_preferred_title:
            score += 50
        elif (
            normalized_preferred_title
            and normalized_preferred_title in normalized_raw_title
        ):
            score += 25

    if entry.get("is_live") or entry.get("live_status") in {
        "is_live",
        "is_upcoming",
        "post_live",
    }:
        score -= 200
    return score


def select_youtube_search_result(
    query: str,
    entries: list[dict],
    preferred_artist: str | None = None,
    preferred_title: str | None = None,
) -> dict:
    candidates = [
        entry
        for entry in entries
        if isinstance(entry, dict) and (entry.get("id") or entry.get("url"))
    ]
    if not candidates:
        raise ValueError(f"No playable search results were found for '{query}'.")

    ranked = [
        (
            score_youtube_search_result(
                entry,
                query,
                index,
                preferred_artist,
                preferred_title,
            ),
            -index,
            entry,
        )
        for index, entry in enumerate(candidates)
    ]
    score, negative_index, selected = max(
        ranked,
        key=lambda candidate: candidate[:2],
    )
    logger.info(
        "YouTube search selected result %s/%s for %s: %s (%s, score %s)",
        -negative_index + 1,
        len(candidates),
        query,
        selected.get("title") or "Untitled track",
        format_duration(selected.get("duration")),
        score,
    )
    return selected


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
    is_search = is_youtube_search_query(resolved_query)
    options = YTDL_SEARCH_OPTIONS if is_search else YTDL_OPTIONS
    search_query = resolved_query
    selection_query = query
    artist_hint: str | None = None

    if is_search and should_use_youtube_music_search(query):
        music_results: list[dict] = []
        try:
            music_results = await search_youtube_music(query)
        except YouTubeCircuitOpenError:
            raise
        except asyncio.TimeoutError:
            logger.warning(
                "YouTube Music search timed out. Falling back to YouTube: %s",
                query,
            )
        except Exception as error:
            logger.warning(
                "YouTube Music search failed. Falling back to YouTube for %s: %s",
                query,
                error,
            )

        music_entry = select_youtube_music_song_result(query, music_results)
        if music_entry is not None:
            try:
                return await extract_ytdl_info(
                    YTDL_OPTIONS,
                    music_entry["webpage_url"],
                    "YouTube Music catalog song resolve",
                )
            except YouTubeCircuitOpenError:
                raise
            except Exception as error:
                logger.warning(
                    "YouTube Music catalog song could not be resolved. "
                    "Falling back to YouTube for %s: %s",
                    query,
                    error,
                )

        artist_hint = get_youtube_music_artist_hint(query, music_results)
        if artist_hint:
            search_query = build_youtube_search_query(query, artist_hint)
            selection_query = f"{query} {artist_hint}"
            logger.info(
                "YouTube Music enriched search for %s with artist %s",
                query,
                artist_hint,
            )

    try:
        info = await extract_ytdl_info(options, search_query, "YouTube search")
    except asyncio.TimeoutError:
        raise ValueError(f"Timed out while searching for '{query}'.") from None

    if "entries" not in info:
        return info

    entries = [entry for entry in info["entries"] if entry]
    if entries:
        if is_search:
            if artist_hint:
                preferred_title = infer_youtube_search_song_title(
                    entries[0],
                    artist_hint,
                )
                return select_youtube_search_result(
                    selection_query,
                    entries,
                    preferred_artist=artist_hint,
                    preferred_title=preferred_title,
                )
            return select_youtube_search_result(
                selection_query,
                entries,
            )
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
LEADING_BRACKETED_TITLE_PART_RE = re.compile(
    r"^\s*(?:\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］)\s*"
)
TRAILING_BRACKETED_TITLE_PART_RE = re.compile(
    r"\s*(?:\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|【[^】]*】|（[^）]*）|［[^］]*］)\s*$"
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


def clean_track_title_preserving_case(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)

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


def clean_track_title(value: str) -> str:
    return clean_track_title_preserving_case(value).casefold()


def strip_edge_title_tags(value: str) -> str:
    value = value.strip()
    previous = None
    while value and previous != value:
        previous = value
        value = LEADING_BRACKETED_TITLE_PART_RE.sub("", value)
        value = TRAILING_BRACKETED_TITLE_PART_RE.sub("", value)
    return value.strip()


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


LRC_TIMESTAMP_RE = re.compile(
    r"\[(?:(?:\d{1,2}):)?\d{1,2}:\d{2}(?:[.:]\d{1,3})?\]"
)
LRC_METADATA_RE = re.compile(
    r"^\[(?:ar|ti|al|by|offset|length|re|ve):.*\]\s*$",
    flags=re.IGNORECASE,
)


class LyricsLookupError(RuntimeError):
    pass


class YouTubeSubtitleError(RuntimeError):
    pass


class KoreanLyricsError(RuntimeError):
    pass


class NamuWikiLyricsError(RuntimeError):
    pass


class LyricsReadingError(RuntimeError):
    pass


QUOTED_TRACK_TITLE_RE = re.compile(
    r"^\s*(?P<artist>.+?)\s*[「『](?P<title>[^」』]+)[」』]"
)
JAPANESE_KANA_RE = re.compile(r"[\u3041-\u309f\u30a0-\u30ff]")
JAPANESE_READING_RE = re.compile(
    r"^[\u3041-\u309f\u30a0-\u30ff\u30fc\u3005\u30fb\uff65\s]+$"
)
JAPANESE_HAN_RE = re.compile(
    r"[\u3005\u3007\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]"
)
HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
EXPLICIT_READING_BRACKETS = (
    ("(", ")"),
    ("（", "）"),
    ("[", "]"),
    ("［", "］"),
    ("{", "}"),
    ("｛", "｝"),
    ("〈", "〉"),
    ("《", "》"),
    ("【", "】"),
    ("〔", "〕"),
)
SUDACHI_TOKENIZER = None
SUDACHI_TOKENIZER_LOCK = threading.Lock()
NAMUWIKI_REQUEST_LOCK = threading.Lock()
namuwiki_last_request_started_at = 0.0
NAMUWIKI_MAX_DOCUMENT_CANDIDATES = 4
NAMUWIKI_MAX_RESPONSE_BYTES = 3_000_000
NAMUWIKI_IGNORED_HTML_TAGS = frozenset(
    {"button", "noscript", "script", "style", "sup", "svg"}
)
NAMUWIKI_VOID_HTML_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}
)
NAMUWIKI_BLOCKED_MARKERS = (
    "captcha 인증이 필요",
    "로봇이 아닙니다",
    "idc 대역 ip",
    "ip 우회 수단",
    "rate limit",
    "too many requests",
    "비정상적인 접근",
    "차단되었습니다",
)


@dataclass
class _NamuWikiHTMLTableContext:
    rows: list[list[str]] = field(default_factory=list)
    row: list[str] | None = None
    cell_fragments: list[str] | None = None
    cell_colspan: int = 1


class NamuWikiHTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[_NamuWikiHTMLTableContext] = []
        self._ignored_tags: list[str] = []

    def _current_context(self) -> _NamuWikiHTMLTableContext | None:
        return self._table_stack[-1] if self._table_stack else None

    def _append_cell_fragment(self, value: str) -> None:
        context = self._current_context()
        if context is not None and context.cell_fragments is not None:
            context.cell_fragments.append(value)

    def _append_cell_break(self) -> None:
        context = self._current_context()
        if context is None or context.cell_fragments is None:
            return
        if context.cell_fragments and context.cell_fragments[-1].endswith("\n"):
            return
        context.cell_fragments.append("\n")

    def _finish_cell(self, context: _NamuWikiHTMLTableContext) -> None:
        if context.cell_fragments is None:
            return
        if context.row is None:
            context.row = []
        text = normalize_namuwiki_table_text("".join(context.cell_fragments))
        context.row.append(text)
        context.row.extend("" for _ in range(max(1, context.cell_colspan) - 1))
        context.cell_fragments = None
        context.cell_colspan = 1

    def _finish_row(self, context: _NamuWikiHTMLTableContext) -> None:
        self._finish_cell(context)
        if context.row is not None and any(cell for cell in context.row):
            context.rows.append(context.row)
        context.row = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        if self._ignored_tags:
            if tag not in NAMUWIKI_VOID_HTML_TAGS:
                self._ignored_tags.append(tag)
            return
        if tag in NAMUWIKI_IGNORED_HTML_TAGS:
            self._ignored_tags.append(tag)
            return

        if tag == "table":
            self._table_stack.append(_NamuWikiHTMLTableContext())
            return

        context = self._current_context()
        if context is None:
            return
        if tag == "tr":
            self._finish_row(context)
            context.row = []
        elif tag in {"td", "th"}:
            self._finish_cell(context)
            context.cell_fragments = []
            attributes = dict(attrs)
            try:
                context.cell_colspan = max(1, int(attributes.get("colspan") or "1"))
            except ValueError:
                context.cell_colspan = 1
        elif tag == "br":
            self._append_cell_break()
        elif tag == "img":
            alt_text = dict(attrs).get("alt")
            if alt_text and not alt_text.startswith("파일:"):
                self._append_cell_fragment(alt_text)
        elif tag in {"div", "li", "p"}:
            self._append_cell_break()

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() in NAMUWIKI_IGNORED_HTML_TAGS:
            return
        self.handle_starttag(tag, attrs)
        if tag.casefold() not in NAMUWIKI_VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._ignored_tags:
            if tag == self._ignored_tags[-1]:
                self._ignored_tags.pop()
            return

        context = self._current_context()
        if context is None:
            return
        if tag in {"td", "th"}:
            self._finish_cell(context)
        elif tag == "tr":
            self._finish_row(context)
        elif tag == "table":
            self._finish_row(context)
            completed = self._table_stack.pop()
            if completed.rows:
                self.tables.append(completed.rows)
        elif tag in {"div", "li", "p"}:
            self._append_cell_break()

    def handle_data(self, data: str) -> None:
        if not self._ignored_tags:
            self._append_cell_fragment(data)


def normalize_namuwiki_table_text(value: str) -> str:
    value = html.unescape(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u200b", "").replace("\ufeff", "").replace("\xa0", " ")
    normalized_lines: list[str] = []
    for raw_line in value.split("\n"):
        line = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        if line:
            normalized_lines.append(line)
        elif normalized_lines and normalized_lines[-1]:
            normalized_lines.append("")
    while normalized_lines and not normalized_lines[-1]:
        normalized_lines.pop()
    return "\n".join(normalized_lines).strip()


def namuwiki_translation_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "한국어번역" in key:
        return 100
    if "한국어해석" in key:
        return 95
    if "한국어가사" in key:
        return 90
    if key in {"번역", "해석", "한국어"}:
        return 70
    return 0


def namuwiki_source_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if "일본어원문" in key or "원어원문" in key:
        return 100
    if key == "원문":
        return 90
    if key in {"일본어", "일어", "원어"}:
        return 70
    return 0


def namuwiki_reading_header_score(value: str) -> int:
    key = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if any(
        marker in key
        for marker in ("일본어독음", "한글독음", "한국어독음")
    ):
        return 100
    if "독음" in key:
        return 90
    if key in {"발음", "요미가나", "읽는법"}:
        return 70
    return 0


def is_valid_korean_translation(value: str) -> bool:
    hangul_count = sum(
        bool(HANGUL_RE.fullmatch(character))
        for character in value
    )
    nonempty_lines = [line for line in value.splitlines() if line.strip()]
    return hangul_count >= 8 and (
        len(nonempty_lines) >= 2 or len(value) >= 30
    )


def is_usable_namuwiki_lyrics(value: str) -> bool:
    groups = [
        group.strip()
        for group in re.split(r"\n\s*\n", value)
        if group.strip()
    ]
    nonempty_lines = [
        line.strip()
        for group in groups
        for line in group.splitlines()
        if line.strip()
    ]
    if len(groups) < 2 and len(nonempty_lines) < 6:
        return False

    foreign_letter_count = sum(
        character.isalpha() and not HANGUL_RE.fullmatch(character)
        for character in value
    )
    return foreign_letter_count >= 2 and is_valid_korean_translation(value)


def extract_interleaved_namuwiki_groups(
    value: str,
) -> tuple[list[str], list[str], int]:
    groups: list[str] = []
    translated_lines: list[str] = []
    source_line_count = 0
    current_source: str | None = None
    current_hangul_lines: list[str] | None = None

    def finish_group() -> None:
        if (
            current_source
            and current_hangul_lines
            and len(current_hangul_lines) >= 2
        ):
            groups.append(
                "\n".join((current_source, *current_hangul_lines))
            )
            translated_lines.append(current_hangul_lines[-1])

    for line in normalize_namuwiki_table_text(value).splitlines():
        has_hangul = bool(HANGUL_RE.search(line))
        has_japanese = bool(
            JAPANESE_KANA_RE.search(line) or JAPANESE_HAN_RE.search(line)
        )
        latin_letter_count = sum(
            character.isascii() and character.isalpha()
            for character in line
        )
        if not has_hangul and (has_japanese or latin_letter_count >= 2):
            finish_group()
            source_line_count += 1
            current_source = line
            current_hangul_lines = []
        elif current_hangul_lines is not None and has_hangul:
            current_hangul_lines.append(line)

    finish_group()
    return groups, translated_lines, source_line_count


def extract_interleaved_namuwiki_lyrics(
    rows: list[list[str]],
) -> str | None:
    table_text = "\n".join(
        cell
        for row in rows
        for cell in row
    )
    (
        groups,
        translated_lines,
        source_line_count,
    ) = extract_interleaved_namuwiki_groups(table_text)

    translation = "\n".join(translated_lines).strip()
    if (
        source_line_count < 3
        or len(groups) < 3
        or not is_valid_korean_translation(translation)
    ):
        return None
    return "\n\n".join(groups)


def best_namuwiki_header_column(
    row: list[str],
    scorer: Callable[[str], int],
    excluded: set[int],
) -> int | None:
    candidates = [
        (scorer(header), column_index)
        for column_index, header in enumerate(row)
        if column_index not in excluded and scorer(header) > 0
    ]
    return max(candidates)[1] if candidates else None


def extract_namuwiki_lyrics_from_tables(
    tables: list[list[list[str]]],
) -> str | None:
    candidates: list[tuple[int, int, int, int, str]] = []
    for rows in tables:
        for header_row_index, row in enumerate(rows):
            for translation_index, header in enumerate(row):
                header_score = namuwiki_translation_header_score(header)
                if header_score == 0:
                    continue

                source_index = best_namuwiki_header_column(
                    row,
                    namuwiki_source_header_score,
                    {translation_index},
                )
                excluded = {translation_index}
                if source_index is not None:
                    excluded.add(source_index)
                reading_index = best_namuwiki_header_column(
                    row,
                    namuwiki_reading_header_score,
                    excluded,
                )

                groups: list[str] = []
                translated_cells: list[str] = []
                complete_group_count = 0
                for candidate_row in rows[header_row_index + 1 :]:
                    if any(
                        namuwiki_translation_header_score(cell) >= header_score
                        for cell in candidate_row
                    ):
                        break
                    if translation_index >= len(candidate_row):
                        continue
                    translation = normalize_namuwiki_table_text(
                        candidate_row[translation_index]
                    )
                    if (
                        not translation
                        or namuwiki_translation_header_score(translation)
                    ):
                        continue

                    group_lines: list[str] = []
                    source = ""
                    reading = ""
                    if (
                        source_index is not None
                        and source_index < len(candidate_row)
                    ):
                        source = normalize_namuwiki_table_text(
                            candidate_row[source_index]
                        )
                        if source:
                            group_lines.append(source)
                    if (
                        reading_index is not None
                        and reading_index < len(candidate_row)
                    ):
                        reading = normalize_namuwiki_table_text(
                            candidate_row[reading_index]
                        )
                        if reading:
                            group_lines.append(reading)
                    group_lines.append(translation)
                    groups.append("\n".join(group_lines))
                    translated_cells.append(translation)
                    if source and reading:
                        complete_group_count += 1

                translation = "\n".join(translated_cells).strip()
                if not translation or not is_valid_korean_translation(translation):
                    continue
                lyrics = "\n\n".join(groups)
                hangul_count = sum(
                    bool(HANGUL_RE.fullmatch(character))
                    for character in translation
                )
                candidates.append(
                    (
                        hangul_count,
                        complete_group_count,
                        header_score,
                        len(lyrics),
                        lyrics,
                    )
                )

        interleaved_lyrics = extract_interleaved_namuwiki_lyrics(rows)
        if interleaved_lyrics:
            groups, translated_lines, _ = extract_interleaved_namuwiki_groups(
                interleaved_lyrics
            )
            translation = "\n".join(translated_lines)
            hangul_count = sum(
                bool(HANGUL_RE.fullmatch(character))
                for character in translation
            )
            candidates.append(
                (
                    hangul_count,
                    len(groups),
                    50,
                    len(interleaved_lyrics),
                    interleaved_lyrics,
                )
            )

    if not candidates:
        return None
    lyrics = max(candidates, key=lambda candidate: candidate[:4])[4]
    return lyrics if is_usable_namuwiki_lyrics(lyrics) else None


NAMUMARK_STYLE_PREFIX_RE = re.compile(r"^(?:\s*<[^>\n]*>)+")
NAMUMARK_RUBY_RE = re.compile(
    r"\[ruby\((?P<base>.*?),\s*ruby=.*?\)\]",
    flags=re.IGNORECASE,
)
NAMUMARK_LINK_RE = re.compile(r"\[\[(?P<value>[^\]]+)\]\]")
NAMUMARK_FOOTNOTE_RE = re.compile(r"\[\*(?:[^\]]*)\]")


def clean_namumark_cell(value: str) -> str:
    value = NAMUMARK_STYLE_PREFIX_RE.sub("", value.strip())
    value = re.sub(r"\[br\]", "\n", value, flags=re.IGNORECASE)
    value = NAMUMARK_RUBY_RE.sub(lambda match: match.group("base"), value)
    value = NAMUMARK_FOOTNOTE_RE.sub("", value)
    value = NAMUMARK_LINK_RE.sub(
        lambda match: match.group("value").split("|", 1)[-1],
        value,
    )
    value = re.sub(r"\[(?:clearfix|목차)\]", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\{\{\{(?:#!wiki[^\n]*|#[^\s}]+\s*)?", "", value)
    value = value.replace("{{{", "").replace("}}}", "")
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("'''", "").replace("''", "")
    return normalize_namuwiki_table_text(value)


def parse_namumark_tables(source: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []
    pending_row_lines: list[str] = []

    def finish_table() -> None:
        nonlocal current_table
        if current_table:
            tables.append(current_table)
            current_table = []

    def finish_row() -> None:
        nonlocal pending_row_lines
        row_source = "\n".join(pending_row_lines).strip()
        pending_row_lines = []
        if not row_source.startswith("||"):
            return
        row_source = row_source[2:]
        if row_source.endswith("||"):
            row_source = row_source[:-2]
        cells = [
            clean_namumark_cell(cell)
            for cell in re.split(r"\s*\|\|\s*", row_source)
        ]
        if any(cells):
            current_table.append(cells)

    normalized_source = source.replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized_source.split("\n"):
        line = raw_line.strip()
        if pending_row_lines:
            pending_row_lines.append(raw_line)
            if line.endswith("||"):
                finish_row()
            continue

        if line.startswith("||"):
            pending_row_lines = [line]
            if line.endswith("||") and len(line) > 2:
                finish_row()
            continue

        finish_table()

    if pending_row_lines:
        finish_row()
    finish_table()
    return tables


def extract_namuwiki_lyrics_from_namumark(source: str) -> str | None:
    return extract_namuwiki_lyrics_from_tables(parse_namumark_tables(source))


def extract_namuwiki_lyrics_from_html(source: str) -> str | None:
    parser = NamuWikiHTMLTableParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception as error:
        raise NamuWikiLyricsError(f"Could not parse NamuWiki HTML: {error}") from error
    return extract_namuwiki_lyrics_from_tables(parser.tables)


def get_namuwiki_override(track: Track) -> str | None:
    if not NAMUWIKI_DOCUMENT_OVERRIDES:
        return None

    keys: list[str] = []
    video_id = get_track_video_id(track)
    if video_id:
        keys.extend((f"video:{video_id}", video_id))
    keys.extend(
        value
        for value in (
            normalize_track_key(track),
            track.song_name,
            track.title,
        )
        if value
    )
    normalized_overrides = {
        key.casefold(): value
        for key, value in NAMUWIKI_DOCUMENT_OVERRIDES.items()
    }
    for key in keys:
        override = normalized_overrides.get(key.casefold())
        if override:
            return override
    return None


def get_namuwiki_document_candidates(track: Track) -> list[str]:
    candidates: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        candidate = value.strip().strip("\"'")
        if (
            not candidate
            or "\n" in candidate
            or len(candidate) > 1000
            or candidate in candidates
        ):
            return
        candidates.append(candidate)

    add(get_namuwiki_override(track))
    add(track.song_name)

    quoted_match = QUOTED_TRACK_TITLE_RE.match(track.title)
    if quoted_match:
        add(quoted_match.group("title"))

    raw_parts = re.split(
        r"\s+(?:-|–|—|\|)\s+",
        track.title,
        maxsplit=1,
    )
    if len(raw_parts) == 2:
        cleaned_part = clean_track_title_preserving_case(raw_parts[1])
        add(cleaned_part)
        add(strip_edge_title_tags(cleaned_part))
        add(raw_parts[1])
    else:
        cleaned_title = clean_track_title_preserving_case(track.title)
        add(cleaned_title)
        add(strip_edge_title_tags(cleaned_title))

    track_name, _ = get_lyrics_search_terms(track)
    add(track_name)
    add(clean_track_title(track.title))
    return candidates[:NAMUWIKI_MAX_DOCUMENT_CANDIDATES]


def split_namuwiki_candidate(candidate: str) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"}:
            raise NamuWikiLyricsError("NamuWiki override URL must use HTTP or HTTPS.")
        marker = "/w/"
        if marker not in parsed.path:
            raise NamuWikiLyricsError("NamuWiki override URL must point to a /w/ page.")
        path_prefix, encoded_document = parsed.path.split(marker, 1)
        document = urllib.parse.unquote(encoded_document).strip()
        encoded_path = (
            f"{path_prefix}{marker}"
            f"{urllib.parse.quote(document, safe='')}"
        )
        page_url = urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, encoded_path, "", "", "")
        )
    else:
        document = candidate.strip()
        page_url = (
            f"{NAMUWIKI_PAGE_BASE_URL}/"
            f"{urllib.parse.quote(document, safe='')}"
        )

    if not document or "\n" in document or len(document) > 255:
        raise NamuWikiLyricsError("NamuWiki document title is invalid.")
    return document, page_url


def wait_for_namuwiki_interval() -> None:
    global namuwiki_last_request_started_at
    with NAMUWIKI_REQUEST_LOCK:
        elapsed = time.monotonic() - namuwiki_last_request_started_at
        delay = max(0.0, NAMUWIKI_REQUEST_INTERVAL_SECONDS - elapsed)
        if delay:
            time.sleep(delay)
        namuwiki_last_request_started_at = time.monotonic()


def read_limited_http_response(response) -> bytes:
    payload = response.read(NAMUWIKI_MAX_RESPONSE_BYTES + 1)
    if len(payload) > NAMUWIKI_MAX_RESPONSE_BYTES:
        raise NamuWikiLyricsError("NamuWiki response was too large.")
    return payload


def request_namuwiki_api_source(document: str) -> str | None:
    if not NAMUWIKI_API_TOKEN:
        return None

    url = (
        f"{NAMUWIKI_API_BASE_URL}/edit/"
        f"{urllib.parse.quote(document, safe='')}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {NAMUWIKI_API_TOKEN}",
            "User-Agent": (
                "discord-music-bot/1.0 "
                "(https://github.com/rpr123/discord-music-bot)"
            ),
        },
    )
    wait_for_namuwiki_interval()
    try:
        with urllib.request.urlopen(
            request,
            timeout=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(
                read_limited_http_response(response).decode("utf-8")
            )
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return None
        raise NamuWikiLyricsError(f"NamuWiki API returned HTTP {error.code}.") from error
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise NamuWikiLyricsError(str(error)) from error

    if not isinstance(payload, dict) or payload.get("exists") is False:
        return None
    source = payload.get("text")
    return source if isinstance(source, str) and source.strip() else None


def request_namuwiki_html(page_url: str) -> tuple[str, str] | None:
    request = urllib.request.Request(
        page_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        },
    )
    wait_for_namuwiki_interval()
    try:
        with urllib.request.urlopen(
            request,
            timeout=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = read_limited_http_response(response)
            final_url = response.geturl()
    except urllib.error.HTTPError as error:
        if error.code in {404, 410}:
            return None
        raise NamuWikiLyricsError(
            f"NamuWiki page returned HTTP {error.code}."
        ) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise NamuWikiLyricsError(str(error)) from error

    source = payload.decode("utf-8", errors="replace")
    lowered_source = source.casefold()
    if any(marker in lowered_source for marker in NAMUWIKI_BLOCKED_MARKERS):
        raise NamuWikiLyricsError("NamuWiki blocked or challenged the request.")
    return source, final_url


def lookup_namuwiki_lyrics(
    track: Track,
) -> tuple[str, str, str] | None:
    if not NAMUWIKI_LYRICS_ENABLED or track.is_local:
        return None

    candidates = get_namuwiki_document_candidates(track)
    for candidate in candidates:
        try:
            document, page_url = split_namuwiki_candidate(candidate)
        except NamuWikiLyricsError as error:
            logger.warning(
                "Invalid NamuWiki document candidate for %s: %s",
                track.title,
                error,
            )
            continue

        if NAMUWIKI_API_TOKEN:
            try:
                namumark = request_namuwiki_api_source(document)
            except NamuWikiLyricsError as error:
                logger.warning(
                    "NamuWiki API lookup failed for %s (%s): %s",
                    track.title,
                    document,
                    error,
                )
            else:
                if namumark:
                    try:
                        lyrics = extract_namuwiki_lyrics_from_namumark(
                            namumark
                        )
                    except Exception as error:
                        logger.warning(
                            "NamuWiki source parsing failed for %s (%s): %s",
                            track.title,
                            document,
                            error,
                        )
                        lyrics = None
                    if lyrics:
                        return lyrics, "나무위키 · 원문·독음·번역", page_url

        try:
            html_result = request_namuwiki_html(page_url)
        except NamuWikiLyricsError as error:
            logger.warning(
                "NamuWiki page lookup failed for %s (%s): %s",
                track.title,
                document,
                error,
            )
            continue
        if html_result is None:
            continue

        page_source, final_url = html_result
        try:
            lyrics = extract_namuwiki_lyrics_from_html(page_source)
        except NamuWikiLyricsError as error:
            logger.warning(
                "NamuWiki HTML parsing failed for %s (%s): %s",
                track.title,
                document,
                error,
            )
            continue
        if lyrics:
            logger.info(
                "NamuWiki lyrics selected for %s (%s)",
                track.title,
                document,
            )
            return lyrics, "나무위키 · 원문·독음·번역", final_url

    if candidates:
        logger.info(
            "No NamuWiki lyrics found for %s (candidates: %s)",
            track.title,
            ", ".join(candidates),
        )
    return None


def get_lyrics_search_terms(track: Track) -> tuple[str, str | None]:
    parsed_artist: str | None = None
    raw_title = track.song_name or track.title
    quoted_match = (
        QUOTED_TRACK_TITLE_RE.match(raw_title)
        if track.song_name is None
        else None
    )
    if quoted_match:
        parsed_artist = quoted_match.group("artist")
        song_name = clean_track_title(quoted_match.group("title"))
    else:
        cleaned_title = clean_track_title(raw_title)
        song_name = cleaned_title

    if track.song_name is None and quoted_match is None:
        title_parts = re.split(
            r"\s+(?:-|–|—|\|)\s+",
            song_name,
            maxsplit=1,
        )
        if len(title_parts) == 2:
            parsed_artist, song_name = title_parts

    artist = track.artist or parsed_artist or track.uploader
    artist_name = normalize_artist_name(artist) if artist else None
    return song_name.strip(), artist_name or None


def extract_original_lyrics(record: dict) -> str | None:
    if record.get("instrumental"):
        return None

    plain_lyrics = record.get("plainLyrics")
    if isinstance(plain_lyrics, str) and plain_lyrics.strip():
        return plain_lyrics.replace("\r\n", "\n").replace("\r", "\n").strip()

    synced_lyrics = record.get("syncedLyrics")
    if not isinstance(synced_lyrics, str) or not synced_lyrics.strip():
        return None

    lines = []
    for line in synced_lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if LRC_METADATA_RE.fullmatch(line.strip()):
            continue
        lines.append(LRC_TIMESTAMP_RE.sub("", line))
    lyrics = "\n".join(lines).strip()
    return lyrics or None


def normalize_lyrics_match_text(value: str) -> str:
    return normalize_identity_component(clean_track_title(value))


def get_lyrics_title_aliases(value: str) -> set[str]:
    cleaned_value = clean_track_title(value)
    aliases = {normalize_identity_component(cleaned_value)}
    aliases.update(
        normalize_identity_component(part)
        for part in re.split(
            r"\s+(?:-|–|—|\||/)\s+",
            cleaned_value,
        )
    )
    return {alias for alias in aliases if alias}


def lyrics_native_script_ratio(record: dict) -> float:
    lyrics = extract_original_lyrics(record) or ""
    letters = [character for character in lyrics if character.isalpha()]
    if not letters:
        return 0.0

    non_latin_letters = sum(
        "LATIN" not in unicodedata.name(character, "")
        for character in letters
    )
    return non_latin_letters / len(letters)


def lyrics_record_score(
    record: dict,
    track_name: str,
    artist_name: str | None,
    duration: int | None,
) -> int | None:
    if extract_original_lyrics(record) is None:
        return None

    expected_title = normalize_lyrics_match_text(track_name)
    candidate_title = normalize_lyrics_match_text(str(record.get("trackName") or ""))
    if not expected_title or not candidate_title:
        return None

    expected_aliases = get_lyrics_title_aliases(track_name)
    candidate_aliases = get_lyrics_title_aliases(
        str(record.get("trackName") or "")
    )
    title_is_exact = bool(expected_aliases & candidate_aliases)
    if title_is_exact:
        score = 100
    elif (
        len(expected_title) >= 4
        and (expected_title in candidate_title or candidate_title in expected_title)
    ):
        score = 40
    else:
        return None

    candidate_duration = record.get("duration")
    duration_difference = (
        abs(float(candidate_duration) - duration)
        if duration is not None and isinstance(candidate_duration, (int, float))
        else None
    )
    title_and_duration_match = (
        title_is_exact
        and duration_difference is not None
        and duration_difference <= LYRICS_DURATION_MATCH_TOLERANCE_SECONDS
    )

    if artist_name:
        expected_artist = normalize_artist_name(artist_name)
        candidate_artist = normalize_artist_name(str(record.get("artistName") or ""))
        if candidate_artist == expected_artist:
            score += 80
        elif (
            candidate_artist
            and len(expected_artist) >= 3
            and (expected_artist in candidate_artist or candidate_artist in expected_artist)
        ):
            score += 25
        elif not title_and_duration_match:
            return None

    if duration_difference is not None:
        if duration_difference <= 2:
            score += 40
        elif duration_difference <= 8:
            score += 20
        elif duration_difference <= 20:
            score += 5

    return score


def select_lyrics_record(
    records: list[dict],
    track_name: str,
    artist_name: str | None,
    duration: int | None,
) -> dict | None:
    scored_records: list[tuple[dict, int]] = []
    for record in records:
        score = lyrics_record_score(record, track_name, artist_name, duration)
        if score is not None:
            scored_records.append((record, score))

    if not scored_records:
        return None

    best_score = max(score for _, score in scored_records)
    close_matches = [
        (record, score)
        for record, score in scored_records
        if score >= best_score - LYRICS_NATIVE_SCRIPT_SCORE_WINDOW
    ]
    native_script_matches: list[tuple[dict, int, float]] = []
    for record, score in close_matches:
        native_script_ratio = lyrics_native_script_ratio(record)
        if native_script_ratio >= LYRICS_NATIVE_SCRIPT_MIN_RATIO:
            native_script_matches.append((record, score, native_script_ratio))
    if native_script_matches:
        return max(
            native_script_matches,
            key=lambda candidate: (candidate[1], candidate[2]),
        )[0]

    return max(scored_records, key=lambda candidate: candidate[1])[0]


def request_lyrics_records(track_name: str, artist_name: str | None) -> list[dict]:
    params = {"track_name": track_name}
    if artist_name:
        params["artist_name"] = artist_name
    separator = "&" if "?" in LYRICS_API_URL else "?"
    url = f"{LYRICS_API_URL}{separator}{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                "discord-music-bot/1.0 "
                "(https://github.com/rpr123/discord-music-bot)"
            ),
        },
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise LyricsLookupError(str(error)) from error

    if not isinstance(payload, list):
        raise LyricsLookupError("Lyrics API returned an invalid response.")
    return [record for record in payload if isinstance(record, dict)]


def lookup_track_lyrics(track: Track) -> str | None:
    if track.is_local:
        return None

    track_name, artist_name = get_lyrics_search_terms(track)
    if not track_name:
        return None
    records = request_lyrics_records(track_name, artist_name)
    record = select_lyrics_record(
        records,
        track_name,
        artist_name,
        track.duration,
    )
    if record is None and artist_name:
        records = request_lyrics_records(track_name, None)
        record = select_lyrics_record(
            records,
            track_name,
            artist_name,
            track.duration,
        )
        if record is not None:
            logger.info(
                "LRCLIB title-only retry matched lyrics for %s",
                track.title,
            )
    return extract_original_lyrics(record) if record else None


def normalize_subtitle_text(value: str) -> str:
    return html.unescape(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_json3_lyrics(payload: str) -> str | None:
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as error:
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.") from error
    if not isinstance(document, dict):
        raise YouTubeSubtitleError("YouTube returned invalid JSON3 subtitles.")

    lines: list[str] = []
    for event in document.get("events") or []:
        if not isinstance(event, dict):
            continue
        segments = event.get("segs") or []
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in segments
            if isinstance(segment, dict)
        )
        for line in normalize_subtitle_text(text).splitlines():
            line = line.strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


VTT_TIMESTAMP_LINE_RE = re.compile(
    r"^(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}\s+-->\s+(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}"
)
VTT_TAG_RE = re.compile(r"<[^>]+>")


def extract_vtt_lyrics(payload: str) -> str | None:
    lines: list[str] = []
    skip_block = False
    for raw_line in normalize_subtitle_text(payload).splitlines():
        line = raw_line.strip()
        if line.startswith(("NOTE", "STYLE", "REGION")):
            skip_block = True
            continue
        if not line:
            skip_block = False
            continue
        if skip_block or line == "WEBVTT" or VTT_TIMESTAMP_LINE_RE.match(line):
            continue
        if line.isdigit():
            continue
        line = normalize_subtitle_text(VTT_TAG_RE.sub("", line))
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    lyrics = "\n".join(lines).strip()
    return lyrics or None


def get_subtitle_candidates(
    subtitles: dict[str, list[dict]],
) -> list[tuple[str, str, str, int]]:
    candidates: list[tuple[str, str, str, int]] = []
    format_scores = {"json3": 30, "vtt": 20}
    for language, formats in subtitles.items():
        if not isinstance(formats, list):
            continue
        for subtitle_format in formats:
            if not isinstance(subtitle_format, dict):
                continue
            extension = str(subtitle_format.get("ext") or "").casefold()
            url = subtitle_format.get("url")
            if extension not in format_scores or not isinstance(url, str) or not url:
                continue
            candidates.append(
                (str(language), extension, url, format_scores[extension])
            )
    return candidates


def get_manual_subtitle_candidates(track: Track) -> list[tuple[str, str, str, int]]:
    return get_subtitle_candidates(track.manual_subtitles)


def select_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    preferred_language = (track.subtitle_language or "").casefold()
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold()
        language_score = 0
        if preferred_language and (
            language_key == preferred_language
            or language_key.split("-", 1)[0] == preferred_language.split("-", 1)[0]
        ):
            language_score += 100
        if language_key.endswith("-orig"):
            language_score += 50
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url


def select_korean_manual_subtitle(track: Track) -> tuple[str, str, str] | None:
    candidates: list[tuple[int, str, str, str]] = []
    for language, extension, url, format_score in get_manual_subtitle_candidates(track):
        language_key = language.casefold().replace("_", "-")
        language_parts = language_key.split("-")
        if not language_parts or language_parts[0] != "ko":
            continue
        language_score = 20 if language_key in {"ko", "ko-kr"} else 0
        candidates.append(
            (language_score + format_score, language, extension, url)
        )

    if not candidates:
        return None
    _, language, extension, url = max(candidates, key=lambda candidate: candidate[0])
    return language, extension, url


def request_youtube_subtitle(url: str, extension: str) -> str | None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 discord-music-bot/1.0"},
    )
    try:
        with urllib.request.urlopen(
            request,
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        ) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise YouTubeSubtitleError(str(error)) from error

    if extension == "json3":
        return extract_json3_lyrics(payload)
    if extension == "vtt":
        return extract_vtt_lyrics(payload)
    return None


async def get_selected_youtube_subtitle(
    track: Track,
    selected: tuple[str, str, str] | None,
    *,
    purpose: str,
) -> str | None:
    if track.is_local or selected is None:
        return None

    language, extension, url = selected

    ensure_youtube_circuit_closed()
    try:
        await asyncio.wait_for(
            ytdl_semaphore.acquire(),
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise YouTubeSubtitleError("Timed out waiting to fetch YouTube subtitles.") from error

    try:
        ensure_youtube_circuit_closed()
        await wait_for_ytdl_interval()
        lyrics = await asyncio.wait_for(
            asyncio.to_thread(request_youtube_subtitle, url, extension),
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS + 2,
        )
    except Exception as error:
        trip_youtube_circuit(error)
        if isinstance(error, YouTubeCircuitOpenError):
            raise
        raise YouTubeSubtitleError(str(error)) from error
    finally:
        ytdl_semaphore.release()

    if lyrics:
        logger.info(
            "YouTube subtitles selected for %s (%s, %s)",
            track.title,
            language,
            purpose,
        )
    return lyrics


async def get_youtube_manual_lyrics(track: Track) -> str | None:
    if not YOUTUBE_LYRICS_FALLBACK:
        return None
    return await get_selected_youtube_subtitle(
        track,
        select_manual_subtitle(track),
        purpose="original lyrics",
    )


async def get_youtube_korean_lyrics(track: Track) -> tuple[str, str] | None:
    selected = select_korean_manual_subtitle(track)
    if selected is None:
        return None
    lyrics = await get_selected_youtube_subtitle(
        track,
        selected,
        purpose="manual Korean lyrics",
    )
    if not lyrics:
        return None
    return lyrics, "YouTube 제공 한국어 자막"


async def get_track_lyrics(track: Track) -> str | None:
    if track.lyrics_loaded:
        return track.lyrics

    lyrics: str | None = None
    try:
        lyrics = await asyncio.wait_for(
            asyncio.to_thread(lookup_track_lyrics, track),
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS + 2,
        )
    except (asyncio.TimeoutError, LyricsLookupError) as error:
        logger.warning("LRCLIB lookup failed for %s: %s", track.title, error)

    if lyrics:
        track.lyrics_source = "LRCLIB"
    else:
        try:
            lyrics = await get_youtube_manual_lyrics(track)
        except (asyncio.TimeoutError, YouTubeSubtitleError, YouTubeCircuitOpenError) as error:
            logger.warning("YouTube subtitle lookup failed for %s: %s", track.title, error)
        if lyrics:
            track.lyrics_source = "YouTube 수동 자막"

    track.lyrics = lyrics
    track.lyrics_loaded = True
    return lyrics


def lyrics_are_japanese(track: Track, lyrics: str) -> bool:
    language = (track.subtitle_language or "").lower()
    if language == "ja" or language.startswith("ja-"):
        return True
    return bool(JAPANESE_KANA_RE.search(lyrics) or JAPANESE_KANA_RE.search(track.title))


def lyrics_are_primarily_korean(lyrics: str) -> bool:
    letters = [character for character in lyrics if character.isalpha()]
    if not letters:
        return False
    hangul_characters = sum(bool(HANGUL_RE.fullmatch(character)) for character in letters)
    return hangul_characters / len(letters) >= 0.5


def can_show_korean_lyrics(track: Track, lyrics: str) -> bool:
    if not LYRICS_TRANSLATION_ENABLED:
        return False

    lyrics = lyrics.strip()
    if lyrics and lyrics_are_primarily_korean(lyrics):
        return False
    if not lyrics:
        language = (track.subtitle_language or "").casefold()
        title = track.song_name or clean_track_title_preserving_case(track.title)
        if (
            language == "ko"
            or language.startswith("ko-")
            or lyrics_are_primarily_korean(title)
        ):
            return False

    namuwiki_may_have_lyrics = NAMUWIKI_LYRICS_ENABLED and (
        not track.namuwiki_lyrics_checked
        or (
            track.korean_lyrics_loaded
            and track.korean_lyrics is not None
            and track.korean_lyrics_url is not None
        )
    )
    return bool(namuwiki_may_have_lyrics or select_korean_manual_subtitle(track))


def get_korean_lyrics_label(track: Track) -> str:
    if track.korean_lyrics_url or (
        NAMUWIKI_LYRICS_ENABLED and not track.namuwiki_lyrics_checked
    ):
        return "나무위키 가사"
    return "한국어 자막"


def split_namuwiki_lyrics_groups(value: str) -> list[list[str]]:
    return [
        [line.strip() for line in group.splitlines() if line.strip()]
        for group in re.split(r"\n\s*\n", value)
        if group.strip()
    ]


def extract_namuwiki_original_lyrics(value: str) -> str | None:
    source_lines = [
        lines[0]
        for lines in split_namuwiki_lyrics_groups(value)
        if len(lines) >= 2
        and (
            JAPANESE_KANA_RE.search(lines[0])
            or JAPANESE_HAN_RE.search(lines[0])
        )
    ]
    return "\n".join(source_lines) if source_lines else None


def extract_namuwiki_hiragana_reading(value: str) -> str | None:
    groups = split_namuwiki_lyrics_groups(value)
    japanese_groups = [
        lines
        for lines in groups
        if len(lines) >= 3
        and (
            JAPANESE_KANA_RE.search(lines[0])
            or JAPANESE_HAN_RE.search(lines[0])
        )
    ]
    if not japanese_groups:
        return None

    readings: list[str] = []
    for lines in japanese_groups:
        reading = next(
            (
                line
                for line in lines[1:-1]
                if JAPANESE_KANA_RE.search(line) and not HANGUL_RE.search(line)
            ),
            None,
        )
        if reading is None:
            return None
        readings.append(katakana_to_hiragana(reading))
    return "\n".join(readings)


def get_hiragana_reading_source_lyrics(track: Track, lyrics: str) -> str | None:
    if lyrics.strip() and lyrics_are_japanese(track, lyrics):
        return lyrics
    if track.korean_lyrics and track.korean_lyrics_url:
        return extract_namuwiki_original_lyrics(track.korean_lyrics)
    return None


def can_generate_lyrics_reading(track: Track, lyrics: str) -> bool:
    if not LYRICS_READING_ENABLED:
        return False
    if (
        track.korean_lyrics
        and track.korean_lyrics_url
        and extract_namuwiki_hiragana_reading(track.korean_lyrics)
    ):
        return True
    return bool(
        sudachi_dictionary is not None
        and get_hiragana_reading_source_lyrics(track, lyrics)
    )


def katakana_to_hiragana(value: str) -> str:
    converted: list[str] = []
    for character in value:
        codepoint = ord(character)
        if 0x30A1 <= codepoint <= 0x30F6:
            converted.append(chr(codepoint - 0x60))
        else:
            converted.append(character)
    return "".join(converted)


def get_sudachi_tokenizer():
    global SUDACHI_TOKENIZER
    if sudachi_dictionary is None:
        raise LyricsReadingError(
            "SudachiPy and SudachiDict-core are not installed."
        )
    if SUDACHI_TOKENIZER is None:
        SUDACHI_TOKENIZER = sudachi_dictionary.Dictionary().create()
    return SUDACHI_TOKENIZER


def find_explicit_reading_base_start(prefix: str, tokenizer) -> int | None:
    marker_index = max(prefix.rfind("|"), prefix.rfind("｜"))
    if marker_index >= 0:
        marked_base = prefix[marker_index + 1 :]
        if marked_base and JAPANESE_HAN_RE.search(marked_base):
            return marker_index

    if not prefix or not JAPANESE_HAN_RE.fullmatch(prefix[-1]):
        return None

    tokens = list(tokenizer.tokenize(prefix))
    token_positions: list[tuple[int, int, str]] = []
    position = 0
    for token in tokens:
        surface = token.surface()
        start = position
        position += len(surface)
        token_positions.append((start, position, surface))

    suffix_start = len(prefix)
    for start, end, surface in reversed(token_positions[-4:]):
        if end != suffix_start or not surface:
            break
        if surface.isspace() or all(
            unicodedata.category(character).startswith("P") for character in surface
        ):
            break
        suffix_start = start
        if JAPANESE_HAN_RE.search(surface):
            return suffix_start

    fallback = re.search(
        (
            r"[\u3005\u3007\u303b\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+"
            r"[\u3041-\u309f\u30a0-\u30ff\u30fc]{0,12}$"
        ),
        prefix,
    )
    return fallback.start() if fallback else None


def replace_explicit_readings(line: str, tokenizer) -> str:
    matches: list[tuple[int, int, str]] = []
    for opening, closing in EXPLICIT_READING_BRACKETS:
        pattern = re.compile(
            re.escape(opening)
            + r"(?P<reading>[^"
            + re.escape(closing)
            + r"]+)"
            + re.escape(closing)
        )
        for match in pattern.finditer(line):
            reading = match.group("reading").strip()
            if reading and JAPANESE_READING_RE.fullmatch(reading):
                matches.append((match.start(), match.end(), reading))

    if not matches:
        return line

    output: list[str] = []
    cursor = 0
    for opening_start, annotation_end, reading in sorted(matches):
        if opening_start < cursor:
            continue
        prefix = line[cursor:opening_start]
        base_start = find_explicit_reading_base_start(prefix, tokenizer)
        if base_start is None:
            output.append(line[cursor:annotation_end])
        else:
            output.append(prefix[:base_start])
            output.append(katakana_to_hiragana(reading))
        cursor = annotation_end
    output.append(line[cursor:])
    return "".join(output)


def token_to_hiragana(surface: str, reading: str) -> str:
    if (
        not reading
        or re.search(r"[A-Za-z]", surface)
        or surface.isspace()
        or all(
            unicodedata.category(character).startswith(("P", "S"))
            for character in surface
        )
    ):
        return surface
    return katakana_to_hiragana(reading)


def generate_hiragana_lyrics(lyrics: str) -> str:
    with SUDACHI_TOKENIZER_LOCK:
        tokenizer = get_sudachi_tokenizer()
        converted_lines: list[str] = []
        for line in lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = replace_explicit_readings(line, tokenizer)
            converted_tokens: list[str] = []
            for token in tokenizer.tokenize(line):
                surface = token.surface()
                reading = token.reading_form()
                converted_tokens.append(token_to_hiragana(surface, reading))
            converted_lines.append("".join(converted_tokens))
    reading_text = "\n".join(converted_lines).strip()
    if not reading_text:
        raise LyricsReadingError("Sudachi returned empty reading text.")
    return reading_text


async def get_track_namuwiki_lyrics(track: Track) -> str | None:
    if track.korean_lyrics_loaded:
        return (
            track.korean_lyrics
            if track.korean_lyrics is not None and track.korean_lyrics_url is not None
            else None
        )
    if track.namuwiki_lyrics_checked:
        return None

    async with track.korean_lyrics_lock:
        if track.korean_lyrics_loaded:
            return (
                track.korean_lyrics
                if (
                    track.korean_lyrics is not None
                    and track.korean_lyrics_url is not None
                )
                else None
            )
        if track.namuwiki_lyrics_checked:
            return None

        namuwiki_result: tuple[str, str, str] | None = None
        try:
            namuwiki_result = await asyncio.wait_for(
                asyncio.to_thread(lookup_namuwiki_lyrics, track),
                timeout=(
                    NAMUWIKI_REQUEST_TIMEOUT_SECONDS
                    * NAMUWIKI_MAX_DOCUMENT_CANDIDATES
                    * (2 if NAMUWIKI_API_TOKEN else 1)
                    + NAMUWIKI_REQUEST_INTERVAL_SECONDS
                    * NAMUWIKI_MAX_DOCUMENT_CANDIDATES
                    * (2 if NAMUWIKI_API_TOKEN else 1)
                    + 5
                ),
            )
        except (asyncio.TimeoutError, NamuWikiLyricsError) as error:
            logger.warning(
                "NamuWiki lyrics lookup failed for %s: %s",
                track.title,
                error,
            )
        except Exception:
            logger.exception(
                "Unexpected NamuWiki lyrics failure for %s",
                track.title,
            )
            return None

        track.namuwiki_lyrics_checked = True
        if namuwiki_result is not None:
            lyrics, source, source_url = namuwiki_result
            track.korean_lyrics = lyrics
            track.korean_lyrics_source = source
            track.korean_lyrics_url = source_url
            track.korean_lyrics_loaded = True
            return lyrics
        return None


async def get_track_korean_lyrics(track: Track) -> str:
    if track.korean_lyrics_loaded and track.korean_lyrics is not None:
        return track.korean_lyrics

    namuwiki_lyrics = await get_track_namuwiki_lyrics(track)
    if namuwiki_lyrics is not None:
        return namuwiki_lyrics

    async with track.korean_lyrics_lock:
        if track.korean_lyrics_loaded and track.korean_lyrics is not None:
            return track.korean_lyrics
        try:
            youtube_result = await get_youtube_korean_lyrics(track)
        except (YouTubeSubtitleError, YouTubeCircuitOpenError) as error:
            raise KoreanLyricsError(str(error)) from error
        if youtube_result is None:
            raise KoreanLyricsError(
                "No NamuWiki lyrics or manually provided Korean YouTube subtitles "
                "are available."
            )

        lyrics, source = youtube_result
        track.korean_lyrics = lyrics
        track.korean_lyrics_source = source
        track.korean_lyrics_url = None
        track.korean_lyrics_loaded = True
        return lyrics


async def get_track_hiragana_reading(track: Track) -> str:
    if track.lyrics_reading_loaded and track.lyrics_reading is not None:
        return track.lyrics_reading

    async with track.lyrics_reading_lock:
        if track.lyrics_reading_loaded and track.lyrics_reading is not None:
            return track.lyrics_reading

        if track.korean_lyrics and track.korean_lyrics_url:
            reading = extract_namuwiki_hiragana_reading(track.korean_lyrics)
            if reading:
                track.lyrics_reading = reading
                track.lyrics_reading_loaded = True
                track.lyrics_reading_source = "나무위키 · 일본어 독음"
                track.lyrics_reading_url = track.korean_lyrics_url
                return reading

        source_lyrics = get_hiragana_reading_source_lyrics(
            track,
            track.lyrics or "",
        )
        if not source_lyrics:
            raise LyricsReadingError("Japanese source lyrics are not available.")
        try:
            reading = await asyncio.to_thread(
                generate_hiragana_lyrics,
                source_lyrics,
            )
        except LyricsReadingError:
            raise
        except Exception as error:
            raise LyricsReadingError(str(error)) from error
        track.lyrics_reading = reading
        track.lyrics_reading_loaded = True
        if track.korean_lyrics_url and source_lyrics != track.lyrics:
            track.lyrics_reading_source = "나무위키 원문 · Sudachi 자동 독음"
            track.lyrics_reading_url = track.korean_lyrics_url
        else:
            track.lyrics_reading_source = "Sudachi · 자동 독음"
            track.lyrics_reading_url = None
        return reading


def cancel_lyrics_publish(state: GuildMusicState) -> None:
    task = state.lyrics_task
    if task and not task.done():
        task.cancel()
    state.lyrics_task = None


async def clear_lyrics_message(guild_id: int, state: GuildMusicState) -> None:
    messages = (state.lyrics_message, state.namuwiki_notice_message)
    state.lyrics_message = None
    state.namuwiki_notice_message = None
    replace_lyrics_view(state, None)
    for message in messages:
        if message is not None:
            await delete_music_channel_message(guild_id, message)


async def clear_namuwiki_lyrics_notice(
    guild_id: int,
    state: GuildMusicState,
) -> None:
    message = state.namuwiki_notice_message
    state.namuwiki_notice_message = None
    if message is not None:
        await delete_music_channel_message(guild_id, message)


def schedule_lyrics_message_cleanup(guild_id: int, state: GuildMusicState) -> None:
    messages = (state.lyrics_message, state.namuwiki_notice_message)
    state.lyrics_message = None
    state.namuwiki_notice_message = None
    replace_lyrics_view(state, None)
    for message in messages:
        if message is not None:
            asyncio.create_task(delete_music_channel_message(guild_id, message))


def make_lyrics_file(lyrics: str, filename: str = "lyrics.txt") -> discord.File:
    return discord.File(
        io.BytesIO(lyrics.encode("utf-8")),
        filename=filename,
    )


def track_is_current(guild_id: int, track: Track) -> bool:
    state = music_states.get(guild_id)
    return state is not None and state.current is track


def replace_lyrics_view(
    state: GuildMusicState,
    view: discord.ui.View | None,
) -> None:
    previous_view = state.lyrics_view
    state.lyrics_view = view
    if previous_view is not None and previous_view is not view:
        previous_view.stop()


async def send_private_lyrics_variant(
    interaction: discord.Interaction,
    guild_id: int,
    track: Track,
    *,
    label: str,
    text: str,
    source: str,
    filename: str,
    source_url: str | None = None,
) -> None:
    if len(text) <= LYRICS_INLINE_LIMIT:
        embed = make_lyrics_variant_embed(
            track,
            label,
            text,
            source,
            source_url,
        )
        message = await send_ephemeral_followup(
            interaction,
            embed=embed,
            delete_after=None,
        )
        if message is not None:
            await register_private_lyrics_message(guild_id, track, message)
        return

    embed = make_lyrics_variant_embed(
        track,
        label,
        "내용이 길어 전체 내용을 파일로 첨부했어요.",
        source,
        source_url,
    )
    message = await send_ephemeral_followup(
        interaction,
        embed=embed,
        file=make_lyrics_file(text, filename),
        delete_after=None,
    )
    if message is not None:
        await register_private_lyrics_message(guild_id, track, message)


class LyricsVariantView(discord.ui.View):
    def __init__(self, guild_id: int, track: Track, lyrics: str):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self.track = track

        if can_show_korean_lyrics(track, lyrics):
            korean_lyrics_button = discord.ui.Button(
                label=get_korean_lyrics_label(track),
                style=discord.ButtonStyle.secondary,
                custom_id=f"lyrics:korean:{track.track_id}",
            )
            korean_lyrics_button.callback = self.show_korean_lyrics
            self.add_item(korean_lyrics_button)

        if can_generate_lyrics_reading(track, lyrics):
            reading_button = discord.ui.Button(
                label="히라가나 독음",
                style=discord.ButtonStyle.secondary,
                custom_id=f"lyrics:reading:{track.track_id}",
            )
            reading_button.callback = self.show_reading
            self.add_item(reading_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if track_is_current(self.guild_id, self.track):
            return True
        await send_ephemeral_response(
            interaction,
            "이미 재생이 끝난 곡이에요.",
        )
        return False

    async def show_korean_lyrics(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            lyrics = await get_track_korean_lyrics(self.track)
        except KoreanLyricsError as error:
            logger.warning(
                "Korean lyrics lookup failed for %s: %s",
                self.track.title,
                error,
            )
            await send_ephemeral_followup(
                interaction,
                "한국어 가사를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
            )
            return

        if not track_is_current(self.guild_id, self.track):
            await send_ephemeral_followup(
                interaction,
                "가사를 가져오는 동안 곡이 바뀌었어요.",
            )
            return
        await send_private_lyrics_variant(
            interaction,
            self.guild_id,
            self.track,
            label=get_korean_lyrics_label(self.track),
            text=lyrics,
            source=(
                self.track.korean_lyrics_source
                or get_korean_lyrics_label(self.track)
            ),
            filename="lyrics-korean.txt",
            source_url=self.track.korean_lyrics_url,
        )

    async def show_reading(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            reading = await get_track_hiragana_reading(self.track)
        except LyricsReadingError as error:
            logger.warning(
                "Lyrics reading generation failed for %s: %s",
                self.track.title,
                error,
            )
            await send_ephemeral_followup(
                interaction,
                "히라가나 독음을 만들지 못했어요.",
            )
            return

        if not track_is_current(self.guild_id, self.track):
            await send_ephemeral_followup(
                interaction,
                "독음을 만드는 동안 곡이 바뀌었어요.",
            )
            return
        await send_private_lyrics_variant(
            interaction,
            self.guild_id,
            self.track,
            label="히라가나 독음",
            text=reading,
            source=self.track.lyrics_reading_source or "Sudachi · 자동 독음",
            filename="lyrics-hiragana.txt",
            source_url=self.track.lyrics_reading_url,
        )


def make_lyrics_variant_view(
    guild_id: int,
    track: Track,
    lyrics: str,
) -> LyricsVariantView | None:
    view = LyricsVariantView(guild_id, track, lyrics)
    return view if view.children else None


async def upsert_lyrics_message(
    guild_id: int,
    state: GuildMusicState,
    track: Track,
    description: str,
    *,
    attachment_lyrics: str | None = None,
    view: discord.ui.View | None = None,
) -> discord.Message | None:
    channel = resolve_control_panel_channel(guild_id, state)
    if channel is None or state.current is not track:
        return None

    message = state.lyrics_message
    if message is not None:
        message_channel_id = getattr(getattr(message, "channel", None), "id", None)
        channel_id = getattr(channel, "id", None)
        if (
            message_channel_id is not None
            and channel_id is not None
            and message_channel_id != channel_id
        ):
            await delete_music_channel_message(guild_id, message)
            state.lyrics_message = None
            replace_lyrics_view(state, None)
            message = None

    embed = make_lyrics_embed(track, description)
    if message is not None:
        attachments = (
            [make_lyrics_file(attachment_lyrics)]
            if attachment_lyrics is not None
            else []
        )
        try:
            edited_message = await message.edit(
                content=None,
                embed=embed,
                attachments=attachments,
                view=view,
            )
        except discord.NotFound:
            state.lyrics_message = None
            replace_lyrics_view(state, None)
            message = None
        except discord.Forbidden:
            logger.warning(
                "Missing permission to edit lyrics in guild %s",
                guild_id,
            )
            return None
        except discord.HTTPException:
            logger.exception("Failed to edit lyrics in guild %s", guild_id)
            return None
        else:
            if state.current is not track:
                await delete_music_channel_message(
                    guild_id,
                    edited_message or message,
                )
                return None
            replace_lyrics_view(state, view)
            state.lyrics_message = edited_message or message
            return state.lyrics_message

    send_options: dict[str, object] = {
        "embed": embed,
        "silent": is_silent_music_channel(channel),
    }
    if attachment_lyrics is not None:
        send_options["file"] = make_lyrics_file(attachment_lyrics)
    if view is not None:
        send_options["view"] = view
    try:
        message = await channel.send(**send_options)
    except discord.Forbidden:
        logger.warning("Missing permission to send lyrics in guild %s", guild_id)
        return None
    except discord.HTTPException:
        logger.exception("Failed to send lyrics in guild %s", guild_id)
        return None

    if state.current is not track:
        await delete_music_channel_message(guild_id, message)
        return None
    replace_lyrics_view(state, view)
    state.lyrics_message = message
    return message


async def upsert_namuwiki_lyrics_notice(
    guild_id: int,
    state: GuildMusicState,
    track: Track,
) -> discord.Message | None:
    channel = resolve_control_panel_channel(guild_id, state)
    if channel is None or state.current is not track:
        return None

    message = state.namuwiki_notice_message
    if message is not None:
        message_channel_id = getattr(getattr(message, "channel", None), "id", None)
        channel_id = getattr(channel, "id", None)
        if (
            message_channel_id is not None
            and channel_id is not None
            and message_channel_id != channel_id
        ):
            await delete_music_channel_message(guild_id, message)
            state.namuwiki_notice_message = None
            message = None

    embed = make_lyrics_variant_embed(
        track,
        "나무위키 가사 발견",
        "원문 가사는 찾지 못했지만, "
        "나무위키에는 원문·독음·번역 가사가 있어요.",
        track.korean_lyrics_source or "나무위키 · 원문·독음·번역",
        track.korean_lyrics_url,
    )

    if message is not None:
        try:
            edited_message = await message.edit(
                content=None,
                embed=embed,
                attachments=[],
                view=None,
            )
        except discord.NotFound:
            state.namuwiki_notice_message = None
            message = None
        except discord.Forbidden:
            logger.warning(
                "Missing permission to edit NamuWiki lyrics notice in guild %s",
                guild_id,
            )
            return None
        except discord.HTTPException:
            logger.exception(
                "Failed to edit NamuWiki lyrics notice in guild %s",
                guild_id,
            )
            return None
        else:
            if state.current is not track:
                await delete_music_channel_message(
                    guild_id,
                    edited_message or message,
                )
                return None
            state.namuwiki_notice_message = edited_message or message
            return state.namuwiki_notice_message

    send_options: dict[str, object] = {
        "embed": embed,
        "silent": is_silent_music_channel(channel),
    }
    try:
        message = await channel.send(**send_options)
    except discord.Forbidden:
        logger.warning(
            "Missing permission to send NamuWiki lyrics notice in guild %s",
            guild_id,
        )
        return None
    except discord.HTTPException:
        logger.exception(
            "Failed to send NamuWiki lyrics notice in guild %s",
            guild_id,
        )
        return None

    if state.current is not track:
        await delete_music_channel_message(guild_id, message)
        return None
    state.namuwiki_notice_message = message
    return message


def schedule_lyrics_publish(
    guild_id: int,
    track: Track,
) -> tuple[asyncio.Task[None], bool]:
    state = get_state(guild_id)
    if state.lyrics_task and not state.lyrics_task.done():
        if state.current is track:
            return state.lyrics_task, False
        state.lyrics_task.cancel()

    task = asyncio.create_task(publish_current_lyrics(guild_id, track))
    state.lyrics_task = task
    return task, True


async def publish_current_lyrics(guild_id: int, track: Track) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    try:
        await clear_namuwiki_lyrics_notice(guild_id, state)
        await upsert_lyrics_message(
            guild_id,
            state,
            track,
            "가사를 찾고 있어요...",
        )
        lyrics = await get_track_lyrics(track)
        if state.current is not track:
            return
        if not lyrics:
            view = make_lyrics_variant_view(guild_id, track, "")
            await upsert_lyrics_message(
                guild_id,
                state,
                track,
                "미제공",
                view=view,
            )
        else:
            view = make_lyrics_variant_view(guild_id, track, lyrics)
            if len(lyrics) <= LYRICS_INLINE_LIMIT:
                await upsert_lyrics_message(
                    guild_id,
                    state,
                    track,
                    lyrics,
                    view=view,
                )
            else:
                await upsert_lyrics_message(
                    guild_id,
                    state,
                    track,
                    "가사가 길어 전체 원문을 첨부했어요.",
                    attachment_lyrics=lyrics,
                    view=view,
                )

        if not lyrics:
            namuwiki_lyrics = await get_track_namuwiki_lyrics(track)
            if state.current is not track:
                return
            if namuwiki_lyrics:
                view = make_lyrics_variant_view(guild_id, track, "")
                await upsert_lyrics_message(
                    guild_id,
                    state,
                    track,
                    "미제공",
                    view=view,
                )
                await upsert_namuwiki_lyrics_notice(
                    guild_id,
                    state,
                    track,
                )
            else:
                view = make_lyrics_variant_view(guild_id, track, "")
                await upsert_lyrics_message(
                    guild_id,
                    state,
                    track,
                    "미제공",
                    view=view,
                )
    except asyncio.CancelledError:
        raise
    finally:
        if state.lyrics_task is current_task:
            state.lyrics_task = None


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
        manual_subtitles=get_manual_subtitles(info),
        subtitle_language=info.get("language") or info.get("original_language"),
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
    counted_match = re.match(
        r"^auto\s*(\d+)\s*:\s*(.*)$",
        query,
        flags=re.IGNORECASE,
    )
    if counted_match:
        count_text = counted_match.group(1)
        rest = counted_match.group(2).strip()
        if not rest:
            raise ValueError(
                f"auto{count_text}: 또는 auto {count_text}: 뒤에 "
                "곡명이나 아티스트를 입력해 주세요."
            )
        return rest, clamp_auto_count(int(count_text))

    default_match = re.match(r"^auto(?::|\s+)(.*)$", query, flags=re.IGNORECASE)
    if not default_match:
        return None

    rest = default_match.group(1).strip()
    if not rest:
        raise ValueError("auto: 뒤에 곡명이나 아티스트를 입력해 주세요.")

    old_count_match = re.match(r"^(\d+)(?::|\s+|$)", rest)
    if old_count_match:
        count_text = old_count_match.group(1)
        raise ValueError(
            f"곡 개수는 `auto{count_text}: 곡명` 또는 `auto {count_text}: 곡명`처럼 "
            "콜론 앞에 입력해 주세요."
        )

    return rest, DEFAULT_AUTO_TRACKS


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
    track.manual_subtitles = get_manual_subtitles(info)
    track.subtitle_language = (
        info.get("language") or info.get("original_language") or track.subtitle_language
    )


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
    return make_track_from_info(info, requester, resolved_query, requester_id)


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
        seen_keys.update(get_track_identity_keys(track))
        tracks.append(track)
        if len(tracks) >= auto_count:
            return tracks

    for entry in entries:
        track = make_track_from_info(entry, requester, fallback_url, requester_id)
        if not get_video_id(entry, track.webpage_url):
            continue
        identity_keys = get_track_identity_keys(track)
        if not seen_keys.isdisjoint(identity_keys):
            continue
        seen_keys.update(identity_keys)
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
            identity_keys = get_track_identity_keys(track)
            if not seen_keys.isdisjoint(identity_keys):
                continue
            seen_keys.update(identity_keys)
            tracks.append(track)
            if len(tracks) >= auto_count:
                break

    if not tracks:
        raise ValueError(f"관련 곡을 찾지 못했어요: {query}")

    return tracks


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


def get_autoplay_seed(state: GuildMusicState) -> Track | None:
    if state.queue:
        return state.queue[-1]
    return state.current


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
    initial_seed_keys = get_track_identity_keys(fallback_seed)
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
                initial_seed_keys | get_track_identity_keys(seed),
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
                if not get_track_identity_keys(candidate).isdisjoint(
                    get_autoplay_excluded_keys(state)
                ):
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
        await send_ephemeral_followup(
            interaction,
            "먼저 음성 채널에 들어가 주세요.",
        )
        return False

    if state.voice and not state.voice.is_connected():
        stop_playback(state, interaction.guild_id)
        state.voice = None

    if state.voice and state.voice.is_connected():
        if state.voice.channel != channel:
            if state.current or state.queue or state.voice.is_playing() or state.voice.is_paused():
                await send_ephemeral_followup(
                    interaction,
                    f"봇이 이미 {state.voice.channel.mention}에서 재생 중이에요. "
                    "같은 음성 채널에 들어와 주세요.",
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
        stop_playback(state, member.guild.id)
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
        await send_ephemeral_followup(interaction, message)
    else:
        await send_ephemeral_response(interaction, message)
    return False


def stop_playback(state: GuildMusicState, guild_id: int) -> None:
    state.playback_generation += 1
    state.stop_requested = True
    state.queue.clear()
    schedule_private_lyrics_cleanup(state)
    state.current = None
    cancel_autoplay_refill(state)
    cancel_lyrics_publish(state)
    schedule_lyrics_message_cleanup(guild_id, state)

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

        stop_playback(state, guild_id)
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
            try:
                await initial_response.edit(content=content, embed=embed, view=view)
            except discord.NotFound:
                pass
            except discord.HTTPException as error:
                log_discord_http_error("editing music feedback", error)
                asyncio.create_task(
                    delete_message_later(initial_response, MUSIC_FEEDBACK_DELETE_SECONDS)
                )
            else:
                if view is None or private:
                    asyncio.create_task(
                        delete_message_later(
                            initial_response,
                            MUSIC_FEEDBACK_DELETE_SECONDS,
                        )
                    )
                return initial_response

        try:
            message = await text_channel.send(
                content=content,
                embed=embed,
                view=view,
                silent=is_silent_music_channel(text_channel),
            )
        except discord.HTTPException as error:
            log_discord_http_error("sending music feedback", error)
            return None
        if view is None or private:
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
    queue_size = len(state.queue)
    if len(tracks) == 1:
        embed = make_track_embed(tracks[0], "Added to queue")
        embed.add_field(name="Position", value=str(queue_size), inline=True)
    else:
        embed = make_bulk_embed(tracks, "Added playlist to queue")
        embed.add_field(name="Queue size", value=str(queue_size), inline=True)

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

    await send_feedback(embed=embed, private=True)

    if started_playback and playback_task:
        await playback_task
        if state.current:
            await update_control_panel(guild_id, state)
        else:
            await send_feedback(content="재생을 시작하지 못했어요. 로그를 확인해 주세요.")
        return state.current is not None

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


def message_has_component_custom_id(
    message: discord.Message,
    custom_id: str,
) -> bool:
    for row in getattr(message, "components", ()):
        for component in getattr(row, "children", ()):
            if getattr(component, "custom_id", None) == custom_id:
                return True
    return False


def is_music_control_panel_message(
    message: discord.Message,
    bot_user_id: int | None = None,
) -> bool:
    if bot_user_id is None:
        bot_user_id = getattr(bot.user, "id", None)
    if bot_user_id is None or getattr(message.author, "id", None) != bot_user_id:
        return False

    has_panel_title = any(
        getattr(embed, "title", None) in CONTROL_PANEL_TITLES
        for embed in getattr(message, "embeds", ())
    )
    return has_panel_title and message_has_component_custom_id(
        message,
        AUTOPLAY_BUTTON_CUSTOM_ID,
    )


async def reconcile_control_panel_messages(
    guild_id: int,
    control_channel: discord.abc.Messageable,
    known_message: discord.Message | None,
    *,
    delete_non_panel_messages: bool = False,
) -> discord.Message | None:
    history = getattr(control_channel, "history", None)
    if history is None:
        return known_message

    candidates: dict[int, discord.Message] = {}
    if known_message is not None:
        candidates[known_message.id] = known_message

    bot_user_id = getattr(bot.user, "id", None)
    deleted_message_count = 0
    try:
        history_limit = None if delete_non_panel_messages else CONTROL_PANEL_HISTORY_LIMIT
        async for message in history(limit=history_limit):
            if (
                message.id in candidates
                or is_music_control_panel_message(message, bot_user_id)
            ):
                candidates[message.id] = message
            elif delete_non_panel_messages and await delete_music_channel_message(
                guild_id,
                message,
            ):
                deleted_message_count += 1
    except discord.Forbidden:
        logger.warning(
            "Missing permission to read music channel history in guild %s",
            guild_id,
        )
        return known_message
    except discord.HTTPException:
        logger.exception(
            "Failed to read music channel history in guild %s",
            guild_id,
        )
        return known_message

    if not candidates:
        if deleted_message_count:
            logger.info(
                "Cleaned %s message(s) from the music channel in guild %s",
                deleted_message_count,
                guild_id,
            )
        return None

    newest_message = max(candidates.values(), key=lambda message: message.id)
    removed_panel_count = 0
    for message in candidates.values():
        if message.id == newest_message.id:
            continue
        if await delete_music_channel_message(guild_id, message):
            removed_panel_count += 1

    if deleted_message_count or removed_panel_count:
        logger.info(
            "Kept control panel %s and removed %s other message(s) and "
            "%s duplicate panel(s) in guild %s",
            newest_message.id,
            deleted_message_count,
            removed_panel_count,
            guild_id,
        )
    return newest_message


async def delete_music_channel_message(
    guild_id: int,
    message: discord.Message,
) -> bool:
    try:
        await message.delete()
        return True
    except discord.NotFound:
        return False
    except discord.Forbidden:
        logger.warning(
            "Missing permission to delete message %s from the music channel in guild %s",
            message.id,
            guild_id,
        )
    except discord.HTTPException:
        logger.exception(
            "Failed to delete message %s from the music channel in guild %s",
            message.id,
            guild_id,
        )
    return False


async def update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
    clean_channel: bool = False,
) -> discord.Message | None:
    async with state.control_panel_lock:
        return await _update_control_panel(
            guild_id,
            state,
            channel=channel,
            clean_channel=clean_channel,
        )


async def _update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
    clean_channel: bool = False,
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

    recovering_panel = state.control_message is None
    reconciling_panel = recovering_panel or clean_channel
    saved_message_id = get_control_message_id(guild_id) if reconciling_panel else None
    if recovering_panel:
        fetch_message = getattr(control_channel, "fetch_message", None)
        if saved_message_id is not None and fetch_message is not None:
            try:
                state.control_message = await fetch_message(saved_message_id)
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

    if reconciling_panel:
        state.control_message = await reconcile_control_panel_messages(
            guild_id,
            control_channel,
            state.control_message,
            delete_non_panel_messages=clean_channel,
        )

    if state.current is None:
        embed = make_idle_player_embed()
        view = MusicControlView(guild_id, disabled=True)
    else:
        embed = make_player_embed(state.current, state)
        view = MusicControlView(guild_id)

    if state.control_message is not None:
        try:
            await state.control_message.edit(content=None, embed=embed, view=view)
            if reconciling_panel and saved_message_id != state.control_message.id:
                set_control_message_id(guild_id, state.control_message.id)
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
            await update_control_panel(
                guild.id,
                state,
                channel=channel,
                clean_channel=True,
            )
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
            cancel_lyrics_publish(state)
            await clear_lyrics_message(guild_id, state)
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
                cancel_lyrics_publish(state)
                await clear_lyrics_message(guild_id, state)
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

                            schedule_private_lyrics_cleanup(state, track.track_id)
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
            if state.current is track:
                schedule_lyrics_publish(guild_id, track)
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
        error_message = await send_music_request_reply(message, error)
        if error_message is not None:
            asyncio.create_task(
                delete_message_later(error_message, MUSIC_FEEDBACK_DELETE_SECONDS)
            )
        await delete_music_request_message(message)
        return

    loading_message = await send_music_request_reply(message, "곡을 찾고 있어요...")
    try:
        await enqueue_tracks(
            message.guild.id,
            message.channel,
            message.author,
            query,
            initial_response=loading_message,
        )
    except discord.HTTPException as error:
        log_discord_http_error("processing a music request", error)
        if loading_message is not None:
            asyncio.create_task(
                delete_message_later(loading_message, MUSIC_FEEDBACK_DELETE_SECONDS)
            )
    finally:
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
        await send_ephemeral_followup(interaction, guild_only_error())
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
    await send_ephemeral_followup(
        interaction,
        f"{selected_channel.mention} 채널을 음악 신청 전용 채널로 설정했어요. "
        "이제 그 채널에 곡명이나 YouTube URL만 보내면 재생되고, 컨트롤 패널은 항상 유지됩니다.",
    )


@setup_music_channel.error
async def setup_music_channel_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
) -> None:
    async def send_error(content: str) -> None:
        if interaction.response.is_done():
            await send_ephemeral_followup(interaction, content)
        else:
            await send_ephemeral_response(interaction, content)

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
        await send_ephemeral_followup(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if await ensure_voice(interaction, state):
        state.announcement_channel = interaction.channel
        await send_ephemeral_followup(interaction, "음성 채널에 들어왔어요.")


@bot.tree.command(name="pause", description="Pause the current track.")
@app_commands.guild_only()
async def pause(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_playing():
        state.voice.pause()
        await send_ephemeral_response(interaction, "일시정지했어요.")
        return

    await send_ephemeral_response(interaction, "지금 재생 중인 곡이 없어요.")


@bot.tree.command(name="resume", description="Resume the paused track.")
@app_commands.guild_only()
async def resume(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and state.voice.is_paused():
        state.voice.resume()
        await send_ephemeral_response(interaction, "다시 재생할게요.")
        return

    await send_ephemeral_response(interaction, "일시정지된 곡이 없어요.")


@bot.tree.command(name="skip", description="Skip the current track.")
@app_commands.guild_only()
async def skip(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    if state.voice and (state.voice.is_playing() or state.voice.is_paused()):
        state.skip_requested = True
        state.voice.stop()
        await interaction.response.send_message("다음 곡으로 넘어갈게요.")
        return

    await send_ephemeral_response(interaction, "스킵할 곡이 없어요.")


@bot.tree.command(name="stop", description="Stop playback and clear the queue.")
@app_commands.guild_only()
async def stop(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    stop_playback(state, interaction.guild_id)

    await show_idle_panel(interaction.guild_id, state)
    await interaction.response.send_message("재생을 멈추고 대기열을 비웠어요.")


@bot.tree.command(name="queue", description="Show the current music queue.")
@app_commands.guild_only()
async def show_queue(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    await send_queue_management_response(
        interaction,
        interaction.guild_id,
        embed=make_queue_embed(state),
        view=QueueManageView(interaction.guild_id) if state.queue else None,
    )


@bot.tree.command(name="remove", description="Remove a track from the queue by position.")
@app_commands.describe(position="Queue position to remove, starting from 1")
@app_commands.guild_only()
async def remove_from_queue(interaction: discord.Interaction, position: int) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    removed = remove_queued_track(state, position - 1)
    if removed is None:
        await send_ephemeral_response(
            interaction,
            "그 번호의 대기열 곡을 찾지 못했어요.",
        )
        return

    schedule_autoplay_refill(interaction.guild_id)
    if state.current:
        await update_control_panel(interaction.guild_id, state)

    await send_ephemeral_response(
        interaction,
        f"대기열에서 `{removed.title}`을 삭제했어요.",
        delete_after=QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
    )


@bot.tree.command(name="nowplaying", description="Show the current track.")
@app_commands.guild_only()
async def now_playing(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if state.current:
        await interaction.response.send_message(
            embed=make_player_embed(state.current, state),
            view=MusicControlView(interaction.guild_id),
        )
        return

    await send_ephemeral_response(interaction, "지금 재생 중인 곡이 없어요.")


@bot.tree.command(name="leave", description="Disconnect from voice and clear the queue.")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return
    cancel_empty_channel_disconnect(state)
    stop_playback(state, interaction.guild_id)

    if state.voice and state.voice.is_connected():
        await show_idle_panel(interaction.guild_id, state)
        await state.voice.disconnect()
        state.voice = None
        await interaction.response.send_message("음성 채널에서 나왔어요.")
        return

    await send_ephemeral_response(interaction, "이미 음성 채널에 없어요.")


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Put it in .env or your environment.")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
