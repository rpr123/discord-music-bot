from __future__ import annotations

import asyncio
import concurrent.futures
import copy
import functools
import random
import re
import shutil
import threading
import time
import unicodedata
from collections import OrderedDict, deque
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
    SUDACHI_TOKENIZER,
    SUDACHI_TOKENIZER_LOCK,
    LyricsReadingError,
    annotate_japanese_reading,
    annotate_token_reading,
    find_explicit_reading_base_start,
    find_explicit_reading_replacements,
    generate_hiragana_lyrics,
    get_reading_surface_segment_kind,
    get_sudachi_tokenizer,
    katakana_to_hiragana,
    lyrics_are_japanese,
    lyrics_are_primarily_korean,
    normalize_japanese_reading,
    protect_explicit_readings,
    replace_explicit_readings,
    split_reading_surface,
    sudachi_dictionary,
)
from music_models import (
    AUTOPLAY_HISTORY_SIZE,
    MAX_PLAYBACK_ATTEMPTS,
    GuildMusicState,
    Track,
    invalidate_track_stream,
    remove_queued_track,
    remove_queued_track_by_id,
    remove_queued_track_range_by_ids,
    requeue_track_after_playback_error,
    reset_track_playback_attempts,
    reset_track_playback_state,
)
from music_discord_display import (
    CONTROL_PANEL_TITLES,
    DISCORD_EMBED_FIELD_LIMIT,
    IDLE_PANEL_TITLE,
    LYRICS_INLINE_LIMIT,
    MUSIC_CHANNEL_DELETE_REQUESTS,
    MUSIC_CHANNEL_SILENT,
    PLAYING_PANEL_TITLE,
    delete_interaction_response_later,
    delete_message_later,
    delete_music_request_message,
    delete_private_interaction_message,
    describe_queue_selection,
    format_duration,
    is_silent_music_channel,
    log_discord_http_error,
    make_bulk_embed,
    make_idle_player_embed,
    make_lyrics_embed,
    make_lyrics_file,
    make_lyrics_variant_embed,
    make_player_embed,
    make_queue_line,
    make_queue_embed,
    make_track_link,
    make_track_embed,
    notify_playback_error,
    requester_label,
    send_music_request_reply,
    single_line,
    truncate_option_text,
    truncate_text,
)
from music_lyrics_sources import (
    LRC_METADATA_RE,
    LRC_TIMESTAMP_RE,
    LYRICS_DURATION_MATCH_TOLERANCE_SECONDS,
    LYRICS_NATIVE_SCRIPT_MIN_RATIO,
    LYRICS_NATIVE_SCRIPT_SCORE_WINDOW,
    QUOTED_TRACK_TITLE_RE,
    VTT_TAG_RE,
    VTT_TIMESTAMP_LINE_RE,
    LyricsLookupError,
    YouTubeSubtitleError,
    extract_json3_lyrics,
    extract_original_lyrics,
    extract_vtt_lyrics,
    get_manual_subtitle_candidates,
    get_lyrics_search_terms,
    get_lyrics_title_aliases,
    get_subtitle_candidates,
    lyrics_native_script_ratio,
    lyrics_record_score,
    lookup_track_lyrics,
    normalize_lyrics_match_text,
    normalize_subtitle_text,
    request_lyrics_records,
    request_youtube_subtitle,
    select_korean_manual_subtitle,
    select_lyrics_record,
    select_manual_subtitle,
)
from music_namuwiki import (
    NAMUWIKI_MAX_DOCUMENT_CANDIDATES,
    build_namuwiki_document_candidates,
    extract_namuwiki_primary_artist_from_tables,
    find_namuwiki_override,
    get_namuwiki_document_candidates,
    get_namuwiki_override,
    get_namuwiki_track_artists,
    lookup_namuwiki_lyrics,
    namuwiki_artist_matches_track,
    parse_namuwiki_candidate,
    read_limited_http_response,
    request_namuwiki_api_source,
    request_namuwiki_html,
    request_namuwiki_html_once,
    split_namuwiki_candidate,
    wait_for_namuwiki_interval,
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
    build_youtube_search_query,
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
    resolve_query,
    score_youtube_search_result,
    select_youtube_music_song_result,
    select_youtube_search_result,
    should_use_youtube_music_search,
    strip_edge_title_tags,
    youtube_music_entries_are_ambiguous,
    youtube_music_result_to_entry,
)
from music_track_metadata import (
    get_audio_codec,
    get_entry_url,
    get_manual_subtitles,
    get_resolved_stream_url,
    get_thumbnail_url,
    get_track_identity_keys,
    get_track_video_id,
    get_video_id,
    make_track_from_info,
    normalize_track_key,
)
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials

