from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

import discord
from discord.opus import OPUS_SILENCE

from music_config import logger


# discord.py sends one 20 ms Opus frame per read() and, after a late read,
# sends the missed frames back to back. Listeners hear that burst as a speed
# change, so frames are read ahead and handed out on a steady clock instead.
AUDIO_FRAME_SECONDS = 0.02
AUDIO_BUFFER_MAX_SECONDS = 10.0
# Wait for this much audio before starting, and again after running dry.
AUDIO_PREBUFFER_SECONDS = 2.0
# A frame later than this restarts the clock instead of catching up.
AUDIO_RESYNC_LATE_SECONDS = 0.06

AUDIO_BUFFER_MAX_FRAMES = round(AUDIO_BUFFER_MAX_SECONDS / AUDIO_FRAME_SECONDS)
AUDIO_PREBUFFER_FRAMES = round(AUDIO_PREBUFFER_SECONDS / AUDIO_FRAME_SECONDS)


class BufferedOpusAudio(discord.AudioSource):
    """Read an Opus source ahead and send it like a streaming player.

    While the buffer is filling, silence is sent so the voice stream stays
    continuous; playback resumes where it stopped once enough audio is ready.
    """

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        label: str,
        clock: Callable[[], float] = time.perf_counter,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._source = source
        self._label = label
        self._clock = clock
        self._sleep = sleep
        self._frames: deque[bytes] = deque()
        self._condition = threading.Condition()
        self._reader: threading.Thread | None = None
        self._source_finished = False
        self._reader_error: Exception | None = None
        self._closed = False
        self._buffering = True
        self._started = False
        self._buffering_started_at = 0.0
        self._next_frame_at: float | None = None

    @property
    def _current_error(self) -> Exception | None:
        # discord.py reports this when read() ends, e.g. FFmpeg exit codes.
        return self._reader_error or getattr(self._source, "_current_error", None)

    def read(self) -> bytes:
        self._start_reader()
        self._wait_for_frame_slot()
        with self._condition:
            if self._buffering:
                if (
                    len(self._frames) < AUDIO_PREBUFFER_FRAMES
                    and not self._source_finished
                ):
                    return OPUS_SILENCE
                self._finish_buffering()
            if self._frames:
                frame = self._frames.popleft()
                self._condition.notify_all()
                return frame
            if self._source_finished:
                if self._reader_error is not None:
                    raise self._reader_error
                return b""
            self._buffering = True
            self._buffering_started_at = self._clock()
            return OPUS_SILENCE

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        with self._condition:
            self._closed = True
            self._frames.clear()
            self._condition.notify_all()
        self._source.cleanup()

    def _start_reader(self) -> None:
        # Started on the first read so an unplayed source leaves no thread.
        if self._reader is not None:
            return
        self._buffering_started_at = self._clock()
        self._reader = threading.Thread(
            target=self._fill,
            name=f"audio-buffer:{id(self):#x}",
            daemon=True,
        )
        self._reader.start()

    def _fill(self) -> None:
        while True:
            with self._condition:
                while (
                    len(self._frames) >= AUDIO_BUFFER_MAX_FRAMES
                    and not self._closed
                ):
                    self._condition.wait()
                if self._closed:
                    return
            error: Exception | None = None
            try:
                frame = self._source.read()
            except Exception as read_error:
                frame = b""
                error = read_error
            with self._condition:
                if self._closed:
                    return
                if frame:
                    self._frames.append(frame)
                else:
                    self._source_finished = True
                    self._reader_error = error
                self._condition.notify_all()
            if not frame:
                return

    def _wait_for_frame_slot(self) -> None:
        now = self._clock()
        if (
            self._next_frame_at is None
            or now - self._next_frame_at > AUDIO_RESYNC_LATE_SECONDS
        ):
            self._next_frame_at = now
        elif now < self._next_frame_at:
            self._sleep(self._next_frame_at - now)
        self._next_frame_at += AUDIO_FRAME_SECONDS

    def _finish_buffering(self) -> None:
        self._buffering = False
        if self._started:
            logger.info(
                "Audio buffer ran dry for %.1fs: %s",
                self._clock() - self._buffering_started_at,
                self._label,
            )
        self._started = True
