import asyncio
import threading
import unittest
from types import SimpleNamespace

from devtools import synthetic_listener


class FakeSource:
    def __init__(self, frames: int, error: Exception | None = None) -> None:
        self.frames = frames
        self._current_error = error
        self.cleaned_up = False

    def read(self) -> bytes:
        if self.frames == 0:
            return b""
        self.frames -= 1
        return b"frame"

    def cleanup(self) -> None:
        self.cleaned_up = True


class FakeVoiceTests(unittest.TestCase):
    def play(self, source: FakeSource) -> list[Exception | None]:
        voice = synthetic_listener.FakeVoice()
        finished = threading.Event()
        errors: list[Exception | None] = []

        def after(error: Exception | None) -> None:
            errors.append(error)
            finished.set()

        voice.play(source, after=after)
        self.assertTrue(finished.wait(2))
        voice._thread.join(2)
        self.assertFalse(voice.is_playing())
        return errors

    def test_source_error_reaches_after_like_discord_player(self) -> None:
        error = RuntimeError("FFmpeg exited with code 1")
        source = FakeSource(frames=2, error=error)

        self.assertEqual(self.play(source), [error])
        self.assertTrue(source.cleaned_up)

    def test_player_reports_stopped_when_after_runs(self) -> None:
        voice = synthetic_listener.FakeVoice()
        finished = threading.Event()
        playing_in_after: list[bool] = []

        def after(error: Exception | None) -> None:
            playing_in_after.append(voice.is_playing())
            finished.set()

        voice.play(FakeSource(frames=1), after=after)
        self.assertTrue(finished.wait(2))
        self.assertEqual(playing_in_after, [False])

    def test_finished_source_reports_no_error(self) -> None:
        source = FakeSource(frames=3)

        self.assertEqual(self.play(source), [None])
        self.assertEqual(source.frames, 0)


class LyricsResultLogTests(unittest.TestCase):
    def log_for(self, lyrics: str | None, source: str | None, description: str):
        track = SimpleNamespace(title="Song", lyrics=lyrics, lyrics_source=source)
        with self.assertLogs("music-bot", level="INFO") as logs:
            synthetic_listener.logger.info("marker")
            asyncio.run(
                synthetic_listener.log_lyrics_result(1, None, track, description)
            )
        return logs.output[1:]

    def test_found_lyrics_are_logged(self) -> None:
        output = self.log_for("a\nb\nc", "LRCLIB", "a\nb\nc")

        self.assertEqual(len(output), 1)
        self.assertIn("found=yes source=LRCLIB lines=3 title=Song", output[0])

    def test_missing_lyrics_are_logged(self) -> None:
        output = self.log_for(None, None, "미제공")

        self.assertIn("found=no source=- lines=0 title=Song", output[0])

    def test_searching_placeholder_is_not_logged(self) -> None:
        self.assertEqual(
            self.log_for(None, None, synthetic_listener.LYRICS_SEARCHING), []
        )


if __name__ == "__main__":
    unittest.main()