from music_config import (
    AUTOPLAY_BUTTON_CUSTOM_ID,
    AUTOPLAY_REFILL_CANDIDATES,
    AUTOPLAY_START_DELAY_SECONDS,
    CONTROL_PANEL_HISTORY_LIMIT,
    DEFAULT_AUTO_TRACKS,
    DEV_GUILD_ID,
    DISCORD_TOKEN,
    EMPTY_CHANNEL_DISCONNECT_DELAY_SECONDS,
    EPHEMERAL_RESPONSE_DELETE_SECONDS,
    FFMPEG_EXECUTABLE,
    FFMPEG_OPTIONS,
    LOG_LEVEL,
    LYRICS_API_URL,
    LYRICS_READING_ENABLED,
    LYRICS_REQUEST_TIMEOUT_SECONDS,
    LYRICS_START_DELAY_SECONDS,
    MAX_AUTO_TRACKS,
    MAX_BULK_TRACKS,
    MUSIC_CHANNEL_ID,
    MUSIC_CHANNEL_NAME,
    MUSIC_CHANNELS_FILE,
    MUSIC_FEEDBACK_DELETE_SECONDS,
    NAMUWIKI_API_BASE_URL,
    NAMUWIKI_API_TOKEN,
    NAMUWIKI_DOCUMENT_OVERRIDES,
    NAMUWIKI_LYRICS_ENABLED,
    NAMUWIKI_PAGE_BASE_URL,
    NAMUWIKI_PREVIEW_FALLBACK_ENABLED,
    NAMUWIKI_REQUEST_INTERVAL_SECONDS,
    NAMUWIKI_REQUEST_TIMEOUT_SECONDS,
    PROJECT_DIR,
    QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
    QUEUE_SELECT_LIMIT,
    STREAM_URL_MAX_AGE_SECONDS,
    VOICE_DISCONNECT_TIMEOUT_SECONDS,
    VOICE_RECONNECT_GRACE_SECONDS,
    YOUTUBE_CIRCUIT_BREAKER_SECONDS,
    YOUTUBE_COOKIES_FILE,
    YOUTUBE_LYRICS_FALLBACK,
    YOUTUBE_MUSIC_AUTH_FILE,
    YOUTUBE_MUSIC_LANGUAGE,
    YOUTUBE_MUSIC_LOCATION,
    YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS,
    YOUTUBE_MUSIC_OAUTH_CLIENT_ID,
    YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET,
    YOUTUBE_MUSIC_SEARCH_ENABLED,
    YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
    YOUTUBE_SEARCH_CANDIDATES,
    YOUTUBE_SUBTITLE_MIN_INTERVAL_SECONDS,
    YTDL_BASE_OPTIONS,
    YTDL_CACHE_MAX_ENTRIES,
    YTDL_CACHE_TTL_SECONDS,
    YTDL_EXTRACT_TIMEOUT_SECONDS,
    YTDL_MAX_CONCURRENT_EXTRACTIONS,
    YTDL_MIN_INTERVAL_SECONDS,
    YTDL_OPTIONS,
    YTDL_PLAYLIST_OPTIONS,
    YTDL_SEARCH_OPTIONS,
    YTDL_WORKER_PATH,
    clear_control_message_id,
    configured_autoplay_enabled,
    configured_control_messages,
    configured_music_channels,
    get_autoplay_enabled,
    get_control_message_id,
    get_music_channel_id,
    load_env_file,
    load_music_channel_config,
    logger,
    parse_nonnegative_float_env,
    parse_positive_int_env,
    parse_string_map_env,
    resolve_project_path,
    save_music_channel_config,
    set_autoplay_enabled,
    set_control_message_id,
    set_music_channel,
)
from music_ytdl import (
    YouTubeCircuitOpenError,
    YtdlJobKind,
    cache_ytdl_info,
    ensure_youtube_circuit_closed,
    get_cached_ytdl_info,
    get_ytdl_cache_key,
    stamp_ytdl_info,
    trip_youtube_circuit,
    wait_for_task_completion_despite_cancellation,
    ytdl_scheduler,
)

