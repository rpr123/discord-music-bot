from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import functools
import json
import logging
import math
import os
import random
import re
import signal
import shutil
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict, deque
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable, Coroutine, TypeVar

import discord
import requests
from discord import app_commands
from discord.ext import commands
from music_autoplay_policy import (
    AUTOPLAY_QUEUE_TARGET,
    AUTOPLAY_RETRY_DELAYS_SECONDS,
    autoplay_can_refill,
    get_autoplay_excluded_keys,
    get_autoplay_retry_delay,
    get_autoplay_seed,
    remember_autoplay_track,
    remember_recent_value,
    select_autoplay_candidate,
)
from music_japanese_reading import (
    EXPLICIT_READING_BRACKETS,
    HANGUL_RE,
    JAPANESE_HAN_RE,
    JAPANESE_KANA_RE,
    JAPANESE_READING_RE,
    annotate_japanese_reading,
    find_explicit_reading_base_start,
    find_explicit_reading_replacements,
    get_reading_surface_segment_kind,
    katakana_to_hiragana,
    lyrics_are_japanese,
    lyrics_are_primarily_korean,
    normalize_japanese_reading,
    protect_explicit_readings,
    replace_explicit_readings,
    split_reading_surface,
)
from music_lyrics_display import (
    LYRICS_INLINE_LIMIT,
    make_lyrics_embed,
    make_lyrics_file,
    make_lyrics_variant_embed,
)
from music_models import AUTOPLAY_HISTORY_SIZE, GuildMusicState, Track
from music_player_embeds import (
    CONTROL_PANEL_TITLES,
    IDLE_PANEL_TITLE,
    PLAYING_PANEL_TITLE,
    describe_queue_selection,
    make_idle_player_embed,
    make_player_embed,
    make_queue_embed,
    make_track_embed,
)
from music_playback_state import (
    MAX_PLAYBACK_ATTEMPTS,
    invalidate_track_stream,
    requeue_track_after_playback_error,
    reset_track_playback_attempts,
    reset_track_playback_state,
)
from music_text import (
    DISCORD_EMBED_FIELD_LIMIT,
    format_duration,
    make_queue_line,
    make_track_link,
    requester_label,
    single_line,
    truncate_option_text,
    truncate_text,
)
from music_lyrics_matching import (
    LRC_METADATA_RE,
    LRC_TIMESTAMP_RE,
    LYRICS_DURATION_MATCH_TOLERANCE_SECONDS,
    LYRICS_NATIVE_SCRIPT_MIN_RATIO,
    LYRICS_NATIVE_SCRIPT_SCORE_WINDOW,
    QUOTED_TRACK_TITLE_RE,
    extract_original_lyrics,
    get_lyrics_search_terms,
    get_lyrics_title_aliases,
    lyrics_native_script_ratio,
    lyrics_record_score,
    normalize_lyrics_match_text,
    select_lyrics_record,
)
from music_namuwiki_matching import (
    build_namuwiki_document_candidates,
    extract_namuwiki_primary_artist_from_tables,
    find_namuwiki_override,
    get_namuwiki_track_artists,
    namuwiki_artist_matches_track,
    parse_namuwiki_candidate,
)
from music_queue import (
    remove_queued_track,
    remove_queued_track_by_id,
    remove_queued_track_range_by_ids,
)
from music_namuwiki_parsing import (
    NAMUMARK_FOOTNOTE_RE,
    NAMUMARK_LINK_RE,
    NAMUMARK_RUBY_RE,
    NAMUMARK_STYLE_PREFIX_RE,
    NAMUWIKI_IGNORED_HTML_TAGS,
    NAMUWIKI_VOID_HTML_TAGS,
    NamuWikiLyricsError,
    NamuWikiHTMLTableParser,
    NamuWikiPageBlockedError,
    _NamuWikiHTMLTableContext,
    best_namuwiki_header_column,
    clean_namumark_cell,
    extract_interleaved_namuwiki_groups,
    extract_interleaved_namuwiki_lyrics,
    extract_namuwiki_annotated_reading,
    extract_namuwiki_lyrics_from_html,
    extract_namuwiki_lyrics_from_namumark,
    extract_namuwiki_original_lyrics,
    extract_namuwiki_lyrics_from_tables,
    get_hiragana_reading_source_lyrics,
    is_usable_namuwiki_lyrics,
    is_valid_korean_translation,
    namuwiki_reading_header_score,
    namuwiki_source_header_score,
    namuwiki_translation_header_score,
    normalize_namuwiki_table_text,
    parse_namumark_tables,
    parse_namuwiki_html_tables,
    split_namuwiki_lyrics_groups,
)
from music_namuwiki_transport import (
    NAMUWIKI_BLOCKED_MARKERS,
    read_limited_http_response as read_namuwiki_http_response,
    request_namuwiki_api_source as fetch_namuwiki_api_source,
    request_namuwiki_html_once as fetch_namuwiki_html_once,
)
from music_request_parsing import (
    YOUTUBE_HOSTS,
    YOUTUBE_PLAYLIST_SEARCH_FILTER,
    build_youtube_playlist_search_url,
    clamp_auto_count as clamp_auto_count_with_limit,
    get_playlist_result_url,
    is_bulk_youtube_url,
    is_playlist_search_url,
    is_youtube_search_query,
    parse_auto_request as parse_auto_request_with_policy,
    parse_music_request,
)
from music_search_scoring import (
    ALTERNATE_VERSION_SEARCH_RE,
    ARTIST_CHANNEL_SUFFIX_RE,
    BRACKETED_TITLE_PART_RE,
    FULL_VERSION_SEARCH_RE,
    GAME_VIDEO_SEARCH_RE,
    LEADING_BRACKETED_TITLE_PART_RE,
    LONG_FORM_SEARCH_RE,
    NON_SONG_LABEL_RE,
    NON_SONG_SUFFIX_RE,
    OFFICIAL_AUDIO_SEARCH_RE,
    OFFICIAL_CHANNEL_RE,
    OFFICIAL_MEDIA_SEARCH_RE,
    OFFICIAL_VIDEO_SEARCH_RE,
    SHORT_VERSION_SEARCH_RE,
    TRAILING_BRACKETED_TITLE_PART_RE,
    VERSION_MARKER_RE,
    YOUTUBE_SEARCH_NOISE_TOKENS,
    clean_track_title,
    clean_track_title_preserving_case,
    get_search_result_duration,
    get_youtube_music_artist_hint,
    get_youtube_music_artist_names,
    get_youtube_search_tokens,
    infer_youtube_search_song_title,
    is_likely_official_youtube_upload,
    normalize_artist_name,
    normalize_identity_component,
    score_youtube_search_result,
    should_use_youtube_music_search,
    strip_edge_title_tags,
    youtube_music_entries_are_ambiguous,
    youtube_music_result_to_entry,
)
from music_subtitles import (
    VTT_TAG_RE,
    VTT_TIMESTAMP_LINE_RE,
    YouTubeSubtitleError,
    extract_json3_lyrics,
    extract_vtt_lyrics,
    get_manual_subtitle_candidates,
    get_subtitle_candidates,
    normalize_subtitle_text,
    select_korean_manual_subtitle,
    select_manual_subtitle,
)
from music_track_identity import (
    get_track_identity_keys,
    get_track_video_id,
    get_video_id,
    normalize_track_key,
)
from music_track_factory import (
    get_audio_codec,
    get_entry_url,
    get_manual_subtitles,
    get_resolved_stream_url,
    get_thumbnail_url,
    make_track_from_info,
)
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials

try:
    from sudachipy import dictionary as sudachi_dictionary
except ImportError:
    sudachi_dictionary = None


PROJECT_DIR = Path(__file__).resolve().parent
YTDL_WORKER_PATH = PROJECT_DIR / "ytdl_worker.py"
T = TypeVar("T")


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
AUTOPLAY_REFILL_CANDIDATES = min(
    parse_positive_int_env("AUTOPLAY_REFILL_CANDIDATES", 5),
    MAX_AUTO_TRACKS,
)
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
NAMUWIKI_PREVIEW_FALLBACK_ENABLED = os.getenv(
    "NAMUWIKI_PREVIEW_FALLBACK_ENABLED", "true"
).lower() not in {
    "0",
    "false",
    "no",
    "off",
}
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
YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS = parse_nonnegative_float_env(
    "YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS",
    YTDL_MIN_INTERVAL_SECONDS,
)
YTDL_CACHE_TTL_SECONDS = parse_positive_int_env("YTDL_CACHE_TTL_SECONDS", 180)
YTDL_CACHE_MAX_ENTRIES = parse_positive_int_env("YTDL_CACHE_MAX_ENTRIES", 16)
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
EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS = 3
VOICE_RECONNECT_GRACE_SECONDS = 5.0
VOICE_DISCONNECT_TIMEOUT_SECONDS = 10.0
AUTOPLAY_START_DELAY_SECONDS = parse_nonnegative_float_env(
    "AUTOPLAY_START_DELAY_SECONDS", 10.0
)
LYRICS_START_DELAY_SECONDS = parse_nonnegative_float_env(
    "LYRICS_START_DELAY_SECONDS", 3.0
)
AUTOPLAY_BUTTON_CUSTOM_ID = "music:autoplay"
CONTROL_PANEL_HISTORY_LIMIT = 100
YTDL_BASE_OPTIONS = {
    "format": "bestaudio[acodec=opus]/bestaudio/best",
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

ytdl_rate_lock = asyncio.Lock()
ytdl_cache_lock = asyncio.Lock()
ytdl_cache: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
ytdl_last_request_started_at = 0.0
youtube_circuit_open_until = 0.0
youtube_circuit_reason: str | None = None
youtube_music_client: YTMusic | None = None
youtube_music_client_lock = threading.Lock()
auxiliary_network_semaphore = asyncio.Semaphore(1)
auxiliary_operation_tasks: set[asyncio.Task] = set()
auxiliary_worker_tasks: set[asyncio.Task] = set()
auxiliary_workers_closing = False
youtube_music_rate_lock = asyncio.Lock()
youtube_music_last_request_started_at = 0.0
youtube_music_cache_lock = asyncio.Lock()
youtube_music_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
youtube_subtitle_rate_lock = asyncio.Lock()
youtube_subtitle_last_request_started_at = 0.0
lyrics_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="music-lyrics",
)
lyrics_executor_closing = False
lyrics_executor_shutdown_task: asyncio.Task[None] | None = None
bot_shutdown_started = False
voice_operation_tasks: set[asyncio.Task] = set()
housekeeping_tasks: set[asyncio.Task] = set()
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


