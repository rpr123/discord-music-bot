from __future__ import annotations

import asyncio
import copy
import json
import math
import os
import signal
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable

from music_config import (
    YOUTUBE_CIRCUIT_BREAKER_SECONDS,
    YTDL_CACHE_MAX_ENTRIES,
    YTDL_CACHE_TTL_SECONDS,
    YTDL_MAX_CONCURRENT_EXTRACTIONS,
    YTDL_MIN_INTERVAL_SECONDS,
    YTDL_WORKER_PATH,
    logger,
)

ytdl_rate_lock = asyncio.Lock()
ytdl_cache_lock = asyncio.Lock()
ytdl_cache: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()
ytdl_last_request_started_at = 0.0
youtube_circuit_open_until = 0.0
youtube_circuit_reason: str | None = None

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