T = TypeVar("T")

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


class QueueRemoveSelect(discord.ui.Select):
    def __init__(
        self,
        guild_id: int,
        *,
        interaction_lock: asyncio.Lock | None = None,
    ):
        self.guild_id = guild_id
        self.interaction_lock = interaction_lock or asyncio.Lock()
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
        accepted_voice = state.voice
        selected_track_id = self.values[0]
        await interaction.response.defer()
        refresh_panel = False
        authorization_error: str | None = None
        try:
            async with self.interaction_lock:
                if state.voice is not accepted_voice:
                    authorization_error = (
                        "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요."
                    )
                else:
                    member_channel = getattr(
                        getattr(interaction.user, "voice", None),
                        "channel",
                        None,
                    )
                    if (
                        accepted_voice is None
                        or not accepted_voice.is_connected()
                        or member_channel != accepted_voice.channel
                    ):
                        authorization_error = (
                            "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
                        )

                if authorization_error is None:
                    removed = remove_queued_track_by_id(state, selected_track_id)
                else:
                    removed = None

                if authorization_error is None and removed is None:
                    replacement_view = (
                        QueueManageView(
                            self.guild_id,
                            interaction_lock=self.interaction_lock,
                        )
                        if state.queue
                        else None
                    )
                    await interaction.edit_original_response(
                        content="이미 삭제되었거나 찾을 수 없는 곡이에요.",
                        embed=make_queue_embed(state),
                        view=replacement_view,
                    )
                    if replacement_view is not None:
                        schedule_queue_message_cleanup(
                            state,
                            interaction.message,
                            EPHEMERAL_RESPONSE_DELETE_SECONDS,
                        )
                    return

                if removed is not None:
                    schedule_autoplay_refill(self.guild_id)
                    refresh_panel = state.current is not None
                    replacement_view = (
                        QueueManageView(
                            self.guild_id,
                            interaction_lock=self.interaction_lock,
                        )
                        if state.queue
                        else None
                    )
                    await interaction.edit_original_response(
                        content=f"대기열에서 `{removed.title}`을 삭제했어요.",
                        embed=make_queue_embed(state),
                        view=replacement_view,
                    )
                    schedule_queue_message_cleanup(
                        state,
                        interaction.message,
                        QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
                    )
        finally:
            if refresh_panel:
                await update_control_panel(self.guild_id, state)

        if authorization_error is not None:
            await send_ephemeral_followup(interaction, authorization_error)