def ensure_auxiliary_workers_open() -> None:
    if auxiliary_workers_closing:
        raise RuntimeError("Auxiliary network workers are shutting down.")


def track_auxiliary_worker(task: asyncio.Task) -> asyncio.Task:
    ensure_auxiliary_workers_open()
    auxiliary_worker_tasks.add(task)
    task.add_done_callback(auxiliary_worker_tasks.discard)
    return task


def track_auxiliary_operation() -> asyncio.Task:
    ensure_auxiliary_workers_open()
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Auxiliary operation requires an asyncio task.")
    auxiliary_operation_tasks.add(task)
    return task


def begin_auxiliary_worker_shutdown() -> None:
    global auxiliary_workers_closing
    auxiliary_workers_closing = True


async def shutdown_auxiliary_operations() -> None:
    begin_auxiliary_worker_shutdown()
    cancellation_received = False
    current_task = asyncio.current_task()
    if current_task is not None:
        auxiliary_operation_tasks.discard(current_task)

    while auxiliary_operation_tasks:
        tasks = list(auxiliary_operation_tasks)
        for task in tasks:
            if task.done():
                auxiliary_operation_tasks.discard(task)
                continue
            if task.cancelling() == 0:
                task.cancel()
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            auxiliary_operation_tasks.discard(task)

    if cancellation_received:
        raise asyncio.CancelledError


async def shutdown_auxiliary_workers() -> None:
    begin_auxiliary_worker_shutdown()
    cancellation_received = False
    while auxiliary_worker_tasks:
        tasks = list(auxiliary_worker_tasks)
        for task in tasks:
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            auxiliary_worker_tasks.discard(task)
    if cancellation_received:
        raise asyncio.CancelledError


def begin_lyrics_executor_shutdown() -> None:
    global lyrics_executor_closing
    lyrics_executor_closing = True


def begin_bot_shutdown() -> None:
    global bot_shutdown_started
    bot_shutdown_started = True
    begin_auxiliary_worker_shutdown()
    begin_lyrics_executor_shutdown()


async def shutdown_lyrics_executor() -> None:
    global lyrics_executor_shutdown_task
    begin_lyrics_executor_shutdown()
    if lyrics_executor_shutdown_task is None:
        lyrics_executor_shutdown_task = asyncio.create_task(
            asyncio.to_thread(
                lyrics_executor.shutdown,
                wait=True,
                cancel_futures=True,
            )
        )
    cancellation_received, shutdown_error = (
        await wait_for_task_completion_despite_cancellation(
            lyrics_executor_shutdown_task
        )
    )
    if shutdown_error is not None:
        raise shutdown_error
    if cancellation_received:
        raise asyncio.CancelledError


