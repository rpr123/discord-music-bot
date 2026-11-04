"""Play YouTube through the bot's playback and autoplay code without Discord.

The listener requests one song, then lets the bot's own autoplay keep the
queue filled. Audio is read at playback speed through the same FFmpeg
pipeline, so YouTube sees the traffic a real listening session makes.
It pauses while the real bot is playing and stops when YouTube blocks.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
# Keep the real bot's autoplay history separate from synthetic sessions.
os.environ.setdefault("AUTOPLAY_LOG_FILE", "logs/synthetic-autoplay.jsonl")

import bot as music_bot  # noqa: E402
import music_ytdl  # noqa: E402
from music_config import logger  # noqa: E402

GUILD_ID = 1
FRAME_SECONDS = 0.02
CONSOLE_LOG = PROJECT_DIR / "logs" / "console.log"
REAL_BOT_IDLE_SECONDS = 10 * 60
PLAYBACK_TITLE_RE = re.compile(r"Playback start: title=(.+?) codec=")
LOG_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


class FakeVoice:
    """Stand-in for discord.VoiceClient that reads audio like its player."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def is_connected(self) -> bool:
        return True

    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        return False

    def play(self, source, *, after) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(source, after),
            name="synthetic-player",
            daemon=True,
        )
        self._thread.start()

    def _run(self, source, after) -> None:
        # Mirrors discord.py 2.7 AudioPlayer: FFmpeg exit errors reach `after`,
        # so a failed stream is retried the way the real bot retries it.
        error: Exception | None = None
        started_at = time.perf_counter()
        frames = 0
        try:
            while not self._stop.is_set():
                if not source.read():
                    error = getattr(source, "_current_error", None)
                    break
                frames += 1
                next_time = started_at + FRAME_SECONDS * frames
                time.sleep(max(0, FRAME_SECONDS + (next_time - time.perf_counter())))
        except Exception as exc:
            error = exc
        finally:
            after(error)
            source.cleanup()

    def stop(self) -> None:
        self._stop.set()

    async def disconnect(self, *, force: bool = False) -> None:
        self.stop()


async def do_nothing(*args, **kwargs) -> None:
    return None


LYRICS_SEARCHING = "가사를 찾고 있어요..."


async def log_lyrics_result(
    guild_id, state, track, description: str, *, attachment_lyrics=None
) -> None:
    # Stands in for the Discord lyrics message so each lookup's outcome is kept.
    if description == LYRICS_SEARCHING:
        return
    lyrics = track.lyrics or ""
    logger.info(
        "Synthetic lyrics result: found=%s source=%s lines=%s title=%s",
        "yes" if lyrics else "no",
        track.lyrics_source or "-",
        len(lyrics.splitlines()),
        track.title,
    )


def last_real_playback_at() -> float | None:
    try:
        with CONSOLE_LOG.open("rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - 256 * 1024))
            lines = log.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if "Playback start:" not in line:
            continue
        match = LOG_TIME_RE.match(line)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    return None


def real_bot_is_playing() -> bool:
    played_at = last_real_playback_at()
    return played_at is not None and time.time() - played_at < REAL_BOT_IDLE_SECONDS


def youtube_is_blocked() -> bool:
    # The circuit only opens on block and rate-limit errors.
    return music_ytdl.youtube_circuit_open_until > time.monotonic()


def pick_seed_title() -> str:
    titles: list[str] = []
    for path in sorted((PROJECT_DIR / "logs").glob("console*.log")):
        text = path.read_text(encoding="utf-8", errors="replace")
        titles.extend(PLAYBACK_TITLE_RE.findall(text))
    if not titles:
        raise SystemExit("No past playback titles were found to use as a seed.")
    return random.choice(titles)


def install() -> None:
    music_bot.bot = MagicMock()
    music_bot.bot.loop = asyncio.get_running_loop()
    music_bot.upsert_lyrics_message = log_lyrics_result
    for name in (
        "clear_lyrics_message",
        "update_control_panel",
        "show_idle_panel",
        "notify_playback_error",
    ):
        setattr(music_bot, name, do_nothing)
    music_bot.update_idle_voice_disconnect = lambda *args: None

    resolve_track_stream = music_bot.resolve_track_stream

    async def resolve_when_real_bot_is_idle(track) -> None:
        # Both processes share the VM's IP; let the real bot have it alone.
        while real_bot_is_playing():
            logger.info("Synthetic listener waiting: the real bot is playing")
            await asyncio.sleep(60)
        await resolve_track_stream(track)

    music_bot.resolve_track_stream = resolve_when_real_bot_is_idle


async def request_song(state, title: str) -> None:
    logger.info("Synthetic listener request: %s", title)
    track = await music_bot.extract_track(title, "synthetic")
    async with state.lock:
        state.queue.append(track)


async def run(hours: float, requests: int) -> int:
    install()
    while real_bot_is_playing():
        logger.info("Synthetic listener waiting: the real bot is playing")
        await asyncio.sleep(60)

    state = music_bot.get_state(GUILD_ID)
    state.voice = FakeVoice()
    state.autoplay_enabled = True

    loop = asyncio.get_running_loop()
    ends_at = loop.time() + hours * 3600
    request_interval = hours * 3600 / max(1, requests)
    next_request_at = loop.time()
    exit_code = 0
    logger.info(
        "Synthetic listener session start: hours=%s requests=%s",
        hours,
        requests,
    )
    try:
        while loop.time() < ends_at:
            if youtube_is_blocked():
                logger.error(
                    "Synthetic listener stopped: YouTube blocked requests: %s",
                    music_ytdl.youtube_circuit_reason,
                )
                exit_code = 2
                break
            if loop.time() >= next_request_at and not real_bot_is_playing():
                next_request_at += request_interval
                try:
                    await request_song(state, pick_seed_title())
                except Exception as error:
                    logger.warning("Synthetic listener request failed: %s", error)
                music_bot.schedule_play_next(GUILD_ID)
            if state.current is None and state.queue:
                music_bot.schedule_play_next(GUILD_ID)
            await asyncio.sleep(30)
    finally:
        state.playback_generation += 1
        state.voice.stop()
        music_bot.begin_bot_shutdown()
        await music_bot.shutdown_auxiliary_operations()
        await music_bot.shutdown_auxiliary_workers()
        logger.info("Synthetic listener session end")
    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=10.0)
    parser.add_argument(
        "--requests",
        type=int,
        default=2,
        help="songs requested by name over the session; autoplay fills the rest",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sys.exit(asyncio.run(run(args.hours, args.requests)))


if __name__ == "__main__":
    main()