class QueueManageView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        *,
        interaction_lock: asyncio.Lock | None = None,
    ):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.interaction_lock = interaction_lock or asyncio.Lock()
        if get_state(guild_id).queue:
            self.add_item(
                QueueRemoveSelect(
                    guild_id,
                    interaction_lock=self.interaction_lock,
                )
            )

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
        await interaction.response.defer()
        async with self.range_view.interaction_lock:
            if self.range_view.is_finished():
                return

            state = get_state(self.range_view.guild_id)
            await interaction.edit_original_response(
                content=self.range_view.make_selection_content(state),
                embed=make_queue_embed(state),
                view=self.range_view,
            )
            schedule_queue_message_cleanup(
                state,
                interaction.message,
                EPHEMERAL_RESPONSE_DELETE_SECONDS,
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
        self.interaction_lock = asyncio.Lock()
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
        state = get_state(self.guild_id)
        accepted_voice = state.voice
        start_track_id = self.start_track_id
        end_track_id = self.end_track_id
        await interaction.response.defer()
        refresh_panel = False
        authorization_error: str | None = None
        try:
            async with self.interaction_lock:
                if self.is_finished():
                    return

                if start_track_id is None or end_track_id is None:
                    await interaction.edit_original_response(
                        content=self.make_selection_content(state),
                        view=self,
                    )
                    return

                async with state.lock:
                    if state.voice is not accepted_voice:
                        authorization_error = (
                            "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요."
                        )
                    else:
                        member_channel = getattr(
                            getattr(interaction.user, "voice", None),
                            "channel",
                            None,
                        )
                        if (
                            accepted_voice is None
                            or not accepted_voice.is_connected()
                            or member_channel != accepted_voice.channel
                        ):
                            authorization_error = (
                                "봇과 같은 음성 채널에 들어와야 조작할 수 있어요."
                            )

                    if authorization_error is None:
                        result = remove_queued_track_range_by_ids(
                            state,
                            start_track_id,
                            end_track_id,
                        )
                    else:
                        result = None

                if authorization_error is None and result is None:
                    replacement_view = (
                        QueueRangeDeleteView(self.guild_id)
                        if state.queue
                        else None
                    )
                    await interaction.edit_original_response(
                        content=(
                            "대기열이 변경되어 선택한 곡을 찾을 수 없어요. "
                            "삭제할 구간을 다시 선택해 주세요."
                        ),
                        embed=make_queue_embed(state),
                        view=replacement_view,
                    )
                    self.stop()
                    if replacement_view is not None:
                        schedule_queue_message_cleanup(
                            state,
                            interaction.message,
                            EPHEMERAL_RESPONSE_DELETE_SECONDS,
                        )
                    return

                if result is not None:
                    removed, start_index, end_index = result
                    schedule_autoplay_refill(self.guild_id)
                    refresh_panel = state.current is not None
                    await interaction.edit_original_response(
                        content=(
                            f"대기열 {start_index + 1}~{end_index + 1}번, "
                            f"{len(removed)}곡을 삭제했어요."
                        ),
                        embed=make_queue_embed(state),
                        view=None,
                    )
                    self.stop()
                    schedule_queue_message_cleanup(
                        state,
                        interaction.message,
                        QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
                    )
        finally:
            if refresh_panel:
                await update_control_panel(self.guild_id, state)

        if authorization_error is not None:
            await send_ephemeral_followup(interaction, authorization_error)


class MusicControlView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        *,
        disabled: bool = False,
    ):
        super().__init__(timeout=None)
        self.guild_id = guild_id
        self._sync_buttons(get_state(guild_id), disabled=disabled)

    def _sync_buttons(
        self,
        state: GuildMusicState,
        *,
        disabled: bool,
    ) -> None:
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
                child.disabled = False
            else:
                child.disabled = disabled

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

    async def edit_panel(
        self,
        interaction: discord.Interaction,
        *,
        refresh_canonical: bool = False,
    ) -> bool:
        state = self.get_state()
        clicked_message_id = getattr(interaction.message, "id", None)
        clicked_panel_updated = False
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
            async with state.control_panel_lock:
                if self.is_finished():
                    return False
                if state.current is None:
                    embed = make_idle_player_embed()
                    view = MusicControlView(self.guild_id, disabled=True)
                else:
                    embed = make_player_embed(state.current, state)
                    view = MusicControlView(self.guild_id)
                await interaction.edit_original_response(embed=embed, view=view)
                control_message_id = getattr(state.control_message, "id", None)
                clicked_is_current = (
                    clicked_message_id is not None
                    and clicked_message_id == control_message_id
                )
                if clicked_is_current:
                    replace_control_panel_view(
                        state,
                        view,
                        message_id=clicked_message_id,
                    )
            clicked_panel_updated = True
        finally:
            if refresh_canonical:
                control_message_id = getattr(state.control_message, "id", None)
                clicked_is_current = (
                    clicked_message_id is not None
                    and clicked_message_id == control_message_id
                )
                if not clicked_panel_updated or not clicked_is_current:
                    await update_control_panel(
                        self.guild_id,
                        state,
                        require_control_view=True,
                    )
        return clicked_panel_updated

    @discord.ui.button(
        label="재생/일시정지",
        emoji="⏯️",
        style=discord.ButtonStyle.secondary,
        custom_id="music:pause_resume",
        row=0,
    )
    async def pause_resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        voice = state.voice
        if voice is None:
            await send_ephemeral_response(interaction, "봇이 음성 채널에 없어요.")
            return
        if not voice.is_paused() and not voice.is_playing():
            await send_ephemeral_response(interaction, "지금 재생 중인 곡이 없어요.")
            return

        await interaction.response.defer()
        if state.voice is not voice:
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            )
            return
        if not await ensure_same_voice_channel(interaction, state):
            return

        if voice.is_paused():
            voice.resume()
        elif voice.is_playing():
            voice.pause()
        else:
            await send_ephemeral_followup(interaction, "지금 재생 중인 곡이 없어요.")
            return

        await self.edit_panel(interaction)

    @discord.ui.button(
        label="스킵",
        emoji="⏭️",
        style=discord.ButtonStyle.primary,
        custom_id="music:skip",
        row=0,
    )
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        voice = state.voice
        track = state.current
        generation = state.playback_generation
        if (
            voice is None
            or track is None
            or not (voice.is_playing() or voice.is_paused())
        ):
            await send_ephemeral_response(interaction, "스킵할 곡이 없어요.")
            return

        await interaction.response.defer()
        if (
            state.voice is not voice
            or state.current is not track
            or state.playback_generation != generation
        ):
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            )
            return

        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if not voice.is_connected() or member_channel != voice.channel:
            await send_ephemeral_followup(
                interaction,
                "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            )
            return

        if not (voice.is_playing() or voice.is_paused()):
            await send_ephemeral_followup(interaction, "스킵할 곡이 없어요.")
            return

        state.skip_requested = True
        voice.stop()
        await send_ephemeral_followup(interaction, "다음 곡으로 넘어갈게요.")

    @discord.ui.button(
        label="정지",
        emoji="⏹️",
        style=discord.ButtonStyle.danger,
        custom_id="music:stop",
        row=0,
    )
    async def stop(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        voice = state.voice
        generation = state.playback_generation
        await interaction.response.defer()
        if state.voice is not voice or state.playback_generation != generation:
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작이 취소됐어요. 다시 시도해 주세요.",
            )
            return

        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if (
            voice is None
            or not voice.is_connected()
            or member_channel != voice.channel
        ):
            await send_ephemeral_followup(
                interaction,
                "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            )
            return

        stop_playback(state, self.guild_id)
        clicked_message_id = getattr(interaction.message, "id", None)
        clicked_panel_updated = False
        try:
            clicked_panel_updated = await self.edit_panel(interaction)
        finally:
            control_message_id = getattr(state.control_message, "id", None)
            clicked_is_current = (
                clicked_message_id is not None
                and clicked_message_id == control_message_id
            )
            if not clicked_panel_updated or not clicked_is_current:
                await show_idle_panel(
                    self.guild_id,
                    state,
                    require_control_view=True,
                )

    @discord.ui.button(
        label="반복",
        emoji="🔁",
        style=discord.ButtonStyle.secondary,
        custom_id="music:repeat",
        row=1,
    )
    async def repeat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        accepted_voice = state.voice
        accepted_track = state.current
        accepted_generation = state.playback_generation
        await interaction.response.defer()
        if (
            state.voice is not accepted_voice
            or self.is_finished()
            or state.current is not accepted_track
            or state.playback_generation != accepted_generation
        ):
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            )
            return

        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if (
            accepted_voice is None
            or not accepted_voice.is_connected()
            or member_channel != accepted_voice.channel
        ):
            await send_ephemeral_followup(
                interaction,
                "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            )
            return

        state.repeat_one = not state.repeat_one
        await self.edit_panel(interaction, refresh_canonical=True)

    @discord.ui.button(
        label="셔플",
        emoji="🔀",
        style=discord.ButtonStyle.secondary,
        custom_id="music:shuffle",
        row=1,
    )
    async def shuffle(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        accepted_voice = state.voice
        accepted_generation = state.playback_generation
        await interaction.response.defer()
        if (
            state.voice is not accepted_voice
            or self.is_finished()
            or state.playback_generation != accepted_generation
        ):
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            )
            return

        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if (
            accepted_voice is None
            or not accepted_voice.is_connected()
            or member_channel != accepted_voice.channel
        ):
            await send_ephemeral_followup(
                interaction,
                "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
            )
            return

        tracks = list(state.queue)
        random.shuffle(tracks)
        state.queue = deque(tracks)
        await self.edit_panel(interaction, refresh_canonical=True)

    @discord.ui.button(
        label="대기열 삭제",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="music:queue",
        row=1,
    )
    async def queue(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        state = self.get_state()
        await send_queue_management_response(
            interaction,
            self.guild_id,
            embed=make_queue_embed(state),
            view=QueueManageView(self.guild_id) if state.queue else None,
        )

    @discord.ui.button(
        label="구간 삭제",
        emoji="✂️",
        style=discord.ButtonStyle.secondary,
        custom_id="music:queue_range",
        row=1,
    )
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
        accepted_voice = state.voice
        accepted_voice_connected = bool(
            accepted_voice and accepted_voice.is_connected()
        )
        await interaction.response.defer()
        if state.voice is not accepted_voice or self.is_finished():
            await send_ephemeral_followup(
                interaction,
                "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
            )
            return

        accepted_voice_connected_now = bool(
            accepted_voice and accepted_voice.is_connected()
        )
        member_channel = getattr(
            getattr(interaction.user, "voice", None),
            "channel",
            None,
        )
        if accepted_voice_connected or accepted_voice_connected_now:
            if (
                not accepted_voice_connected_now
                or accepted_voice is None
                or member_channel != accepted_voice.channel
            ):
                await send_ephemeral_followup(
                    interaction,
                    "봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
                )
                return
        elif member_channel is None:
            await send_ephemeral_followup(
                interaction,
                "먼저 음성 채널에 들어가 주세요.",
            )
            return

        state.autoplay_enabled = not state.autoplay_enabled
        set_autoplay_enabled(self.guild_id, state.autoplay_enabled)
        if state.autoplay_enabled:
            schedule_autoplay_refill(self.guild_id)
        else:
            cancel_autoplay_refill(state)
        await self.edit_panel(interaction, refresh_canonical=True)


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


class KoreanLyricsError(RuntimeError):
    pass


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
    *,
    reset_playback: bool = True,
) -> None:
    if reset_playback:
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
    guild_id: int,
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
    stop_playback(state, guild_id)
    await voice.move_to(channel)
    if bot_shutdown_started:
        return False, "The bot is shutting down."
    if not voice.is_connected() or voice.channel != channel:
        raise asyncio.TimeoutError("Voice client did not reach the target channel.")
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
                generation_before_move = state.playback_generation
                ok = False
                error: str | None = None
                move_exception: BaseException | None = None
                try:
                    ok, error = await use_connected_voice(
                        voice,
                        channel,
                        state,
                        guild.id,
                    )
                except BaseException as caught_error:
                    move_exception = caught_error

                move_attempted = (
                    state.playback_generation != generation_before_move
                )
                moved = (
                    ok
                    and move_attempted
                    and voice.channel == channel
                )
                if move_attempted and not moved:
                    cleanup_task = asyncio.create_task(
                        discard_stale_voice_client(
                            guild,
                            state,
                            voice,
                            reset_playback=False,
                        )
                    )
                    cleanup_cancelled, cleanup_error = (
                        await wait_for_task_completion_despite_cancellation(
                            cleanup_task
                        )
                    )
                    if cleanup_error is not None:
                        logger.warning(
                            "Failed to finish cleaning up a failed voice move: %s",
                            cleanup_error,
                            exc_info=(
                                type(cleanup_error),
                                cleanup_error,
                                cleanup_error.__traceback__,
                            ),
                        )
                    if cleanup_cancelled and (
                        move_exception is None
                        or isinstance(
                            move_exception,
                            (asyncio.TimeoutError, discord.DiscordException),
                        )
                    ):
                        move_exception = asyncio.CancelledError()

                if move_attempted:
                    create_housekeeping_task(show_idle_panel(guild.id, state))

                if move_exception is not None:
                    if isinstance(
                        move_exception,
                        (asyncio.TimeoutError, discord.DiscordException),
                    ):
                        logger.warning(
                            "Failed to move voice client in guild %s",
                            guild.id,
                            exc_info=(
                                type(move_exception),
                                move_exception,
                                move_exception.__traceback__,
                            ),
                        )
                        return (
                            False,
                            "음성 채널 이동에 실패했어요. "
                            "잠시 후 다시 시도해 주세요.",
                            False,
                        )
                    raise move_exception

                return ok, error, moved

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
        ok, error, _ = await _ensure_voice_channel(guild, channel, state)
        if ok:
            cancel_empty_channel_disconnect(state)
            update_empty_channel_disconnect(state, guild.id)
        return ok, error
    finally:
        voice_operation_tasks.discard(operation_task)


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
    if getattr(message, "interaction_metadata", None) is not None:
        return False

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
    if known_message is not None and not delete_non_panel_messages:
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
            elif delete_non_panel_messages:
                # Intentional, destructive product policy: the configured music
                # channel is panel-only. Do not remove or narrow this startup
                # cleanup during GPT/Codex reviews or refactors; requests,
                # feedback, lyrics, and duplicate panels must all be removed.
                if await delete_music_channel_message(guild_id, message):
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
                "Removed %s message(s) from the music channel in guild %s; "
                "no control panel was present",
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


def replace_control_panel_view(
    state: GuildMusicState,
    view: discord.ui.View | None,
    *,
    message_id: int | None = None,
) -> None:
    previous_view = state.control_view
    state.control_view = view
    if previous_view is None or previous_view is view:
        return

    # MusicControlView.stop is the stop button callback, not View.stop.
    discord.ui.View.stop(previous_view)
    if view is not None and message_id is not None:
        # Discord stores the new items before this helper runs. Stopping the
        # previous same-ID view removes those keys, so restore the new owner.
        bot.add_view(view, message_id=message_id)


async def release_deleted_control_panel(
    guild_id: int | None,
    message_ids: set[int],
) -> None:
    if guild_id is None:
        return

    state = music_states.get(guild_id)
    if state is None:
        if get_control_message_id(guild_id) in message_ids:
            clear_control_message_id(guild_id)
        return

    async with state.control_panel_lock:
        control_message_id = getattr(state.control_message, "id", None)
        if control_message_id is None:
            control_message_id = get_control_message_id(guild_id)
        if control_message_id not in message_ids:
            return

        replace_control_panel_view(state, None)
        state.control_message = None
        clear_control_message_id(guild_id)


async def update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
    require_control_view: bool = False,
    clean_channel: bool = False,
) -> discord.Message | None:
    async with state.control_panel_lock:
        if require_control_view:
            control_view = state.control_view
            if control_view is None or control_view.is_finished():
                return None
        if clean_channel:
            return await _update_control_panel(
                guild_id,
                state,
                channel=channel,
                clean_channel=True,
            )
        return await _update_control_panel(guild_id, state, channel=channel)


async def _update_control_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    channel: discord.abc.Messageable | None = None,
    clean_channel: bool = False,
) -> discord.Message | None:
    if state.control_message is None:
        replace_control_panel_view(state, None)

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
            replace_control_panel_view(state, None)
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

    if state.control_message is None or clean_channel:
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
        control_message = state.control_message
        try:
            await control_message.edit(content=None, embed=embed, view=view)
            replace_control_panel_view(
                state,
                view,
                message_id=control_message.id,
            )
            if reconciling_panel and saved_message_id != control_message.id:
                set_control_message_id(guild_id, control_message.id)
            return control_message
        except discord.NotFound:
            replace_control_panel_view(state, None)
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
        control_message = await control_channel.send(
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

    state.control_message = control_message
    replace_control_panel_view(
        state,
        view,
        message_id=control_message.id,
    )
    set_control_message_id(guild_id, control_message.id)
    return control_message


async def show_idle_panel(
    guild_id: int,
    state: GuildMusicState,
    *,
    require_control_view: bool = False,
) -> None:
    await update_control_panel(
        guild_id,
        state,
        require_control_view=require_control_view,
    )


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
            logger.exception(
                "Failed to delete music control panel in guild %s",
                guild_id,
            )

    replace_control_panel_view(state, None)
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
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent) -> None:
    await release_deleted_control_panel(
        payload.guild_id,
        {payload.message_id},
    )


