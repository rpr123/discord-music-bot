import ast
import queue
import threading
import time
import unittest
from pathlib import Path

import music_audio_buffer as audio_buffer
from music_audio_buffer import OPUS_SILENCE, BufferedOpusAudio


END = object()


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


class FakeOpusSource:
    """Hands out frames pushed by the test, blocking like an FFmpeg pipe."""

    def __init__(self) -> None:
        self.pending: queue.Queue = queue.Queue()
        self.reads = 0
        self.cleaned_up = False
        self._current_error = None

    def push(self, *frames: object) -> None:
        for frame in frames:
            self.pending.put(frame)

    def read(self) -> bytes:
        self.reads += 1
        frame = self.pending.get()
        if frame is END:
            return b""
        if isinstance(frame, Exception):
            raise frame
        return frame

    def is_opus(self) -> bool:
        return True

    def cleanup(self) -> None:
        self.cleaned_up = True
        self.pending.put(END)


def frames(count: int, prefix: str = "f") -> list[bytes]:
    return [f"{prefix}{index}".encode() for index in range(count)]


class BufferedOpusAudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.inner = FakeOpusSource()
        self.audio = BufferedOpusAudio(
            self.inner,
            label="test song",
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        self.addCleanup(self.audio.cleanup)

    def wait_until(self, condition) -> None:
        deadline = time.monotonic() + 2
        while not condition():
            if time.monotonic() > deadline:
                self.fail("buffer did not reach the expected state")
            time.sleep(0.001)

    def buffered(self) -> int:
        return len(self.audio._frames)

    def read_frames(self, count: int) -> list[bytes]:
        return [self.audio.read() for _ in range(count)]

    def test_waits_for_prebuffer_with_silence_then_plays_in_order(self) -> None:
        prebuffer = audio_buffer.AUDIO_PREBUFFER_FRAMES
        self.assertEqual(self.audio.read(), OPUS_SILENCE)
        self.inner.push(*frames(prebuffer - 1))
        self.wait_until(lambda: self.buffered() == prebuffer - 1)
        self.assertEqual(self.audio.read(), OPUS_SILENCE)

        self.inner.push(*frames(1, "last"), END)
        self.wait_until(lambda: self.audio._source_finished)

        self.assertEqual(
            self.read_frames(prebuffer),
            frames(prebuffer - 1) + frames(1, "last"),
        )
        self.assertEqual(self.audio.read(), b"")
        self.assertIsNone(self.audio._current_error)

    def test_short_track_starts_as_soon_as_the_source_ends(self) -> None:
        self.assertEqual(self.audio.read(), OPUS_SILENCE)
        self.inner.push(*frames(3), END)
        self.wait_until(lambda: self.audio._source_finished)

        self.assertEqual(self.read_frames(4), frames(3) + [b""])

    def test_running_dry_pauses_with_silence_until_prebuffer_refills(self) -> None:
        prebuffer = audio_buffer.AUDIO_PREBUFFER_FRAMES
        self.audio.read()
        self.inner.push(*frames(prebuffer))
        self.wait_until(lambda: self.buffered() == prebuffer)
        self.read_frames(prebuffer)

        with self.assertLogs("music-bot", level="INFO") as logs:
            self.assertEqual(self.audio.read(), OPUS_SILENCE)
            self.inner.push(*frames(prebuffer - 1, "r"))
            self.wait_until(lambda: self.buffered() == prebuffer - 1)
            self.assertEqual(self.audio.read(), OPUS_SILENCE)
            self.inner.push(*frames(1, "rlast"))
            self.wait_until(lambda: self.buffered() == prebuffer)
            self.assertEqual(self.audio.read(), b"r0")

        self.assertIn("ran dry", "\n".join(logs.output))
        self.assertIn("test song", "\n".join(logs.output))

    def test_frames_are_paced_and_late_reads_restart_the_clock(self) -> None:
        frame = audio_buffer.AUDIO_FRAME_SECONDS
        self.audio.read()
        self.inner.push(*frames(200))
        self.wait_until(lambda: self.buffered() >= 150)

        # discord.py calls read() back to back when it is behind schedule.
        self.read_frames(5)
        self.assertEqual(self.clock.sleeps, [frame] * 5)

        self.clock.sleeps.clear()
        self.clock.now += 0.5
        self.read_frames(4)
        # No burst of missed frames: one immediate frame, then 20 ms steps.
        self.assertEqual(self.clock.sleeps, [frame] * 3)

    def test_reads_ahead_only_up_to_the_buffer_limit(self) -> None:
        limit = audio_buffer.AUDIO_BUFFER_MAX_FRAMES
        self.audio.read()
        self.inner.push(*frames(limit + 50))
        self.wait_until(lambda: self.buffered() == limit)
        time.sleep(0.05)

        self.assertEqual(self.buffered(), limit)
        self.assertEqual(self.inner.reads, limit)

    def test_source_errors_surface_after_buffered_audio(self) -> None:
        failure = RuntimeError("bad ogg page")
        self.audio.read()
        self.inner.push(*frames(2), failure)
        self.wait_until(lambda: self.audio._source_finished)

        self.assertEqual(self.read_frames(2), frames(2))
        with self.assertRaises(RuntimeError):
            self.audio.read()
        self.assertIs(self.audio._current_error, failure)

    def test_ffmpeg_exit_error_is_forwarded_to_discord_player(self) -> None:
        self.inner._current_error = RuntimeError("FFmpeg exited with code 1")
        self.audio.read()
        self.inner.push(END)
        self.wait_until(lambda: self.audio._source_finished)

        self.assertEqual(self.audio.read(), b"")
        self.assertIs(self.audio._current_error, self.inner._current_error)

    def test_cleanup_stops_the_reader_and_the_source(self) -> None:
        self.audio.read()
        reader = self.audio._reader

        self.audio.cleanup()
        reader.join(timeout=2)

        self.assertFalse(reader.is_alive())
        self.assertTrue(self.inner.cleaned_up)

    def test_unplayed_source_starts_no_reader_thread(self) -> None:
        before = threading.active_count()
        audio = BufferedOpusAudio(FakeOpusSource(), label="unused")

        self.assertIsNone(audio._reader)
        self.assertEqual(threading.active_count(), before)
        self.assertTrue(audio.is_opus())

    def test_module_has_only_the_expected_import_dependencies(self) -> None:
        tree = ast.parse(Path(audio_buffer.__file__).read_text(encoding="utf-8"))
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )

        self.assertEqual(
            imported_modules,
            {
                "__future__",
                "collections",
                "discord",
                "discord.opus",
                "music_config",
                "threading",
                "time",
                "typing",
            },
        )


if __name__ == "__main__":
    unittest.main()