async def wait_for_ytdl_interval(
    minimum_interval_seconds: float | None = None,
    *,
    on_interval_reserved: Callable[[], None] | None = None,
) -> None:
    global ytdl_last_request_started_at
    interval_seconds = (
        YTDL_MIN_INTERVAL_SECONDS
        if minimum_interval_seconds is None
        else max(0.0, minimum_interval_seconds)
    )
    async with ytdl_rate_lock:
        elapsed = time.monotonic() - ytdl_last_request_started_at
        delay = max(0.0, interval_seconds - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
        if on_interval_reserved is not None:
            on_interval_reserved()
        ytdl_last_request_started_at = time.monotonic()


async def wait_for_youtube_music_interval() -> None:
    global youtube_music_last_request_started_at
    async with youtube_music_rate_lock:
        elapsed = time.monotonic() - youtube_music_last_request_started_at
        delay = max(0.0, YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
        youtube_music_last_request_started_at = time.monotonic()


async def wait_for_youtube_subtitle_interval() -> None:
    global youtube_subtitle_last_request_started_at
    async with youtube_subtitle_rate_lock:
        elapsed = time.monotonic() - youtube_subtitle_last_request_started_at
        delay = max(0.0, YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS - elapsed)
        if delay > 0:
            await asyncio.sleep(delay)
        youtube_subtitle_last_request_started_at = time.monotonic()


async def stop_ytdl_worker(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        return
    except OSError:
        try:
            process.kill()
        except ProcessLookupError:
            return
    await process.wait()


async def wait_for_task_completion_despite_cancellation(
    task: asyncio.Task,
) -> tuple[bool, BaseException | None]:
    cancellation_received = False
    current_task = asyncio.current_task()
    observed_cancellations = (
        current_task.cancelling() if current_task is not None else 0
    )
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            current_cancellations = (
                current_task.cancelling() if current_task is not None else 0
            )
            if current_cancellations > observed_cancellations or not task.done():
                cancellation_received = True
            observed_cancellations = current_cancellations
        except BaseException:
            break

    if task.cancelled():
        return cancellation_received, asyncio.CancelledError()
    return cancellation_received, task.exception()


def finish_housekeeping_task(task: asyncio.Task) -> None:
    housekeeping_tasks.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning(
            "Housekeeping task failed: %s",
            error,
            exc_info=(type(error), error, error.__traceback__),
        )


def create_housekeeping_task(
    coroutine: Coroutine[object, object, T],
) -> asyncio.Task[T] | None:
    if bot_shutdown_started:
        coroutine.close()
        return None
    task = asyncio.create_task(coroutine)
    housekeeping_tasks.add(task)
    task.add_done_callback(finish_housekeeping_task)
    return task


async def shutdown_housekeeping_tasks() -> None:
    cancellation_received = False
    current_task = asyncio.current_task()
    if current_task is not None:
        housekeeping_tasks.discard(current_task)

    while housekeeping_tasks:
        tasks = list(housekeeping_tasks)
        for task in tasks:
            if not task.done() and task.cancelling() == 0:
                task.cancel()
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            housekeeping_tasks.discard(task)

    if cancellation_received:
        raise asyncio.CancelledError


async def cleanup_ytdl_process(
    process: asyncio.subprocess.Process,
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> None:
    try:
        await stop_ytdl_worker(process)
    finally:
        if not communication.done():
            communication.cancel()
        await asyncio.gather(communication, return_exceptions=True)


async def finish_ytdl_process_cleanup(
    process: asyncio.subprocess.Process,
    communication: asyncio.Task[tuple[bytes, bytes]],
) -> bool:
    cleanup_task = asyncio.create_task(
        cleanup_ytdl_process(process, communication)
    )
    cancellation_received, cleanup_error = (
        await wait_for_task_completion_despite_cancellation(cleanup_task)
    )
    if cleanup_error is not None and not isinstance(
        cleanup_error,
        asyncio.CancelledError,
    ):
        logger.warning(
            "Failed to finish yt-dlp subprocess cleanup: %s",
            cleanup_error,
        )
    return cancellation_received


class YtdlJobKind(IntEnum):
    PLAYBACK_STREAM = 0
    USER_REQUEST = 10
    PLAYLIST_ALBUM = 20
    AUTOPLAY = 30
    LYRICS_FALLBACK = 40

    @property
    def log_name(self) -> str:
        return self.name.casefold()


@dataclass
class YtdlQueueJob:
    sequence: int
    options: dict
    query: str
    label: str
    job_kind: YtdlJobKind
    minimum_interval_seconds: float | None
    enqueued_at: float
    deadline: float
    future: asyncio.Future[dict]
    execution_task: asyncio.Task[dict] | None = None
    rate_slot_reserved: bool = False
    worker_started: bool = False
    defer_requested: bool = False


async def run_ytdl_worker(
    options: dict,
    query: str,
    timeout_seconds: float,
    *,
    label: str = "yt-dlp",
    job_kind: str = "general",
    priority: str = "normal",
    queue_wait_seconds: float = 0.0,
) -> dict:
    if not YTDL_WORKER_PATH.is_file():
        raise RuntimeError(f"yt-dlp worker was not found: {YTDL_WORKER_PATH}")

    started_at = time.monotonic()
    status = "failure"
    response_bytes = 0
    try:
        process_options: dict[str, object] = {}
        if os.name == "posix":
            process_options["start_new_session"] = True

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(YTDL_WORKER_PATH),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **process_options,
        )
        request = json.dumps(
            {"options": options, "query": query},
            ensure_ascii=False,
        ).encode("utf-8")
        communication = asyncio.create_task(process.communicate(request))
        try:
            stdout, stderr = await asyncio.wait_for(
                communication,
                timeout=max(0.1, timeout_seconds),
            )
        except asyncio.TimeoutError:
            status = "timeout"
            cancelled_during_cleanup = await finish_ytdl_process_cleanup(
                process,
                communication,
            )
            if cancelled_during_cleanup:
                raise asyncio.CancelledError
            raise
        except asyncio.CancelledError:
            status = "cancelled"
            await finish_ytdl_process_cleanup(process, communication)
            raise

        response_bytes = len(stdout)
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            detail = stderr_text or "yt-dlp worker returned an invalid response."
            raise RuntimeError(detail) from error

        if not isinstance(response, dict):
            raise RuntimeError("yt-dlp worker returned an invalid response.")
        error_message = response.get("error")
        if process.returncode != 0 or error_message:
            raise RuntimeError(
                str(error_message or stderr_text or "yt-dlp worker failed.")
            )

        info = response.get("info")
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp worker returned invalid track information.")
        status = "success"
        return info
    finally:
        elapsed = time.monotonic() - started_at
        log = logger.warning if status in {"failure", "timeout"} else logger.info
        log(
            "yt-dlp job: label=%s kind=%s priority=%s status=%s "
            "queue_wait=%.3fs worker=%.3fs response_bytes=%s",
            label,
            job_kind,
            priority,
            status,
            queue_wait_seconds,
            elapsed,
            response_bytes,
        )


class YtdlPriorityScheduler:
    def __init__(self, max_concurrency: int = 1) -> None:
        self.max_concurrency = max(1, max_concurrency)
        self.queue: asyncio.PriorityQueue[tuple[int, int, YtdlQueueJob]] = (
            asyncio.PriorityQueue()
        )
        self.sequence = 0
        self.worker_tasks: set[asyncio.Task[None]] = set()
        self.active_jobs: dict[int, YtdlQueueJob] = {}
        self.closed = False

    def _ensure_workers(self) -> None:
        completed_tasks = {
            task for task in self.worker_tasks if task.done()
        }
        self.worker_tasks.difference_update(completed_tasks)
        available_slots = self.max_concurrency - len(self.worker_tasks)
        worker_count = min(available_slots, self.queue.qsize())
        for _ in range(worker_count):
            task = asyncio.create_task(self._worker_loop())
            self.worker_tasks.add(task)
            task.add_done_callback(self._worker_done)

    def _worker_done(self, task: asyncio.Task[None]) -> None:
        self.worker_tasks.discard(task)
        if not self.closed and not self.queue.empty():
            self._ensure_workers()

    @staticmethod
    def _request_execution_cancel(task: asyncio.Task[dict] | None) -> None:
        if task is not None and not task.done() and task.cancelling() == 0:
            task.cancel()

    @classmethod
    async def _cancel_execution_once(
        cls,
        task: asyncio.Task[dict] | None,
    ) -> bool:
        if task is None or task.done():
            return False
        cls._request_execution_cancel(task)
        cancellation_received, _ = (
            await wait_for_task_completion_despite_cancellation(task)
        )
        return cancellation_received

    async def submit(
        self,
        options: dict,
        query: str,
        label: str,
        *,
        job_kind: YtdlJobKind,
        timeout_seconds: float,
        minimum_interval_seconds: float | None,
    ) -> dict:
        if self.closed:
            raise RuntimeError("yt-dlp scheduler is closed.")

        loop = asyncio.get_running_loop()
        now = loop.time()
        future: asyncio.Future[dict] = loop.create_future()
        job = YtdlQueueJob(
            sequence=self.sequence,
            options=options,
            query=query,
            label=label,
            job_kind=job_kind,
            minimum_interval_seconds=minimum_interval_seconds,
            enqueued_at=now,
            deadline=now + max(0.1, timeout_seconds),
            future=future,
        )
        self.sequence += 1
        self.queue.put_nowait((int(job_kind), job.sequence, job))
        self._defer_waiting_lower_priority_jobs(job_kind)
        self._ensure_workers()

        try:
            return await asyncio.wait_for(
                asyncio.shield(future),
                timeout=max(0.1, timeout_seconds),
            )
        except asyncio.TimeoutError:
            timed_out_while_pending = not future.done()
            if timed_out_while_pending:
                future.cancel()
            execution_task = job.execution_task
            cancelled_during_cleanup = False
            if not self.closed:
                cancelled_during_cleanup = await self._cancel_execution_once(
                    execution_task
                )
            if timed_out_while_pending and not job.worker_started:
                self._log_pre_worker_exit(
                    job,
                    "queue_timeout",
                    loop.time() - job.enqueued_at,
                )
            if cancelled_during_cleanup:
                raise asyncio.CancelledError
            raise
        except asyncio.CancelledError:
            future.cancel()
            execution_task = job.execution_task
            if not self.closed:
                await self._cancel_execution_once(execution_task)
            raise

    def _defer_waiting_lower_priority_jobs(
        self,
        incoming_kind: YtdlJobKind,
    ) -> None:
        for active_job in self.active_jobs.values():
            execution_task = active_job.execution_task
            if (
                active_job.job_kind > incoming_kind
                and not active_job.rate_slot_reserved
                and not active_job.worker_started
                and not active_job.defer_requested
                and execution_task is not None
                and not execution_task.done()
            ):
                # Rate-limit waits are interruptible; a subprocess already running is not.
                active_job.defer_requested = True
                self._request_execution_cancel(execution_task)

    async def _worker_loop(self) -> None:
        while not self.closed:
            try:
                _, _, job = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            try:
                await self._run_job(job)
            finally:
                self.queue.task_done()

    async def _run_job(self, job: YtdlQueueJob) -> None:
        if job.future.cancelled():
            logger.debug("Skipped cancelled yt-dlp job: %s", job.label)
            return

        loop = asyncio.get_running_loop()
        queue_wait_seconds = loop.time() - job.enqueued_at
        if loop.time() >= job.deadline:
            self._log_pre_worker_exit(job, "queue_timeout", queue_wait_seconds)
            job.future.set_exception(asyncio.TimeoutError())
            return

        execution_task = asyncio.create_task(
            self._execute_job(job, queue_wait_seconds)
        )
        job.execution_task = execution_task
        self.active_jobs[id(job)] = job
        try:
            info = await execution_task
        except asyncio.CancelledError:
            if (
                job.defer_requested
                and not self.closed
                and not job.future.done()
            ):
                job.defer_requested = False
                job.rate_slot_reserved = False
                self.queue.put_nowait((int(job.job_kind), job.sequence, job))
                return
            if not job.future.done():
                job.future.cancel()
            return
        except asyncio.TimeoutError as error:
            if not job.worker_started:
                self._log_pre_worker_exit(job, "timeout", queue_wait_seconds)
            if not job.future.done():
                job.future.set_exception(error)
        except Exception as error:
            trip_youtube_circuit(error)
            if not job.worker_started:
                self._log_pre_worker_exit(job, "failure", queue_wait_seconds)
            if not job.future.done():
                job.future.set_exception(error)
        else:
            if not job.future.done():
                job.future.set_result(info)
        finally:
            self.active_jobs.pop(id(job), None)
            job.execution_task = None

    async def _execute_job(
        self,
        job: YtdlQueueJob,
        queue_wait_seconds: float,
    ) -> dict:
        ensure_youtube_circuit_closed()
        loop = asyncio.get_running_loop()
        remaining_timeout = job.deadline - loop.time()
        if remaining_timeout <= 0:
            raise asyncio.TimeoutError

        await asyncio.wait_for(
            wait_for_ytdl_interval(
                job.minimum_interval_seconds,
                on_interval_reserved=lambda: setattr(
                    job,
                    "rate_slot_reserved",
                    True,
                ),
            ),
            timeout=remaining_timeout,
        )
        ensure_youtube_circuit_closed()
        remaining_timeout = job.deadline - loop.time()
        if remaining_timeout <= 0:
            raise asyncio.TimeoutError

        job.worker_started = True
        return await run_ytdl_worker(
            job.options,
            job.query,
            remaining_timeout,
            label=job.label,
            job_kind=job.job_kind.log_name,
            priority=str(int(job.job_kind)),
            queue_wait_seconds=queue_wait_seconds,
        )

    @staticmethod
    def _log_pre_worker_exit(
        job: YtdlQueueJob,
        status: str,
        queue_wait_seconds: float,
    ) -> None:
        logger.warning(
            "yt-dlp job: label=%s kind=%s priority=%s status=%s "
            "queue_wait=%.3fs worker=0.000s response_bytes=0",
            job.label,
            job.job_kind.log_name,
            int(job.job_kind),
            status,
            queue_wait_seconds,
        )

    async def shutdown(self) -> None:
        if self.closed and not self.worker_tasks:
            return
        self.closed = True

        while True:
            try:
                _, _, job = self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not job.future.done():
                job.future.cancel()
            self.queue.task_done()

        execution_tasks: list[asyncio.Task[dict]] = []
        for job in list(self.active_jobs.values()):
            if not job.future.done():
                job.future.cancel()
            if job.execution_task and not job.execution_task.done():
                self._request_execution_cancel(job.execution_task)
                execution_tasks.append(job.execution_task)

        workers = list(self.worker_tasks)
        cancellation_received = False
        for task in [*execution_tasks, *workers]:
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
        self.active_jobs.clear()
        self.worker_tasks.clear()
        if cancellation_received:
            raise asyncio.CancelledError


ytdl_scheduler = YtdlPriorityScheduler(YTDL_MAX_CONCURRENT_EXTRACTIONS)


async def extract_ytdl_info(
    options: dict,
    query: str,
    label: str,
    *,
    job_kind: YtdlJobKind,
    use_cache: bool = True,
    minimum_interval_seconds: float | None = None,
) -> dict:
    if bot_shutdown_started:
        raise asyncio.CancelledError

    cache_key = get_ytdl_cache_key(options, query)
    if use_cache:
        cached = await get_cached_ytdl_info(cache_key)
        if cached is not None:
            logger.info("yt-dlp cache hit: %s", label)
            return cached

    ensure_youtube_circuit_closed()
    logger.debug("yt-dlp query for %s: %s", label, query)

    loop = asyncio.get_running_loop()
    started_at = loop.time()
    try:
        info = await ytdl_scheduler.submit(
            options,
            query,
            label,
            job_kind=job_kind,
            timeout_seconds=YTDL_EXTRACT_TIMEOUT_SECONDS,
            minimum_interval_seconds=minimum_interval_seconds,
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
    logger.debug("yt-dlp completed in %.3fs: %s", loop.time() - started_at, label)
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


async def _search_youtube_music_operation(query: str) -> list[dict]:
    if bot_shutdown_started:
        raise asyncio.CancelledError
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
            auxiliary_network_semaphore.acquire(),
            timeout=YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("YouTube Music search queue timed out: %s", query)
        raise

    try:
        ensure_youtube_circuit_closed()
        await wait_for_youtube_music_interval()
        ensure_youtube_circuit_closed()
        ensure_auxiliary_workers_open()
    except BaseException:
        auxiliary_network_semaphore.release()
        raise

    worker = track_auxiliary_worker(
        asyncio.create_task(asyncio.to_thread(search))
    )

    def search_finished(task: asyncio.Task[list[dict]]) -> None:
        auxiliary_network_semaphore.release()
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


async def search_youtube_music(query: str) -> list[dict]:
    if bot_shutdown_started:
        raise asyncio.CancelledError
    operation_task = track_auxiliary_operation()
    try:
        return await _search_youtube_music_operation(query)
    finally:
        auxiliary_operation_tasks.discard(operation_task)


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


async def delete_message_later(
    message: discord.Message,
    delay_seconds: float,
) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error("deleting temporary music feedback", error)


async def delete_interaction_response_later(
    interaction: discord.Interaction,
    delay_seconds: float,
) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass
    except discord.HTTPException as error:
        log_discord_http_error(
            "deleting a temporary interaction response",
            error,
        )


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


intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True


def track_voice_operation() -> asyncio.Task:
    if bot_shutdown_started:
        raise asyncio.CancelledError
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("Voice operation requires an asyncio task.")
    voice_operation_tasks.add(task)
    return task


async def shutdown_voice_operations() -> None:
    cancellation_received = False
    current_task = asyncio.current_task()
    if current_task is not None:
        voice_operation_tasks.discard(current_task)

    while voice_operation_tasks:
        tasks = list(voice_operation_tasks)
        for task in tasks:
            if task.done():
                voice_operation_tasks.discard(task)
                continue
            if task.cancelling() == 0:
                task.cancel()
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            voice_operation_tasks.discard(task)

    if cancellation_received:
        raise asyncio.CancelledError


async def cancel_music_background_tasks_for_shutdown() -> None:
    cancellation_received = False
    for state in list(music_states.values()):
        state.playback_generation += 1
        state.stop_requested = True
        clear_pending_playback_advance(state)
        voice = state.voice
        if voice and (voice.is_playing() or voice.is_paused()):
            try:
                voice.stop()
            except Exception:
                logger.warning(
                    "Failed to stop voice playback during shutdown",
                    exc_info=True,
                )

    while True:
        tracked_tasks: list[tuple[GuildMusicState, str, asyncio.Task]] = []
        queue_tasks: list[tuple[GuildMusicState, int, asyncio.Task]] = []
        seen_tasks: set[asyncio.Task] = set()
        for state in list(music_states.values()):
            for attribute in (
                "advance_task",
                "noncritical_task",
                "autoplay_task",
                "lyrics_task",
                "empty_channel_task",
            ):
                task = getattr(state, attribute)
                if task is None:
                    continue
                if task.done():
                    if getattr(state, attribute) is task:
                        setattr(state, attribute, None)
                    continue
                if task in seen_tasks:
                    continue
                seen_tasks.add(task)
                tracked_tasks.append((state, attribute, task))
                if task.cancelling() == 0:
                    task.cancel()

            for message_id, task in list(state.queue_cleanup_tasks.items()):
                if task.done():
                    if state.queue_cleanup_tasks.get(message_id) is task:
                        state.queue_cleanup_tasks.pop(message_id, None)
                    continue
                if task in seen_tasks:
                    continue
                seen_tasks.add(task)
                queue_tasks.append((state, message_id, task))
                if task.cancelling() == 0:
                    task.cancel()

        if not tracked_tasks and not queue_tasks:
            break

        for state, attribute, task in tracked_tasks:
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            if getattr(state, attribute) is task:
                setattr(state, attribute, None)

        for state, message_id, task in queue_tasks:
            task_cancelled, _ = (
                await wait_for_task_completion_despite_cancellation(task)
            )
            cancellation_received = cancellation_received or task_cancelled
            if state.queue_cleanup_tasks.get(message_id) is task:
                state.queue_cleanup_tasks.pop(message_id, None)

    if cancellation_received:
        raise asyncio.CancelledError


class MusicBot(commands.Bot):
    _discord_close_task: asyncio.Task[None] | None = None

    async def _shutdown_discord_client(self) -> None:
        if self._discord_close_task is None:
            self._discord_close_task = asyncio.create_task(super().close())
        cancellation_received, close_error = (
            await wait_for_task_completion_despite_cancellation(
                self._discord_close_task
            )
        )
        if close_error is not None:
            raise close_error
        if cancellation_received:
            raise asyncio.CancelledError

    async def close(self) -> None:
        begin_bot_shutdown()
        try:
            try:
                try:
                    try:
                        await cancel_music_background_tasks_for_shutdown()
                    finally:
                        await shutdown_voice_operations()
                finally:
                    await shutdown_auxiliary_operations()
            finally:
                await ytdl_scheduler.shutdown()
        finally:
            try:
                await shutdown_auxiliary_workers()
            finally:
                try:
                    await shutdown_lyrics_executor()
                finally:
                    try:
                        await shutdown_housekeeping_tasks()
                    finally:
                        await self._shutdown_discord_client()


bot = MusicBot(command_prefix="!", intents=intents)
music_states: dict[int, GuildMusicState] = {}
configured_music_channels: dict[int, int] = {}
configured_control_messages: dict[int, int] = {}
configured_autoplay_enabled: dict[int, bool] = {}
startup_initialization_lock = asyncio.Lock()
startup_initialized = False
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
    delete_after: float | None = EPHEMERAL_RESPONSE_DELETE_SECONDS,
) -> None:
    options: dict[str, object] = {"ephemeral": True}
    if embed is not None:
        options["embed"] = embed
    if view is not None:
        options["view"] = view
    await interaction.response.send_message(content, **options)
    if delete_after is not None:
        create_housekeeping_task(
            delete_interaction_response_later(interaction, delete_after)
        )


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
        create_housekeeping_task(delete_message_later(message, delete_after))
    return message


async def delete_private_interaction_message(
    message: discord.WebhookMessage | discord.InteractionMessage,
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
    message: discord.WebhookMessage | discord.InteractionMessage,
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
        if not bot_shutdown_started:
            create_housekeeping_task(delete_private_interaction_message(message))


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
    if bot_shutdown_started or message is None:
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


def build_youtube_search_query(
    query: str,
    artist_hint: str | None = None,
) -> str:
    search_text = query
    if artist_hint:
        search_text = f"{query} {artist_hint}"
    return f"ytsearch{YOUTUBE_SEARCH_CANDIDATES}:{search_text}"


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
                    job_kind=YtdlJobKind.USER_REQUEST,
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
        info = await extract_ytdl_info(
            options,
            search_query,
            "YouTube search",
            job_kind=YtdlJobKind.USER_REQUEST,
        )
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


class LyricsLookupError(RuntimeError):
    pass


class KoreanLyricsError(RuntimeError):
    pass


class LyricsReadingError(RuntimeError):
    pass


SUDACHI_TOKENIZER = None
SUDACHI_TOKENIZER_LOCK = threading.Lock()
NAMUWIKI_REQUEST_LOCK = threading.Lock()
namuwiki_last_request_started_at = 0.0
namuwiki_prefer_preview_renderer = False
NAMUWIKI_MAX_DOCUMENT_CANDIDATES = 4
NAMUWIKI_MAX_RESPONSE_BYTES = 3_000_000
NAMUWIKI_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
NAMUWIKI_PREVIEW_USER_AGENT = "Discordbot/2.0"


def get_namuwiki_override(track: Track) -> str | None:
    return find_namuwiki_override(track, NAMUWIKI_DOCUMENT_OVERRIDES)


def get_namuwiki_document_candidates(track: Track) -> list[str]:
    return build_namuwiki_document_candidates(
        track,
        get_namuwiki_override(track),
        NAMUWIKI_MAX_DOCUMENT_CANDIDATES,
    )


def split_namuwiki_candidate(candidate: str) -> tuple[str, str]:
    return parse_namuwiki_candidate(candidate, NAMUWIKI_PAGE_BASE_URL)


def wait_for_namuwiki_interval() -> None:
    global namuwiki_last_request_started_at
    with NAMUWIKI_REQUEST_LOCK:
        elapsed = time.monotonic() - namuwiki_last_request_started_at
        delay = max(0.0, NAMUWIKI_REQUEST_INTERVAL_SECONDS - elapsed)
        if delay:
            time.sleep(delay)
        namuwiki_last_request_started_at = time.monotonic()


def read_limited_http_response(response) -> bytes:
    return read_namuwiki_http_response(
        response,
        NAMUWIKI_MAX_RESPONSE_BYTES,
    )


def request_namuwiki_api_source(document: str) -> str | None:
    return fetch_namuwiki_api_source(
        document,
        api_token=NAMUWIKI_API_TOKEN,
        api_base_url=NAMUWIKI_API_BASE_URL,
        timeout_seconds=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        wait_for_interval=wait_for_namuwiki_interval,
        read_response=read_limited_http_response,
        urlopen=urllib.request.urlopen,
    )


def request_namuwiki_html_once(
    page_url: str,
    user_agent: str,
) -> tuple[str, str] | None:
    return fetch_namuwiki_html_once(
        page_url,
        user_agent,
        timeout_seconds=NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
        wait_for_interval=wait_for_namuwiki_interval,
        read_response=read_limited_http_response,
        urlopen=urllib.request.urlopen,
        blocked_markers=NAMUWIKI_BLOCKED_MARKERS,
    )


def request_namuwiki_html(page_url: str) -> tuple[str, str] | None:
    global namuwiki_prefer_preview_renderer

    if (
        not NAMUWIKI_PREVIEW_FALLBACK_ENABLED
        or namuwiki_prefer_preview_renderer
    ):
        user_agent = (
            NAMUWIKI_PREVIEW_USER_AGENT
            if namuwiki_prefer_preview_renderer
            else NAMUWIKI_BROWSER_USER_AGENT
        )
        return request_namuwiki_html_once(page_url, user_agent)

    try:
        return request_namuwiki_html_once(
            page_url,
            NAMUWIKI_BROWSER_USER_AGENT,
        )
    except NamuWikiPageBlockedError as browser_error:
        logger.info(
            "NamuWiki browser page was blocked; retrying through the "
            "Discord link-preview renderer"
        )
        try:
            result = request_namuwiki_html_once(
                page_url,
                NAMUWIKI_PREVIEW_USER_AGENT,
            )
        except NamuWikiLyricsError as preview_error:
            raise NamuWikiLyricsError(
                f"{browser_error} Discord preview fallback failed: "
                f"{preview_error}"
            ) from preview_error

        namuwiki_prefer_preview_renderer = True
        logger.info(
            "NamuWiki Discord link-preview renderer is now preferred "
            "for this process"
        )
        return result


def lookup_namuwiki_lyrics(
    track: Track,
) -> tuple[str, str, str] | None:
    if not NAMUWIKI_LYRICS_ENABLED:
        return None

    candidates = get_namuwiki_document_candidates(track)
    override = get_namuwiki_override(track)
    transient_failures: list[str] = []
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
                        namumark_tables = parse_namumark_tables(namumark)
                        lyrics = extract_namuwiki_lyrics_from_tables(
                            namumark_tables
                        )
                        page_artist = extract_namuwiki_primary_artist_from_tables(
                            namumark_tables
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
                        if (
                            candidate != override
                            and not namuwiki_artist_matches_track(
                                track,
                                page_artist,
                            )
                        ):
                            logger.info(
                                "NamuWiki artist mismatch for %s (%s): "
                                "expected %s, page has %s",
                                track.title,
                                document,
                                ", ".join(get_namuwiki_track_artists(track)),
                                page_artist,
                            )
                            continue
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
            transient_failures.append(f"{document}: {error}")
            continue
        if html_result is None:
            continue

        page_source, final_url = html_result
        try:
            html_tables = parse_namuwiki_html_tables(page_source)
            lyrics = extract_namuwiki_lyrics_from_tables(html_tables)
            page_artist = extract_namuwiki_primary_artist_from_tables(
                html_tables
            )
        except NamuWikiLyricsError as error:
            logger.warning(
                "NamuWiki HTML parsing failed for %s (%s): %s",
                track.title,
                document,
                error,
            )
            transient_failures.append(f"{document}: {error}")
            continue
        if lyrics:
            if (
                candidate != override
                and not namuwiki_artist_matches_track(track, page_artist)
            ):
                logger.info(
                    "NamuWiki artist mismatch for %s (%s): expected %s, "
                    "page has %s",
                    track.title,
                    document,
                    ", ".join(get_namuwiki_track_artists(track)),
                    page_artist,
                )
                continue
            logger.info(
                "NamuWiki lyrics selected for %s (%s)",
                track.title,
                document,
            )
            return lyrics, "나무위키 · 원문·독음·번역", final_url

    if transient_failures:
        raise NamuWikiLyricsError(
            "NamuWiki candidate pages could not be verified. "
            "On hosted servers, configure NAMUWIKI_API_TOKEN. "
            f"Last failure: {transient_failures[-1]}"
        )

    if candidates:
        logger.info(
            "No NamuWiki lyrics found for %s (candidates: %s)",
            track.title,
            ", ".join(candidates),
        )
    return None


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


async def run_lyrics_job(function: Callable[..., T], *args: object) -> T:
    if lyrics_executor_closing:
        raise asyncio.CancelledError
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        lyrics_executor,
        functools.partial(function, *args),
    )


async def _get_selected_youtube_subtitle_operation(
    track: Track,
    selected: tuple[str, str, str] | None,
    *,
    purpose: str,
) -> str | None:
    if bot_shutdown_started:
        raise asyncio.CancelledError
    if selected is None:
        return None

    language, extension, url = selected

    ensure_youtube_circuit_closed()
    try:
        await asyncio.wait_for(
            auxiliary_network_semaphore.acquire(),
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as error:
        raise YouTubeSubtitleError("Timed out waiting to fetch YouTube subtitles.") from error

    try:
        ensure_youtube_circuit_closed()
        await wait_for_youtube_subtitle_interval()
        ensure_youtube_circuit_closed()
        ensure_auxiliary_workers_open()
    except BaseException:
        auxiliary_network_semaphore.release()
        raise

    worker = track_auxiliary_worker(
        asyncio.create_task(
            run_lyrics_job(request_youtube_subtitle, url, extension)
        )
    )

    def subtitle_finished(task: asyncio.Task[str | None]) -> None:
        auxiliary_network_semaphore.release()
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            trip_youtube_circuit(error)

    worker.add_done_callback(subtitle_finished)
    try:
        lyrics = await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=LYRICS_REQUEST_TIMEOUT_SECONDS + 2,
        )
    except Exception as error:
        trip_youtube_circuit(error)
        if isinstance(error, YouTubeCircuitOpenError):
            raise
        raise YouTubeSubtitleError(str(error)) from error

    if lyrics:
        logger.info(
            "YouTube subtitles selected for %s (%s, %s)",
            track.title,
            language,
            purpose,
        )
    return lyrics


async def get_selected_youtube_subtitle(
    track: Track,
    selected: tuple[str, str, str] | None,
    *,
    purpose: str,
) -> str | None:
    if bot_shutdown_started:
        raise asyncio.CancelledError
    if selected is None:
        return None
    operation_task = track_auxiliary_operation()
    try:
        return await _get_selected_youtube_subtitle_operation(
            track,
            selected,
            purpose=purpose,
        )
    finally:
        auxiliary_operation_tasks.discard(operation_task)


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
            run_lyrics_job(lookup_track_lyrics, track),
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


def can_show_korean_lyrics(track: Track, lyrics: str) -> bool:
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


def can_generate_lyrics_reading(track: Track, lyrics: str) -> bool:
    if not LYRICS_READING_ENABLED:
        return False
    if (
        track.korean_lyrics
        and track.korean_lyrics_url
        and extract_namuwiki_annotated_reading(track.korean_lyrics)
    ):
        return True
    return bool(
        sudachi_dictionary is not None
        and get_hiragana_reading_source_lyrics(track, lyrics)
    )


def get_sudachi_tokenizer():
    global SUDACHI_TOKENIZER
    if sudachi_dictionary is None:
        raise LyricsReadingError(
            "SudachiPy and SudachiDict-core are not installed."
        )
    if SUDACHI_TOKENIZER is None:
        SUDACHI_TOKENIZER = sudachi_dictionary.Dictionary().create()
    return SUDACHI_TOKENIZER


def annotate_token_reading(surface: str, reading: str) -> str:
    if (
        not reading
        or re.search(r"[A-Za-z]", surface)
        or not JAPANESE_HAN_RE.search(surface)
        or surface.isspace()
        or all(
            unicodedata.category(character).startswith(("P", "S"))
            for character in surface
        )
    ):
        return surface
    return annotate_japanese_reading(surface, reading)


def generate_hiragana_lyrics(lyrics: str) -> str:
    with SUDACHI_TOKENIZER_LOCK:
        tokenizer = get_sudachi_tokenizer()
        converted_lines: list[str] = []
        for line in lyrics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line, protected_readings = protect_explicit_readings(line, tokenizer)
            converted_tokens: list[str] = []
            for token in tokenizer.tokenize(line):
                surface = token.surface()
                reading = token.reading_form()
                converted_tokens.append(annotate_token_reading(surface, reading))
            converted_line = "".join(converted_tokens)
            for placeholder, replacement in protected_readings.items():
                converted_line = converted_line.replace(placeholder, replacement)
            converted_lines.append(converted_line)
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
            request_attempts_per_candidate = (
                1
                + (1 if NAMUWIKI_API_TOKEN else 0)
                + (1 if NAMUWIKI_PREVIEW_FALLBACK_ENABLED else 0)
            )
            namuwiki_result = await asyncio.wait_for(
                run_lyrics_job(lookup_namuwiki_lyrics, track),
                timeout=(
                    NAMUWIKI_REQUEST_TIMEOUT_SECONDS
                    * NAMUWIKI_MAX_DOCUMENT_CANDIDATES
                    * request_attempts_per_candidate
                    + NAMUWIKI_REQUEST_INTERVAL_SECONDS
                    * NAMUWIKI_MAX_DOCUMENT_CANDIDATES
                    * request_attempts_per_candidate
                    + 5
                ),
            )
        except (asyncio.TimeoutError, NamuWikiLyricsError) as error:
            logger.warning(
                "NamuWiki lyrics lookup failed for %s: %s",
                track.title,
                error,
            )
            return None
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
            reading = extract_namuwiki_annotated_reading(track.korean_lyrics)
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
            reading = await run_lyrics_job(
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
    message = state.lyrics_message
    state.lyrics_message = None
    replace_lyrics_view(state, None)
    if message is not None:
        await delete_music_channel_message(guild_id, message)


def schedule_lyrics_message_cleanup(guild_id: int, state: GuildMusicState) -> None:
    message = state.lyrics_message
    state.lyrics_message = None
    replace_lyrics_view(state, None)
    if message is not None and not bot_shutdown_started:
        create_housekeeping_task(delete_music_channel_message(guild_id, message))


def track_is_current(guild_id: int, track: Track) -> bool:
    state = music_states.get(guild_id)
    return state is not None and state.current is track


def replace_lyrics_view(
    state: GuildMusicState,
    view: discord.ui.View | None,
    *,
    message_id: int | None = None,
) -> None:
    previous_view = state.lyrics_view
    state.lyrics_view = view
    if previous_view is not None and previous_view is not view:
        previous_view.stop()
        if view is not None and message_id is not None:
            # message.edit stores the new items before the old view is stopped.
            # Identical custom IDs are removed with the old view, so restore them.
            bot.add_view(view, message_id=message_id)


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
    edit_original: bool = False,
) -> None:
    attachment: discord.File | None = None
    if len(text) <= LYRICS_INLINE_LIMIT:
        embed = make_lyrics_variant_embed(
            track,
            label,
            text,
            source,
            source_url,
        )
    else:
        embed = make_lyrics_variant_embed(
            track,
            label,
            "내용이 길어 전체 내용을 파일로 첨부했어요.",
            source,
            source_url,
        )
        attachment = make_lyrics_file(text, filename)

    if edit_original:
        message = await interaction.edit_original_response(
            content=None,
            embed=embed,
            attachments=[attachment] if attachment is not None else [],
        )
    else:
        message = await send_ephemeral_followup(
            interaction,
            embed=embed,
            file=attachment,
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
        logger.info("Korean lyrics button received for %s", self.track.title)
        await interaction.response.send_message(
            "가사 정보를 확인하고 있어요...",
            ephemeral=True,
        )
        logger.info("Korean lyrics button acknowledged for %s", self.track.title)
        try:
            lyrics = await get_track_korean_lyrics(self.track)
        except KoreanLyricsError as error:
            logger.warning(
                "Korean lyrics lookup failed for %s: %s",
                self.track.title,
                error,
            )
            message = await interaction.edit_original_response(
                content="한국어 가사를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.",
                embed=None,
                attachments=[],
            )
            create_housekeeping_task(
                delete_message_later(message, EPHEMERAL_RESPONSE_DELETE_SECONDS)
            )
            return

        if not track_is_current(self.guild_id, self.track):
            message = await interaction.edit_original_response(
                content="가사를 가져오는 동안 곡이 바뀌었어요.",
                embed=None,
                attachments=[],
            )
            create_housekeeping_task(
                delete_message_later(message, EPHEMERAL_RESPONSE_DELETE_SECONDS)
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
            edit_original=True,
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
            state.lyrics_message = edited_message or message
            replace_lyrics_view(
                state,
                view,
                message_id=state.lyrics_message.id,
            )
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
    state.lyrics_message = message
    replace_lyrics_view(state, view, message_id=message.id)
    return message


def schedule_lyrics_publish(
    guild_id: int,
    track: Track,
) -> tuple[asyncio.Task[None] | None, bool]:
    if bot_shutdown_started:
        return None, False
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

    except asyncio.CancelledError:
        raise
    finally:
        if state.lyrics_task is current_task:
            state.lyrics_task = None


def clamp_auto_count(count: int) -> int:
    return clamp_auto_count_with_limit(count, MAX_AUTO_TRACKS)


def parse_auto_request(query: str) -> tuple[str, int] | None:
    return parse_auto_request_with_policy(
        query,
        default_count=DEFAULT_AUTO_TRACKS,
        clamp_count=clamp_auto_count,
    )


async def resolve_track_stream(track: Track) -> None:
    stream_age = (
        time.monotonic() - track.stream_resolved_at
        if track.stream_resolved_at is not None
        else STREAM_URL_MAX_AGE_SECONDS
    )
    if track.stream_url and stream_age < STREAM_URL_MAX_AGE_SECONDS:
        return

    invalidate_track_stream(track)
    info = await extract_ytdl_info(
        YTDL_OPTIONS,
        track.source_url,
        "audio stream resolve",
        job_kind=YtdlJobKind.PLAYBACK_STREAM,
        use_cache=False,
        minimum_interval_seconds=0.0,
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
    track.audio_codec = get_audio_codec(info)
    track.manual_subtitles = get_manual_subtitles(info)
    track.subtitle_language = (
        info.get("language") or info.get("original_language") or track.subtitle_language
    )


async def extract_track(
    query: str,
    requester: str,
    search_kind: str | None = None,
    requester_id: int | None = None,
) -> Track:
    resolved_query = resolve_query(query, search_kind)
    info = await extract_first_info(query, resolved_query)
    return make_track_from_info(info, requester, resolved_query, requester_id)


async def extract_tracks(
    query: str,
    requester: str,
    search_kind: str | None = None,
    requester_id: int | None = None,
) -> list[Track]:
    resolved_query = resolve_query(query, search_kind)
    info = await extract_ytdl_info(
        YTDL_PLAYLIST_OPTIONS,
        resolved_query,
        "playlist or album search",
        job_kind=YtdlJobKind.PLAYLIST_ALBUM,
    )

    if is_playlist_search_url(resolved_query):
        search_entries = [entry for entry in info.get("entries", []) if entry]
        if not search_entries:
            raise ValueError("No matching album or playlist was found.")

        first_result_url = get_playlist_result_url(search_entries[0])
        info = await extract_ytdl_info(
            YTDL_PLAYLIST_OPTIONS,
            first_result_url,
            "playlist or album resolve",
            job_kind=YtdlJobKind.PLAYLIST_ALBUM,
        )

    entries = [entry for entry in info.get("entries", []) if entry]
    if not entries:
        return [await extract_track(query, requester, search_kind, requester_id)]

    return [
        make_track_from_info(entry, requester, resolved_query, requester_id)
        for entry in entries[:MAX_BULK_TRACKS]
    ]


def build_youtube_radio_url(track: Track) -> str | None:
    video_id = get_track_video_id(track)
    if not video_id:
        return None
    return f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"


def get_autoplay_search_limit(
    count: int,
    job_kind: YtdlJobKind,
) -> int:
    auto_count = clamp_auto_count(count)
    if job_kind == YtdlJobKind.AUTOPLAY:
        return auto_count
    return auto_count * 3


def get_autoplay_playlist_options(count: int) -> dict:
    return {
        **YTDL_PLAYLIST_OPTIONS,
        "playlistend": clamp_auto_count(count),
    }


async def extract_auto_tracks_from_seed(
    seed_track: Track,
    requester: str,
    count: int,
    requester_id: int | None = None,
    *,
    job_kind: YtdlJobKind = YtdlJobKind.USER_REQUEST,
) -> list[Track]:
    auto_count = clamp_auto_count(count)
    if auto_count == 1:
        return [seed_track]

    search_limit = get_autoplay_search_limit(auto_count, job_kind)

    entries: list[dict] = []
    fallback_url = seed_track.webpage_url or seed_track.source_url
    radio_url = build_youtube_radio_url(seed_track)
    if radio_url:
        fallback_url = radio_url
        try:
            radio_info = await extract_ytdl_info(
                get_autoplay_playlist_options(auto_count),
                radio_url,
                "YouTube radio mix",
                job_kind=job_kind,
            )
            entries = [entry for entry in radio_info.get("entries", []) if entry]
        except Exception:
            logger.exception("Failed to extract YouTube radio mix for %s", seed_track.title)

    if not entries:
        search_query = f"ytsearch{search_limit}:{seed_track.title} radio mix"
        fallback_url = search_query
        info = await extract_ytdl_info(
            YTDL_SEARCH_OPTIONS,
            search_query,
            "auto fallback search",
            job_kind=job_kind,
        )
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
        search_query = f"ytsearch{search_limit}:{seed_track.title} radio mix"
        info = await extract_ytdl_info(
            YTDL_SEARCH_OPTIONS,
            search_query,
            "auto supplemental search",
            job_kind=job_kind,
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
        raise ValueError(f"관련 곡을 찾지 못했어요: {seed_track.title}")

    return tracks


async def extract_auto_tracks(
    query: str,
    requester: str,
    count: int,
    requester_id: int | None = None,
) -> list[Track]:
    seed_query = resolve_query(query)
    seed_info = await extract_first_info(query, seed_query)
    seed_track = make_track_from_info(seed_info, requester, seed_query, requester_id)
    return await extract_auto_tracks_from_seed(
        seed_track,
        requester,
        count,
        requester_id,
        job_kind=YtdlJobKind.USER_REQUEST,
    )


def cancel_autoplay_refill(state: GuildMusicState) -> None:
    task = state.autoplay_task
    if task and not task.done():
        task.cancel()
    state.autoplay_task = None


def schedule_autoplay_refill(
    guild_id: int,
) -> tuple[asyncio.Task[None] | None, bool]:
    if bot_shutdown_started:
        return None, False
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
    candidate_count = clamp_auto_count(AUTOPLAY_REFILL_CANDIDATES)

    try:
        while autoplay_can_refill(state, generation):
            seed = get_autoplay_seed(state) or fallback_seed
            fallback_seed = seed
            try:
                candidates = await extract_auto_tracks_from_seed(
                    seed,
                    "자동재생",
                    candidate_count,
                    job_kind=YtdlJobKind.AUTOPLAY,
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
            if (
                not bot_shutdown_started
                and added_track
                and current_track_id != starting_track_id
            ):
                schedule_autoplay_refill(guild_id)


def cancel_noncritical_tasks(state: GuildMusicState) -> None:
    task = state.noncritical_task
    if task and not task.done():
        task.cancel()
    state.noncritical_task = None


def schedule_noncritical_tasks(
    guild_id: int,
    track: Track,
) -> tuple[asyncio.Task[None] | None, bool]:
    if bot_shutdown_started:
        return None, False
    state = get_state(guild_id)
    if state.noncritical_task and not state.noncritical_task.done():
        return state.noncritical_task, False

    task = asyncio.create_task(
        start_noncritical_tasks(
            guild_id,
            state.playback_generation,
            track,
        )
    )
    state.noncritical_task = task
    return task, True


async def start_noncritical_tasks(
    guild_id: int,
    generation: int,
    track: Track,
) -> None:
    state = get_state(guild_id)
    current_task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    jobs = (
        (AUTOPLAY_START_DELAY_SECONDS, "autoplay"),
        (LYRICS_START_DELAY_SECONDS, "lyrics"),
    )

    try:
        for delay_seconds, job in sorted(jobs):
            remaining = delay_seconds - (loop.time() - started_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
            if (
                generation != state.playback_generation
                or state.current is not track
            ):
                return
            if job == "autoplay":
                schedule_autoplay_refill(guild_id)
            else:
                schedule_lyrics_publish(guild_id, track)
    finally:
        if state.noncritical_task is current_task:
            state.noncritical_task = None


async def wait_for_voice_connection(
    voice: discord.VoiceProtocol,
    timeout_seconds: float = VOICE_RECONNECT_GRACE_SECONDS,
) -> bool:
    if voice.is_connected():
        return True
    if timeout_seconds <= 0:
        return False

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while not voice.is_connected():
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.25, remaining))
    return True


async def discard_stale_voice_client(
    guild: discord.Guild,
    state: GuildMusicState,
    voice: discord.VoiceProtocol,
) -> None:
    stop_playback(state, guild.id)
    try:
        await asyncio.wait_for(
            voice.disconnect(force=True),
            timeout=VOICE_DISCONNECT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out cleaning up stale voice client in guild %s", guild.id)
    except Exception:
        logger.warning(
            "Failed to disconnect stale voice client in guild %s",
            guild.id,
            exc_info=True,
        )
    finally:
        if getattr(guild, "voice_client", None) is voice:
            cleanup = getattr(voice, "cleanup", None)
            if callable(cleanup):
                try:
                    cleanup()
                except Exception:
                    logger.warning(
                        "Failed to remove stale voice client in guild %s",
                        guild.id,
                        exc_info=True,
                    )
        if state.voice is voice:
            state.voice = None


async def use_connected_voice(
    voice: discord.VoiceProtocol,
    channel: discord.abc.Connectable,
    state: GuildMusicState,
) -> tuple[bool, str | None]:
    if bot_shutdown_started:
        return False, "The bot is shutting down."
    if voice.channel == channel:
        return True, None
    if state.current or state.queue or voice.is_playing() or voice.is_paused():
        return (
            False,
            f"봇이 이미 {voice.channel.mention}에서 재생 중이에요. "
            "같은 음성 채널에 들어와 주세요.",
        )
    if bot_shutdown_started:
        return False, "The bot is shutting down."
    await voice.move_to(channel)
    if bot_shutdown_started:
        return False, "The bot is shutting down."
    return True, None


async def cleanup_voice_connected_during_shutdown(
    voice: discord.VoiceProtocol,
) -> None:
    async def cleanup() -> None:
        try:
            await asyncio.wait_for(
                voice.disconnect(force=True),
                timeout=VOICE_DISCONNECT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Timed out disconnecting a late voice connection")
        except Exception:
            logger.warning(
                "Failed to disconnect a late voice connection",
                exc_info=True,
            )
        finally:
            cleanup_callback = getattr(voice, "cleanup", None)
            if callable(cleanup_callback):
                try:
                    cleanup_callback()
                except Exception:
                    logger.warning(
                        "Failed to clean up a late voice connection",
                        exc_info=True,
                    )

    cleanup_task = asyncio.create_task(cleanup())
    cancellation_received, cleanup_error = (
        await wait_for_task_completion_despite_cancellation(cleanup_task)
    )
    if cleanup_error is not None:
        raise cleanup_error
    if cancellation_received:
        raise asyncio.CancelledError


async def _ensure_voice_channel(
    guild: discord.Guild,
    channel: discord.abc.Connectable,
    state: GuildMusicState,
) -> tuple[bool, str | None, bool]:
    async with state.voice_connect_lock:
        if bot_shutdown_started:
            return False, "The bot is shutting down.", False
        for attempt in range(2):
            registered_voice = getattr(guild, "voice_client", None)
            if registered_voice is not None:
                state.voice = registered_voice

            voice = state.voice
            if voice is not None and not voice.is_connected():
                recovered = (
                    registered_voice is voice
                    and await wait_for_voice_connection(voice)
                )
                if not recovered:
                    await discard_stale_voice_client(guild, state, voice)
                    voice = None

            if voice is not None and voice.is_connected():
                try:
                    original_channel = voice.channel
                    ok, error = await use_connected_voice(voice, channel, state)
                    moved = (
                        ok
                        and original_channel != channel
                        and voice.channel == channel
                    )
                    if moved:
                        stop_playback(state, guild.id)
                    return ok, error, moved
                except (asyncio.TimeoutError, discord.DiscordException):
                    logger.warning(
                        "Failed to move voice client in guild %s",
                        guild.id,
                        exc_info=True,
                    )
                    return False, "음성 채널 이동에 실패했어요. 잠시 후 다시 시도해 주세요.", False

            if bot_shutdown_started:
                return False, "The bot is shutting down.", False
            try:
                voice = await channel.connect()
            except discord.ClientException as error:
                if getattr(guild, "voice_client", None) is not None and attempt == 0:
                    logger.info(
                        "Adopting registered voice client after a connection race in guild %s",
                        guild.id,
                    )
                    continue
                logger.warning(
                    "Voice connection rejected in guild %s: %s",
                    guild.id,
                    error,
                )
                return False, "음성 채널 연결에 실패했어요. 잠시 후 다시 시도해 주세요.", False
            except (asyncio.TimeoutError, discord.DiscordException):
                logger.warning(
                    "Voice connection failed in guild %s",
                    guild.id,
                    exc_info=True,
                )
                return False, "음성 채널 연결에 실패했어요. 잠시 후 다시 시도해 주세요.", False

            if bot_shutdown_started:
                await cleanup_voice_connected_during_shutdown(voice)
                return False, "The bot is shutting down.", False
            state.voice = voice
            return True, None, False

    return False, "음성 채널 연결에 실패했어요. 잠시 후 다시 시도해 주세요.", False


async def ensure_voice_channel(
    guild: discord.Guild,
    channel: discord.abc.Connectable,
    state: GuildMusicState,
) -> tuple[bool, str | None]:
    if bot_shutdown_started:
        return False, "The bot is shutting down."
    operation_task = track_voice_operation()
    try:
        ok, error, moved = await _ensure_voice_channel(guild, channel, state)
        if ok:
            cancel_empty_channel_disconnect(state)
            update_empty_channel_disconnect(state, guild.id)
            if moved:
                create_housekeeping_task(show_idle_panel(guild.id, state))
        return ok, error
    finally:
        voice_operation_tasks.discard(operation_task)


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

    guild = interaction.guild
    if guild is None:
        await send_ephemeral_followup(interaction, guild_only_error())
        return False

    ok, error = await ensure_voice_channel(guild, channel, state)
    if not ok:
        await send_ephemeral_followup(
            interaction,
            error or "음성 채널 연결에 실패했어요.",
        )
    return ok


async def ensure_voice_for_member(
    member: discord.Member,
    state: GuildMusicState,
) -> tuple[bool, str | None]:
    voice_state = getattr(member, "voice", None)
    channel = getattr(voice_state, "channel", None)

    if channel is None:
        return False, "먼저 음성 채널에 들어가 주세요."
    return await ensure_voice_channel(member.guild, channel, state)


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
    if state.current is not None:
        reset_track_playback_state(state.current)
    state.current = None
    cancel_noncritical_tasks(state)
    cancel_autoplay_refill(state)
    cancel_lyrics_publish(state)
    schedule_lyrics_message_cleanup(guild_id, state)
    clear_pending_playback_advance(state)

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
        async with state.voice_connect_lock:
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

        async with state.voice_connect_lock:
            if (
                state.voice is not voice
                or not voice.is_connected()
                or voice.channel.id != channel_id
                or channel_has_human_listener(voice.channel)
            ):
                return

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
    if bot_shutdown_started:
        return
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
) -> tuple[asyncio.Task[None] | None, bool]:
    if bot_shutdown_started:
        return None, False
    state = get_state(guild_id)
    if state.advance_task and not state.advance_task.done():
        return state.advance_task, False

    task = asyncio.create_task(play_next(guild_id, announce=announce))
    state.advance_task = task
    return task, True


def clear_pending_playback_advance(state: GuildMusicState) -> None:
    state.pending_advance_task = None
    state.pending_advance_generation = None
    state.pending_advance_announce = False


def complete_pending_playback_advance(
    guild_id: int,
    completed_task: asyncio.Task[None],
) -> None:
    state = get_state(guild_id)
    if state.pending_advance_task is not completed_task:
        return

    generation = state.pending_advance_generation
    announce = state.pending_advance_announce
    clear_pending_playback_advance(state)
    if bot_shutdown_started or generation != state.playback_generation:
        return
    if announce:
        schedule_play_next(guild_id)
    else:
        schedule_play_next(guild_id, announce=False)


def schedule_play_next_after_current(
    guild_id: int,
    generation: int,
    *,
    announce: bool = True,
) -> tuple[asyncio.Task[None] | None, bool]:
    if bot_shutdown_started:
        return None, False
    state = get_state(guild_id)
    if generation != state.playback_generation:
        return state.advance_task, False

    active_task = state.advance_task
    if active_task and not active_task.done():
        # Coalesce callbacks and advance only after the current scheduler task is done.
        if state.pending_advance_task is not active_task:
            state.pending_advance_task = active_task
            state.pending_advance_generation = generation
            state.pending_advance_announce = announce
            active_task.add_done_callback(
                lambda completed: complete_pending_playback_advance(
                    guild_id,
                    completed,
                )
            )
        else:
            state.pending_advance_announce = (
                state.pending_advance_announce or announce
            )
        return active_task, False

    if announce:
        return schedule_play_next(guild_id)
    return schedule_play_next(guild_id, announce=False)


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
    request_generation: int | None = None,
) -> bool:
    state = get_state(guild_id)
    if request_generation is None:
        request_generation = state.playback_generation
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
                create_housekeeping_task(
                    delete_message_later(initial_response, MUSIC_FEEDBACK_DELETE_SECONDS)
                )
            else:
                if view is None or private:
                    create_housekeeping_task(
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
            create_housekeeping_task(
                delete_message_later(message, MUSIC_FEEDBACK_DELETE_SECONDS)
            )
        return message

    if state.playback_generation != request_generation:
        await send_feedback(
            content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요."
        )
        return False

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

    if state.playback_generation != request_generation:
        await send_feedback(
            content="곡을 찾는 동안 재생이 중지되어 요청을 취소했어요."
        )
        return False

    state.queue.extend(tracks)
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
        active_advance = state.advance_task
        if active_advance is not None and not active_advance.done():
            playback_task, started_playback = schedule_play_next_after_current(
                guild_id,
                request_generation,
                announce=True,
            )
        else:
            playback_task, started_playback = schedule_play_next(
                guild_id,
                announce=False,
            )
    else:
        schedule_autoplay_refill(guild_id)

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
) -> discord.Message | None:
    history = getattr(control_channel, "history", None)
    if history is None:
        return known_message

    candidates: dict[int, discord.Message] = {}
    if known_message is not None:
        candidates[known_message.id] = known_message

    bot_user_id = getattr(bot.user, "id", None)
    try:
        async for message in history(limit=CONTROL_PANEL_HISTORY_LIMIT):
            if (
                message.id in candidates
                or is_music_control_panel_message(message, bot_user_id)
            ):
                candidates[message.id] = message
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
        return None

    newest_message = max(candidates.values(), key=lambda message: message.id)
    removed_panel_count = 0
    for message in candidates.values():
        if message.id == newest_message.id:
            continue
        if await delete_music_channel_message(guild_id, message):
            removed_panel_count += 1

    if removed_panel_count:
        logger.info(
            "Kept control panel %s and removed %s duplicate panel(s) in guild %s",
            newest_message.id,
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
) -> discord.Message | None:
    async with state.control_panel_lock:
        return await _update_control_panel(
            guild_id,
            state,
            channel=channel,
        )


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

    recovering_panel = state.control_message is None
    saved_message_id = get_control_message_id(guild_id) if recovering_panel else None
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

    searched_history = False
    if state.control_message is None:
        searched_history = True
        state.control_message = await reconcile_control_panel_messages(
            guild_id,
            control_channel,
            state.control_message,
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
            if searched_history and saved_message_id != state.control_message.id:
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
            cancel_noncritical_tasks(state)
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
                    track.playback_attempts += 1
                    state.current = track
                    state.skip_requested = False
                    state.stop_requested = False
                    should_delete_panel = False

            if should_delete_panel:
                cancel_noncritical_tasks(state)
                cancel_lyrics_publish(state)
                await clear_lyrics_message(guild_id, state)
                await show_idle_panel(guild_id, state)
                return
            assert track is not None
            cancel_noncritical_tasks(state)
            cancel_lyrics_publish(state)

            used_opus_copy = False
            attempt_number = track.playback_attempts
            try:
                await resolve_track_stream(track)
                used_opus_copy = (
                    not track.force_transcode
                    and (track.audio_codec or "").casefold() in {"opus", "libopus"}
                )
                logger.info(
                    "Playback start: title=%s codec=%s copy=%s transcode=%s retry=%s",
                    track.title,
                    track.audio_codec or "unknown",
                    used_opus_copy,
                    not used_opus_copy,
                    max(0, attempt_number - 1),
                )
                source = discord.FFmpegOpusAudio(
                    track.stream_url,
                    bitrate=128,
                    codec="copy" if used_opus_copy else None,
                    executable=FFMPEG_EXECUTABLE,
                    **FFMPEG_OPTIONS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                retrying = requeue_track_after_playback_error(
                    state,
                    track,
                    used_opus_copy=used_opus_copy,
                )
                logger.exception(
                    "Failed to prepare playback for %s (attempt %s/%s, retry=%s)",
                    track.title,
                    attempt_number,
                    MAX_PLAYBACK_ATTEMPTS,
                    retrying,
                )
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
                        def advance() -> None:
                            if (
                                generation != state.playback_generation
                                or state.current is not track
                            ):
                                return

                            cancel_noncritical_tasks(state)
                            cancel_lyrics_publish(state)
                            schedule_private_lyrics_cleanup(state, track.track_id)
                            if error:
                                retrying = requeue_track_after_playback_error(
                                    state,
                                    track,
                                    used_opus_copy=used_opus_copy,
                                )
                                logger.warning(
                                    "Playback error for %s (attempt %s/%s, retry=%s): %s",
                                    track.title,
                                    attempt_number,
                                    MAX_PLAYBACK_ATTEMPTS,
                                    retrying,
                                    error,
                                )
                            else:
                                repeating = (
                                    state.repeat_one
                                    and not state.skip_requested
                                    and not state.stop_requested
                                )
                                if repeating:
                                    reset_track_playback_attempts(track)
                                    state.queue.appendleft(track)
                                else:
                                    reset_track_playback_state(track)
                                state.current = None
                            schedule_play_next_after_current(
                                guild_id,
                                generation,
                            )

                        bot.loop.call_soon_threadsafe(advance)

                    try:
                        voice.play(source, after=after_playback)
                    except Exception:
                        source.cleanup()
                        retrying = requeue_track_after_playback_error(
                            state,
                            track,
                            used_opus_copy=used_opus_copy,
                        )
                        logger.exception(
                            "Failed to start playback for %s "
                            "(attempt %s/%s, retry=%s)",
                            track.title,
                            attempt_number,
                            MAX_PLAYBACK_ATTEMPTS,
                            retrying,
                        )
                        continue
            except asyncio.CancelledError:
                if not voice.is_playing():
                    source.cleanup()
                raise

            remember_autoplay_track(state, track)
            if announce and state.current is track:
                await update_control_panel(guild_id, state)
            if state.current is track:
                schedule_noncritical_tasks(guild_id, track)
            return
    finally:
        if state.advance_task is current_task:
            state.advance_task = None


def guild_only_error() -> str:
    return "이 명령어는 디스코드 서버 안에서만 사용할 수 있어요."


@bot.event
async def on_ready() -> None:
    global commands_synced, startup_initialized
    logger.info("Logged in as %s", bot.user)
    async with startup_initialization_lock:
        if not startup_initialized:
            load_music_channel_config()
            if ffmpeg_is_available():
                logger.info("Using FFmpeg executable: %s", FFMPEG_EXECUTABLE)
            else:
                logger.error(
                    "FFmpeg executable was not found. Set FFMPEG_PATH in .env "
                    "or add ffmpeg to PATH."
                )
            await restore_control_panels()
            startup_initialized = True

        if commands_synced:
            return

        if DEV_GUILD_ID:
            guild = discord.Object(id=int(DEV_GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info(
                "Synced %s command(s) to dev guild %s",
                len(synced),
                DEV_GUILD_ID,
            )
        else:
            synced = await bot.tree.sync()
            logger.info("Synced %s global command(s)", len(synced))
        commands_synced = True


@bot.event
async def on_message(message: discord.Message) -> None:
    if bot_shutdown_started or message.author.bot or message.guild is None:
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
            create_housekeeping_task(
                delete_message_later(error_message, MUSIC_FEEDBACK_DELETE_SECONDS)
            )
        await delete_music_request_message(message)
        return

    request_generation = state.playback_generation
    loading_message = await send_music_request_reply(message, "곡을 찾고 있어요...")
    try:
        await enqueue_tracks(
            message.guild.id,
            message.channel,
            message.author,
            query,
            initial_response=loading_message,
            request_generation=request_generation,
        )
    except discord.HTTPException as error:
        log_discord_http_error("processing a music request", error)
        if loading_message is not None:
            create_housekeeping_task(
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

    voice_to_disconnect: discord.VoiceProtocol | None = None
    original_channel: discord.abc.Connectable | None = None
    async with state.voice_connect_lock:
        voice = state.voice
        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if (
            voice is not None
            and voice.is_connected()
            and member_channel == voice.channel
        ):
            voice_to_disconnect = voice
            original_channel = voice.channel
            cancel_empty_channel_disconnect(state)
            stop_playback(state, interaction.guild_id)

    if voice_to_disconnect is None or original_channel is None:
        await send_ephemeral_response(
            interaction,
            "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
        )
        return

    await show_idle_panel(interaction.guild_id, state)

    disconnected = False
    async with state.voice_connect_lock:
        if (
            state.voice is voice_to_disconnect
            and voice_to_disconnect.is_connected()
            and voice_to_disconnect.channel == original_channel
        ):
            await voice_to_disconnect.disconnect()
            if state.voice is voice_to_disconnect:
                state.voice = None
            disconnected = True

    if not disconnected:
        await send_ephemeral_response(
            interaction,
            "재생은 중지했지만 봇의 음성 채널이 변경되어 연결 해제를 취소했어요.",
        )
        return

    await interaction.response.send_message("음성 채널에서 나왔어요.")


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Put it in .env or your environment.")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