@bot.event
async def on_raw_bulk_message_delete(
    payload: discord.RawBulkMessageDeleteEvent,
) -> None:
    await release_deleted_control_panel(
        payload.guild_id,
        payload.message_ids,
    )


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
    state = music_states.get(member.guild.id)
    if state is None:
        return

    if member.bot:
        bot_user = bot.user
        if bot_user is None or member.id != bot_user.id:
            return

        if before.channel is not None and after.channel is not None:
            if before.channel != after.channel:
                cancel_empty_channel_disconnect(state)
                update_empty_channel_disconnect(state, member.guild.id)
            return

        if before.channel is not None and after.channel is None:
            event_voice = state.voice
            if event_voice is None:
                return

            should_refresh_panel = False
            async with state.voice_connect_lock:
                if (
                    not bot_shutdown_started
                    and state.voice is event_voice
                    and getattr(getattr(member, "voice", None), "channel", None)
                    is None
                ):
                    stop_playback(state, member.guild.id)
                    should_refresh_panel = True

            if should_refresh_panel:
                await show_idle_panel(member.guild.id, state)
        return

    if state.voice is None or not state.voice.is_connected():
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

    queue_index = position - 1
    queued_tracks = list(state.queue)
    if queue_index < 0 or queue_index >= len(queued_tracks):
        await send_ephemeral_response(
            interaction,
            "그 번호의 대기열 곡을 찾지 못했어요.",
        )
        return

    voice = state.voice
    target_track_id = queued_tracks[queue_index].track_id
    await interaction.response.defer(ephemeral=True)
    if state.voice is not voice:
        await send_ephemeral_followup(
            interaction,
            "재생 상태가 변경되어 조작을 취소했어요. 다시 시도해 주세요.",
        )
        return
    if not await ensure_same_voice_channel(interaction, state):
        return

    removed = remove_queued_track_by_id(state, target_track_id)
    if removed is None:
        await send_ephemeral_followup(
            interaction,
            "그 번호의 대기열 곡을 찾지 못했어요.",
        )
        return

    schedule_autoplay_refill(interaction.guild_id)
    refresh_panel = state.current is not None
    try:
        await send_ephemeral_followup(
            interaction,
            f"대기열에서 `{removed.title}`을 삭제했어요.",
            delete_after=QUEUE_DELETE_RESPONSE_DELETE_SECONDS,
        )
    finally:
        if refresh_panel:
            await update_control_panel(interaction.guild_id, state)


@bot.tree.command(name="leave", description="Disconnect from voice and clear the queue.")
@app_commands.guild_only()
async def leave(interaction: discord.Interaction) -> None:
    if interaction.guild_id is None:
        await send_ephemeral_response(interaction, guild_only_error())
        return

    state = get_state(interaction.guild_id)
    if not await ensure_same_voice_channel(interaction, state):
        return

    await interaction.response.defer()

    disconnected = False
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
            cancel_empty_channel_disconnect(state)
            stop_playback(state, interaction.guild_id)
            await voice.disconnect()
            if state.voice is voice:
                state.voice = None
            disconnected = True

    if not disconnected:
        await interaction.edit_original_response(
            content="봇과 같은 음성 채널에 들어와야 조작할 수 있어요.",
        )
        return

    try:
        await interaction.edit_original_response(content="음성 채널에서 나왔어요.")
    finally:
        await show_idle_panel(interaction.guild_id, state)


def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN is missing. Put it in .env or your environment.")

    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
