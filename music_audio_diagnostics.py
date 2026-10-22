from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Callable

import discord

from music_config import (
    AUDIO_LAG_LOG_ENABLED,
    AUDIO_LAG_LOG_FILE,
    AUDIO_LAG_THRESHOLD_MS,
    logger,
)


# discord.py sends one 20 ms Opus frame per read() and bursts frames to catch
# up after a late read, which listeners hear as stutter or a speed change.
AUDIO_FRAME_SECONDS = 0.02
AUDIO_LAG_LOG_MAX_BYTES = 1024 * 1024
AUDIO_LAG_LOG_BACKUP_COUNT = 3
AUDIO_LAG_LOG_SUPPRESS_SECONDS = 1.0
CPU_SAMPLE_INTERVAL_SECONDS = 1.0
PROC_STAT_PATH = "/proc/stat"
PROC_MEMINFO_PATH = "/proc/meminfo"

CpuTimes = tuple[int, ...]

_handler: RotatingFileHandler | None = None
_write_failed = False


def log_audio_lag_event(event: str, **details: object) -> None:
    """Write bounded JSONL diagnostics without interrupting playback."""
    global _handler, _write_failed
    if not AUDIO_LAG_LOG_ENABLED:
        return
    try:
        message = json.dumps(
            {
                "schema_version": 1,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **details,
            },
            ensure_ascii=False,
        )
        if _handler is None:
            AUDIO_LAG_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            _handler = RotatingFileHandler(
                AUDIO_LAG_LOG_FILE,
                maxBytes=AUDIO_LAG_LOG_MAX_BYTES,
                backupCount=AUDIO_LAG_LOG_BACKUP_COUNT,
                encoding="utf-8",
                delay=True,
            )
            _handler.setFormatter(logging.Formatter("%(message)s"))
        _handler.handle(logging.LogRecord(
            "audio-lag-diagnostics", logging.INFO, __file__, 0, message, (), None,
        ))
    except (OSError, ValueError, TypeError):
        if not _write_failed:
            logger.warning("Could not write audio lag diagnostics", exc_info=True)
            _write_failed = True


def read_cpu_times(path: str = PROC_STAT_PATH) -> CpuTimes | None:
    # user nice system idle iowait irq softirq steal; None off Linux.
    try:
        with open(path, encoding="ascii") as stat_file:
            fields = stat_file.readline().split()
    except OSError:
        return None
    if len(fields) < 9 or fields[0] != "cpu":
        return None
    try:
        return tuple(int(value) for value in fields[1:9])
    except ValueError:
        return None


def describe_cpu_window(
    before: CpuTimes,
    after: CpuTimes,
    window_seconds: float,
) -> dict | None:
    deltas = [max(0, end - start) for start, end in zip(before, after)]
    total = sum(deltas)
    if total <= 0:
        return None
    user, nice, system, idle, iowait, irq, softirq, steal = deltas

    def percent(value: int) -> float:
        return round(value * 100 / total, 1)

    return {
        "window_seconds": round(window_seconds, 2),
        "busy_percent": percent(user + nice + system + irq + softirq),
        "idle_percent": percent(idle),
        "iowait_percent": percent(iowait),
        "steal_percent": percent(steal),
    }


def read_mem_available_mb(path: str = PROC_MEMINFO_PATH) -> int | None:
    try:
        with open(path, encoding="ascii") as meminfo_file:
            for line in meminfo_file:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_load_average() -> float | None:
    try:
        return round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        return None


class LagMonitoredAudioSource(discord.AudioSource):
    """Log late frame reads with the server state at that moment."""

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        title: str,
        get_ytdl_job_kinds: Callable[[], tuple[str, ...]] = tuple,
        clock: Callable[[], float] = time.perf_counter,
        read_cpu: Callable[[], CpuTimes | None] = read_cpu_times,
    ) -> None:
        self._source = source
        self._title = title
        self._get_ytdl_job_kinds = get_ytdl_job_kinds
        self._clock = clock
        self._read_cpu = read_cpu
        self._threshold_seconds = AUDIO_LAG_THRESHOLD_MS / 1000
        self._frames = 0
        self._last_read_started: float | None = None
        self._last_read_seconds = 0.0
        self._last_logged_at: float | None = None
        self._suppressed = 0
        # Two samples about a second apart so a late frame can be compared
        # with CPU usage over the window that contains it.
        self._older_cpu: tuple[float, CpuTimes] | None = None
        self._newer_cpu: tuple[float, CpuTimes] | None = None

    def read(self) -> bytes:
        started = self._clock()
        if AUDIO_LAG_LOG_ENABLED:
            if self._last_read_started is not None:
                late = started - self._last_read_started - AUDIO_FRAME_SECONDS
                if late >= self._threshold_seconds:
                    self._record_lag(started, late)
            self._sample_cpu(started)
        self._last_read_started = started
        data = self._source.read()
        self._last_read_seconds = self._clock() - started
        self._frames += 1
        return data

    def reset_timing(self) -> None:
        # The gap across a pause is intentional, not a late frame.
        self._last_read_started = None

    def is_opus(self) -> bool:
        return self._source.is_opus()

    def cleanup(self) -> None:
        self._source.cleanup()

    def _sample_cpu(self, now: float) -> None:
        if (
            self._newer_cpu is not None
            and now - self._newer_cpu[0] < CPU_SAMPLE_INTERVAL_SECONDS
        ):
            return
        times = self._read_cpu()
        if times is None:
            return
        self._older_cpu = self._newer_cpu
        self._newer_cpu = (now, times)

    def _record_lag(self, now: float, late: float) -> None:
        if (
            self._last_logged_at is not None
            and now - self._last_logged_at < AUDIO_LAG_LOG_SUPPRESS_SECONDS
        ):
            self._suppressed += 1
            return
        source_wait = self._last_read_seconds
        cpu = None
        baseline = self._older_cpu or self._newer_cpu
        current_cpu = self._read_cpu() if baseline is not None else None
        if baseline is not None and current_cpu is not None:
            cpu = describe_cpu_window(baseline[1], current_cpu, now - baseline[0])
        try:
            ytdl_job_kinds = list(self._get_ytdl_job_kinds())
        except Exception:
            ytdl_job_kinds = None
        log_audio_lag_event(
            "audio_lag",
            title=self._title,
            position_seconds=round(self._frames * AUDIO_FRAME_SECONDS, 1),
            late_ms=round(late * 1000),
            source_wait_ms=round(source_wait * 1000),
            # A late frame mostly spent waiting on FFmpeg means the YouTube
            # stream stalled; otherwise the sending thread did not get to run.
            cause_hint="stream" if source_wait >= late / 2 else "scheduling",
            suppressed_since_last=self._suppressed,
            cpu=cpu,
            mem_available_mb=read_mem_available_mb(),
            load_1m=read_load_average(),
            ytdl_workers=ytdl_job_kinds,
        )
        self._last_logged_at = now
        self._suppressed = 0


def reset_audio_lag_timing(source: object) -> None:
    if isinstance(source, LagMonitoredAudioSource):
        source.reset_timing()
