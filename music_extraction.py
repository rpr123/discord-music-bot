from __future__ import annotations

import asyncio
import copy
import functools
import threading
import time
import unicodedata
import uuid
from collections import OrderedDict

import requests
from ytmusicapi import YTMusic
from ytmusicapi.auth.oauth import OAuthCredentials

from music_autoplay_logging import describe_autoplay_track, log_autoplay_event
from music_config import (
    AUTOPLAY_MIN_INTERVAL_SECONDS,
    DEFAULT_AUTO_TRACKS,
    MAX_AUTO_TRACKS,
    MAX_BULK_TRACKS,
    STREAM_URL_MAX_AGE_SECONDS,
    YOUTUBE_MUSIC_AUTH_FILE,
    YOUTUBE_MUSIC_LANGUAGE,
    YOUTUBE_MUSIC_LOCATION,
    YOUTUBE_MUSIC_MIN_INTERVAL_SECONDS,
    YOUTUBE_MUSIC_OAUTH_CLIENT_ID,
    YOUTUBE_MUSIC_OAUTH_CLIENT_SECRET,
    YOUTUBE_MUSIC_SEARCH_ENABLED,
    YOUTUBE_MUSIC_SEARCH_TIMEOUT_SECONDS,
    YOUTUBE_SEARCH_CANDIDATES,
    YTDL_CACHE_MAX_ENTRIES,
    YTDL_CACHE_TTL_SECONDS,
    YTDL_EXTRACT_TIMEOUT_SECONDS,
    YTDL_OPTIONS,
    YTDL_PLAYLIST_OPTIONS,
    YTDL_SEARCH_OPTIONS,
    logger,
    resolve_project_path,
)
from music_models import Track, invalidate_track_stream
from music_request_parsing import (
    clamp_auto_count as clamp_auto_count_with_limit,
    get_playlist_result_url,
    is_playlist_search_url,
    is_youtube_search_query,
    parse_auto_request as parse_auto_request_with_policy,
)
from music_search_scoring import (
    build_youtube_search_query,
    get_version_style_intents,
    get_youtube_music_artist_hint,
    infer_youtube_search_song_title,
    rank_autoplay_candidates,
    resolve_query,
    select_youtube_music_song_result,
    select_youtube_search_result,
    should_use_youtube_music_search,
)
from music_track_metadata import (
    get_audio_codec,
    get_manual_subtitles,
    get_resolved_stream_url,
    get_thumbnail_url,
    get_track_identity_keys,
    get_track_video_id,
    get_video_id,
    make_track_from_info,
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
extraction_shutdown_started = False


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


def begin_extraction_shutdown() -> None:
    global extraction_shutdown_started
    extraction_shutdown_started = True
    begin_auxiliary_worker_shutdown()


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
    job_kind: YtdlJobKind,
    use_cache: bool = True,
    minimum_interval_seconds: float | None = None,
) -> dict:
    if extraction_shutdown_started:
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
    if extraction_shutdown_started:
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
    if extraction_shutdown_started:
        raise asyncio.CancelledError
    operation_task = track_auxiliary_operation()
    try:
        return await _search_youtube_music_operation(query)
    finally:
        auxiliary_operation_tasks.discard(operation_task)


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
    style_query: str | None = None,
) -> list[Track]:
    auto_count = clamp_auto_count(count)
    if auto_count == 1:
        return [seed_track]

    search_id = uuid.uuid4().hex
    search_candidates: list[dict] = []
    search_limit = get_autoplay_search_limit(auto_count, job_kind)
    autoplay_request_kwargs = (
        {"minimum_interval_seconds": AUTOPLAY_MIN_INTERVAL_SECONDS}
        if job_kind == YtdlJobKind.AUTOPLAY
        else {}
    )
    style_intents = set(get_version_style_intents(seed_track.title))
    if style_query:
        style_intents.update(get_version_style_intents(style_query))
    frozen_style_intents = frozenset(style_intents)

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
                **autoplay_request_kwargs,
            )
            entries = [entry for entry in radio_info.get("entries", []) if entry]
        except Exception:
            logger.exception("Failed to extract YouTube radio mix for %s", seed_track.title)
            if job_kind == YtdlJobKind.AUTOPLAY:
                raise

    if not entries and (job_kind != YtdlJobKind.AUTOPLAY or radio_url is None):
        search_query = f"ytsearch{search_limit}:{seed_track.title} radio mix"
        fallback_url = search_query
        info = await extract_ytdl_info(
            YTDL_SEARCH_OPTIONS,
            search_query,
            "auto fallback search",
            job_kind=job_kind,
            **autoplay_request_kwargs,
        )
        entries = [entry for entry in info.get("entries", []) if entry]

    entry_batches = [(entries, fallback_url)]

    def build_ranked_tracks(
        batches: list[tuple[list[dict], str]],
    ) -> tuple[list[Track], list[tuple[Track, int, int]]]:
        search_candidates.clear()
        tracks = [seed_track]
        seen_keys = get_track_identity_keys(seed_track)
        ranked_entries: list[tuple[dict, int, int, int, str]] = []
        for batch_index, (candidate_entries, source_url) in enumerate(batches):
            ranked_entries.extend(
                (entry, score, source_index, batch_index, source_url)
                for entry, score, source_index in rank_autoplay_candidates(
                    candidate_entries,
                    style_intents=frozen_style_intents,
                )
            )
        ranked_entries.sort(
            key=lambda candidate: (-candidate[1], candidate[3], candidate[2])
        )

        ranked_track_details: list[tuple[Track, int, int]] = []
        for entry, score, source_index, batch_index, source_url in ranked_entries:
            track = make_track_from_info(entry, requester, source_url, requester_id)
            video_id = get_video_id(entry, track.webpage_url)
            record = {
                "batch_index": batch_index,
                "source_index": source_index,
                "video_id": video_id,
                "title": track.title,
                "quality_score": score,
                "scoring_input": {
                    key: entry.get(key) for key in (
                        "title", "artist", "creator", "channel", "uploader",
                        "duration", "is_live", "is_upcoming", "live_status",
                    )
                },
            }
            search_candidates.append(record)
            identity_keys = get_track_identity_keys(track)
            if not video_id:
                record["status"] = "invalid_video_id"
                continue
            if not seen_keys.isdisjoint(identity_keys):
                record["status"] = "seed_or_duplicate"
                continue
            if (
                job_kind == YtdlJobKind.AUTOPLAY
                and "cover" not in frozen_style_intents
                and "cover" in get_version_style_intents(
                    str(entry.get("title") or "")
                )
            ):
                record["status"] = "cover_excluded"
                continue
            if len(tracks) >= auto_count:
                record["status"] = "candidate_limit"
                continue
            seen_keys.update(identity_keys)
            setattr(track, "_autoplay_score", score)
            setattr(track, "_autoplay_source_index", source_index)
            setattr(track, "_autoplay_search_id", search_id)
            record.update(status="candidate", track_id=track.track_id)
            tracks.append(track)
            ranked_track_details.append((track, score, source_index))
        return tracks, ranked_track_details

    tracks, ranked_track_details = build_ranked_tracks(entry_batches)

    if (
        job_kind != YtdlJobKind.AUTOPLAY
        and len(tracks) < auto_count
        and fallback_url.startswith("https://www.youtube.com/watch")
    ):
        search_query = f"ytsearch{search_limit}:{seed_track.title} radio mix"
        info = await extract_ytdl_info(
            YTDL_SEARCH_OPTIONS,
            search_query,
            "auto supplemental search",
            job_kind=job_kind,
        )
        supplemental_entries = [entry for entry in info.get("entries", []) if entry]
        entry_batches.append((supplemental_entries, search_query))
        tracks, ranked_track_details = build_ranked_tracks(entry_batches)

    fetched_entry_count = sum(
        len(candidate_entries) for candidate_entries, _ in entry_batches
    )

    log_autoplay_event(
        "search_results",
        search_id=search_id,
        job_kind=job_kind.name,
        seed=describe_autoplay_track(seed_track),
        requested_count=auto_count,
        sources=[source for _, source in entry_batches],
        style_intents=sorted(frozen_style_intents),
        candidates=search_candidates,
    )

    logger.debug(
        "Autoplay ranking for %s: styles=%s fetched=%s valid=%s top=%s",
        seed_track.title,
        sorted(frozen_style_intents),
        fetched_entry_count,
        len(ranked_track_details),
        [
            (track.title, score, source_index)
            for track, score, source_index in ranked_track_details[:5]
        ],
    )

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
        style_query=query,
    )
